"""Look commands and actionable audio failures; no devices or host bootstrap."""
import importlib.machinery
import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from hermes_gaze import cli
from hermes_gaze.runtime import service
from hermes_gaze.audio import voice
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.runtime.naming import plain_error
from hermes_gaze.runtime.voice_turns import VoiceTurns


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
        ctx.turns = turns
        ctx.commands = commands
        return plugin, session, ctx, commands['look'], hooks

    def test_explicit_setup_prepares_without_connecting_or_replacing_binding(self):
        plugin, session, ctx, command, hooks = self.register(None)
        ctx.turns.bind(session_key="key", session_id="session")
        binding = ctx.turns.binding
        with patch.object(plugin, '_handle_slash_command') as start, \
             patch.object(cli.importlib.util, 'find_spec', return_value=object()):
            command('setup', session_id='session', session_key='key')
            voice.prepare_recognition.assert_called_once()
            self.assertIs(ctx.turns.binding, binding)
            self.assertFalse(session.cdp.is_connected)
            start.assert_not_called()
            ctx.inject_message.assert_not_called()

    def test_start_and_legacy_alias_share_lifecycle_without_implicit_downloads(self):
        from unittest.mock import PropertyMock
        plugin, session, ctx, command, hooks = self.register(None)
        with patch.object(plugin, '_handle_slash_command', return_value='Ready') as start, \
             patch.object(type(session.cdp), 'is_connected', new_callable=PropertyMock, return_value=True):
            for alias in ('look', 'gaze'):
                for action in ('', 'start', 'connect', ' START '):
                    ctx.commands[alias](action, session_key='key', session_id='session')
                    self.assertTrue(ctx.turns.connected)
                    self.assertEqual(ctx.turns.binding['session_id'], 'session')
            self.assertEqual(start.call_count, 8)
            voice.prepare_recognition.assert_not_called()
            ctx.inject_message.assert_not_called()

    def test_disclosure_and_refused_source_change_cannot_steal_existing_binding(self):
        from unittest.mock import PropertyMock
        plugin, session, ctx, command, _ = self.register(None)
        ctx.turns.bind(session_key="key", session_id="owner")
        binding = ctx.turns.binding
        with patch.object(plugin, "_handle_slash_command", wraps=cli._handle_slash_command), \
             patch.object(cli, "get_shared_session", return_value=session), \
             patch.object(type(session.cdp), "is_connected", new_callable=PropertyMock, return_value=True):
            command("start --existing", session_key="other", session_id="other")
            self.assertIs(ctx.turns.binding, binding)
            command("start --existing --accept", session_key="other", session_id="other")
            self.assertIs(ctx.turns.binding, binding)

    def test_action_approval_opt_in_is_connection_owned_and_resets(self):
        plugin, session, ctx, command, _ = self.register(None)
        ctx.turns.bind(session_key="key", session_id="owner")
        def run(text, owner="owner", key="key"):
            return command(text, session_id=owner, session_key=key)
        self.assertIn("on", run("actions"))
        self.assertIn("off", run("actions allow-all"))
        self.assertEqual(session.tasks.approval_session, "owner")
        run("actions confirm", key="foreign")
        self.assertEqual(session.tasks.approval_session, "owner")
        ctx.turns.bind(session_key="key", session_id="owner")
        self.assertEqual(session.tasks.approval_session, "")
        run("actions allow-all")
        self.assertIn("on", run("actions confirm"))
        self.assertEqual(session.tasks.approval_session, "")
        run("actions allow-all")
        ctx.turns._disconnect()
        self.assertEqual(session.tasks.approval_session, "")

    def test_late_ready_cannot_replace_newer_binding_or_revive_stop(self):
        plugin, session, ctx, command, _ = self.register(None)
        callbacks = []
        def pending(raw, *, on_ready=None, on_error=None):
            session.cdp.source = "extension"
            if on_ready:
                callbacks.append(on_ready)
            return "Waiting"
        with patch.object(plugin, "_handle_slash_command", side_effect=pending):
            command("start --extension", session_key="old", session_id="old")
            ctx.turns.bind(session_key="new", session_id="new")
            binding = ctx.turns.binding
            ctx.turns.pending.append({"request_id": "retained"})
            callbacks.pop()()
            self.assertIs(ctx.turns.binding, binding)
            self.assertEqual(ctx.turns.pending, [{"request_id": "retained"}])
            command("start --extension", session_key="new", session_id="new")
            command("stop", session_key="new", session_id="new")
            callbacks.pop()()
            self.assertIsNone(ctx.turns.binding)

    def test_connection_failure_posts_to_captured_context_unless_stopped_or_rebound(self):
        from contextvars import ContextVar
        destination = ContextVar("destination", default="other")
        for outcome in ("failed", "stopped", "rebound"):
            with self.subTest(outcome=outcome):
                plugin, session, ctx, command, _ = self.register(None)
                callbacks, messages = [], []
                ctx.post_message = lambda text: messages.append((destination.get(), text))
                def pending(raw, *, on_ready=None, on_error=None):
                    session.cdp.source = "extension"
                    if on_error:
                        callbacks.append(on_error)
                    return "Looking for Chrome"
                token = destination.set("original")
                try:
                    with patch.object(plugin, "_handle_slash_command", side_effect=pending):
                        command("start --extension", session_key="key", session_id="owner")
                        if outcome == "stopped":
                            command("stop", session_key="key", session_id="owner")
                        elif outcome == "rebound":
                            ctx.turns.bind(session_key="new", session_id="new")
                finally:
                    destination.reset(token)
                callbacks[0]("Chrome discovery is unavailable.")
                self.assertEqual(messages, [("original", "Chrome discovery is unavailable.")]
                                 if outcome == "failed" else [])
                ctx.inject_message.assert_not_called()

    def test_read_only_commands_do_not_steal_another_conversation(self):
        plugin, session, ctx, command, _ = self.register(None)
        ctx.turns.bind(session_key="key", session_id="owner")
        binding = ctx.turns.binding
        with patch.object(cli, 'get_shared_session', return_value=session), \
             patch.object(session, 'is_chrome_reachable', return_value=False), \
             patch.object(cli.importlib.util, 'find_spec', return_value=object()):
            for action in ('status', 'tracker', 'diagnostics', 'help', 'help advanced', 'typo', 'stop extra'):
                command(action, session_key='other', session_id='other')
                self.assertIs(ctx.turns.binding, binding)

    def test_stop_releases_resources_and_binding_but_retains_host_admission(self):
        for alias, action in (('look', 'stop'), ('gaze', 'disconnect')):
            with self.subTest(alias=alias, action=action):
                plugin, session, ctx, command, _ = self.register(None)
                ctx.turns.bind(session_key='key', session_id='owner')
                ctx.turns.host_session, ctx.turns.host_turn = 'owner', 'active'
                cancelled = threading.Event()
                ctx.turns._speech_cancel = cancelled
                stream = Mock()
                session.microphone._stream = stream
                session.microphone._audio.extend(b'private audio')
                camera = Mock()
                session.webcam = camera
                tab = Mock()
                session.cdp._tabs['tab'] = tab
                server = Mock()
                with patch.object(cli, 'get_shared_session', return_value=session), \
                     patch.object(cli, 'get_shared_server', return_value=server):
                    ctx.commands[alias](action, session_key='other', session_id='other')
                self.assertFalse(ctx.turns.connected)
                self.assertTrue(cancelled.is_set())
                self.assertEqual(ctx.turns.host_turn, 'active')
                self.assertEqual(ctx.turns.host_session, 'owner')
                self.assertIsNone(session.microphone._stream)
                self.assertEqual(session.microphone._audio, b'')
                stream.abort.assert_called_once()
                stream.close.assert_called_once()
                camera.stop.assert_called_once()
                tab.close.assert_called_once()
                self.assertEqual(session.cdp._tabs, {})
                server.stop.assert_called_once()

    def test_raw_camera_diagnostics_are_explicit_not_ordinary_output(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        session.tracker.mode = 'webcam'
        status = dict(state='failed', error='PRIVATE_DIAGNOSTIC', samples=1234, calibrated=False)
        with patch.object(cli, 'get_shared_session', return_value=session), \
             patch.object(session, 'webcam_status', return_value=status), \
             patch.object(session, 'is_chrome_reachable', return_value=False):
            for action in ('status', 'tracker'):
                result = cli._handle_slash_command(action)
                self.assertNotIn('PRIVATE_DIAGNOSTIC', result)
                self.assertNotIn('1234', result)
                self.assertNotIn('{', result)
            detailed = json.loads(cli._handle_slash_command('diagnostics'))
            self.assertEqual(detailed['webcam'], status)

    def test_disconnected_companion_still_reports_independent_camera_activity(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        with patch.object(cli, 'get_shared_session', return_value=session):
            for state in ('starting', 'running', 'stopping', 'failed'):
                with self.subTest(state=state), \
                     patch.object(session, 'webcam_status', return_value={'state': state}):
                    result = cli._handle_slash_command('status')
                    self.assertIn('Camera', result)
                    self.assertIn('/look stop', result)
                    self.assertNotIn('Look is stopped', result)


    def test_status_and_repeated_connect_preserve_setup_but_new_key_revokes_it(self):
        from unittest.mock import PropertyMock
        plugin, session, ctx, command, _ = self.register(SimpleNamespace(get=lambda *a: True))
        ctx.turns.bind(session_key="key", session_id="session")
        binding = ctx.turns.binding
        generation = ctx.turns.binding_generation
        with patch.object(plugin, "_handle_slash_command", return_value="Tracker status"), \
             patch.object(type(session.cdp), "is_connected", new_callable=PropertyMock, return_value=True):
            command("tracker", session_key="key", session_id="session")
            self.assertIs(ctx.turns.binding, binding)
            command("connect", session_key="key", session_id="session")
            self.assertIs(ctx.turns.binding, binding)
            self.assertEqual(ctx.turns.binding_generation, generation)
            command("connect", session_key="replacement-key", session_id="session")
            self.assertIsNot(ctx.turns.binding, binding)


    def test_microphone_and_recognition_failures_stay_distinct_on_tool_path(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        with patch.object(session, 'configure'), \
             patch.object(session, 'fetch_cursor_context', return_value={}), \
             patch.object(voice, 'record_microphone', side_effect=PermissionError('denied private detail')):
            result = service.resolve_now(session, utterance='', record_voice=True)
        self.assertFalse(result['ok'])
        self.assertIn('Microphone capture', result['error'])
        microphone_recovery = result['plain_error']
        self.assertNotIn('private detail', result['plain_error'])
        with patch.object(session, 'configure'), \
             patch.object(session, 'fetch_cursor_context', return_value={}), \
             patch.object(voice, 'record_microphone', return_value=b'fake'), \
             patch.object(voice, 'transcribe_audio_buffer', side_effect=RuntimeError('decoder private detail')):
            result = service.resolve_now(session, utterance='', record_voice=True)
        self.assertFalse(result['ok'])
        self.assertIn('Speech recognition', result['error'])
        self.assertNotEqual(result['plain_error'], microphone_recovery)
        self.assertNotIn('private detail', result['plain_error'])

    def test_model_load_failure_keeps_cause_but_offers_model_recovery(self):
        import numpy as np
        with patch.object(voice, 'decode_audio_to_float32', return_value=np.ones(100, dtype=np.float32)), \
             patch.object(voice, 'get_whisper_model', side_effect=OSError('private cache path')):
            with self.assertRaises(RuntimeError) as caught:
                voice.transcribe_audio_buffer(b'fake', backend='whisper')
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertEqual(str(caught.exception.__cause__), 'private cache path')
        message = plain_error('failed', str(caught.exception))
        self.assertNotEqual(message, plain_error('failed', 'Speech recognition failed'))
        self.assertNotIn('private cache path', message)

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
            self.assertNotIn('PRIVATE_DIAGNOSTIC', replies[-1]['plain_error'])

    def test_stopped_camera_launch_offers_retry_not_calibration_instructions(self):
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        with patch.object(cli, 'get_shared_session', return_value=session), \
             patch.object(cli, 'apple_silicon_mac', return_value=True), \
             patch.object(session, 'start_webcam', return_value={'state': 'stopped', 'error': ''}):
            for command in ('calibrate', 'mode webcam'):
                with self.subTest(command=command):
                    result = cli._handle_slash_command(command)
                    self.assertEqual(session.tracker.mode, 'webcam')
                    self.assertNotIn('{', result)

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
        finally:
            release.set()
            worker.join(2)


if __name__ == '__main__':
    unittest.main()
