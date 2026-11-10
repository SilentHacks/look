"""Opt-in NVIDIA v3: verified local assets and one disposable, warm C-ABI worker.

No listener, microphone, runtime downloader, or host configuration changes.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request

from ..asset_cache import AssetIntegrityError, AssetsMissing, prepare, verify
from ...platform_support import apple_silicon_mac

MODEL = "nvidia/parakeet-tdt-0.6b-v3"
MODEL_FILE = "parakeet-tdt-0.6b-v3.q8_0.gguf"
PINS = json.loads(Path(__file__).with_name("parakeet_v3_runtime.json").read_text())
REQUEST_TIMEOUT = 60
_LOCK = threading.Lock()
_RUNNER = None

_LOAD_ERROR = None

def runtime_root():
    return Path.home() / "Library/Caches/Look/nemo-speech/0.3.0"


def assets(*, download=False, directory=None):
    if not apple_silicon_mac():
        raise RuntimeError("Parakeet v3 requires an Apple Silicon Mac.")
    root = Path(directory) if directory is not None else runtime_root()
    archive = root / "runtime.tar.gz"
    installed = root / PINS["directory"]
    if not archive.is_file():
        if not download:
            raise AssetsMissing("Parakeet v3 is not installed. Run /look setup.")
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as out:
            tmp = Path(out.name)
            try:
                with urllib.request.urlopen(PINS["url"], timeout=60) as response:
                    import shutil
                    shutil.copyfileobj(response, out)
                out.close()
                verify(tmp, PINS)
                tmp.replace(archive)
            finally:
                tmp.unlink(missing_ok=True)
    verify(archive, PINS)
    if not installed.exists():
        if not download:
            raise AssetsMissing("Parakeet v3 is not installed. Run /look setup.")
        # Only publish a complete tree. The vendor's notice/license files stay intact.
        with tempfile.TemporaryDirectory(dir=root) as staging:
            with tarfile.open(archive) as package:
                package.extractall(staging, filter="data")
            Path(staging, PINS["directory"]).rename(installed)
    for name, expected in PINS["files"].items():
        path = installed / name
        if not path.resolve().is_relative_to(installed.resolve()) or not path.is_file():
            raise AssetIntegrityError("Parakeet v3 runtime is incomplete or unsafe. Remove its cache and run /look setup.")
        verify(path, expected)
    model = prepare(MODEL, download=download) / MODEL_FILE
    return installed, model


class Runner:
    """Serial IPC bounds native hangs/crashes; a failed request is never retried here."""

    def __init__(self, runtime, model):
        self.lock = threading.Lock()
        self.buffer = b""
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(Path(__file__).with_name("parakeet_v3_worker.py")),
             str(runtime / "lib/libnemo_speech_asr_c.dylib"), str(model)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={k: v for k, v in os.environ.items()
                 if not k.startswith(("NEMO_SPEECH_", "DYLD_"))},
        )
        try:
            self._reply(time.monotonic() + 90)
        except BaseException:
            self.close()
            raise
        atexit.register(self.close)

    @property
    def ready(self):
        return self.process.poll() is None

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()

    def _write(self, data, deadline):
        fd = self.process.stdin.fileno()
        os.set_blocking(fd, False)
        data = memoryview(data)
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                raise TimeoutError("Parakeet v3 timed out.")
            try:
                written = os.write(fd, data)
            except BlockingIOError:
                continue
            data = data[written:]

    def _reply(self, deadline):
        os.set_blocking(self.process.stdout.fileno(), False)
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError("Parakeet v3 timed out.")
            try:
                chunk = os.read(self.process.stdout.fileno(), 65536)
            except BlockingIOError:
                continue
            if not chunk:
                raise RuntimeError("Parakeet v3 worker stopped.")
            self.buffer += chunk
            if len(self.buffer) > 1024 * 1024:
                raise RuntimeError("Parakeet v3 returned too much text.")
        line, self.buffer = self.buffer.split(b"\n", 1)
        result = json.loads(line)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    def transcribe(self, audio, sample_rate=16000, epoch=0.0):
        import numpy as np
        audio = np.ascontiguousarray(audio, dtype="<f4")
        if audio.ndim != 1 or not 8000 <= sample_rate <= 96000 or len(audio) > 30 * sample_rate:
            raise ValueError("Parakeet v3 accepts up to 30 seconds of mono audio at 8–96 kHz.")
        with self.lock:
            try:
                deadline = time.monotonic() + REQUEST_TIMEOUT
                self._write(struct.pack("<II", len(audio), sample_rate), deadline)
                self._write(memoryview(audio).cast("B"), deadline)
                result = self._reply(deadline)
            except BaseException:
                self.close()
                raise
        words = result["words"]
        for word in words:
            start, end = word["start"], word["end"]
            if not 0 <= start <= end <= len(audio) / sample_rate + 0.1:
                self.close()
                raise ValueError("Parakeet v3 returned invalid word times.")
            word["start"], word["end"] = start + epoch, end + epoch
        return result["text"], words


def get_runner(*, download=False):
    global _RUNNER, _LOAD_ERROR
    with _LOCK:
        if not download:
            if _LOAD_ERROR is not None:
                raise _LOAD_ERROR
            if _RUNNER is not None and not _RUNNER.ready:
                raise RuntimeError("Parakeet v3 stopped. Run /look setup to restart it.")
        if _RUNNER is None or not _RUNNER.ready:
            try:
                _RUNNER = Runner(*assets(download=download))
                _LOAD_ERROR = None
            except Exception as exc:
                _LOAD_ERROR = exc
                raise
        return _RUNNER


def ready():
    return _RUNNER is not None and _RUNNER.ready
