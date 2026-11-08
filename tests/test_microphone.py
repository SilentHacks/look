"""Talk capture must close its device and never hand one tab another tab's audio."""
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hermes_gaze.microphone import Microphone
from tests.test_recording_hold import Input


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

    def test_release_includes_callback_already_writing_pcm(self):
        for status in (None, "input overflow"):
            with self.subTest(status=status):
                entered, resume, callback_done, published = (threading.Event() for _ in range(4))
                errors, result = [], []

                class Tail(bytes):
                    def __len__(self):
                        entered.set()
                        if not resume.wait(2):
                            raise TimeoutError("tail callback was not released")
                        return super().__len__()

                class Device(Input):
                    def stop(self):
                        if not callback_done.wait(2):
                            raise TimeoutError("tail callback did not finish")

                mic = Microphone()
                with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Device)):
                    mic.start("A", lambda: None)
                    stream = mic._stream

                    def callback():
                        try:
                            stream.callback(Tail(b"\x02\x00"), 1, None, status)
                        except Exception as exc:
                            errors.append(exc)
                        finally:
                            callback_done.set()

                    def stop():
                        try:
                            result.append(mic.stop("A", before_stop=published.set))
                        except Exception as exc:
                            errors.append(exc)

                    writer = threading.Thread(target=callback, daemon=True)
                    stopper = threading.Thread(target=stop, daemon=True)
                    writer.start()
                    try:
                        self.assertTrue(entered.wait(1))
                        stopper.start()
                        self.assertFalse(published.wait(.05), "UI published before an admitted buffer was sealed")
                    finally:
                        resume.set()
                        writer.join(3)
                        if stopper.ident is not None:
                            stopper.join(3)
                    self.assertFalse(writer.is_alive())
                    self.assertFalse(stopper.is_alive())
                    if status:
                        self.assertEqual([str(exc) for exc in errors], [status])
                        self.assertEqual(result, [])
                    else:
                        self.assertEqual(errors, [])
                        self.assertEqual(result[0][0], b"\x01\x00\x02\x00")

    def test_new_input_cannot_open_during_publication_or_native_close(self):
        closing, release = threading.Event(), threading.Event()
        errors, streams = [], []

        class Device(Input):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                streams.append(self)

            def close(self):
                closing.set()
                if not release.wait(2):
                    raise TimeoutError("native close was not released")

        mic = Microphone()
        with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Device)):
            mic.start("A", lambda: None)

            def publish():
                self.assertFalse(mic.start("B", lambda: None)["ok"])
                mic.cancel()  # A rebind cannot reopen the close gate.

            def stop():
                try:
                    mic.stop("A", before_stop=publish)
                except Exception as exc:
                    errors.append(exc)

            worker = threading.Thread(target=stop, daemon=True)
            worker.start()
            try:
                self.assertTrue(closing.wait(1))
                self.assertFalse(mic.start("B", lambda: None)["ok"])
                self.assertEqual(len(streams), 1)
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(mic.start("B", lambda: None)["ok"])
            mic.cancel()
