"""Bounded native microphone capture; audio never enters a website origin."""
from __future__ import annotations

import array
import math
import threading
import time

from .voice import MAX_AUDIO_BYTES


class Microphone:
    MAX_RECORDING_SECONDS = 30.

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stream = None
        self._owner = None
        self._audio = bytearray()
        self._epoch = 0.
        self._error = ""
        self._generation = 0
        self._level = 0.
        self._accepting = False

    def start(self, owner: str, check_loss, sample_rate: int = 16000, on_cancel=None, on_warning=None,
              on_level=None) -> dict:
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return {"ok": False, "error": "Microphone is already in use"}
            try:
                loss = check_loss()
            except Exception:
                return {"ok": False, "error": "Could not check the focused Chrome tab; try again"}
            if loss:
                return {"ok": False, "error": loss}
            self._audio = bytearray()
            self._error = ""
            self._epoch = 0.
            self._accepting = True
            first = threading.Event()
            started = time.monotonic()

            def receive(data, frames, clock, status):
                if not self._accepting:
                    return
                if not self._epoch:
                    self._epoch = time.time() - (clock.currentTime - clock.inputBufferAdcTime)
                if status:
                    self._error = str(status)
                if on_level is not None:
                    # Speech RMS sits near .03 to .1 of full scale; sqrt spreads that for the bars.
                    samples = array.array("h", bytes(data)[:len(data) & ~1])[::4]
                    if samples:
                        rms = math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768
                        self._level = min(1., math.sqrt(rms) * 2.6)
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

        foreground_loss = ""

        def check_foreground():
            nonlocal foreground_loss
            while True:
                with self._lock:
                    if self._stream is None or self._generation != generation:
                        return
                try:
                    loss = check_loss()
                except Exception:
                    loss = None  # A slow/broken CDP read is unknown, not proof of loss.
                with self._lock:
                    if self._generation != generation or self._stream is None:
                        return
                    if loss:
                        foreground_loss = loss
                        return
                time.sleep(.1)

        def watch():
            # Never wait for Chrome here: a stalled renderer cannot extend the native cap.
            warned = False
            while True:
                time.sleep(.1)
                with self._lock:
                    if self._stream is None or self._generation != generation:
                        return
                    remaining = self.MAX_RECORDING_SECONDS - (time.monotonic() - started)
                    reason = (f"Recording cancelled: {self.MAX_RECORDING_SECONDS:g}-second limit reached."
                              if remaining <= 0 else
                              f"Recording cancelled: microphone error ({self._error})." if self._error else
                              foreground_loss)
                    if reason:
                        self.cancel(owner)
                if reason:
                    if on_cancel:
                        on_cancel(reason)
                    return
                if remaining <= 5 and not warned:
                    warned = True
                    if on_warning:
                        on_warning(5)

        def levels():
            while True:
                time.sleep(.04)
                with self._lock:
                    if self._stream is None or self._generation != generation:
                        return
                    level = self._level
                try:
                    on_level(level)
                except Exception:
                    return  # The waveform is decoration; capture never depends on it.

        if on_level is not None:
            threading.Thread(target=levels, name="hermes-gaze-mic-level", daemon=True).start()
        threading.Thread(target=check_foreground, name="hermes-gaze-mic-focus", daemon=True).start()
        threading.Thread(target=watch, name="hermes-gaze-mic", daemon=True).start()
        return {"ok": True, "ready_ms": round((time.monotonic() - started) * 1000)}

    def stop(self, owner: str, timing=None, before_stop=None) -> tuple[bytes, float]:
        with self._lock:
            if self._stream is None or self._owner != owner:
                raise RuntimeError("Recording was cancelled or belongs to another tab")
            stream, self._stream = self._stream, None
            self._owner = None
            self._accepting = False
            if timing is not None:
                timing.mark("record_stop")
            audio = bytes(self._audio)
            try:
                if before_stop is not None:
                    before_stop()
            finally:
                try:
                    if timing is not None:
                        timing.mark("stream_stop_start")
                    stream.stop()
                    if timing is not None:
                        timing.mark("stream_stopped")
                finally:
                    self._audio.clear()
                    if timing is not None:
                        timing.mark("mic_close_start")
                    stream.close()
                    if timing is not None:
                        timing.mark("mic_closed")
            if self._error:
                raise RuntimeError(self._error)
            return audio, self._epoch

    def cancel(self, owner: str | None = None) -> None:
        with self._lock:
            if self._stream is not None and (owner is None or owner == self._owner):
                stream, self._stream = self._stream, None
                self._accepting = False
                self._owner = None
                try:
                    stream.abort()
                finally:
                    self._audio.clear()
                    stream.close()
