"""Actual action popup + native host + plugin, isolated CfT profile and fake delayed ASR.
Run: python tests/extension_setup_chrome.py --chrome PATH --headed --out /tmp/look-setup
Only this disposable Chrome exposes an ephemeral loopback inspector to the test driver.
"""
from __future__ import annotations
import argparse
import base64
from contextlib import ExitStack
import http.server
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests
from tests.test_first_run import FirstRunTests
from tests.extension_chrome import EXTENSION, Page
from tests.test_chrome_consent import until as wait_until
from hermes_gaze import cli
from hermes_gaze.audio import voice
from hermes_gaze.runtime import service
from hermes_gaze.browser import extension as transport, extension_host
from websockets.sync.client import connect

def until(predicate, timeout=10):
    value = None
    def ready():
        nonlocal value
        value = predicate()
        return bool(value)
    wait_until(ready, timeout)
    return value



class Driver:
    def __init__(self, url):
        self.ws, self.sequence = connect(url, max_size=8 * 1024 * 1024), 0

    def call(self, method, params=None, session=None):
        self.sequence += 1
        message = dict(id=self.sequence, method=method, params=params or {})
        if session:
            message['sessionId'] = session
        self.ws.send(json.dumps(message))
        while True:
            answer = json.loads(self.ws.recv(timeout=10))
            if answer.get('id') == self.sequence:
                assert 'error' not in answer, answer
                return answer.get('result', {})

    def evaluate(self, session, expression):
        answer = self.call('Runtime.evaluate', dict(expression=expression, returnByValue=True,
                                                   awaitPromise=True, userGesture=True), session)
        assert 'exceptionDetails' not in answer, answer
        return answer.get('result', {}).get('value')

    def targets(self):
        return self.call('Target.getTargets')['targetInfos']

    def attach(self, target):
        return self.call('Target.attachToTarget', dict(targetId=target, flatten=True))['sessionId']


def run(chrome, out, headed=False):
    checks = []
    def check(name, value):
        assert value, name
        checks.append(name)
        print('PASS', name, flush=True)
    with tempfile.TemporaryDirectory(prefix='look-popup-', dir='/tmp') as temp, ExitStack() as stack:
        directory = Path(temp)
        native, profile, runtime = (directory / name for name in ('native', 'profile', 'transport'))
        runtime.mkdir(mode=0o700)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Page)
        server.documents, server.status, server.mutations = [], {}, 0
        server.go, server.offers, server.results = False, {}, {}
        server.error = ''
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.server_close)
        stack.callback(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/'
        release = threading.Event()
        stack.callback(release.set)
        def load(model):
            assert release.wait(90)
            voice._WHISPER_MODELS[model] = object()
            return voice._WHISPER_MODELS[model]
        for module in (extension_host, transport):
            stack.enter_context(patch.object(module, 'runtime_directory', return_value=runtime))
        stack.enter_context(patch.object(extension_host, 'install_directory', return_value=native))
        stack.enter_context(patch.object(extension_host, 'manifest_directory', return_value=profile / 'NativeMessagingHosts'))
        stack.enter_context(patch.object(voice, '_WHISPER_MODELS', {}))
        stack.enter_context(patch.object(voice, 'apple_silicon_mac', return_value=False))
        stack.enter_context(patch.object(voice, 'prepare'))
        stack.enter_context(patch.object(voice, 'get_whisper_model', side_effect=load))
        fixture = FirstRunTests()
        stack.callback(fixture.doCleanups)
        plugin, session, ctx, command, _ = fixture.register(None, warm=True)
        session.cdp._owned_chrome.profile = directory / 'lease'
        for module in (service, cli):
            stack.enter_context(patch.object(module, 'get_shared_session', return_value=session))
        stack.enter_context(patch.object(service, '_VOICE_TURNS', ctx.turns))
        stack.enter_context(patch.object(cli, 'get_shared_server', return_value=Mock()))
        stack.enter_context(patch.object(plugin, '_handle_slash_command', wraps=cli._handle_slash_command))
        command('setup extension')
        wrapper = directory / 'host_entry.py'
        wrapper.write_text('import runpy\nfrom pathlib import Path\n'
                           + f'host=runpy.run_path({str(native / "host.py")!r})\n'
                           + f'host["main"].__globals__["runtime_directory"]=lambda: Path({str(runtime)!r})\n'
                           + 'host["main"]()\n')
        launcher = native / 'host'
        launcher.write_text(launcher.read_text().replace(str(native / 'host.py'), str(wrapper)))
        extension = native / 'unpacked'
        args = [chrome, f'--user-data-dir={profile}', *([] if headed else ['--headless=new']), '--no-first-run',
                '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
                '--disable-sync', '--disable-default-apps', '--password-store=basic', '--use-mock-keychain',
                '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                f'--disable-extensions-except={extension}', f'--load-extension={extension}',
                url]
        log = stack.enter_context((directory / 'chrome.log').open('wb'))
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
        def close():
            session.close()
            process.terminate()
            try: process.wait(10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(5)
            if out:
                (out / 'chrome.log').write_bytes((directory / 'chrome.log').read_bytes())
        stack.callback(close)
        active = profile / 'DevToolsActivePort'
        until(active.is_file, 15)
        port, endpoint = active.read_text().splitlines()[:2]
        driver = Driver(f'ws://127.0.0.1:{port}{endpoint}')
        stack.callback(driver.ws.close)
        worker_target = until(lambda: next((t for t in driver.targets()
            if t['type'] == 'service_worker' and t['url'] == f'chrome-extension://{EXTENSION}/worker.js'), None))
        worker = driver.attach(worker_target['targetId'])
        driver.call('Runtime.enable', session=worker)
        until(lambda: driver.evaluate(worker, 'typeof chrome !== "undefined" && !!chrome.runtime?.id'))
        # An ordinary local fixture; no accounts or external navigation.
        page_id = next(t['targetId'] for t in driver.targets() if t['type'] == 'page')
        page_session = driver.attach(page_id)
        driver.call('Page.enable', session=page_session)
        driver.call('Page.setDocumentContent', dict(frameId=driver.call('Page.getFrameTree', session=page_session)['frameTree']['frame']['id'],
                    html='<title>Local setup fixture</title><p>Fixture price: 42 pounds</p>'), page_session)
        def open_popup(owner=None):
            if headed:
                from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
                app = NSRunningApplication.runningApplicationWithProcessIdentifier_(process.pid)
                assert app is not None, f'disposable Chrome exited: {process.poll()}'
                app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                until(app.isActive)
                driver.evaluate(worker, f'chrome.windows.get({owner}).then(w=>chrome.windows.update(w.id,{{focused:true}}))'
                                if owner else 'chrome.windows.getLastFocused().then(w=>chrome.windows.update(w.id,{focused:true}))')
                until(lambda: driver.evaluate(worker, 'chrome.windows.getLastFocused().then(w=>w.focused)'))
            driver.call('Target.activateTarget', dict(targetId=page_id))
            driver.evaluate(worker, f'chrome.action.openPopup({{windowId:{owner}}}).then(()=>true)'
                            if owner else 'chrome.action.openPopup().then(()=>true)')
            target = until(lambda: next((t for t in driver.targets() if t['url'] == f'chrome-extension://{EXTENSION}/popup.html'), None))
            popup = driver.attach(target['targetId'])
            if headed:
                until(lambda: driver.evaluate(popup, 'document.hasFocus()'))
            return popup
        def state(popup):
            return driver.evaluate(popup, 'Object.fromEntries(["start","pair","add","stop","status"].map(id=>{const n=document.getElementById(id);return [id,{hidden:n.hidden,text:n.textContent,disabled:n.disabled}]}))')
        def snap(popup, name):
            if out:
                (out / (name + '.png')).write_bytes(base64.b64decode(driver.call('Page.captureScreenshot', session=popup)['data']))
        def close_popup(popup):
            driver.evaluate(popup, 'window.close()')
        def start():
            return command('start --extension', session_id='fixture', session_key='fixture-key', platform='fixture')
        def connect_popup(popup):
            point = driver.evaluate(popup, '(()=>{const r=document.getElementById("pair").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
            for kind in ('mousePressed', 'mouseReleased'):
                driver.call('Input.dispatchMouseEvent', dict(type=kind, button='left', clickCount=1, **point), popup)
            until(lambda: ctx.turns.connected, 25)
        popup = open_popup()
        if headed:
            check('focused_toolbar_popup_has_unfocused_normal_owner',
                  driver.evaluate(popup, '(async()=>document.hasFocus() && !(await chrome.windows.getCurrent()).focused)()'))
        until(lambda: not state(popup)['start']['hidden'])
        check('not_running_popup_shows_start_without_connect', state(popup)['pair']['hidden'])
        start()
        until(lambda: not state(popup)['pair']['hidden'])
        check('already_open_popup_discovers_pending_request', not ctx.turns.connected)
        snap(popup, 'pending')
        # First observed ownership must stay pinned even if a replacement appears.
        command('stop')
        start()
        until(lambda: state(popup)['pair']['hidden'])
        check('open_popup_cannot_retarget_replacement', not ctx.turns.connected)
        close_popup(popup)
        popup = open_popup()
        until(lambda: not state(popup)['pair']['hidden'])
        root = session.cdp.chrome
        root._expires = time.monotonic() - 1
        until(lambda: state(popup)['pair']['hidden'])
        check('expired_request_removes_connect', not ctx.turns.connected)
        close_popup(popup)
        # Two real normal windows: the popup must pin its own active tab.
        original_page = page_id
        other = driver.evaluate(worker, 'chrome.windows.create({url:' + json.dumps(url + '?second') + '}).then(w=>({id:w.id,tab:w.tabs[0].id}))')
        page_id = until(lambda: next((t['targetId'] for t in driver.targets() if t['url'] == url + '?second'), None))
        command('stop')
        start()
        popup = open_popup(other['id'])
        until(lambda: not state(popup)['pair']['hidden'])
        chosen = driver.evaluate(popup, 'selection')
        check('second_window_popup_pins_own_tab', chosen['id'] == other['tab'] and chosen['windowId'] == other['id'])
        connect_popup(popup)
        check('second_window_connect_attaches_only_own_tab',
              driver.evaluate(worker, '[...tabs.keys()]') == [other['tab']])
        command('stop')
        driver.evaluate(worker, f'chrome.windows.remove({other["id"]})')
        page_id = original_page
        command('stop')
        start()
        driver.call('Page.navigate', dict(url='chrome://extensions'), page_session)
        until(lambda: driver.evaluate(page_session, 'location.href') == 'chrome://extensions/')
        popup = open_popup()
        until(lambda: bool(state(popup)['status']['text']) and state(popup)['status']['text'] != 'Checking connection…')
        check('restricted_tab_has_no_connect_and_does_not_consume_request',
              state(popup)['pair']['hidden'] and not ctx.turns.connected)
        close_popup(popup)
        # Chrome enforces manifest incognito:not_allowed; no private popup is available.
        check('manifest_refuses_incognito_permission',
              driver.evaluate(worker, 'chrome.extension.isAllowedIncognitoAccess()') is False)
        driver.evaluate(worker, 'chrome.windows.create({incognito:true,url:' + json.dumps(url + '?private') + '}).then(()=>true)')
        private_page = until(lambda: next((t['targetId'] for t in driver.targets() if t['url'] == url + '?private'), None))
        driver.call('Target.activateTarget', dict(targetId=private_page))
        check('incognito_window_hidden_from_extension',
              driver.evaluate(worker, 'chrome.tabs.query({}).then(ts=>ts.every(t=>!t.incognito))') and not ctx.turns.connected)
        driver.call('Target.closeTarget', dict(targetId=private_page))
        driver.call('Page.navigate', dict(url=url), page_session)
        until(lambda: driver.evaluate(page_session, 'document.readyState === "complete" && location.href === ' + json.dumps(url)))
        command('stop')
        start()
        popup = open_popup()
        until(lambda: not state(popup)['pair']['hidden'])
        driver.evaluate(popup, 'document.getElementById("pair").click()')
        check('synthetic_popup_click_cannot_pair', not ctx.turns.connected)
        connect_popup(popup)
        check('trusted_popup_click_pairs_actual_plugin_and_host', ctx.turns.binding['session_id'] == 'fixture')
        check('pending_recognition_is_typed_only', session.cdp._inbox_event['recognition']['ready'] is False)
        tab = until(lambda: next((t for t in session.cdp._tabs.values() if t.is_connected and t._ui_frames), None))
        def private_words():
            words = []
            for _, context in tab._ui_frames.values():
                words.append(tab._submit(tab._eval_coro('document.body.innerText', 5, context_id=context), 7) or '')
            return '\n'.join(words)
        until(lambda: 'Preparing local speech recognition' in private_words())
        check('pending_hint_reaches_protected_renderer', True)
        def key(code, text):
            for kind in ('keyDown', 'keyUp'):
                driver.call('Input.dispatchKeyEvent', dict(type=kind, code=code, key=text), page_session)
        key('AltRight', 'Alt')
        card_context = tab._ui_frames['card'][1]
        until(lambda: tab._submit(tab._eval_coro('!!document.querySelector("#hg-input")', 5, context_id=card_context), 7))
        release.set()
        until(lambda: session.cdp._inbox_event['recognition']['ready'])
        check('readiness_does_not_replace_active_composer', 'Speech recognition is ready' not in private_words())
        key('Escape', 'Escape')
        until(lambda: 'Speech recognition is ready' in private_words())
        check('completed_asr_announces_readiness_without_host_post_message', True)
        popup = open_popup()
        until(lambda: not state(popup)['stop']['hidden'])
        check('active_popup_offers_disconnect_not_connect', state(popup)['pair']['hidden'])
        snap(popup, 'connected')
        close_popup(popup)
        command('stop')
        (extension / 'popup.js').write_text('throw Error("Stale fixture popup");')
        check('stopped_staging_update_succeeds', cli._setup_extension()[0] == 0)
        launcher.write_text(launcher.read_text().replace(str(native / 'host.py'), str(wrapper)))
        driver.call('Page.navigate', dict(url='chrome://extensions'), page_session)
        toolbar = 'document.querySelector("extensions-manager").shadowRoot.querySelector("extensions-toolbar").shadowRoot'
        until(lambda: driver.evaluate(page_session, '!!document.querySelector("extensions-manager")?.shadowRoot?.querySelector("extensions-toolbar")?.shadowRoot'))
        def click_ui(expression):
            point = driver.evaluate(page_session, '(()=>{const n=' + expression + ';const r=n.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
            for kind in ('mousePressed', 'mouseReleased'):
                driver.call('Input.dispatchMouseEvent', dict(type=kind, button='left', clickCount=1, **point), page_session)
        if not driver.evaluate(page_session, toolbar + '.querySelector("#devMode").checked'):
            click_ui(toolbar + '.querySelector("#devMode")')
        item = 'document.querySelector("extensions-manager").shadowRoot.querySelector("extensions-item-list").shadowRoot.querySelector("#' + EXTENSION + '")'
        until(lambda: driver.evaluate(page_session, '!!(' + item + ')?.shadowRoot?.querySelector("#dev-reload-button")'))
        driver.call('Target.detachFromTarget', dict(sessionId=worker))
        click_ui(item + '.shadowRoot.querySelector("#dev-reload-button")')
        until(lambda: driver.evaluate(page_session, '(' + item + ').data.state === "ENABLED"'))
        check('extension_reload_leaves_binding_stopped', not ctx.turns.connected)
        # Restart only our disposable process, exercising the staged files from disk.
        driver.ws.close()
        process.terminate()
        process.wait(10)
        active.unlink(missing_ok=True)
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
        until(active.is_file, 15)
        port, endpoint = active.read_text().splitlines()[:2]
        driver = Driver(f'ws://127.0.0.1:{port}{endpoint}')
        stack.callback(driver.ws.close)
        wake = driver.call('Target.createTarget', dict(url=f'chrome-extension://{EXTENSION}/popup.html'))['targetId']
        wake_session = driver.attach(wake)
        until(lambda: driver.evaluate(wake_session, 'document.readyState === "complete"'))
        replacement = until(lambda: next((t for t in driver.targets() if
            t['url'] == f'chrome-extension://{EXTENSION}/worker.js'), None))
        worker = driver.attach(replacement['targetId'])
        driver.call('Runtime.enable', session=worker)
        until(lambda: driver.evaluate(worker, 'typeof chrome !== "undefined" && !!chrome.runtime?.id'))
        driver.call('Target.closeTarget', dict(targetId=wake))
        page_id = next(t['targetId'] for t in driver.targets() if t['type'] == 'page' and t['url'] == url)
        popup = open_popup()
        until(lambda: not state(popup)['start']['hidden'])
        start()
        until(lambda: not state(popup)['pair']['hidden'])
        check('restaged_reloaded_extension_discovers_fresh_start', not ctx.turns.connected)
        close_popup(popup)
        command('stop')
        if out:
            (out / 'results.json').write_text(json.dumps(checks, indent=2) + '\n')
        return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chrome', required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--headed', action='store_true')
    args = parser.parse_args()
    if args.out: args.out.mkdir(parents=True, exist_ok=True)
    print(json.dumps(run(args.chrome, args.out, args.headed), indent=2))
