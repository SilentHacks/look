"""Consumer-visible privacy, ownership, microphone deadline and voice regressions."""
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hermes_gaze import service, voice
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.browser.companion import Companion
from hermes_gaze.config import GazeConfig
from hermes_gaze.microphone import Microphone
from hermes_gaze.resolver.cursor_context import safe_url


class TrustBoundaries(unittest.TestCase):
    def test_answers_have_one_document_owner_and_wait_for_foreground(self):
        companion = Companion('http://127.0.0.1:1')
        a = SimpleNamespace(is_connected=True, _context_unique_id='doc-A', session_event=None,
                            eval_js_once=Mock(return_value=False))
        b = SimpleNamespace(is_connected=True, _context_unique_id='doc-B', session_event=None,
                            eval_js_once=Mock(return_value=True))
        companion._tabs = {'A': a, 'B': b}
        event = dict(browser_target='A', browser_document='doc-A', text='PRIVATE_PAYROLL')
        companion.display(event)
        self.assertIsNone(b.session_event)
        b.eval_js_once.assert_not_called()
        self.assertIsNone(getattr(a, '_displayed_event', None))
        a.eval_js_once.return_value = True
        companion._display_pending(a)
        self.assertEqual(a._displayed_event['text'], 'PRIVATE_PAYROLL')
        a._context_unique_id = 'replaced'
        companion.display({**event, 'text': 'LATE_PRIVATE_PAYROLL'})
        self.assertEqual(a.eval_js_once.call_count, 2)
        companion.display({'text': 'UNOWNED_PRIVATE_MESSAGE'})
        b.eval_js_once.assert_not_called()

    def test_simulated_resolution_keeps_evidence_owner_after_scoring_focus_change(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        pushed = {'browser_target': 'A', 'browser_document': 'doc-A', 'browser_route': 4,
                  'pointer': {'x_vp': 20, 'y_vp': 20},
                  'candidates': [dict(id='open', tag='button', role='button', label='Open preferences',
                    selector='#open', rect_vp=[10, 10, 50, 30], rect_doc=[10, 10, 50, 30],
                    is_interactive=True, is_direct_hit=True)]}
        original = service.resolve_candidates

        def scoring(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[2] == 'Open this':
                other = {**pushed, 'browser_target': 'B', 'browser_document': 'doc-B', 'browser_route': 9,
                         'candidates': [{**pushed['candidates'][0], 'label': 'PRIVATE B target'}]}
                service.resolve_now(session, utterance='Inspect B', mode='simulated', pushed=other)
            session.cdp._target = Mock(side_effect=AssertionError('Do not look up focus after capture'))
            return result

        with patch.object(service, '_CONFIG', GazeConfig()), patch.object(service, '_LLM', None), \
                patch.object(service, 'resolve_candidates', side_effect=scoring):
            result = service.resolve_now(session, utterance='Open this', mode='simulated', pushed=pushed)
        self.assertEqual(result['browser_target'], 'A')
        self.assertEqual((session._resolution_target, session._resolution_document, session._resolution_route),
                         ('A', 'doc-A', 4))
        self.assertIn('Open preferences', result['context'])
        self.assertNotIn('PRIVATE B target', result['context'])
        session.cdp._target.assert_not_called()

    def test_recording_deadline_closes_and_discards_without_release_event(self):
        closed, cancelled = threading.Event(), threading.Event()

        class Input:
            def __init__(self, **kwargs):
                self.callback = kwargs['callback']
            def start(self):
                self.callback(b'\x01\x00', 1, SimpleNamespace(currentTime=1., inputBufferAdcTime=1.), None)
            def abort(self):
                pass
            def close(self):
                closed.set()

        mic = Microphone()
        mic.MAX_RECORDING_SECONDS = .02
        self.addCleanup(mic.cancel)
        with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Input)):
            self.assertTrue(mic.start('A', lambda: None, on_cancel=lambda _: cancelled.set())['ok'])
            self.assertTrue(closed.wait(1))
            self.assertTrue(cancelled.wait(1))
            self.assertEqual(mic._audio, bytearray())
            with self.assertRaises(RuntimeError):
                mic.stop('A')

    def test_simulated_voice_resolves_release_candidates_not_cursor_context(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        inputs = []

        def complete(**kwargs):
            inputs.extend(kwargs['input'])
            return 'Preferences opens the settings panel.'

        intent = dict(type='record_stop', mode='simulated', nonce=session._intent_nonce,
                      _browser_target='A', _browser_document='doc-A', _browser_route=0,
                      pointer={'x_vp': 20, 'y_vp': 20}, fixations=[],
                      candidates=[dict(id='open', tag='button', role='button', label='Open preferences',
                        selector='#open', rect_vp=[10, 10, 50, 30], rect_doc=[10, 10, 50, 30],
                        is_interactive=True, is_direct_hit=True)])
        replies = []
        with patch.object(service, 'get_shared_session', return_value=session), \
                patch.object(service, '_VOICE_TURNS', None), patch.object(service, '_CONFIG', GazeConfig()), \
                patch.object(service, '_LLM', SimpleNamespace(complete_structured=complete)), \
                patch.object(session.microphone, 'stop', return_value=(b'\x01\x00', time.time())), \
                patch.object(voice, 'transcribe_audio_buffer', return_value=('What does this do?', [])):
            service.handle_intent(intent, replies.append)
        self.assertTrue(replies[0]['ok'], replies)
        self.assertEqual(replies[0]['delivery'], 'one_shot')
        self.assertEqual(replies[0]['explanation'], 'Preferences opens the settings panel.')
        self.assertTrue(any('Open preferences' in value['text'] for value in inputs))

    def test_urls_keep_destinations_but_remove_capabilities(self):
        self.assertEqual(safe_url('https://alice:password@example.invalid/reset?access_token=SECRET#KEY'),
                         'https://example.invalid/reset')
        self.assertEqual(safe_url('https://[::1]/path?code=SECRET'), 'https://[::1]/path')
        self.assertEqual(safe_url('https://youtube.com/watch?v=abc'), 'https://youtube.com/watch?v=abc')
        self.assertEqual(safe_url('https://shop.invalid/product?id=123&sort=price&tag=a&tag=b'),
                         'https://shop.invalid/product?id=123&sort=price&tag=a&tag=b')
        self.assertEqual(safe_url('https://shop.invalid/?search=ordinary+search+phrase&empty='),
                         'https://shop.invalid/?search=ordinary+search+phrase&empty=')
        for name in ('token', 'api_key', 'clientSecret', 'password', 'auth', 'session',
                     'signature', 'code', 'csrf', 'accessToken', 'X-Amz-Signature'):
            self.assertEqual(safe_url(f'https://shop.invalid/?id=123&{name}=hidden'),
                             'https://shop.invalid/?id=123')
        self.assertEqual(safe_url('https://shop.invalid/?id=123&data=0123456789abcdef0123456789abcdef'),
                         'https://shop.invalid/?id=123')
        self.assertEqual(safe_url('https://shop.invalid/?' + '&'.join('x=1' for _ in range(129))), '')
        for value in ('javascript:alert(1)', 'https://[broken/path', 'https://example.invalid/\nSECRET',
                      'https://example.invalid\\@evil.invalid/'):
            self.assertEqual(safe_url(value), '')
