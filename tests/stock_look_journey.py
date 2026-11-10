"""Headed disposable Chrome journey, called by stock_startup.py --journey-chrome.

Real registered stock commands/native admission; fake video, scripted predictions,
fake microphone and stock_startup's offline provider. No personal Chrome or devices.
"""
import asyncio
from contextlib import ExitStack
import base64
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from tests.extension_setup_chrome import Driver, EXTENSION
from tests.calibration_chrome import Scripted, Window
from tests.test_webcam import appearance_observations
from tests.ui_review.devlib import FakeInput
from hermes_gaze.browser import webcam, extension_host, extension
from hermes_gaze.tracker.webcam_gaze import AppearanceEstimator, ScreenPoint
from hermes_gaze.audio import voice

from hermes_gaze.runtime import service

FIXTURE = ('<title>Local journey</title><style>p{position:absolute;width:200px;height:100px}'
           '#cursor{left:20px;top:0}#gaze{left:500px;top:220px}</style>'
           '<p id="cursor">Cursor balance: 999 dollars</p>'
           '<p id="gaze">Gaze fixture price: 42 pounds</p><div style="height:4000px"></div>')

async def journey(args, base, session, turns, look, create, sid):
    results = []
    shots = base / 'screens'
    shots.mkdir()
    async def until(fn, seconds=20):
        async with asyncio.timeout(seconds):
            while not (value := await asyncio.to_thread(fn)):
                await asyncio.sleep(.05)
            return value
    async def command(text, owner=None):
        response = await look(owner or sid, text)
        results.append(dict(command=text, response=str(response)))
        print('JOURNEY', text, str(response), flush=True)
        return response
    def check(name, value):
        assert value, (name, results)
        results.append(dict(check=name))
        print('PASS', name, flush=True)
    def cmd(tab, method, params=None):
        if session.cdp.source == 'extension' and (method.startswith('Input.') or method == 'Page.captureScreenshot'):
            return driver.call(method, params or {}, local_session)
        return tab._submit(tab._send_cmd(method, params or {}, timeout=5), 7)
    def page(tab, expression):
        return tab.eval_js_once(expression, context_id=tab._context_unique_id, operation='read')
    def stop(process):
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
    def focus(process):
        from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(process.pid)
        assert app is not None
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    async def front(tab):
        await asyncio.to_thread(focus, session.cdp.chrome.process if session.cdp.source == 'owned' else extension_process)
        await asyncio.to_thread(cmd, tab, 'Page.bringToFront')
        await until(lambda: page(tab, 'document.hasFocus() && !document.hidden'))
    async def listen(tab, label, *, submit=False):
        await front(tab)
        delivered = host.delivered
        await asyncio.to_thread(cmd, tab, 'Input.dispatchMouseEvent',
                                dict(type='mouseMoved', x=100 if submit else 400, y=24 if submit else 250))
        if session.tracker.mode == 'webcam' and session.cdp.source == 'extension':
            geometry = await asyncio.to_thread(page, tab,
                f'window.__HERMES_GAZE_OVERLAY__.webcamViewport({host.profile["screen"]["dpr"]})')
            check(label + ': trusted pointer measures viewport origin', 'origin_x' in geometry)
            zoom = geometry['dpr'] / host.profile['screen']['dpr']
            Scripted.script = lambda f, t: ScreenPoint(
                geometry['origin_x'] + 600 * zoom, geometry['origin_y'] + 280 * zoom, t)
            def gaze_evidence():
                data = session.cdp.capture('window.__HERMES_GAZE_OVERLAY__.captureNoisyContext()')
                return data if data['fixations'] and all(
                    s['source'] == 'webcam' and abs(s['x_vp'] - 600) < 1 and abs(s['y_vp'] - 280) < 1
                    for s in data['fixations']) else None
            data = await until(gaze_evidence)
            with patch.object(service, '_LLM', None):
                resolved = await asyncio.to_thread(service.resolve_now, session, utterance='Explain this',
                                                   pushed=data, activate=False)
            check(label + ': gaze selects price with cursor over different balance',
                  resolved['ok'] and resolved['mode'] == 'webcam' and
                  'Gaze fixture price' in resolved['top']['label'] and
                  'Cursor balance' not in resolved['context'])
            check(label + ': status reports gaze delivery', 'Using gaze' in str(await command('status')))
        await until(lambda: host.delivered > delivered + 2 if session.tracker.mode == 'webcam' else True)
        before = await asyncio.to_thread(page, tab, 'scrollY')
        runs = len(turns.runs)
        await asyncio.to_thread(cmd, tab, 'Input.dispatchKeyEvent', dict(type='keyDown', code='Space', key=' ', windowsVirtualKeyCode=32))
        try:
            await until(lambda: turns.capture_state == 'recording', 8)
            check(label + ': hold starts native capture without scroll', await asyncio.to_thread(page, tab, 'scrollY') == before)
            if submit:
                await asyncio.sleep(.4)  # Speak after Listening; shorter holds intentionally cancel.
            check(label + ': protected pill says Listening', any('Listening' in tab._submit(tab._eval_coro('document.body.innerText', 3, context_id=context), 5) for _, context in tab._ui_frames.values()))
            image = await asyncio.to_thread(cmd, tab, 'Page.captureScreenshot', {'format': 'png'})
            (shots / (label.replace(' ', '-') + '.png')).write_bytes(base64.b64decode(image['data']))
        finally:
            if not submit:
                await asyncio.to_thread(cmd, tab, 'Input.dispatchKeyEvent', dict(type='keyDown', code='Escape', key='Escape', windowsVirtualKeyCode=27))
            await asyncio.to_thread(cmd, tab, 'Input.dispatchKeyEvent', dict(type='keyUp', code='Space', key=' ', windowsVirtualKeyCode=32))
        await until(lambda: turns.capture_state == 'idle')
        if submit:
            try:
                await until(lambda: len(turns.runs) > runs and turns.runs[-1]['status'] == 'complete' and turns.active is None)
            except TimeoutError:
                print('VOICE_RESULT', [(r['status'], r.get('error'), bool(r.get('admission_id'))) for r in turns.runs],
                      'capture', turns.capture_state, 'connected', turns.connected, flush=True)
                raise
            check(label + ': released voice reaches stock provider and terminal receipt', bool(turns.runs[-1].get('admission_id')))
            if session.tracker.mode == 'webcam':
                snapshot = turns.runs[-1]['snapshot']
                check(label + ': admitted stock question retains gaze evidence',
                      snapshot['mode'] == 'webcam' and 'Gaze fixture price' in snapshot['context'] and
                      'Cursor balance' not in snapshot['context'])
    async def camera(*, saved=False):
        await until(lambda: host.state in ('running', 'failed', 'stopped'))
        check('camera command opens actual owned process', host.state == 'running' and host._process.poll() is None)
        window = await asyncio.to_thread(Window, host, base)
        await until(lambda: window.state()['face'], 30)
        # Simulated accepted calibration, not a physical accuracy claim.
        screen = await asyncio.to_thread(window.tab.main, '({left:screen.availLeft,top:screen.availTop,width:screen.availWidth,height:screen.availHeight,screen_width:screen.width,screen_height:screen.height,screen_left:screen.availLeft,screen_top:screen.availTop,dpr:devicePixelRatio})')
        if saved:
            check('cached calibration loads without another fit', host.profile is not None and host.estimator.profile is not None)
        else:
            profile = AppearanceEstimator().calibrate(appearance_observations(), screen)
            host._save(profile); host.estimator.load(profile); host.profile = profile
        Scripted.script = lambda f, t: ScreenPoint(screen['left'] + 400, screen['top'] + 350, t)
        host._ui('checkResult', host._result_words('good', True))
        await asyncio.to_thread(window.wait, 'result')
        await asyncio.to_thread(focus, host._process)
        await asyncio.to_thread(window.click, 'done')
        await until(lambda: window.state()['phase'] in ('tracking', 'return-error'))
        if window.state()['phase'] == 'return-error' and session.cdp.source == 'owned':
            check('missing foreground destination offers explicit fallback', 'Open start page' in window.text())
            await asyncio.to_thread(window.click, 'start-page')
        await asyncio.to_thread(window.wait, 'tracking')
        window.tab.ws.close()
        return host._process.pid
    with ExitStack() as stack:
        runtime = base / 'transport'; runtime.mkdir(mode=0o700)
        native = base / 'native'; profile = base / 'extension-profile'
        for module in (extension_host, extension):
            stack.enter_context(patch.object(module, 'runtime_directory', return_value=runtime))
        stack.enter_context(patch.object(extension_host, 'install_directory', return_value=native))
        stack.enter_context(patch.object(extension_host, 'manifest_directory', return_value=profile / 'NativeMessagingHosts'))
        stack.enter_context(patch.object(webcam, '_CHROME', args.journey_chrome))
        stack.enter_context(patch.object(service, '_LLM', SimpleNamespace(
            complete_structured=lambda **_: SimpleNamespace(parsed={'handles': []}))))
        stack.enter_context(patch.object(voice, 'recognition_ready', return_value=True))
        stack.enter_context(patch.object(voice, 'transcribe_audio_buffer', return_value=('Explain this fixture price', [])))
        stack.enter_context(patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=FakeInput)))
        host = session.webcam = webcam.WebcamHost(session._accept_webcam_point, estimator=Scripted(),
            assets=Path(args.journey_assets), fake_video=Path(args.journey_video), profile_path=base / 'calibration.json')
        stack.callback(host.stop)
        stack.callback(setattr, Scripted, 'script', None)
        with socket.socket() as port:
            port.bind(('127.0.0.1', 0)); session.cdp_http_url = 'http://127.0.0.1:' + str(port.getsockname()[1])
        owned = session.cdp._owned_chrome
        original_start = owned.start
        stack.enter_context(patch.object(owned, 'start', side_effect=lambda url='about:blank': original_start(url, executable=args.journey_chrome)))
        stack.callback(lambda: stop(owned.process))
        # The first actual user ordering: setup before any browsing connection.
        await command('setup eyes')
        pid = await camera()
        tab = await asyncio.to_thread(session.cdp._target)
        await command('start')
        check('start retains calibrated camera process', host._process.pid == pid and host._live())
        await listen(tab, 'separate setup-before-start')
        await command('start --separate')
        check('repeated separate start retains camera', host._process.pid == pid and host._live())
        await command('calibrate')
        check('reopening calibration retains camera', host._process.pid == pid and host._live())
        await command('start --extension')
        check('source change refuses without killing calibrated tracker', session.cdp.source == 'owned' and host._live() and host._process.pid == pid)
        await command('stop')
        await until(lambda: host._process.poll() is not None)
        # Same session restart, tracker started after browser.
        await command('start --separate')
        await command('eyes')
        await camera(saved=True)
        tab = await asyncio.to_thread(session.cdp._target)
        await listen(tab, 'separate start-before-setup')
        await command('stop')
        # Actual installed extension/native host and trusted action popup.
        await command('setup extension')
        wrapper = native / 'host_entry.py'
        wrapper.write_text('import runpy\nfrom pathlib import Path\n' + f'host=runpy.run_path({str(native / "host.py")!r})\n' + f'host["main"].__globals__["runtime_directory"]=lambda: Path({str(runtime)!r})\n' + 'host["main"]()\n')
        launcher = native / 'host'; launcher.write_text(launcher.read_text().replace(str(native / 'host.py'), str(wrapper)))
        # Local file is deliberately not eligible for the extension; serve a loopback fixture.
        import http.server
        import threading
        class Page(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = FIXTURE.encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            def log_message(self, *a): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Page)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.server_close); stack.callback(server.shutdown)
        unpacked = native / 'unpacked'
        extension_process = subprocess.Popen([args.journey_chrome, f'--user-data-dir={profile}',
            '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
            '--disable-component-update', '--disable-sync', '--disable-default-apps',
            '--password-store=basic', '--use-mock-keychain', '--remote-debugging-port=0',
            f'--disable-extensions-except={unpacked}', f'--load-extension={unpacked}',
            f'http://127.0.0.1:{server.server_port}/'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        stack.callback(lambda: stop(extension_process))
        active = profile / 'DevToolsActivePort'
        await until(active.is_file)
        port, endpoint = active.read_text().splitlines()[:2]
        driver = Driver(f'ws://127.0.0.1:{port}{endpoint}')
        stack.callback(driver.ws.close)
        local_page = next(t for t in driver.targets() if t['type'] == 'page')
        local_session = driver.attach(local_page['targetId'])
        driver.call('Page.enable', session=local_session)
        driver.call('Page.setDocumentContent', dict(frameId=driver.call('Page.getFrameTree', session=local_session)['frameTree']['frame']['id'],
            html=FIXTURE), local_session)
        worker_target = await until(lambda: next((t for t in driver.targets() if t['url'] == f'chrome-extension://{EXTENSION}/worker.js'), None))
        worker = driver.attach(worker_target['targetId'])
        driver.call('Runtime.enable', session=worker)
        await until(lambda: driver.evaluate(worker, 'typeof chrome !== "undefined" && !!chrome.runtime?.id && !!chrome.action'))
        async def pair():
            await asyncio.to_thread(focus, extension_process)
            await asyncio.to_thread(driver.evaluate, worker, 'chrome.action.openPopup().then(()=>true)')
            popup_target = None
            def popup_ready():
                nonlocal popup_target
                popup_target = next((t for t in driver.targets() if t['url'] == f'chrome-extension://{EXTENSION}/popup.html'), None)
                return popup_target
            await until(popup_ready)
            popup = driver.attach(popup_target['targetId'])
            await until(lambda: driver.evaluate(popup, 'document.hasFocus() && !document.getElementById("pair").hidden'))
            point = driver.evaluate(popup, '(()=>{const r=document.getElementById("pair").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()')
            for kind in ('mousePressed', 'mouseReleased'):
                await asyncio.to_thread(driver.call, 'Input.dispatchMouseEvent', dict(type=kind, button='left', clickCount=1, **point), popup)
            try:
                await until(lambda: turns.connected and session.cdp.is_connected)
            except TimeoutError:
                print('PAIR_STATE', session.cdp.connection_status, 'bound', turns.connected,
                      'binding_generation', turns.binding_generation, 'connecting_native',
                      turns.connecting_native is not None,
                      'tabs', [(t.is_connected, bool(t._ui_frames)) for t in session.cdp._tabs.values()],
                      driver.evaluate(worker, '({dead,selected:[...tabs.values()].map(t=>({document:!!t.document,armed:!!t.armedAt}))})'), flush=True)
                raise
            await until(lambda: driver.evaluate(worker, '[...tabs.values()].some(t=>!!t.armedAt)'))
            return next(t for t in session.cdp._tabs.values() if t.is_connected)
        await command('start --extension')
        tab = await pair()
        await listen(tab, 'extension cursor', submit=True)
        check('extension status identifies cursor before eyes', 'Using the pointer' in str(await command('status')))
        await command('setup eyes')
        pid = await camera()
        check('extension setup retains canonical native binding', turns.native_input is not None and turns.connected)
        await command('start')
        check('existing extension start retains tracker', host._process.pid == pid and host._live())
        await listen(tab, 'extension eyes', submit=True)
        await command('start --separate')
        check('separate source change cannot replace live extension camera',
              session.cdp.source == 'extension' and host._live() and host._process.pid == pid)
        replacement = await create('replacement-conversation')
        sid = replacement
        await command('start', replacement)
        await until(lambda: not host._live() and host._process.poll() is not None)
        check('new session revokes old camera authority', turns.binding['session_id'] == replacement)
        await command('stop', replacement)
        await command('setup eyes', replacement)
        check('disconnected extension cannot launch or rebind camera',
              not turns.connected and host._process.poll() is not None)
        await command('start --extension', replacement)
        tab = await pair()
        check('stop and reconnect report cursor until explicit eye activation',
              session.tracker.mode == 'hover' and 'Using the pointer' in str(await command('status')))
        await command('eyes', replacement)
        await camera(saved=True)
        await listen(tab, 'extension saved eyes', submit=True)
        saved_profile = host.profile_path.read_bytes()
        await command('cursor', replacement)
        await until(lambda: host._process.poll() is not None)
        check('explicit cursor stops camera and changes page source',
              await asyncio.to_thread(page, tab, 'window.__HERMES_GAZE_OVERLAY__.state.mode') == 'hover')
        host.profile_path.write_text('{"model_id":"invalid"}')
        await command('eyes', replacement)
        await until(lambda: host.state == 'running')
        await front(tab)
        check('invalid saved calibration never falls back to cursor',
              host.profile is None and session.tracker.mode == 'webcam' and
              await asyncio.to_thread(page, tab, 'window.__HERMES_GAZE_OVERLAY__.state.mode') == 'webcam')
        await asyncio.to_thread(cmd, tab, 'Input.dispatchMouseEvent', dict(type='mouseMoved', x=100, y=24))
        await asyncio.to_thread(cmd, tab, 'Input.dispatchKeyEvent', dict(type='keyDown', code='Space', key=' ', windowsVirtualKeyCode=32))
        await asyncio.sleep(1)
        await asyncio.to_thread(cmd, tab, 'Input.dispatchKeyEvent', dict(type='keyUp', code='Space', key=' ', windowsVirtualKeyCode=32))
        check('invalid calibration blocks capture instead of using cursor', turns.capture_state == 'idle' and
              'needs calibration' in str(await command('status', replacement)))
        await command('cursor', replacement)
        host.profile_path.write_bytes(saved_profile)
        await command('eyes', replacement)
        await camera(saved=True)
        await listen(tab, 'extension recovered eyes')
        await command('stop', replacement)
        return results
