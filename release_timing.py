"""In-memory monotonic timings only: never audio, text, URLs or identities."""
from __future__ import annotations

from collections import deque
import math
import threading
import time


class ReleaseTiming:
    def __init__(self, turn, browser):
        self.turn = turn
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.stages = {"binding_received": 0.0}
        self.browser = {}
        for key in ("keyup_received", "evidence_start", "evidence_frozen", "intent_sent"):
            value = browser.get(key) if isinstance(browser, dict) else None
            if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 60000:
                self.browser[key] = round(value, 2)
        self.max_gap = 0.0
        self.finished = False

    def mark(self, stage):
        with self.lock:
            self.stages.setdefault(stage, round((time.monotonic() - self.started) * 1000, 2))

    def finish(self):
        with self.lock:
            self.finished = self.finished or time.monotonic()

    def snapshot(self):
        with self.lock:
            return {"turn": self.turn, "browser_ms": dict(self.browser),
                    "python_ms": dict(self.stages), "heartbeat_max_gap_ms": round(self.max_gap, 2)}


class ReleaseTimings:
    def __init__(self):
        self.lock = threading.Lock()
        self.turns = deque(maxlen=8)
        self.sequence = 0
        self.thread = None
        self.max_gap = 0.0

    def start(self):
        with self.lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self._heartbeat, name="gaze-timing", daemon=True)
                self.thread.start()

    def begin(self, browser=None):
        self.start()
        with self.lock:
            self.sequence += 1
            trace = ReleaseTiming(self.sequence, browser)
            self.turns.append(trace)
            return trace

    def _heartbeat(self):
        last = time.monotonic()
        while True:
            time.sleep(.02)
            now = time.monotonic()
            gap = (now - last) * 1000
            with self.lock:
                self.max_gap = max(self.max_gap, gap)
                for trace in self.turns:
                    with trace.lock:
                        end = min(now, trace.finished or now)
                        trace.max_gap = max(trace.max_gap, (end - max(last, trace.started)) * 1000)
            last = now

    def get(self, turn):
        with self.lock:
            return next((trace for trace in self.turns if trace.turn == turn), None)

    def snapshot(self):
        with self.lock:
            return {"heartbeat_interval_ms": 20, "heartbeat_max_gap_ms": round(self.max_gap, 2),
                    "turns": [trace.snapshot() for trace in self.turns]}


TIMINGS = ReleaseTimings()
