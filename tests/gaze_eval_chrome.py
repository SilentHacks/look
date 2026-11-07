"""Record a fake camera through the actual private recorder. Never opens real devices."""
import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tests
from hermes_gaze.benchmark.gaze_eval import private_directory, save_json
from hermes_gaze.benchmark.gaze_record import RecordingHost
from tests.webcam_chrome import fixture, tracker_tab, until


def run(out, duration=144):
    out = private_directory(out)
    recording = out / "recording"
    host = None
    camera = None
    with tempfile.TemporaryDirectory(prefix="hermes-eval-fake-camera-") as directory:
        video = fixture(Path(directory))
        host = RecordingHost(recording, person="nasa-fake", duration=duration, fake_video=video)
        try:
            assert host.start()["state"] == "running", host.status()
            camera = tracker_tab(host)
            assert camera.main("document.querySelector('video').srcObject.getAudioTracks().length") == 0
            bounds = camera.main("(()=>{const r=document.querySelector('button').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
            for kind in ("mousePressed", "mouseReleased"):
                camera.send("Input.dispatchMouseEvent", {"type": kind, "button": "left", "clickCount": 1, **bounds})
            until(lambda: host.last_frame > 1.)
            screenshot = camera.send("Page.captureScreenshot", {"format": "png"})["data"]
            (out / "recording.png").write_bytes(base64.b64decode(screenshot))
            assert host.done.wait(duration + 20), host.status()
            meta = json.loads((recording / "recording.json").read_text())
            assert meta["finished"] and meta["fake_camera"] and not meta["audio"], meta
            assert meta["actual_seconds"] >= duration - 1, meta
            phases = {json.loads(line)["phase"] for line in (recording / "targets.jsonl").read_text().splitlines()}
            assert phases == {"calibration", "fixed", "moving", "reading"}, phases
            assert recording.stat().st_mode & 0o777 == 0o700
            assert all(path.stat().st_mode & 0o777 == 0o600 for path in recording.iterdir())
            result = dict(fake_camera=True, microphone=False, video_bytes=meta["video_bytes"],
                          actual_seconds=meta["actual_seconds"], phases=sorted(phases), permissions="0700/0600",
                          accuracy="Not measured: translated public-domain NASA portrait, not human gaze.")
            save_json(out / "recorder-results.json", result)
            print(json.dumps(result, indent=2))
        finally:
            if camera:
                camera.ws.close()
            if host:
                host.stop()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--duration", type=int, default=144)
    args = p.parse_args()
    run(args.out, args.duration)
