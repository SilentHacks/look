"""Owned Chrome camera process, nonce-bound observations and local-only calibration.

No HTTP listener. The tracker never attaches to the companion/user's Chrome.
Only this class's Popen process is closed. Importing this module opens no device.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import queue
import secrets
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request

from .tracker.webcam_gaze import (CHECK_OBSERVE_MS, CHECK_ORDERS, CHECK_POINTS, CHECK_SETTLE_MS, AppearanceEstimator,
                                  GazeEstimator, LandmarkEstimator, score_check_trial, summarize_check)

_ASSETS = {
    "tasks.tgz": ("https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-0.10.32.tgz",
                  "b362a2b56aafcce7857047c25dc8fd69612fd8e75018e264717d24290e7815c1"),
    "face_landmarker.task": ("https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
                             "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"),
}
_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_POINTS = [(x, y) for y in (.1, .5, .9) for x in (.1, .5, .9)]
_SCREEN_KEYS = ("left", "top", "width", "height", "screen_width", "screen_height", "screen_left", "screen_top", "dpr")
_WRONG_WINDOW = "Move this window fully onto one screen and try again."
_WRONG_DISPLAY = "Your calibration was made on a different screen. Recalibrate on this one."
_OLD_MODEL = "The gaze model changed. Please recalibrate with /gaze calibrate."
_OLD_MODEL_WINDOW = "The eye tracker was updated, so your old calibration no longer fits. Please recalibrate."
_BAD_PROFILE_WINDOW = "Your saved calibration could not be read. Please recalibrate."
_RECALIBRATE_NOTE = "Moved, changed glasses or adjusted the camera? Recalibrate."
_GOOD = "The estimate stayed in the same broad area most of the time. Small controls can still be wrong."
_WEAK = "The estimate missed several areas. Adjust your position or lighting and try again."
_INSUFFICIENT = "We could not collect enough gaze to check this. Make sure your face stays in view, then try again."
_KEPT = "Your earlier calibration has not changed."


def asset_directory() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hermes-gaze" / "webcam-0.10.32"


def prepare_assets(directory: Path | None = None) -> Path:
    """Official, version-pinned downloads; verify before unpacking and on each start."""
    directory = directory or asset_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, (url, expected) in _ASSETS.items():
        path = directory / name
        if not path.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(32 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Webcam asset checksum mismatch: " + name)
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as f:
                f.write(data); temporary = Path(f.name)
            os.replace(temporary, path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Webcam asset checksum mismatch: " + name)
    # Re-extract the verified bytes: modified cached JS/WASM must never execute.
    with tarfile.open(fileobj=io.BytesIO((directory / "tasks.tgz").read_bytes())) as archive:
        for member in archive.getmembers():
            if member.name in ("package/vision_bundle.mjs", "package/wasm/vision_wasm_internal.js",
                               "package/wasm/vision_wasm_internal.wasm", "package/wasm/vision_wasm_nosimd_internal.js",
                               "package/wasm/vision_wasm_nosimd_internal.wasm"):
                archive.extract(member, directory, filter="data")
    return directory


class WebcamHost:
    def __init__(self, on_point, *, estimator: GazeEstimator | None = None,
                 profile_path: Path | None = None, assets: Path | None = None,
                 fake_video: Path | None = None, runtime_source: Path | None = None,
                 runtime_options: dict | None = None, on_use_cursor=None, chrome_args: tuple[str, ...] = ()) -> None:
        self.estimator = estimator or AppearanceEstimator()
        self._feature_limits = getattr(self.estimator, "feature_limits", (4.,) * self.estimator.feature_count)
        self.on_point = on_point
        self.on_use_cursor = on_use_cursor
        self.chrome_args = tuple(chrome_args)
        self.profile_path = profile_path or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hermes-gaze" / "webcam-calibration.json"
        self.assets = assets
        self.fake_video = fake_video
        self.runtime_source = runtime_source or Path(__file__).parent / "browser" / "webcam_host.js"
        self.runtime_options = runtime_options or {}
        self.profile = None
        self._calibration_notice = ""
        self.error = ""
        self.state = "stopped"
        self.samples = self.predictions = self.delivered = self.hidden_samples = 0
        self.drops = dict.fromkeys((
            "stale_sample", "no_features", "uncalibrated", "calibrating", "offscreen", "prediction_rejected",
            "no_foreground_tab", "no_page_anchor", "viewport_changed", "unsupported_zoom",
            "wrong_display", "outside_page", "invalid_geometry", "page_mode_mismatch",
            "mode_changed", "rejected_by_page", "transport_error", "transport_timeout",
        ), 0)
        self.last_sample = 0.
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._start_lock = threading.Lock()
        self._commands: queue.Queue = queue.Queue()
        self._thread = self._process = self._ws = None
        self._nonce = ""
        self._context = None
        self._seq = 0
        self._calibration = None
        self._observations = []
        self._point_samples = []
        self._point_index = 0
        self._check = None  # In-memory held-out check; estimates are discarded after each result.
        self._practice = None

    def status(self) -> dict:
        return {"state": self.state, "calibrated": self.profile is not None, "samples": self.samples,
                "predictions": self.predictions, "delivered": self.delivered, "hidden_samples": self.hidden_samples,
                "drops": dict(self.drops),
                "sample_age_seconds": round(time.time() - self.last_sample, 2) if self.last_sample else None,
                "error": self.error, "model": self.estimator.model_id,
                "calibration_message": self._calibration_notice}

    def start(self) -> dict:
        with self._start_lock:
            return self._start()

    def _start(self) -> dict:
        if self._thread and self._thread.is_alive():
            return self.status()
        self._stop.clear(); self._ready.clear(); self.error = ""; self.state = "starting"
        self.last_sample = 0.
        self._clear_flow()
        try:
            self.assets = prepare_assets(self.assets)
        except (OSError, ValueError) as exc:
            self.state = "failed"; self.error = str(exc)
            return self.status()
        self.profile = None
        self._calibration_notice = ""
        try:
            if self.profile_path.exists():
                if self.profile_path.stat().st_size > 65536:
                    raise ValueError("Calibration file too large")
                profile = json.loads(self.profile_path.read_text())
                if not isinstance(profile, dict):
                    raise ValueError("Invalid calibration profile")
                if profile.get("model_id") != self.estimator.model_id:
                    self._calibration_notice = _OLD_MODEL
                    profile = None
                if profile is not None:
                    self.estimator.load(profile); self.profile = profile
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error = "Calibration could not be loaded; run /gaze calibrate"
        if self._stop.is_set():
            self.state = "stopped"
            return self.status()
        self._thread = threading.Thread(target=self._run, name="hermes-webcam", daemon=True)
        self._thread.start()
        self._ready.wait(25)
        return self.status()

    def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.send(json.dumps({"id": 0, "method": "Browser.close"}))
            except Exception:
                pass
        elif self._process is not None and self._process.poll() is None:
            self._process.terminate()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(12)
        self._clear_flow()
        self.state = "stopped"

    def calibrate(self) -> dict:
        status = self.start()
        if status["state"] in ("running", "failed"):  # A failed window explains why and offers a way out.
            self._commands.put(("Page.bringToFront", {}))
        return status

    def _send(self, method: str, params: dict) -> int:
        self._seq += 1
        self._ws.send(json.dumps({"id": self._seq, "method": method, "params": params}))
        return self._seq

    def _command(self, method: str, params: dict) -> dict:
        seq = self._send(method, params)
        while not self._stop.is_set():
            message = json.loads(self._ws.recv(timeout=20))
            if message.get("id") == seq:
                if message.get("error"):
                    raise RuntimeError(message["error"].get("message", "Tracker CDP failed"))
                return message.get("result", {})
            self._event(message)
        raise RuntimeError("Tracker stopped")

    def _ui(self, method: str, value="") -> None:
        self._send("Runtime.evaluate", {"expression": "globalThis.__HERMES_WEBCAM__?." + method + "(" + json.dumps(value) + ")",
                                       "contextId": self._context})

    def _clear_flow(self) -> None:
        self._calibration = self._check = self._practice = None
        self._observations = []; self._point_samples = []; self._point_index = 0

    def _measure(self, data: dict) -> tuple[dict, dict] | None:
        screen, viewport = data.get("screen", {}), data.get("viewport", {})
        if not all(isinstance(screen.get(k), (int, float)) and math.isfinite(screen[k]) for k in _SCREEN_KEYS):
            return None
        if min(screen[k] for k in ("width", "height", "dpr")) <= 0:
            return None
        if not all(isinstance(viewport.get(k), (int, float)) and math.isfinite(viewport[k])
                   for k in ("left", "top", "width", "height")) or min(viewport["width"], viewport["height"]) <= 0:
            return None
        return screen, viewport

    @staticmethod
    def _targets_on_screen(points, viewport: dict, screen: dict) -> list[tuple[float, float]] | None:
        targets = [((viewport["left"] + x * viewport["width"] - screen["left"]) / screen["width"],
                    (viewport["top"] + y * viewport["height"] - screen["top"]) / screen["height"]) for x, y in points]
        return None if any(not 0 <= v <= 1 for point in targets for v in point) else targets

    def _on_saved_display(self, screen: dict) -> bool:
        saved = self.profile["screen"]
        return all(abs(float(screen[k]) - float(saved[k])) <= 1 for k in ("screen_width", "screen_height", "screen_left", "screen_top"))

    def _begin_check(self, estimator, screen: dict, viewport: dict, candidate: dict | None) -> None:
        points = [CHECK_POINTS[i] for order in CHECK_ORDERS for i in order]
        targets = self._targets_on_screen(points, viewport, screen)
        if targets is None:
            self._clear_flow(); self._ui("notice", _WRONG_WINDOW); return
        self._calibration = None; self._observations = []
        self._check = {"estimator": estimator, "screen": screen, "targets": targets, "candidate": candidate,
                       "trial": 0, "estimates": [], "trials": []}
        self._ui("checkReady", {"points": points, "settle_ms": CHECK_SETTLE_MS, "observe_ms": CHECK_OBSERVE_MS})

    def _check_observe(self, data: dict, features: list | None, t: float) -> None:
        check = self._check
        if data.get("check") != check["trial"] or len(check["estimates"]) >= 60:
            return
        point = check["estimator"].predict(features, t) if features is not None else None
        screen = check["screen"]
        check["estimates"].append(None if point is None else
                                  ((point.x - screen["left"]) / screen["width"], (point.y - screen["top"]) / screen["height"]))

    def _finish_check(self) -> None:
        check, self._check = self._check, None
        outcome, candidate = summarize_check(check["trials"]), check["candidate"]
        accepted = False
        if outcome == "good" and candidate is not None:
            try:
                self._save(candidate)
                self.estimator.load(candidate); self.profile = candidate
                self.error = ""; self._calibration_notice = ""; accepted = True
            except (OSError, ValueError) as exc:
                self.error = str(exc)[:300]
                self._ui("notice", "Your calibration could not be saved on this computer. Please try again."); return
        self._ui("checkResult", self._result_words(outcome, candidate is not None, accepted))

    def _result_words(self, outcome: str, new: bool, accepted: bool) -> dict:
        if outcome == "good":
            return {"outcome": outcome, "title": "It found the right area", "body": [_GOOD, _RECALIBRATE_NOTE] if not new else [_GOOD],
                    "calibrated": True, "actions": [["practise", "Practise"], ["done", "Done"]] if accepted
                    else [["done", "Done"], ["practise", "Practise"], ["calibrate", "Recalibrate"]]}
        words = _WEAK if outcome == "weak" else _INSUFFICIENT
        title = "This didn\u2019t work well enough" if outcome == "weak" else "We couldn\u2019t check this"
        if new:
            body = [words] + ([_KEPT] if self.profile is not None else [])
            return {"outcome": outcome, "title": title, "body": body, "calibrated": self.profile is not None,
                    "actions": [["calibrate", "Try again"]]}
        body = [words, "Your calibration may no longer fit how you are sitting."]
        return {"outcome": outcome, "title": title, "body": body, "calibrated": True, "actions": [["calibrate", "Recalibrate"]]}

    def _practice_observe(self, features: list | None, t: float) -> None:
        if features is None:
            self._ui("practiceGaze", {"lost": "face"}); return
        point = self.estimator.predict(features, t)
        viewport = self._practice
        x, y = None, None
        if point is not None:
            x, y = (point.x - viewport["left"]) / viewport["width"], (point.y - viewport["top"]) / viewport["height"]
        if point is None or not (0 <= x <= 1 and 0 <= y <= 1):
            self._ui("practiceGaze", {"lost": "offscreen"}); return  # Removed, never clamped to an edge.
        self._ui("practiceGaze", {"x": x, "y": y})

    def _save(self, profile: dict) -> None:
        self.profile_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode="w", dir=self.profile_path.parent, delete=False) as f:
            json.dump(profile, f, allow_nan=False); temporary = Path(f.name)
        try:
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.profile_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _event(self, message: dict) -> None:
        params = message.get("params", {})
        if message.get("method") == "Page.frameNavigated" and params.get("frame", {}).get("id") == self._frame:
            self._stop.set()  # This owned document's replacement is never trusted.
            return
        if message.get("method") != "Runtime.bindingCalled" or params.get("name") != "__hermesGazeIntent" or params.get("executionContextId") != self._context:
            return
        payload = params.get("payload", "")
        if len(payload) > 4096:
            return
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict) or data.get("nonce") != self._nonce:
            return
        kind = data.get("type")
        if kind == "ready":
            self.error = ""; self.state = "running"; self._ready.set()
        elif kind == "error":
            # The window stays open to explain this; Use cursor or Try again ends it.
            self.error = str(data.get("error", "Tracker failed"))[:300]; self.state = "failed"
            self._clear_flow(); self._ready.set()
        elif kind == "retry_camera":
            self.error = ""; self.state = "starting"; self.last_sample = 0.
        elif kind == "use_cursor":
            self._clear_flow()
            if self.on_use_cursor is None:
                self._stop.set()
            else:  # configure() stops this host and joins this thread's loop; keep it off the reader.
                threading.Thread(target=self.on_use_cursor, name="hermes-webcam-cursor", daemon=True).start()
        elif kind == "calibration_start":
            measured = self._measure(data)
            if measured is None:
                return
            screen, viewport = measured
            targets = self._targets_on_screen(_POINTS, viewport, screen)
            if targets is None:
                self._clear_flow(); self._ui("notice", _WRONG_WINDOW); return
            self._clear_flow()
            self._targets, self._calibration, self._viewport = targets, screen, viewport
        elif kind == "check_start" or kind == "practice_start":
            measured = self._measure(data)
            if measured is None:
                return
            self._clear_flow()
            screen, viewport = measured
            if self.profile is None:
                self._ui("notice", "Calibrate first."); return
            if not self._on_saved_display(screen):
                self._ui("notice", _WRONG_DISPLAY); return
            if kind == "check_start":
                self._begin_check(self.estimator, self.profile["screen"], viewport, None)
            else:
                self._practice = viewport; self._ui("practiceReady")
        elif kind == "calibration_cancel" or kind == "practice_end":
            self._clear_flow()  # An unaccepted candidate goes with it; the saved profile stays.
        elif kind == "check_trial" and self._check is not None:
            check = self._check
            if data.get("index") != check["trial"]:
                return
            check["trials"].append(score_check_trial(check["estimates"], check["targets"][check["trial"]]))
            check["estimates"] = []; check["trial"] += 1
            if check["trial"] == len(check["targets"]):
                self._finish_check()
        elif kind == "calibration_point" and self._calibration is not None:
            if data.get("index") != self._point_index:
                return
            if len(self._point_samples) < 5:
                self._point_samples = []
                self._ui("pointRetry"); return
            x, y = self._targets[self._point_index]
            self._observations.extend((f, x, y) for f in self._point_samples)
            self._point_samples = []; self._point_index += 1
            if self._point_index < 9:
                self._ui("pointAccepted"); return
            screen, observations = self._calibration, self._observations
            try:
                # Fit a private copy: the accepted estimator and file change only after the check passes.
                candidate = copy.deepcopy(self.estimator)
                profile = candidate.calibrate(observations, screen)
            except (OSError, ValueError) as exc:
                self._clear_flow(); self.error = str(exc)[:300]
                self._ui("calibrationFailed", self.error)
                return
            self._begin_check(candidate, screen, self._viewport, profile)
        elif kind == "sample":
            t, f = data.get("t"), data.get("features")
            if not isinstance(t, (int, float)) or not math.isfinite(t) or not (self.last_sample < t <= time.time() + .2) or time.time() - t > 1:
                self.drops["stale_sample"] += 1
                return
            self.samples += 1; self.last_sample = t; self.hidden_samples += data.get("hidden") is True
            if not isinstance(f, list) or len(f) != self.estimator.feature_count or not all(
                type(v) in (int, float) and -limit < v < limit
                for v, limit in zip(f, self._feature_limits)
            ):
                self.drops["no_features"] += 1
                if self._check is not None:
                    self._check_observe(data, None, t)  # Counts against this trial.
                elif self._practice is not None:
                    self._practice_observe(None, t)
                return  # Missing face/blink: never synthesize a center fixation.
            if self._check is not None or self._practice is not None:
                self.drops["calibrating"] += 1  # Owned window only; never delivered to a page.
                if self._check is not None:
                    self._check_observe(data, f, t)
                else:
                    self._practice_observe(f, t)
                return
            if self._calibration is not None:
                self.drops["calibrating"] += 1
                if data.get("calibration") == self._point_index and len(self._point_samples) < 30:
                    self._point_samples.append(f)
                return
            if self.profile is None:
                self.drops["uncalibrated"] += 1
                return
            point = self.estimator.predict(f, t)
            if point is None:
                self.drops["offscreen" if isinstance(self.estimator, LandmarkEstimator) else "prediction_rejected"] += 1
                return
            self.predictions += 1
            try:
                result = self.on_point(point, self.profile["screen"])
            except TimeoutError:
                result = "transport_timeout"
            except ConnectionError:
                result = "transport_error"
            if result is True:
                self.delivered += 1
            else:
                self.drops[result if isinstance(result, str) and result in self.drops else "rejected_by_page"] += 1

    def _run(self) -> None:
        from websockets.sync.client import connect
        try:
            with tempfile.TemporaryDirectory(prefix="hermes-webcam-", ignore_cleanup_errors=True) as profile:
                host = Path(profile) / "tracker.html"
                host.write_text('<!doctype html><meta charset="utf-8"><title>Hermes Gaze webcam</title>')
                args = [_CHROME, f"--user-data-dir={profile}", "--remote-debugging-port=0", "--no-first-run",
                        "--no-default-browser-check", "--disable-extensions", "--allow-file-access-from-files", "--start-maximized",
                        "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                        "--disable-backgrounding-occluded-windows", *self.chrome_args, host.as_uri()]
                if self.fake_video is not None:
                    if not self.fake_video.is_file():
                        raise ValueError("Fake camera video does not exist")
                    args += ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                             "--use-file-for-fake-video-capture=" + str(self.fake_video.resolve())]
                self._process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                active = Path(profile) / "DevToolsActivePort"
                deadline = time.monotonic() + 15
                while not active.exists() and time.monotonic() < deadline and not self._stop.wait(.1):
                    if self._process.poll() is not None:
                        raise RuntimeError("Tracker Chrome exited before startup")
                self.http_url = "http://127.0.0.1:" + active.read_text().splitlines()[0]
                with urllib.request.urlopen(self.http_url + "/json/list", timeout=3) as response:
                    tab = next(t for t in json.load(response) if t.get("type") == "page" and t.get("url") == host.as_uri())
                self.target_id = tab["id"]
                with connect(tab["webSocketDebuggerUrl"], max_size=8 * 1024 * 1024) as self._ws:
                    self._frame = None
                    self._command("Runtime.enable", {}); self._command("Page.enable", {})
                    self._command("Network.enable", {})
                    self._command("Network.setBlockedURLs", {"urls": ["http://*", "https://*"]})
                    tree = self._command("Page.getFrameTree", {})
                    self._frame = tree["frameTree"]["frame"]["id"]
                    result = self._command("Page.createIsolatedWorld", {"frameId": self._frame, "worldName": "hermes-webcam"})
                    self._context = result["executionContextId"]; self._nonce = secrets.token_hex(32)
                    self._command("Runtime.addBinding", {"name": "__hermesGazeIntent", "executionContextId": self._context})
                    # MediaPipe normally inserts its loader into the main world. Keep it
                    # in this exact isolated context instead; no runtime/nonce in the DOM.
                    loader = (self.assets / "package/wasm/vision_wasm_internal.js").read_text()
                    result = self._command("Runtime.evaluate", {"expression": loader, "contextId": self._context})
                    if result.get("exceptionDetails"):
                        raise RuntimeError("Tracker WASM loader failed")
                    features = Path(__file__).with_name("browser") / "webcam_features.js"
                    self._command("Runtime.evaluate", {"expression": features.read_text(), "contextId": self._context})
                    options = {"nonce": self._nonce, "module": (self.assets / "package/vision_bundle.mjs").as_uri(),
                               "wasm": (self.assets / "package/wasm").as_uri(), "model": (self.assets / "face_landmarker.task").as_uri(),
                               "calibrated": self.profile is not None,
                               "calibration_notice": _OLD_MODEL_WINDOW if self._calibration_notice else (_BAD_PROFILE_WINDOW if self.error else ""),
                               **self.runtime_options}
                    result = self._command("Runtime.evaluate", {"expression": self.runtime_source.read_text() + "(" + json.dumps(options) + ")",
                                           "contextId": self._context, "awaitPromise": True})
                    if result.get("exceptionDetails"):
                        raise RuntimeError("Tracker runtime failed to initialize")
                    while not self._stop.is_set():
                        while not self._commands.empty():
                            method, params = self._commands.get_nowait(); self._send(method, params)
                        try:
                            self._event(json.loads(self._ws.recv(timeout=.1)))
                        except TimeoutError:
                            if self.state == "running" and self.last_sample and time.time() - self.last_sample > 4:
                                # Keep the window to say so; its stop releases the camera.
                                self.error = "Tracker stopped producing camera frames"; self.state = "failed"
                                self.last_sample = 0.; self._clear_flow(); self._ui("cameraFailed", self.error)
                    self._send("Runtime.evaluate", {"expression": "globalThis.__HERMES_WEBCAM__?.stop()", "contextId": self._context})
                    self._send("Browser.close", {})
                self._process.wait(8)
        except Exception as exc:
            if not self._stop.is_set():
                self.error = str(exc)[:300]; self.state = "failed"
        finally:
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(8)
                except subprocess.TimeoutExpired:
                    self._process.kill(); self._process.wait(5)
            self._ws = None; self._ready.set()
            if self.state != "failed":
                self.state = "stopped"
