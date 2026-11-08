"""Pure screen-coordinate estimator and viewport mapping; no camera or persistence."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class ScreenPoint:
    x: float
    y: float
    t: float  # Unix seconds, not video-relative or performance.now().


class GazeEstimator(Protocol):
    """A runtime supplies bounded observations; policy never depends on its model."""
    model_id: str
    feature_count: int

    def predict(self, features: list[float], t: float) -> ScreenPoint | None: ...
    def calibrate(self, observations: list[tuple[list[float], float, float]], screen: dict) -> dict: ...
    def load(self, profile: dict) -> None: ...


class LandmarkEstimator:
    """Personal ridge regression over iris/head features from Face Mesh V2.

    No pretrained gaze weights or external gaze-training data. This estimates a
    coarse region, not an actionable button. Feature order is versioned with the model.
    """
    model_id = "mediapipe-face-v2-iris-ridge-1"
    feature_count = 8
    ridge = 1.

    def __init__(self) -> None:
        self.profile: dict | None = None

    def load(self, profile: dict) -> None:
        if profile.get("model_id") != self.model_id:
            raise ValueError("Calibration belongs to a different estimator")
        n = self.feature_count
        for key, shape in (("mean", (n,)), ("scale", (n,)), ("weights", (n + 1, 2))):
            a = np.asarray(profile.get(key), dtype=float)
            if a.shape != shape or not np.isfinite(a).all():
                raise ValueError("Invalid calibration profile")
        if min(profile["scale"]) <= 0:
            raise ValueError("Invalid calibration scale")
        screen = profile.get("screen", {})
        if not all(math.isfinite(float(screen[k])) for k in
                   ("left", "top", "width", "height", "screen_width", "screen_height", "screen_left", "screen_top", "dpr")):
            raise ValueError("Invalid calibration screen")
        if min(screen[k] for k in ("width", "height", "dpr")) <= 0:
            raise ValueError("Invalid calibration screen size")
        # ponytail: one display per profile; add per-display profiles if multi-monitor gaze is needed.
        self._mean = np.asarray(profile["mean"], dtype=float)
        self._scale = np.asarray(profile["scale"], dtype=float)
        self._weights = np.asarray(profile["weights"], dtype=float)
        self.profile = profile

    def calibrate(self, observations: list[tuple[list[float], float, float]], screen: dict) -> dict:
        x = np.asarray([r[0] for r in observations], dtype=float)
        y = np.asarray([[r[1], r[2]] for r in observations], dtype=float)
        if x.shape != (len(observations), self.feature_count) or len(x) < 45 or not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("Not enough valid calibration samples; try again")
        if len(np.unique(y, axis=0)) != 9:
            raise ValueError("Calibration requires all nine targets")
        mean, scale = x.mean(axis=0), x.std(axis=0)
        if max(scale) < .001:
            raise ValueError("Eyes did not move enough during calibration; try again")
        scale = np.maximum(scale, .001)
        a = np.column_stack((np.ones(len(x)), (x - mean) / scale))
        penalty = np.eye(self.feature_count + 1) * self.ridge; penalty[0, 0] = 0
        weights = np.linalg.solve(a.T @ a + penalty, a.T @ y)
        error = float(np.sqrt(np.mean((a @ weights - y) ** 2)))
        if error > .20:
            raise ValueError("Calibration did not fit the targets; try again in better light")
        profile = {"model_id": self.model_id, "mean": mean.tolist(), "scale": scale.tolist(),
                   "weights": weights.tolist(), "screen": dict(screen), "fit_error": error}
        self.load(profile)
        return profile

    def predict(self, features: list[float], t: float) -> ScreenPoint | None:
        if self.profile is None:
            return None
        x = np.asarray(features, dtype=float)
        if x.shape != (self.feature_count,) or not np.isfinite(x).all() or not math.isfinite(t):
            return None
        p = self.profile
        xy = self._weights[0] + ((x - self._mean) / self._scale) @ self._weights[1:]
        # Do not clamp an off-screen estimate onto an unrelated edge control.
        if not np.isfinite(xy).all() or not (0 <= xy[0] <= 1 and 0 <= xy[1] <= 1):
            return None
        s = p["screen"]
        return ScreenPoint(s["left"] + xy[0] * s["width"], s["top"] + xy[1] * s["height"], t)


class AppearanceEstimator(LandmarkEstimator):
    """Left 16×8 normalized grayscale eye patch, then that eye's two iris coordinates.

    Matches research appearance-left / linear / λ10; no smoothing or edge tolerance.
    The original eight-value estimator remains the offline comparison baseline.
    """
    model_id = "mediapipe-face-v2-left-appearance-iris-ridge10-1"
    feature_count = 130
    ridge = 10.
    # A standardized 128-pixel patch has |value| ≤ sqrt(127); iris keeps its old bound.
    feature_limits = (math.sqrt(128),) * 128 + (4., 4.)


# Held-out check after calibration: positions differ from the nine training points.
CHECK_POINTS = ((.3, .3), (.7, .3), (.2, .7), (.5, .7), (.8, .7))
CHECK_ORDERS = ((0, 3, 1, 4, 2), (4, 1, 2, 0, 3))
# PROVISIONAL pending the user's real-camera trial; fake devices cannot choose these.
CHECK_SETTLE_MS = 900  # Dot travel and eye movement; ignored samples.
CHECK_OBSERVE_MS = 700
CHECK_REGION_HALF = 1 / 6  # Screen fraction per axis: one cell of a 3×3 grid around the target.
CHECK_MIN_VALID_FRACTION = .5  # Of the trial's samples.
CHECK_MIN_VALID_SAMPLES = 3
CHECK_PASS_TRIALS = 8  # Of ten: "most of the time" must be clearly more than a majority.
CHECK_ENOUGH_TRIALS = 6  # Fewer valid trials than this cannot judge the calibration.
_MAP_CELLS, _HIT_STEPS = 40, 4  # Result drawing only: deliberately coarse positions.


def score_check_trial(estimates: list[tuple[float, float] | None], target: tuple[float, float]) -> dict:
    """One target trial, one vote. Missing or off-screen estimates count against it."""
    valid = [e for e in estimates if e is not None]
    if len(valid) < CHECK_MIN_VALID_SAMPLES or len(valid) < CHECK_MIN_VALID_FRACTION * len(estimates):
        return {"valid": False, "hit": False}
    x, y = np.median(np.asarray(valid, dtype=float), axis=0)
    return {"valid": True, "hit": bool(abs(x - target[0]) <= CHECK_REGION_HALF and abs(y - target[1]) <= CHECK_REGION_HALF),
            "point": (float(x), float(y))}


def summarize_check(trials: list[dict]) -> str:
    """Plain outcome only: "good", "weak" or "insufficient". Never a score."""
    if sum(t["hit"] for t in trials) >= CHECK_PASS_TRIALS:
        return "good"
    return "weak" if sum(t["valid"] for t in trials) >= CHECK_ENOUGH_TRIALS else "insufficient"


def check_map(trials: list[dict], targets: list[tuple[float, float]], screen: dict, viewport: dict) -> list[dict]:
    """Display-only result: coarse landings per check place, built once and never kept.

    A hit is an offset inside the acceptance area; a miss is where it landed in this
    window. Anything missing, or outside the window, has no position: it is still a miss.
    """
    places = [{"x": x, "y": y, "trials": []} for x, y in CHECK_POINTS]
    order = [i for pass_order in CHECK_ORDERS for i in pass_order]
    for place, trial, target in zip(order, trials, targets):
        mark: dict = {"hit": trial["hit"]}
        if trial["hit"]:
            mark |= {"dx": round((trial["point"][0] - target[0]) / CHECK_REGION_HALF * _HIT_STEPS) / _HIT_STEPS,
                     "dy": round((trial["point"][1] - target[1]) / CHECK_REGION_HALF * _HIT_STEPS) / _HIT_STEPS}
        elif trial["valid"]:
            x = (trial["point"][0] * screen["width"] + screen["left"] - viewport["left"]) / viewport["width"]
            y = (trial["point"][1] * screen["height"] + screen["top"] - viewport["top"]) / viewport["height"]
            if 0 <= x <= 1 and 0 <= y <= 1:
                mark |= {"x": round(x * _MAP_CELLS) / _MAP_CELLS, "y": round(y * _MAP_CELLS) / _MAP_CELLS}
        places[place]["trials"].append(mark)
    return places


def screen_to_viewport(point: ScreenPoint, geometry: dict, screen: dict, sigma_px: float = 120.) -> dict | str:
    """Map desktop logical pixels to page CSS pixels, including browser zoom.

    The viewport origin is measured from a trusted mouse event, not guessed from
    outerHeight-innerHeight (which fails with side panels, DevTools and zoom).
    A new tab/changed chrome needs one pointer movement to measure that origin.
    """
    if geometry.get("drop_reason"):
        return geometry["drop_reason"]
    try:
        values = [point.x, point.y, point.t, sigma_px] + [float(geometry[k]) for k in
                  ("origin_x", "origin_y", "dpr", "width", "height", "scroll_x", "scroll_y")]
        if not all(math.isfinite(v) for v in values) or sigma_px <= 0:
            return "invalid_geometry"
        if any(abs(float(geometry[k]) - float(screen[k])) > 1 for k in ("screen_width", "screen_height")):
            return "wrong_display"
        if geometry["screen_left"] != screen["screen_left"] or geometry["screen_top"] != screen["screen_top"]:
            return "wrong_display"
        zoom = geometry["dpr"] / screen["dpr"]
        if zoom <= 0:
            return "invalid_geometry"
        x, y = (point.x - geometry["origin_x"]) / zoom, (point.y - geometry["origin_y"]) / zoom
        if not (0 <= x < geometry["width"] and 0 <= y < geometry["height"]):
            return "outside_page"
        return {"x_vp": x, "y_vp": y, "x_doc": x + geometry["scroll_x"], "y_doc": y + geometry["scroll_y"],
                "t": point.t, "t_start": point.t - .1, "duration_ms": 100., "sigma": sigma_px,
                "source": "webcam"}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return "invalid_geometry"
