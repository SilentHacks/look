"""Bounded native microphone capture; audio never enters a website origin."""
from __future__ import annotations

import threading
import time

from .voice import MAX_AUDIO_BYTES


class Microphone:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stream = None
        self._owner = None
        self._audio = bytearray()
        self._epoch = 0.
        self._error = ""
        self._generation = 0

    def start(self, owner: str, foreground, sample_rate: int = 16000) -> dict:
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return {"ok": False, "error": "Microphone is already in use"}
            if not foreground():
                return {"ok": False, "error": "Only the focused Chrome tab can record"}
            self._audio = bytearray()
            self._error = ""
            self._epoch = 0.
            first = threading.Event()
            started = time.monotonic()

            def receive(data, frames, clock, status):
                if not self._epoch:
                    self._epoch = time.time() - (clock.currentTime - clock.inputBufferAdcTime)
                if status:
                    self._error = str(status)
                if len(self._audio) + len(data) <= MAX_AUDIO_BYTES:
                    self._audio.extend(data)
                else:
                    self._error = "Recording exceeds maximum size"
                first.set()
            stream = sd.RawInputStream(samplerate=sample_rate, channels=1, dtype="int16", callback=receive)
            try:
                stream.start()
                if not first.wait(2):
                    raise RuntimeError("Microphone produced no audio")
            except Exception:
                stream.close()
                raise
            self._stream, self._owner = stream, owner
            self._generation += 1
            generation = self._generation

        def watch():
            # ponytail: focus checked every 100ms; native OS key capture only if this proves too slow.
            while True:
                time.sleep(.1)
                with self._lock:
                    if self._stream is None or self._generation != generation:
                        return
                try:
                    live = foreground()
                except Exception:
                    live = False
                if not live:
                    with self._lock:
                        if self._generation == generation:
                            self.cancel(owner)
                    return

        threading.Thread(target=watch, name="hermes-gaze-mic", daemon=True).start()
        return {"ok": True, "ready_ms": round((time.monotonic() - started) * 1000)}

    def stop(self, owner: str) -> tuple[bytes, float]:
        with self._lock:
            if self._stream is None or self._owner != owner:
                raise RuntimeError("Recording was cancelled or belongs to another tab")
            stream, self._stream = self._stream, None
            self._owner = None
            try:
                stream.stop()
                audio = bytes(self._audio)
            finally:
                self._audio.clear()
                stream.close()
            if self._error:
                raise RuntimeError(self._error)
            return audio, self._epoch

    def cancel(self, owner: str | None = None) -> None:
        with self._lock:
            if self._stream is not None and (owner is None or owner == self._owner):
                stream, self._stream = self._stream, None
                self._owner = None
                try:
                    stream.abort()
                finally:
                    self._audio.clear()
                    stream.close()
