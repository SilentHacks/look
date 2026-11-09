"""Guided dataset proof. Fake camera only; recordings and decoded frames are temporary."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tests
from hermes_gaze.benchmark.gaze_eval import extract_manifest, private_directory, save_json, evaluate, PROTOCOLS, summaries
from hermes_gaze.benchmark.gaze_dataset import export_person, import_person, inventory, load_dataset
from hermes_gaze.benchmark.gaze_record import RecordingHost, CONDITIONS, completed_blocks
from hermes_gaze.benchmark.gaze_tuning import Regression
from tests.webcam_chrome import fixture, tracker_tab, until


def click(tab, selector):
    tab.main("document.querySelector(" + json.dumps(selector) + ").scrollIntoView({block:'center'})")
    bounds = tab.main("(()=>{const r=document.querySelector(" + json.dumps(selector) + ").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
    for kind in ("mousePressed", "mouseReleased"):
        tab.send("Input.dispatchMouseEvent", {"type": kind, "button": "left", "clickCount": 1, **bounds})


def run(out, duration=36):
    out = private_directory(out)
    report = dict(fake_camera=True, microphone=False, accuracy="Not measured: translated portrait, not human gaze")
    with tempfile.TemporaryDirectory(prefix="hermes-dataset-proof-") as tmp:
        tmp = Path(tmp)
        video = fixture(tmp)
        recordings = private_directory(tmp / "recordings")
        def record(glasses, blocks, consent=False, stop_at_break=False):
            person_dir = private_directory(recordings / "p-demo")
            host = RecordingHost(person_dir, person="p-demo", glasses=glasses, device="fake-laptop",
                                 blocks=blocks, duration=duration, fake_video=video, dataset_root=recordings)
            tab = None
            try:
                assert host.start(wait=25)["state"] == "running", host.status()
                tab = tracker_tab(host)
                if consent:
                    assert tab.main("Boolean(document.querySelector('#consent'))")
                    assert tab.main("!document.querySelector('video')")  # No camera before consent.
                    assert not inventory(recordings)
                    (out / "consent.png").write_bytes(base64.b64decode(tab.send("Page.captureScreenshot", {"format": "png"})["data"]))
                    click(tab, "#consent")
                    until(lambda: host.consented)
                else:
                    assert not tab.main("Boolean(document.querySelector('#consent'))")
                click(tab, "#camera")
                until(lambda: tab.main("Boolean(document.querySelector('#start'))"))
                assert tab.main("document.querySelector('video').srcObject.getAudioTracks().length") == 0
                for index, block in enumerate(blocks):
                    assert block in tab.main("document.querySelector('h1').textContent")
                    click(tab, "#start")
                    try:
                        until(lambda: host.video_file is not None)
                    except AssertionError:
                        raise AssertionError((host.status(), tab.main("document.body.innerText"),
                                              tab.iso("globalThis.__HERMES_WEBCAM__.status()", host._context)))
                    try:
                        until(lambda: host.last_frame > 1)
                    except AssertionError:
                        raise AssertionError((host.status(), host.metadata,
                                              tab.iso("globalThis.__HERMES_WEBCAM__.status()", host._context),
                                              tab.main("document.body.innerText")))
                    if index == 0:
                        (out / ("targets-" + glasses + ".png")).write_bytes(base64.b64decode(tab.send("Page.captureScreenshot", {"format": "png"})["data"]))
                    until(lambda: len(host.saved) == index + 1, duration + 15)
                    if stop_at_break:
                        until(lambda: tab.main("Boolean(document.querySelector('#exit'))"))
                        (out / "break.png").write_bytes(base64.b64decode(tab.send("Page.captureScreenshot", {"format": "png"})["data"]))
                        click(tab, "#exit")
                        assert host.done.wait(5)
                        return
                    if index + 1 < len(blocks):
                        until(lambda: tab.main("document.querySelector('h1').textContent.includes(" + json.dumps(blocks[index + 1]) + ")"))
                assert host.done.wait(5)
            finally:
                if tab:
                    tab.ws.close()
                host.stop()
        blocks = list(CONDITIONS)
        # First run stops at the break; a new owned process resumes under the same pseudonym.
        record("glasses", blocks, consent=True, stop_at_break=True)
        complete = completed_blocks(recordings, "p-demo", "glasses", "fake-laptop")
        assert complete == {"upright"}, complete
        record("glasses", [b for b in blocks if b not in complete])
        record("none", blocks)
        sessions = inventory(recordings)
        assert len(sessions) == 12, len(sessions)
        for directory, meta in sessions:
            assert meta["finished"] and meta["complete"] and meta["fake_camera"] and not meta["audio"], meta
            phases = {json.loads(line)["phase"] for line in (directory / "targets.jsonl").read_text().splitlines()}
            expected = {"fixed", "moving", "reading", "validation-start", "validation-end"}
            if meta["condition"] != "no-recalibration":
                expected.add("calibration")
            else:
                assert meta["calibration_source"]
            assert phases == expected, (meta["condition"], phases)
            assert directory.stat().st_mode & 0o777 == 0o700
            assert all(path.stat().st_mode & 0o777 == 0o600 for path in directory.iterdir())
        # The actual CLI resumes without opening another window when all requested work is complete.
        resumed = subprocess.run([sys.executable, "scripts/gaze.py", "record", "--out", str(recordings),
                                  "--person", "p-demo", "--glasses", "none", "--device", "fake-laptop", "--fake-video", str(video)],
                                 cwd=ROOT, capture_output=True, text=True, check=True)
        assert "All selected blocks are complete" in resumed.stdout, resumed.stdout
        bundle = export_person(recordings, "p-demo", tmp / "person.zip")
        imported = private_directory(tmp / "imported")
        assert import_person(bundle, imported) == "p-demo"
        assert import_person(bundle, imported) == "p-demo"
        for (a, _), (b, _) in zip(sessions, inventory(imported)):
            assert all((a / name).read_bytes() == (b / name).read_bytes() for name in ("recording.json", "targets.jsonl", "camera.webm"))
        data = load_dataset(imported, tmp / "frames", stride=1)
        # Retain all calibration frames for sample guards; a few test/validation frames suffice for a smoke.
        for session in data["sessions"]:
            session["frames"] = [f for i, f in enumerate(session["frames"]) if f["phase"] == "calibration" or i % 8 == 0]
        data = extract_manifest(data)
        rows = []
        for protocol in PROTOCOLS:
            scored, _ = evaluate(data, Regression, "fake-personal-ridge", 25, protocol)
            rows.extend(scored)
        successful = [r for r in rows if r["status"] == "ok"]
        assert {(r["condition"], r["glasses"]) for r in successful if r["protocol"] == "same-session"} == {(b, g) for b in blocks for g in ("none", "glasses")}, rows
        assert any(r["status"] == "ok" for r in rows if r["protocol"] == "cross-condition"), rows
        assert any(r["status"] == "ok" for r in rows if r["protocol"] == "cross-glasses"), rows
        assert all("validation-end" in r["validation"] for r in successful)
        report.update(sessions=len(sessions), blocks=blocks, glasses=["glasses", "none"], consent_before_camera=True,
                      break_and_resume=True, cli_resume_without_camera=True, export_import_byte_identical=True,
                      phases="calibration / fixed / moving / reading / validation-start / validation-end",
                      rows=len(rows), successful_rows=len(successful), unscorable_rows=len(rows) - len(successful),
                      by_protocol={p: sum(r["status"] == "ok" for r in rows if r["protocol"] == p) for p in PROTOCOLS},
                      permissions="0700/0600", temporary_recordings_removed=True)
        save_json(out / "smoke-scores.json", rows)
        save_json(out / "summary.json", summaries(rows))
    save_json(out / "recorder-results.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--duration", type=int, default=36)
    args = p.parse_args()
    run(args.out, args.duration)
