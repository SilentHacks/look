"""Passive onboarding and actionable audio failures; no devices or host bootstrap."""
import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from hermes_gaze import cli, service, voice
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.naming import plain_error
from hermes_gaze.voice_turns import VoiceTurns


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(voice, "prepare_recognition"))
        self.enterContext(patch.object(voice, "recognition_ready", return_value=True))

    def register(self, state, *, warm=False):
        loader = importlib.machinery.SourceFileLoader(
            'hermes_gaze.first_run_entry', str(Path(__file__).parents[1] / '__init__.py'))
        plugin = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader, is_package=False))
        loader.exec_module(plugin)
        commands, hooks = {}, {}
        ctx = SimpleNamespace(state=state, get_config=lambda key, default: default,
            register_system_prompt_section=Mock(), register_tool=Mock(),
            register_hook=lambda name, fn: hooks.update({name: fn}), register_middleware=Mock(),
            register_command=lambda name, **kw: commands.update({name: kw['handler']}),
            register_cli_command=Mock(), register_skill=Mock(), on_unload=Mock(), inject_message=Mock())
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        with patch.object(plugin, 'get_shared_session', return_value=session), \
             patch.object(plugin, 'get_shared_server', return_value=Mock()), \
             patch.object(voice, 'prewarm', wraps=voice.prewarm if warm else None), \
             patch.object(service, '_VOICE_TURNS', None), patch.object(service, '_CONFIG', None):
            plugin.register(ctx)
            turns = service._VOICE_TURNS
        self.addCleanup(turns.close)
        return plugin, session, ctx, commands['gaze'], hooks

    def test_first_guide_prepares_without_connecting_and_reopen_does_not_rebind(self):
        saved = {}
        state = SimpleNamespace(get=saved.get, set=lambda key, value: saved.update({key: value}))
        plugin, session, ctx, command, hooks = self.register(state)
        with patch.object(plugin, '_handle_slash_command') as start, \
             patch.object(cli.importlib.util, 'find_spec', return_value=object()), \
             patch.object(voice, '_COREML_RUNNER', None):
            guide = command('', session_id='new', session_key='key')
            self.assertIn('Send a normal message', guide)
            start.assert_not_called()
            ctx.inject_message.assert_not_called()
            self.assertFalse(session.cdp.is_connected)
            self.assertTrue(saved['first_run_shown'])
            # Guide remains explicitly available even after host readiness was observed.
            hooks['pre_llm_call'](session_id='new', user_message='Hello')
            self.assertNotIn('readiness is not confirmed', command('setup', session_id='new'))
            start.assert_not_called()
            command('', session_id='new', session_key='key')
            start.assert_called_once_with('start')
            ctx.inject_message.assert_not_called()

    def test_persisted_guide_stays_quiet_after_reload_and_state_error_is_recoverable(self):
        for state, guide_expected in (
            (SimpleNamespace(get=lambda *a: True), False),
            (SimpleNamespace(get=Mock(side_effect=RuntimeError('bad JSON')), set=Mock()), True),
        ):
            with self.subTest(guide_expected=guide_expected):
                plugin, session, ctx, command, _ = self.register(state)
                with patch.object(plugin, '_handle_slash_command', return_value='reconnect') as start, \
                     patch.object(cli.importlib.util, 'find_spec', return_value=object()):
                    result = command('')
                    self.assertEqual('Hermes Gaze first run' in result, guide_expected)
                    self.assertEqual(start.called, not guide_expected)


    def test_microphone_and_recognition_failures_stay_distinct_on_tool_path(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        with patch.object(session, 'configure'), \
             patch.object(session, 'fetch_cursor_context', return_value={}), \
             patch.object(voice, 'record_microphone', side_effect=PermissionError('denied private detail')):
            result = service.resolve_now(session, utterance='', record_voice=True)
        self.assertIn('Microphone', result['plain_error'])
        self.assertIn('settings', result['plain_error'])
        self.assertNotIn('private detail', result['plain_error'])
        with patch.object(session, 'configure'), \
             patch.object(session, 'fetch_cursor_context', return_value={}), \
             patch.object(voice, 'record_microphone', return_value=b'fake'), \
             patch.object(voice, 'transcribe_audio_buffer', side_effect=RuntimeError('decoder private detail')):
            result = service.resolve_now(session, utterance='', record_voice=True)
        self.assertIn('Speech recognition', result['plain_error'])
        self.assertIn('Right Option', result['plain_error'])
        self.assertNotIn('microphone', result['plain_error'])
        self.assertNotIn('private detail', result['plain_error'])

    def test_model_load_failure_keeps_cause_but_offers_model_recovery(self):
        import numpy as np
        with patch.object(voice, 'decode_audio_to_float32', return_value=np.ones(100, dtype=np.float32)), \
             patch.object(voice, 'get_whisper_model', side_effect=OSError('private cache path')):
            with self.assertRaisesRegex(RuntimeError, 'Speech model could not load') as caught:
                voice.transcribe_audio_buffer(b'fake', backend='whisper')
        self.assertIsInstance(caught.exception.__cause__, OSError)
        message = plain_error('failed', str(caught.exception))
        self.assertIn('disk space', message)
        self.assertNotIn('private cache path', message)
        self.assertNotIn('make out', message)

    def test_owned_microphone_errors_are_labelled_without_exposing_native_diagnostics(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        for kind, method in (('record_start', 'start'), ('record_stop', 'stop')):
            replies = []
            with self.subTest(kind=kind), \
                 patch.object(service, 'get_shared_session', return_value=session), \
                 patch.object(service, '_VOICE_TURNS', None), \
                 patch.object(session.microphone, method, side_effect=OSError('native PRIVATE_DIAGNOSTIC')):
                service.handle_intent({'type': kind, 'nonce': session._intent_nonce,
                                       '_browser_target': 'tab', '_browser_document': 'doc'}, replies.append)
            self.assertFalse(replies[-1]['ok'])
            self.assertIn('Microphone', replies[-1]['plain_error'])
            self.assertIn('permission', replies[-1]['plain_error'])
            self.assertNotIn('PRIVATE_DIAGNOSTIC', replies[-1]['plain_error'])

    def test_chrome_launch_failure_returns_a_repair_action(self):
        session = SimpleNamespace(cdp_http_url='http://127.0.0.1:1', is_chrome_reachable=lambda: False)
        with patch.object(cli, 'get_shared_session', return_value=session), \
             patch.object(cli, 'launch_chrome_with_cdp', side_effect=FileNotFoundError):
            result = cli._handle_slash_command('start')
        self.assertIn('/gaze setup', result)
        self.assertIn('Applications', result)

    def test_stopped_camera_launch_offers_retry_not_calibration_instructions(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        with patch.object(cli, 'get_shared_session', return_value=session), \
             patch.object(session, 'start_webcam', return_value={'state': 'stopped', 'error': ''}):
            for command in ('calibrate', 'mode webcam'):
                with self.subTest(command=command):
                    result = cli._handle_slash_command(command)
                    self.assertEqual(session.tracker.mode, 'webcam')
                    self.assertIn('Camera stopped', result)
                    self.assertIn('Try again', result)
                    self.assertIn('/gaze calibrate', result)
                    self.assertNotIn('click Begin', result)

    def test_busy_and_stopping_speech_refuse_capture_with_their_own_recovery(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        turns = VoiceTurns(SimpleNamespace(), session)
        self.addCleanup(turns.close)
        release = threading.Event()
        worker = threading.Thread(target=release.wait, daemon=True)
        worker.start()
        try:
            for capture, speech_worker, cause in (('recording', None, 'Microphone'),
                                                  ('idle', worker, 'Read aloud')):
                turns.capture_state, turns._speech_thread = capture, speech_worker
                replies = []
                with self.subTest(cause=cause), \
                     patch.object(service, 'get_shared_session', return_value=session), \
                     patch.object(service, '_VOICE_TURNS', turns), \
                     patch.object(session.microphone, 'start') as microphone:
                    service.handle_intent({'type': 'record_start', 'nonce': session._intent_nonce,
                                           '_browser_target': 'tab', '_browser_document': 'doc'}, replies.append)
                microphone.assert_not_called()
                self.assertFalse(replies[-1]['ok'])
                self.assertIn(cause, replies[-1]['plain_error'])
                self.assertNotIn('permission', replies[-1]['plain_error'])
        finally:
            release.set()
            worker.join(2)


if __name__ == '__main__':
    unittest.main()
