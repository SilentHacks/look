"""Guided local dataset recorder. Agents MUST supply --fake-video; no audio ever."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time

from ..browser.webcam import WebcamHost
from .gaze_eval import BROWSER, CACHE, private_directory, save_json
from .gaze_dataset import inventory, pseudonym

CONDITIONS = {
    "upright": "Baseline: sit upright, normal comfortable light and usual distance. Keep the camera fixed.",
    "distance": "Lean back comfortably (or sit closer). Keep that distance throughout; do not move the display.",
    "head": "Turn or tilt your head slightly and comfortably; keep that pose while your eyes follow the dot.",
    "light": "Use a lower or brighter comfortable room light. Avoid darkness or glare. Sit upright.",
    "lid": "Tilt the laptop lid a little BEFORE starting. Keep this camera angle throughout; sit upright.",
    "no-recalibration": "Return the lid to baseline, then lean back slightly. Reuse the earlier baseline calibration; no new fit.",
}
DETAILS = {
    "upright": dict(posture="upright", lighting="normal", distance="usual", camera_angle="baseline"),
    "distance": dict(posture="upright", lighting="normal", distance="lean back", camera_angle="baseline"),
    "head": dict(posture="slight head turn/tilt", lighting="normal", distance="usual", camera_angle="baseline"),
    "light": dict(posture="upright", lighting="lower light", distance="usual", camera_angle="baseline"),
    "lid": dict(posture="upright", lighting="normal", distance="usual", camera_angle="lid tilted"),
    "no-recalibration": dict(posture="upright", lighting="normal", distance="lean back", camera_angle="baseline"),
}
DEFAULT_BLOCKS = ["upright", "distance", "head", "no-recalibration"]
DEFAULT_SECONDS = 25 * 1.2 + 9 * 1.2 + 16 * 1.2 + 15 + 16.8 + 9 * 1.2


def block_seconds(block, duration=None):
    return duration if duration is not None else DEFAULT_SECONDS - (30 if block == "no-recalibration" else 0)


def completed_blocks(root, person, glasses, device):
    return {m["condition"] for _, m in inventory(root, person)
            if m.get("complete") and m.get("glasses") == glasses and m.get("device") == device}


class RecordingHost(WebcamHost):
    def __init__(self, directory: Path, *, person="p-demo", condition="upright", duration=None, fake_video=None,
                 geometry=None, glasses="none", device="laptop", note="", blocks=None, dataset_root=None):
        self.directory = private_directory(directory)
        self.dataset_root = Path(dataset_root) if dataset_root is not None else None
        self.person, self.glasses, self.device, self.note = pseudonym(person), glasses, device, note
        self.blocks = blocks or [condition]
        self.geometry = geometry or {}
        self.duration = duration
        self.done = threading.Event()
        self.metadata = {}
        self.video_file = self.targets_file = None
        self.bytes = 0
        self.last_frame = -1.
        self.saved = []
        self.consent_path = self.directory / "consent.json"
        self.consented = self.consent_path.is_file() and json.loads(self.consent_path.read_text()).get("accepted") is True
        super().__init__(lambda *_: False, profile_path=self.directory / "unused-calibration.json", fake_video=fake_video,
                         runtime_source=BROWSER / "gaze_record.js",
                         runtime_options=dict(duration=duration, blocks=[dict(name=b, instruction=CONDITIONS[b], details=DETAILS[b]) for b in self.blocks],
                                              consent_required=not self.consented, person=person, glasses=glasses,
                                              device=device, note=note, physical=self.geometry, delete_path=str(self.directory)))

    def _event(self, message):
        params = message.get("params", {})
        if message.get("method") != "Runtime.bindingCalled" or params.get("name") != "__lookIntent" or params.get("executionContextId") != self._context:
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
        if kind == "record_consent" and data.get("accepted") is True:
            self.consented = True
            if not self.consent_path.exists():
                save_json(self.consent_path, dict(version=1, person=self.person, accepted=True,
                          accepted_at=datetime.now(timezone.utc).isoformat(), notice_version=1,
                          notice="Face/background video and targets, no audio; local only, optional export; deletable with derivatives and backups."))
        elif kind == "record_start" and self.video_file is None and self.consented:
            geometry = data.get("screen", {})
            keys = ("left", "top", "width", "height", "screen_width", "screen_height", "screen_left", "screen_top", "dpr")
            if not all(isinstance(geometry.get(k), (int, float)) and math.isfinite(geometry[k]) for k in keys):
                return
            if min(geometry[k] for k in ("width", "height", "screen_width", "screen_height", "dpr")) <= 0:
                return
            if not isinstance(data.get("epoch"), (int, float)) or not math.isfinite(data["epoch"]):
                return
            block = data.get("block", self.blocks[0])
            if block not in self.blocks:
                return
            details = data.get("details", DETAILS[block])
            if not isinstance(details, dict) or set(details) != set(DETAILS[block]) or any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in details.values()):
                return
            note = data.get("note", self.note)
            if not isinstance(note, str) or len(note) > 1000:
                return
            distance = data.get("distance_mm", self.geometry.get("distance_mm"))
            if distance is not None and (not isinstance(distance, (int, float)) or not math.isfinite(distance) or distance <= 0):
                return
            source = None
            if block == "no-recalibration":
                candidates = [(d, m) for d, m in inventory(self.dataset_root, self.person)
                              if m.get("complete") and m.get("condition") == "upright"
                              and m.get("glasses") == self.glasses and m.get("device") == self.device
                              and all(m["screen"].get(k) == geometry.get(k) for k in ("width", "height", "dpr", "screen_width", "screen_height"))]
                if not candidates:
                    self._commands.put(("Runtime.evaluate", {"expression": "globalThis.__HERMES_WEBCAM__.reject('No compatible baseline. Restore its window/display size and complete baseline first.')", "contextId": self._context}))
                    return
                source = candidates[-1][1]["session"]
            if self.dataset_root is not None:
                self.directory = private_directory(self.dataset_root / self.person / (time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)))
            self.bytes, self.last_frame = 0, -1.
            physical = dict(self.geometry)
            if physical:
                physical["distance_mm"] = distance
                physical["width_mm"] *= geometry["width"] / geometry["screen_width"]
                physical["height_mm"] *= geometry["height"] / geometry["screen_height"]
            self.metadata = dict(version=2, person=self.person, session=self.directory.name, condition=block,
                                 glasses=self.glasses, device=self.device, note=note, condition_details=details,
                                 fake_camera=self.fake_video is not None, finished=False, complete=False,
                                 requested_seconds=block_seconds(block, self.duration), screen={**geometry, **physical}, audio=False,
                                 date_time=datetime.now().astimezone().isoformat(), epoch=data["epoch"],
                                 viewport_origin=data.get("viewport_origin"), calibration_source=source,
                                 target_seed=data.get("seed"), protocol_version=3)
            # Exclusive creation: never append to another recording, including partial sessions.
            self.video_file = os.fdopen(os.open(self.directory / "camera.webm", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")
            self.targets_file = os.fdopen(os.open(self.directory / "targets.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w")
            save_json(self.directory / "recording.json", self.metadata)
            self._commands.put(("Runtime.evaluate", {"expression": "globalThis.__HERMES_WEBCAM__.begin()", "contextId": self._context}))
        elif kind == "record_chunk" and self.video_file is not None:
            chunk = base64.b64decode(data.get("data", ""), validate=True)
            if len(chunk) > 49152 or self.bytes + len(chunk) > 512 * 1024 * 1024:
                raise ValueError("Recording exceeded the private size bound")
            self.video_file.write(chunk); self.bytes += len(chunk)
        elif kind == "record_frame" and self.targets_file is not None:
            t, target = data.get("t"), data.get("target")
            g = self.metadata["screen"]
            if not isinstance(t, (int, float)) or not math.isfinite(t) or not self.last_frame < t <= self.metadata["requested_seconds"] + 1:
                return
            if not isinstance(target, list) or len(target) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= g[k] for v, k in zip(target, ("width", "height"))):
                return
            if data.get("phase") not in ("calibration", "fixed", "moving", "reading", "validation-start", "validation-end"):
                return
            self.last_frame = t
            record = {k: data[k] for k in ("t", "target", "phase", "settling", "media_time", "presented_frame")}
            self.targets_file.write(json.dumps(record, allow_nan=False) + "\n")
        elif kind == "record_end" and self.video_file is not None:
            self.video_file.close(); self.targets_file.close()
            self.metadata.update(finished=self.bytes > 0 and self.last_frame > 0, reason=str(data.get("reason", "unknown"))[:80],
                                 complete=data.get("reason") == "complete" and self.last_frame >= self.metadata["requested_seconds"] - 1,
                                 actual_seconds=self.last_frame, video_bytes=self.bytes)
            save_json(self.directory / "recording.json", self.metadata)
            self.saved.append(self.directory)
            self.video_file = self.targets_file = None
            if self.dataset_root is None:
                self.done.set()
            self._commands.put(("Runtime.evaluate", {"expression": "globalThis.__HERMES_WEBCAM__.saved()", "contextId": self._context}))
        elif kind == "protocol_end":
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
    p.add_argument("--person", required=True, help="anonymous ID, e.g. p-a7c4; never a real name")
    p.add_argument("--glasses", choices=("none", "glasses", "contacts"), required=True)
    p.add_argument("--device", required=True, help="anonymous camera/display label, e.g. laptop-front")
    p.add_argument("--note", default="", help="no names or contact details")
    p.add_argument("--blocks", nargs="+", choices=CONDITIONS, default=DEFAULT_BLOCKS)
    p.add_argument("--repeat", action="store_true", help="record completed blocks again instead of resuming")
    p.add_argument("--duration", type=float, help="override each block's seconds (72–180; 36–180 with a fake camera); default: unscaled schedule")
    p.add_argument("--fake-video", type=Path, help="Y4M/MJPEG fake camera; mandatory for agents")
    p.add_argument("--width-mm", type=float)
    p.add_argument("--height-mm", type=float)
    p.add_argument("--distance-mm", type=float)
    args = p.parse_args()
    try:
        pseudonym(args.person)
    except ValueError as exc:
        p.error(str(exc))
    if not args.device.strip() or len(args.device) > 100 or len(args.note) > 1000:
        p.error("Device label is required (max 100 characters); note max 1000; no personal names")
    if args.duration is not None and (not math.isfinite(args.duration) or not (36 if args.fake_video else 72) <= args.duration <= 180):
        p.error("--duration must be 72–180 seconds (36–180 for fake devices)")
    physical = {k: v for k, v in vars(args).items() if k in ("width_mm", "height_mm", "distance_mm") and v is not None}
    if physical and (len(physical) != 3 or any(not math.isfinite(v) or v <= 0 for v in physical.values())):
        p.error("Supply all three positive physical measurements, or none (degrees will be N/A)")
    root = private_directory(args.out)
    completed = completed_blocks(root, args.person, args.glasses, args.device)
    blocks = list(dict.fromkeys(args.blocks))
    if not args.repeat:
        blocks = [b for b in blocks if b not in completed]
    if not blocks:
        print("All selected blocks are complete. Use --repeat for another round.")
        return
    if "no-recalibration" in blocks and "upright" not in completed and ("upright" not in blocks or blocks.index("upright") > blocks.index("no-recalibration")):
        p.error("Record upright first (in this command or an earlier session with the same glasses/device)")
    host = RecordingHost(private_directory(root / args.person), person=args.person, glasses=args.glasses,
                         device=args.device, note=args.note, blocks=blocks, duration=args.duration,
                         fake_video=args.fake_video, geometry=physical, dataset_root=root)
    try:
        state = host.start(wait=25)
        if state["state"] != "running":
            raise RuntimeError(state["error"])
        print("Guided recorder ready. Consent, instructions and breaks are in the owned window; no audio.", flush=True)
        while not host.done.wait(.2):
            if host.state in ("failed", "stopped") or host._stop.is_set():
                raise RuntimeError(host.error or "Window closed; completed sessions are retained. Run the same command to resume.")
        for directory in host.saved:
            print("Saved private local recording: " + str(directory))
    finally:
        host.stop()


if __name__ == "__main__":
    main()
