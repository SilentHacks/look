"""Offline contracts: leakage, abstention, calibration parity and private recording."""
import base64
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from hermes_gaze.benchmark.gaze_eval import EvalRidge, evaluate, private_directory, screen, split_frames
from hermes_gaze.benchmark.gaze_tuning import Regression, jitter_score
from hermes_gaze.benchmark.gaze_record import RecordingHost
from hermes_gaze.benchmark.run_benchmark import run_benchmark_suite
from hermes_gaze.tracker.webcam_gaze import LandmarkEstimator
from tests.test_webcam import observations, SCREEN


class GazeEvaluationTests(unittest.TestCase):
    def test_offline_baseline_is_numerically_the_shipped_regressor(self):
        live, offline = LandmarkEstimator(), EvalRidge()
        a, b = live.calibrate(observations(), SCREEN), offline.calibrate(observations(), SCREEN)
        np.testing.assert_allclose(a["weights"], b["weights"], atol=1e-12)
        features = [.3, .7, .06, .21, 1., -.4, .3, .1]
        self.assertEqual(live.predict(features, 1.), offline.predict(features, 1.))

    def test_whole_days_and_target_identities_are_held_out_before_face_filtering(self):
        frames = [dict(t=day, target=[x, y], phase="unassigned", features=[x, y] + [0.] * 6)
                  for day in (1., 2., 3., 4.) for x, y in ((10., 10.), (20., 80.), (90., 20.), (80., 90.))]
        session = dict(person="a", session="days", screen=screen(100, 100), temporal=False, frames=frames)
        calibration, test, _ = split_frames([session], 3)
        self.assertTrue(all(f["t"] == 1 for _, f in calibration))
        self.assertTrue(all(f["t"] > 1 for _, f in test))
        self.assertTrue({tuple(f["target"]) for _, f in calibration}.isdisjoint({tuple(f["target"]) for _, f in test}))
        # Missing early faces do not move the cutoff into the test days.
        for f in frames[:4]:
            f["features"] = None
        with self.assertRaises(ValueError):
            split_frames([session], 3)

    def test_missing_faces_are_region_misses_not_discarded_rows(self):
        frames = [dict(t=i * .1, phase="calibration", features=f, target=[x * 100, y * 100])
                  for i, (f, x, y) in enumerate(observations())]
        features = [.3, .7, .06, .21, 1., -.4, .3, .1]
        frames += [dict(t=10 + i * .1, phase="fixed", features=features if i % 2 else None, target=[30., 70.]) for i in range(10)]
        session = dict(person="a", session="video", screen=screen(100, 100), temporal=True, frames=frames)
        rows, traces = evaluate(dict(dataset="check", sessions=[session]), EvalRidge, "baseline", 9, "same-session")
        self.assertEqual(rows[0]["test_frames"], 10)
        self.assertEqual(rows[0]["predicted"], 5)
        self.assertEqual(rows[0]["region_hit"], {"2": 50., "3": 50., "4": 50., "5": 50.})
        self.assertEqual(sum(t["prediction"] is None for t in traces), 5)
        self.assertIsNone(rows[0]["jitter_px"])

    def test_later_recording_calibration_never_leaks_back_into_earlier_tests(self):
        early = [dict(t=i * .1, phase="calibration", features=f, target=[x * 100, y * 100])
                 for i, (f, x, y) in enumerate(observations())]
        test = dict(t=10., phase="fixed", features=[.3] * 8, target=[30., 70.])
        first = dict(person="a", session="first", screen=screen(100, 100), temporal=True, frames=early + [test])
        later = dict(person="a", session="later", screen=screen(100, 100), temporal=True,
                     frames=[{**f, "t": f["t"] + 100.} for f in early])
        calibration, held_out, _ = split_frames([first, later], 9, "same-session")
        self.assertTrue(all(s is first for s, _ in calibration + held_out))
        self.assertIn((first, test), held_out)
        later["frames"].append({**test, "t": 110.})
        _, cross_day, _ = split_frames([first, later], 9, "cross-day")
        self.assertEqual(cross_day, [(later, later["frames"][-1])])

    def test_same_day_freezes_early_cutoff_and_refits_each_day(self):
        frames = [dict(t=day, order=i, target=[10. + i * 4, 20. + (i % 3) * 20],
                       features=[float(i)] * 8, phase="unassigned")
                  for day in (1., 2.) for i in range(20)]
        session = dict(person="a", session="days", screen=screen(100, 100), temporal=False, frames=frames)
        seen = []
        class Capture(EvalRidge):
            def calibrate(self, observations, geometry):
                seen.append([r[0][0] for r in observations])
                return super().calibrate(observations, geometry)
        rows, trace = evaluate(dict(dataset="check", sessions=[session]), Capture, "capture", 3, "same-session")
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])
        self.assertTrue(all(i < 8 for fit in seen for i in fit))
        self.assertEqual([r["test_frames"] for r in rows], [12, 12])
        self.assertTrue(all(t["target"][0] >= 42 for t in trace))
        first = {**session, "frames": frames[:20]}
        calibration, test, cutoff = split_frames([first], 3, "same-session")
        self.assertEqual(cutoff, 8)
        self.assertTrue({tuple(f["target"]) for _, f in calibration}.isdisjoint(
                        {tuple(f["target"]) for _, f in test}))
        for f in first["frames"][:8]:
            f["features"] = None
        with self.assertRaises(ValueError):
            split_frames([first], 3, "same-session")

    def test_candidate_models_fit_only_calibration_and_abstain_offscreen(self):
        data = observations()
        for kind in ("linear", "poly2", "rbf", "axes"):
            model = Regression(.001, kind)
            profile = model.calibrate(data, SCREEN)
            restored = Regression(.001, kind); restored.load(profile)
            f, x, y = data[0]
            prediction = restored.predict(f, 1.)
            self.assertIsNotNone(prediction)
            self.assertAlmostEqual(prediction.x / SCREEN["width"], x, delta=.02)
            self.assertAlmostEqual(prediction.y / SCREEN["height"], y, delta=.02)
            self.assertIsNone(restored.predict([float("nan")] * 8, 2.))

    def test_temporal_filters_reject_spikes_without_filling_missing_frames(self):
        samples = [dict(session="s", temporal=True, t=i * .1, target=[10., 10.], prediction=[10., 10.])
                   for i in range(10)]
        samples[4]["prediction"] = [100., 100.]
        samples[7]["prediction"] = None
        raw, filtered = jitter_score(samples, "raw"), jitter_score(samples, "median3-ema")
        self.assertGreater(raw["jitter_px"], 50.)
        self.assertEqual(filtered["jitter_px"], 0.)
        self.assertEqual(filtered["predictions"], 9)
        # A new session at the same timestamp resets, rather than inheriting a previous person's filter.
        samples += [dict(session="other", temporal=True, t=0., target=[80., 80.], prediction=[80., 80.])]
        self.assertEqual(jitter_score(samples, "median3-ema")["jitter_px"], 0.)

    def test_recorded_benchmark_preserves_abstentions(self):
        sample = dict(person="a", session="a", t=1., temporal=False, screen=[1280., 900.],
                      prediction=[500., 400.], target=[500., 400.])
        perfect = run_benchmark_suite(5, gaze_trace=[sample])
        missing = run_benchmark_suite(5, gaze_trace=[{**sample, "prediction": None}])
        self.assertEqual(perfect["raw_hit_test"]["recorded"], 100.)
        self.assertTrue(all(v["recorded"] == 0 for v in missing.values()))
        mixed = run_benchmark_suite(2, gaze_trace=[{**sample, "temporal": True},
            {**sample, "temporal": True, "t": 1.2, "prediction": None}])
        self.assertEqual(mixed["raw_hit_test"]["recorded"], 50.)
        with self.assertRaises(ValueError):
            run_benchmark_suite(gaze_trace=[])

    def test_recording_requires_owned_nonce_and_writes_only_private_files(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "private"
            host = RecordingHost(directory, duration=36, fake_video=Path(root) / "fake.y4m",
                                 geometry=dict(width_mm=300., height_mm=200., distance_mm=600.))
            host._context, host._nonce = 7, "owned"
            self.addCleanup(host.stop)
            def event(kind, nonce="owned", context=7, **fields):
                host._event(dict(method="Runtime.bindingCalled", params=dict(name="__hermesGazeIntent", executionContextId=context,
                    payload=json.dumps(dict(type=kind, nonce=nonce, **fields)))))
            event("record_start", nonce="forged", screen=SCREEN)
            event("record_start", context=8, screen=SCREEN)
            self.assertFalse((directory / "camera.webm").exists())
            event("record_start", screen={**SCREEN, "height": 450}, epoch=1., viewport_origin=[0, 0])
            event("record_frame", t=.1, target=[10, 20], phase="calibration", settling=False, media_time=.1, presented_frame=1)
            event("record_frame", t=.1, target=[10, 20], phase="calibration", settling=False, media_time=.1, presented_frame=1)
            event("record_chunk", data=base64.b64encode(b"private camera bytes").decode())
            event("record_end", reason="test")
            self.assertTrue(host.done.is_set())
            self.assertEqual(len((directory / "targets.jsonl").read_text().splitlines()), 1)
            self.assertEqual((directory / "camera.webm").read_bytes(), b"private camera bytes")
            self.assertTrue(json.loads((directory / "recording.json").read_text())["finished"])
            measured = json.loads((directory / "recording.json").read_text())["screen"]
            self.assertEqual((measured["width_mm"], measured["height_mm"], measured["distance_mm"]), (300., 100., 600.))
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            for file in directory.iterdir():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            public = Path(root) / "public"; public.mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                private_directory(public)


if __name__ == "__main__":
    unittest.main()
