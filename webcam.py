"""Owned Chrome camera process, nonce-bound observations and local-only calibration.

No HTTP listener. The tracker never attaches to the companion/user's Chrome.
Only this class's Popen process is closed. Importing this module opens no device.
"""
from __future__ import annotations

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

from .tracker.webcam_gaze import GazeEstimator, LandmarkEstimator

_ASSETS = {
    "tasks.tgz": ("https://registry.npmjs.org/@mediapipe/tasks-vision/-/tasks-vision-0.10.32.tgz",
                  "b362a2b56aafcce7857047c25dc8fd69612fd8e75018e264717d24290e7815c1"),
    "face_landmarker.task": ("https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
                             "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"),
}
_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_POINTS = [(x, y) for y in (.1, .5, .9) for x in (.1, .5, .9)]


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
                 fake_video: Path | None = None, runtime_source: Path | None = None) -> None:
        self.estimator = estimator or LandmarkEstimator()
        self.on_point = on_point
        self.profile_path = profile_path or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hermes-gaze" / "webcam-calibration.json"
        self.assets = assets
        self.fake_video = fake_video
        self.runtime_source = runtime_source or Path(__file__).parent / "browser" / "webcam_host.js"
        self.profile = None
        self.error = ""
        self.state = "stopped"
        self.samples = self.predictions = self.delivered = self.hidden_samples = 0
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

    def status(self) -> dict:
        return {"state": self.state, "calibrated": self.profile is not None, "samples": self.samples,
                "predictions": self.predictions, "delivered": self.delivered, "hidden_samples": self.hidden_samples,
                "sample_age_seconds": round(time.time() - self.last_sample, 2) if self.last_sample else None,
                "error": self.error, "model": self.estimator.model_id}

    def start(self) -> dict:
        with self._start_lock:
            return self._start()

    def _start(self) -> dict:
        if self._thread and self._thread.is_alive():
            return self.status()
        self._stop.clear(); self._ready.clear(); self.error = ""; self.state = "starting"
        self.last_sample = 0.
        self._calibration = None
        self._observations = []; self._point_samples = []; self._point_index = 0
        try:
            self.assets = prepare_assets(self.assets)
        except (OSError, ValueError) as exc:
            self.state = "failed"; self.error = str(exc)
            return self.status()
        self.profile = None
        try:
            if self.profile_path.exists():
                if self.profile_path.stat().st_size > 65536:
                    raise ValueError("Calibration file too large")
                profile = json.loads(self.profile_path.read_text())
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
        self._calibration = None
        self._observations = []; self._point_samples = []; self._point_index = 0
        self.state = "stopped"

    def calibrate(self) -> dict:
        status = self.start()
        if status["state"] == "running":
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

    def _ui(self, method: str, text: str) -> None:
        self._send("Runtime.evaluate", {"expression": "globalThis.__HERMES_WEBCAM__?." + method + "(" + json.dumps(text) + ")",
                                       "contextId": self._context})

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
            self.state = "running"; self._ready.set()
        elif kind == "error":
            self.error = str(data.get("error", "Tracker failed"))[:300]; self.state = "failed"; self._stop.set()
        elif kind == "stopped":
            self._stop.set()
        elif kind == "calibration_start":
            screen = data.get("screen", {})
            if not all(isinstance(screen.get(k), (int, float)) and math.isfinite(screen[k]) for k in
                       ("left", "top", "width", "height", "screen_width", "screen_height", "screen_left", "screen_top", "dpr")):
                return
            if min(screen[k] for k in ("width", "height", "dpr")) <= 0:
                return
            viewport = data.get("viewport", {})
            if not all(isinstance(viewport.get(k), (int, float)) and math.isfinite(viewport[k])
                       for k in ("left", "top", "width", "height")):
                return
            self._targets = [((viewport["left"] + x * viewport["width"] - screen["left"]) / screen["width"],
                              (viewport["top"] + y * viewport["height"] - screen["top"]) / screen["height"])
                             for x, y in _POINTS]
            if any(not 0 <= v <= 1 for point in self._targets for v in point):
                self._ui("calibrationResult", "Move the calibration window fully onto one screen and try again.")
                return
            self._calibration = screen; self._observations = []; self._point_samples = []; self._point_index = 0
        elif kind == "calibration_cancel":
            self._calibration = None; self._observations = []; self._point_samples = []
        elif kind == "calibration_point" and self._calibration is not None:
            if data.get("index") != self._point_index:
                return
            if len(self._point_samples) < 5:
                self.error = "Face was lost during calibration; try again"; self._calibration = None
                self._ui("calibrationResult", self.error); return
            x, y = self._targets[self._point_index]
            self._observations.extend((f, x, y) for f in self._point_samples)
            self._point_samples = []; self._point_index += 1
            if self._point_index == 9:
                try:
                    profile = self.estimator.calibrate(self._observations, self._calibration)
                    self._save(profile); self.profile = profile; self.error = ""
                    self._ui("calibrationResult", "Calibration saved locally. Return to Chrome; move the pointer once in the page, then hold Space.")
                except (OSError, ValueError) as exc:
                    if self.profile is not None:
                        self.estimator.load(self.profile)
                    self.error = str(exc); self._ui("calibrationResult", self.error)
                finally:
                    self._calibration = None; self._observations = []
        elif kind == "sample":
            t, f = data.get("t"), data.get("features")
            if not isinstance(t, (int, float)) or not math.isfinite(t) or not (self.last_sample < t <= time.time() + .2) or time.time() - t > 1:
                return
            self.samples += 1; self.last_sample = t; self.hidden_samples += data.get("hidden") is True
            if not isinstance(f, list) or len(f) != self.estimator.feature_count or not all(isinstance(v, (int, float)) and math.isfinite(v) and abs(v) < 4 for v in f):
                return  # Missing face/blink: never synthesize a center fixation.
            if self._calibration is not None:
                if data.get("calibration") == self._point_index and len(self._point_samples) < 30:
                    self._point_samples.append(f)
                return
            point = self.estimator.predict(f, t)
            if point is not None and self.profile is not None:
                self.predictions += 1
                try:
                    self.delivered += self.on_point(point, self.profile["screen"]) is True
                except (ConnectionError, TimeoutError):
                    pass  # No foreground document is normal while using another application.

    def _run(self) -> None:
        from websockets.sync.client import connect
        try:
            with tempfile.TemporaryDirectory(prefix="hermes-webcam-", ignore_cleanup_errors=True) as profile:
                host = Path(profile) / "tracker.html"
                host.write_text('<!doctype html><meta charset="utf-8"><title>Hermes Gaze webcam</title>')
                args = [_CHROME, f"--user-data-dir={profile}", "--remote-debugging-port=0", "--no-first-run",
                        "--no-default-browser-check", "--disable-extensions", "--allow-file-access-from-files", "--start-maximized",
                        "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                        "--disable-backgrounding-occluded-windows", host.as_uri()]
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
                    options = {"nonce": self._nonce, "module": (self.assets / "package/vision_bundle.mjs").as_uri(),
                               "wasm": (self.assets / "package/wasm").as_uri(), "model": (self.assets / "face_landmarker.task").as_uri(),
                               "calibrated": self.profile is not None}
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
                            if self.last_sample and time.time() - self.last_sample > 4:
                                raise RuntimeError("Tracker stopped producing camera frames")
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
