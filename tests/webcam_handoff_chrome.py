"""Fake camera and disposable Chrome only; no user profile, devices or model calls.

Run: .venv/bin/python tests/webcam_handoff_chrome.py --out /tmp/look-handoff
Synthetic predictions test delivery, not eye-tracking accuracy.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
import tests
from tests.calibration_chrome import HEADLESS, Scripted, Window, fixture
from tests.test_webcam import appearance_observations
from tests.ui_review.devlib import Rig, until
from look.browser.webcam import WebcamHost
from look.tracker.webcam_gaze import AppearanceEstimator, ScreenPoint


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    os.environ["SHOTS"] = str(out)
    checks = []
    def check(ok, label):
        assert ok, label
        checks.append(label)
        print("PASS", label, flush=True)
    with tempfile.TemporaryDirectory(prefix="look-handoff-") as tmp:
        tmp = Path(tmp)
        video = fixture(tmp)
        rig = Rig(scale=1)
        host = window = None
        try:
            source = rig.new_tab()
            rig.cmd("Emulation.clearDeviceMetricsOverride", {}, source)
            rig.cmd("Emulation.setFocusEmulationEnabled", {"enabled": False}, source)
            screen = rig.page("({left:screen.availLeft,top:screen.availTop,width:screen.availWidth,height:screen.availHeight,screen_width:screen.width,screen_height:screen.height,screen_left:screen.availLeft,screen_top:screen.availTop,dpr:devicePixelRatio})")
            rig.session.configure(mode="webcam")
            host = WebcamHost(rig.session._accept_webcam_point, estimator=Scripted(), fake_video=video,
                profile_path=tmp / "calibration.json", chrome_args=HEADLESS,
                on_use_cursor=lambda: rig.session.configure(mode="hover"))
            host._save(AppearanceEstimator().calibrate(appearance_observations(), screen))
            Scripted.script = lambda f, t: ScreenPoint(screen["left"] + screen["width"] / 2,
                                                     screen["top"] + screen["height"] / 2, t)
            rig.session.webcam = host
            rig.session.start_webcam()
            until(lambda: host.state in ("running", "failed"), 25)
            window = Window(host, out)
            until(lambda: window.state()["face"])
            host._ui("checkResult", host._result_words("good", False))
            window.wait("result")
            identity = (host._process.pid, host._context)
            # Preserve the verified browser/root but remove every supported destination.
            chrome = rig.session.cdp.chrome
            chrome.command("Target.createTarget", {"url": "chrome://version"})
            for target in tuple(rig.session.cdp._tabs):
                chrome.command("Target.closeTarget", {"targetId": target})
            until(lambda: not rig.session.cdp.is_connected)
            before = host.samples
            until(lambda: host.samples > before + 4 or host.state != "running")
            check(host.state == "running" and host._process.poll() is None,
                  "missing last browsing tab retains owned camera and real-frame inference")
            window.click("done"); window.wait("return-error")
            check("That page is no longer available" in window.text(), "missing destination reports no false focus")
            window.click("return"); window.wait("return-error")
            window.click("start-page"); window.wait("tracking", 15)
            fallback = rig.session.cdp._start_owner
            rig.tab = rig.session.cdp._tabs[fallback["browser_target"]]
            check(rig.page("document.hasFocus() && !document.hidden") and "Start browsing" in rig.page("document.body.innerText"),
                  "explicit fallback opens and actually focuses its own browsing page")
            check((host._process.pid, host._context) == identity and window.state()["active"],
                  "fallback retains exact tracker process and inference context")
            rig.move(500, 350)
            delivered = host.delivered
            until(lambda: host.delivered > delivered + 3, 15)
            check(rig.session.ring_buffer.latest().source == "webcam", "post-fallback fake-camera predictions reach session ingest")
            window.tab.send("Page.bringToFront", {})
            window.click("return"); window.wait("tracking", 10)
            check(rig.page("document.hasFocus() && !document.hidden"), "later return uses fallback owner rather than missing original")
            window.tab.send("Page.bringToFront", {})
            try:
                window.click("cursor")
            except TimeoutError:
                # Stop can close CDP before the trusted release's reply. Never replay it.
                assert host._stop.is_set()
            until(lambda: host.state == "stopped" and host._process.poll() is not None)
            check(rig.session.tracker.mode == "hover" and chrome.process.poll() is None,
                  "explicit cursor stop closes only owned tracker and preserves browsing process")
        finally:
            Scripted.script = None
            if window:
                window.close()
            elif host:
                host.stop()
            rig.close()
    (out / "handoff-results.json").write_text(json.dumps({"checks": checks, "passed": len(checks)}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args().out.resolve())
