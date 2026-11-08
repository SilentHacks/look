"""Private Chrome recording regression; fake device, real CDP, no model or host."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests
from hermes_gaze import service
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.microphone import Microphone
from hermes_gaze.resolver.cursor_context import cursor_result


def until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.025)
    raise AssertionError('Private Chrome scenario timed out')


def command(tab, method, params):
    return tab._submit(tab._send_cmd(method, params, timeout=5), 7)


def page(tab, expression):
    result = command(tab, 'Runtime.evaluate', {'expression': expression, 'returnByValue': True})
    assert not result.get('exceptionDetails'), result
    return result.get('result', {}).get('value')


class Input:
    def __init__(self, **kwargs):
        self.callback = kwargs['callback']
    def start(self):
        self.callback(b'\x01\x00' * 160, 160, SimpleNamespace(currentTime=1., inputBufferAdcTime=1.), None)
    def stop(self): pass
    def abort(self): pass
    def close(self): pass


def run():
    with tempfile.TemporaryDirectory(prefix='hermes-recording-chrome-') as tmp:
        chrome = subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '--remote-debugging-port=0', f'--user-data-dir={tmp}', '--no-first-run',
            '--no-default-browser-check', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        session = None
        mic = Microphone()
        try:
            active = Path(tmp) / 'DevToolsActivePort'
            until(active.exists)
            session = GazeSession('http://127.0.0.1:' + active.read_text().splitlines()[0])
            assert session.cdp.connect()
            def new_tab():
                req = urllib.request.Request(session.cdp_http_url + '/json/new?about:blank', method='PUT')
                with urllib.request.urlopen(req) as response:
                    target = json.load(response)['id']
                return until(lambda: (tab if (tab := session.cdp._tabs.get(target)) and tab.is_connected else None))
            a, b = new_tab(), new_tab()
            command(a, 'Page.bringToFront', {})
            command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': True})
            page(a, '''document.body.innerHTML='<div id="a" style="height:100px">Item A</div><div style="height:1600px"></div><div id="b" style="height:100px">Item B</div><div style="height:1200px"></div>';
                window.scrollMode='';window.scrollEvents=0;window.addEventListener('scroll',()=>{
                  scrollEvents++;if(scrollMode==='route')history.replaceState({},'', '#section'+scrollY);
                  if(scrollMode==='heavy'){const end=performance.now()+1000;while(performance.now()<end){}}
                });''')
            document = a._context_unique_id
            reasons, warnings = [], []
            events = []
            stopped = []
            hint_entered, hint_release = threading.Event(), threading.Event()
            def handle(intent, reply):
                if intent.get('action') == 'coach' and 'heard' in intent.get('coach', {}):
                    hint_entered.set()
                    assert hint_release.wait(5), 'release hint was not unblocked'
                if intent['type'] == 'record_stop':
                    stopped.append(intent)
                    session.microphone.stop(f"{intent['_browser_target']}:{intent['_browser_document']}")
                    reply({'ok': True})
                else:
                    service.handle_intent(intent, lambda result: (events.append(result), reply(result)))
            session.cdp.set_intent_handler(handle)
            with patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Input)), \
                    patch.object(service, 'get_shared_session', return_value=session), \
                    patch.object(service, '_VOICE_TURNS', None):
                def start():
                    reasons.clear()
                    assert mic.start('A', lambda: session.cdp.recording_loss(a._target_id, document),
                                     on_cancel=reasons.append, on_warning=warnings.append)['ok']
                start()
                page(a, "scrollMode='heavy';setTimeout(()=>scrollTo(0,200),20)")
                time.sleep(1.5)
                assert not reasons and mic._stream is not None, reasons
                print('PASS: main-thread scroll stall survives')
                mic.cancel()
                page(a, "scrollMode='route'")
                start()
                route = a._route_id
                page(a, 'scrollTo(0,400)')
                until(lambda: a._route_id > route)
                time.sleep(.3)
                assert not reasons and mic._stream is not None, reasons
                print('PASS: replaceState scroll survives; route authority still changes')
                mic.cancel()
                # Existing real-identity history already spans off-screen points and word times.
                page(a, "scrollMode='';scrollTo(0,0)")
                time.sleep(.15)
                def aim(selector):
                    r = page(a, f'(()=>{{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect();return {{x:r.x+5,y:r.y+5}}}})()')
                    command(a, 'Input.dispatchMouseEvent', {'type': 'mouseMoved', **r})
                    time.sleep(.1)
                    return time.time()
                aim('#a')
                # Exercise trusted Space down/up and freeze across a route change.
                page(a, 'document.body.tabIndex=-1;document.body.focus()')
                command(a, 'Input.dispatchKeyEvent', {'type': 'keyDown', 'key': ' ', 'code': 'Space', 'windowsVirtualKeyCode': 32})
                until(lambda: session.microphone._stream is not None)
                time.sleep(.25)
                ta = time.time()
                route = a._route_id
                page(a, "scrollMode='route'")
                page(a, 'scrollTo(0,1700)')
                time.sleep(.15)
                tb = aim('#b')
                until(lambda: a._route_id > route)
                page(a, "window.dispatchEvent(new Event('blur'));document.dispatchEvent(new Event('visibilitychange'))")
                time.sleep(.2)
                assert session.microphone._stream is not None
                command(a, 'Input.dispatchKeyEvent', {'type': 'keyUp', 'key': ' ', 'code': 'Space', 'windowsVirtualKeyCode': 32})
                try:
                    until(hint_entered.is_set)
                    assert session.microphone._stream is None, 'Hint persistence delayed microphone close'
                finally:
                    hint_release.set()
                print('PASS: release closes input before a blocked hint update')
                until(lambda: stopped)
                frozen = stopped[-1]
                assert frozen['_browser_document'] == document
                assert frozen['_browser_route'] == a._route_id and a._route_id > route
                capture = frozen['cursor_context']
                result = cursor_result(capture, 'this or this', [dict(word='this',start=ta,end=ta+.01), dict(word='this',start=tb,end=tb+.01)])
                points = result['pointed']
                assert len(points) == 2 and all(p['available'] for p in points), points
                assert points[0]['id'] != points[1]['id'], points
                assert 'Item A' in result['context'] and 'Item B' in result['context'], result['context']
                assert len(result['context']) <= 6000
                print('PASS: two timed this anchors retain distinct real identities; off-screen Item A and Item B in bounded packet')
                print('PASS: overlay hold survives route revocation and spurious blur/visibility; release evidence owns current route')
                start()
                command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': False})
                command(b, 'Page.bringToFront', {})
                until(lambda: reasons)
                assert 'focus' in reasons[0].lower() or 'hidden' in reasons[0].lower(), reasons
                print('PASS: real tab switch cancels: ' + reasons[0])
                command(a, 'Page.bringToFront', {})
                command(a, 'Emulation.setFocusEmulationEnabled', {'enabled': True})
                start()
                command(a, 'Page.navigate', {'url': 'about:blank?new-document'})
                until(lambda: reasons)
                assert 'document' in reasons[0].lower(), reasons
                print('PASS: full navigation cancels: ' + reasons[0])
                until(lambda: a._context_unique_id and a._context_unique_id != document and a._ui_frames
                      and a.eval_js("(() => {const t=window.__HERMES_GAZE_OVERLAY__?.debug().talk;return t?.ready && t.nonce})()"))
                document = a._context_unique_id
                # Real native deadline, warning transport and visible private renderer.
                events.clear()
                page(a, 'document.body.tabIndex=-1;document.body.focus()')
                command(a, 'Input.dispatchKeyEvent', {'type': 'keyDown', 'key': ' ', 'code': 'Space', 'windowsVirtualKeyCode': 32})
                until(lambda: session.microphone._stream is not None)
                until(lambda: any(e.get('type') == 'record_warning' for e in events), 28)
                def warning_label():
                    # The capsule's words exist only in its protected frame, reachable through CDP.
                    return a._submit(a._eval_coro('document.getElementById("pill")?.textContent',
                                                  5., context_id=a._ui_frames['pill'][1]), 7)
                assert until(lambda: warning_label() == '5 seconds left. Let go of Space', 3)
                until(lambda: session.microphone._stream is None, 7)
                cancellation = until(lambda: next((e for e in events if e.get('type') == 'record_cancel'), None))
                assert cancellation['error'] == 'Recording cancelled: 30-second limit reached.', cancellation
                assert len([e for e in events if e.get('type') == 'record_warning']) == 1
                print('PASS: visible \"5 seconds left. Let go of Space\" warning then native 30-second cancellation')
        finally:
            mic.cancel()
            if session:
                live = next((t for t in session.cdp._tabs.values() if t.is_connected), None)
                if live:
                    try: command(live, 'Browser.close', {})
                    except (ConnectionError, TimeoutError): pass
                session.close()
            try: chrome.wait(timeout=10)
            except subprocess.TimeoutExpired:
                chrome.terminate()
                chrome.wait(timeout=10)


if __name__ == '__main__':
    run()
