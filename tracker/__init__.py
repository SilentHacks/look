"""Pointing & gaze stream abstractions for hermes-gaze."""

from __future__ import annotations

from .simulated_gaze import FixationSample, FixationRingBuffer, SimulatedPointerTracker
from .recalibrator import OnlineRecalibrator
from .voice_listener import (
    get_shared_voice_server,
    get_whisper_model,
    record_microphone,
    transcribe_audio_buffer,
)

__all__ = [
    "FixationSample",
    "FixationRingBuffer",
    "SimulatedPointerTracker",
    "OnlineRecalibrator",
    "get_shared_voice_server",
    "get_whisper_model",
    "record_microphone",
    "transcribe_audio_buffer",
]
