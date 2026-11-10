"""Actual plugin transport in disposable Chrome for Testing. No remote debugging/devices/providers.

Run: <test-python> tests/extension_chrome.py --chrome /absolute/CfT/executable
The temporary extension adds a fixture-only inspector/automatic local pairing entry.
Neither is present in the installed product extension. No personal profile is opened.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
import hashlib
import http.server
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import shutil
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # Package shell, not installed Hermes.
from tests.test_first_run import FirstRunTests
from tests.test_chrome_consent import until
from hermes_gaze import cli, service
from hermes_gaze.browser import extension as extension_transport, extension_host
from hermes_gaze.config import GazeConfig

HERE = Path(__file__).resolve().parents[1]
# The shipped public key keeps setup, relocation and the real Chrome origin in agreement.
KEY = json.loads((HERE / 'extension/manifest.json').read_text())['key']
EXTENSION = ''.join(chr(97 + int(c, 16)) for c in hashlib.sha256(base64.b64decode(KEY)).hexdigest()[:32])
PAGE = b'''<!doctype html><title>Look disposable adapter fixture</title>
<style>body{font:20px system-ui;padding:60px}button{padding:20px}</style>
<h1>Local fixture</h1><p id="target">The fixture price is 42 pounds.</p><button id="delete">Delete fixture</button>
<script>window.keys=[];for(const type of ['keydown','keyup','input','selectionchange'])document.addEventListener(type,e=>keys.push(e.key||String(getSelection())),true);
window.suppressedFocusEvents=0;for(const [node,type] of [[window,'blur'],[document,'visibilitychange']])node.addEventListener(type,e=>{window.suppressedFocusEvents++;e.stopImmediatePropagation()},true);
setInterval(()=>fetch('/status',{method:'POST',body:JSON.stringify({root:!!document.getElementById('hermes-gaze-root')})}),100);
document.querySelector('#delete').onclick=()=>fetch('/mutation',{method:'POST'});</script>'''


class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/gate':
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({'go': self.server.go}).encode())
            return
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        raw = self.rfile.read(min(int(self.headers.get('Content-Length', '0')), 16384))
        if self.path == '/mutation':
            self.server.mutations += 1
        elif self.path == '/status':
            self.server.status = json.loads(raw)
        elif self.path == '/error':
            self.server.error = raw.decode()
        elif self.path in ('/offer', '/result'):
            value = json.loads(raw)
            getattr(self.server, 'offers' if self.path == '/offer' else 'results')[value['client']] = value
        self.send_response(204); self.end_headers()

    def log_message(self, *_):
        pass


def fixture_worker(url, client='main', gated=False):
    # Test-only raw inspector and gesture driver. Production worker refuses these methods.
    return r'''
const fixtureRoot = root;
root = async (method, params) => {
  if (method === 'Test.command') {
    const tab = tabs.get(Number(params.target)) || [...tabs.values()][0];
    return direct(tab, params.method, params.params || {});
  }
  if (method === 'Test.background') { return {target: (await chrome.tabs.create({url: FIXTURE_URL, active:true})).id}; }
  if (method === 'Test.focus') { await chrome.tabs.update(Number(params.target), {active:true}); return {}; }
  if (method === 'Test.reload') { setTimeout(()=>chrome.runtime.reload(),50); return {}; }
  if (method === 'Test.client') return {client: FIXTURE_CLIENT};
  try { return await fixtureRoot(method, params); }
  catch(error) { await fetch(FIXTURE_URL+'error',{method:'POST',body:method+': '+error.message}); throw error; }
};
chrome.runtime.onInstalled.addListener(async details => {
  if (details.reason !== 'install') return;
  try {
    const tab = await chrome.tabs.create({url: FIXTURE_URL, active:true});
    for(let n=0;n<100 && (await chrome.tabs.get(tab.id)).status !== 'complete';n++) await new Promise(r=>setTimeout(r,50));
    const offer = await chrome.runtime.sendNativeMessage('org.look.companion', {op:'status'});
    if (FIXTURE_GATED) {
      await fetch(FIXTURE_URL+'offer',{method:'POST',body:JSON.stringify({client:FIXTURE_CLIENT,request:offer.request})});
      while (!(await (await fetch(FIXTURE_URL+'gate')).json()).go) await new Promise(r=>setTimeout(r,50));
    }
    try {
      await pair(offer.request, await chrome.tabs.get(tab.id));
      if (FIXTURE_GATED) await fetch(FIXTURE_URL+'result',{method:'POST',body:JSON.stringify({client:FIXTURE_CLIENT,ok:true,attached:tabs.has(tab.id)})});
    } catch(error) {
      if (!FIXTURE_GATED) throw error;
      await fetch(FIXTURE_URL+'result',{method:'POST',body:JSON.stringify({client:FIXTURE_CLIENT,ok:false,attached:tabs.has(tab.id)})});
    }
  } catch(error) {
    await fetch(FIXTURE_URL+'error',{method:'POST',body:error.stack});
  }
});
'''.replace('FIXTURE_URL', json.dumps(url)).replace('FIXTURE_CLIENT', json.dumps(client)).replace('FIXTURE_GATED', json.dumps(gated))


def scenario(chrome, mode, out=None):
    checks = []
    def check(name, value):
        assert value, name
        checks.append(name)
        print('PASS', mode, name, flush=True)
    with tempfile.TemporaryDirectory(prefix='look-extension-adapter-', dir='/tmp') as directory, ExitStack() as stack:
        directory = Path(directory)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Page)
        server.mutations, server.status, server.error = 0, {}, ''
        server.go, server.offers, server.results = False, {}, {}
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        stack.callback(server.server_close); stack.callback(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/'
        fixture = FirstRunTests()
        fixture.setUp()
        stack.callback(fixture.doCleanups)
        plugin, session, ctx, command, hooks = fixture.register(None)
        session.cdp._owned_chrome.profile = directory / 'lease'
        turns = ctx.turns
        stack.enter_context(patch.object(service, '_VOICE_TURNS', turns))
        stack.enter_context(patch.object(service, '_CONFIG', GazeConfig(early_highlight=False)))
        stack.enter_context(patch.object(service, '_LLM', None))
        stack.enter_context(patch.object(service, 'get_shared_session', return_value=session))
        stack.enter_context(patch.object(cli, 'get_shared_session', return_value=session))
        stack.enter_context(patch.object(cli, 'get_shared_server', return_value=Mock()))
        stack.enter_context(patch.object(plugin, '_handle_slash_command', wraps=cli._handle_slash_command))
        native = directory / 'native'
        profile = directory / 'profile'
        stack.enter_context(patch.object(extension_host, 'install_directory', return_value=native))
        stack.enter_context(patch.object(extension_host, 'manifest_directory', return_value=profile / 'NativeMessagingHosts'))
        transport = directory / 'transport'
        transport.mkdir(mode=0o700)
        stack.enter_context(patch.object(extension_host, 'runtime_directory', return_value=transport))
        stack.enter_context(patch.object(extension_transport, 'runtime_directory', return_value=transport))
        command('setup extension')
        check('setup_stages_native_host_and_fixed_extension_without_binding', (native / 'unpacked/manifest.json').is_file() and not turns.connected)
        command('setup extension')
        check('repeated_setup_retains_exact_origin', extension_host.configuration(native)['extension_id'] == EXTENSION)
        # Wrapper records only its own child PID; the real installed host main/framing/relay runs unchanged.
        wrapper = directory / 'host_entry.py'
        wrapper.write_text('import os,runpy\nfrom pathlib import Path\n'
                           + f'Path({str(directory / "host.pid")!r}).write_text(str(os.getpid()))\n'
                           + f'host=runpy.run_path({str(native / "host.py")!r})\n'
                           + f'host["main"].__globals__["runtime_directory"]=lambda: Path({str(transport)!r})\n'
                           + 'host["main"]()\n')
        launcher = native / 'host'
        launcher.write_text(launcher.read_text().replace(str(native / 'host.py'), str(wrapper)))
        result = command('start --extension', session_id='fixture-session', session_key='fixture-key', platform='fixture')
        root = session.cdp.chrome
        check('registered_plugin_creates_explicit_one_use_pairing', root.state == 'waiting' and
              root.generation not in result and root._capability not in result and not turns.connected)
        check('waiting_generation_refuses_setup_and_uninstall', cli._setup_extension()[0] == 1 and cli._setup_extension(remove=True)[0] == 1)
        extension = native / 'unpacked'
        manifest = json.loads((extension / 'manifest.json').read_text())
        manifest['host_permissions'] = [url + '*']  # Only the disposable error reporter needs this.
        (extension / 'manifest.json').write_text(json.dumps(manifest))
        gated = mode in ('competing', 'expiry', 'stop', 'stale')
        (extension / 'worker.js').write_text((extension / 'worker.js').read_text() + fixture_worker(url, gated=gated))
        args = [chrome, f'--user-data-dir={profile}', '--headless=new', '--no-first-run', '--no-default-browser-check',
                '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-default-apps',
                '--password-store=basic', '--use-mock-keychain', f'--disable-extensions-except={extension}',
                f'--load-extension={extension}', 'about:blank']
        check('no_remote_debugging_or_unsafe_extension_flags', not any('remote-debugging' in a or 'unsafe-extension' in a for a in args))
        with (directory / 'chrome.log').open('wb') as log:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
        if mode == 'competing':
            second_profile, second_extension = directory / 'profile-b', directory / 'extension-b'
            shutil.copytree(extension, second_extension)
            (second_extension / 'worker.js').write_text((HERE / 'extension/worker.js').read_text() + fixture_worker(url, client='other', gated=True))
            second_manifests = second_profile / 'NativeMessagingHosts'
            second_manifests.mkdir(parents=True)
            shutil.copyfile(profile / 'NativeMessagingHosts/org.look.companion.json', second_manifests / 'org.look.companion.json')
            second_args = [arg.replace(str(profile), str(second_profile)).replace(str(extension), str(second_extension)) for arg in args]
            with (directory / 'chrome-b.log').open('wb') as log:
                second = subprocess.Popen(second_args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
            def close_second():
                if second.poll() is None:
                    second.terminate()
                    try: second.wait(10)
                    except subprocess.TimeoutExpired: second.kill(); second.wait(5)
            stack.callback(close_second)
        def cleanup():
            session.close()
            if process.poll() is None:
                process.terminate()
                try: process.wait(10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(5)
        stack.callback(cleanup)
        try:
            if gated:
                until(lambda: len(server.offers) == (2 if mode == 'competing' else 1) or bool(server.error), 25)
                assert not server.error, server.error
                check('opening_popups_discovers_only_the_approved_conversation_without_attachment',
                      all(value['request'] == root.generation for value in server.offers.values()) and not root.live and not turns.connected)
                replacement = None
                if mode in ('stop', 'stale'):
                    command('stop')
                    if mode == 'stale':
                        command('start --extension', session_id='replacement-session', session_key='replacement-key', platform='fixture')
                        replacement = session.cdp.chrome
                elif mode == 'expiry':
                    root._expires = time.monotonic() - 1
                    until(lambda: root.state == 'failed')
                server.go = True  # Fixture-only Connect clicks; production never auto-pairs.
                until(lambda: len(server.results) == len(server.offers) or bool(server.error), 15)
                assert not server.error, server.error
                if mode == 'competing':
                    winners = [value for value in server.results.values() if value['ok']]
                    losers = [value for value in server.results.values() if not value['ok']]
                    check('competing_profile_clicks_consume_exactly_one_native_port', len(winners) == len(losers) == 1 and not losers[0]['attached'])
                    until(lambda: turns.connected)
                    check('winning_profile_port_and_exact_conversation_are_pinned',
                          root.command('Test.client')['client'] == winners[0]['client'] and turns.binding['session_id'] == 'fixture-session')
                    command('stop')
                    until(lambda: not root.live)
                else:
                    check(mode + '_rejects_late_click_without_debugger_attachment',
                          all(not value['ok'] and not value['attached'] for value in server.results.values()) and not root.live and not turns.connected)
                    if replacement:
                        check('stale_click_cannot_consume_replacement_conversation', replacement.state == 'waiting' and
                              extension_host.pending_request()['request'] == replacement.generation)
                command('stop')
                check('rejected_or_stopped_generation_does_not_reconnect', not turns.connected and not session.cdp.chrome.live)
                return checks
            until(lambda: turns.connected or bool(server.error), 25)
            assert not server.error, server.error
            check('real_chrome_native_host_pairs_exact_plugin_conversation', turns.binding['session_id'] == 'fixture-session')
            tab = next(t for t in session.cdp._tabs.values() if t.is_connected)
            target = tab._target_id
            owner = session.cdp._document_owner(tab)
            def raw(method, params=None):
                return root.command('Test.command', dict(target=target, method=method, params=params or {}))
            def evaluate(expression, context=None):
                params = dict(expression=expression, returnByValue=True, awaitPromise=True)
                if context: params['uniqueContextId'] = context.removeprefix(tab._ws.document_prefix)
                result = raw('Runtime.evaluate', params)
                assert 'exceptionDetails' not in result, result
                return result.get('result', {}).get('value')
            def key(code, text):
                for kind in ('keyDown', 'keyUp'):
                    raw('Input.dispatchKeyEvent', dict(type=kind, code=code, key=text))
            def click(selector):
                until(lambda: evaluate('(()=>{const a=window.__HERMES_GAZE_OVERLAY__,r=a.uiFrame.getBoundingClientRect(),d=a.debug();return Math.abs(r.y-d.frame.y)<1 && Math.abs(r.x-d.card.x)<1})()', tab._context_unique_id))
                card = tab._ui_frames['card'][1]
                point = evaluate(f'(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()', card)
                frame = evaluate('(()=>{const r=window.__HERMES_GAZE_OVERLAY__.uiFrame.getBoundingClientRect();return {x:r.x,y:r.y}})()', tab._context_unique_id)
                for kind in ('mousePressed', 'mouseReleased'):
                    raw('Input.dispatchMouseEvent', dict(type=kind, button='left', clickCount=1, x=point['x']+frame['x'], y=point['y']+frame['y']))
            for name, (_, context) in tab._ui_frames.items():
                check(name + '_opaque_script_disabled', evaluate('self.origin === "null" && (()=>{const s=document.createElement("script");s.textContent="window.fixtureScriptRan=true";document.body.append(s);return !window.fixtureScriptRan})()', context))
                evaluate('window.fixtureTimer=false;setTimeout(()=>window.fixtureTimer=true,0);true', context)
                time.sleep(.15)
                check(name + '_timers_disabled', evaluate('!window.fixtureTimer', context))
            check('website_cannot_access_isolated_api', evaluate('typeof window.__HERMES_GAZE_OVERLAY__ === "undefined"'))
            if mode == 'surface':
                raw('Input.dispatchMouseEvent', dict(type='mouseMoved', x=105, y=105))
                key(tab.overlay_config['hotkey'], 'Alt' if tab.overlay_config['hotkey'] == 'AltRight' else '`')
                card = tab._ui_frames['card'][1]
                until(lambda: evaluate('!!document.querySelector("#hg-input")', card))
                evaluate('document.querySelector("#hg-input").value="FORGED";document.querySelector("#hg-send").click();true', card)
                time.sleep(.1)
                check('synthetic_private_submission_rejected', not turns.items)
                click('#hg-input')
                until(lambda: evaluate('document.activeElement?.id==="hg-input" && document.hasFocus()', card))
                evaluate('document.querySelector("#hg-input").value="";true', card)
                raw('Input.insertText', dict(text='Explain this PRIVATE_QUESTION'))
                key('Enter', 'Enter')
                until(lambda: bool(turns.active) and ctx.inject_message.call_count == 1)
                check('trusted_private_input_reaches_actual_plugin_inbox', turns.active['utterance'] == 'Explain this PRIVATE_QUESTION' and ctx.inject_message.call_count == 1)
                run = turns.active
                turns.pre(session_id='fixture-session', turn_id='fixture-turn', user_message=run['wire'])
                turns.post(session_id='fixture-session', turn_id='fixture-turn', assistant_response='## Fixture\n\nPRIVATE_LOCAL_ANSWER')
                until(lambda: evaluate('document.body.textContent.includes("PRIVATE_LOCAL_ANSWER")', card))
                until(lambda: evaluate('getComputedStyle(document.querySelector(".card")).opacity === "1" && document.querySelector(".body").getBoundingClientRect().height > 0', card)
                      and evaluate('Number(window.__HERMES_GAZE_OVERLAY__.uiFrame.parentElement.style.opacity) > .99', tab._context_unique_id))
                check('answer_rendered_in_existing_private_renderer', True)
                evaluate('(()=>{const r=document.createRange();r.selectNodeContents(document.body);const s=getSelection();s.removeAllRanges();s.addRange(r);return true})()', card)
                check('page_cannot_read_answer_input_or_selection', evaluate('!document.body.textContent.includes("PRIVATE_LOCAL_ANSWER") && !String(getSelection()).includes("PRIVATE_LOCAL_ANSWER") && !JSON.stringify(keys).includes("PRIVATE_QUESTION")'))
                if out:
                    (out / 'extension-surface.png').write_bytes(base64.b64decode(raw('Page.captureScreenshot', {'format':'png'})['data']))
                capture_stream = Mock()
                def input_stream(**kwargs):
                    capture_stream.start.side_effect = lambda: kwargs['callback'](
                        b'\\0\\0' * 160, 160, SimpleNamespace(currentTime=1., inputBufferAdcTime=1.), False)
                    return capture_stream
                cancelled = []
                with patch.dict(sys.modules, {'sounddevice': SimpleNamespace(RawInputStream=input_stream)}):
                    captured = session.microphone.start('fixture-capture',
                        lambda: session.cdp.recording_loss(target, owner['browser_document']), on_cancel=cancelled.append)
                assert captured['ok'], captured
                second = root.command('Test.background')['target']
                until(lambda: bool(cancelled), 3)
                check('browser_api_focus_loss_cancels_native_capture_despite_suppressed_page_events',
                    'lost focus' in cancelled[0] and capture_stream.abort.called and capture_stream.close.called
                    and not session.microphone._audio and root.live and evaluate('suppressedFocusEvents > 0'))
                with unittest_error():
                    session.cdp.eval_js_once('window.fixtureBackgroundMutation=true', **dict(target=target, document=owner['browser_document'], route=owner['browser_route']))
                check('background_selected_tab_mutation_refused', not evaluate('!!window.fixtureBackgroundMutation'))
                with unittest_error():
                    tab._submit(tab._render_ui({'frame':'card','view':'compose','title':'BACKGROUND_PRIVATE_MARKER'}), 3)
                check('background_private_render_refused', not evaluate('document.body.textContent.includes("BACKGROUND_PRIVATE_MARKER")', card))
                time.sleep(4.2)
                check('background_liveness_does_not_destroy_selected_surface', evaluate('!!document.getElementById("hermes-gaze-root")'))
                root.command('Test.focus', {'target': target})
                old_route = tab._route_id
                evaluate('history.pushState({},"","/?route=1");history.back();true')
                until(lambda: tab._route_id >= old_route + 2)
                with unittest_error():
                    session.cdp.eval_js_once('window.fixtureStaleRoute=true', target=target, document=owner['browser_document'], route=owner['browser_route'])
                check('route_and_back_reject_old_action_owner', not evaluate('!!window.fixtureStaleRoute'))
                old_document = tab._context_unique_id
                raw('Page.navigate', {'url':url+'?document=2'})
                until(lambda: tab.is_connected and tab._context_unique_id != old_document and bool(tab._ui_frames), 15)
                with unittest_error():
                    session.cdp.eval_js_once('true', target=target, document=old_document)
                check('full_navigation_rearms_but_rejects_old_document', True)
                current = session.cdp._document_owner(tab)
                transferred = session.cdp.action_navigate(url+'?newtab=1', new_tab=True, **current)
                check('guarded_new_tab_transfers_only_from_exact_source', transferred['browser_target'] != target and transferred['browser_document'] != current['browser_document'])
                command('stop', session_id='fixture-session', session_key='fixture-key')
                until(lambda: server.status.get('root') is False)
                check('stop_removes_overlay_keeps_browser_and_revokes_binding', process.poll() is None and not turns.connected and not root.live)
            else:
                stream = Mock()
                session.microphone._stream = stream
                session.microphone._audio.extend(b'fixture-only-pcm')
                cancel = turns._speech_cancel = threading.Event()
                session.tasks.begin('fixture-session', 'fixture-turn', owner)
                # Actual pending approval on a real captured risky control, never approve it.
                session.tasks.authorize_call('fixture-session', 'fixture-turn')
                structure = session.tasks.handle('read', {}, session_id='fixture-session', turn_id='fixture-turn')
                assert structure['ok'], structure
                handle = next(c['handle'] for c in structure['controls'] if c.get('label') == 'Delete fixture')
                approval = session.actions.request_commit(handle, session.resolution_id)
                assert approval['confirmation_required'], approval
                pending = session.actions._pending
                card = tab._ui_frames['card'][1]
                until(lambda: evaluate('!!document.querySelector(".choice.yes")', card))
                evaluate('document.querySelector(".choice.yes").click();document.querySelector(".choice.yes").focus({preventScroll:true});true', card)
                key('Enter', 'Enter')
                check('synthetic_and_keyboard_approval_rejected', session.actions._pending is pending and server.mutations == 0)
                if mode == 'lost-reply':
                    with unittest_error():
                        tab.eval_js_once('fetch("/mutation",{method:"POST"});new Promise(()=>{})', .2, context_id=tab._context_unique_id)
                    until(lambda: server.mutations == 1)
                elif mode == 'worker-reload':
                    root.command('Test.reload')
                else:
                    os.kill(int((directory / 'host.pid').read_text()), signal.SIGTERM)
                until(lambda: not root.live and not turns.connected, 8)
                until(lambda: session.microphone._stream is None, 5)
                check('transport_loss_cancels_native_input_output_task_and_approval', cancel.is_set() and stream.close.called and session.tasks._stopped.is_set() and session.actions._pending is None and not session.microphone._audio)
                until(lambda: server.status.get('root') is False, 8)
                check('host_loss_teardown_fails_open_and_keeps_page', process.poll() is None)
                if mode == 'lost-reply':
                    with unittest_error(): tab.eval_js('fetch("/mutation",{method:"POST"})', .1)
                    time.sleep(.3)
                    check('lost_mutation_reply_executes_once_and_generation_never_reconnects', server.mutations == 1 and not root.live)
        except BaseException:
            if server.error:
                print('FIXTURE_WORKER_ERROR', server.error, file=sys.stderr)
            if root.live and 'raw' in locals():
                print('FIXTURE_DIAGNOSTIC', evaluate('window.__HERMES_GAZE_OVERLAY__?.debug()', tab._context_unique_id),
                      evaluate('({focus:document.hasFocus(),active:document.activeElement?.id,text:document.body.textContent})', tab._ui_frames['card'][1]), file=sys.stderr)
                if out:
                    (out / 'extension-failure.png').write_bytes(base64.b64decode(raw('Page.captureScreenshot', {'format':'png'})['data']))
            print((directory / 'chrome.log').read_text(errors='replace')[-8000:], file=sys.stderr)
            raise
    return checks


class unittest_error:
    def __enter__(self): return self
    def __exit__(self, kind, value, traceback):
        assert kind and issubclass(kind, (ConnectionError, RuntimeError, TimeoutError)), 'operation unexpectedly succeeded'
        return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chrome', required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.out: args.out.mkdir(parents=True, exist_ok=True)
    results = {mode: scenario(args.chrome, mode, args.out) for mode in (
        'surface', 'lost-reply', 'host-loss', 'worker-reload', 'competing', 'expiry', 'stop', 'stale')}
    if args.out:
        (args.out / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
