"""Recording loss must be definite; Chrome must never delay the native deadline."""
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from look.browser.companion import Companion
from look.audio.microphone import Microphone


class Input:
    def __init__(self, **kwargs):
        self.callback = kwargs['callback']
    def start(self):
        self.callback(b'\x01\x00', 1, SimpleNamespace(currentTime=1., inputBufferAdcTime=1.), None)
    def stop(self): pass
    def abort(self): pass
    def close(self): pass


class RecordingHold(unittest.TestCase):
    def setUp(self):
        self.mic = Microphone()
        self.addCleanup(self.mic.cancel)
        self.device = patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Input))
        self.device.start()
        self.addCleanup(self.device.stop)

    def test_unknown_checks_keep_audio_until_definite_focus_loss(self):
        checked, cancelled = threading.Event(), threading.Event()
        reasons = []
        calls = 0
        loss = threading.Event()
        def check():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TimeoutError('busy renderer')
            if calls > 2:
                checked.set()
            return 'Recording cancelled: the source tab lost focus.' if loss.is_set() else None
        def cancel(reason):
            reasons.append(reason)
            cancelled.set()
        self.assertTrue(self.mic.start('A', check, on_cancel=cancel)['ok'])
        self.assertTrue(checked.wait(1))
        self.assertEqual(self.mic._audio, b'\x01\x00')
        self.assertEqual(reasons, [])
        loss.set()
        self.assertTrue(cancelled.wait(1))
        self.assertEqual(reasons, ['Recording cancelled: the source tab lost focus.'])
        self.assertEqual(self.mic._audio, b'')

    def test_stalled_focus_check_cannot_extend_deadline_and_warning_is_once(self):
        blocked, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        warnings, reasons = [], []
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls > 1:
                blocked.set()
                release.wait(2)
            return None
        def cancel(reason):
            reasons.append(reason)
            cancelled.set()
        self.mic.MAX_RECORDING_SECONDS = .3
        self.assertTrue(self.mic.start('A', check, on_cancel=cancel, on_warning=warnings.append)['ok'])
        self.assertTrue(blocked.wait(1))
        self.assertTrue(cancelled.wait(1))  # The Chrome check is still blocked.
        self.assertEqual(warnings, [5])
        self.assertEqual(reasons, ['Recording cancelled: 0.3-second limit reached.'])
        self.assertIsNone(self.mic._stream)
        self.assertEqual(self.mic._audio, b'')

    def test_device_error_names_the_actual_failure(self):
        cancelled = threading.Event()
        reasons = []
        def cancel(reason):
            reasons.append(reason)
            cancelled.set()
        self.assertTrue(self.mic.start('A', lambda: None, on_cancel=cancel)['ok'])
        self.mic._stream.callback(b'', 0, SimpleNamespace(currentTime=1., inputBufferAdcTime=1.), 'input overflow')
        self.assertTrue(cancelled.wait(1))
        self.assertEqual(reasons, ['Recording cancelled: microphone error (input overflow).'])
        self.assertEqual(self.mic._audio, b'')

    def test_recording_owner_ignores_route_but_not_focus_or_replaced_document(self):
        companion = Companion('http://127.0.0.1:1')
        tab = SimpleNamespace(is_connected=True, _context_unique_id='document', _route_id=15,
                              eval_js_once=Mock(return_value={'hidden': False, 'focused': True}))
        companion._tabs = {'A': tab}
        self.assertIsNone(companion.recording_loss('A', 'document'))
        tab._route_id += 1
        self.assertIsNone(companion.recording_loss('A', 'document'))
        tab.eval_js_once.return_value = {'hidden': False, 'focused': False}
        self.assertEqual(companion.recording_loss('A', 'document'),
                         'Recording cancelled: the source tab lost focus.')
        tab.eval_js_once.side_effect = TimeoutError('heavy scroll')
        with self.assertRaises(TimeoutError):
            companion.recording_loss('A', 'document')  # Microphone treats this as unknown.
        tab._context_unique_id = 'new-document'
        self.assertEqual(companion.recording_loss('A', 'document'),
                         'Recording cancelled: the source document changed.')

    def test_document_replaced_during_foreground_read_is_not_accepted(self):
        companion = Companion('http://127.0.0.1:1')
        def evaluate(*args, **kwargs):
            tab._context_unique_id = 'new-document'
            return {'hidden': False, 'focused': True}
        tab = SimpleNamespace(is_connected=True, _context_unique_id='document', eval_js_once=evaluate)
        companion._tabs = {'A': tab}
        self.assertEqual(companion.recording_loss('A', 'document'),
                         'Recording cancelled: the source document changed.')
