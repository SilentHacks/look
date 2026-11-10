"""Stock registered commands, fake Chrome consent and synthetic profile secrets only."""
from contextvars import ContextVar
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hermes_gaze import cli
from hermes_gaze.runtime import service
from hermes_gaze.browser.consent import ConsentChrome
from tests.test_chrome_consent import FakeChrome, until
from tests import test_first_run


class ProfileHighlight(unittest.TestCase):
    register = test_first_run.FirstRunTests.register
    setUp = test_first_run.FirstRunTests.setUp

    def connection(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        fake = FakeChrome(directory, allow=False)
        self.addCleanup(fake.close)
        plugin, session, ctx, command, _ = self.register(None)
        session.cdp._owned_chrome.profile = Path(directory) / 'look'
        original = ConsentChrome.__init__
        def initialize(root, **kwargs):
            original(root, **dict(kwargs, metadata_path=fake.metadata))
        self.enterContext(patch.object(ConsentChrome, '__init__', initialize))
        self.enterContext(patch.object(plugin, '_handle_slash_command', wraps=cli._handle_slash_command))
        self.enterContext(patch.object(cli, 'get_shared_session', return_value=session))
        self.enterContext(patch.object(cli, 'get_shared_server', return_value=Mock()))
        self.enterContext(patch.object(cli.platform, 'system', return_value='Darwin'))
        self.enterContext(patch.object(cli.platform, 'machine', return_value='arm64'))
        self.enterContext(patch.object(service, '_VOICE_TURNS', ctx.turns))
        self.enterContext(patch.object(service, '_CONFIG', None))
        def run(text, owner='session'):
            return command(text, session_id=owner, session_key=owner + '-key')
        return fake, session, ctx.turns, run

    def test_stop_restart_pending_consent_cannot_bind_old_attempt(self):
        fake, session, turns, run = self.connection()
        run('start --existing --accept')
        self.assertTrue(fake.requested.wait(2))
        old_root, old_worker = session.cdp.chrome, session.cdp._consent_worker
        run('stop')
        run('start --existing --accept')
        until(lambda: fake.upgrades == 2)
        self.assertFalse(old_root.live)
        old_worker.join(3)
        self.assertFalse(old_worker.is_alive())
        fake.allow.set()
        until(lambda: turns.connected)
        self.assertIsNot(session.cdp.chrome, old_root)
        self.assertEqual(turns.binding['session_id'], 'session')
        self.assertEqual(fake.upgrades, 2)

    def test_profile_rotation_rebind_and_revoked_delayed_asr(self):
        profile = ContextVar('synthetic_profile', default={})
        reads, requests = [], []
        def secret(name):
            reads.append(name)
            return profile.get().get(name)
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def read(self, _):
                return b'{"answers":{"scope":{"choice":"none"}}}'
        def send(request, **_):
            requests.append(request)
            return Response()
        with patch.dict('sys.modules', {'agent.secret_scope': SimpleNamespace(get_secret=secret)}), \
             patch('urllib.request.urlopen', side_effect=send):
            fake, session, turns, run = self.connection()
            own = {'TYPESAFE_API_KEY': 'synthetic-owner'}
            token = profile.set(own)
            try:
                run('start --existing --accept')
            finally:
                profile.reset(token)
            self.assertEqual(reads, [])
            fake.allow.set()
            until(lambda: turns.connected)
            turns.host_turn = 'busy'  # Keep synthetic questions out of the host injector.
            snapshot = dict(ok=True, mode='hover', utterance='Explain this', context='PRIVATE_PAGE',
                            top={'role': 'td'}, scope_bundles={'none': [], 'pointed': ['@a']})
            def capture():
                profile.set({'TYPESAFE_API_KEY': 'synthetic-wrong-thread'})
                turns.capture(snapshot)
            for key in ('synthetic-owner', 'synthetic-rotated'):
                own['TYPESAFE_API_KEY'] = key
                worker = threading.Thread(target=capture)
                worker.start()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                for decision in threading.enumerate():
                    if decision.name == 'gaze-scope':
                        decision.join(2)
                self.assertEqual(requests[-1].get_header('Authorization'), 'Bearer ' + key)
                self.assertNotIn('PRIVATE_PAGE', requests[-1].data.decode())
                self.assertNotIn(key, requests[-1].data.decode())
                self.assertNotIn(key, json.dumps(session.last_hover_snapshot, default=str))
                self.assertNotIn(key, json.dumps(turns.items, default=str))
            pending = turns.capture(snapshot, transcribing=True)
            turns.native_disconnected()
            self.assertIsNone(turns._secret_context)
            token = profile.set({'TYPESAFE_API_KEY': 'synthetic-second-profile'})
            try:
                turns.bind(session_key='session-key', session_id='session')
            finally:
                profile.reset(token)
            turns.transcribed(pending['request_id'], 'old capture', snapshot)
            self.assertEqual(len(reads), 2)  # Late ASR cannot read the replacement scope.
            capture()
            for decision in threading.enumerate():
                if decision.name == 'gaze-scope':
                    decision.join(2)
            self.assertEqual(requests[-1].get_header('Authorization'), 'Bearer synthetic-second-profile')
            native = Mock()
            turns.bind(session_key='session-key', session_id='session', native_input=native)
            generation = turns.binding_generation
            token = profile.set({'TYPESAFE_API_KEY': 'synthetic-refreshed-command'})
            try:
                turns.bind(session_key='session-key', session_id='session', native_input=native)
            finally:
                profile.reset(token)
            self.assertEqual(turns.binding_generation, generation)
            capture()
            for decision in threading.enumerate():
                if decision.name == 'gaze-scope':
                    decision.join(2)
            self.assertEqual(requests[-1].get_header('Authorization'), 'Bearer synthetic-refreshed-command')
            run('stop')
            self.assertIsNone(turns._secret_context)
            self.assertFalse(turns.connected)
