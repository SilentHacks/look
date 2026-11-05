"""Unified FixationRingBuffer and simulated/hover pointer tracker (stdlib-only).

Supports two Stage 1 modes without requiring a webcam:
- ``hover`` (Magic Pointer mode): Low spatial uncertainty (sigma = 18 px) for snappy mouse + voice.
- ``simulated`` (Noisy Gaze mode): Configurable Gaussian noise (default sigma = 120 px) + One-Euro
  smoothing and I-VT fixation grouping to test and benchmark the Bayesian reference resolver and
  Semantic Lens under realistic webcam eye-tracking uncertainty.
"""

from __future__ import annotations

import collections
import math
import random
import threading
import time
from dataclasses import asdict, dataclass
from typing import Deque, List, Optional, Tuple


@dataclass
class FixationSample:
    """A single pointer or gaze fixation stored in both viewport and scroll-invariant document coordinates."""

    x_doc: float
    y_doc: float
    x_vp: float
    y_vp: float
    t_start: float
    t_end: float
    duration_ms: float
    sigma_x: float = 18.0
    sigma_y: float = 18.0
    source: str = "hover"

    @property
    def t_mid(self) -> float:
        return 0.5 * (self.t_start + self.t_end)

    def to_dict(self) -> dict:
        return asdict(self)


class OneEuroFilter1D:
    """Adaptive low-pass filter (Casiez et al., CHI 2012) for smoothing jitter while preserving fast saccades."""

    def __init__(self, min_cutoff: float = 1.2, beta: float = 0.015, d_cutoff: float = 1.0) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x_prev: Optional[float] = None
        self._dx_prev: float = 0.0
        self._t_prev: Optional[float] = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-4))
        return 1.0 / (1.0 + tau / max(dt, 1e-4))

    def filter(self, x: float, t: Optional[float] = None) -> float:
        now = time.time() if t is None else t
        if self._x_prev is None or self._t_prev is None:
            self._x_prev = x
            self._t_prev = now
            return x
        dt = max(now - self._t_prev, 1e-3)
        self._t_prev = now
        dx = (x - self._x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1.0 - a_d) * self._dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1.0 - a) * self._x_prev
        self._x_prev = x_hat
        self._dx_prev = dx_hat
        return x_hat


class FixationRingBuffer:
    """Thread-safe 10-second ring buffer of fixations in document coordinates."""

    def __init__(self, window_seconds: float = 10.0, max_samples: int = 300) -> None:
        self.window_seconds = window_seconds
        self._samples: Deque[FixationSample] = collections.deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def add(self, sample: FixationSample) -> None:
        with self._lock:
            # Merge with previous fixation if spatial distance is tiny (< 35 px) and gap < 220 ms
            if self._samples:
                prev = self._samples[-1]
                dist = math.hypot(sample.x_doc - prev.x_doc, sample.y_doc - prev.y_doc)
                if dist < 35.0 and (sample.t_start - prev.t_end) <= 0.22 and prev.source == sample.source:
                    w_prev = max(prev.duration_ms, 50.0)
                    w_new = max(sample.duration_ms, 50.0)
                    w_sum = w_prev + w_new
                    prev.x_doc = (prev.x_doc * w_prev + sample.x_doc * w_new) / w_sum
                    prev.y_doc = (prev.y_doc * w_prev + sample.y_doc * w_new) / w_sum
                    prev.x_vp = (prev.x_vp * w_prev + sample.x_vp * w_new) / w_sum
                    prev.y_vp = (prev.y_vp * w_prev + sample.y_vp * w_new) / w_sum
                    prev.t_end = max(prev.t_end, sample.t_end)
                    prev.duration_ms = max(prev.duration_ms + sample.duration_ms, (prev.t_end - prev.t_start) * 1000.0)
                    return
            self._samples.append(sample)
            self._prune_unlocked(sample.t_end)

    def _prune_unlocked(self, now: Optional[float] = None) -> None:
        cutoff = (time.time() if now is None else now) - self.window_seconds
        while len(self._samples) > 1 and self._samples[0].t_end < cutoff:
            self._samples.popleft()

    def snapshot(self, now: Optional[float] = None) -> List[FixationSample]:
        with self._lock:
            self._prune_unlocked(now)
            return list(self._samples)

    def latest(self) -> Optional[FixationSample]:
        with self._lock:
            return self._samples[-1] if self._samples else None

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()


class SimulatedPointerTracker:
    """Converts browser cursor / hover events into FixationSamples (exact or with Gaussian gaze noise)."""

    def __init__(
        self,
        ring_buffer: Optional[FixationRingBuffer] = None,
        mode: str = "hover",
        sigma_px: float = 120.0,
        seed: Optional[int] = None,
    ) -> None:
        self.ring_buffer = ring_buffer or FixationRingBuffer()
        self.mode = mode
        self.sigma_px = sigma_px
        self._rng = random.Random(seed)
        self._fx = OneEuroFilter1D()
        self._fy = OneEuroFilter1D()

    def record_point(
        self,
        x_vp: float,
        y_vp: float,
        scroll_x: float = 0.0,
        scroll_y: float = 0.0,
        timestamp: Optional[float] = None,
        duration_ms: float = 140.0,
        bias_offset: Tuple[float, float] = (0.0, 0.0),
    ) -> FixationSample:
        now = time.time() if timestamp is None else timestamp
        if self.mode == "simulated":
            raw_x = x_vp + self._rng.gauss(0.0, self.sigma_px)
            raw_y = y_vp + self._rng.gauss(0.0, self.sigma_px)
            filt_x = self._fx.filter(raw_x, now) - bias_offset[0]
            filt_y = self._fy.filter(raw_y, now) - bias_offset[1]
            sigma = max(self.sigma_px, 40.0)
        else:
            filt_x = x_vp - bias_offset[0]
            filt_y = y_vp - bias_offset[1]
            sigma = 24.0

        sample = FixationSample(
            x_doc=filt_x + scroll_x,
            y_doc=filt_y + scroll_y,
            x_vp=filt_x,
            y_vp=filt_y,
            t_start=now - (duration_ms / 1000.0),
            t_end=now,
            duration_ms=duration_ms,
            sigma_x=sigma,
            sigma_y=sigma,
            source=self.mode,
        )
        self.ring_buffer.add(sample)
        return sample
