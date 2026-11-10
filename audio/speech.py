"""Local-only Phonon setup and worker-owned, cancellable native playback."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

from .asset_cache import ASSETS, AssetIntegrityError, prepare

MODEL_REPO = "gradium/phonon-31m-en"
MODEL_REVISION = "8c64b55ec301728e2d1695bfea87a08a267d0c2d"
VOICE_REPO = "gradium/phonon-voices"
VOICE_REVISION = "0ee17205f254b5abc43b266c8a0f215565c352f7"
MODEL_FILES = ("config.json", "tokenizer.json", "model.q8.gguf", "default-voice.safetensors")


def asset_root():
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hermes-gaze" / "phonon"


def setup(voice="Russell"):
    """Explicit setup only: fetch immutable model and selected English voice assets."""
    root = asset_root()
    model = prepare(MODEL_REPO, download=True, local_dir=root / MODEL_REVISION)
    catalog = root / VOICE_REVISION
    prepare(VOICE_REPO, download=True, names=["voices.jsonl", "README.md"], local_dir=catalog)
    selected = _voice(catalog, voice)
    prepare(VOICE_REPO, download=True, names=[selected["filename"]], local_dir=catalog)
    print(f"Read aloud is ready offline.\nVoice: {selected['name']}\nModel files: {model}")


def _voice(catalog, voice):
    records = [json.loads(line) for line in (catalog / "voices.jsonl").read_text().splitlines() if line.strip()]
    selected = next((r for r in records if voice.casefold() in
                     (r["name"].casefold(), r["voice_id"].casefold()) and r["language"] == "en"), None)
    if selected is None or selected["filename"] not in ASSETS[VOICE_REPO]["files"]:
        raise ValueError(f"Unknown pinned English catalogue voice: {voice}")
    return selected


class SpeechPlayback:
    """Access only from the single inbox speech worker; no device at construction."""

    def __init__(self):
        self.model = None

    def load(self, voice):
        root = asset_root()
        model_dir, catalog_dir = root / MODEL_REVISION, root / VOICE_REVISION
        prepare(MODEL_REPO, names=MODEL_FILES, local_dir=model_dir)
        prepare(VOICE_REPO, names=["voices.jsonl"], local_dir=catalog_dir)
        selected = _voice(catalog_dir, voice)
        prepare(VOICE_REPO, names=[selected["filename"]], local_dir=catalog_dir)
        if self.model is None:
            import ptts
            model = ptts.TTS(str(model_dir), lang="en", quant="q8", voice_catalog=str(catalog_dir))
            self.model = model
        self.model.add_voice(voice, str(catalog_dir / selected["filename"]))
        return self.model

    def play(self, text, voice, cancel, report):
        # Preflight includes first PCM and output-device opening, before any audio.
        with ExitStack() as stack:
            try:
                model = self.load(voice)
                if cancel.is_set():
                    return
                stream = stack.enter_context(model.stream(text, voice=voice))
                first = next(stream)
                if cancel.is_set():
                    return
                import sounddevice as sd
                output = sd.OutputStream(samplerate=stream.sample_rate, channels=1,
                                         dtype="float32", blocksize=max(1, stream.sample_rate // 50),
                                         latency="low")
                stack.callback(output.close)
                if cancel.is_set():
                    return
                output.start()  # Device-start errors still precede the first audio write.
                stack.callback(output.abort)
            except AssetIntegrityError as exc:
                report("unavailable", "", str(exc))
                return
            except Exception as exc:
                stack.close()  # Stop native producers before selecting the fallback.
                if not cancel.is_set():
                    self.say(text, cancel, report, str(exc))
                return
            if cancel.is_set():
                return
            report("phonon", f"Reading with Phonon · {voice}.", "")
            # Small blocking writes bound queued audio; no full-answer PCM buffer.
            frames = max(1, stream.sample_rate // 50)
            for pcm in itertools.chain((first,), stream):
                for start in range(0, len(pcm), frames):
                    if cancel.is_set():
                        return
                    output.write(pcm[start:start + frames])
            if not cancel.is_set():
                output.stop()  # Drain before the inbox clears speaking state.

    @staticmethod
    def say(text, cancel, report, reason):
        if sys.platform != "darwin" or not os.access("/usr/bin/say", os.X_OK):
            report("unavailable", "", f"Phonon unavailable: {reason}. macOS say is unavailable too.")
            return
        report("say", "Reading with macOS say.", f"Using macOS say because Phonon is unavailable: {reason}")
        if cancel.is_set():
            return
        process = subprocess.Popen(["/usr/bin/say", "-f", "-"], stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   text=True, encoding="utf-8")
        try:
            first = True
            while not cancel.is_set():
                try:
                    process.communicate(text if first else None, timeout=0.02)
                    if process.returncode:
                        raise RuntimeError(f"macOS say exited with status {process.returncode}")
                    return
                except subprocess.TimeoutExpired:
                    first = False
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download pinned offline Phonon read-aloud assets (no playback)")
    parser.add_argument("--voice", default="Russell")
    setup(parser.parse_args().voice)
