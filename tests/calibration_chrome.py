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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
import tests
from benchmark.probe_companion_ui import Tab
from hermes_gaze.tracker.webcam_gaze import AppearanceEstimator, LandmarkEstimator, ScreenPoint
from hermes_gaze.webcam import WebcamHost
from tests.webcam_chrome import PORTRAIT, PORTRAIT_HASH, tracker_tab, until

HEADLESS = ("--headless=new", "--window-size=1440,900", "--screen-info={1440x900}")
SPOT, FACE_SECONDS, BLACK_SECONDS = 2, 18, 4
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
        status = host.start()
        assert status["state"] in ("running", "failed"), status
        self.tab = tracker_tab(host)
        self.tab.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})

    def state(self):
        return self.tab.iso("globalThis.__HERMES_WEBCAM__.status()", self.host._context)

    def wait(self, phase, seconds=30):
        until(lambda: self.state()["phase"] == phase, seconds)

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

    def key(self, kind, name="Space"):
        key, code = (" ", 32) if name == "Space" else ("Escape", 27)
        self.tab.send("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": name, "windowsVirtualKeyCode": code})

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
            until(lambda: index * SPOT + .15 <= self.clock() < index * SPOT + .75, PERIOD + 8)
            self.tap()
            if shots and index == 4:
                for name, wait in (("04a-ring-closing", .1), ("04b-ring-closing", .3), ("04c-ring-closing", .3)):
                    self.shot(name, wait)
            until(lambda: self.state()["index"] != index or self.state()["phase"] != "calibrate", 6)

    def fit(self, report, shots=False):
        """Fake footage is not a person: a real fit can legitimately fail. Say so, then retry."""
        for _ in range(4):
            self.nine(shots=shots)
            until(lambda: self.state()["phase"] in ("checkIntro", "result"), 30)
            if self.state()["phase"] == "checkIntro":
                return
            report["fit_retries"] = report.get("fit_retries", 0) + 1
        raise AssertionError("Fit failed four times on fake footage")

    def start_check(self):
        until(lambda: .1 <= self.clock() < 1.2, PERIOD + 8)  # All sixteen seconds fall inside the face footage.
        self.tap(); self.wait("check", 4)

    def finish_check(self):
        until(lambda: .1 <= self.clock() < 1.2, PERIOD + 8)
        for index in range(10):
            until(lambda: self.state()["phase"] == "checkIntro" and self.state()["checkIndex"] == index, 5)
            # Each target waits: it must not advance until the user is ready.
            time.sleep(.15)
            assert self.state()["phase"] == "checkIntro" and self.state()["checkIndex"] == index
            self.tap()
        self.wait("result", 5)

    def close(self):
        self.tab.ws.close(); self.host.stop()


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
    needle = "stream = await navigator.mediaDevices.getUserMedia("
    assert needle in source
    broken = tmp / "broken_camera.js"
    broken.write_text(source.replace(needle, "throw new DOMException('Could not start video source', 'NotReadableError');\n    stream = await navigator.mediaDevices.getUserMedia("))
    used = []
    host = WebcamHost(lambda *_: False, profile_path=tmp / "none.json", runtime_source=broken, chrome_args=HEADLESS,
                      fake_video=video, on_use_cursor=lambda: used.append(True))
    window = Window(host, out)
    try:
        window.wait("error")
        words = window.text()
        assert "Camera in use" in words and "Try again" in words and "Use cursor" in words, words
        assert host.status()["state"] == "failed" and "Could not start" in host.status()["error"]
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
        assert "Start a new calibration" in window.text() and "Test saved calibration" not in window.text()
        assert not window.host.status()["calibrated"] and path.read_bytes() == before
        window.shot("11-old-calibration")
        report["old_profile"] = {"refused_with_plain_message": True, "file_unchanged": True}
    finally:
        window.close()


def main_flow(tmp, video, out, report, scheme="light"):
    path = tmp / f"personal-{scheme}" / "calibration.json"
    used = []
    host = WebcamHost(lambda *_: False, estimator=Scripted(), profile_path=path, fake_video=video, chrome_args=HEADLESS,
                      on_use_cursor=lambda: used.append(True))
    window = Window(host, out, scheme)
    def at(x, y):
        def predict(_features, t):
            s = host.profile["screen"]
            return ScreenPoint(s["left"] + x * s["width"], s["top"] + y * s["height"], t)
        return predict
    try:
        window.wait("home"); until(lambda: window.state()["face"], PERIOD + 8)
        assert window.tab.main("typeof __HERMES_WEBCAM__") == "undefined"
        assert window.tab.main("typeof __hermesGazeIntent") == "undefined"
        words = window.text()
        assert "stays in this window" in words and "Eye tracking beta" in words and "Start calibration" in words
        for gone in ("large", "glasses", "Hermes can see"):
            assert gone not in words, words
        window.shot("02-setup")

        # A cancelled attempt leaves nothing behind.
        window.fit(report, shots=True)
        assert not path.exists() and not host.status()["calibrated"]
        window.shot("05-check-waiting")
        window.tap("Escape"); window.wait("home")
        assert not path.exists() and not host.status()["calibrated"] and host._check is None
        report["cancel_after_fit"] = {"nothing_saved": True}

        # A real fit and real frames; the check sees scripted estimates near each target.
        window.fit(report)
        Scripted.script = jittered(host)
        window.shot("06-check-running")
        hidden = window.tab.main("getComputedStyle(document.querySelector('#region')).opacity")
        assert hidden == "0"
        assert not path.exists()
        window.finish_check()
        Scripted.script = None
        words = window.text()
        assert "Try eye tracking" in words and "Finish setup" in words and "%" not in words and not any(c.isdigit() for c in words), words
        assert window.tab.main("document.querySelectorAll('#map, #marks').length") == 0
        assert path.exists() and oct(path.stat().st_mode & 0o777) == "0o600" and host.status()["calibrated"]
        assert host._check is None and "map" not in json.dumps(host.status())
        window.shot("07-success", 1.6)
        report["passing_check"] = {"saved_only_after_result": True, "region_hidden_during_check": True}
        saved = path.read_bytes()

        # Practice: only ever inside this window.
        Scripted.script = at(.3, .35)
        until(lambda: .1 <= window.clock() < 12, PERIOD + 8)
        window.click("practise"); window.wait("practice")
        until(lambda: window.tab.main("document.querySelector('#region').style.opacity") == "1")
        until(lambda: "Practice: look between the cards" in window.text(), 5)
        assert host.delivered == 0
        window.shot("08-practice")
        Scripted.script = lambda *_: None
        until(lambda: "Off screen" in window.text(), 5)
        assert window.tab.main("document.querySelector('#region').style.opacity") == "0"
        window.shot("09a-practice-offscreen")
        Scripted.script = at(.7, .6)
        until(lambda: FACE_SECONDS + .4 <= window.clock(), PERIOD + 8)
        until(lambda: "Couldn’t see your eyes" in window.text(), 5)
        assert window.tab.main("document.querySelector('#region').style.opacity") == "0"
        window.shot("09b-practice-face-lost")
        report["practice"] = {"lost_face_removes_region_says_why": True, "offscreen_says_why": True, "pages_delivered": host.delivered}
        Scripted.script = None

        # The rehearsal says it is one.
        window.click("done"); window.wait("handoff")
        assert "Hold" in window.text() and "in Chrome to ask" in window.text()
        window.shot("10a-lesson")
        window.key("keyDown"); until(lambda: "rehearsal" in window.tab.main("document.querySelector('#rehearse').textContent"), 3)
        assert "Listening" in window.text()
        window.shot("10b-rehearsal-held", .35)
        window.key("keyUp"); until(lambda: "this asks" in window.text(), 3)
        window.shot("10c-rehearsal-done", .25)
        report["rehearsal"] = {"says_rehearsal": True}
        window.click("home"); window.wait("home")
        assert "Test saved calibration" in window.text() and "stays in this window" in window.text()
        window.shot("12-welcome-back")

        # A weak attempt explains the failure and keeps the accepted calibration.
        window.fit(report)
        Scripted.script = jittered(host, misses={1, 2, 5, 7})
        window.finish_check()
        Scripted.script = None
        words = window.text()
        assert "Calibration" in words and "Your saved calibration has not changed" in words, words
        assert "Try calibration again" in words and "Use cursor" in words and "ready" not in words.lower()
        assert path.read_bytes() == saved
        window.shot("13-weak", 1.6)
        report["failed_check"] = {"previous_kept": True}

        # A fit that fails outright says what to change and keeps the earlier setup.
        Scripted.fail_next_fit = True
        window.nine(); window.wait("result", 30)
        words = window.text()
        assert "Calibration" in words and "Your saved calibration has not changed" in words, words
        assert path.read_bytes() == saved
        window.shot("13b-fit-failed")

        # A moved or resized window is an error state, not a silent return.
        window.click("calibrate"); window.wait("calibrate")
        window.tab.send("Emulation.setDeviceMetricsOverride", {"width": 1300, "height": 800, "deviceScaleFactor": 1, "mobile": False})
        window.wait("home"); until(lambda: "Window moved" in window.text(), 3)
        window.tab.send("Emulation.clearDeviceMetricsOverride", {})
        window.shot("12b-window-moved", .8)
        assert path.read_bytes() == saved
        report["window_moved"] = {"shown_as_error": True, "saved_file_unchanged": True}

        # Daily start: a new process with the accepted file.
        window.close()
        window = Window(WebcamHost(lambda *_: False, estimator=Scripted(), profile_path=path, fake_video=video, chrome_args=HEADLESS,
                                   on_use_cursor=lambda: used.append(True)), out, scheme)
        host = window.host
        window.wait("home")
        assert host.status()["calibrated"] and "Test saved calibration" in window.text()
        window.click("check"); window.wait("checkIntro")
        window.shot("14-saved-check-waiting", .9)
        Scripted.script = lambda *_: None
        window.finish_check()
        Scripted.script = None
        words = window.text()
        assert "Saved calibration did not pass" in words and "Try calibration again" in words, words
        assert path.read_bytes() == saved
        window.shot("15-couldnt-check", 1.6)
        for name, value in (("reduced-solid", [{"name": "prefers-color-scheme", "value": scheme}, {"name": "prefers-reduced-transparency", "value": "reduce"}, {"name": "prefers-reduced-motion", "value": "reduce"}]),):
            window.tab.send("Emulation.setEmulatedMedia", {"features": value})
            window.click("calibrate"); window.wait("calibrate")
            window.shot(f"16-dot-{name}", .4)
            window.tap("Escape"); window.wait("home")
            window.shot(f"16-home-{name}")
        report["daily_start"] = {"saved_file_untouched_by_check": True}
        window.click("cursor"); until(lambda: used)
        report["tracker_final"] = {k: v for k, v in host.status().items() if k in ("state", "calibrated", "delivered")}
    finally:
        Scripted.script = None
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
            main_flow(tmp, video, out, report, scheme)
    (out / "calibration-results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--schemes", nargs="+", choices=("light", "dark"), default=("light", "dark"))
    args = parser.parse_args()
    run(args.out.resolve(), tuple(args.schemes))
