"""Actual Hermes tool-search dispatch + private Chrome; scripted local model, no API key/devices."""
from __future__ import annotations

import argparse
import atexit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import traceback
import urllib.request
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmark.browser_actions_production import (
    Fixtures, ProductionTools, FORM_ASK, MODEL, PROFILE, approve, count, oracle, run_turn, setup_home, until,
)


class LocalModel(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append({'path':self.path,'keys':list(body),
            'roles':[m.get('role') for m in body.get('messages', [])],
            'input_type':type(body.get('input')).__name__,'stream':body.get('stream')})
        try:
            assert self.path.endswith('/chat/completions'), self.path
            assert any(m.get('role') == 'user' for m in body.get('messages', [])), 'User message lost'
            agent = self.server.agents[-1]
            names = {t.get('function', t).get('name') for t in body.get('tools', [])}
            assert names <= agent.valid_tool_names, (names, agent.valid_tool_names)
            assert 'tool_call' in names and 'browser_exec' not in names
            phase = self.server.phase
            self.server.phase += 1
            tool_messages = [m for m in body['messages'] if m.get('role') == 'tool']
            name, args = 'tool_call', {}
            if phase == 0:
                args = {'calls': [{'name': 'browser_exec', 'arguments': {'code': 'untrusted code must not run'}}]}
            elif phase == 1:
                assert 'guarded' in str(tool_messages[-1]['content']).lower(), tool_messages[-1]
                name, args = 'tool_describe', {'names': ['gaze_fill', 'gaze_click', 'gaze_request_commit']}
            elif phase == 2:
                assert 'new_tab' in str(tool_messages[-1]['content']), tool_messages[-1]
                args = {'calls': [{'name': 'gaze_read', 'arguments': {}}]}
            elif phase == 3:
                info = json.loads(tool_messages[-1]['content'])
                assert info.get('ok') and len(info['fields']) == 9, info
                self.server.structure = info
                args = {'calls': [{'name': 'gaze_fill', 'arguments': {
                    'resolution_id': info['resolution_id'], 'entries': [
                        {'handle': f['handle'], 'text': PROFILE[f['label']]} for f in info['fields']]}}]}
            elif phase == 4:
                assert json.loads(tool_messages[-1]['content']).get('executed'), tool_messages[-1]
                info = self.server.structure
                submit = next(c for c in info['controls'] if c.get('form_submit'))
                args = {'calls': [{'name': 'gaze_request_commit', 'arguments': {
                    'resolution_id': info['resolution_id'], 'handle': submit['handle']}}]}
            else:
                assert phase == 5 and json.loads(tool_messages[-1]['content']).get('confirmation_required')
                name = None
            message = ({'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': f'call-{phase}', 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
                if name else {'role': 'assistant', 'content': '## Prepared\n\nReview the form in Chrome.'})
        except Exception:
            self.server.errors.append({'traceback': traceback.format_exc(), 'phase': self.server.phase,
                'roles': [m.get('role') for m in body.get('messages', [])],
                'stream': body.get('stream')})
            message = {'role': 'assistant', 'content': 'LOCAL DISPATCH CHECK FAILED'}
        name = bool(message.get('tool_calls'))
        finish = 'tool_calls' if name else 'stop'
        if body.get('stream'):
            delta = {k: v for k, v in message.items() if v is not None}
            if name:
                delta['tool_calls'][0]['index'] = 0
            chunks = [dict(id='local', object='chat.completion.chunk', created=1, model=MODEL,
                           choices=[{'index': 0, 'delta': delta, 'finish_reason': None}]),
                      dict(id='local', object='chat.completion.chunk', created=1, model=MODEL,
                           choices=[{'index': 0, 'delta': {}, 'finish_reason': finish}])]
            data = ''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n'
            content_type = 'text/event-stream'
        else:
            data = json.dumps({'id': 'local', 'object': 'chat.completion', 'created': 1, 'model': MODEL,
                'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
            content_type = 'application/json'
        encoded = data.encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    home = tempfile.mkdtemp(prefix='gaze-default-dispatch-')
    atexit.register(shutil.rmtree, home, ignore_errors=True)
    setup_home(home)
    os.environ['SHOTS'] = str(args.out.resolve())
    sys.path.insert(0, str(ROOT / 'tests' / 'ui_review'))
    from devlib import Rig
    import run_agent
    from tools.registry import registry
    real_agent = run_agent.AIAgent
    forbidden = Mock(return_value='{"ok":false,"error":"unsafe handler reached"}')
    registry.register(name='browser_exec', toolset='hermes_gaze',
        schema={'name':'browser_exec','description':'Forbidden fixture tool',
                'parameters':{'type':'object','properties':{'code':{'type':'string'}},'required':['code']}},
        handler=forbidden, check_fn=lambda: True, override=True)
    backend = ThreadingHTTPServer(('127.0.0.1', 0), LocalModel)
    backend.requests = []
    backend.agents, backend.errors, backend.phase = [], [], 0
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    import httpx
    from openai import OpenAI
    clients = []
    def local_client(self, client_kwargs, **kwargs):
        # Preserve the real AIAgent class and static helpers; script only provider I/O.
        backend.agents.append(self)
        def forward(request):
            local = urllib.request.Request(f'http://127.0.0.1:{backend.server_port}' + request.url.path,
                data=request.content, headers={'Content-Type':'application/json'}, method=request.method)
            with urllib.request.urlopen(local) as response:
                return httpx.Response(response.status, content=response.read(),
                                      headers={'Content-Type':response.headers['Content-Type']})
        client = OpenAI(**{**client_kwargs, 'api_key':'local-fixture-only',
                           'http_client':httpx.Client(transport=httpx.MockTransport(forward))})
        clients.append(client)
        return client
    rig = tools = None
    rows = []
    try:
        with Fixtures() as fixtures:
            os.environ['REVIEW_START_URL'] = fixtures.url('form')
            rig = Rig(scale=1)
            rig.tab = until(lambda: next((t for t in rig.session.cdp._tabs.values() if t.is_connected and t._ui_frames), None))
            rig.front(rig.tab)
            tools = ProductionTools(rig)
            tools.install_host_plugin()
            for ingress in ('terminal', 'typed', 'voice'):
                rig.goto(fixtures.url('form'))
                rig.aim('#form-heading')
                backend.phase = 0
                with patch.object(real_agent, '_create_openai_client', new=local_client):
                    row = run_turn(rig, tools, FORM_ASK, 'local-fixture-only', fixtures.origin, ingress=ingress)
                assert not backend.errors, backend.errors
                row['draft_correct'] = oracle(rig, 'form', rig.tab._target_id)[1]
                assert row['draft_correct'] and count(rig) == 0 and backend.phase == 6, row
                forbidden.assert_not_called()
                row['approval'] = approve(rig)
                assert all(row['approval'].values()), row
                row.update(scripted_local_backend=True, advertised_names_executable=True, raw_browser_blocked=True)
                rows.append(row)
                rig.session.tasks.stop()
        args.out.joinpath('dispatch-results.json').write_text(json.dumps(rows, indent=2))
        print('PASS default deferred dispatch: terminal, private typing and fake voice; real Hermes validation, guarded bridge, native Chrome writes and trusted approval; zero paid calls')
    finally:
        args.out.joinpath('dispatch-errors.json').write_text(json.dumps(backend.errors, indent=2))
        args.out.joinpath('dispatch-requests.json').write_text(json.dumps(backend.requests, indent=2))
        if tools:
            tools.close()
        if rig:
            rig.close()
        backend.shutdown()
        for client in clients:
            client.close()
        backend.server_close()
        thread.join()


if __name__ == '__main__':
    main()
