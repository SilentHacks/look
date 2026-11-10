"""Fake devices only. Exercises calibration, background flow, mapping and held Space.

Run: .venv/bin/python tests/webcam_chrome.py --out /absolute/output-directory
Downloads a public-domain NASA portrait and checksum-verified MediaPipe assets.
The moving portrait checks plumbing, NOT human eye-tracking accuracy.
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
import time
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
import tests
from hermes_gaze.runtime import service
from hermes_gaze.audio import voice
from hermes_gaze.browser.webcam import WebcamHost
from benchmark.probe_companion_ui import Tab

PORTRAIT = "https://www.nasa.gov/wp-content/uploads/2023/03/464436main_S69-31741_full.jpg"
PORTRAIT_HASH = "1cb000ea1005dc2b63bc0593e86a371b95105a9e1c989876b7dbd1874837714c"


def until(fn, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = fn()
        if result:
            return result
        time.sleep(.06)
    raise AssertionError("Private webcam probe timed out")


def fixture(directory):
    portrait, video = directory / "nasa.jpg", directory / "face.y4m"
    data = urllib.request.urlopen(PORTRAIT, timeout=45).read()
    assert hashlib.sha256(data).hexdigest() == PORTRAIT_HASH
    portrait.write_bytes(data)
    # Public-domain portrait translated to nine known camera-frame positions.
    # This supplies changing real landmark observations, not synthetic gaze samples.
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
        "color=c=black:s=640x480:r=15:d=36", "-loop", "1", "-i", str(portrait), "-filter_complex",
        "[1:v]crop=650:650:150:80,scale=300:300[face];[0:v][face]overlay=x='30+140*mod(floor(t/4),3)':y='90*floor(mod(t,36)/12)':shortest=1",
        "-t", "36", "-r", "15", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=45)
    return video


def tracker_tab(host):
    pages = json.load(urllib.request.urlopen(host.http_url + "/json/list", timeout=3))
    return Tab(next(t["webSocketDebuggerUrl"] for t in pages if t["id"] == host.target_id))


def click_action(camera, action):
    bounds = until(lambda: camera.main(f"(()=>{{const b=[...document.querySelectorAll('[data-action={action}]')].find(n=>n.getClientRects().length);"
                                       "if(!b||b.disabled)return null;const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()"), 30)
    for kind in ("mousePressed", "mouseReleased"):
        camera.send("Input.dispatchMouseEvent", {"type": kind, "button": "left", "clickCount": 1, **bounds})


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    os.environ["SHOTS"] = str(out)
    from tests.ui_review.devlib import Rig
    report = {"accuracy": "Not measured; a translated NASA portrait tests plumbing only."}
    with tempfile.TemporaryDirectory(prefix="hermes-webcam-probe-") as tmp:
        tmp = Path(tmp)
        video = fixture(tmp)
        rig = Rig(headless=False)
        host = WebcamHost(rig.session._accept_webcam_point, profile_path=tmp / "personal" / "calibration.json", fake_video=video)
        rig.session.webcam = host
        camera = None
        try:
            # Keep the companion page open through the real mode-switch/calibration sequence.
            tab = rig.new_tab()
            rig.cmd("Emulation.clearDeviceMetricsOverride", {}, tab)
            rig.cmd("Emulation.setFocusEmulationEnabled", {"enabled": False}, tab)
            rig.page("document.body.style.cssText='margin:0;height:200vh';document.body.innerHTML='<article id=planet style=\"padding:32px;height:85vh;background:#eef\"><h1>Jupiter storms</h1><p>The Great Red Spot is a persistent storm on Jupiter.</p></article>'")
            rig.session.configure(mode="webcam")
            status = rig.session.start_webcam()
            until(lambda: host.state in ("running", "failed"), 25)
            status = host.status()
            assert status["state"] == "running", status
            assert not status["calibrated"], status
            camera = tracker_tab(host)
            camera.send("Page.bringToFront", {})
            until(lambda: camera.main("document.hasFocus() && !document.hidden"))
            until(lambda: not rig.page("document.hasFocus()"))
            ctx = host._context
            def camera_state():
                return camera.iso("globalThis.__HERMES_WEBCAM__.status()", ctx)
            click_action(camera, "calibrate")
            until(lambda: camera_state()["index"] == 0)
            shot = camera.send("Page.captureScreenshot", {"format": "png"})["data"]
            (out / "nine-point-calibration.png").write_bytes(base64.b64decode(shot))
            for index in range(9):
                until(lambda: index * 4 + .6 <= camera_state()["videoTime"] % 36 < index * 4 + 1.5, 45)
                for kind in ("keyDown", "keyUp"):
                    camera.send("Input.dispatchKeyEvent", {"type": kind, "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})
                until(lambda: camera_state()["index"] != index)
            # This portrait cannot follow the dot, so its held-out result is set; the fit is real.
            until(lambda: camera_state()["phase"] == "boundary")
            click_action(camera, "start-check")
            until(lambda: camera_state()["phase"] == "checkIntro")
            assert not host.profile_path.exists()
            with patch("hermes_gaze.browser.webcam.summarize_check", return_value="good"):
                for trial in range(10):
                    until(lambda: camera_state()["phase"] == "checkIntro" and camera_state()["checkIndex"] == trial)
                    for kind in ("keyDown", "keyUp"):
                        camera.send("Input.dispatchKeyEvent", {"type": kind, "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})
                until(lambda: host.profile is not None, 30)
            assert host.profile_path.stat().st_mode & 0o777 == 0o600
            report["calibration"] = {"points": 9, "stored_mode": "0600", "model": host.profile["model_id"]}
            runtime = camera_state()
            report["camera_runtime"] = {key: runtime[key] for key in ("frames", "frame_ms", "feature_ms", "sample_hz")}
            assert runtime["frames"] > 1 and runtime["sample_hz"] > 0
            # Main-world code cannot see the isolated runtime or call its binding.
            assert camera.main("typeof __HERMES_WEBCAM__") == "undefined"
            assert camera.main("typeof __hermesGazeIntent") == "undefined"
            report["isolated_camera_context"] = True

            # Return directly from the first completed calibration: no restart, new tab,
            # focus emulation or synthetic viewport geometry to hide a handoff defect.
            click_action(camera, "done")
            until(lambda: camera_state()["phase"] == "tracking", 10)
            until(lambda: rig.page("document.hasFocus() && !document.hidden"))
            assert rig.iso("window.__HERMES_GAZE_OVERLAY__.state.mode") == "webcam"
            # Returning focus can itself produce a trusted mousemove; do not assume
            # the anchor is still missing just because the probe hasn't moved yet.
            report["native_focus_handoff"] = {"existing_tab": True, "focus_emulation": False}
            rig.move(400, 300)
            # A measured page with no deliveries must not give irrelevant pointer advice.
            with patch.object(host, "on_point", return_value="outside_page"):
                time.sleep(1.1)
                rig.space_down()
                until(lambda: "No fresh gaze. Check /gaze tracker." in rig.text("pill"))
                rig.space_up()
                assert "pointer" not in rig.text("pill").lower()
                assert rig.session.microphone._stream is None
                report["anchored_no_gaze_message"] = True
            # Calibrated camera position 4 corresponds to display centre, inside this viewport.
            until(lambda: 16.4 < camera_state()["videoTime"] % 36 < 18., 45)
            # The timed camera wait can outlast an external app's focus change.
            # Re-front only our owned page; retain native focus and ownership checks.
            rig.cmd("Page.bringToFront", {}, tab)
            until(lambda: rig.page("document.hasFocus() && !document.hidden"))
            # History can contain pre-focus samples; wait for usable frozen evidence.
            data = until(lambda: data if (data := rig.session.cdp.capture(
                "window.__HERMES_GAZE_OVERLAY__.captureNoisyContext()")).get("fixations") else None)
            assert data["fixations"] and all(s["source"] == "webcam" for s in data["fixations"])
            age = time.time() - data["fixations"][-1]["t"]
            assert 0 <= age < 1, age
            report["ingest"] = {"source": rig.session.ring_buffer.latest().source,
                                "timestamp_age_seconds": round(age, 3), "delivered": host.delivered}
            assert report["ingest"]["source"] == "webcam" and host.delivered > 0
            # Move the pointer far from gaze: it must not replace the camera evidence.
            rig.move(20, 20)
            seen = []
            resolve = service.resolve_candidates
            def scoring(*args, **kwargs):
                result = resolve(*args, **kwargs)
                seen.append({"source": [s.source for s in args[1]], "top": result.top.candidate.label})
                return result
            rig.host.answers = [{"text": "## Jupiter\n\nThe Great Red Spot is a persistent storm.", "think": .1}]
            def transcript(_audio, **kwargs):
                now = time.time()
                return "Explain this region", [{"word": "this", "start": now - .4, "end": now - .2}]
            with patch.object(service, "resolve_candidates", side_effect=scoring), \
                 patch.object(service, "_LLM", None), patch.object(voice, "transcribe_audio_buffer", side_effect=transcript):
                rig.space_down()
                until(lambda: rig.dbg()["talk"]["micReady"])
                rig.shot("webcam-held-region")
                time.sleep(.4)
                rig.space_up()
                until(lambda: bool(rig.host.wires))
                until(lambda: rig.turns.active is None and not rig.turns.pending)
            assert seen and all(s == "webcam" for result in seen for s in result["source"]), seen
            saved = rig.turns.runs[0]["snapshot"]
            assert saved["mode"] == "webcam" and "Jupiter" in saved["context"], saved
            assert "Great Red Spot" in rig.turns.runs[0]["text"]
            report["held_space"] = {"fusion_calls": len(seen), "camera_sources_only": True,
                                    "scripted_answer": "Great Red Spot", "context_has_jupiter": True}
            # Explicitly reset just the page's mode to exercise an unmeasured page,
            # independently of OS-generated pointer events during native focus.
            rig.iso("window.__HERMES_GAZE_OVERLAY__.Configure({mode:'hover'});"
                    "window.__HERMES_GAZE_OVERLAY__.Configure({mode:'webcam'})")
            until(lambda: host.drops["no_page_anchor"] > 0)
            rig.space_down()
            until(lambda: "Move the pointer once" in rig.text("pill"))
            rig.space_up()
            assert rig.session.microphone._stream is None
            report["missing_anchor_blocks_capture"] = True
            rig.shot("webcam-needs-page-anchor")
            rig.move(400, 300)
            # Changed geometry has a different diagnostic and recovers by remeasuring.
            width, height, dpr = rig.page("[innerWidth,innerHeight,devicePixelRatio]")
            rig.cmd("Emulation.setDeviceMetricsOverride",
                    {"width": width - 80, "height": height, "deviceScaleFactor": dpr, "mobile": False})
            until(lambda: host.drops["viewport_changed"] > 0)
            time.sleep(.9)
            rig.space_down()
            until(lambda: "Page size changed" in rig.text("pill"))
            rig.space_up()
            rig.cmd("Emulation.clearDeviceMetricsOverride")
            rig.move(400, 300)
            report["changed_viewport_guidance"] = True
            camera.send("Page.bringToFront", {})
            # Stop midway through a second calibration, then reuse the saved profile.
            until(lambda: camera.main("!document.body.classList.contains('calibrating')"))
            saved_profile = host.profile_path.read_bytes()
            # Recalibration is available in the retained camera window.
            click_action(camera, "calibrate")
            until(lambda: camera_state()["index"] == 0)
            for kind in ("keyDown", "keyUp"):
                camera.send("Input.dispatchKeyEvent", {"type": kind, "key": " ", "code": "Space", "windowsVirtualKeyCode": 32})
            until(lambda: bool(host._point_samples))
            rig.session.configure(mode="hover")
            camera.ws.close()
            rig.session.configure(mode="webcam")
            before_predictions = host.predictions
            assert host.start(wait=25)["state"] == "running"
            camera = tracker_tab(host); ctx = host._context
            until(lambda: host.predictions > before_predictions)
            assert host.profile_path.read_bytes() == saved_profile
            report["interrupted_calibration_restart"] = True
            # A genuine background tab in the owned tracker process.
            until(lambda: camera.main("!document.fullscreenElement"))
            request = urllib.request.Request(host.http_url + "/json/new?about:blank", method="PUT")
            urllib.request.urlopen(request, timeout=3).read()
            until(lambda: camera_state()["hidden"])
            before = host.samples
            time.sleep(2)
            report["hidden_flow"] = {"samples_in_two_seconds": host.samples - before, "hidden_total": host.hidden_samples}
            assert report["hidden_flow"]["samples_in_two_seconds"] >= 10
            assert host.hidden_samples >= 10, (host.status(), camera_state())
            # Focus a different tab. Camera samples must reach that document, not A's history.
            other = rig.new_tab()
            rig.cmd("Emulation.clearDeviceMetricsOverride", {}, other)
            rig.page("document.body.innerHTML='<h1>Moon landing</h1>';document.body.style.height='100vh'")
            # Restore native focus after the rig helper's default emulation.
            rig.cmd("Emulation.setFocusEmulationEnabled", {"enabled": False}, other)
            rig.move(300, 250)
            until(lambda: rig.iso("window.__HERMES_GAZE_OVERLAY__.state.ringBuffer.some(s=>s.source==='webcam')"), 45)
            saved = len(tab.eval_js("window.__HERMES_GAZE_OVERLAY__.state.ringBuffer"))
            time.sleep(.5)
            assert len(tab.eval_js("window.__HERMES_GAZE_OVERLAY__.state.ringBuffer")) == saved
            report["focused_tab_ownership"] = True
            rig.session.configure(mode="hover")
            assert host.state == "stopped" and host._process.poll() is not None
            unseeded = service.resolve_now(rig.session, utterance="Explain this", activate=False)
            assert not unseeded["ok"], "Gaze must not become manual cursor/action evidence on mode switch"
            rig.aim("h1")
            cursor = service.resolve_now(rig.session, utterance="Explain this", activate=False)
            assert cursor["ok"] and cursor["mode"] == "hover" and "Moon" in cursor["context"], cursor
            report["cursor_after_switch"] = True
            report["tracker_final"] = host.status()
        except BaseException:
            print("Failed webcam probe:", json.dumps(host.status()), flush=True)
            if rig.tab:
                print("Companion state:", rig.iso("({focused:document.hasFocus(), hidden:document.hidden,"
                      "mode:window.__HERMES_GAZE_OVERLAY__.state.mode,"
                      "geometry:window.__HERMES_GAZE_OVERLAY__.webcamViewport(devicePixelRatio).drop_reason || 'measured'})"),
                      flush=True)
            raise
        finally:
            if camera:
                camera.ws.close()
            host.stop()
            rig.close()
    (out / "webcam-results.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args().out.resolve())
