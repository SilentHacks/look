"""Real flattened transport/renderer proof on owned disposable Chrome, NOT native consent proof.

No personal profiles/accounts, devices, model, downloads or native-dialog automation.
The fixture alone substitutes a token-verified owned root for human approval.
"""
import asyncio
import http.server
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests
from tests.owned_chrome import private_session
from tests.test_chrome_consent import until
from hermes_gaze.browser.cdp_bridge import CdpSession, GazeSession
from hermes_gaze.browser.consent import ConsentChrome
from hermes_gaze.browser.ownership import acquire_runtime_lease
from websockets.sync.client import connect


class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b'<!doctype html><title>Disposable fixture</title><p id="target">Fixture target</p>'
                         b'<input id="draft"><script>document.cookie="look_fixture=retained; SameSite=Strict"</script>')

    def log_message(self, *_):
        pass


def command(ws, method, params=None):
    ws.send(json.dumps(dict(id=1, method=method, params=params or {})))
    while True:
        message = json.loads(ws.recv(timeout=5))
        if message.get("id") == 1:
            assert "error" not in message, "disposable CDP command failed"
            return message.get("result", {})


def approve_owned_fixture(root, owner):
    # Production ConsentChrome.start REFUSES this legacy endpoint. Only this
    # private fixture may supply its independently verified socket directly.
    sock = socket.create_connection(("127.0.0.1", int(owner.http_url.rsplit(":", 1)[1])))
    root._socket = sock
    root._ws = connect(owner.http_url.replace("http://", "ws://") + owner._ws.request.path,
                       sock=sock, proxy=None, origin=None, close_timeout=1)
    root._reader = threading.Thread(target=root._read, args=(root._ws,), daemon=True)
    root._reader.start()
    owner.verify_arguments(root.command("Browser.getBrowserCommandLine"))
    product = root.command("Browser.getVersion")["product"]
    root.default_context = root.command("Target.getBrowserContexts").get("defaultBrowserContextId")
    assert root.default_context, "installed Chrome cannot prove regular context"
    root._lease = acquire_runtime_lease(root.lease_dir)
    root.state = "connected"
    root.start = lambda **_: root.attach()
    return product


def run():
    with tempfile.TemporaryDirectory(prefix="look-flat-chrome-") as directory:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/"
        fixture = private_session(Path(directory) / "chrome", chrome_args=("--headless=new",), url=url)
        owner = fixture.cdp.chrome
        process = owner.process
        session = GazeSession(profile_dir=Path(directory) / "look")
        root = ConsentChrome(lease_dir=Path(directory) / "look")
        try:
            second = owner.command("Target.createTarget", {"url": url})["targetId"]
            product = approve_owned_fixture(root, owner)
            ready = threading.Event()
            with patch("hermes_gaze.browser.companion.ConsentChrome", return_value=root):
                session.cdp.start_existing(on_ready=ready.set)
                assert ready.wait(15), "flattened renderer readiness failed"
            until(lambda: len(session.cdp._tabs) == 2 and all(t.is_connected for t in session.cdp._tabs.values()), 15)
            tabs = list(session.cdp._tabs.values())
            assert all(set(tab._ui_frames) == {"card", "pill"} for tab in tabs)
            assert all(tab.eval_js("!!window.__HERMES_GAZE_OVERLAY__") for tab in tabs)
            assert tabs[0]._context_unique_id != tabs[1]._context_unique_id
            print("PASS flattened two-tab isolated overlay and opaque script-disabled renderer:", product)
            source = session.cdp._tabs[second]
            source._submit(source._send_cmd("Emulation.setFocusEmulationEnabled", {"enabled": True}, 2), 3)
            owner_info = session.cdp._document_owner(source)
            source.eval_js_once("document.querySelector('#draft').value='retained'; true")
            transferred = session.cdp.action_navigate(url + "next", new_tab=True, **owner_info)
            new_tab = session.cdp._tabs[transferred["browser_target"]]
            info = root.command("Target.getTargetInfo", {"targetId": new_tab._target_id})["targetInfo"]
            assert info["browserContextId"] == root.default_context
            print("PASS source-context new-tab creation, activation and exact-document authority transfer")
            targets = set(session.cdp._tabs)
            session.close()
            assert process.poll() is None
            assert targets.issubset({t["targetId"] for t in owner.command("Target.getTargets")["targetInfos"]})
            endpoint = owner.http_url.replace("http://", "ws://") + "/devtools/page/" + second
            with connect(endpoint, proxy=None, close_timeout=1) as inspector:
                def read(expression):
                    return command(inspector, "Runtime.evaluate", dict(expression=expression, returnByValue=True))["result"].get("value")
                assert read("!document.getElementById('hermes-gaze-root')") is True
                assert read("document.querySelector('#draft').value === 'retained' && document.cookie.includes('look_fixture=retained')")
                origin = read("performance.timeOrigin")
                command(inspector, "Page.reload")
                until(lambda: read(f"performance.timeOrigin !== {origin} && document.readyState === 'complete'"))
                assert read("!document.getElementById('hermes-gaze-root')") is True
            print("PASS Stop detaches overlays/new-document scripts; Chrome, tabs, draft and fixture cookie remain")
            root = ConsentChrome(lease_dir=Path(directory) / "look")
            approve_owned_fixture(root, owner)
            entered = threading.Event()
            async def blocked_ui(tab):
                entered.set()
                while not tab._closed:
                    await asyncio.sleep(.01)
                raise ConnectionError("Stopped during renderer initialization")
            with patch("hermes_gaze.browser.companion.ConsentChrome", return_value=root), \
                 patch.object(CdpSession, "_init_ui", blocked_ui):
                session.cdp.start_existing()
                assert entered.wait(10), "overlay injection barrier not reached"
                session.close()
            for target in targets:
                endpoint = owner.http_url.replace("http://", "ws://") + "/devtools/page/" + target
                with connect(endpoint, proxy=None, close_timeout=1) as inspector:
                    result = command(inspector, "Runtime.evaluate", {
                        "expression": "!document.getElementById('hermes-gaze-root')", "returnByValue": True})
                    assert result["result"]["value"] is True, "Stop left partial-startup DOM installed"
            print("PASS Stop during renderer startup removes actual injected DOM before root closure")
            assert session.webcam is None and session.microphone._stream is None
            print("NOT TESTED native Allow/deny dialog, personal sign-in, managed policy or real devices")
        finally:
            session.close()
            root.close()
            fixture.close()
            if process.poll() is None:
                process.terminate()  # Only our own disposable Popen; never a discovered browser.
                process.wait(10)
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    run()
