"""Action-task authorization, cancellation, URL and schema boundaries."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hermes_gaze.browser_tasks import BrowserTasks, navigation_url
from hermes_gaze import tools


class BrowserTaskTests(unittest.TestCase):
    def setUp(self):
        self.owner = dict(browser_target='tab', browser_document='document', browser_route=3)
        self.session = SimpleNamespace(actions=Mock(), display_session_event=Mock(), cdp=Mock(), clear_hover_snapshot=Mock())
        self.session.cdp_http_url = 'http://127.0.0.1:9333'
        self.tasks = BrowserTasks(self.session)
        self.assertTrue(self.tasks.begin('session', 'turn', self.owner)['ok'])

    def test_exact_turn_authorization_and_terminal_stop(self):
        for ids in ({}, dict(session_id='session'), dict(session_id='foreign', turn_id='turn'),
                    dict(session_id='session', turn_id='old-turn')):
            self.assertFalse(self.tasks.handle('read', {}, **ids)['ok'])
        self.tasks.authorize_call('session', 'turn')
        self.assertEqual(self.tasks._authorized('session'), '')
        self.tasks.finish('foreign', 'turn', failed=True)
        self.assertEqual(self.tasks._authorized('session'), '')
        self.tasks.stop()
        self.assertFalse(self.tasks.begin('session', 'turn', self.owner)['ok'])
        self.assertFalse(self.tasks.handle('read', {}, session_id='session', turn_id='turn')['ok'])
        self.assertTrue(self.tasks.begin('session', 'next-turn', self.owner)['ok'])
        self.assertNotEqual(self.tasks._authorized('session'), '')

    def test_failed_owner_cannot_keep_previous_turn_authority(self):
        self.session.cdp.capture.side_effect = ConnectionError('no focus')
        self.assertFalse(self.tasks.begin('session', 'new-turn')['ok'])
        self.assertFalse(self.tasks.handle('read', {}, session_id='session', turn_id='turn')['ok'])

    def test_unknown_navigation_outcome_revokes_instead_of_replaying(self):
        self.tasks._current = lambda epoch: None
        self.session.cdp.action_navigate.side_effect = ConnectionError('reply lost')
        result = self.tasks.handle('open_tab', dict(resolution_id=1, url='https://example.test/'),
                                   session_id='session', turn_id='turn')
        self.assertEqual(result['outcome'], 'unknown')
        self.assertFalse(self.tasks.handle('read', {}, session_id='session', turn_id='turn')['ok'])
        self.assertEqual(self.session.cdp.action_navigate.call_count, 1)

    def test_malformed_navigation_reply_revokes_authority_without_replay(self):
        self.tasks._current = lambda epoch: None
        self.session.cdp.action_navigate.side_effect = json.JSONDecodeError('malformed reply', '', 0)
        result = self.tasks.handle('open_tab', dict(resolution_id=1, url='https://example.test/'),
                                   session_id='session', turn_id='turn')
        self.assertIsNone(result['executed'])
        self.assertEqual(result['outcome'], 'unknown')
        self.assertFalse(self.tasks.handle('read', {}, session_id='session', turn_id='turn')['ok'])
        self.assertEqual(self.session.cdp.action_navigate.call_count, 1)

    def test_destination_validation_preserves_ordinary_urls(self):
        url = 'https://example.test/watch?v=123#chapter'
        self.assertEqual(navigation_url(url), url)
        for url in ('file:///tmp/page', 'javascript:alert(1)', 'mailto:a@example.test',
                    'https://user:secret@example.test/', '//example.test/', 'https://example.test:0',
                    'https://example.test:999999/', 'https://example.test/\nsecret', 'https://example.test\\@evil.test'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                navigation_url(url)

    def test_missing_required_mutation_arguments_never_execute(self):
        self.tasks._current = lambda epoch: None
        self.tasks.snapshot = dict(snapshot_id='capture', resolution_id=1)
        self.session.tasks = self.tasks
        with patch.object(tools, 'get_shared_session', return_value=self.session):
            result = json.loads(tools.handle_gaze_fill({'resolution_id': 1}, session_id='session', turn_id='turn'))
        self.assertFalse(result['executed'])
        self.session.actions._browser.assert_not_called()
        schema = tools.GAZE_FILL_SCHEMA['parameters']
        self.assertEqual(set(schema['required']), {'resolution_id', 'entries'})
        self.assertEqual(set(tools.GAZE_REQUEST_COMMIT_SCHEMA['parameters']['required']), {'resolution_id', 'handle'})

    def test_missing_or_invalid_tab_choice_never_clicks(self):
        self.tasks._current = lambda epoch: None
        self.tasks.snapshot = dict(snapshot_id='capture', resolution_id=1)
        for choice in (None, 'true', 1):
            result = self.tasks.handle('click', dict(resolution_id=1, handle='@1', new_tab=choice),
                                       session_id='session', turn_id='turn')
            self.assertFalse(result['executed'])
        self.session.actions.click.assert_not_called()
        self.session.actions._inspect.assert_not_called()

    def test_provider_rejection_stops_the_trial_instead_of_looping_over_fixtures(self):
        from hermes_gaze.benchmark.browser_actions_production import run_turn
        agent = Mock(session_id='trial-session')
        agent._memory_store._system_prompt_snapshot = {'user': 'Alex Morgan alex@example.test'}
        agent.run_conversation.return_value = {'completed': False, 'final_response': 'HTTP 429 free-models-per-day'}
        trial_tools = SimpleNamespace(entries={}, rules='', calls=[], plugin_turns=SimpleNamespace(
            ctx=SimpleNamespace(inject_message=Mock()), bind=Mock()))
        with patch.dict('sys.modules', run_agent=SimpleNamespace(AIAgent=Mock(return_value=agent))), \
                patch.dict('os.environ', HERMES_HOME='/unused-trial-home'):
            with self.assertRaises(SystemExit):
                run_turn(SimpleNamespace(), trial_tools, 'Fill this out', 'unused', 'http://fixture.test')
            def limited_after_action(*_):
                trial_tools.calls.append({'tool': 'gaze_read'})
                return {'completed': False, 'failure_reason': 'rate_limit'}
            agent.run_conversation.side_effect = limited_after_action
            with self.assertRaises(SystemExit):
                run_turn(SimpleNamespace(), trial_tools, 'Fill this out', 'unused', 'http://fixture.test')

    def test_trial_auth_failure_stops_without_disclosing_credentials(self):
        from hermes_gaze.benchmark.browser_actions_production import runtime_credentials
        auth = Mock()
        auth.resolve_nous_runtime_credentials.side_effect = RuntimeError('secret-token-in-provider-error')
        with patch.dict('sys.modules', hermes_cli=SimpleNamespace(auth=auth)):
            with self.assertRaises(SystemExit) as stopped:
                runtime_credentials('nous')
        self.assertIn('hermes auth add nous', str(stopped.exception))
        self.assertNotIn('secret-token', str(stopped.exception))

    def test_navigation_cannot_open_its_own_debugger_even_through_a_loopback_alias(self):
        self.tasks._current = lambda epoch: None
        for url in ('http://127.0.0.1:9333/json', 'http://127.1:9333/json',
                    'http://localhost:9333/devtools/inspector.html'):
            with self.subTest(url=url):
                result = self.tasks.handle('navigate', dict(resolution_id=1, url=url),
                                           session_id='session', turn_id='turn')
                self.assertFalse(result['ok'])
        self.session.cdp.action_navigate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
