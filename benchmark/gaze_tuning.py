"""Offline candidates only. No live defaults, camera access or reusable gaze weights.

Run: python -c 'import tests, runpy; runpy.run_module("hermes_gaze.benchmark.gaze_tuning", run_name="__main__")' ...
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path

import numpy as np

from .gaze_eval import EvalRidge, evaluate, private_directory, save_json, scoreboard
from ..tracker.webcam_gaze import ScreenPoint


class Regression:
    """Small personal fits behind GazeEstimator; all scaling is calibration-only."""
    def __init__(self, ridge=10., kind="linear"):
        self.ridge, self.kind = ridge, kind
        self.model_id = f"eval-{kind}-{ridge:g}"
        self.feature_count = 0
        self.profile = None

    def design(self, x):
        z = (x - self.mean) / self.scale
        if self.kind == "poly2":
            a, b = np.triu_indices(z.shape[-1])
            z = np.concatenate((z, z[..., a] * z[..., b]), axis=-1)
        return z

    def calibrate(self, observations, screen):
        if len(observations) < 3:
            raise ValueError("Fewer than three valid selected calibration frames")
        x = np.asarray([r[0] for r in observations], dtype=float)
        y = np.asarray([r[1:] for r in observations], dtype=float)
        if x.ndim != 2 or not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("Nonfinite calibration")
        self.feature_count = x.shape[1]
        self.mean, self.scale = x.mean(axis=0), np.maximum(x.std(axis=0), .001)
        z = self.design(x)
        self.ymean = y.mean(axis=0)
        if self.kind == "rbf":
            self.support = z
            k = np.exp(-np.sum((z[:, None] - z) ** 2, axis=-1) / (2 * self.feature_count))
            self.weights = np.linalg.solve(k + self.ridge * np.eye(len(z)), y - self.ymean)
        else:
            self.weights = np.zeros((z.shape[1], 2))
            for axis in range(2):
                indices = [axis, axis + 2, 4, 5, 6, 7] if self.kind == "axes" else list(range(z.shape[1]))
                a = z[:, indices]
                # Dual solve keeps the frozen appearance embedding fit bounded by calibration count.
                w = a.T @ np.linalg.solve(a @ a.T + self.ridge * np.eye(len(a)), y[:, axis] - self.ymean[axis])
                self.weights[indices, axis] = w
        profile = dict(model_id=self.model_id, mean=self.mean.tolist(), scale=self.scale.tolist(),
                       ymean=self.ymean.tolist(), weights=self.weights.tolist(), screen=screen,
                       support=self.support.tolist() if self.kind == "rbf" else None)
        self.load(profile)
        return profile

    def load(self, profile):
        if profile["model_id"] != self.model_id:
            raise ValueError("Different evaluation model")
        self.profile = profile
        self.mean, self.scale, self.weights, self.ymean = (np.asarray(profile[k]) for k in ("mean", "scale", "weights", "ymean"))
        self.feature_count = len(self.mean)
        if self.kind == "rbf":
            self.support = np.asarray(profile["support"])

    def predict(self, features, t):
        x = np.asarray(features, dtype=float)
        if self.profile is None or x.shape != (self.feature_count,) or not np.isfinite(x).all() or not math.isfinite(t):
            return None
        z = self.design(x)
        if self.kind == "rbf":
            z = np.exp(-np.sum((self.support - z) ** 2, axis=-1) / (2 * self.feature_count))
        xy = self.ymean + z @ self.weights
        if not np.isfinite(xy).all() or not ((0 <= xy) & (xy <= 1)).all():
            return None
        s = self.profile["screen"]
        return ScreenPoint(s["left"] + xy[0] * s["width"], s["top"] + xy[1] * s["height"], t)


# Deliberately not a Cartesian grid. Each row asks one feature/model question.
CONFIGS = {
    "baseline-ridge1": ("baseline", lambda: EvalRidge(1.)),
    "ridge10": ("baseline", lambda: EvalRidge(10.)),
    "ridge100": ("baseline", lambda: EvalRidge(100.)),
    "eyes-only": ("eyes", Regression),
    "one-eye": ("one-eye", Regression),
    "head-local": ("pose", Regression),
    "openness-gate": ("gate", lambda: EvalRidge(10.)),
    "poly2": ("baseline", lambda: Regression(10., "poly2")),
    "rbf": ("baseline", lambda: Regression(.1, "rbf")),
    "per-axis": ("baseline", lambda: Regression(10., "axes")),
    "appearance": ("appearance", Regression),
}


def observations_for(data, representation):
    sessions = []
    for s in data["sessions"]:
        frames = []
        for f in s["frames"]:
            x = f.get("features")
            if representation == "eyes":
                x = x[:4] if x else None
            elif representation == "one-eye":
                x = x[:2] + x[4:] if x else None
            elif representation == "pose":
                x = f.get("pose_features") if x else None
            elif representation == "gate":
                if f.get("blink", 1.) > .4 or min(f.get("openness", [0.])) < .18:
                    x = None
            elif representation == "appearance":
                x = f.get("appearance") if x else None
            frames.append({**f, "observation": x})
        sessions.append({**s, "frames": frames})
    return {**data, "sessions": sessions}


def jitter_score(samples, mode):
    """Causal trace filters. Never bridge missing frames/gaps or consult target labels."""
    history, state, previous, last = deque(maxlen=3), None, None, None
    squared, valid, intervals = [], 0, []
    for sample in samples:
        if not sample["temporal"]:
            raise ValueError("Jitter needs video timestamps, not stills")
        p = sample["prediction"]
        dt = sample["t"] - last["t"] if last else 0
        continuous = last is not None and sample["session"] == last["session"] and 0 < dt <= .25
        if p is None or not continuous:
            history.clear(); state = previous = None
        last = sample
        if p is None:
            continue
        p = np.asarray(p, dtype=float)
        history.append(p)
        if mode == "median3-ema":
            p = np.median(np.asarray(history), axis=0)
        if mode != "raw" and state is not None:
            p = state + (1 - math.exp(-dt / .12)) * (p - state)
        state = p
        valid += 1
        # Labels enter only the metric, never the filter.
        residual = p - sample["target"]
        if previous is not None and previous[0] == sample["target"]:
            squared.append(float(np.sum((residual - previous[1]) ** 2)))
            intervals.append(dt)
        previous = (sample["target"], residual)
    return dict(filter=mode, predictions=valid, frames=len(samples), stationary_pairs=len(squared),
                jitter_px=math.sqrt(np.mean(squared)) if squared else None,
                nominal_ema_time_constant_ms=0 if mode == "raw" else 120,
                median_delay_ms=1000 * float(np.median(intervals)) if intervals and mode == "median3-ema" else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--points", nargs="+", type=int, default=[9, 16, 25])
    parser.add_argument("--configs", nargs="+", choices=CONFIGS, default=list(CONFIGS))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--jitter-trace", type=Path, help="fake-camera trace; score filters for jitter only")
    args = parser.parse_args()
    if min(args.points) < 3:
        parser.error("Calibration needs at least three points")
    out = private_directory(args.out)
    data = json.loads(args.manifest.read_text())
    rows = []
    for name in args.configs:
        representation, factory = CONFIGS[name]
        prepared = observations_for(data, representation)
        for points in args.points:
            for protocol in ("same-session", "cross-day"):
                scored, trace = evaluate(prepared, factory, name, points, protocol,
                                         "appearance" if representation == "appearance" else "observation")
                rows.extend(scored)
                save_json(out / f"{name}-{points}-{protocol}-trace.json", dict(version=1, samples=trace))
    save_json(out / "results.json", rows)
    (out / "SCOREBOARD.md").write_text(scoreboard(rows))
    (out / "SCOREBOARD.md").chmod(0o600)
    if args.jitter_trace:
        trace = json.loads(args.jitter_trace.read_text())["samples"]
        save_json(out / "jitter.json", [jitter_score(trace, mode) for mode in ("raw", "ema", "median3-ema")])
    print(f"Saved {len(rows)} per-person/session rows to {out}")

if __name__ == "__main__":
    main()
