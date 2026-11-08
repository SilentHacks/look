"""Release diagnostics stay bounded/private and detect native GIL stalls."""
import ctypes
import os
import time
import unittest
from unittest.mock import patch

from hermes_gaze.release_timing import ReleaseTimings


class ReleaseTimingTests(unittest.TestCase):
    def test_only_bounded_numeric_stages_survive(self):
        timings = ReleaseTimings()
        with patch.object(timings, "start"):
            for _ in range(12):
                trace = timings.begin({"keyup_received": 0, "evidence_frozen": 12.5,
                                       "intent_sent": float("nan"), "evidence_start": "secret",
                                       "audio": "secret", "page_url": "secret"})
                trace.mark("record_stop")
                first = trace.snapshot()["python_ms"]["record_stop"]
                trace.mark("record_stop")
                self.assertEqual(trace.snapshot()["python_ms"]["record_stop"], first)
        state = timings.snapshot()
        self.assertEqual([turn["turn"] for turn in state["turns"]], list(range(5, 13)))
        self.assertEqual(state["turns"][-1]["browser_ms"], {"keyup_received": 0, "evidence_frozen": 12.5})
        self.assertIsNone(timings.get(1))
        self.assertNotIn("secret", str(state))

    @unittest.skipUnless(os.name == "posix", "uses POSIX usleep without releasing the GIL")
    def test_heartbeat_retains_native_stall_even_when_turn_finishes_first(self):
        timings = ReleaseTimings()
        trace = timings.begin()
        time.sleep(.05)
        native = ctypes.PyDLL(None).usleep
        native.argtypes = [ctypes.c_uint]
        native(150000)
        trace.finish()
        time.sleep(.05)
        self.assertGreaterEqual(trace.snapshot()["heartbeat_max_gap_ms"], 140)
