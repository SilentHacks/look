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

    def __init__(self) -> None:
        self.profile: dict | None = None

    def load(self, profile: dict) -> None:
        if profile.get("model_id") != self.model_id:
            raise ValueError("Calibration belongs to a different estimator")
        for key, shape in (("mean", (8,)), ("scale", (8,)), ("weights", (9, 2))):
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
        if x.shape != (len(observations), 8) or len(x) < 45 or not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("Not enough valid calibration samples; try again")
        if len(np.unique(y, axis=0)) != 9:
            raise ValueError("Calibration requires all nine targets")
        mean, scale = x.mean(axis=0), x.std(axis=0)
        if max(scale) < .001:
            raise ValueError("Eyes did not move enough during calibration; try again")
        scale = np.maximum(scale, .001)
        a = np.column_stack((np.ones(len(x)), (x - mean) / scale))
        penalty = np.eye(9); penalty[0, 0] = 0
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
        if x.shape != (8,) or not np.isfinite(x).all() or not math.isfinite(t):
            return None
        p = self.profile
        xy = self._weights[0] + ((x - self._mean) / self._scale) @ self._weights[1:]
        # Do not clamp an off-screen estimate onto an unrelated edge control.
        if not np.isfinite(xy).all() or not (0 <= xy[0] <= 1 and 0 <= xy[1] <= 1):
            return None
        s = p["screen"]
        return ScreenPoint(s["left"] + xy[0] * s["width"], s["top"] + xy[1] * s["height"], t)


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
