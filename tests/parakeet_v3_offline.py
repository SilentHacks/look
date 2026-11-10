"""Explicit offline native probe; requires already-prepared v3 and public WAV input.

python -m tests.parakeet_v3_offline --audio /path/to/public.wav
Never opens a device. Run under sandbox-exec with network denied on macOS.
"""
import argparse
import json
import threading
import time

import numpy as np
from hermes_gaze.audio import voice
from hermes_gaze.audio.asr import parakeet_v3 as v3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True)
    args = parser.parse_args()
    from pathlib import Path
    audio = voice.decode_audio_to_float32(Path(args.audio).read_bytes())
    started = time.monotonic()
    runner = v3.get_runner()
    load = time.monotonic() - started
    assert v3.ready() and v3.get_runner() is runner
    results = {"cache_load_and_warmup_seconds": load}
    try:
        text, words = runner.transcribe(audio, epoch=1700000000.0)
        assert text and words and all(1700000000 <= w["start"] <= w["end"] for w in words)
        results["text"], results["epoch_first_word"] = text, words[0]
        # Native silence, 8 kHz resampling and the real 30-second capture ceiling.
        assert runner.transcribe(np.zeros(16000, dtype=np.float32)) == ("", [])
        assert runner.transcribe(audio[::2], 8000)[0]
        long_audio = np.tile(audio, int(np.ceil(480000 / len(audio))))[:480000]
        long_text, long_words = runner.transcribe(long_audio)
        assert long_text and all(0 <= w["start"] <= w["end"] <= 30.1 for w in long_words)
        try:
            runner.transcribe(np.zeros(480001, dtype=np.float32))
        except ValueError:
            pass
        else:
            raise AssertionError("Over-limit audio accepted")
        results["silence_8khz_30sec_bounds"] = "passed"
        errors = []
        entered = threading.Event()
        def recognize():
            entered.set()
            try:
                runner.transcribe(long_audio)
            except Exception as exc:
                errors.append(type(exc).__name__)
        worker = threading.Thread(target=recognize)
        worker.start()
        assert entered.wait(1)
        time.sleep(0.02)
        runner.close()
        worker.join(2)
        assert not worker.is_alive() and errors and not v3.ready()
        try:
            v3.get_runner()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Failed native work was restarted implicitly")
        results["forced_native_exit"] = errors
        # Explicit setup can restart from verified caches while still offline.
        replacement = v3.get_runner(download=True)
        assert replacement is not runner and replacement.transcribe(audio)[0]
        replacement.close()
        results["explicit_cached_restart"] = "passed"
    finally:
        runner.close()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
