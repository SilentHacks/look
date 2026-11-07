"""Local frame-exact evaluation through GazeEstimator; never opens a capture device.

Entry point: python -c 'import tests; from hermes_gaze.benchmark.gaze_eval import main; main()' ...
SciPy is optional and needed only to read MPIIFaceGaze's MATLAB geometry.
"""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
import hashlib
import importlib
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import zipfile

import numpy as np

from ..tracker.webcam_gaze import GazeEstimator, LandmarkEstimator
from ..webcam import WebcamHost

CACHE = Path.home() / ".cache" / "hermes-gaze-eval"
BROWSER = Path(__file__).resolve().parents[1] / "browser"


def private_directory(path: Path) -> Path:
    path = path.expanduser()
    if path.is_symlink():
        raise ValueError("Choose a real private directory, not a symlink")
    path = path.resolve()
    repo = Path(__file__).resolve().parents[1]
    if path == repo or repo in path.parents:
        raise ValueError("Evaluation data must stay outside the repository")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("Choose a private directory (mode 0700)")
    return path


def save_json(path: Path, value) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        json.dump(value, f, allow_nan=False, indent=2)
    try:
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def screen(width, height, **extra):
    return dict(left=0, top=0, width=float(width), height=float(height), dpr=1,
                screen_width=float(width), screen_height=float(height), screen_left=0, screen_top=0, **extra)


def load_mpiiface(archive: Path, out: Path, people: list[str], limit: int, days: int = 0, per_day: int = 100) -> dict:
    """Preserve original pixels, day ordering, true targets and calibrated screen plane."""
    from scipy.io import loadmat
    from scipy.spatial.transform import Rotation
    out = private_directory(out)
    sessions = []
    with zipfile.ZipFile(archive) as z:
        for person in people:
            prefix = f"MPIIFaceGaze/{person}/"
            size = loadmat(io.BytesIO(z.read(prefix + "Calibration/screenSize.mat")), squeeze_me=True)
            pose = loadmat(io.BytesIO(z.read(prefix + "Calibration/monitorPose.mat")), squeeze_me=True)
            geometry = screen(size["width_pixel"], size["height_pixel"],
                              width_mm=float(size["width_mm"]), height_mm=float(size["height_mm"]),
                              rotation=Rotation.from_rotvec(np.ravel(pose.get("rvecs", pose.get("rvects")))).as_matrix().tolist(),
                              translation=np.ravel(pose["tvecs"]).tolist())
            rows = [line.split() for line in z.read(prefix + person + ".txt").decode().splitlines() if line.strip()]
            rows.sort(key=lambda r: (int(r[0].split("/")[0][3:]), int(Path(r[0]).stem)))
            # Sample by acquisition order, not gaze/appearance; no test-dependent selection.
            chosen = np.linspace(0, len(rows) - 1, min(limit, len(rows)), dtype=int)
            if days:
                by_day = defaultdict(list)
                for i, r in enumerate(rows):
                    by_day[r[0].split("/")[0]].append(i)
                # Label/face-blind first/middle/last eligible days; enough early frames for 25 points.
                eligible = [indices for indices in by_day.values() if len(indices) >= 80]
                if len(eligible) < days:
                    raise ValueError(f"{person}: fewer than {days} days with at least 80 images")
                chosen = [i for j in np.linspace(0, len(eligible) - 1, days, dtype=int)
                          for i in np.asarray(eligible[j])[np.linspace(0, len(eligible[j]) - 1,
                                                                     min(per_day, len(eligible[j])), dtype=int)]]
            frames = []
            for index in chosen:
                r = rows[index]
                name = r[0]
                day = int(name.split("/")[0][3:])
                dest = out / f"{person}-{name.replace('/', '-')}"
                if not dest.exists():
                    with dest.open("xb") as f:
                        dest.chmod(0o600); f.write(z.read(prefix + name))
                frames.append(dict(path=str(dest), t=float(day), order=int(index), target=[float(r[1]), float(r[2])],
                                   eye_origin=[float(v) for v in r[21:24]], phase="unassigned"))
            sessions.append(dict(person=person, session="mpii-" + person, screen=geometry,
                                 temporal=False, clock="acquisition day; intra-day order only", frames=frames))
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    result = dict(version=1, dataset="MPIIFaceGaze", licence="CC BY-NC-SA 4.0; internal research evaluation only",
                  source_sha256=digest, sampling=dict(days=days, per_day=per_day, limit=limit), sessions=sessions)
    save_json(out / "manifest.json", result)
    return result


def load_recording(directory: Path, out: Path, stride: int = 3) -> dict:
    """Decode the retained camera video; match real decoder PTS to recorded targets."""
    meta = json.loads((directory / "recording.json").read_text())
    if not meta.get("finished"):
        raise ValueError("Recording was not finalized; keep the raw files for recovery")
    targets = [json.loads(line) for line in (directory / "targets.jsonl").read_text().splitlines()]
    if not targets:
        raise ValueError("Recording has no target timestamps")
    out = private_directory(out)
    video = directory / "camera.webm"
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                            "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(video)],
                           check=True, capture_output=True, text=True)
    pts = [float(f["best_effort_timestamp_time"]) for f in json.loads(probe.stdout)["frames"]]
    if not pts:
        raise ValueError("Recording has no decodable camera frames")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"select=not(mod(n\\,{stride}))",
                    "-vsync", "0", "-y", str(out / "frame-%06d.png")], check=True, capture_output=True, umask=0o077)
    times = np.array([r["t"] for r in targets])
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Target timestamps must be finite and increasing")
    frames = []
    for i, timestamp in enumerate(pts[::stride]):
        t = timestamp - pts[0]
        # Last displayed target, never a future target across a target transition.
        at = int(np.searchsorted(times, t, side="right") - 1)
        if at < 0 or t - times[at] > .25:
            continue
        row = targets[at]
        if row.get("settling"):
            continue
        path = out / f"frame-{i + 1:06d}.png"
        path.chmod(0o600)
        frames.append(dict(path=str(path), t=meta["epoch"] + t, video_t=t, target=row["target"], phase=row["phase"]))
    result = dict(version=1, dataset="personal-fake" if meta["fake_camera"] else "personal",
                  licence="Private local recording; no upload", sessions=[dict(person=meta["person"],
                  session=meta["session"], start_epoch=meta["epoch"], screen=meta["screen"], temporal=True,
                  clock="video PTS aligned to MediaRecorder start (within one camera frame)", frames=frames)])
    save_json(out / "manifest.json", result)
    return result


class FrameExtractor:
    """Same pinned WASM, model, features and VIDEO mode; step every selected frame exactly once."""
    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hermes-gaze-offline-")
        self.host = WebcamHost(lambda *_: False, profile_path=Path(self.tmp.name) / "unused.json",
                               runtime_source=BROWSER / "gaze_eval.js")
        try:
            state = self.host.start()
            if state["state"] != "running":
                raise RuntimeError(state["error"])
            from websockets.sync.client import connect
            with urllib.request.urlopen(self.host.http_url + "/json/list", timeout=3) as r:
                tab = next(t for t in json.load(r) if t["id"] == self.host.target_id)
            self.ws = connect(tab["webSocketDebuggerUrl"], max_size=16 * 1024 * 1024)
            self.seq = 0
            self.call("Performance.enable", {"timeDomain": "threadTicks"})
            return self
        except Exception:
            self.host.stop(); self.tmp.cleanup(); raise

    def call(self, method, params):
        self.seq += 1
        self.ws.send(json.dumps(dict(id=self.seq, method=method, params=params)))
        while True:
            r = json.loads(self.ws.recv(timeout=60))
            if r.get("id") == self.seq:
                if "error" in r:
                    raise RuntimeError(r["error"])
                return r["result"]

    def cpu(self):
        metrics = self.call("Performance.getMetrics", {})["metrics"]
        return next(m["value"] for m in metrics if m["name"] == "ThreadTime")

    def extract(self, path: Path, t: float, discontinuous: bool):
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        src = "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode()
        before = self.cpu()
        expression = "globalThis.__HERMES_EVAL__.extract(" + json.dumps(src) + f",{t},{str(discontinuous).lower()})"
        r = self.call("Runtime.evaluate", dict(expression=expression, contextId=self.host._context,
                                               awaitPromise=True, returnByValue=True))
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"])
        value = r["result"]["value"]
        value["extract_cpu_ms"] = (self.cpu() - before) * 1000
        return value

    def __exit__(self, *_):
        self.ws.close(); self.host.stop(); self.tmp.cleanup()


def extract_manifest(data: dict) -> dict:
    with FrameExtractor() as runtime:
        for session in data["sessions"]:
            for i, frame in enumerate(session["frames"]):
                # Video keeps its true cadence; unrelated stills reset the temporal face track.
                timestamp = (frame["t"] - session["frames"][0]["t"]) * 1000 + 1 if session["temporal"] else (i + 1) * 100.
                frame.update(runtime.extract(Path(frame["path"]), timestamp, not session["temporal"] or i == 0))
    data["extractor"] = dict(model="mediapipe-face-v2-iris-ridge-1",
                             feature_sha256=hashlib.sha256((BROWSER / "webcam_features.js").read_bytes()).hexdigest(),
                             offline_sha256=hashlib.sha256((BROWSER / "gaze_eval.js").read_bytes()).hexdigest())
    return data


class EvalRidge(LandmarkEstimator):
    """Shipped predictor/standardization/solver; offline calibration accepts arbitrary target counts.

    Live UI guards (45 frames, exactly nine targets, fit rejection) cannot apply to
    sparse public stills. Never saves a profile into the live tracker's location.
    """
    def __init__(self, ridge=1.):
        super().__init__()
        self.ridge = ridge

    def calibrate(self, observations, geometry):
        x = np.asarray([r[0] for r in observations], dtype=float)
        y = np.asarray([[r[1], r[2]] for r in observations], dtype=float)
        if x.shape != (len(x), self.feature_count) or len(x) < 3 or not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("Insufficient finite calibration observations")
        mean, scale = x.mean(axis=0), np.maximum(x.std(axis=0), .001)
        a = np.column_stack((np.ones(len(x)), (x - mean) / scale))
        penalty = np.eye(self.feature_count + 1) * self.ridge; penalty[0, 0] = 0
        weights = np.linalg.solve(a.T @ a + penalty, a.T @ y)
        profile = dict(model_id=self.model_id, mean=mean.tolist(), scale=scale.tolist(), weights=weights.tolist(),
                       screen=geometry, fit_error=float(np.sqrt(np.mean((a @ weights - y) ** 2))))
        self.load(profile)
        return profile


def split_frames(sessions: list[dict], points: int, protocol: str = "cross-day"):
    """Freeze chronology before face filtering; never select calibration from test labels."""
    ordered = [(s, f) for s in sessions for f in s["frames"]]
    if all(f["phase"] == "unassigned" for _, f in ordered):
        ordered.sort(key=lambda row: (row[1]["t"], row[1].get("order", 0)))
        if protocol == "same-session":
            if len(sessions) != 1 or len({f["t"] for _, f in ordered}) != 1:
                raise ValueError("Same-session stills require one acquisition day")
            cutoff = max(1, int(len(ordered) * .4))
            early, later = ordered[:cutoff], ordered[cutoff:]
        else:
            days = sorted({f["t"] for _, f in ordered})
            if len(days) < 2:
                raise ValueError("Need at least two acquisition days")
            cutoff = days[max(1, int(len(days) * .4)) - 1]
            early = [(s, f) for s, f in ordered if f["t"] <= cutoff]
            later = [(s, f) for s, f in ordered if f["t"] > cutoff]
    else:
        first = sessions[0]
        boundary = next((i for i, f in enumerate(first["frames"]) if f["phase"] != "calibration"), len(first["frames"]))
        early = [(first, f) for f in first["frames"][:boundary]]
        if protocol == "same-session":
            later = [(first, f) for f in first["frames"][boundary:]]
        else:
            later = [(s, f) for s in sessions[1:] for f in s["frames"] if f["phase"] != "calibration"]
    available = [(s, f) for s, f in early if f.get("features") is not None]
    groups = defaultdict(list)
    for s, f in available:
        groups[tuple(f["target"])].append((s, f))
    if len(groups) < points:
        raise ValueError(f"Only {len(groups)} valid early targets for {points}-point calibration")
    # Farthest-point selection on calibration coordinates only, normalized to screen size.
    keys = sorted(groups)
    g = available[0][0]["screen"]
    xy = np.asarray(keys) / [g["width"], g["height"]]
    chosen = [int(np.argmin(np.sum((xy - .5) ** 2, axis=1)))]
    while len(chosen) < points:
        distance = np.min(np.sum((xy[:, None] - xy[chosen]) ** 2, axis=2), axis=1)
        distance[chosen] = -1
        chosen.append(int(np.argmax(distance)))
    held_in = {keys[i] for i in chosen}
    calibration = [row for i in chosen for row in groups[keys[i]]]
    # Later repeats of calibration locations are explicitly not counted as unseen targets.
    test = [(s, f) for s, f in later if tuple(f["target"]) not in held_in]
    if not test:
        raise ValueError("No later, held-out targets")
    return calibration, test, len(early)


def angular_error(prediction, frame, geometry):
    if all(k in geometry for k in ("rotation", "translation", "width_mm", "height_mm")) and "eye_origin" in frame:
        def ray(xy):
            point = np.array([xy[0] / geometry["width"] * geometry["width_mm"],
                              xy[1] / geometry["height"] * geometry["height_mm"], 0.])
            v = np.asarray(geometry["rotation"]) @ point + geometry["translation"] - frame["eye_origin"]
            return v / np.linalg.norm(v)
    elif all(geometry.get(k, 0) > 0 for k in ("width_mm", "height_mm", "distance_mm")):
        def ray(xy):
            v = np.array([(xy[0] / geometry["width"] - .5) * geometry["width_mm"],
                          (xy[1] / geometry["height"] - .5) * geometry["height_mm"], geometry["distance_mm"]])
            return v / np.linalg.norm(v)
    else:
        return None
    return float(np.degrees(np.arccos(np.clip(np.dot(ray(prediction), ray(frame["target"])), -1, 1))))


def summarize(values):
    return {"mean": float(np.mean(values)), "median": float(np.median(values)), "p95": float(np.percentile(values, 95))} if values else None


def evaluate(data: dict, factory, name: str, points: int, protocol: str = "cross-day",
             feature_key: str = "features") -> tuple[list[dict], list[dict]]:
    if protocol not in ("same-session", "cross-day"):
        raise ValueError("Unknown evaluation protocol")
    people = defaultdict(list)
    for session in data["sessions"]:
        if protocol == "same-session" and all(f["phase"] == "unassigned" for f in session["frames"]):
            for day in sorted({f["t"] for f in session["frames"]}):
                window = {**session, "session": f"{session['session']}-day{day:g}",
                          "frames": [f for f in session["frames"] if f["t"] == day]}
                people[(session["person"], window["session"])].append(window)
        else:
            people[(session["person"], session["session"] if protocol == "same-session" else "all")].append(session)
    results, traces = [], []
    for (person, window), sessions in people.items():
        sessions.sort(key=lambda s: s.get("start_epoch", 0))
        row = dict(dataset=data["dataset"], person=person, session=window, protocol=protocol,
                   config=name, calibration_points=points)
        try:
            calibration, test, early_count = split_frames(sessions, points, protocol)
            model: GazeEstimator = factory()
            geometry = calibration[0][0]["screen"]
            if any(s["screen"] != geometry for s in sessions):
                raise ValueError("Screen changed within a person; evaluate geometry sessions separately")
            observations = [(f[feature_key], (f["target"][0] - geometry["left"]) / geometry["width"],
                             (f["target"][1] - geometry["top"]) / geometry["height"])
                            for _, f in calibration if f.get(feature_key) is not None]
            model.calibrate(observations, geometry)
            errors, angles, residuals, jitter, latency, cpu, extract_cpu = [], [], [], [], [], [], []
            hits = {2: 0, 3: 0, 4: 0, 5: 0}
            previous = None
            for s, frame in test:
                start, cpu_start = time.perf_counter(), time.thread_time()
                prediction = model.predict(frame[feature_key], frame["t"]) if frame.get(feature_key) is not None else None
                cpu.append((time.thread_time() - cpu_start) * 1000)
                inference = frame.get("appearance_inference_ms", frame.get("inference_ms", 0)) if feature_key == "appearance" else frame.get("inference_ms", 0)
                latency.append((time.perf_counter() - start) * 1000 + inference)
                extract_cpu.append(frame.get("extract_cpu_ms", 0))
                trace = dict(person=person, session=s["session"], t=frame["t"], temporal=s["temporal"],
                             target=frame["target"], screen=[geometry["width"], geometry["height"]], prediction=None,
                             protocol=protocol)
                if prediction is None:
                    traces.append(trace); previous = None; continue
                xy = [prediction.x, prediction.y]
                trace["prediction"] = xy; traces.append(trace)
                delta = np.asarray(xy) - frame["target"]
                errors.append(float(np.linalg.norm(delta)))
                angle = angular_error(xy, frame, geometry)
                if angle is not None:
                    angles.append(angle)
                residuals.append((frame["t"], delta, errors[-1]))
                for n in hits:
                    def cell(p):
                        return tuple(min(n - 1, math.floor((v - o) / size * n)) for v, o, size in
                                     zip(p, (geometry["left"], geometry["top"]), (geometry["width"], geometry["height"])))
                    hits[n] += cell(xy) == cell(frame["target"])
                if previous is not None and s["temporal"]:
                    prev_s, prev_f, prev_delta = previous
                    if s is prev_s and 0 < frame["t"] - prev_f["t"] <= .25 and frame["target"] == prev_f["target"]:
                        jitter.append(float(np.linalg.norm(delta - prev_delta) ** 2))
                previous = (s, frame, delta)
            third = max(1, len(residuals) // 3)
            drift = None
            if len(residuals) >= 6:
                drift = dict(first_third_mean_px=float(np.mean([r[2] for r in residuals[:third]])),
                             last_third_mean_px=float(np.mean([r[2] for r in residuals[-third:]])),
                             bias_shift_px=float(np.linalg.norm(np.mean([r[1] for r in residuals[-third:]], axis=0) -
                                                                np.mean([r[1] for r in residuals[:third]], axis=0))),
                             elapsed=residuals[-1][0] - residuals[0][0],
                             unit="seconds" if sessions[0]["temporal"] else "acquisition days")
            row.update(status="ok", calibration_frames=len(observations), early_frames=early_count,
                       calibration_targets_used=len({(r[1], r[2]) for r in observations}),
                       test_frames=len(test), predicted=len(errors), coverage=100 * len(errors) / len(test),
                       region_hit={str(n): 100 * hit / len(test) for n, hit in hits.items()},
                       error_px=summarize(errors), error_deg=summarize(angles), jitter_px=math.sqrt(np.mean(jitter)) if jitter else None,
                       drift=drift, latency_ms=summarize(latency), predict_cpu_ms=summarize(cpu),
                       extract_cpu_ms=summarize(extract_cpu))
        except ValueError as exc:
            row.update(status="unscorable", reason=str(exc))
        results.append(row)
    return results, traces


def scoreboard(rows):
    lines = ["# Offline gaze scoreboard", "", "Region hits include missing/off-screen predictions as misses. Errors are conditional on a prediction.",
             "Public results describe those participants and setups, not the user's laptop. Fake-camera results test plumbing only.", "",
             "| Dataset/person/session | Protocol | Configuration | Cal points/frames | Test/predicted | Coverage | 3×3 | 4×4 | 5×5 | px mean/median/p95 | degrees mean/median/p95 | jitter px | latency mean ms | CPU extract/predict ms | Drift first→last px |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    def stats(v):
        return "/".join(f"{v[k]:.2f}" for k in ("mean", "median", "p95")) if v else "N/A"
    for r in rows:
        if r["status"] != "ok":
            lines.append(f"| {r['dataset']}/{r['person']}/{r['session']} | {r['protocol']} | {r['config']} | {r['calibration_points']} | unscorable: {r['reason']} | — | — | — | — | — | — | — | — | — | — |")
            continue
        drift = r["drift"]
        drift_text = f"{drift['first_third_mean_px']:.1f}→{drift['last_third_mean_px']:.1f} ({drift['elapsed']:.1f} {drift['unit']})" if drift else "N/A"
        jitter = f"{r['jitter_px']:.2f}" if r['jitter_px'] is not None else "N/A"
        hits = " | ".join(f"{r['region_hit'][str(n)]:.1f}%" for n in (3, 4, 5))
        lines.append(f"| {r['dataset']}/{r['person']}/{r['session']} | {r['protocol']} | {r['config']} | {r['calibration_points']}/{r['calibration_frames']} | {r['test_frames']}/{r['predicted']} | {r['coverage']:.1f}% | {hits} | {stats(r['error_px'])} | {stats(r['error_deg'])} | {jitter} | {r['latency_ms']['mean']:.2f} | {r['extract_cpu_ms']['mean']:.2f}/{r['predict_cpu_ms']['mean']:.3f} | {drift_text} |")
    lines += ["", "Latency = WASM inference + Python predict wall time, excludes decoding, CDP and camera exposure.",
              "CPU = Chrome renderer thread CPU (includes image decode/model reset/CDP work) / Python prediction thread CPU.",
              "Jitter = RMS successive residual displacement on stationary targets ≤250 ms apart; still images: N/A.",
              "Drift is descriptive early/late error and bias shift, confounded by target/posture changes; not causal sensor drift.",
              "Baseline uses the shipped predictor and λ=1 solver; offline calibration relaxes live nine-target/45-frame/fit-rejection UI guards.",
              "No model profiles or public-data weights are shipped; live defaults are unchanged.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    mpii = subs.add_parser("mpiiface")
    mpii.add_argument("archive", type=Path)
    mpii.add_argument("--people", nargs="+", default=["p00", "p01", "p02"])
    mpii.add_argument("--limit", type=int, default=300)
    mpii.add_argument("--days", type=int, default=0, help="sample this many dense acquisition days instead of sparse whole-history sampling")
    mpii.add_argument("--per-day", type=int, default=100)
    mpii.add_argument("--out", type=Path, required=True)
    rec = subs.add_parser("recording")
    rec.add_argument("directory", type=Path)
    rec.add_argument("--stride", type=int, default=3)
    rec.add_argument("--out", type=Path, required=True)
    extract = subs.add_parser("extract")
    extract.add_argument("manifest", type=Path)
    extract.add_argument("--out", type=Path, required=True)
    score = subs.add_parser("score")
    score.add_argument("manifests", type=Path, nargs="+")
    score.add_argument("--points", type=int, nargs="+", default=[9, 16, 25])
    score.add_argument("--protocols", nargs="+", choices=["same-session", "cross-day"], default=["same-session", "cross-day"])
    score.add_argument("--estimator", help="optional trusted local module:factory implementing GazeEstimator")
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "mpiiface":
        if args.limit < 10:
            parser.error("--limit must be at least 10")
        if args.days < 0 or args.per_day < 80:
            parser.error("--days must be nonnegative and --per-day at least 80")
        load_mpiiface(args.archive, args.out, args.people, args.limit, args.days, args.per_day)
    elif args.command == "recording":
        if args.stride < 1:
            parser.error("--stride must be positive")
        load_recording(args.directory, args.out, args.stride)
    elif args.command == "extract":
        out = private_directory(args.out)
        data = extract_manifest(json.loads(args.manifest.read_text()))
        save_json(out / "features.json", data)
    else:
        if min(args.points) < 3:
            parser.error("--points must be at least three")
        out = private_directory(args.out)
        configs = [("baseline-ridge1", EvalRidge), ("ridge10", lambda: EvalRidge(10.))]
        if args.estimator:
            module, factory = args.estimator.split(":")
            configs.append((args.estimator, getattr(importlib.import_module(module), factory)))
        rows = []
        for manifest in args.manifests:
            data = json.loads(manifest.read_text())
            for name, factory in configs:
                for points in args.points:
                    for protocol in args.protocols:
                        scored, traces = evaluate(data, factory, name, points, protocol)
                        rows.extend(scored)
                        save_json(out / f"{manifest.parent.name}-{name.replace(':', '-')}-{points}-{protocol}-trace.json", dict(version=1, samples=traces))
        save_json(out / "results.json", rows)
        (out / "SCOREBOARD.md").write_text(scoreboard(rows)); (out / "SCOREBOARD.md").chmod(0o600)
        print(scoreboard(rows))


if __name__ == "__main__":
    main()
