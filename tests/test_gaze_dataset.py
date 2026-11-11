"""Participant portability, resumption and honest protocol summaries."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from look.benchmark.gaze_dataset import export_person, import_person, inventory, pseudonym
from look.benchmark.gaze_eval import summaries, validation_metrics
from look.benchmark.gaze_record import completed_blocks
from look.tracker.webcam_gaze import ScreenPoint


class DatasetTests(unittest.TestCase):
    def test_bundle_roundtrip_resume_collision_and_untrusted_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"; root.mkdir(mode=0o700)
            person = root / "p-a7c4"; person.mkdir(mode=0o700)
            (person / "consent.json").write_text(json.dumps(dict(person=person.name, accepted=True)))
            for session, complete in (("baseline", True), ("partial", False)):
                directory = person / session; directory.mkdir(mode=0o700)
                meta = dict(person=person.name, session=session, glasses="glasses", condition="upright",
                            device="laptop", complete=complete, finished=True, epoch=1 if complete else 2)
                (directory / "recording.json").write_text(json.dumps(meta))
                (directory / "targets.jsonl").write_text('{"t":0.1}\n')
                (directory / "camera.webm").write_bytes(b"private fixture bytes")
            self.assertEqual(completed_blocks(root, person.name, "glasses", "laptop"), {"upright"})
            self.assertEqual(completed_blocks(root, person.name, "none", "laptop"), set())
            (person / "baseline" / "recording.json").write_text(json.dumps({**meta, "session": "baseline", "complete": False}))
            self.assertEqual(completed_blocks(root, person.name, "glasses", "laptop"), set())
            bundle = export_person(root, person.name, Path(tmp) / "person.zip")
            dest = Path(tmp) / "imported"
            self.assertEqual(import_person(bundle, dest), person.name)
            self.assertEqual(import_person(bundle, dest), person.name)
            self.assertEqual(len(inventory(dest, person.name)), 2)
            for original in person.rglob("*"):
                if original.is_file():
                    restored = dest / person.name / original.relative_to(person)
                    self.assertEqual(restored.read_bytes(), original.read_bytes())
                    self.assertEqual(restored.stat().st_mode & 0o777, 0o600)
            changed = dest / person.name / "baseline" / "camera.webm"
            changed.unlink()
            import_person(bundle, dest)
            self.assertEqual(changed.read_bytes(), b"private fixture bytes")
            changed.write_bytes(b"other person's video")
            with self.assertRaisesRegex(ValueError, "collision"):
                import_person(bundle, dest)
            conflict = Path(tmp) / "conflict"; conflict.mkdir(mode=0o700)
            (conflict / person.name).mkdir(mode=0o700)
            (conflict / person.name / "baseline").write_text("not a session directory")
            with self.assertRaisesRegex(ValueError, "collision"):
                import_person(bundle, conflict)
            evil = Path(tmp) / "evil.zip"
            with zipfile.ZipFile(evil, "w") as z:
                z.writestr("../escape", "bad")
            with self.assertRaises(ValueError):
                import_person(evil, dest)
            self.assertFalse((Path(tmp) / "escape").exists())
            with zipfile.ZipFile(evil, "w") as z:
                z.writestr("p-a7c4/consent.json", " " * 8193)
            with self.assertRaisesRegex(ValueError, "size bound"):
                import_person(evil, dest)
            consent = person / "consent.json"
            consent.unlink(); consent.symlink_to(person / "baseline" / "recording.json")
            with self.assertRaisesRegex(ValueError, "regular local file"):
                export_person(root, person.name, Path(tmp) / "symlink.zip")
            for value in ("a name", "../p-demo", "/p-demo", "p-a"):
                with self.assertRaises(ValueError):
                    pseudonym(value)

    def test_equal_person_summary_and_matched_end_validation(self):
        base = dict(status="ok", condition="upright", glasses="none", protocol="same-session",
                    config="baseline", calibration_points=9, coverage=100)
        rows = [{**base, "person": "a", "test_frames": 100, "region_hit": {str(n): 100 for n in (3, 4, 5)}},
                {**base, "person": "b", "test_frames": 10, "region_hit": {str(n): 0 for n in (3, 4, 5)}}]
        self.assertEqual(summaries(rows)["cross_person"][0]["region_hit"]["3"], 50)
        class Model:
            def predict(self, f, t):
                return ScreenPoint(f[0], f[1], t)
        session = dict(screen=dict(width=100, height=100), frames=[
            dict(phase="validation-start", features=[20, 20], t=1, target=[20, 20]),
            dict(phase="validation-end", features=[30, 20], t=2, target=[20, 20]),
            dict(phase="validation-end", features=None, t=3, target=[20, 20])])
        result = validation_metrics(Model(), session, "features")
        self.assertEqual(result["bias_shift_px"], 10)
        self.assertEqual(result["validation-end"]["region_hit"]["3"], 50)
        self.assertEqual(result["validation-end"]["predicted"], 1)
