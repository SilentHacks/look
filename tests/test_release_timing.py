"""Release diagnostics stay bounded/private and detect native GIL stalls."""
import ctypes
import gc
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
import weakref
from unittest.mock import patch

from hermes_gaze.release_timing import ReleaseTimings


class ReleaseTimingTests(unittest.TestCase):
    def test_only_bounded_numeric_stages_survive(self):
        timings = ReleaseTimings()
        self.addCleanup(timings.stop)
        for _ in range(12):
            trace = timings.begin({"keyup_received": 0, "evidence_frozen": 12.5,
                                   "cursor_controls_ms": 3.25, "noisy_discovery_ms": 2,
                                   "noisy_actions_ms": True, "cursor_blocks_ms": -1,
                                   "noisy_candidates_ms": float("inf"),
                                   "intent_sent": float("nan"), "evidence_start": "secret",
                                   "audio": "secret", "page_url": "secret"})
            trace.mark("record_stop")
            first = trace.snapshot()["python_ms"]["record_stop"]
            trace.mark("record_stop")
            self.assertEqual(trace.snapshot()["python_ms"]["record_stop"], first)
        state = timings.snapshot()
        self.assertEqual([turn["turn"] for turn in state["turns"]], list(range(5, 13)))
        self.assertEqual(state["turns"][-1]["browser_ms"],
                         {"keyup_received": 0, "evidence_frozen": 12.5,
                          "cursor_controls_ms": 3.25, "noisy_discovery_ms": 2})
        self.assertIsNone(timings.get(1))
        self.assertNotIn("secret", str(state))

    def test_watchdog_names_blocked_stage_and_samples_stacks_without_payloads(self):
        timings = ReleaseTimings()
        self.addCleanup(timings.stop)
        trace = timings.begin()
        release, entered = threading.Event(), threading.Event()

        def blocked_native_stop():
            audio = b"PRIVATE-PAYLOAD"
            transcript = "PRIVATE-PAYLOAD"
            gaze = ["PRIVATE-PAYLOAD"]
            trace.mark("stream_stop_start")
            entered.set()
            release.wait(3)

        worker = threading.Thread(target=blocked_native_stop)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            deadline = time.monotonic() + 2
            while trace.snapshot()["slow_release"] is None and time.monotonic() < deadline:
                time.sleep(.01)
            sample = trace.snapshot()["slow_release"]
            self.assertIsNotNone(sample)
            self.assertEqual(sample["after_stage"], "stream_stop_start")
            self.assertGreaterEqual(sample["sampled_ms"], 500)
            stacks = {thread["thread_id"]: thread["stack"] for thread in sample["threads"]}
            self.assertIn("blocked_native_stop", [frame["function"] for frame in stacks[worker.ident]])
            self.assertNotIn("PRIVATE-PAYLOAD", str(sample))
            self.assertTrue(all(set(frame) == {"file", "function", "line"}
                                for stack in stacks.values() for frame in stack))
            trace.mark("stream_stopped")
            time.sleep(.04)
            self.assertEqual(trace.snapshot()["slow_release"], sample, "watchdog must sample only once")
        finally:
            release.set()
            worker.join(3)
            trace.finish()

    @unittest.skipUnless(os.name == "posix", "uses POSIX usleep without releasing the GIL")
    def test_heartbeat_retains_native_stall_even_when_turn_finishes_first(self):
        timings = ReleaseTimings()
        trace = timings.begin()
        self.addCleanup(timings.stop)
        time.sleep(.05)
        native = ctypes.PyDLL(None).usleep
        native.argtypes = [ctypes.c_uint]
        native(150000)
        trace.finish()
        time.sleep(.05)
        self.assertGreaterEqual(trace.snapshot()["heartbeat_max_gap_ms"], 140)

    def test_worker_retires_when_idle_and_can_stop_and_restart(self):
        timings = ReleaseTimings()
        self.addCleanup(timings.stop)
        self.assertIsNone(timings.thread)
        first = timings.begin()
        worker = timings.thread
        second = timings.begin()
        self.assertIs(timings.thread, worker)
        first.finish()
        second.finish()
        worker.join(1)
        self.assertFalse(worker.is_alive(), "finished releases retained a heartbeat")
        timings.begin()
        worker = timings.thread
        timings.stop()
        timings.stop()
        self.assertFalse(worker.is_alive())
        timings.begin()
        self.assertIsNot(timings.thread, worker)

    def test_worker_does_not_retain_abandoned_collector(self):
        timings = ReleaseTimings()
        reference = weakref.ref(timings)
        timings.begin()
        worker = timings.thread
        del timings
        gc.collect()
        worker.join(1)
        self.assertIsNone(reference())
        self.assertFalse(worker.is_alive())

    def test_disconnect_and_unload_stop_unfinished_release(self):
        from hermes_gaze.browser import cdp_bridge
        from hermes_gaze import voice_turns
        from tests.test_voice_turns import Host

        timings = ReleaseTimings()
        self.addCleanup(timings.stop)
        session = cdp_bridge.GazeSession("http://127.0.0.1:1")
        self.addCleanup(session.close)
        turns = voice_turns.VoiceTurns(Host(), session)
        with patch.object(voice_turns, "TIMINGS", timings), patch.object(cdp_bridge, "TIMINGS", timings):
            turns.bind(session_key="key", session_id="session")
            timings.begin()
            worker = timings.thread
            turns.bind("disconnect", session_key="key", session_id="session")
            self.assertFalse(worker.is_alive())
            timings.begin()
            worker = timings.thread
            session.close()
            self.assertFalse(worker.is_alive())
            turns.close()

    def test_module_reload_retires_worker_and_prewarm_does_not_start_one(self):
        # Use an isolated module so imported singleton references in other tests stay valid.
        spec = importlib.util.spec_from_file_location("release_timing_reload", Path(__file__).parents[1] / "release_timing.py")
        module = importlib.util.module_from_spec(spec)
        for _ in range(3):
            spec.loader.exec_module(module)
            self.addCleanup(module.TIMINGS.stop)
            module.TIMINGS.begin()
            worker = module.TIMINGS.thread
            spec.loader.exec_module(module)
            self.assertFalse(worker.is_alive())
            self.assertIsNone(module.TIMINGS.thread)
        script = """import tests, threading
from unittest.mock import patch
from hermes_gaze import voice
with patch.object(voice, 'apple_silicon_mac', return_value=False), patch.object(
        voice, 'prepare', side_effect=voice.AssetsMissing('empty test cache')):
    voice.prewarm()
    for thread in threading.enumerate():
        if thread.name == 'gaze-asr-prewarm':
            thread.join(2)
assert not any(t.name == 'gaze-timing' for t in threading.enumerate())
"""
        subprocess.run([sys.executable, "-c", script], check=True, timeout=5)
