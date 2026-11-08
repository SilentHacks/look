"""Feature-only estimator research. Never extracts images, opens devices or installs fits.

Select on fixed/moving/reading; freeze choices before reporting validation-end.
Run: scripts/gaze.py research FEATURES --out PRIVATE_DIR --stage select|report
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from .gaze_eval import EvalRidge, evaluation_pairs, private_directory, save_json, split_frames, summarize
from .gaze_tuning import Regression


@dataclass(frozen=True)
class Candidate:
    representation: str = "baseline"
    ridge: float = 1.
    kind: str = "linear"
    robust: bool = False
    gate: str = "none"
    ema: float = 0.
    tolerance: float = 0.
    bias_points: int = 0

    @property
    def name(self):
        return (f"{self.representation}-{self.kind}-r{self.ridge:g}"
                f"{'-huber' if self.robust else ''}-{self.gate}"
                f"-ema{self.ema:g}-edge{self.tolerance:g}-bias{self.bias_points}")


def observation(frame, candidate):
    x = frame.get("features")
    if x is None:
        return None
    if candidate.gate != "none":
        blink, opening = (.4, .18) if candidate.gate == "tight" else (.65, .10)
        if frame.get("blink", 1.) > blink or min(frame.get("openness", [0.])) < opening:
            return None
    rep = candidate.representation
    if rep == "eyes":
        x = x[:4]
    elif rep == "left":
        x = x[:2]
    elif rep == "right":
        x = x[2:4]
    elif rep == "mean-eye":
        x = [(x[0] + x[2]) / 2, (x[1] + x[3]) / 2]
    elif rep in ("pose", "pose-eyes"):
        x = frame.get("pose_features")
        if x is not None and rep == "pose-eyes":
            x = x[:4]
    elif rep.startswith("appearance"):
        x = frame.get("appearance")
        if x is not None:
            if rep == "appearance-eyes":
                x = x[:256] + x[-8:-4]
            elif rep == "appearance-left":
                x = x[:128] + x[-8:-6]
            elif rep == "appearance-right":
                x = x[128:256] + x[-6:-4]
    if x is None:
        return None
    x = np.asarray(x, dtype=float)
    return x if x.ndim == 1 and np.isfinite(x).all() else None


class Fit(Regression):
    """Existing calibration standardization/design, with optional Huber reweighting.

    Raw coordinates stay available for labelled bias correction BEFORE screen gating.
    No profile is persisted; these models cannot be loaded into the live tracker.
    """
    def __init__(self, candidate):
        super().__init__(candidate.ridge, candidate.kind)
        self.candidate = candidate

    def calibrate(self, observations, screen):
        if self.candidate == Candidate():
            baseline = EvalRidge()
            baseline.calibrate(observations, screen)
            self.raw = lambda x: baseline._weights[0] + ((x - baseline._mean) / baseline._scale) @ baseline._weights[1:]
            return
        if len(observations) < 45:
            raise ValueError("Need 45 finite selected calibration observations")
        x = np.asarray([r[0] for r in observations])
        y = np.asarray([r[1:] for r in observations])
        if len(np.unique(y, axis=0)) < 3 or max(x.std(axis=0)) < .001:
            raise ValueError("Insufficient calibration targets or movement")
        self.feature_count = x.shape[1]
        self.mean, self.scale = x.mean(axis=0), np.maximum(x.std(axis=0), .001)
        z = self.design(x)
        self.support = z
        if self.kind == "rbf":
            z = np.exp(-np.sum((z[:, None] - z) ** 2, axis=-1) / (2 * self.feature_count))
        weights = np.ones(len(x))
        for _ in range(5 if self.candidate.robust else 1):
            self.ymean = np.average(y, axis=0, weights=weights)
            self.zmean = np.average(z, axis=0, weights=weights)
            a = (z - self.zmean) * np.sqrt(weights[:, None])
            b = (y - self.ymean) * np.sqrt(weights[:, None])
            if a.shape[1] <= len(a):
                self.weights = np.linalg.solve(a.T @ a + self.ridge * np.eye(a.shape[1]), a.T @ b)
            else:
                self.weights = a.T @ np.linalg.solve(a @ a.T + self.ridge * np.eye(len(a)), b)
            residual = np.linalg.norm(self.ymean + (z - self.zmean) @ self.weights - y, axis=1)
            weights = np.minimum(1., .08 / np.maximum(residual, 1e-9))
        if np.sqrt(np.mean((self.ymean + (z - self.zmean) @ self.weights - y) ** 2)) > .20:
            raise ValueError("Calibration did not fit targets")

    def raw(self, x):
        z = self.design(x)
        if self.kind == "rbf":
            z = np.exp(-np.sum((self.support - z) ** 2, axis=-1) / (2 * self.feature_count))
        return self.ymean + (z - self.zmean) @ self.weights


class Filter:
    """Causal EMA; missing frames and >250ms gaps reset, never fill abstentions."""
    def __init__(self, tau):
        self.tau, self.last, self.value = tau, None, None

    def apply(self, value, t):
        continuous = self.last is not None and 0 < t - self.last <= .25
        if value is None:
            self.value = None
        elif self.value is None or not continuous or not self.tau:
            self.value = value
        else:
            self.value = self.value + (1 - math.exp(-(t - self.last) / self.tau)) * (value - self.value)
        self.last = t
        return self.value


def selected_targets(frames, points, size):
    keys = sorted({tuple(f["target"]) for f in frames})
    if len(keys) < points:
        raise ValueError("Not enough labelled correction targets")
    xy = np.asarray(keys) / size
    chosen = [int(np.argmin(np.sum((xy - .5) ** 2, axis=1)))]
    while len(chosen) < points:
        d = np.min(np.sum((xy[:, None] - xy[chosen]) ** 2, axis=-1), axis=1)
        d[chosen] = -1
        chosen.append(int(np.argmax(d)))
    return {keys[i] for i in chosen}


def correction(model, frames, candidate, size, origin):
    if not candidate.bias_points:
        return np.zeros(2), 0
    start = [f for f in frames if f["phase"] == "validation-start"]
    chosen = selected_targets(start, candidate.bias_points, size)
    residuals = defaultdict(list)
    for f in start:
        if tuple(f["target"]) not in chosen:
            continue
        x = observation(f, candidate)
        if x is not None:
            raw = model.raw(x)
            if np.isfinite(raw).all():
                residuals[tuple(f["target"])].append((np.asarray(f["target"]) - origin) / size - raw)
    if len(residuals) != len(chosen):
        raise ValueError("Missing a selected correction target")
    # Equal target weight; more dwell at one target must not dominate the shift.
    return np.median([np.median(v, axis=0) for v in residuals.values()], axis=0), sum(map(len, residuals.values()))


def run(candidate, points, source, target, phases):
    """One fit/target pair; only aggregate metrics escape this function."""
    row = dict(config=candidate.name, candidate=asdict(candidate), points=points,
               session=target["session"], source=source["session"] if source else None,
               glasses=target["glasses"], condition=target["condition"])
    if source is None:
        return {**row, "status": "unscorable", "reason": "No compatible earlier calibration"}
    s = source["screen"]
    size, origin = np.array([s["width"], s["height"]]), np.array([s["left"], s["top"]])
    train, _, _ = split_frames([source], points)
    repeated = {tuple(f["target"]) for _, f in train}
    frames = [f for f in target["frames"] if f["phase"] in phases
              and ("validation-end" in phases or tuple(f["target"]) not in repeated)]
    row["frames"] = len(frames)
    try:
        observations = [(x, *((np.asarray(f["target"]) - origin) / size))
                        for _, f in train if (x := observation(f, candidate)) is not None]
        model = Fit(candidate)
        fit_start = time.thread_time()
        model.calibrate(observations, s)
        bias, correction_frames = correction(model, target["frames"], candidate, size, origin)
        row.update(calibration_frames=len(observations), correction_frames=correction_frames,
                   fit_cpu_ms=1000 * (time.thread_time() - fit_start))
        filt = Filter(candidate.ema)
        errors, jitter, cpu, wall, inference, extraction, intervals = [], [], [], [], [], [], []
        hits, previous, offscreen, missing, pairs = {str(n): 0 for n in (3, 4, 5)}, None, 0, 0, 0
        for f in frames:
            t0, c0 = time.perf_counter(), time.thread_time()
            x = observation(f, candidate)
            raw = model.raw(x) + bias if x is not None else None
            if raw is None or not np.isfinite(raw).all():
                xy = None; missing += 1
            elif np.any(raw < -candidate.tolerance) or np.any(raw > 1 + candidate.tolerance):
                xy = None; offscreen += 1
            else:
                # Offline edge-tolerance experiment only. Never returned as action authority.
                xy = origin + np.clip(raw, 0., 1.) * size
            xy = filt.apply(xy, f["t"])
            cpu.append(1000 * (time.thread_time() - c0))
            wall.append(1000 * (time.perf_counter() - t0))
            inference.append(f.get("appearance_inference_ms", f.get("inference_ms", 0))
                             if candidate.representation.startswith("appearance") else f.get("inference_ms", 0))
            extraction.append(f.get("extract_cpu_ms", 0))
            if xy is None:
                previous = None
                continue
            delta = xy - f["target"]
            errors.append(float(np.linalg.norm(delta)))
            for n in (3, 4, 5):
                a = np.minimum(n - 1, np.floor((xy - origin) / size * n))
                b = np.minimum(n - 1, np.floor((np.asarray(f["target"]) - origin) / size * n))
                hits[str(n)] += int(np.array_equal(a, b))
            if previous is not None and 0 < f["t"] - previous["t"] <= .25:
                intervals.append(f["t"] - previous["t"])
                if f["target"] == previous["target"]:
                    jitter.append(float(np.sum((delta - previous["delta"]) ** 2))); pairs += 1
            previous = dict(t=f["t"], target=f["target"], delta=delta)
        row.update(status="ok", predicted=len(errors), coverage=100 * len(errors) / len(frames) if frames else 0,
                   region_hit={n: 100 * h / len(frames) if frames else 0 for n, h in hits.items()},
                   error_px=summarize(errors), jitter_px=math.sqrt(np.mean(jitter)) if jitter else None,
                   stationary_pairs=pairs, offscreen=offscreen, missing_or_gated=missing,
                   predict_cpu_ms=summarize(cpu), predict_wall_ms=summarize(wall),
                   saved_inference_ms=summarize(inference), saved_extract_cpu_ms=summarize(extraction),
                   ema_tau_ms=1000 * candidate.ema,
                   ema_discrete_delay_ms=(1000 * np.median(intervals) / math.expm1(np.median(intervals) / candidate.ema)
                                          if intervals and candidate.ema else 0.))
    except (ValueError, np.linalg.LinAlgError) as exc:
        row.update(status="unscorable", reason=str(exc), predicted=0, coverage=0., region_hit={str(n): 0. for n in (3, 4, 5)})
    return row


def objective(rows):
    # Equal-session/region weighting. Abstentions and failed fits are zero hits.
    return float(np.mean([sum(r.get("region_hit", {}).get(str(n), 0.) for n in (3, 4, 5)) / 3 for r in rows]))


def initial_candidates():
    candidates = [Candidate(rep, ridge) for rep in
                  ("baseline", "eyes", "left", "right", "mean-eye", "pose", "pose-eyes",
                   "appearance", "appearance-eyes", "appearance-left", "appearance-right")
                  for ridge in (.1, 1., 10., 100., 1000.)]
    candidates += [Candidate(rep, r, kind) for rep in ("baseline", "eyes", "pose-eyes")
                   for r in (1., 10., 100.) for kind in ("poly2", "rbf")]
    return candidates


def select(data, out):
    """Finite, two-rung search; validation-end is removed before any search work."""
    development = {**data, "sessions": [{**s, "frames": [f for f in s["frames"] if f["phase"] != "validation-end"]}
                                        for s in data["sessions"]]}
    all_rows, choices = [], []
    for protocol in ("same-session", "cross-condition"):
        pairs = [(a, b) for a, b in evaluation_pairs(development, protocol) if a is not None
                 and (protocol != "same-session" or a is b)]
        for points in (9, 16, 25):
            scores = {}
            def score(c):
                if c not in scores:
                    result = [dict(run(c, points, a, b, {"fixed", "moving", "reading"}), protocol=protocol) for a, b in pairs]
                    scores[c] = result
                    all_rows.extend(result)
                return scores[c]
            pool = initial_candidates()
            for c in pool:
                score(c)
            # Eyewear-specific selection costs no new fitted cross-session weights.
            for glasses in ("all", "none", "glasses"):
                def relevant(rows):
                    return [r for r in rows if glasses == "all" or r["glasses"] == glasses]
                leaders = sorted(pool, key=lambda c: -objective(relevant(score(c))))[:3]
                neighbors = list(leaders)
                for c in leaders:
                    neighbors += [replace(c, robust=True), replace(c, gate="loose"), replace(c, gate="tight")]
                    neighbors += [replace(c, ema=t) for t in (.06, .12, .24)]
                    neighbors += [replace(c, tolerance=t) for t in (.02, .05, .1)]
                    if protocol == "cross-condition":
                        neighbors += [replace(c, bias_points=n) for n in (1, 3, 5)]
                for c in neighbors:
                    score(c)
                best = max(neighbors, key=lambda c: objective(relevant(score(c))))
                # Final rung combines the winning estimator with independent filter/edge/bias knobs.
                combined = [replace(best, ema=e, tolerance=t, bias_points=b)
                            for e in (0., .12) for t in (0., .05)
                            for b in ((0, 1, 3, 5) if protocol == "cross-condition" else (0,))]
                for c in combined:
                    score(c)
                best = max(neighbors + combined, key=lambda c: objective(relevant(score(c))))
                choices.append(dict(protocol=protocol, points=points, glasses=glasses,
                                    candidate=asdict(best), development_score=objective(relevant(score(best)))))
    save_json(out / "development.json", all_rows)
    save_json(out / "selection.json", dict(version=1, separation="fixed/moving/reading selection; validation-end final only",
                                           choices=choices, development_rows=len(all_rows)))
    print(f"Frozen {len(choices)} choices from {len(all_rows)} development rows; final validation not scored")


def aggregate(rows):
    """Equal-session headline; per-session p95 range avoids pretending quantiles pool."""
    ok = [r for r in rows if r["status"] == "ok"]
    def mean(key):
        values = [r[key] for r in ok if r.get(key) is not None]
        return float(np.mean(values)) if values else None
    errors = [r["error_px"] for r in ok if r.get("error_px")]
    return dict(sessions=len(rows), scorable=len(ok), frames=sum(r.get("frames", 0) for r in rows),
                coverage=mean("coverage"), region_hit={str(n): float(np.mean([r.get("region_hit", {}).get(str(n), 0.) for r in rows])) for n in (3, 4, 5)},
                error_mean_px=float(np.mean([e["mean"] for e in errors])) if errors else None,
                session_p95_mean_px=float(np.mean([e["p95"] for e in errors])) if errors else None,
                session_p95_range_px=[min(e["p95"] for e in errors), max(e["p95"] for e in errors)] if errors else None,
                jitter_px=mean("jitter_px"), hit3_session_range=[min(r.get("region_hit", {}).get("3", 0.) for r in rows),
                                                               max(r.get("region_hit", {}).get("3", 0.) for r in rows)],
                predict_cpu_ms=float(np.mean([r["predict_cpu_ms"]["mean"] for r in ok if r.get("predict_cpu_ms")])) if ok else None)


def report(data, selection, out):
    rows = []
    for protocol in ("same-session", "cross-condition"):
        pairs = [(a, b) for a, b in evaluation_pairs(data, protocol) if a is not None
                 and (protocol != "same-session" or a is b)]
        for points in (9, 16, 25):
            choices = [c for c in selection["choices"] if c["protocol"] == protocol and c["points"] == points]
            for source, target in pairs:
                configs = {"baseline": Candidate()}
                for choice in choices:
                    if choice["glasses"] in ("all", target["glasses"]):
                        key = "global-selected" if choice["glasses"] == "all" else "eyewear-selected"
                        configs[key] = Candidate(**choice["candidate"])
                for label, c in configs.items():
                    rows.append(dict(run(c, points, source, target, {"validation-end"}), protocol=protocol, label=label))
    save_json(out / "final.json", rows)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["protocol"], row["glasses"], row["points"], row["label"])].append(row)
    summary = [dict(protocol=p, glasses=g, points=n, label=l, **aggregate(v)) for (p, g, n, l), v in groups.items()]
    save_json(out / "final-summary.json", summary)
    lines = ["# Reserved end-validation results", "",
             "Equal-session means; pixel errors conditional on prediction. Session p95 means are NOT pooled p95.",
             "No end-validation frames were used for model selection. Start-validation is labelled bias-refresh input only.", "",
             "| Protocol | Eyewear | Points | Candidate | Sessions | 3×3 | 4×4 | 5×5 | Coverage | px mean / mean session p95 | Jitter px | CPU ms |",
             "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    def number(x):
        return f"{x:.1f}" if x is not None else "N/A"
    for r in summary:
        hits = " | ".join(number(r["region_hit"][str(n)]) for n in (3, 4, 5))
        cpu = f"{r['predict_cpu_ms']:.3f}" if r['predict_cpu_ms'] is not None else "N/A"
        lines.append(f"| {r['protocol']} | {r['glasses']} | {r['points']} | {r['label']} | {r['sessions']} | {hits} | {number(r['coverage'])} | {number(r['error_mean_px'])} / {number(r['session_p95_mean_px'])} | {number(r['jitter_px'])} | {cpu} |")
    path = out / "FINAL.md"
    path.write_text("\n".join(lines) + "\n"); path.chmod(0o600)
    print(f"Reported {len(rows)} reserved-validation rows, {len(summary)} aggregate comparisons")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stage", choices=("select", "report"), required=True)
    args = parser.parse_args()
    out = private_directory(args.out)
    digest = hashlib.sha256(args.features.read_bytes()).hexdigest()
    data = json.loads(args.features.read_text())
    path = out / "selection.json"
    if args.stage == "select":
        if path.exists():
            parser.error("Selection already frozen; choose a new output directory")
        select(data, out)
        selection = json.loads(path.read_text())
        selection.update(features_sha256=digest, code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        save_json(path, selection)
    else:
        selection = json.loads(path.read_text())
        if selection["features_sha256"] != digest:
            parser.error("Features changed since selection")
        if selection["code_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            parser.error("Research code changed since selection; do not re-tune against final validation")
        report(data, selection, out)


if __name__ == "__main__":
    main()
