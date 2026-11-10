"""Owned calibration return, guided silent practice and background camera proof.

Private Chrome profiles, fake video only; no real capture, audio, Hermes or API calls.
The saved fit/result fixture avoids repeating nine-point accuracy checks here.
Run separately from other headed probes so they cannot steal native foreground focus.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
import tests
from tests.calibration_chrome import Window, Scripted, fixture, HEADLESS, PERIOD
from tests.test_webcam import appearance_observations
from tests.ui_review.devlib import Rig, until
from hermes_gaze.browser.webcam import WebcamHost
from hermes_gaze.tracker.webcam_gaze import AppearanceEstimator, ScreenPoint


def run(out, headed=False):
    out.mkdir(parents=True, exist_ok=True)
    os.environ["SHOTS"] = str(out)
    checks, report = [], {"native_focus": headed, "accuracy": "Not measured; saved synthetic fit and scripted predictions."}
    def check(ok, label):
        assert ok, label
        checks.append(label)
    with tempfile.TemporaryDirectory(prefix="hermes-return-proof-") as tmp:
        tmp = Path(tmp)
        video = fixture(tmp)
        rig = Rig(headless=not headed, scale=1)
        host = window = None
        try:
            source = rig.new_tab()
            rig.cmd("Emulation.clearDeviceMetricsOverride", {}, source)
            if not headed:
                # Both private processes simulate the same display; don't weaken the display guard.
                rig.cmd("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 900,
                    "deviceScaleFactor": 1, "mobile": False, "screenWidth": 1440, "screenHeight": 900}, source)
            rig.cmd("Emulation.setFocusEmulationEnabled", {"enabled": False}, source)
            rig.page("document.body.textContent='A captured reading page';document.body.style.height='100vh'")
            until(lambda: rig.page("document.hasFocus() && !document.hidden"))
            screen = rig.page("({left:screen.availLeft,top:screen.availTop,width:screen.availWidth,height:screen.availHeight,screen_width:screen.width,screen_height:screen.height,screen_left:screen.availLeft,screen_top:screen.availTop,dpr:devicePixelRatio})")
            rig.session.configure(mode="webcam")
            rig.move(300, 240)
            host = WebcamHost(rig.session._accept_webcam_point, estimator=Scripted(), fake_video=video,
                profile_path=tmp / "personal" / "calibration.json", chrome_args=() if headed else HEADLESS,
                on_use_cursor=lambda: rig.session.configure(mode="hover"))
            host._save(AppearanceEstimator().calibrate(appearance_observations(), screen))
            rig.session.webcam = host
            rig.session.start_webcam()
            until(lambda: host.state in ("running", "failed"), 25)
            check(host.state == "running", "owned fake camera started")
            window = Window(host, out)
            camera, ctx = window.tab, host._context
            host.calibrate()
            until(lambda: window.state()["face"], PERIOD + 8)
            check(camera.main("typeof __hermesGazeIntent === 'undefined' && typeof __HERMES_WEBCAM__ === 'undefined'"), "camera main world has no binding or runtime")
            # Actual trusted measurement entry, one count and below-dot cue geometry.
            window.click("calibrate"); window.wait("calibrate")
            geometry = camera.main("(()=>{const d=document.querySelector('#dot').getBoundingClientRect(), c=document.querySelector('#cue').getBoundingClientRect();return {below:c.top>d.top,bottom:c.bottom,height:innerHeight}})()")
            check(geometry["below"] and geometry["bottom"] <= geometry["height"], "dot cue below target within viewport")
            window.tap("Escape"); window.wait("home")
            # Existing saved-profile check behavior is separately covered by calibration_chrome.
            def result():
                host._ui("checkResult", host._result_words("good", False)); window.wait("result")
            def predict(_features, t):
                v = host._practice
                if v:
                    return ScreenPoint(v["left"] + v["width"] * .75, v["top"] + v["height"] * .35, t)
                return ScreenPoint(screen["left"] + screen["width"] * .5, screen["top"] + screen["height"] * .5, t)
            Scripted.script = predict
            result(); window.click("practise"); window.wait("practice")
            until(lambda: .35 < window.clock() % 3 < .65 and window.clock() < 25 and window.state()["face"], PERIOD + 8)
            window.tap(); check(window.state()["practiceStep"] in ("tap", "early"), "short release cannot complete rehearsal")
            window.key("keyDown"); time.sleep(.2); window.key("keyUp")
            check(window.state()["practiceStep"] == "early", "early release cannot complete rehearsal")
            window.key("keyDown"); time.sleep(.2); window.tap("Escape"); window.key("keyUp")
            check(window.state()["practiceStep"] == "cancelled", "Escape keeps guided scene and cancels rehearsal")
            until(lambda: .35 < window.clock() % 3 < .65 and window.clock() < 25 and window.state()["face"], PERIOD + 8)
            window.key("keyDown")
            until(lambda: window.state()["practiceStep"] == "waiting")
            until(lambda: window.state()["practiceStep"] == "listening")
            window.shot("guided-listening", .1)
            window.key("keyUp")
            check(window.state()["practiceStep"] == "answer", "release shows labelled silent example")
            until(lambda: rig.turns.coach["rehearsed"])
            check(rig.session.microphone._stream is None and not rig.host.wires, "practice opens no microphone and submits no question")
            window.shot("guided-example", .1)
            camera.main("document.querySelector('[data-action=return]').click()")
            check(window.state()["phase"] == "practice", "synthetic completion click is inert")
            camera.iso("__hermesGazeIntent(JSON.stringify({type:'return_browsing',nonce:'forged',flow:999}))", ctx)
            check(window.state()["phase"] == "practice", "forged completion binding is inert")
            identity = (host._process.pid, host._context, camera.iso("document.getElementById('feed').srcObject.id", ctx))
            window.click("return")
            until(lambda: window.state()["phase"] in ("tracking", "return-error"), 10)
            check(window.state()["phase"] == "tracking", "return observes original foreground without focus emulation")
            check(rig.page("document.hasFocus() && !document.hidden"), "captured reading page actually foreground")
            check((host._process.pid, host._context, camera.iso("document.getElementById('feed').srcObject.id", ctx)) == identity, "return retains exact process document and video stream")
            check(host._practice is None and host._calibration is None and host._check is None, "return discards only unfinished setup work")
            rig.move(430, 310)
            until(lambda: host.delivered > 0, 10)
            if rig.dbg()["view"] == "tracking":
                rig.press("Escape", "Escape")
            count = host.samples
            time.sleep(1.2)
            check(host.samples > count + 3 and host.delivered > 0, "background camera continues real-frame inference and foreground delivery")
            check("Hold Space" not in rig.text("pill"), "completed rehearsal suppresses repeated hold coaching")
            # An actual changed anchor produces persistent private guidance, not a timer.
            rig.iso("window.__HERMES_GAZE_OVERLAY__.Configure({mode:'hover'});window.__HERMES_GAZE_OVERLAY__.Configure({mode:'webcam'});window.__HERMES_GAZE_OVERLAY__.returnFromCalibration()")
            until(lambda: "Move the pointer in this page." in rig.text("pill"))
            rig.press("AltRight", "Alt"); until(lambda: rig.dbg()["view"] == "compose")
            rig.iso("window.__HERMES_GAZE_OVERLAY__.returnFromCalibration()")
            rig.press("Escape", "Escape")
            until(lambda: "Move the pointer in this page." in rig.text("pill"))
            check(True, "origin guidance resumes after composer closes or return arrives during compose")
            rig.space_down(); time.sleep(.25); rig.space_up()
            until(lambda: "Move the pointer in this page." in rig.text("pill"), 6)
            check(rig.session.microphone._stream is None, "origin guidance resumes after temporary Space repair without capture")
            rig.page("document.dispatchEvent(new MouseEvent('mousemove',{bubbles:true,clientX:5,clientY:5}))")
            time.sleep(.2)
            check("Move the pointer in this page." in rig.text("pill"), "synthetic pointer cannot dismiss missing-anchor guidance")
            rig.move(470, 340)
            until(lambda: "Move the pointer" not in rig.text("pill"))
            check(True, "accepted trusted origin clears private pointer guidance")
            rig.iso("window.__HERMES_GAZE_OVERLAY__.returnFromCalibration()")
            check("Move the pointer" not in rig.text("pill"), "anchored page gets no pointer coaching")
            # A real private answer fixture exercises native footer keyboard activation.
            from tests.test_companion_ui import snapshot
            rig.host.answers = [{"text": "## Rings\n\nA scripted answer for keyboard controls.", "think": .1}]
            rig.turns.submit("Keyboard controls fixture", snapshot())
            until(lambda: rig.dbg()["view"] == "answer")
            until(lambda: rig.turns.active is None and rig.turns.runs[-1]["status"] == "complete")
            for key in ("Enter", "Space"):
                rig.panel("card", "document.querySelector('[data-act=tracking]').focus()")
                check(rig.panel("card", "document.activeElement?.dataset.act") == "tracking", f"footer receives keyboard focus for {key}")
                rig.press(key, " " if key == "Space" else key)
                until(lambda: rig.dbg()["view"] == "tracking")
                check(rig.session.microphone._stream is None, f"focused answer footer accepts trusted {key} without capture")
                rig.press("Escape", "Escape"); rig.press("KeyQ", "q")
                until(lambda: rig.dbg()["view"] == "answer")
            rig.press("Escape", "Escape")
            # Cached initialization cannot acknowledge a website-removed protected host.
            rig.iso("window.__HERMES_GAZE_OVERLAY__.uiFrame.getRootNode().host.remove()")
            camera.send("Page.bringToFront", {})
            window.click("return"); window.wait("return-error")
            check("Couldn’t bring your page forward" in window.text(), "missing protected renderer cannot report return success")
            # Returning to the camera is explicit; a replaced source must not be silently retargeted.
            camera.send("Page.bringToFront", {})
            old_document = source._context_unique_id
            rig.cmd("Page.navigate", {"url": (ROOT / "browser" / "start.html").as_uri()}, source)
            until(lambda: source._context_unique_id and source._context_unique_id != old_document)
            window.click("return"); window.wait("return-error")
            check("That page is no longer available" in window.text(), "replaced source stays in honest recovery")
            window.click("return"); window.wait("return-error")
            check("That page is no longer available" in window.text(), "retry rechecks original owner rather than current document")
            # Fallback creation failure stays actionable; explicit retry succeeds.
            with patch.object(rig.session.cdp, "open_start_page", side_effect=OSError("Start page creation unavailable")):
                window.click("start-page"); window.wait("return-error")
                check("Start page creation unavailable" in window.text(), "fallback failure preserves actual error and recovery")
            window.click("start-page"); window.wait("tracking", 15)
            fallback = rig.session.cdp._start_owner
            check(fallback["browser_target"] != source._target_id, "fallback never navigates unrelated existing tab")
            rig.tab = rig.session.cdp._tabs[fallback["browser_target"]]
            check("Start browsing" in rig.page("document.body.innerText") and rig.page("document.hasFocus()"), "explicit owned start surface foreground with protected renderer")
            rig.move(500, 350)
            rig.press("KeyQ", "q")
            until(lambda: rig.dbg()["view"] == "answer")
            check("Hold Space" not in rig.text("pill"), "new destination renderer does not repeat completed practice")
            rig.panel("card", "document.querySelector('[data-act=tracking]').focus()")
            rig.press("Enter", "Enter")
            until(lambda: rig.dbg()["view"] == "tracking")
            # Stop only the fake camera track; watchdog state must repaint the OPEN controls.
            camera.iso("document.getElementById('feed').srcObject.getVideoTracks()[0].stop()", ctx)
            until(lambda: host.state == "failed", 10)
            until(lambda: "Camera unavailable" in rig.text(), 5)
            check(True, "open companion controls update when fake camera frames actually stop")
            rig.click_panel('[data-act="use_cursor"]')
            until(lambda: rig.session.tracker.mode == "hover" and host.state == "stopped")
            check(host._process.poll() is not None, "companion protected Use cursor stops only owned camera")
            report["checks"], report["passed"] = checks, len(checks)
        except BaseException:
            report.update(checks=checks, passed=len(checks), camera=host.status() if host else None,
                          ui=window.state() if window else None, text=window.text() if window else "")
            raise
        finally:
            (out / "return-results.json").write_text(json.dumps(report, indent=2))
            Scripted.script = None
            if window:
                window.close()
            elif host:
                host.stop()
            rig.close()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    run(args.out.resolve(), args.headed)
