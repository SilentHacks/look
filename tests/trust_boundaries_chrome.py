"""One hostile-page sample per trust-boundary regression; never attaches owner Chrome.
Run: .venv/bin/python tests/trust_boundaries_chrome.py
Uses fake audio/model/host for deterministic security probes; real CDP trusted input.
"""
import base64
import http.server
import json
import subprocess
import sys
import tempfile
import threading
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
    """Privileged read inside the protected card frame, through CDP only."""
    body = 'const n=document.querySelector(' + json.dumps(selector) + ');if(!n)return null;' \
           'return (function(){' + expression + '}).call(n)'
    return tab._submit(tab._eval_coro('(()=>{' + body + '})()', 5., context_id=tab._ui_context_unique_id), 7)


def click(tab, selector):
    time.sleep(.5)  # Let the plate's spring settle before aiming at something on it.
    r = until(lambda: node(tab, selector, 'const r=this.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}'))
    frame = tab.eval_js('(()=>{const r=window.__HERMES_GAZE_OVERLAY__.uiFrame.getBoundingClientRect();return {x:r.x,y:r.y}})()')
    for kind in ('mousePressed', 'mouseReleased'):
        command(tab, 'Input.dispatchMouseEvent', {'type': kind, 'button': 'left', 'clickCount': 1,
            'x': r['x'] + frame['x'], 'y': r['y'] + frame['y']})
    # UI events first travel to the main isolated world, then enter its intent FIFO.
    time.sleep(.15)
    drain(tab)


def aim(tab, selector):
    r = page(tab, 'const r=document.querySelector(' + json.dumps(selector) + ').getBoundingClientRect();'
        'return {x:r.left+2,y:r.top+2};')
    command(tab, 'Input.dispatchMouseEvent', {'type': 'mouseMoved', **r})


def capture(tab):
    data = tab.eval_js('window.__HERMES_GAZE_OVERLAY__.captureCursorContext()')
    data.update(browser_target=tab._target_id, browser_document=tab._context_unique_id, browser_route=tab._route_id)
    return data


def key(tab, code, name=None, text=""):
    for kind in ("keyDown", "keyUp"):
        command(tab, "Input.dispatchKeyEvent", {"type": kind, "code": code,
            "key": name or code, "text": text if kind == "keyDown" else ""})
    time.sleep(.15)
    drain(tab)


def talk(tab, session, *, hold=.4):
    """A real held Space: past the tap threshold, then released."""
    command(tab, 'Input.dispatchKeyEvent', {'type': 'keyDown', 'key': ' ', 'code': 'Space', 'windowsVirtualKeyCode': 32})
    try:
        until(lambda: session.microphone._stream is not None)
    except AssertionError:
        print('talk did not start:', view(tab)['talk'], tab._context_id, tab._ui_frames, tab.eval_js('window.__HERMES_GAZE_OVERLAY__===undefined'), tab.eval_js('[document.hasFocus(),document.activeElement?.tagName,window.__HERMES_GAZE_OVERLAY__.state.mode]'),
              node(tab, 'html', 'return [document.hasFocus(),document.activeElement?.tagName]'), [(r['type'], r.get('ok'), r.get('error')) for r in replies[-5:]], flush=True)
        raise
    time.sleep(hold)
    command(tab, 'Input.dispatchKeyEvent', {'type': 'keyUp', 'key': ' ', 'code': 'Space', 'windowsVirtualKeyCode': 32})
    until(lambda: session.microphone._stream is None)


def compose(tab):
    page(tab, 'document.body.tabIndex=-1;document.body.focus()')
    key(tab, "AltRight", "Alt")
    until(lambda: node(tab, "#hg-input", "return this.getBoundingClientRect().width>0"))
    time.sleep(.5)  # The card springs into place; a click during that can land beside it.


def view(tab):
    return tab.eval_js('window.__HERMES_GAZE_OVERLAY__.debug()')


def foreground(tab, others=()):
    for other in others:
        command(other, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
    command(tab, 'Page.bringToFront', {})
    command(tab, 'Emulation.setFocusEmulationEnabled', {'enabled': True})


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


# ---------- a page that patched every browser API it could before we arrived ----------
HOSTILE = r'''<!doctype html><html><head><title>Hostile</title><script>
window.__seen = []; window.__shadow = null; window.__frameDoc = null; window.__frames = [];
const rapply = Reflect.apply, jsonText = JSON.stringify, seenPush = Array.prototype.push;
let busy = false;
const note = (name, value) => { try { rapply(seenPush, window.__seen, [name + ':' + (typeof value === 'string' ? value :
  value && value.nodeType ? value.nodeName + ' ' + (value.outerHTML || value.textContent || '') : jsonText(value))]); } catch (_) {} };
function wrap(owner, name) {
  const original = owner[name]; if (typeof original !== 'function') return;
  owner[name] = function (...args) {
    if (busy) return rapply(original, this, args);
    busy = true;
    try { for (const a of args) if (typeof a !== 'number') note(name, a); } finally { busy = false; }
    const out = rapply(original, this, args);
    if (name === 'attachShadow') window.__shadow = out;
    return out; };
}
for (const [owner, names] of [
  [Element.prototype, ['attachShadow', 'setAttribute', 'append', 'prepend', 'replaceChildren', 'insertAdjacentHTML',
    'showPopover', 'hidePopover', 'togglePopover', 'getAnimations', 'animate', 'scrollIntoView']],
  [Node.prototype, ['appendChild', 'insertBefore', 'replaceChild']],
  [Document.prototype, ['createElement', 'createTextNode', 'createElementNS', 'elementFromPoint']],
  [CSSStyleSheet.prototype, ['replaceSync', 'replace', 'insertRule']],
  [CharacterData.prototype, ['appendData']], [EventTarget.prototype, ['addEventListener', 'dispatchEvent']],
  [window, ['requestAnimationFrame', 'postMessage', 'fetch', 'setTimeout', 'getComputedStyle', 'getSelection']],
  [navigator, ['sendBeacon']], [JSON, ['stringify', 'parse']], [console, ['log', 'debug', 'info']],
  [Object, ['defineProperty', 'assign']], [Function.prototype, ['call', 'apply', 'bind']],
]) for (const name of names) wrap(owner, name);
for (const proto of [HTMLIFrameElement.prototype]) for (const prop of ['contentWindow', 'contentDocument']) {
  const d = Object.getOwnPropertyDescriptor(proto, prop);
  Object.defineProperty(proto, prop, { get() { window.__frames.push(this); return d.get.call(this); } });
}
for (const prop of ['innerHTML', 'textContent']) {
  const owner = prop === 'innerHTML' ? Element.prototype : Node.prototype, d = Object.getOwnPropertyDescriptor(owner, prop);
  Object.defineProperty(owner, prop, { get: d.get, set(v) { note('set ' + prop, v); d.set.call(this, v); } });
}
const d = Object.getOwnPropertyDescriptor(Element.prototype, 'shadowRoot');
Object.defineProperty(Element.prototype, 'shadowRoot', { get() { const r = d.get.call(this); if (r) window.__shadow = r; return r; } });
const OriginalObserver = window.MutationObserver;
window.__mutations = [];
new OriginalObserver(list => { for (const m of list) { for (const n of m.addedNodes) note('added', n);
  window.__mutations.push(m.type + ':' + (m.target.nodeName)); } }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
window.addEventListener('message', e => note('message', e.data), true);
for (const type of ['keydown', 'keyup', 'keypress', 'input', 'beforeinput', 'paste', 'copy', 'selectionchange', 'focusin'])
  window.addEventListener(type, e => note(type, e.key || e.data || ''), true);
</script></head><body><p id="target" style="margin:80px">Hostile target paragraph</p></body></html>'''


class LeakServer(http.server.BaseHTTPRequestHandler):
    hits = []
    def do_GET(self):
        LeakServer.hits.append(self.path)
        self.send_response(204); self.end_headers()
    def log_message(self, *args): pass


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
        foreground(a)
        command(b, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
        def seed(tab):
            page(tab, '''document.body.innerHTML='<button id="danger">Delete sample</button><a id="secret" href="https://alice:password@example.invalid/export?access_token=VERY_SECRET#private_key">Download export</a>';
                window.project=window.project||'A';window.deleted=[];document.querySelector('#danger').onclick=()=>deleted.push(project);
                window.keys=[];window.addEventListener('keydown',e=>keys.push(e.key),true);''')
        seed(a)
        injected = []
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda text, **kw: injected.append(text) or True), session)
        turns.bind(session_key='private', session_id='private-session')
        replies = []
        def handle(intent, reply):
            service.handle_intent(intent, lambda result: (replies.append({'type': intent['type'], **result}), reply(result)))
        session.cdp.set_intent_handler(handle)
        turn_serial = [0]
        def answered(tab, question, answer, name='PRIVATE_ITEM_LABEL'):
            aim(tab, '#danger')
            snapshot = cursor_result(capture(tab), question)
            snapshot.update(browser_target=tab._target_id, browser_document=tab._context_unique_id,
                            utterance=question, subject={'name': name, 'count': 1})
            assert turns.submit(question, snapshot)['ok']
            turn_serial[0] += 1
            turn = f'turn-{turn_serial[0]}'
            turns.pre(session_id='private-session', turn_id=turn, user_message=injected[-1])
            turns.post(session_id='private-session', turn_id=turn, assistant_response=answer)
            turns.end(session_id='private-session', turn_id=turn)
        def reply_text(tab):
            return node(tab, '#hg-reply', 'return this.textContent') or ''
        def main_world_text(tab):
            # Main-world probes: serialization, text, selection, frames and open shadows.
            return page(tab, '''const seen=[];function walk(root){
                if(!root)return;seen.push(root.textContent,root.innerHTML);
                for(const n of root.querySelectorAll("*")){
                    if(n.shadowRoot)walk(n.shadowRoot);
                    if(n.tagName==="IFRAME"){try{walk(n.contentDocument)}catch(e){}}
                }}walk(document.documentElement);seen.push(String(getSelection()));
                return JSON.stringify(seen);''')
        with patch.object(service, 'get_shared_session', return_value=session), \
             patch.object(service, '_VOICE_TURNS', turns), patch.object(service, '_CONFIG', GazeConfig()):
            assert page(a, 'return document.querySelector("#hermes-gaze-root").shadowRoot') is None
            assert page(a, 'return typeof window.__HERMES_GAZE_OVERLAY__+":"+typeof window.__hermesGazeIntent') == 'undefined:undefined'
            boundary = page(a, 'try {return {readable:!!window.frames[0].document,frames:frames.length}}catch(e){return {error:e.name,frames:frames.length}}')
            assert boundary.get('error') == 'SecurityError' or boundary['frames'] == 0, boundary
            assert a.eval_js('(()=>{try{window.__HERMES_GAZE_OVERLAY__.uiFrame.contentWindow.document;return false}catch(e){return e.name}})()') == 'SecurityError'
            assert view(a)['view'] is None
            compose(a)
            page(a, 'keys=[]')
            node(a, '#hg-input', 'this.value="FORGED_MESSAGE";return true')
            node(a, '#hg-send', 'this.click();return true')
            drain(a)
            assert injected == []
            click(a, '#hg-input')
            command(a, 'Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Q', 'code': 'KeyQ', 'text': 'Q'})
            command(a, 'Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Q', 'code': 'KeyQ'})
            assert page(a, 'return keys') == []
            key(a, 'Escape', 'Escape')
            until(lambda: view(a)['view'] is None)
            page(a, 'document.body.tabIndex=-1;document.body.focus()')
            print('PASS 1: page cannot reach UI/API/binding; synthetic Ask rejected; no host injection')

            answered(a, 'PRIVATE_QUESTION', 'PRIVATE_A_PAYROLL_7391')
            until(lambda: 'PRIVATE_A_PAYROLL_7391' in reply_text(a))
            assert 'PRIVATE_A_PAYROLL_7391' not in reply_text(b)
            key(a, "Escape", "Escape")
            until(lambda: view(a)['view'] is None)
            key(a, "KeyQ", "q")
            until(lambda: 'PRIVATE_A_PAYROLL_7391' in reply_text(a))
            foreground(b, [a])
            answered(a, 'PRIVATE_QUESTION_TWO', 'PRIVATE_UNREAD_ANSWER', 'PRIVATE_SECOND_LABEL')
            until(lambda: 'PRIVATE_UNREAD_ANSWER' in reply_text(b) or 'PRIVATE_A_PAYROLL_7391' in reply_text(b))
            assert 'PRIVATE_UNREAD_ANSWER' not in reply_text(a)
            for tab in (a, b):
                public = main_world_text(tab)
                for marker in ('PRIVATE_ITEM_LABEL', 'PRIVATE_SECOND_LABEL', 'PRIVATE_QUESTION', 'PRIVATE_A_PAYROLL_7391',
                               'PRIVATE_UNREAD_ANSWER', '1 unread'):
                    assert marker not in public, marker
            foreground(a, [b])
            until(lambda: 'PRIVATE_SECOND_LABEL' in (node(a, '#root', 'return this.textContent') or ''))
            key(a, 'ArrowDown', 'ArrowDown')
            until(lambda: 'PRIVATE_UNREAD_ANSWER' in reply_text(a))
            node(a, '#hg-reply', 'const r=document.createRange();r.selectNodeContents(this);getSelection().removeAllRanges();getSelection().addRange(r);return true')
            assert 'PRIVATE_UNREAD_ANSWER' not in page(a, 'return String(getSelection())')
            key(a, 'Escape', 'Escape')
            until(lambda: view(a)['view'] is None)
            print('PASS 2: focused-only protected inbox recall; hostile pages cannot read item, answer or unread text')

            aim(a, '#secret')
            data = capture(a)
            packet = cursor_result(data, 'What is this export?')['context']
            for secret in ('alice', 'password', 'VERY_SECRET', 'private_key'):
                assert secret not in json.dumps(data) and secret not in packet
            assert 'https://example.invalid/export' in packet
            print('PASS 6: URL credentials, secret query parameters and fragments absent from wire and model context')

            # Connected voice carries its reserved item identity back to its captured source.
            assert a._submit(a._on_new_context(force=True), 20)
            turns.publish()
            page(a, 'document.body.tabIndex=-1;document.body.focus()')
            aim(a, '#secret')
            time.sleep(.1)
            with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=FakeInput)), \
                 patch.object(voice, 'transcribe_audio_buffer', return_value=('What is this export?', [])):
                talk(a, session)
                until(lambda: any(r['type'] == 'record_stop' and r.get('delivery') == 'session' for r in replies))
            turns.pre(session_id='private-session', turn_id='voice-anchor', user_message=injected[-1])
            turns.post(session_id='private-session', turn_id='voice-anchor', assistant_response='The captured link is an export.')
            turns.end(session_id='private-session', turn_id='voice-anchor')
            def source_card():
                state = view(a)
                return state['view'] == 'answer' and state['targets'] and state
            state = until(source_card)
            card, target = state['card'], state['targets'][0]
            assert card['x'] >= target['right'] or card['x'] + card['w'] <= target['left'] or \
                   card['y'] >= target['bottom'] or card['y'] + card['h'] <= target['top'], state
            print('PASS voice: connected transcription keeps its captured source lit and uncovered')
            key(a, 'Escape', 'Escape')
            until(lambda: view(a)['view'] is None)

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
            foreground(a)
            command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
            command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': True})
            page(a, 'document.body.tabIndex=-1;document.body.focus()')
            assert a.eval_js('document.hasFocus()')
            with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=FakeInput)):
                command(a, 'Input.dispatchKeyEvent', {'type':'keyDown','key':' ','code':'Space','windowsVirtualKeyCode':32})
                until(lambda: session.microphone._stream is not None)
                command(a, 'Input.dispatchKeyEvent', {'type':'keyUp','key':' ','code':'Space','windowsVirtualKeyCode':32})
                time.sleep(.2)
                assert session.microphone._stream is not None
                until(lambda: session.microphone._stream is None, seconds=32)
                assert streams[-1].closed and session.microphone._audio == bytearray()
            print('PASS 5: suppressed release remains open briefly, then native 30s cap closes and discards capture')

            # A fresh document, without that hostile listener.
            old = a._context_unique_id
            command(a, 'Page.navigate', {'url': 'about:blank?next'})
            until(lambda: a._context_unique_id != old and a._ui_frames and a.is_connected)
            time.sleep(.3)
            foreground(a)
            page(a, 'window.project="B"')
            seed(a)
            turns.close()
            service._VOICE_TURNS = None
            replies.clear()
            switch_on_answer = [True]
            def one_shot_model(**kwargs):
                if switch_on_answer[0]:
                    switch_on_answer[0] = False
                    foreground(b, [a])
                return SimpleNamespace(text='ONE_SHOT_ANSWER_MARKER', parsed={'handles': []})
            with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=FakeInput)), \
                 patch.object(service, '_LLM', SimpleNamespace(complete_structured=one_shot_model)), \
                 patch.object(voice, 'transcribe_audio_buffer', return_value=('What is this export?', [])):
                page(a, 'document.body.tabIndex=-1;document.body.focus()')
                aim(a, '#secret')
                talk(a, session)
                stop = until(lambda: next((r for r in replies if r['type']=='record_stop'), None))
                assert stop['ok'] and stop['delivery']=='one_shot', stop
                assert 'ONE_SHOT_ANSWER_MARKER' not in reply_text(a)
                foreground(a, [b])
                until(lambda: 'ONE_SHOT_ANSWER_MARKER' in reply_text(a))
                session.configure(mode='hover')
                assert 'ONE_SHOT_ANSWER_MARKER' in reply_text(a)
                print('PASS 7: disconnected voice displays actual one-shot answer, not queued')
                replies.clear()
                key(a, 'Escape', 'Escape')
                session.configure(mode='simulated')
                page(a, 'document.body.tabIndex=-1;document.body.focus()')
                talk(a, session)
                stop = until(lambda: next((r for r in replies if r['type']=='record_stop'), None))
                assert stop['ok'] and stop['mode']=='simulated', stop
                assert 'No DOM candidates' not in json.dumps(stop)
                print('PASS 8: simulated voice freezes candidates and pointer at release and resolves successfully')
                key(a, 'Escape', 'Escape')
                session.configure(mode='hover')
                compose(a)
                click(a, '#hg-input')
                for char in 'What is this export?':
                    command(a, 'Input.dispatchKeyEvent', {'type': 'char', 'text': char})
                replies.clear()
                command(a, 'Input.dispatchKeyEvent', {'type': 'keyDown', 'code': 'Enter', 'key': 'Enter', 'windowsVirtualKeyCode': 13})
                command(a, 'Input.dispatchKeyEvent', {'type': 'keyUp', 'code': 'Enter', 'key': 'Enter', 'windowsVirtualKeyCode': 13})
                until(lambda: any(r['type'] == 'submit' and r.get('delivery') == 'one_shot' for r in replies))
                until(lambda: view(a)['view'] == 'note')
                key(a, 'Escape', 'Escape')
                until(lambda: view(a)['view'] is None)
                key(a, 'AltRight', 'Alt')  # Reopen while the dismissed private frame still owns focus.
                until(lambda: node(a, '#hg-input', 'return this.getBoundingClientRect().width>0'))
                assert node(a, '#hg-input', 'return document.activeElement===this')
                key(a, 'Escape', 'Escape')
                until(lambda: view(a)['view'] is None)
                talk(a, session)
                key(a, 'Escape', 'Escape')
                print('PASS review: idle is absent, private typing focuses and survives, Enter and Space capture work')
            session.configure(mode='hover')
            until(lambda: view(a)['view'] is None)

            # Fresh snapshot: normal trusted confirmation remains single-use.
            aim(a, '#danger'); data = capture(a)
            snapshot = cursor_result(data, 'Delete this sample')
            hid = next(k for k, v in data['handles'].items() if v.get('label') == 'Delete sample')
            snapshot.update(browser_target=a._target_id, browser_document=a._context_unique_id, utterance='Delete this sample')
            rid = session.store_hover_snapshot(snapshot)
            assert session.actions.click(hid, rid)['confirmation_required']
            until(lambda: view(a)['view'] == 'confirm' and node(a, '.choice.yes', 'return this.getBoundingClientRect().width>0'))
            # Synthetic consent inside the private frame, and keyboard activation, are both refused.
            node(a, '.choice.yes', 'this.click();return true')
            node(a, '.choice.yes', 'this.focus();return true')
            key(a, 'Enter', 'Enter', '\r')
            drain(a);assert page(a,'return deleted')==[] and session.actions._pending
            time.sleep(.3)
            Path(tmp, 'confirmation.png').write_bytes(base64.b64decode(
                command(a, 'Page.captureScreenshot', {'format': 'png'})['data']))
            click(a, '.choice.yes')
            until(lambda: page(a,'return deleted.length')==1)
            assert page(a,'return deleted')==['B']
            assert not session.actions.confirm(pending['action_id'],rid,True)['ok']
            print('PASS normal: trusted confirmation executes once; synthetic and keyboard consent remain rejected')

            page(a,'document.body.innerHTML="<button id=cross-target>Open preferences</button>";window.crossClicks=0;document.querySelector("button").onclick=()=>crossClicks++')
            page(b,'document.body.innerHTML="<button id=cross-target>Delete project</button>";window.crossClicks=0;document.querySelector("button").onclick=()=>crossClicks++')
            aim(a,'#cross-target')
            selected=[a]
            real_resolve=service.resolve_candidates
            def switch_after_scoring(*args,**kwargs):
                result=real_resolve(*args,**kwargs)
                if args[2] != 'Open this':
                    return result
                foreground(b, [a])
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
            until(lambda: node(b, '.lens-card', 'return this.getBoundingClientRect().width>0'))
            key(b, 'Escape', 'Escape')
            key(b, 'Digit1', '1')
            assert page(b, 'return crossClicks') == 0
            assert not b.eval_js('window.__HERMES_GAZE_OVERLAY__.state.lensActive')
            b.eval_js('window.__HERMES_GAZE_OVERLAY__.renderSemanticLens(' +
                json.dumps(lens['ranked'][:1]) + ',null,' + str(lens['resolution_id']) + ');true')
            until(lambda: node(b, '.lens-card', 'return this.getBoundingClientRect().width>0'))
            node(b, '.lens-card', 'this.focus();return true')
            command(b, 'Input.dispatchKeyEvent', {'type':'keyDown','key':'1','code':'Digit1','windowsVirtualKeyCode':49})
            command(b, 'Input.dispatchKeyEvent', {'type':'keyUp','key':'1','code':'Digit1','windowsVirtualKeyCode':49})
            until(lambda: page(b, 'return crossClicks') == 1)
            command(b, 'Emulation.setDeviceMetricsOverride', {'width':390,'height':420,'deviceScaleFactor':1,'mobile':False})
            b.eval_js('window.__HERMES_GAZE_OVERLAY__.showHudMessage("Long private reply ".repeat(500));true')
            def inside():
                state = view(b)
                card = state['card']
                return b.eval_js(f'(()=>{{const v=visualViewport;return {card["x"]}>=v.offsetLeft&&{card["y"]}>=v.offsetTop&&'
                                 f'{card["x"]+card["w"]}<=v.offsetLeft+v.width&&{card["y"]+card["h"]}<=v.offsetTop+v.height}})()')
            until(lambda: view(b)['view'] == 'note' and inside())
            until(lambda: node(b, '#hg-reply', 'return this.textContent.startsWith("Long private reply") && this.scrollHeight>this.clientHeight'))
            command(b, 'Emulation.setPageScaleFactor', {'pageScaleFactor':1.5})
            until(inside)
            assert node(b, '.card', 'return this.scrollWidth<=this.clientWidth')
            command(b, 'Emulation.setPageScaleFactor', {'pageScaleFactor':1})
            command(b, 'Emulation.clearDeviceMetricsOverride', {})
            key(b, 'Escape', 'Escape')
            print('PASS review: concurrent B resolution cannot steal A ownership; Lens is usable and the card stays inside 390x420 and pinch zoom')

            # ---------- the glass plate on a page that patched browser APIs first ----------
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), LeakServer)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            leak = f'http://127.0.0.1:{server.server_address[1]}/leak'
            hostile_path = Path(tmp, 'hostile.html')
            hostile_path.write_text(HOSTILE)
            c = new_tab()
            old = c._context_unique_id
            command(c, 'Page.navigate', {'url': hostile_path.as_uri()})
            until(lambda: c._context_unique_id != old and c._ui_frames and page(c, 'return document.readyState') == 'complete')
            # The page's patches now exist. Inject once more after them, as any late attach would.
            assert c._submit(c._on_new_context(force=True), 20)
            foreground(c, [a, b])
            page(c, 'document.body.tabIndex=-1;document.body.focus();window.__seen.length=0')
            hostile_turns = VoiceTurns(SimpleNamespace(inject_message=lambda text, **kw: injected.append(text) or True), session)
            hostile_turns.bind(session_key='private', session_id='private-session')
            turns = hostile_turns
            service._VOICE_TURNS = hostile_turns
            aim(c, '#target')
            snapshot = cursor_result(capture(c), 'PLATE_QUESTION')
            snapshot.update(browser_target=c._target_id, browser_document=c._context_unique_id,
                            utterance='PLATE_QUESTION', subject={'name': 'PLATE_LABEL', 'count': 1})
            assert hostile_turns.submit('PLATE_QUESTION', snapshot)['ok']
            hostile_turns.pre(session_id='private-session', turn_id='plate', user_message=injected[-1])
            # Grow the answer word by word; the page may only ever see coarse hit-test geometry.
            hostile_md = (f'PLATE_SECRET_ANSWER **PLATE_BOLD** <script>window.__pwned=1</script> '
                          f'<img src="{leak}/img" onerror="window.__pwned=2"> ![pixel]({leak}/md) '
                          f'[press](javascript:window.__pwned=3) [ok]({leak}/link) '
                          f'<button data-act="confirm" data-value="yes">Confirm</button> ')
            extents = set()
            def extent():
                x = view(c)['card']['x'] + 100
                return page(c, '''const host=document.querySelector("#hermes-gaze-root");let top=-1,bottom=-1;
                    for(let y=0;y<innerHeight;y+=1){if(document.elementFromPoint(%f,y)===host){
                      if(top<0||y<top)top=y;if(y>bottom)bottom=y;}}
                    return top<0?null:bottom-top+1;''' % x)
            words = [hostile_md] + ['more plate words here'] * 45
            lengths = 0
            for chunk in words:
                hostile_turns.delta(session_id='private-session', turn_id='plate', delta=chunk + ' ', kind='text')
                time.sleep(.09)
                lengths += 1
                value = extent()
                if value:
                    extents.add(value)
            hostile_turns.post(session_id='private-session', turn_id='plate', assistant_response=hostile_md + ' '.join(words[1:]))
            hostile_turns.end(session_id='private-session', turn_id='plate')
            until(lambda: 'PLATE_SECRET_ANSWER' in reply_text(c))
            time.sleep(.5)
            final = extent()
            assert final and min(final % 24, 24 - final % 24) <= 1, final
            # Sampled on whole pixels, so a card mid-spring at a fractional y can read one row longer.
            assert all(min(v % 24, 24 - v % 24) <= 1 for v in extents), extents
            settled = {round(v / 24) * 24 for v in extents}
            assert len(settled) >= 2 and len(settled) < lengths / 2, (extents, lengths)
            # Markup text is inert words. Structurally: only allow-listed elements and attributes exist.
            structure = node(c, '.a', '''const out=new Set();for(const n of this.querySelectorAll("*")){out.add(n.tagName);
                for(const a of n.attributes)out.add("@"+a.name)}return [...out]''')
            allowed = {'P','DIV','SPAN','STRONG','EM','DEL','CODE','PRE','UL','OL','LI','BLOCKQUOTE','HR','BR','TABLE','THEAD','TBODY','TR','TH','TD',
                       '@class','@style','@data-url','@data-align','@start'}
            assert set(structure) <= allowed, structure
            assert node(c, '.a', 'return !this.querySelector("img,script,a,button,iframe,style,link,video,audio,object,embed")')
            # Clicking the scripted link words does nothing; a real link goes only through Python.
            click(c, '.a')
            time.sleep(.2)
            assert page(c, 'return window.__pwned') is None
            links = node(c, '.a', 'return [...this.querySelectorAll(".link")].map(n=>n.dataset.url)')
            assert links == [f'{leak}/link'], links
            for url in ('javascript:alert(1)', 'data:text/html,x', 'file:///etc/passwd', 'https://user:pw@evil.test/', 'chrome://settings'):
                out = []
                service.handle_intent({'type': 'open_link', 'url': url, 'nonce': session._intent_nonce}, out.append)
                assert not out[0]['ok'], url
            # A waveform runs too, so its levels would show up here if they could.
            with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=FakeInput)), \
                 patch.object(voice, 'transcribe_audio_buffer', return_value=('PLATE_VOICE_QUESTION', [])):
                command(c, 'Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': 5, 'y': 5})
                talk(c, session)
            time.sleep(.3)
            compose(c)
            click(c, '#hg-input')
            for char in 'PLATE_TYPED':
                command(c, 'Input.dispatchKeyEvent', {'type': 'char', 'text': char})
            time.sleep(.2)
            markers = ['PLATE_QUESTION', 'PLATE_LABEL', 'PLATE_SECRET_ANSWER', 'PLATE_BOLD', 'PLATE_VOICE_QUESTION',
                       'PLATE_TYPED', '/leak', 'class="bar', 'Looking into', 'Listening']
            seen = page(c, '''const results=window.__seen.join("\\n");
              const host=document.querySelector("#hermes-gaze-root");
              const inner=document.getAnimations().map(a=>a.effect&&a.effect.target&&a.effect.target.nodeName);
              const fields={results,hostHtml:host.innerHTML,hostText:host.textContent,selection:String(getSelection()),body:document.documentElement.outerHTML};
              const hits=[];for(const m of ''' + json.dumps(markers) + ''')for(const f in fields)if(fields[f].includes(m))hits.push([m,f,fields[f].slice(Math.max(0,fields[f].indexOf(m)-80),fields[f].indexOf(m)+80)]);
              return {hits,shadow:window.__shadow?window.__shadow.innerHTML:null,frames:window.__frames.length,
                count:window.__seen.length,hostChildren:host.children.length,
                sub:host.getAnimations({subtree:true}).length,anims:inner,framesLen:window.frames.length,
                pwned:window.__pwned===undefined?null:window.__pwned,
                entries:performance.getEntriesByType("resource").map(e=>e.name)}''')
            assert seen['hits'] == [], seen['hits']
            assert seen['shadow'] is None and seen['frames'] == 0, seen
            assert seen['hostChildren'] == 0 and seen['sub'] == 0 and seen['framesLen'] == 0, seen
            assert not any(a in ('DIV', 'IFRAME', 'I', 'SPAN') for a in seen['anims']), seen['anims']
            assert seen['pwned'] is None and not any('leak' in name for name in seen['entries']), seen
            assert LeakServer.hits == [], LeakServer.hits
            key(c, 'Escape', 'Escape')
            server.shutdown()
            print(f'PASS plate: page with patched APIs sees no private text, shadow, frame, level or network; '
                  f'hit-test height only in coarse steps ({sorted(settled)[:6]}…, {lengths} answer lengths)')
            print('PASS markdown: hostile script, image, javascript: and control text render as inert allow-listed text; 0 requests')

            turns.close()
    finally:
        if session:
            # SIGTERM lets Chrome's profile-writing children outlive the browser.
            # Close the private browser gracefully before removing its profile.
            live = next((t for t in session.cdp._tabs.values() if t.is_connected), None)
            if live:
                try:
                    command(live, 'Browser.close', {})
                except (ConnectionError, TimeoutError):
                    pass  # Chrome can close its socket before acknowledging Browser.close.
            session.close()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.terminate()
            chrome.wait(timeout=10)
