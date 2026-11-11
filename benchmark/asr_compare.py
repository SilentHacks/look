"""Offline same-audio comparison. Explicit --fetch downloads public LibriSpeech data.

Run via the tests package shell, without executing the plugin registration:
python -c 'import tests; from look.benchmark.asr_compare import main; main()' --help
Benchmark-only dependencies: pyarrow, soundfile. Never opens an audio device.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import resource
import statistics
import time
import urllib.request

REVISION = "5be91486e11a2d616f4ec5db8d3fd248585ac07a"
URL = f"https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy/resolve/{REVISION}/clean/validation-00000-of-00001.parquet"
SHA256 = "4e69a06fa5edc90921e5e7e39a7084881f8b3ed9c805c574f4f39c6fde27c603"


def edits(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, a in enumerate(reference, 1):
        current = [i]
        for j, b in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def words(text):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--backend", choices=("v3", "whisper"), required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    import pyarrow.parquet as pq
    import soundfile as sf
    import numpy as np
    from ..audio import voice
    from ..audio.asr.parakeet_v3 import Runner
    if args.fetch:
        args.fixtures.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL, timeout=60) as source:
            args.fixtures.write_bytes(source.read())
    if hashlib.sha256(args.fixtures.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Reference fixture checksum changed")
    rows = pq.read_table(args.fixtures).to_pylist()[:args.count]
    clips = []
    for row in rows:
        audio, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
        assert rate == 16000 and audio.ndim == 1 and len(audio) <= 30 * rate
        # Identical Look gain normalization for every backend.
        peak = float(np.max(np.abs(audio)))
        if 0.002 < peak < 0.65:
            audio = np.clip(audio * (0.85 / peak), -1, 1).astype(np.float32)
        clips.append((row, audio, rate))
    load_start = time.monotonic()
    if args.backend == "v3":
        if args.runtime is None or args.model is None:
            parser.error("v3 requires --runtime and --model")
        runner = Runner(args.runtime, args.model)
        transcribe = lambda audio, rate: runner.transcribe(audio, rate, 1700000000.0)
        pid = runner.process.pid
    else:
        runner = voice.get_whisper_model()
        warm_segments, _ = runner.transcribe(np.zeros(16000, dtype=np.float32))
        list(warm_segments)
        def transcribe(audio, rate):
            segments, _ = runner.transcribe(audio, word_timestamps=True, language="en", condition_on_previous_text=False)
            segments = list(segments)
            return " ".join(s.text.strip() for s in segments), [
                {"word": w.word, "start": w.start + 1700000000.0, "end": w.end + 1700000000.0}
                for s in segments for w in s.words or []]
        pid = None
    load_seconds = time.monotonic() - load_start
    results = []
    try:
        for repeat in range(args.repetitions):
            for row, audio, rate in clips:
                started = time.monotonic()
                text, timestamps = transcribe(audio, rate)
                seconds = time.monotonic() - started
                assert timestamps and all(np.isfinite(w["start"]) and w["start"] >= 1700000000 for w in timestamps)
                reference, hypothesis = words(row["text"]), words(text)
                results.append(dict(id=row["id"], speaker=row["speaker_id"], repeat=repeat,
                    duration=len(audio) / rate, seconds=seconds, reference=row["text"], text=text,
                    errors=edits(reference, hypothesis), reference_words=len(reference), words=timestamps,
                    audio_sha256=hashlib.sha256(row["audio"]["bytes"]).hexdigest()))
        rss = None
        if pid:
            runner.close()
            rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        first = [r for r in results if r["repeat"] == 0]
        report = dict(backend=args.backend, hardware=platform.platform(), fixture_url=URL,
            fixture_sha256=hashlib.sha256(args.fixtures.read_bytes()).hexdigest(),
            samples=len(clips), repetitions=args.repetitions, load_and_silent_warmup_seconds=load_seconds,
            first_request_seconds=results[0]["seconds"],
            repeated_median_seconds=statistics.median(r["seconds"] for r in results if r["repeat"] > 0),
            wer=sum(r["errors"] for r in first) / sum(r["reference_words"] for r in first),
            worker_peak_rss_bytes=rss,
            parent_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            results=results)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    finally:
        if args.backend == "v3":
            runner.close()


if __name__ == "__main__":
    main()
