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

    def test_release_seals_pcm_before_ui_and_closes_even_if_ui_fails(self):
        streams = []

        class Input:
            def __init__(self, **kwargs):
                self.callback, self.closed = kwargs["callback"], False
                streams.append(self)

            def start(self):
                self.callback(b"\x01\x00", 1, SimpleNamespace(currentTime=1., inputBufferAdcTime=1.), None)

            def stop(self):
                pass

            def close(self):
                self.closed = True

        mic = Microphone()
        with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Input)):
            mic.start("A", lambda: None)
            def ui():
                self.assertFalse(streams[-1].closed)
                streams[-1].callback(b"\x02\x00", 1, None, "late device error")
            audio, _ = mic.stop("A", before_stop=ui)
            self.assertEqual(audio, b"\x01\x00")
            self.assertTrue(streams[-1].closed)
            mic.start("A", lambda: None)
            def failed_ui():
                raise RuntimeError("renderer unavailable")
            with self.assertRaisesRegex(RuntimeError, "renderer unavailable"):
                mic.stop("A", before_stop=failed_ui)
            self.assertTrue(streams[-1].closed)
            self.assertEqual(mic._audio, bytearray())
