"""The companion session cannot acquire generic code/debugger authority."""
from concurrent.futures import ThreadPoolExecutor
import json
import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze import service, voice


class BrowserToolGuardTests(unittest.TestCase):
    def test_connected_session_excludes_code_and_vetoes_raw_calls(self):
        name = 'hermes_gaze.guard_entry'
        loader = importlib.machinery.SourceFileLoader(name, str(Path(__file__).parents[1] / '__init__.py'))
        spec = importlib.util.spec_from_loader(name, loader, is_package=False)
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)
        hooks, middleware = {}, {}
        ctx = SimpleNamespace(get_config=lambda name, default: default,
            register_system_prompt_section=Mock(), register_tool=Mock(),
            register_hook=lambda name, callback: hooks.update({name: callback}),
            register_middleware=lambda name, callback: middleware.update({name: callback}),
            register_command=Mock(), register_cli_command=Mock(), register_skill=Mock(), on_unload=Mock())
        session = GazeSession('http://127.0.0.1:1')
        self.addCleanup(session.close)
        with patch.object(plugin, 'get_shared_session', return_value=session), \
             patch.object(plugin, 'get_shared_server', return_value=Mock()), \
             patch.object(voice, 'prewarm'), patch.object(service, '_VOICE_TURNS', None), \
             patch.object(service, '_CONFIG', None):
            plugin.register(ctx)
            turns = service._VOICE_TURNS
            turns.bind(session_key='key', session_id='connected')
            guard = hooks['pre_tool_call']
            for tool in ('browser_exec', 'browser_cdp', 'terminal', 'execute_code', 'tool_call', 'delegate_task', 'gaze_confirm'):
                with self.subTest(tool=tool):
                    self.assertEqual(guard(tool_name=tool, session_id='connected', turn_id='t')['action'], 'block')
                    self.assertIsNone(guard(tool_name=tool, session_id='unrelated', turn_id='t'))
            self.assertIsNone(guard(tool_name='gaze_read', session_id='connected', turn_id='t'))
            request = {'tools': [{'type': 'function', 'function': {'name': name}} for name in ('browser_exec', 'terminal', 'web_search')]}
            reduced = middleware['llm_request'](request, session_id='connected')['request']['tools']
            names = {tool['function']['name'] for tool in reduced}
            self.assertTrue({'gaze_read', 'gaze_fill', 'gaze_request_commit', 'web_search'} <= names)
            self.assertFalse({'browser_exec', 'terminal', 'tool_call', 'delegate_task'} & names)
            session.tasks.begin('connected', 't', owner={
                'browser_target': 'tab', 'browser_document': 'doc', 'browser_route': 0})
            # Hermes policy callbacks run on bounded workers, not the executor.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(guard, tool_name='gaze_read', session_id='connected', turn_id='t').result()
            self.assertNotEqual(session.tasks._authorized('connected'), '')
            execute = middleware['tool_execution']
            self.assertEqual(execute(lambda: session.tasks._authorized('connected'),
                                    tool_name='gaze_read', session_id='connected', turn_id='t'), '')
            self.assertNotEqual(session.tasks._authorized('connected'), '')
            forbidden = Mock()
            blocked = execute(forbidden, tool_name='browser_exec', session_id='connected', turn_id='t')
            self.assertFalse(json.loads(blocked)['ok'])
            forbidden.assert_not_called()
            turns.bind('disconnect', session_key='key', session_id='connected')
            self.assertIsNone(guard(tool_name='browser_exec', session_id='connected', turn_id='t'))
            self.assertIsNone(middleware['llm_request'](request, session_id='connected'))


if __name__ == '__main__':
    unittest.main()
