"""Recorder schedules and compatibility without Chrome, devices or saved data."""
import base64
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from hermes_gaze.benchmark import gaze_record
from hermes_gaze.benchmark.gaze_dataset import load_dataset
from hermes_gaze.benchmark.gaze_eval import evaluate, EvalRidge, screen
from tests.test_webcam import observations


class RecordingTests(unittest.TestCase):
    def test_schedule_and_reading_hold_in_node(self):
        runtime = Path(__file__).resolve().parents[1] / "browser" / "gaze_record.js"
        result = subprocess.run(["node", "-e", r'''
const assert = require("node:assert/strict");
const {protocol, scheduleLength, target} = require(process.argv[1]);
const totals = {};
for (const block of ["upright", "distance", "head", "light", "lid", "no-recalibration"]) {
  const steps = protocol(block, 123), total = scheduleLength(steps);
  totals[block] = total;
  assert.ok(Math.abs(total - (block === "no-recalibration" ? 72.6 : 102.6)) < 1e-9);
  for (const [phase, count] of [["calibration", block === "no-recalibration" ? 0 : 25],
      ["validation-start", 9], ["fixed", 16], ["validation-end", 9]]) {
    const fixed = steps.filter(s => s.phase === phase);
    assert.equal(fixed.length, count);
    assert.ok(fixed.every(s => s.span === 1.2));
  }
  assert.deepEqual(steps.filter(s => s.phase === "validation-start").map(s => s.xy),
    steps.filter(s => s.phase === "validation-end").map(s => s.xy));
  let start = 0;
  for (const step of steps) {
    if (step.phase === "reading") break;
    start += step.span;
  }
  for (const duration of [total, 150, 36]) {
    const at = t => target(steps, t * duration / total, duration);
    for (let line = 0; line < 4; line++) {
      const t = start + line * 4.2;
      for (const offset of [.001, .4, .799]) {
        const hold = at(t + offset);
        assert.equal(hold.phase, "reading");
        assert.equal(hold.settling, true);
        assert.deepEqual(hold.xy, [.08, .12 + line * .25]);
      }
      const moving = at(t + .801), end = at(t + 4.199);
      assert.equal(moving.settling, false);
      assert.ok(moving.xy[0] > .08 && moving.xy[0] < .081);
      assert.ok(end.xy[0] > .919 && end.xy[0] < .921);
    }
    assert.equal(at(total - .1).phase, "validation-end");
    assert.equal(at(total - .1).settling, false);
  }
}
console.log(JSON.stringify(totals));
''', str(runtime)], check=True, capture_output=True, text=True)
        for block, total in json.loads(result.stdout).items():
            self.assertAlmostEqual(total, gaze_record.block_seconds(block))

    def test_completion_uses_each_blocks_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            person = root / "p-demo"
            person.mkdir(mode=0o700)
            baseline = person / "old-baseline"
            baseline.mkdir(parents=True, mode=0o700)
            geometry = screen(100, 100)
            (baseline / "recording.json").write_text(json.dumps(dict(
                version=2, protocol_version=2, person="p-demo", session="old-baseline",
                condition="upright", complete=True, finished=True, glasses="glasses",
                device="laptop", screen=geometry, epoch=1, requested_seconds=150)))
            for block, override, elapsed, complete in [
                ("distance", None, 102.5, True), ("no-recalibration", None, 72.5, True),
                ("head", None, 72.5, False), ("light", 120, 119.9, True),
            ]:
                with self.subTest(block=block):
                    host = gaze_record.RecordingHost(person, person="p-demo", glasses="glasses",
                        blocks=[block], duration=override, dataset_root=root)
                    host._context, host._nonce = 7, "owned"
                    def event(kind, **fields):
                        host._event(dict(method="Runtime.bindingCalled", params=dict(
                            name="__hermesGazeIntent", executionContextId=7,
                            payload=json.dumps(dict(type=kind, nonce="owned", **fields)))))
                    try:
                        event("record_consent", accepted=True)
                        event("record_start", block=block, screen=geometry, epoch=200)
                        if block == "no-recalibration":
                            self.assertEqual(host.metadata["calibration_source"], "old-baseline")
                        event("record_frame", t=elapsed, target=[20, 20], phase="validation-end",
                              settling=False, media_time=elapsed, presented_frame=1)
                        event("record_chunk", data=base64.b64encode(b"synthetic video").decode())
                        event("record_end", reason="complete")
                        self.assertEqual(host.metadata["complete"], complete)
                        self.assertAlmostEqual(host.metadata["requested_seconds"],
                                               gaze_record.block_seconds(block, override))
                        self.assertEqual(host.metadata["protocol_version"], 3)
                    finally:
                        host.stop()

    def test_legacy_and_new_sessions_load_and_score_without_settling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "recordings"
            for version, name, condition, epoch in [(2, "old", "upright", 1), (3, "new", "distance", 200)]:
                directory = root / "p-demo" / name
                directory.mkdir(parents=True, mode=0o700)
                meta = dict(version=2, protocol_version=version, person="p-demo", session=name,
                    condition=condition, glasses="glasses", device="laptop", complete=True,
                    finished=True, fake_camera=False, epoch=epoch, screen=screen(100, 100),
                    requested_seconds=150 if version == 2 else 102.6)
                (directory / "recording.json").write_text(json.dumps(meta))
                rows = [dict(t=i * .1, target=[x * 100, y * 100], phase="calibration", settling=False)
                        for i, (_, x, y) in enumerate(observations())]
                rows += [dict(t=t, target=[30, 70], phase="reading", settling=settling)
                         for t, settling in [(90, True), (91, False)]]
                (directory / "targets.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            def decode(command, **kwargs):
                if command[0] == "ffprobe":
                    directory = Path(command[-1]).parent
                    rows = [json.loads(r) for r in (directory / "targets.jsonl").read_text().splitlines()]
                    return subprocess.CompletedProcess(command, 0, json.dumps(dict(frames=[
                        dict(best_effort_timestamp_time=r["t"]) for r in rows])))
                for i in range(len(observations()) + 2):
                    Path(command[-1].replace("%06d", f"{i + 1:06d}")).write_bytes(b"synthetic frame")
                return subprocess.CompletedProcess(command, 0)
            with patch("hermes_gaze.benchmark.gaze_eval.subprocess.run", side_effect=decode):
                data = load_dataset(root, Path(tmp) / "frames", stride=1)
            self.assertEqual(gaze_record.completed_blocks(root, "p-demo", "glasses", "laptop"),
                             {"upright", "distance"})
            for session in data["sessions"]:
                self.assertEqual([f["video_t"] for f in session["frames"] if f["phase"] == "reading"], [91])
                for frame, (features, _, _) in zip(session["frames"], observations()):
                    frame["features"] = features
                session["frames"][-1]["features"] = [.3, .7, .06, .21, 1., -.4, .3, .1]
            rows, _ = evaluate(data, EvalRidge, "baseline", 9, "same-session")
            self.assertEqual({r["session"]: (r["status"], r["test_frames"]) for r in rows},
                             {"old": ("ok", 1), "new": ("ok", 1)})
            cross, _ = evaluate(data, EvalRidge, "baseline", 9, "cross-condition")
            self.assertEqual([(r["session"], r["calibration_session"]) for r in cross if r["status"] == "ok"],
                             [("new", "old")])

    def test_cli_default_blocks_resume_and_duration(self):
        for extra in [[], ["--duration", "102.6"], ["--duration", "150"], ["--blocks", "light", "lid"]]:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                with patch.object(sys, "argv", ["record", "--person", "p-demo", "--glasses", "glasses",
                        "--device", "laptop", "--out", tmp, *extra]), \
                     patch.object(gaze_record, "completed_blocks", return_value=set(gaze_record.CONDITIONS)) as completed, \
                     patch.object(gaze_record, "RecordingHost") as host, contextlib.redirect_stdout(io.StringIO()) as output:
                    gaze_record.main()
                    self.assertIn("All selected blocks are complete", output.getvalue())
                    completed.assert_called_once()
                    host.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(sys, "argv", ["record", "--person", "p-demo", "--glasses", "glasses",
                 "--device", "laptop", "--out", tmp]), \
             patch.object(gaze_record, "completed_blocks", return_value={"upright"}), \
             patch.object(gaze_record, "RecordingHost") as host, contextlib.redirect_stdout(io.StringIO()):
            host.return_value.start.return_value = {"state": "running"}
            host.return_value.done.wait.return_value = True
            host.return_value.saved = []
            gaze_record.main()
            self.assertEqual(host.call_args.kwargs["blocks"], ["distance", "head", "no-recalibration"])
            self.assertIsNone(host.call_args.kwargs["duration"])
