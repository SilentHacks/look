"""Private headless Chrome; preparation/failure controls, never a capture device."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HERMES_DISABLE_LAZY_INSTALLS"] = "1"
import tests
from hermes_gaze.browser.webcam import WebcamHost


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    os.environ["SHOTS"] = str(out)
    from tests.ui_review.devlib import Rig, until
    rig = Rig(headless=True, scale=1)
    release = threading.Event()
    checks = []
    try:
        rig.new_tab()
        rig.move(400, 300)
        with tempfile.TemporaryDirectory() as tmp:
            host = WebcamHost(lambda *_: False, assets=Path(tmp), profile_path=Path(tmp) / "saved.json")
            rig.session.webcam = host
            rig.session.configure(mode="webcam")
            entered = threading.Event()
            def slow(*_, **__):
                entered.set(); release.wait(15)
                return Path(tmp)
            with patch("hermes_gaze.browser.webcam.prepare_assets", side_effect=slow), patch.object(host, "_run") as launch:
                rig.session.start_webcam(download=True)
                assert entered.wait(2)
                until(lambda: "Preparing eye tracking" in rig.text())
                assert "Use cursor" in rig.text()
                assert "Preparing eye tracking" not in rig.page("document.body.innerText")
                time.sleep(.7)  # Let the protected card's arrival/layout settle for the screenshot.
                rig.shot("startup-preparing")
                rig.click_panel('[data-act="use_cursor"]')
                until(lambda: rig.session.tracker.mode == "hover")
                assert host._stop.is_set() and not rig.session.ring_buffer.latest()
                release.set(); host._thread.join(3)
                assert not host._thread.is_alive() and host.state == "stopped"
                launch.assert_not_called()
                checks.append("protected Use cursor cancels blocked preparation; no late camera launch or fabricated evidence")
            rig.session.configure(mode="webcam")
            rig.session.start_webcam()
            until(lambda: host.state == "failed")
            until(lambda: "/look setup eyes" in rig.text())
            assert "Use cursor" in rig.text()
            rig.shot("startup-files-missing")
            checks.append("cache-only startup fails with explicit setup and cursor recovery")
            host._thread.join(3)
            with patch("hermes_gaze.browser.webcam.prepare_assets", return_value=Path(tmp)), \
                 patch.object(host, "_run", side_effect=OSError("PRIVATE_NATIVE_DIAGNOSTIC")):
                rig.session.start_webcam()
                until(lambda: host.state == "failed")
                host._thread.join(3)
                until(lambda: "Camera unavailable" in rig.text())
                assert "Try again" in rig.text() and "Use cursor" in rig.text()
                assert "PRIVATE" not in rig.text()
                rig.shot("startup-failure")
                checks.append("pre-camera failure updates open protected controls with concise retry and cursor; diagnostics private")
                rig.click_panel('[data-act="use_cursor"]')
                until(lambda: rig.session.tracker.mode == "hover")
            report = {"checks": checks, "passed": len(checks), "devices": "No camera or microphone opened"}
            (out / "startup-results.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
    finally:
        release.set()
        rig.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args().out.resolve())
