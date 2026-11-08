"""Offline research: baseline parity, pre-gate drift rescue and causal abstention."""
import unittest

import numpy as np

from hermes_gaze.benchmark.gaze_eval import EvalRidge
from hermes_gaze.benchmark.gaze_research import Candidate, Filter, Fit, run
from tests.test_webcam import observations, SCREEN


def features(x, y):
    return [x, y, x * .2, y * .3, x + y, x - y, .3, .1]


def session(shift=0.):
    frames = [dict(t=i * .1, phase="calibration", features=f, target=[x * 1440, y * 900])
              for i, (f, x, y) in enumerate(observations())]
    frames += [dict(t=10 + i * .1, phase="validation-start", features=features(.5 + shift, .5 + shift),
                    target=[720., 450.]) for i in range(6)]
    frames += [dict(t=20 + i * .1, phase="fixed", features=features(.3 + shift, .7 + shift),
                    target=[432., 630.]) for i in range(6)]
    frames += [dict(t=30 + i * .1, phase="validation-end", features=features(.3 + shift, .7 + shift),
                    target=[432., 630.]) for i in range(6)]
    return dict(session="synthetic", glasses="none", condition="upright", screen=SCREEN, frames=frames)


class GazeResearchTests(unittest.TestCase):
    def test_raw_baseline_matches_live_solver_including_offscreen_values(self):
        baseline, research = EvalRidge(), Fit(Candidate())
        baseline.calibrate(observations(), SCREEN)
        research.calibrate(observations(), SCREEN)
        x = np.array(features(.3, .7))
        p = baseline.predict(x, 1.)
        np.testing.assert_allclose(research.raw(x) * [1440, 900], [p.x, p.y], atol=1e-10)
        self.assertIsNone(baseline.predict(features(2., 2.), 2.))
        self.assertTrue(np.all(research.raw(np.array(features(2., 2.))) > 1))

    def test_labelled_bias_refresh_rescues_offscreen_without_using_end_labels(self):
        s = session(2.)
        rejected = run(Candidate(), 9, s, s, {"validation-end"})
        corrected = run(Candidate(bias_points=1), 9, s, s, {"validation-end"})
        self.assertEqual(rejected["coverage"], 0.)
        self.assertEqual(corrected["coverage"], 100.)
        self.assertEqual(corrected["region_hit"], {"3": 100., "4": 100., "5": 100.})
        self.assertLess(corrected["error_px"]["mean"], 12.)
        for f in s["frames"]:
            if f["phase"] == "validation-end":
                f["target"] = [0., 0.]
        changed = run(Candidate(bias_points=1), 9, s, s, {"validation-end"})
        self.assertEqual(changed["coverage"], 100.)
        self.assertGreater(changed["error_px"]["mean"], 700.)

    def test_missing_and_gated_samples_remain_region_misses_after_smoothing(self):
        s = session()
        end = [f for f in s["frames"] if f["phase"] == "validation-end"]
        for f in s["frames"]:
            f.update(blink=0., openness=[.3, .3])
        end[1]["features"] = None
        end[3]["blink"] = .9
        row = run(Candidate(gate="loose", ema=.12), 9, s, s, {"validation-end"})
        self.assertEqual(row["predicted"], 4)
        self.assertAlmostEqual(row["coverage"], 100 * 4 / 6)
        self.assertAlmostEqual(row["region_hit"]["3"], 100 * 4 / 6)
        self.assertEqual(row["missing_or_gated"], 2)

    def test_causal_filter_resets_after_missing_gaps_and_nonmonotone_time(self):
        f = Filter(.12)
        np.testing.assert_array_equal(f.apply(np.array([0., 0.]), 0.), [0., 0.])
        first = f.apply(np.array([100., 100.]), .1).copy()
        self.assertTrue(np.all((first > 0) & (first < 100)))
        self.assertIsNone(f.apply(None, .2))
        np.testing.assert_array_equal(f.apply(np.array([80., 80.]), .3), [80., 80.])
        np.testing.assert_array_equal(f.apply(np.array([20., 20.]), 1.), [20., 20.])
        np.testing.assert_array_equal(f.apply(np.array([50., 50.]), 0.), [50., 50.])

    def test_end_validation_cannot_change_development_fit_or_metrics(self):
        s = session()
        before = run(Candidate(), 9, s, s, {"fixed", "moving", "reading"})
        for f in s["frames"]:
            if f["phase"] == "validation-end":
                f.update(features=[float("nan")] * 8, target=[-1e9, 1e9])
        after = run(Candidate(), 9, s, s, {"fixed", "moving", "reading"})
        self.assertEqual(before["region_hit"], after["region_hit"])
        self.assertEqual(before["error_px"], after["error_px"])
        self.assertEqual(before["coverage"], after["coverage"])


if __name__ == "__main__":
    unittest.main()
