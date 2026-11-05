"""Local speech recognition helpers for hermes-gaze.

faster-whisper local model (tiny.en / base.en) with word-level timestamps plus
sounddevice microphone capture from the default OS audio input. Optional
dependencies (numpy, faster-whisper, sounddevice) are imported lazily inside
each function so importing this module never requires them.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import wave
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "base.en"
_WHISPER_MODELS: Dict[str, Any] = {}  # per-name cache — config may switch models mid-session
_MODEL_LOCK = threading.Lock()

# Base64 audio payloads from the overlay's transcribe intent are bounded before decode.
MAX_AUDIO_BYTES = 12 * 1024 * 1024


def get_whisper_model(model_name: str = _DEFAULT_MODEL) -> Any:
    """Lazy per-name singleton loader for the local faster-whisper model."""
    with _MODEL_LOCK:
        model = _WHISPER_MODELS.get(model_name)
        if model is None:
            from faster_whisper import WhisperModel

            logger.info("Loading faster-whisper model '%s' on CPU (int8)...", model_name)
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _WHISPER_MODELS[model_name] = model
        return model


def decode_audio_to_float32(raw_bytes: bytes, sample_rate: int = 16000) -> Any:
    """Decode any audio container (WebM, Opus, WAV, MP3) to 16kHz mono float32 numpy array."""
    import numpy as np
    import shutil
    import subprocess

    if not raw_bytes:
        return np.zeros(0, dtype=np.float32)

    ffmpeg_bin = (
        shutil.which("ffmpeg")
        or ("/opt/homebrew/bin/ffmpeg" if os.path.isfile("/opt/homebrew/bin/ffmpeg") else "/usr/local/bin/ffmpeg")
    )
    if os.path.isfile(ffmpeg_bin):
        try:
            cmd = [
                ffmpeg_bin,
                "-nostdin",
                "-threads", "0",
                "-i", "pipe:0",
                "-f", "s16le",
                "-ac", "1",
                "-ar", str(sample_rate),
                "pipe:1",
            ]
            proc = subprocess.run(cmd, input=raw_bytes, capture_output=True, check=True)
            if len(proc.stdout) > 0:
                return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception as exc:
            logger.warning("ffmpeg decode error: %s, falling back to wav/pcm parsing", exc)

    # Fallback to WAV parsing
    if raw_bytes.startswith(b"RIFF") and b"WAVE" in raw_bytes[:16]:
        try:
            with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
                channels = wf.getnchannels()
                raw_frames = wf.readframes(wf.getnframes())
                audio_np = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
                if channels > 1:
                    audio_np = audio_np.reshape(-1, channels).mean(axis=1)
                return audio_np
        except Exception as exc:
            logger.warning("WAV parsing error: %s, falling back to raw PCM", exc)

    return np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_audio_buffer(
    audio_bytes: bytes,
    sample_rate: int = 16000,
    model_name: str = _DEFAULT_MODEL,
    audio_epoch: Optional[float] = None,
) -> Tuple[str, List[Dict[str, object]]]:
    """Transcribe WebM, WAV, or PCM bytes into text with word-level timestamps.

    ``audio_epoch`` is the wall-clock time (time.time()) when recording began; when
    given, the audio-relative whisper word times are shifted to wall-clock epochs so
    the temporal aligner can weight them against real fixations."""
    import numpy as np

    audio_np = decode_audio_to_float32(audio_bytes, sample_rate=sample_rate)
    if len(audio_np) == 0:
        return "", []

    peak = float(np.max(np.abs(audio_np)))
    if peak < 1e-5:
        return "", []

    # Normalize quiet microphone input so Whisper reliably detects normal/soft speech
    if 0.002 < peak < 0.65:
        audio_np = np.clip(audio_np * (0.85 / peak), -1.0, 1.0).astype(np.float32)

    model = get_whisper_model(model_name)
    segments, _info = model.transcribe(
        audio_np,
        word_timestamps=True,
        language="en",
        condition_on_previous_text=False,
    )
    epoch_off = float(audio_epoch or 0.0)
    words: List[Dict[str, object]] = []
    text_parts: List[str] = []
    for seg in segments:
        text_parts.append(seg.text.strip())
        for w in getattr(seg, "words", None) or []:
            words.append({"word": w.word, "start": float(w.start) + epoch_off, "end": float(w.end) + epoch_off})

    full_text = " ".join(text_parts).strip()
    return full_text, words


def record_microphone(
    duration_s: float = 2.5,
    sample_rate: int = 16000,
) -> bytes:
    """Record audio from default macOS microphone using sounddevice."""
    import numpy as np
    import sounddevice as sd

    num_samples = int(duration_s * sample_rate)
    recording = sd.rec(num_samples, samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    return recording.tobytes()
