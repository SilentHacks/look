"""Passive onboarding and actionable audio failures; no devices or host bootstrap."""
import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hermes_gaze import cli, service, voice
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.naming import plain_error


class FirstRunTests(unittest.TestCase):
    def register(self, state):
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
             patch.object(plugin, 'get_shared_server', return_value=Mock()), patch.object(voice, 'prewarm'), \
             patch.object(service, '_VOICE_TURNS', None), patch.object(service, '_CONFIG', None):
            plugin.register(ctx)
            turns = service._VOICE_TURNS
        self.addCleanup(turns.close)
        return plugin, session, ctx, commands['gaze'], hooks

    def test_first_guide_is_passive_repeat_connects_and_reopen_does_not_rebind(self):
        saved = {}
        state = SimpleNamespace(get=saved.get, set=lambda key, value: saved.update({key: value}))
        plugin, session, ctx, command, hooks = self.register(state)
        with patch.object(plugin, '_handle_slash_command') as start, \
             patch.object(cli.importlib.util, 'find_spec', return_value=object()), \
             patch.object(voice, '_COREML_RUNNER', None):
            guide = command('', session_id='new', session_key='key')
            self.assertIn('Send a normal message', guide)
            self.assertIn('preparing', guide)
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

    def test_missing_prerequisites_and_failed_model_do_not_claim_ready(self):
        session = SimpleNamespace(cdp=SimpleNamespace(is_connected=False))
        with patch.object(cli.platform, 'system', return_value='Linux'), \
             patch.object(cli.Path, 'is_file', return_value=False), \
             patch.object(cli.importlib.util, 'find_spec', side_effect=lambda name: None if name == 'sounddevice' else object()), \
             patch.object(voice, '_COREML_RUNNER', False), \
             patch.object(voice, '_get_coreml_runner') as load:
            guide = cli._first_run_guide(session)
        self.assertIn('use an Apple Silicon Mac', guide)
        self.assertIn('install Google Chrome', guide)
        self.assertIn('missing sounddevice', guide)
        self.assertIn('hermes pm install', guide)
        self.assertIn('fallback', guide)
        self.assertNotIn('recognition is ready', guide)
        load.assert_not_called()

    def test_microphone_and_recognition_failures_stay_distinct_on_tool_path(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        with patch.object(session, 'configure'), \
             patch.object(session, 'fetch_cursor_context', return_value={}), \
             patch.object(voice, 'record_microphone', side_effect=PermissionError('denied private detail')):
            result = service.resolve_now(session, utterance='', record_voice=True)
        self.assertIn('Microphone', result['plain_error'])
        self.assertIn('Privacy & Security', result['plain_error'])
        self.assertNotIn('private detail', result['plain_error'])
        with patch.object(session, 'configure'), \
             patch.object(session, 'fetch_cursor_context', return_value={}), \
             patch.object(voice, 'record_microphone', return_value=b'fake'), \
             patch.object(voice, 'transcribe_audio_buffer', side_effect=RuntimeError('decoder private detail')):
            result = service.resolve_now(session, utterance='', record_voice=True)
        self.assertIn('Speech recognition', result['plain_error'])
        self.assertIn('type your question', result['plain_error'])
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


if __name__ == '__main__':
    unittest.main()
