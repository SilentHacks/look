"""No devices, host, accounts or model calls: temporary owned Chrome lifecycle."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests
from tests.owned_chrome import private_session
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.browser.ownership import OwnedChrome, OwnershipError
from websockets.sync.client import connect


def command(ws, method, params=None):
    ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
    while True:
        message = json.loads(ws.recv(timeout=5))
        if message.get("id") == 1:
            assert "error" not in message, message
            return message.get("result", {})


def run():
    with tempfile.TemporaryDirectory(prefix="look-owned-chrome-") as directory:
        profile = Path(directory) / "companion"
        session = private_session(profile, chrome_args=("--headless=new", "--disable-gpu"))
        chrome = session.cdp.chrome.process
        endpoint = session.cdp_http_url
        restarted = None
        try:
            assert session.ensure_overlay(), "owned Chrome must attach"
            tab = next(tab for tab in session.cdp._tabs.values() if tab.is_connected)
            target = tab._target_id
            assert tab.eval_js("!!window.__HERMES_GAZE_OVERLAY__")
            assert set(tab._ui_frames) == {"card", "pill"}
            browser_id = session.cdp.chrome.command("Browser.getVersion")["product"]
            print("PASS owned launch and exact-context protected renderers:", browser_id)
            competitor = OwnedChrome(endpoint, profile)
            try:
                competitor.attach()
                raise AssertionError("second runtime acquired live ownership")
            except OwnershipError as exc:
                assert "Another Look runtime" in str(exc)
            print("PASS competing runtime fails before attachment")
            # Even knowing the token does not make a different profile the companion.
            wrong_profile = Path(directory) / "wrong"
            wrong_profile.mkdir(mode=0o700)
            token = wrong_profile / ".look-owner"
            token.write_bytes((profile / ".look-owner").read_bytes())
            token.chmod(0o600)
            wrong = GazeSession(endpoint, profile_dir=wrong_profile)
            try:
                assert not wrong.ensure_overlay()
                assert not wrong.cdp._tabs
            finally:
                wrong.close()
            print("PASS wrong-profile Chrome refused before page attachment")
            marker = profile / "retained-user-data"
            marker.write_text("keep")
            ws_url = endpoint.replace("http://", "ws://") + "/devtools/page/" + target
            session.close()
            assert chrome.poll() is None
            with connect(ws_url, proxy=None) as inspector:
                result = command(inspector, "Runtime.evaluate", {
                    "expression": "!document.getElementById('hermes-gaze-root')", "returnByValue": True})
                assert result["result"]["value"] is True, result
                origin = command(inspector, "Runtime.evaluate", {
                    "expression": "performance.timeOrigin", "returnByValue": True})["result"]["value"]
                command(inspector, "Page.reload")
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    state = command(inspector, "Runtime.evaluate", {
                        "expression": f"performance.timeOrigin !== {origin} && document.readyState === 'complete'",
                        "returnByValue": True})["result"].get("value")
                    if state:
                        break
                    time.sleep(.05)
                assert state
                assert command(inspector, "Runtime.evaluate", {
                    "expression": "!document.getElementById('hermes-gaze-root')",
                    "returnByValue": True})["result"]["value"]
            print("PASS Stop removes overlay/input; Chrome, tabs and profile remain")
            subprocess.run([sys.executable, "-B", "-c",
                "import tests; from pathlib import Path; from hermes_gaze.browser.cdp_bridge import GazeSession; "
                f"s=GazeSession({endpoint!r}, profile_dir=Path({str(profile)!r})); "
                "assert s.cdp.start(); assert s.cdp.chrome.process is None; s.close(); "
                "print('PASS separate-process warm ownership and clean lock handoff')"], check=True, timeout=25)
            restarted = GazeSession(endpoint, profile_dir=profile)
            assert restarted.cdp.start(), "new runtime must verify and reuse the warm companion"
            assert restarted.cdp.chrome.process is None, "warm restart must not spawn Chrome"
            assert marker.read_text() == "keep"
            assert target in restarted.cdp._tabs
            assert restarted.cdp._tabs[target] is not tab
            restarted.configure(mode="webcam")  # State only; never starts the separate camera.
            # Camera return uses this exact attached document, with no camera opening.
            owner = restarted.cdp._document_owner(restarted.cdp._tabs[target])
            assert restarted.cdp._return_tab(owner) is restarted.cdp._tabs[target]
            returned_tab = restarted.cdp._tabs[target]
            returned_tab._submit(returned_tab._send_cmd("Emulation.setFocusEmulationEnabled", {"enabled": True}, timeout=2), 3)
            returned = restarted.cdp.return_to_document(owner, lambda: True)
            assert returned == {"ok": True}, returned
            assert restarted.webcam is None and restarted.microphone._stream is None
            print("PASS warm runtime restart, retained data and actual camera-return foreground/renderer checks; no devices")
            # Chrome exits; a replacement cannot inherit the old page transport.
            try:
                restarted.cdp.chrome.command("Browser.close")
            except OwnershipError:
                pass
            chrome.wait(10)
            deadline = time.monotonic() + 5
            while restarted.cdp._tabs and time.monotonic() < deadline:
                time.sleep(.05)
            assert not restarted.cdp._tabs
            restarted.close()
            # Restart the same profile after an actual browser exit, using fresh identity.
            relaunched = private_session(profile, chrome_args=("--headless=new", "--disable-gpu"))
            try:
                assert relaunched.ensure_overlay()
                assert marker.read_text() == "keep"
                assert (profile / ".look-owner").read_bytes() != token.read_bytes()
                print("PASS exited owned Chrome restarts with fresh launch identity and retained data")
            finally:
                try:
                    relaunched.cdp.chrome.command("Browser.close")
                except OwnershipError:
                    pass
                relaunched.cdp.chrome.process.wait(10)
                relaunched.close()
        finally:
            if restarted:
                restarted.close()
            session.close()
            if chrome.poll() is None:
                # This Popen is ours, never a PID discovered on the user's machine.
                chrome.terminate()
                chrome.wait(10)


if __name__ == "__main__":
    run()
