"""Headless, fake camera only: every calibration, check and practice state.

Run: .venv/bin/python tests/calibration_chrome.py --out /absolute/output-directory
Private profiles on allocated ports. Never the user's Chrome, port 9333, a real camera,
microphone or speakers. Only `predict` is scripted for the passing path; fitting, binding
and camera frames are real. A translated portrait proves plumbing, NOT gaze accuracy.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
import tests
from benchmark.probe_companion_ui import Tab, make_recording
from look.tracker.webcam_gaze import AppearanceEstimator, LandmarkEstimator, ScreenPoint
from look.browser.webcam import WebcamHost
from tests.webcam_chrome import PORTRAIT, PORTRAIT_HASH, tracker_tab, until

HEADLESS = ("--headless=new", "--window-size=1440,900", "--screen-info={1440x900}")
SPOT, FACE_SECONDS, BLACK_SECONDS = 3, 27, 4
PERIOD = FACE_SECONDS + BLACK_SECONDS


class Scripted(AppearanceEstimator):
    """Real fit and profile; the passing path only replaces the final estimate."""
    script = None
    fail_next_fit = False

    def calibrate(self, observations, screen):
        if Scripted.fail_next_fit:
            Scripted.fail_next_fit = False
            raise ValueError("Calibration did not fit the targets; try again in better light")
        return super().calibrate(observations, screen)

    def predict(self, features, t):
        return Scripted.script(features, t) if Scripted.script else super().predict(features, t)


def fixture(directory):
    portrait, video = directory / "nasa.jpg", directory / "face.y4m"
    data = urllib.request.urlopen(PORTRAIT, timeout=45).read()
    assert hashlib.sha256(data).hexdigest() == PORTRAIT_HASH
    portrait.write_bytes(data)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        f"color=c=black:s=640x480:r=15:d={PERIOD}", "-loop", "1", "-i", str(portrait), "-filter_complex",
        f"[1:v]crop=650:650:150:80,scale=300:300[face];[0:v][face]overlay=x='30+140*mod(floor(t/{SPOT}),3)':y='90*floor(t/{3 * SPOT})':enable='lt(t,{FACE_SECONDS})':shortest=1",
        "-t", str(PERIOD), "-r", "15", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=60)
    return video


class Window:
    def __init__(self, host, out, scheme="light"):
        self.host, self.out, self.scheme = host, out, scheme
        status = host.start(wait=25)
        assert status["state"] in ("running", "failed"), status
        self.tab = tracker_tab(host)
        self.tab.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})

    def state(self):
        return self.tab.iso("globalThis.__HERMES_WEBCAM__.status()", self.host._context)

    def wait(self, phase, seconds=30):
        try:
            until(lambda: self.state()["phase"] == phase, seconds)
        except AssertionError:
            raise AssertionError({"expected": phase, "ui": self.state(), "host": self.host.status(),
                                  "text": self.text(), "screen": self.tab.main("[screen.width,screen.height,screen.availLeft,screen.availTop]"),
                                  "saved_screen": self.host.profile and self.host.profile["screen"]}) from None

    def text(self):
        return self.tab.main("document.body.innerText")

    def shot(self, name, settle=.55):
        time.sleep(settle)
        data = self.tab.send("Page.captureScreenshot", {"format": "png"})["data"]
        (self.out / f"{'' if self.scheme == 'light' else self.scheme + '-'}{name}.png").write_bytes(base64.b64decode(data))

    def click(self, action):
        box = until(lambda: self.tab.main(
            f"(()=>{{const b=[...document.querySelectorAll('[data-action={action}]')].find(n=>n.getClientRects().length);if(!b||b.disabled)return null;"
            "const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()"))
        for kind in ("mousePressed", "mouseReleased"):
            self.tab.send("Input.dispatchMouseEvent", {"type": kind, "button": "left", "clickCount": 1, **box})

    def key(self, kind, name="Space", *, repeat=False):
        key, code = (" ", 32) if name == "Space" else ("Escape", 27)
        self.tab.send("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": name, "windowsVirtualKeyCode": code, "autoRepeat": repeat})

    def tap(self, name="Space"):
        self.key("keyDown", name); self.key("keyUp", name)

    def clock(self):
        return self.state()["videoTime"] % PERIOD

    def nine(self, shots=False):
        self.click("calibrate"); self.wait("calibrate")
        if shots:
            assert "Tap" in self.text()
            self.shot("03-first-dot-tap-space")
        for index in range(9):
            for attempt in range(4):
                until(lambda: self.state()["index"] != index or
                      index * SPOT + .35 <= self.clock() < index * SPOT + .75 and self.state()["face"], PERIOD + 8)
                if self.state()["index"] != index:
                    break  # A delayed acceptance can arrive while waiting for the next footage cycle.
                self.tap()
                self.key("keyDown", repeat=True); self.key("keyUp")
                snapshot = self.tab.iso("({state:__HERMES_WEBCAM__.status(),progress:document.getElementById('progress').textContent})", self.host._context)
                if snapshot["state"]["phase"] == "calibrate":
                    assert snapshot["progress"] == f"{snapshot['state']['index'] + 1} of 9"
                if shots and index == 4:
                    self.shot("progress", .15)
                time.sleep(1.4)
                if self.state()["index"] != index or self.state()["phase"] != "calibrate":
                    break
            else:
                raise AssertionError(f"Fake camera rejected target {index + 1} four times")

    def fit(self, report, shots=False):
        """Fake footage is not a person: a real fit can legitimately fail. Say so, then retry."""
        for _ in range(4):
            self.nine(shots=shots)
            until(lambda: self.state()["phase"] in ("boundary", "result"), 30)
            if self.state()["phase"] == "boundary":
                return
            report["fit_retries"] = report.get("fit_retries", 0) + 1
        raise AssertionError("Fit failed four times on fake footage")

    def start_check(self):
        until(lambda: .1 <= self.clock() < 1.2, PERIOD + 8)  # All sixteen seconds fall inside the face footage.
        self.tap(); self.wait("check", 4)

    def finish_check(self, start=0):
        if self.state()["phase"] == "boundary":
            self.click("start-check"); self.wait("checkIntro")
        for index in range(start, 10):
            until(lambda: self.state()["phase"] == "checkIntro" and self.state()["checkIndex"] == index, 5)
            for attempt in range(4):
                # A full real observation fits between the portrait's movements.
                until(lambda: .45 <= self.clock() % SPOT < .55 and self.clock() < FACE_SECONDS - 1.7 and self.state()["face"], PERIOD + 8)
                assert f"{index + 1} of 10" in self.text()
                self.tap()
                trace = []
                for _ in range(18):
                    time.sleep(.1)
                    s = self.state()
                    trace.append((round(self.clock(), 2), s["phase"], s["face"], s["checkIndex"]))
                if self.state()["phase"] == "result" or self.state()["checkIndex"] != index:
                    break
                assert self.state()["phase"] == "checkIntro" and f"{index + 1} of 10" in self.text()
            else:
                raise AssertionError({"target": index + 1, "trace": trace, "text": self.text(),
                                      "trial": self.host._check and self.host._check["trial"]})
        self.wait("result", 5)

    def close(self):
        self.tab.ws.close(); self.host.stop()


def delayed_check_ack(window):
    """Face loss after a completed trial cannot undo a pending Python acknowledgement."""
    host, queued, original = window.host, [], window.host._ui
    def delay(method, value=""):
        if method == "checkAccepted":
            queued.append((method, value))
        else:
            original(method, value)
    with patch.object(host, "_ui", side_effect=delay):
        until(lambda: .45 <= window.clock() % SPOT < .55 and window.clock() < FACE_SECONDS - 1.7 and window.state()["face"], PERIOD + 8)
        window.tap()
        until(lambda: queued, 5)
        assert host._check["trial"] == 1 and window.state()["checkIndex"] == 0
        until(lambda: not window.state()["face"], PERIOD + 8)
        assert window.state()["phase"] == "check", "completed observation must wait for its acknowledgement"
        original(*queued[0])
        until(lambda: window.state()["checkIndex"] == 1)
        assert window.state()["phase"] == "checkIntro"

def jittered(host, misses=()):
    """Scripted estimates near each target; trials in `misses` land clearly elsewhere."""
    drift = ((-.04, .03), (.05, -.02), (.03, .05), (-.05, -.04), (.02, -.06))
    def predict(_features, t):
        check = host._check
        if check is None:
            return None
        trial = min(check["trial"], len(check["targets"]) - 1)
        x, y = check["targets"][trial]
        s = check["screen"]
        dx, dy = (.24, .2) if trial in misses and trial % 2 else (-.27, .14) if trial in misses else drift[trial % 5]
        return ScreenPoint(s["left"] + (x + dx) * s["width"], s["top"] + (y + dy) * s["height"], t)
    return predict


def camera_failure(tmp, video, out, report):
    source = (ROOT / "browser" / "webcam_host.js").read_text()
    needle = "const acquired = await navigator.mediaDevices.getUserMedia("
    assert needle in source
    broken = tmp / "broken_camera.js"
    broken.write_text(source.replace(needle, "throw new DOMException('Could not start video source', 'NotReadableError');\n    " + needle))
    used = []
    host = WebcamHost(lambda *_: False, profile_path=tmp / "none.json", runtime_source=broken, chrome_args=HEADLESS,
                      fake_video=video, on_use_cursor=lambda: used.append(True))
    window = Window(host, out)
    try:
        window.wait("error")
        words = window.text()
        assert "Camera in use" in words and "Try again" in words and "Use cursor" in words, words
        assert host.status()["state"] == "failed"
        window.shot("01-camera-error")
        window.click("retry"); until(lambda: "Camera in use" in window.text()); window.wait("error")
        window.click("cursor"); until(lambda: used)
        report["camera_error"] = {"plain_label_shown": True, "retry_offered": True, "use_cursor_changes_mode": True}
    finally:
        window.close()


def old_profile(tmp, video, out, report):
    from tests.test_webcam import SCREEN, observations
    path = tmp / "old" / "calibration.json"; path.parent.mkdir()
    path.write_text(json.dumps(LandmarkEstimator().calibrate(observations(), SCREEN)))
    before = path.read_bytes()
    window = Window(WebcamHost(lambda *_: False, profile_path=path, fake_video=video, chrome_args=HEADLESS), out)
    try:
        window.wait("home"); until(lambda: window.state()["face"], PERIOD + 8)
        assert "Recalibration needed" in window.text() and "The eye tracker has changed." in window.text()
        assert not window.host.status()["calibrated"] and path.read_bytes() == before
        window.shot("11-old-calibration")
        report["old_profile"] = {"refused_with_plain_message": True, "file_unchanged": True}
    finally:
        window.close()


def main_flow(tmp, video, out, report, scheme="light"):
    path = tmp / f"personal-{scheme}" / "calibration.json"
    host = WebcamHost(lambda *_: False, estimator=Scripted(), profile_path=path, fake_video=video, chrome_args=HEADLESS)
    window = Window(host, out, scheme)
    checks = []
    def check(ok, name):
        assert ok, name
        checks.append(name)
    def selected():
        return window.tab.main("document.querySelectorAll('.topic.selected').length")
    try:
        window.wait("home"); until(lambda: window.state()["face"], PERIOD + 8)
        check(window.tab.main("typeof __HERMES_WEBCAM__") == "undefined", "isolated runtime")
        check(window.text().strip() == "Set up eye tracking\n\nStart calibration\nUse cursor", "entry whitelist")
        window.shot("setup")
        # No observation advances merely because Space repeats or the face disappears.
        window.click("calibrate"); window.wait("calibrate")
        check("1 of 9" in window.text() and "Tap Space" in window.text(), "single initial instruction")
        window.tab.main("document.getElementById('cancel').focus()")
        window.tap(); window.wait("home"); until(lambda: host._calibration is None)
        check(not path.exists(), "focused Cancel Space cancels training without observing")
        window.click("calibrate"); window.wait("calibrate")
        until(lambda: FACE_SECONDS + .8 <= window.clock(), PERIOD + 8)
        window.tap(); time.sleep(1.3)
        check(window.state()["index"] == 0 and not window.state()["collecting"], "missing face cannot collect")
        window.tap("Escape"); window.wait("home")
        window.fit(report, shots=True)
        check(not path.exists() and host._check is not None and not host._check["started"], "unsaved stopped candidate")
        window.shot("boundary")
        for _ in range(3): window.tap()
        time.sleep(1.8)
        check(window.state()["phase"] == "boundary" and host._check["trial"] == 0, "neutral Space never starts check")
        # Resizing at the boundary discards the candidate and stale callbacks.
        queued = []
        with patch.object(host, "_send", side_effect=lambda method, params: queued.append(params["expression"])):
            host._ui("checkReady", {"points": [[.5, .5]]})
        window.tab.send("Emulation.setDeviceMetricsOverride", {"width": 1300, "height": 800, "deviceScaleFactor": 1, "mobile": False})
        window.wait("moved")
        until(lambda: host._check is None)
        check(not path.exists(), "resize discards unsaved candidate")
        window.tab.iso(queued[0], host._context)
        check(window.state()["phase"] == "moved", "old callback cannot resurrect")
        window.tab.send("Emulation.clearDeviceMetricsOverride", {})
        window.click("home"); window.wait("home")
        window.fit(report)
        window.click("cancel"); window.wait("home")
        until(lambda: host._check is None)
        check(not path.exists(), "boundary Cancel discards candidate")
        if scheme == "light":
            window.tab.send("Page.startScreencast", {"format": "jpeg", "quality": 75, "maxWidth": 1280, "maxHeight": 720, "everyNthFrame": 2})
        window.fit(report)
        Scripted.script = jittered(host)
        window.finish_check()
        check("Calibration saved" in window.text(), "passing check result")
        check(path.exists() and path.stat().st_mode & 0o777 == 0o600, "private save after pass")
        saved = path.read_bytes()
        window.shot("saved")
        if scheme == "light":
            window.tab.send("Page.stopScreencast")
            make_recording(window.tab, out)
        # Optional practice uses real-frame Python predictions, never page delivery.
        def at(_f, t):
            v = host._practice or {"left": 0, "top": 0, "width": 1440, "height": 900}
            return ScreenPoint(v["left"] + .75 * v["width"], v["top"] + .35 * v["height"], t)
        Scripted.script = at
        until(lambda: .1 <= window.clock() < 12, PERIOD + 8)
        window.click("practise"); window.wait("practice")
        until(selected)
        check(host.delivered == 0 and "Practice:" not in window.text(), "practice stays local without caption")
        window.shot("practice")
        Scripted.script = lambda *_: None
        until(lambda: selected() == 0)
        check("Off screen" not in window.text(), "offscreen removes highlight silently")
        until(lambda: FACE_SECONDS + .8 <= window.clock(), PERIOD + 8)
        until(lambda: "Bring your face into view." in window.text())
        check(selected() == 0, "face loss removes highlight")
        # Guided Space gestures and completion are covered by calibration_return_chrome.
        window.click("done"); window.wait("return-error")
        check(window.state()["active"] and host._practice is None and host.state == "running", "standalone host retains inference and honest recovery")
        window.shot("return-recovery", .1)
        window.close()
        # New process, same profile: direct checking skips training.
        host = WebcamHost(lambda *_: False, estimator=Scripted(), profile_path=path, fake_video=video, chrome_args=HEADLESS)
        window = Window(host, out, scheme)
        window.wait("home"); until(lambda: window.state()["face"], PERIOD + 8)
        window.click("check"); window.wait("checkIntro")
        check(window.state()["checkIndex"] == 0 and host._calibration is None, "saved entry skips training")
        window.tab.main("document.getElementById('cancel').focus()")
        window.tap(); window.wait("home"); until(lambda: host._check is None)
        check(path.read_bytes() == saved, "focused Cancel Space cancels checking without changing profile")
        window.click("check"); window.wait("checkIntro")
        Scripted.script = jittered(host)
        delayed_check_ack(window)
        check(window.state()["checkIndex"] == 1, "completed trial survives face loss before acknowledgement")
        window.finish_check(start=1)
        check("Saved calibration passed" in window.text() and path.read_bytes() == saved, "saved pass never rewrites profile")
        # Optional practice can be skipped with native Space on its focused button.
        window.tab.main("document.querySelector('[data-action=done]').focus()")
        window.tap(); window.wait("return-error")
        check(window.state()["active"] and host._practice is None, "focused skip does not rehearse or stop inference")
        window.close()
        host = WebcamHost(lambda *_: False, estimator=Scripted(), profile_path=path, fake_video=video, chrome_args=HEADLESS)
        window = Window(host, out, scheme)
        window.wait("home"); until(lambda: window.state()["face"], PERIOD + 8)
        window.click("check"); window.wait("checkIntro")
        Scripted.script = lambda *_: None
        window.finish_check()
        check("Couldn’t see your eyes clearly" in window.text() and "Saved calibration unchanged." in window.text(), "insufficient check recovery")
        check(path.read_bytes() == saved, "failed saved check preserves profile")
        window.shot("insufficient")
        Scripted.script = None
        Scripted.fail_next_fit = True
        window.nine(); window.wait("result", 30)
        check("Couldn’t calibrate" in window.text() and path.read_bytes() == saved, "fit failure preserves profile")
        window.shot("fit-failed")
        report[scheme] = {"checks": checks, "passed": len(checks)}
    finally:
        Scripted.script = None
        window.close()


def dark_smoke(tmp, video, out, report):
    path = tmp / "personal-light" / "calibration.json"
    before = path.read_bytes()
    host = WebcamHost(lambda *_: False, estimator=Scripted(), profile_path=path, fake_video=video, chrome_args=HEADLESS)
    window = Window(host, out, "dark")
    try:
        window.wait("home"); until(lambda: window.state()["face"], PERIOD + 8)
        window.shot("setup")
        window.click("check"); window.wait("checkIntro")
        assert "1 of 10" in window.text()
        until(lambda: window.tab.main("getComputedStyle(document.body).backgroundColor") == "rgb(239, 239, 242)")
        window.shot("check")
        window.tap("Escape"); window.wait("home")
        window.fit(report)
        until(lambda: window.tab.main("getComputedStyle(document.body).backgroundColor") == "rgb(27, 27, 30)")
        window.shot("boundary")
        assert window.tab.main("document.documentElement.scrollWidth <= innerWidth")
        window.tab.send("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-color-scheme", "value": "dark"},
            {"name": "prefers-reduced-transparency", "value": "reduce"},
            {"name": "prefers-reduced-motion", "value": "reduce"}]})
        window.shot("boundary-solid")
        assert "Ready to check" in window.text() and "of 9" not in window.text()
        window.click("cancel"); window.wait("home")
        until(lambda: host._check is None)
        assert path.read_bytes() == before and host._check is None
        report["dark"] = {"saved_entry": True, "neutral_measurement": True, "stopped_boundary": True,
                          "solid_reduced_motion": True, "no_overflow": True, "saved_profile_unchanged": True}
    finally:
        window.close()



def run(out, schemes=("light", "dark")):
    out.mkdir(parents=True, exist_ok=True)
    report = {"accuracy": "Not measured; a translated portrait tests plumbing only."}
    with tempfile.TemporaryDirectory(prefix="hermes-calibration-probe-") as tmp:
        tmp = Path(tmp)
        video = fixture(tmp)
        camera_failure(tmp, video, out, report)
        old_profile(tmp, video, out, report)
        for scheme in schemes:
            if scheme == "dark" and "light" in schemes:
                dark_smoke(tmp, video, out, report)
            else:
                main_flow(tmp, video, out, report, scheme)
    (out / "calibration-results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--schemes", nargs="+", choices=("light", "dark"), default=("light", "dark"))
    args = parser.parse_args()
    run(args.out.resolve(), tuple(args.schemes))
