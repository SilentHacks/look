"""Talk capture must close its device and never hand one tab another tab's audio."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hermes_gaze.microphone import Microphone


class CaptureTests(unittest.TestCase):
    def test_single_owner_release_and_wrong_tab_stop(self):
        streams = []

        class Input:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                self.closed = False
                streams.append(self)

            def start(self):
                self.callback(b"\x01\x00\x02\x00", 2,
                              SimpleNamespace(currentTime=10., inputBufferAdcTime=9.9), None)

            def stop(self):
                pass

            def abort(self):
                pass

            def close(self):
                self.closed = True

        mic = Microphone()
        self.addCleanup(mic.cancel)
        with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Input)):
            self.assertFalse(mic.start("background", lambda: "Recording cancelled: the source tab is hidden.")["ok"])
            self.assertEqual(streams, [])
            self.assertTrue(mic.start("tab-A", lambda: None)["ok"])
            self.assertFalse(mic.start("tab-B", lambda: None)["ok"])
            with self.assertRaises(RuntimeError):
                mic.stop("tab-B")
            self.assertFalse(streams[0].closed)
            audio, epoch = mic.stop("tab-A")
            self.assertEqual(audio, b"\x01\x00\x02\x00")
            self.assertTrue(streams[0].closed)
            self.assertGreater(epoch, 0)
            self.assertTrue(mic.start("tab-B", lambda: None)["ok"])
            mic.cancel("tab-A")
            self.assertFalse(streams[1].closed)
            mic.cancel("tab-B")
            self.assertTrue(streams[1].closed)
            with self.assertRaises(RuntimeError):
                mic.stop("tab-B")
            self.assertTrue(mic.start("tab-C", lambda: None)["ok"])

            def device_lost():
                raise RuntimeError("device lost")

            streams[2].stop = device_lost
            with self.assertRaisesRegex(RuntimeError, "device lost"):
                mic.stop("tab-C")
            self.assertTrue(streams[2].closed)
            self.assertEqual(mic._audio, bytearray())
