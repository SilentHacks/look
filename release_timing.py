"""Memory-only stage timings and code-location stacks; never capture user data."""
from __future__ import annotations

from collections import deque
import copy
import math
import os
import sys
import threading
import time
import weakref


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
        self.stack_sample = None
        self.observed_stage = "binding_received"
        self.ui_ready = None  # Transport-owned Event, never serialized.

    def mark(self, stage):
        with self.lock:
            self.stages.setdefault(stage, round((time.monotonic() - self.started) * 1000, 2))

    def finish(self):
        with self.lock:
            self.finished = self.finished or time.monotonic()

    def snapshot(self):
        with self.lock:
            return {"turn": self.turn, "browser_ms": dict(self.browser),
                    "python_ms": dict(self.stages), "heartbeat_max_gap_ms": round(self.max_gap, 2),
                    "slow_release": copy.deepcopy(self.stack_sample)}


def _thread_stacks():
    # No traceback formatting: source lines and frame locals may contain private text.
    threads = []
    for ident, frame in sys._current_frames().items():
        stack = []
        while frame is not None and len(stack) < 64:
            code = frame.f_code
            stack.append({"file": os.path.basename(code.co_filename),
                          "function": code.co_name, "line": frame.f_lineno})
            frame = frame.f_back
        threads.append({"thread_id": ident, "stack": stack})
    return threads


class ReleaseTimings:
    def __init__(self):
        self.lock = threading.Lock()
        self.turns = deque(maxlen=8)
        self.sequence = 0
        self.thread = None
        self.stopped = threading.Event()
        self.max_gap = 0.0

    def begin(self, browser=None):
        with self.lock:
            self.sequence += 1
            trace = ReleaseTiming(self.sequence, browser)
            self.turns.append(trace)
            if self.thread is None:
                self.stopped = threading.Event()
                self.thread = threading.Thread(target=self._heartbeat,
                                               args=(weakref.ref(self), self.stopped),
                                               name="gaze-timing", daemon=True)
                self.thread.start()
            return trace

    def stop(self):
        with self.lock:
            self.stopped.set()
            thread, self.thread = self.thread, None
            for trace in self.turns:
                trace.finish()
        if thread is not None:
            thread.join()

    @staticmethod
    def _heartbeat(reference, stopped):
        last = time.monotonic()
        while not stopped.wait(.02):
            timings = reference()
            if timings is None:
                return
            now = time.monotonic()
            gap = (now - last) * 1000
            with timings.lock:
                if stopped.is_set():
                    return
                timings.max_gap = max(timings.max_gap, gap)
                active = False
                for trace in timings.turns:
                    with trace.lock:
                        end = min(now, trace.finished or now)
                        trace.max_gap = max(trace.max_gap, (end - max(last, trace.started)) * 1000)
                        if (end - trace.started >= .5 and trace.stack_sample is None):
                            trace.stack_sample = {
                                "sampled_ms": round((now - trace.started) * 1000, 2),
                                "after_stage": trace.observed_stage,
                                "current_stage": next(reversed(trace.stages)),
                                "scheduler_gap_ms": round(gap, 2),
                                "sampled_after_finish": bool(trace.finished),
                                "threads": _thread_stacks(),
                            }
                        trace.observed_stage = next(reversed(trace.stages))
                        active |= not trace.finished
                if not active:
                    timings.thread = None
                    return
            del timings  # Waiting must not retain an abandoned/replaced collector.
            last = now

    def get(self, turn):
        with self.lock:
            return next((trace for trace in self.turns if trace.turn == turn), None)

    def snapshot(self):
        with self.lock:
            return {"heartbeat_interval_ms": 20, "watchdog_threshold_ms": 500,
                    "heartbeat_max_gap_ms": round(self.max_gap, 2),
                    "turns": [trace.snapshot() for trace in self.turns]}


# importlib.reload keeps this module dictionary; retire its previous worker first.
if "TIMINGS" in globals():
    TIMINGS.stop()
TIMINGS = ReleaseTimings()
