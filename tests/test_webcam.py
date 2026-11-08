"""Webcam contracts without devices, downloads, Chrome or model calls."""
import copy
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
import subprocess
from unittest.mock import patch

import numpy as np

from hermes_gaze.benchmark.gaze_research import Candidate, Fit
from hermes_gaze import service
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.tracker.webcam_gaze import AppearanceEstimator, LandmarkEstimator, ScreenPoint, screen_to_viewport
from hermes_gaze.webcam import WebcamHost

SCREEN = {"left": 0, "top": 0, "width": 1440, "height": 900, "dpr": 2,
          "screen_width": 1440, "screen_height": 900, "screen_left": 0, "screen_top": 25}


def observations():
    return [([x, y, x * .2, y * .3, x + y, x - y, .3, .1], x, y)
            for y in (.1, .5, .9) for x in (.1, .5, .9) for _ in range(6)]


def appearance_features(x, y):
    return [x if i % 2 == 0 else y for i in range(128)] + [.2 * x, .3 * y]


def appearance_observations():
    return [(appearance_features(x, y), x, y) for _, x, y in observations()]


class WebcamContracts(unittest.TestCase):
    def test_mapping_uses_viewport_origin_zoom_and_scroll_not_retina_pixels(self):
        geometry = {"origin_x": 140, "origin_y": 180, "dpr": 2.5, "width": 800, "height": 500,
                    "scroll_x": 17, "scroll_y": 900, "screen_left": 0, "screen_top": 25,
                    "screen_width": 1440, "screen_height": 900}
        p = ScreenPoint(640, 430, 1794000000.125)
        sample = screen_to_viewport(p, geometry, SCREEN)
        self.assertEqual((sample["x_vp"], sample["y_vp"]), (400, 200))
        self.assertEqual((sample["x_doc"], sample["y_doc"]), (417, 1100))
        self.assertEqual(sample["t"], p.t)
        self.assertAlmostEqual(sample["t_start"], p.t - .1)
        for changed, reason in (({"origin_x": 1000}, "outside_page"), ({"dpr": 0}, "invalid_geometry"),
                                ({"screen_left": 1440}, "wrong_display"), ({"origin_y": math.nan}, "invalid_geometry")):
            self.assertEqual(screen_to_viewport(p, {**geometry, **changed}, SCREEN), reason)
        self.assertEqual(screen_to_viewport(p, {}, SCREEN), "invalid_geometry")
        self.assertEqual(screen_to_viewport(p, {"drop_reason": "no_page_anchor"}, SCREEN), "no_page_anchor")

    def test_personal_calibration_predicts_unseen_position_and_loads_exactly(self):
        model = LandmarkEstimator()
        self.assertIsNone(model.predict([0.] * 8, 1794000000.))
        profile = model.calibrate(observations(), SCREEN)
        features = [.3, .7, .06, .21, 1., -.4, .3, .1]
        point = model.predict(features, 1794000000.25)
        self.assertAlmostEqual(point.x, .3 * 1440, delta=12)
        self.assertAlmostEqual(point.y, .7 * 900, delta=12)
        loaded = LandmarkEstimator(); loaded.load(json.loads(json.dumps(profile)))
        self.assertEqual(loaded.predict(features, point.t), point)
        self.assertIsNone(model.predict([math.nan] * 8, point.t))
        self.assertIsNone(model.predict([10.] * 8, point.t))
        with self.assertRaises(ValueError):
            model.load({**profile, "model_id": "other-runtime"})
        with self.assertRaises(ValueError):
            model.calibrate([([0.] * 8, x, y) for _, x, y in observations()], SCREEN)

    def test_appearance_fit_matches_selected_research_and_profile_roundtrip(self):
        data = appearance_observations()
        model = AppearanceEstimator()
        research = Fit(Candidate("appearance-left", 10.))
        profile = model.calibrate(data, SCREEN)
        research.calibrate(data, SCREEN)
        loaded = AppearanceEstimator(); loaded.load(json.loads(json.dumps(profile)))
        for x, y in ((.3, .7), (.8, .2), (.45, .55)):
            features = appearance_features(x, y)
            point = model.predict(features, 123.)
            np.testing.assert_allclose([point.x / SCREEN["width"], point.y / SCREEN["height"]],
                                       research.raw(np.asarray(features)), atol=1e-12)
            self.assertAlmostEqual(point.x / SCREEN["width"], x, delta=.01)
            self.assertAlmostEqual(point.y / SCREEN["height"], y, delta=.01)
            self.assertEqual(loaded.predict(features, 123.), point)
        for invalid in (observations(), data[:44], data[:-6],
                        [([math.nan] * 130, x, y) for _, x, y in data]):
            with self.subTest("invalid fit"), self.assertRaises(ValueError):
                model.calibrate(invalid, SCREEN)
        with self.assertRaises(ValueError):
            model.load(LandmarkEstimator().calibrate(observations(), SCREEN))
        with self.assertRaises(ValueError):
            model.load({**profile, "weights": [[0., 0.]] * 9})

    def test_appearance_rejects_strictly_outside_screen_without_smoothing(self):
        model = AppearanceEstimator()
        weights = np.zeros((131, 2)); weights[-2:] = np.eye(2)
        model.load(dict(model_id=model.model_id, mean=[0.] * 130, scale=[1.] * 130,
                        weights=weights.tolist(), screen=SCREEN))
        for x, y in ((0., 0.), (1., 1.), (.2, .8), (.8, .2)):
            self.assertEqual(model.predict([0.] * 128 + [x, y], 12.), ScreenPoint(x * 1440, y * 900, 12.))
        for x, y in ((np.nextafter(0., -1.), .5), (np.nextafter(1., 2.), .5),
                     (.5, np.nextafter(0., -1.)), (.5, np.nextafter(1., 2.))):
            self.assertIsNone(model.predict([0.] * 128 + [x, y], 12.))
        for features in ([0.] * 8, [0.] * 129, [math.nan] * 130, [math.inf] * 130):
            self.assertIsNone(model.predict(features, 12.))
        self.assertIsNone(model.predict([0.] * 130, math.nan))

    def test_appearance_binding_accepts_bounded_features_but_not_malformed_vectors(self):
        host = WebcamHost(lambda *_: False)
        host._context, host._nonce = 8, "owned"
        host._calibration = SCREEN
        now = time.time()
        def send(features):
            nonlocal now
            now += .001
            host._event({"method": "Runtime.bindingCalled", "params": {"name": "__hermesGazeIntent",
                "executionContextId": 8, "payload": json.dumps({"type": "sample", "nonce": "owned",
                    "t": now, "features": features, "calibration": 0})}})
        features = [10.] + [0.] * 127 + [.2, .3]
        send(features)
        self.assertEqual(host._point_samples, [features])
        malformed = (None, {}, [0.] * 8, [0.] * 129, [0.] * 131, ["0"] * 130, [False] * 130,
                     [math.nan] * 130, [math.inf] * 130, [math.sqrt(128)] + [0.] * 129,
                     [0.] * 128 + [4., 0.], [0.] * 128 + [0., -4.])
        for vector in malformed:
            send(vector)
        self.assertEqual(host._point_samples, [features])
        self.assertEqual(host.drops["no_features"], len(malformed))

    def test_old_profile_requests_recalibration_without_error_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            old = LandmarkEstimator().calibrate(observations(), SCREEN)
            path.write_text(json.dumps(old))
            before = path.read_bytes()
            host = WebcamHost(lambda *_: False, profile_path=path)
            self.addCleanup(host.stop)
            def camera():
                host.state = "running"; host._ready.set(); host._stop.wait(5)
            with patch("hermes_gaze.webcam.prepare_assets", return_value=Path(directory)), \
                 patch.object(host, "_run", side_effect=camera):
                status = host.start()
                self.assertEqual(status["state"], "running")
                self.assertFalse(status["calibrated"])
                self.assertEqual(status["error"], "")
                self.assertIn("recalibrate", status["calibration_message"])
                self.assertIsNone(host.estimator.profile)
                self.assertEqual(path.read_bytes(), before)
                host.stop()

    def test_shared_appearance_extraction_preserves_saved_layout_in_node(self):
        result = subprocess.run(["node", str(Path(__file__).with_name("webcam_features.cjs"))],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_owned_context_nonce_epoch_validation_and_swappable_estimator(self):
        class OtherEstimator:
            model_id = "test-other-runtime"
            feature_count = 2
            def predict(self, features, t):
                return ScreenPoint(features[0] * 1440, features[1] * 900, t)
        received = []
        host = WebcamHost(lambda point, screen: received.append(point) or True, estimator=OtherEstimator())
        host.profile = {"screen": SCREEN}
        host._context, host._nonce = 8, "private"
        now = time.time()
        def send(t=now, nonce="private", context=8, features=None):
            host._event({"method": "Runtime.bindingCalled", "params": {"name": "__hermesGazeIntent",
                "executionContextId": context, "payload": json.dumps({"type": "sample", "nonce": nonce,
                "t": t, "features": [.25, .75] if features is None else features})}})
        send(nonce="page-forged"); send(context=7); send(t=12.5); send(t=now + 10)
        self.assertEqual(received, [])
        send(); send()  # Replayed observation cannot extend a fixation.
        self.assertEqual(received, [ScreenPoint(360, 675, now)])
        send(t=now + .01, features=[0.] * 8)
        self.assertEqual(host.predictions, 1)

    def test_calibration_file_is_private_and_not_a_repo_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "personal" / "calibration.json"
            host = WebcamHost(lambda *_: False, profile_path=path)
            profile = LandmarkEstimator().calibrate(observations(), SCREEN)
            host._save(profile)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(json.loads(path.read_text()), profile)

    def test_mode_switch_never_opens_camera_and_revokes_old_evidence(self):
        session = GazeSession("http://127.0.0.1:1")
        self.addCleanup(session.close)
        session.configure(mode="webcam")
        self.assertIsNone(session.webcam)
        now = time.time()
        session.ingest([{"x_vp": 40, "y_vp": 60, "x_doc": 40, "y_doc": 60, "t": now, "source": "webcam"}])
        self.assertEqual(session.ring_buffer.latest().source, "webcam")
        before = session.resolution_id
        session.configure(mode="hover")
        self.assertIsNone(session.ring_buffer.latest())
        self.assertGreater(session.resolution_id, before)
        self.assertFalse(session.choose(resolution_id=before)["ok"])
        with self.assertRaises(ValueError):
            session.configure(mode="unknown")

    def test_webcam_fusion_uses_only_camera_fixations_and_freezes_before_asr(self):
        session = GazeSession("http://127.0.0.1:1")
        self.addCleanup(session.close)
        session.configure(mode="webcam")
        t = time.time()
        pushed = {"pointer": {"x_vp": 900, "y_vp": 800}, "page_url": "https://example.test/",
                  "browser_target": "source", "browser_document": "document", "browser_route": 2,
                  "fixations": [{"x_vp": 150, "y_vp": 150, "x_doc": 150, "y_doc": 150, "t": t, "source": "webcam"}],
                  "candidates": [{"id": "article", "tag": "p", "role": "text", "label": "Orbital mechanics",
                                  "rect_vp": [100, 100, 160, 100], "rect_doc": [100, 100, 160, 100]}]}
        epoch = session.resolution_id
        with patch.object(service, "_LLM", None):
            payload = service.resolve_now(session, utterance="Explain this", pushed=pushed, activate=False)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["top"]["id"], "article")
        self.assertIn("Webcam gaze", payload["context"])
        self.assertFalse(payload["actions_allowed"])
        self.assertEqual(session.resolution_id, epoch)
        self.assertEqual(payload["browser_document"], "document")
        self.assertEqual(session.ring_buffer.latest().source, "webcam")
        self.assertAlmostEqual(session.ring_buffer.latest().x_vp, 150.)
        no_camera = copy.deepcopy(pushed); no_camera["fixations"][0]["source"] = "hover"
        self.assertFalse(service.resolve_now(session, utterance="Explain this", pushed=no_camera)["ok"])
        session.configure(mode="hover")
        # Late ASR owns its saved webcam evidence but must not switch the live mode back.
        with patch.object(service, "_LLM", None):
            late = service.resolve_now(session, mode="webcam", utterance="Explain this", pushed=pushed, activate=False)
        self.assertTrue(late["ok"])
        self.assertEqual(session.tracker.mode, "hover")

    def test_delayed_simulated_asr_cannot_restore_choose_in_webcam_mode(self):
        from tests.test_service_intents import _pushed
        session = GazeSession("http://127.0.0.1:1")
        self.addCleanup(session.close)
        session.configure(mode="simulated")
        captured = _pushed(time.time())
        session.configure(mode="webcam")
        epoch = session.resolution_id
        with patch.object(service, "_LLM", None):
            frozen = service.resolve_now(session, mode="simulated", utterance="Export this",
                                         pushed=captured, activate=False)
            with self.subTest("frozen resolution cannot reactivate actions"):
                self.assertTrue(frozen["ok"])
                self.assertIsNone(session.last_resolution)
                self.assertEqual(session.resolution_id, epoch)
            active = service.resolve_now(session, mode="simulated", utterance="Export this", pushed=captured)
            with self.subTest("choose also requires the live simulated mode"):
                self.assertFalse(session.choose(resolution_id=active["resolution_id"])["ok"])
                self.assertEqual(session.tracker.mode, "webcam")
                self.assertTrue(all(s.source != "webcam" for s in session.ring_buffer.snapshot()))

    def test_restarting_after_interrupted_calibration_predicts_with_saved_profile(self):
        received = []
        with tempfile.TemporaryDirectory() as directory:
            host = WebcamHost(lambda point, screen: received.append(point) or True,
                              profile_path=Path(directory) / "calibration.json")
            self.addCleanup(host.stop)
            profile = AppearanceEstimator().calibrate(appearance_observations(), SCREEN)
            host._save(profile)
            def camera():
                host._context, host._nonce = 8, "owned"
                host.state = "running"
                host._ready.set()
                host._stop.wait(5)
            def event(kind, **data):
                host._event({"method": "Runtime.bindingCalled", "params": {"name": "__hermesGazeIntent",
                    "executionContextId": 8, "payload": json.dumps({"type": kind, "nonce": "owned", **data})}})
            with patch("hermes_gaze.webcam.prepare_assets", return_value=Path(directory)), \
                 patch.object(host, "_run", side_effect=camera):
                host.start()
                event("calibration_start", screen=SCREEN, viewport={"left": 0, "top": 0, "width": 1440, "height": 900})
                event("sample", t=time.time(), features=appearance_features(.3, .7), calibration=0)
                host.stop()
                host.start()
                event("sample", t=time.time(), features=appearance_features(.3, .7), calibration=-1)
                self.assertEqual(len(received), 1)
                self.assertAlmostEqual(received[0].x, 432, delta=12)
                self.assertAlmostEqual(received[0].y, 630, delta=12)
                self.assertEqual(json.loads(host.profile_path.read_text()), profile)
                host.stop()

    def test_drop_status_distinguishes_prediction_and_delivery_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            results = iter(("no_page_anchor", "outside_page", "no_foreground_tab", False,
                            ConnectionError(), TimeoutError(), True))
            def deliver(*_):
                result = next(results)
                if isinstance(result, Exception):
                    raise result
                return result
            host = WebcamHost(deliver, profile_path=Path(directory) / "calibration.json")
            profile = AppearanceEstimator().calibrate(appearance_observations(), SCREEN)
            host.estimator.load(profile)
            host._context, host._nonce = 8, "owned"
            now = time.time()
            def send(features, t=None):
                nonlocal now
                now += .001
                host._event({"method": "Runtime.bindingCalled", "params": {"name": "__hermesGazeIntent",
                    "executionContextId": 8, "payload": json.dumps({"type": "sample", "nonce": "owned",
                    "t": now if t is None else t, "features": features})}})
            features = appearance_features(.3, .7)
            send(features)  # No profile is active yet.
            host.profile = profile
            send(None)
            send([3.] * 130)  # Valid observations, but an off-screen estimate.
            send(features, t=1.)
            for _ in range(7):
                send(features)
            drops = host.status()["drops"]
            self.assertEqual(host.delivered, 1)
            for reason in ("uncalibrated", "no_features", "offscreen", "stale_sample", "no_page_anchor",
                           "outside_page", "no_foreground_tab", "rejected_by_page", "transport_error", "transport_timeout"):
                self.assertEqual(drops[reason], 1, reason)
            self.assertTrue(all(type(count) is int for count in drops.values()))
            drops["offscreen"] = 0
            self.assertEqual(host.status()["drops"]["offscreen"], 1)


if __name__ == "__main__":
    unittest.main()
