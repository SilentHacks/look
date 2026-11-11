"""Action-task authorization, cancellation, URL and schema boundaries."""
import json
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from look.browser.browser_tasks import BrowserTasks, navigation_url
from look import tools
from look.config import GazeConfig
from look.runtime import service


class BrowserTaskTests(unittest.TestCase):
    def setUp(self):
        self.owner = dict(browser_target='tab', browser_document='document', browser_route=3)
        self.session = SimpleNamespace(actions=Mock(), display_session_event=Mock(), cdp=Mock(), clear_hover_snapshot=Mock())
        self.session.cdp_http_url = 'http://127.0.0.1:9333'
        self.tasks = BrowserTasks(self.session)
        self.assertTrue(self.tasks.begin('session', 'turn', self.owner)['ok'])
        dns = patch('socket.getaddrinfo', return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
        self.dns = dns.start()
        self.addCleanup(dns.stop)
        config = patch.object(service, '_CONFIG', GazeConfig())
        config.start()
        self.addCleanup(config.stop)

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

    def test_approval_mode_is_explicit_session_owned_and_revokes_current_task(self):
        self.assertFalse(self.tasks.grant['allow_all'])
        self.tasks.set_approval_mode('session', allow_all=True)
        self.assertFalse(self.tasks.handle('read', {}, session_id='session', turn_id='turn')['ok'])
        self.tasks.begin('session', 'next', self.owner)
        self.assertTrue(self.tasks.grant['allow_all'])
        self.tasks.begin('foreign', 'next', self.owner)
        self.assertFalse(self.tasks.grant['allow_all'])
        self.tasks.set_approval_mode()
        self.tasks.begin('session', 'again', self.owner)
        self.assertFalse(self.tasks.grant['allow_all'])

    def test_commit_cannot_navigate_to_debugger_in_either_approval_mode(self):
        for allow_all in (False, True):
            self.tasks.set_approval_mode('session', allow_all=allow_all)
            turn = str(allow_all)
            self.tasks.begin('session', turn, self.owner)
            self.tasks.snapshot = {'resolution_id': 1}
            self.tasks._current = lambda epoch: None
            self.session.actions._inspect.return_value = {
                'ok': True, 'tag': 'a', 'url': 'http://127.0.0.1:9333/json',
                'fingerprint': 'captured'}
            self.tasks._dom = Mock(return_value={'ok': True, 'url': 'http://127.0.0.1:9333/json'})
            result = self.tasks.handle('request_commit', {'resolution_id': 1, 'handle': '@link'},
                                       session_id='session', turn_id=turn)
            self.assertFalse(result['ok'])
            self.session.actions.click.assert_not_called()

    def test_request_stop_does_not_revoke_another_turn(self):
        self.assertFalse(self.tasks.stop("foreign", "turn")["ok"])
        self.assertFalse(self.tasks._stopped.is_set())
        self.assertFalse(self.tasks.stop("session", "old")["ok"])
        self.assertTrue(self.tasks.stop("session", "turn")["ok"])
        self.assertTrue(self.tasks._stopped.is_set())
        self.assertTrue(self.tasks.begin("other", "next", self.owner)["ok"])
        self.assertFalse(self.tasks.stop("session", "turn")["ok"])
        self.assertFalse(self.tasks._stopped.is_set())

    def test_stop_latches_during_tool_without_claiming_rollback(self):
        import threading
        for dispatched in (False, True):
            with self.subTest(dispatched=dispatched):
                self.tasks.begin("session", str(dispatched), self.owner)
                entered, release = threading.Event(), threading.Event()
                results = []
                def blocked(*_):
                    entered.set()
                    self.assertTrue(release.wait(2))
                    if dispatched:
                        raise ConnectionError("mutation reply lost")
                    return None
                self.tasks._check_owner = lambda: None
                self.tasks._current = (lambda _: None) if dispatched else blocked
                self.tasks._dom = Mock(side_effect=blocked)
                worker = threading.Thread(target=lambda: results.append(self.tasks.handle(
                    "scroll", {"resolution_id": 1, "pixels": 100},
                    session_id="session", turn_id=str(dispatched))))
                worker.start()
                self.assertTrue(entered.wait(2))
                stop = threading.Thread(target=lambda: self.tasks.stop("session", str(dispatched)))
                stop.start()
                self.assertTrue(self.tasks._stopped.wait(2))
                release.set()
                worker.join(2)
                stop.join(2)
                self.assertFalse(worker.is_alive() or stop.is_alive())
                if dispatched:
                    self.assertEqual(results[0]["outcome"], "unknown")
                    self.assertIsNone(results[0]["executed"])
                    self.assertEqual(self.tasks._dom.call_count, 1)
                else:
                    self.assertFalse(results[0]["executed"])
                    self.tasks._dom.assert_not_called()

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
        from look.tests.browser_actions.browser_actions_production import run_turn
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
        from look.tests.browser_actions.browser_actions_production import runtime_credentials
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

    def destination_call(self, op, url, **extra):
        self.tasks._current = lambda _: None
        self.tasks._read = Mock(return_value={'ok': True})
        self.tasks.snapshot = {'resolution_id': 1}
        self.tasks._dom = Mock(return_value={'ok': True, 'url': url})
        self.session.actions._inspect.return_value = {
            'ok': True, 'tag': 'a', 'fingerprint': 'captured', 'url': url}
        self.session.actions.click.return_value = {'ok': True, 'executed': False}
        self.session.cdp.action_navigate.return_value = self.owner
        self.session.actions.reset_mock()
        self.session.cdp.action_navigate.reset_mock()
        return self.tasks.handle(op, {'resolution_id': 1, 'url': url, 'handle': '@link',
                                     'new_tab': False, **extra},
                                 session_id='session', turn_id='turn')

    def test_nonpublic_destinations_rejected_before_all_dispatch_paths(self):
        blocked = (
            '10.0.0.1', '172.16.0.1', '192.168.1.1', '127.0.0.1', '0.0.0.0',
            '169.254.169.254', '168.63.129.16', '192.0.0.192', '100.100.100.200', '100.64.0.1', '224.0.0.1',
            '240.0.0.1', '192.0.2.1', '[::]', '[::1]', '[fc00::1]', '[fe80::1]',
            '[ff02::1]', '[2001:db8::1]', '[::ffff:127.0.0.1]',
            '[::ffff:93.184.216.34]', 'localhost', 'LOCALHOST.', 'a.localhost',
            'printer.local', 'host.localdomain', '127.1', '2130706433',
            '0177.0.0.1', '0x7f000001', '0x7f.0.0.1',
            '127%2e0%2e0%2e1', '[fe80::1%25en0]', '-bad.test', 'bad..test',
            'example.test..', '[::1]example.test', 'example.test:',
            'faß.test', '１２７.０.０.１',
        )
        for op in ('navigate', 'open_tab', 'click', 'request_commit'):
            for host in blocked:
                with self.subTest(op=op, host=host):
                    result = self.destination_call(op, f'http://{host}/')
                    self.assertFalse(result['ok'])
                    self.assertFalse(result['executed'])
                    self.session.cdp.action_navigate.assert_not_called()
                    self.session.actions.click.assert_not_called()
                    self.session.actions.invalidate.assert_not_called()
                    if op in ('click', 'request_commit'):
                        self.tasks._dom.assert_called_once_with('actionLinkUrl', '@link', 'captured')

    def test_dns_is_fail_closed_including_mixed_answers_and_aliases(self):
        for answers in ([], ['10.0.0.1'], ['169.254.169.254'],
                        ['93.184.216.34', '127.0.0.1'],
                        ['2606:4700:4700::1111', '::ffff:93.184.216.34']):
            self.dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 80))
                                     for ip in answers]
            for op in ('navigate', 'open_tab', 'click', 'request_commit'):
                with self.subTest(op=op, answers=answers):
                    self.assertFalse(self.destination_call(op, 'http://alias.example/')['ok'])
                    self.session.cdp.action_navigate.assert_not_called()
                    self.session.actions.click.assert_not_called()
        self.dns.side_effect = socket.gaierror('unavailable')
        for allow_private in (False, True):
            with patch.object(service, '_CONFIG', GazeConfig(allow_private_network=allow_private)):
                for op in ('navigate', 'open_tab', 'click', 'request_commit'):
                    self.assertFalse(self.destination_call(op, 'https://example.test/')['ok'])
                    self.session.cdp.action_navigate.assert_not_called()
                    self.session.actions.click.assert_not_called()

    def test_public_destinations_dispatch_without_rewriting(self):
        url = 'https://example.test/watch?v=123#chapter'
        for op in ('navigate', 'open_tab', 'click', 'request_commit'):
            with self.subTest(op=op):
                self.assertTrue(self.destination_call(op, url)['ok'])
                if op in ('navigate', 'open_tab'):
                    self.session.cdp.action_navigate.assert_called_once_with(
                        url, new_tab=op == 'open_tab', **self.owner)
                else:
                    self.session.actions.click.assert_called_once_with('@link', 1,
                        force_confirmation=op == 'request_commit', skip_confirmation=False)
        self.assertTrue(self.destination_call('click', url, new_tab=True)['ok'])
        self.session.cdp.action_navigate.assert_called_once_with(url, new_tab=True, **self.owner)
        for url in ('https://93.184.216.34/', 'https://[2606:4700:4700::1111]/'):
            self.assertEqual(self.tasks._destination(url), url)

    def test_private_network_requires_strict_owner_opt_in_and_blocks_debugger(self):
        self.assertFalse(GazeConfig().allow_private_network)
        for value in (None, False, 0, 1, 'true', 'false', True):
            ctx = SimpleNamespace(get_config=lambda key, default:
                value if key == 'allow_private_network' else default)
            self.assertIs(GazeConfig.from_ctx(ctx).allow_private_network, value is True)
            self.assertIs(GazeConfig(allow_private_network=value).allow_private_network, value is True)
            with patch.object(service, '_CONFIG', SimpleNamespace(allow_private_network=value)):
                for op in ('navigate', 'open_tab', 'click', 'request_commit'):
                    result = self.destination_call(op, 'http://192.168.1.1/', allow_private_network=True)
                    self.assertIs(result['ok'], value is True)
        self.dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 8080))]
        with patch.object(service, '_CONFIG', GazeConfig(allow_private_network=True)):
            for op in ('navigate', 'open_tab', 'click', 'request_commit'):
                self.assertTrue(self.destination_call(op, 'http://localhost:8080/')['ok'])
                for host in ('127.0.0.1', '127.1', 'localhost', 'alias.example', '[::1]'):
                    with self.subTest(op=op, host=host):
                        self.assertFalse(self.destination_call(op, f'http://{host}:9333/json')['ok'])
                        self.session.cdp.action_navigate.assert_not_called()
                        self.session.actions.click.assert_not_called()

    def test_new_tab_links_and_allow_all_still_require_public_destinations(self):
        for allow_all in (False, True):
            self.tasks.grant['allow_all'] = allow_all
            self.session.actions._inspect.return_value = {
                'ok': True, 'tag': 'a', 'fingerprint': 'captured', 'new_tab': True,
                'url': 'http://10.0.0.1/'}
            self.tasks.snapshot = {'resolution_id': 1}
            self.tasks._current = lambda _: None
            self.tasks._dom = Mock(return_value={'ok': True, 'url': 'http://10.0.0.1/'})
            for op in ('click', 'request_commit'):
                self.session.actions.reset_mock()
                result = self.tasks.handle(op, dict(resolution_id=1, handle='@link', new_tab=True),
                                           session_id='session', turn_id='turn')
                self.assertFalse(result['ok'])
                self.session.cdp.action_navigate.assert_not_called()
                self.session.actions.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
