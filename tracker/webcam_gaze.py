"""Webcam gaze tracker wrapper (Stage 2 MediaPipe FaceLandmarker with graceful fallback to Stage 1)."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from typing import Optional

from plugins.plugin_storage import plugin_data_dir

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)


def ensure_face_landmarker_model() -> Path:
    """Download Google's official MediaPipe face_landmarker.task into plugin_data_dir() on first webcam use."""
    models_dir = plugin_data_dir("hermes-gaze") / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / "face_landmarker.task"
    if target.is_file() and target.stat().st_size > 1_000_000:
        return target
    req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "hermes-gaze/0.1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = resp.read()
    digest = hashlib.sha256(payload).hexdigest()
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(payload)
    tmp.replace(target)
    (models_dir / "face_landmarker.sha256").write_text(digest, encoding="utf-8")
    return target


def webcam_dependencies_available() -> bool:
    """Passive probe for Stage 2 webcam dependencies (mediapipe + cv2)."""
    import importlib.util

    return (
        importlib.util.find_spec("mediapipe") is not None
        and importlib.util.find_spec("cv2") is not None
    )
