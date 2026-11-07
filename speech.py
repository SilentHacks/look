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

MODEL_REPO = "gradium/phonon-31m-en"
MODEL_REVISION = "8c64b55ec301728e2d1695bfea87a08a267d0c2d"
VOICE_REPO = "gradium/phonon-voices"
VOICE_REVISION = "0ee17205f254b5abc43b266c8a0f215565c352f7"
MODEL_FILES = ("config.json", "tokenizer.json", "model.q8.gguf", "default-voice.safetensors")


def asset_root():
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hermes-gaze" / "phonon"


def setup(voice="Russell"):
    """Explicit setup only: fetch immutable model and selected English voice assets."""
    from huggingface_hub import hf_hub_download, snapshot_download

    root = asset_root()
    model = root / MODEL_REVISION
    snapshot_download(MODEL_REPO, revision=MODEL_REVISION,
                      allow_patterns=[*MODEL_FILES, "README.md", "LICENSE*"], local_dir=model)
    catalog = root / VOICE_REVISION
    manifest = hf_hub_download(VOICE_REPO, "voices.jsonl", revision=VOICE_REVISION, local_dir=catalog)
    records = [json.loads(line) for line in Path(manifest).read_text().splitlines() if line.strip()]
    selected = next((r for r in records if voice.casefold() in
                     (r["name"].casefold(), r["voice_id"].casefold()) and r["language"] == "en"), None)
    if selected is None:
        raise ValueError(f"Unknown English catalogue voice: {voice}")
    hf_hub_download(VOICE_REPO, selected["filename"], revision=VOICE_REVISION, local_dir=catalog)
    hf_hub_download(VOICE_REPO, "README.md", revision=VOICE_REVISION, local_dir=catalog)
    print(f"Phonon ready offline: {model}; voice {selected['name']}")


class SpeechPlayback:
    """Access only from the single inbox speech worker; no device at construction."""

    def __init__(self):
        self.model = None

    def load(self, voice):
        root = asset_root()
        model_dir, catalog_dir = root / MODEL_REVISION, root / VOICE_REVISION
        for name in MODEL_FILES:
            if not (model_dir / name).is_file():
                raise FileNotFoundError("Phonon assets missing; run scripts/setup_speech.py")
        # Only register downloaded embeddings. No hf:// URI can reach the runtime.
        records = [json.loads(line) for line in (catalog_dir / "voices.jsonl").read_text().splitlines()
                   if line.strip()]
        selected = next((r for r in records if voice.casefold() in
                         (r["name"].casefold(), r["voice_id"].casefold()) and r["language"] == "en"), None)
        if selected is None or not (catalog_dir / selected["filename"]).is_file():
            raise FileNotFoundError(f"Phonon voice {voice} missing; run scripts/setup_speech.py --voice {voice}")
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
            except Exception as exc:
                stack.close()  # Stop native producers before selecting the fallback.
                if not cancel.is_set():
                    self.say(text, cancel, report, str(exc))
                return
            if cancel.is_set():
                return
            report("phonon", f"Reading with Phonon · {voice}.", "")
            output.start()
            try:
                # Small blocking writes bound queued audio; no full-answer PCM buffer.
                frames = max(1, stream.sample_rate // 50)
                for pcm in itertools.chain((first,), stream):
                    for start in range(0, len(pcm), frames):
                        if cancel.is_set():
                            return
                        output.write(pcm[start:start + frames])
                if not cancel.is_set():
                    output.stop()  # Drain before the inbox clears speaking state.
            finally:
                output.abort()  # Discard queued audio on cancellation/error, never drain it.

    @staticmethod
    def say(text, cancel, report, reason):
        if sys.platform != "darwin" or not os.access("/usr/bin/say", os.X_OK):
            report("unavailable", "", f"Phonon unavailable: {reason}. macOS say is unavailable too.")
            return
        report("say", "Reading with macOS say.", f"Using macOS say; Phonon unavailable: {reason}")
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
