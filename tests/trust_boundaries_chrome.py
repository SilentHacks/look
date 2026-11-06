"""One hostile-page sample per trust-boundary regression; never attaches owner Chrome.
Run: .venv/bin/python tests/trust_boundaries_chrome.py
Uses fake audio/model/host for deterministic security probes; real CDP trusted input.
"""
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tests
from hermes_gaze import service, voice
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.config import GazeConfig
from hermes_gaze.resolver.cursor_context import cursor_result
from hermes_gaze.voice_turns import VoiceTurns



def until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Chrome scenario deadline exceeded')


def command(tab, method, params):
    return tab._submit(tab._send_cmd(method, params, timeout=5), 7)


def page(tab, expression):
    result = command(tab, 'Runtime.evaluate', {'expression': '(() => {' + expression + '})()',
        'returnByValue': True, 'awaitPromise': True})
    assert not result.get('exceptionDetails'), result
    return result.get('result', {}).get('value')


def drain(tab):
    tab._handler_pool.submit(lambda: None).result(30)


def node(tab, selector, expression):
    tree = command(tab, 'DOM.getDocument', {'depth': -1, 'pierce': True})
    wanted = selector.removeprefix('#')
    def search(value):
        if isinstance(value, dict):
            attrs = value.get('attributes', [])
            attributes = dict(zip(attrs[::2], attrs[1::2]))
            if (selector.startswith('#') and attributes.get('id') == wanted or
                    selector.startswith('.') and selector[1:] in attributes.get('class', '').split()):
                return value.get('backendNodeId')
            for child in value.values():
                found = search(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = search(child)
                if found:
                    return found
    backend = search(tree)
    if not backend:
        return None
    obj = command(tab, 'DOM.resolveNode', {'backendNodeId': backend,
        'executionContextId': tab._ui_context_id})['object']['objectId']
    try:
        result = command(tab, 'Runtime.callFunctionOn', {'objectId': obj,
            'functionDeclaration': 'function(){if(!this.isConnected)return;' + expression + '}', 'returnByValue': True})
        assert not result.get('exceptionDetails'), result
        return result['result'].get('value')
    finally:
        command(tab, 'Runtime.releaseObject', {'objectId': obj})


def click(tab, selector):
    r = until(lambda: node(tab, selector, 'const r=this.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}'))
    frame = tab.eval_js('(()=>{const r=window.__HERMES_GAZE_OVERLAY__.uiFrame.getBoundingClientRect();return {x:r.x,y:r.y}})()')
    for kind in ('mousePressed', 'mouseReleased'):
        command(tab, 'Input.dispatchMouseEvent', {'type': kind, 'button': 'left', 'clickCount': 1,
            'x': r['x'] + frame['x'], 'y': r['y'] + frame['y']})
    # UI events first travel to the main isolated world, then enter its intent FIFO.
    time.sleep(.15)
    drain(tab)


def aim(tab, selector):
    page(tab, 'const r=document.querySelector(' + json.dumps(selector) + ').getBoundingClientRect();'
        'window.dispatchEvent(new MouseEvent("mousemove",{clientX:r.left+2,clientY:r.top+2}));')


def capture(tab):
    data = tab.eval_js('window.__HERMES_GAZE_OVERLAY__.captureCursorContext()')
    data.update(browser_target=tab._target_id, browser_document=tab._context_unique_id, browser_route=tab._route_id)
    return data


streams = []
class FakeInput:
    def __init__(self, **kwargs):
        self.callback, self.closed = kwargs['callback'], False
        streams.append(self)
    def start(self):
        self.callback(b'\x01\x00' * 160, 160, SimpleNamespace(currentTime=1., inputBufferAdcTime=1.), None)
    def stop(self): pass
    def abort(self): pass
    def close(self): self.closed = True


with tempfile.TemporaryDirectory(prefix='hermes-trust-chrome-') as tmp:
    chrome = subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '--remote-debugging-port=0', f'--user-data-dir={tmp}', '--no-first-run',
        '--no-default-browser-check', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = None
    try:
        # Discover only the port published by OUR private profile, never an existing browser.
        active_port = Path(tmp) / 'DevToolsActivePort'
        until(active_port.exists)
        port = int(active_port.read_text().splitlines()[0])
        session = GazeSession(f'http://127.0.0.1:{port}')
        assert session.cdp.connect()
        def new_tab():
            request = urllib.request.Request(session.cdp_http_url + '/json/new?about:blank', method='PUT')
            with urllib.request.urlopen(request) as response: target = json.load(response)['id']
            return until(lambda: (tab if (tab := session.cdp._tabs.get(target)) and tab.is_connected else None))
        a, b = new_tab(), new_tab()
        command(a, 'Page.bringToFront', {})
        command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': True})
        command(b, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
        page(a, '''document.body.innerHTML='<button id="danger">Delete sample</button><a id="secret" href="https://alice:password@example.invalid/export?access_token=VERY_SECRET#private_key">Download export</a>';
            window.project='A';window.deleted=[];document.querySelector('#danger').onclick=()=>deleted.push(project);
            window.keys=[];window.addEventListener('keydown',e=>keys.push(e.key),true);''')
        injected = []
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda text, **kw: injected.append(text) or True), session)
        turns.bind(session_key='private', session_id='private-session')
        replies = []
        def handle(intent, reply):
            service.handle_intent(intent, lambda result: (replies.append({'type': intent['type'], **result}), reply(result)))
        session.cdp.set_intent_handler(handle)
        with patch.object(service, 'get_shared_session', return_value=session), \
             patch.object(service, '_VOICE_TURNS', turns), patch.object(service, '_CONFIG', GazeConfig()):
            assert page(a, 'return document.querySelector("#hermes-gaze-root").shadowRoot') is None
            assert page(a, 'return typeof window.__HERMES_GAZE_OVERLAY__+":"+typeof window.__hermesGazeIntent') == 'undefined:undefined'
            boundary = page(a, 'try {return {readable:!!window.frames[0].document,frames:frames.length}}catch(e){return {error:e.name,frames:frames.length}}')
            assert boundary.get('error') == 'SecurityError' or boundary['frames'] == 0, boundary
            assert a.eval_js('(()=>{try{window.__HERMES_GAZE_OVERLAY__.uiFrame.contentWindow.document;return false}catch(e){return e.name}})()') == 'SecurityError'
            node(a, '#hg-input', 'this.value="FORGED_MESSAGE";return true')
            node(a, '#hg-send', 'this.click();return true')
            drain(a)
            assert injected == []
            click(a, '#hg-input')
            command(a, 'Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Q', 'code': 'KeyQ', 'text': 'Q'})
            command(a, 'Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Q', 'code': 'KeyQ'})
            assert page(a, 'return keys') == []
            page(a, 'document.body.tabIndex=-1;document.body.focus()')
            print('PASS 1: page cannot reach UI/API/binding; synthetic Ask rejected; no host injection')

            event = dict(sequence=100, request_id='private-A', resolution_id=100, status='complete',
                         text='PRIVATE_A_PAYROLL_7391', browser_target=a._target_id, browser_document=a._context_unique_id)
            session.display_session_event(event)
            until(lambda: node(a, '#hg-reply', 'return this.textContent') == event['text'])
            assert b.session_event is None
            assert 'PRIVATE_A_PAYROLL_7391' not in (node(b, '#hg-reply', 'return this.textContent') or '')
            command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
            command(b, 'Page.bringToFront', {})
            command(b, 'Emulation.setFocusEmulationEnabled', {'enabled': True})
            waiting = {**event, 'sequence': 101, 'resolution_id': 101, 'text': 'PRIVATE_A_WAITING'}
            session.display_session_event(waiting)
            assert node(a, '#hg-reply', 'return this.textContent') == event['text']
            assert b.session_event is None
            command(b, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
            command(a, 'Page.bringToFront', {})
            command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': True})
            until(lambda: node(a, '#hg-reply', 'return this.textContent') == waiting['text'])
            node(a, '#hg-reply', 'const r=document.createRange();r.selectNodeContents(this);getSelection().removeAllRanges();getSelection().addRange(r);return true')
            assert 'PRIVATE_A_PAYROLL_7391' not in page(a, 'return String(getSelection())')
            print('PASS 2: only source receives reply; background receives nothing; parent selection cannot read reply')

            aim(a, '#secret')
            data = capture(a)
            packet = cursor_result(data, 'What is this export?')['context']
            for secret in ('alice', 'password', 'VERY_SECRET', 'private_key'):
                assert secret not in json.dumps(data) and secret not in packet
            assert 'https://example.invalid/export' in packet
            print('PASS 6: URL credentials, all query parameters and fragments absent from wire and model context')

            aim(a, '#danger')
            data = capture(a)
            snapshot = cursor_result(data, 'Delete this sample')
            snapshot.update(browser_target=a._target_id, browser_document=a._context_unique_id, utterance='Delete this sample')
            rid = session.store_hover_snapshot(snapshot)
            hid = next(k for k,v in data['handles'].items() if v.get('label') == 'Delete sample')
            assert session.actions.highlight([hid], rid)['ok']
            assert session.actions.click(hid, rid)['confirmation_required']
            pending = dict(session.actions._pending)
            page(a, 'window.project="B";history.pushState({},"","#projectB")')
            until(lambda: a._route_id > 0)
            assert not session.actions.confirm(pending['action_id'], rid, True)['ok']
            assert page(a, 'return deleted') == []
            assert session.actions.highlight([hid], rid)['ok']
            page(a, 'history.replaceState({},"","about:blank")')
            until(lambda: a._route_id > 1)
            assert not session.actions.click(hid, rid)['ok']
            print('PASS 3: route reuse and return to original URL revoke action authority; read-only highlights still work')

            # Earlier website capture listener hides keyup; native deadline must still close.
            page(a, 'window.addEventListener("keyup",e=>{if(e.code==="Space")e.stopImmediatePropagation()},true)')
            assert a._submit(a._on_new_context(force=True), 20)
            with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=FakeInput)):
                command(a, 'Input.dispatchKeyEvent', {'type':'keyDown','key':' ','code':'Space','windowsVirtualKeyCode':32})
                drain(a)
                assert session.microphone._stream is not None
                command(a, 'Input.dispatchKeyEvent', {'type':'keyUp','key':' ','code':'Space','windowsVirtualKeyCode':32})
                time.sleep(.2)
                assert session.microphone._stream is not None
                until(lambda: session.microphone._stream is None, seconds=32)
                assert streams[-1].closed and session.microphone._audio == bytearray()
            print('PASS 5: suppressed release remains open briefly, then native 30s cap closes and discards capture')

            turns.close()
            service._VOICE_TURNS = None
            replies.clear()
            switch_on_answer = [True]
            def one_shot_model(**kwargs):
                if switch_on_answer[0]:
                    switch_on_answer[0] = False
                    command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
                    command(b, 'Page.bringToFront', {})
                    command(b, 'Emulation.setFocusEmulationEnabled', {'enabled': True})
                return SimpleNamespace(text='ONE_SHOT_ANSWER_MARKER', parsed={'handles': []})
            with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=FakeInput)), \
                 patch.object(service, '_LLM', SimpleNamespace(complete_structured=one_shot_model)), \
                 patch.object(voice, 'transcribe_audio_buffer', return_value=('What is this export?', [])):
                aim(a, '#secret')
                # Use trusted mic clicks; the hostile keyup listener is still installed.
                click(a, '#hg-mic-btn')
                assert session.microphone._stream is not None
                click(a, '#hg-mic-btn')
                stop = until(lambda: next((r for r in replies if r['type']=='record_stop'), None))
                assert stop['ok'] and stop['delivery']=='one_shot', stop
                assert 'ONE_SHOT_ANSWER_MARKER' not in node(a, '#hg-reply', 'return this.textContent')
                command(b, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
                command(a, 'Page.bringToFront', {})
                command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': True})
                until(lambda: 'ONE_SHOT_ANSWER_MARKER' in (node(a, '#hg-reply', 'return this.textContent') or ''))
                assert node(a, '#hg-lock-label', 'return this.textContent') == 'complete'
                session.configure(mode='hover')
                assert 'ONE_SHOT_ANSWER_MARKER' in node(a, '#hg-reply', 'return this.textContent')
                print('PASS 7: disconnected voice displays actual one-shot answer, not queued')
                replies.clear()
                session.configure(mode='simulated')
                click(a, '#hg-mic-btn'); click(a, '#hg-mic-btn')
                stop = until(lambda: next((r for r in replies if r['type']=='record_stop'), None))
                assert stop['ok'] and stop['mode']=='simulated', stop
                assert 'No DOM candidates' not in json.dumps(stop)
                print('PASS 8: simulated voice freezes candidates and pointer at release and resolves successfully')
                session.configure(mode='hover')
                def key(code, key_name=None):
                    for kind in ('keyDown', 'keyUp'):
                        command(a, 'Input.dispatchKeyEvent', {'type': kind, 'code': code,
                            'key': key_name or code, 'windowsVirtualKeyCode': 13 if code == 'Enter' else 0,
                            'text': '\r' if kind == 'keyDown' and code == 'Enter' else ''})
                        time.sleep(.1)
                    drain(a)
                aim(a, '#secret')
                node(a, '#hg-lock-btn', 'this.focus();return true')
                before = a.eval_js('window.__HERMES_GAZE_OVERLAY__.state.armed')
                key('Enter')
                until(lambda: a.eval_js('window.__HERMES_GAZE_OVERLAY__.state.armed') != before)
                node(a, '#hg-tuck-btn', 'this.focus();return true')
                key('Enter')
                until(lambda: a.eval_js('window.__HERMES_GAZE_OVERLAY__.state.tucked'))
                key('Enter')
                until(lambda: not a.eval_js('window.__HERMES_GAZE_OVERLAY__.state.tucked'))
                node(a, '#hg-input', 'this.value="What is this export?";return true')
                node(a, '#hg-send', 'this.focus();return true')
                replies.clear()
                key('Enter')
                until(lambda: any(r['type'] == 'submit' and r.get('delivery') == 'one_shot' for r in replies))
                node(a, '#hg-mic-btn', 'this.focus();return true')
                key('Enter')
                until(lambda: session.microphone._stream is not None)
                key('Enter')
                until(lambda: session.microphone._stream is None)
                node(a, '#hg-lock-btn', 'this.focus();return true')
                before = a.eval_js('window.__HERMES_GAZE_OVERLAY__.state.armed')
                key('AltRight', 'Alt')
                until(lambda: a.eval_js('window.__HERMES_GAZE_OVERLAY__.state.armed') != before)
                node(a, '#hg-mic-btn', 'this.focus();return true')
                command(a, 'Input.dispatchKeyEvent', {'type': 'keyDown', 'code': 'Space', 'key': ' ', 'windowsVirtualKeyCode': 32})
                until(lambda: session.microphone._stream is not None)
                command(a, 'Input.dispatchKeyEvent', {'type': 'keyUp', 'code': 'Space', 'key': ' ', 'windowsVirtualKeyCode': 32})
                until(lambda: session.microphone._stream is None)
                key('Escape')
                until(lambda: node(a, '#hg-reply', 'return this.style.display') == 'none')
                print('PASS review: iframe shortcuts and Space release work; native Enter activates Ask/Speak/Lock/Minimize')
            session.configure(mode='hover')

            # Fresh snapshot: normal trusted confirmation remains single-use.
            aim(a, '#danger'); data = capture(a)
            snapshot = cursor_result(data, 'Delete this sample')
            hid = next(k for k, v in data['handles'].items() if v.get('label') == 'Delete sample')
            snapshot.update(browser_target=a._target_id, browser_document=a._context_unique_id, utterance='Delete this sample')
            rid = session.store_hover_snapshot(snapshot)
            assert session.actions.click(hid, rid)['confirmation_required']
            # Find the confirmation control through privileged CDP only.
            def confirm_id():
                # UI ids are private, but the DOM backend can inspect them without a production debug API.
                tree = command(a, 'DOM.getDocument', {'depth':-1,'pierce':True})
                def walk(v):
                    if isinstance(v,dict):
                        if v.get('nodeName')=='BUTTON' and any(c.get('nodeValue')=='Confirm action' for c in v.get('children',[])):
                            return v.get('backendNodeId')
                        for c in v.values():
                            if (r:=walk(c)): return r
                    elif isinstance(v,list):
                        for c in v:
                            if (r:=walk(c)): return r
                return walk(tree)
            backend = until(confirm_id)
            obj = command(a,'DOM.resolveNode',{'backendNodeId':backend,'executionContextId':a._ui_context_id})['object']['objectId']
            r=command(a,'Runtime.callFunctionOn',{'objectId':obj,'functionDeclaration':'function(){this.click();const r=this.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}}','returnByValue':True})['result']['value']
            drain(a);assert page(a,'return deleted')==[]
            frame=a.eval_js('(()=>{const r=window.__HERMES_GAZE_OVERLAY__.uiFrame.getBoundingClientRect();return {x:r.x,y:r.y}})()')
            Path('/tmp/hermes-trust-confirmation.png').write_bytes(base64.b64decode(
                command(a, 'Page.captureScreenshot', {'format': 'png'})['data']))
            for kind in ('mousePressed','mouseReleased'):
                command(a,'Input.dispatchMouseEvent',{'type':kind,'button':'left','clickCount':1,'x':frame['x']+r['x'],'y':frame['y']+r['y']})
            until(lambda: page(a,'return deleted.length')==1)
            assert page(a,'return deleted')==['B']
            assert not session.actions.confirm(pending['action_id'],rid,True)['ok']
            print('PASS normal: trusted confirmation executes once; synthetic consent remains rejected')

            page(a,'document.body.innerHTML="<button id=cross-target>Open preferences</button>";window.crossClicks=0;document.querySelector("button").onclick=()=>crossClicks++')
            page(b,'document.body.innerHTML="<button id=cross-target>Delete project</button>";window.crossClicks=0;document.querySelector("button").onclick=()=>crossClicks++')
            aim(a,'#cross-target')
            selected=[a]
            real_resolve=service.resolve_candidates
            def switch_after_scoring(*args,**kwargs):
                result=real_resolve(*args,**kwargs)
                if args[2] != 'Open this':
                    return result
                command(a,'Emulation.setFocusEmulationEnabled',{'enabled':False})
                command(b,'Page.bringToFront',{})
                command(b,'Emulation.setFocusEmulationEnabled',{'enabled':True})
                selected[0]=b
                aim(b, '#cross-target')
                other = service.resolve_now(session, utterance='Inspect B', mode='simulated')
                assert other['browser_target'] == b._target_id
                return result
            with patch.object(service,'_LLM',None),patch.object(service,'resolve_candidates',side_effect=switch_after_scoring), \
                 patch.object(session.cdp,'_target',side_effect=lambda:selected[0]):
                result=service.resolve_now(session,utterance='Open this',mode='simulated')
            assert session._resolution_target==a._target_id
            chosen=session.choose(resolution_id=result['resolution_id'])
            assert not chosen['ok'] and page(b,'return crossClicks')==0 and page(a,'return crossClicks')==0
            print('PASS 4: scoring-time focus switch cannot transfer resolution or click to matching selector in B')
            # Actual Lens keyboard selection and compact private renderer layout.
            aim(b, '#cross-target')
            with patch.object(service, '_LLM', None):
                lens = service.resolve_now(session, utterance='Open this', mode='simulated')
            b.eval_js('window.__HERMES_GAZE_OVERLAY__.renderSemanticLens(' +
                json.dumps(lens['ranked'][:1]) + ',"Choose the captured test control",' + str(lens['resolution_id']) + ');true')
            until(lambda: node(b, '.lens-card', 'const r=this.getBoundingClientRect(),h=this.getRootNode().querySelector(".hud-shell").getBoundingClientRect();return r.bottom<=h.top||h.bottom<=r.top'))
            node(b, '#hg-lock-btn', 'this.focus();return true')
            command(b, 'Input.dispatchKeyEvent', {'type':'keyDown','key':'1','code':'Digit1','windowsVirtualKeyCode':49})
            command(b, 'Input.dispatchKeyEvent', {'type':'keyUp','key':'1','code':'Digit1','windowsVirtualKeyCode':49})
            until(lambda: page(b, 'return crossClicks') == 1)
            command(b, 'Emulation.setDeviceMetricsOverride', {'width':390,'height':420,'deviceScaleFactor':1,'mobile':False})
            b.eval_js('window.__HERMES_GAZE_OVERLAY__.showHudMessage("Long private reply ".repeat(500));true')
            until(lambda: b.eval_js('(()=>{const r=window.__HERMES_GAZE_OVERLAY__.uiFrame.getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight})()'))
            until(lambda: node(b, '#hg-reply', 'return this.textContent.startsWith("Long private reply") && this.scrollHeight>this.clientHeight'))
            Path('/tmp/hermes-trust-small.png').write_bytes(base64.b64decode(
                command(b, 'Page.captureScreenshot', {'format': 'png'})['data']))
            command(b, 'Emulation.clearDeviceMetricsOverride', {})
            print('PASS review: concurrent B resolution cannot steal A ownership; Lens is usable and frame stays inside 390x420 viewport')
    finally:
        if session:
            session.close()
        chrome.terminate()
        chrome.wait(timeout=10)
