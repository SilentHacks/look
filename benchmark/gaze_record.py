"""Explicit local recorder in an owned Chrome window. Importing opens no devices.

User only: python -c 'import tests; from hermes_gaze.benchmark.gaze_record import main; main()' ...
Agents must supply --fake-video; never run the real camera command themselves.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time

from ..webcam import WebcamHost
from .gaze_eval import BROWSER, CACHE, private_directory, save_json

CONDITIONS = {
    "upright": "Sit upright in your usual lighting. Keep the screen and camera still.",
    "lean-back": "Lean back comfortably in the same lighting. Do not move the screen.",
    "lean-side": "Sit a little to one side, naturally. Do not strain your neck.",
    "dim": "Use comfortable dimmer room lighting, without a strong light behind you.",
    "side-light": "Use ordinary side lighting. Sit in your normal working posture.",
}


class RecordingHost(WebcamHost):
    def __init__(self, directory: Path, *, person="self", condition="upright", duration=180., fake_video=None, geometry=None):
        self.directory = private_directory(directory)
        self.done = threading.Event()
        self.metadata = dict(version=1, person=person, session=self.directory.name, condition=condition,
                             fake_camera=fake_video is not None, finished=False, requested_seconds=duration,
                             screen=geometry or {}, audio=False)
        self.video_file = self.targets_file = None
        self.bytes = 0
        self.last_frame = -1.
        super().__init__(lambda *_: False, profile_path=self.directory / "unused-calibration.json", fake_video=fake_video,
                         runtime_source=BROWSER / "gaze_record.js",
                         runtime_options=dict(duration=duration, instruction=CONDITIONS[condition]))

    def _event(self, message):
        params = message.get("params", {})
        if message.get("method") != "Runtime.bindingCalled" or params.get("name") != "__hermesGazeIntent" or params.get("executionContextId") != self._context:
            return super()._event(message)
        payload = params.get("payload", "")
        if not isinstance(payload, str) or len(payload) > 70000:
            return
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict) or data.get("nonce") != self._nonce:
            return
        kind = data.get("type")
        if kind == "record_start" and self.video_file is None:
            geometry = data.get("screen", {})
            keys = ("left", "top", "width", "height", "screen_width", "screen_height", "screen_left", "screen_top", "dpr")
            if not all(isinstance(geometry.get(k), (int, float)) and math.isfinite(geometry[k]) for k in keys):
                return
            if min(geometry[k] for k in ("width", "height", "screen_width", "screen_height", "dpr")) <= 0:
                return
            if not isinstance(data.get("epoch"), (int, float)) or not math.isfinite(data["epoch"]):
                return
            # Exclusive creation: never replace or append another person's video.
            self.video_file = os.fdopen(os.open(self.directory / "camera.webm", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")
            self.targets_file = os.fdopen(os.open(self.directory / "targets.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w")
            physical = {k: v for k, v in self.metadata["screen"].items() if k in ("width_mm", "height_mm", "distance_mm")}
            if physical:
                physical["width_mm"] *= geometry["width"] / geometry["screen_width"]
                physical["height_mm"] *= geometry["height"] / geometry["screen_height"]
            self.metadata.update(screen={**geometry, **physical}, viewport_origin=data.get("viewport_origin"), epoch=data.get("epoch"))
            save_json(self.directory / "recording.json", self.metadata)
        elif kind == "record_chunk" and self.video_file is not None and not self.done.is_set():
            chunk = base64.b64decode(data.get("data", ""), validate=True)
            if len(chunk) > 49152 or self.bytes + len(chunk) > 512 * 1024 * 1024:
                raise ValueError("Recording exceeded the private size bound")
            self.video_file.write(chunk); self.bytes += len(chunk)
        elif kind == "record_frame" and self.targets_file is not None and not self.done.is_set():
            t, target = data.get("t"), data.get("target")
            g = self.metadata["screen"]
            if not isinstance(t, (int, float)) or not math.isfinite(t) or not self.last_frame < t <= self.metadata["requested_seconds"] + 1:
                return
            if not isinstance(target, list) or len(target) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= g[k] for v, k in zip(target, ("width", "height"))):
                return
            if data.get("phase") not in ("calibration", "fixed", "moving", "reading"):
                return
            self.last_frame = t
            record = {k: data[k] for k in ("t", "target", "phase", "settling", "media_time", "presented_frame")}
            self.targets_file.write(json.dumps(record, allow_nan=False) + "\n")
        elif kind == "record_end" and self.video_file is not None and not self.done.is_set():
            self.video_file.close(); self.targets_file.close()
            self.metadata.update(finished=self.bytes > 0 and self.last_frame > 0, reason=str(data.get("reason", "unknown"))[:80],
                                 actual_seconds=self.last_frame, video_bytes=self.bytes)
            save_json(self.directory / "recording.json", self.metadata)
            self.done.set()
        else:
            super()._event(message)

    def stop(self):
        super().stop()
        for file in (self.video_file, self.targets_file):
            if file is not None and not file.closed:
                file.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=CACHE / "recordings")
    p.add_argument("--person", default="self", help="local pseudonym, not a real name")
    p.add_argument("--condition", choices=CONDITIONS, default="upright")
    p.add_argument("--duration", type=float, default=180.)
    p.add_argument("--fake-video", type=Path, help="Y4M/MJPEG fake camera; mandatory for agents")
    p.add_argument("--width-mm", type=float)
    p.add_argument("--height-mm", type=float)
    p.add_argument("--distance-mm", type=float)
    args = p.parse_args()
    if not math.isfinite(args.duration) or not 36 <= args.duration <= 480:
        p.error("--duration must be 36–480 seconds (180 recommended)")
    physical = {k: v for k, v in vars(args).items() if k in ("width_mm", "height_mm", "distance_mm") and v is not None}
    if physical and (len(physical) != 3 or any(not math.isfinite(v) or v <= 0 for v in physical.values())):
        p.error("Supply all three positive physical measurements, or none (degrees will be N/A)")
    root = private_directory(args.out)
    directory = root / (time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3))
    host = RecordingHost(directory, person=args.person, condition=args.condition, duration=args.duration,
                         fake_video=args.fake_video, geometry=physical)
    try:
        state = host.start()
        if state["state"] != "running":
            raise RuntimeError(state["error"])
        print("Recording window ready. Click Start recording; no audio is captured.", flush=True)
        while not host.done.wait(.2):
            if host.state in ("failed", "stopped") or host._stop.is_set():
                raise RuntimeError(host.error or "Window closed before the recording was finalized")
        print("Saved private local recording: " + str(directory))
    finally:
        host.stop()


if __name__ == "__main__":
    main()
