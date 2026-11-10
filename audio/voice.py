"""Local NVIDIA Parakeet v3 and faster-whisper recognition.

Returns text and word timestamps shifted by the native capture's audio epoch.
Only explicit setup downloads assets. Registration and transcription use caches.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import wave
from typing import Any, Dict, List, Optional, Tuple

from .asset_cache import AssetIntegrityError, AssetsMissing, WHISPER, prepare


logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "base.en"
_WHISPER_MODELS: Dict[str, Any] = {}  # per-name cache — config may switch models mid-session
_MODEL_LOCK = threading.Lock()

_PREPARE_LOCK = threading.Lock()
_PREPARING = False
_PREPARATION_ERROR = ""
_PREPARE_DOWNLOAD = False
_PREPARE_REPORT = None

# Backend used by the latest transcription, for diagnostics.
_LAST_BACKEND: Optional[str] = None

# Base64 audio payloads from the overlay's transcribe intent are bounded before decode.
MAX_AUDIO_BYTES = 12 * 1024 * 1024


def get_whisper_model(model_name: str = _DEFAULT_MODEL) -> Any:
    """Lazy per-name singleton loader for the local faster-whisper model."""
    if model_name not in WHISPER:
        raise ValueError("Supported speech models are base.en and tiny.en. Custom repositories and paths are not supported.")
    with _MODEL_LOCK:
        model = _WHISPER_MODELS.get(model_name)
        if model is None:
            from faster_whisper import WhisperModel

            logger.info("Loading faster-whisper model '%s' on CPU (int8)...", model_name)
            root = prepare(WHISPER[model_name])
            model = WhisperModel(str(root), device="cpu", compute_type="int8", local_files_only=True)
            _WHISPER_MODELS[model_name] = model
        return model




def recognition_ready(model_name=_DEFAULT_MODEL):
    """Constant-time capture gate: never take a model loader lock or touch disk."""
    if model_name == "parakeet-v3":
        from .asr.parakeet_v3 import ready
        if ready():
            return True
        model_name = _DEFAULT_MODEL
    return model_name in _WHISPER_MODELS


def recognition_status(model_name=_DEFAULT_MODEL):
    if recognition_ready(model_name):
        return "Local speech recognition is ready."
    if _PREPARING:
        return "Preparing local speech recognition. You can type with Right Option while you wait."
    if _PREPARATION_ERROR:
        return _PREPARATION_ERROR
    return "Local speech recognition is not ready. Run /look setup, or press Right Option to type."


def _prepare_recognition(model_name, *, download, report=None):
    """One worker checks every cache before an explicitly requested download."""
    global _PREPARING, _PREPARE_DOWNLOAD, _PREPARE_REPORT, _PREPARATION_ERROR
    if model_name == "parakeet-v3":
        from .asr.parakeet_v3 import ready as is_ready
    else:
        is_ready = lambda: recognition_ready(model_name)
    with _PREPARE_LOCK:
        if is_ready():
            return
        if _PREPARING:
            _PREPARE_DOWNLOAD |= download
            if report is not None:
                _PREPARE_REPORT = report
            return
        _PREPARING = True
        _PREPARE_DOWNLOAD = download
        _PREPARE_REPORT = report
        _PREPARATION_ERROR = ""

    def work():
        global _PREPARING, _PREPARATION_ERROR, _PREPARE_REPORT
        missing, error, unavailable = [], "", False

        def try_load(repo, load, *, fetch=False):
            nonlocal unavailable
            try:
                if repo == "parakeet-v3":
                    from .asr.parakeet_v3 import get_runner
                    loaded = get_runner(download=fetch)
                else:
                    prepare(repo, download=fetch)
                    loaded = load()
                if loaded is not None:
                    return True
                unavailable = True
            except AssetIntegrityError:
                raise
            except AssetsMissing:
                if not fetch and (model_name != "parakeet-v3" or repo == "parakeet-v3"):
                    missing.append((repo, load))
            except Exception as exc:
                logger.debug("Speech backend %s unavailable: %s", repo, exc)
                unavailable = True
                if repo == "parakeet-v3" and not fetch:
                    missing.append((repo, load))
            return False

        def failed(exc):
            logger.warning("Speech recognition preparation stopped: %s", exc)
            return (str(exc) if isinstance(exc, (AssetIntegrityError, ValueError)) else
                    "Local speech recognition could not prepare. Check internet, disk space and "
                    "dependencies, then run /look setup. Use Right Option to type.")

        try:
            if model_name not in (*WHISPER, "parakeet-v3"):
                raise ValueError("Supported speech models are base.en, tiny.en and parakeet-v3.")
            fallback_model = _DEFAULT_MODEL if model_name == "parakeet-v3" else model_name
            loaders = [(WHISPER[fallback_model], lambda: get_whisper_model(fallback_model))]
            if model_name == "parakeet-v3":
                loaders.insert(0, ("parakeet-v3", None))
            for repo, load in loaders:
                if try_load(repo, load, fetch=download and repo == "parakeet-v3"):
                    break
        except Exception as exc:
            error = failed(exc)

        # Finish cache-only work atomically with accepting an overlapping Setup.
        # Only the latest completion reporter is retained during repeated Setup.
        with _PREPARE_LOCK:
            fetch = not error and not is_ready() and _PREPARE_DOWNLOAD
            if not fetch:
                if not error and unavailable and not recognition_ready(model_name):
                    error = ("Local speech recognition could not load cached models. Check dependencies, "
                             "then run /look setup. Use Right Option to type.")
                _PREPARATION_ERROR = error
                _PREPARING = False
                callback, _PREPARE_REPORT = _PREPARE_REPORT, None
        if fetch:
            try:
                for repo, load in missing:
                    if try_load(repo, load, fetch=True):
                        break
                if not recognition_ready(model_name):
                    raise RuntimeError("No usable local speech backend")
            except Exception as exc:
                error = failed(exc)
            with _PREPARE_LOCK:
                _PREPARATION_ERROR = error
                _PREPARING = False
                callback, _PREPARE_REPORT = _PREPARE_REPORT, None
        if callback is not None:
            callback(recognition_status(model_name))

    threading.Thread(target=work, name="gaze-asr-prepare" if download else "gaze-asr-prewarm",
                     daemon=True).start()


def prepare_recognition(model_name=_DEFAULT_MODEL, *, report=None):
    """Explicit setup may fetch missing assets only after trying usable caches."""
    _prepare_recognition(model_name, download=True, report=report)


def prewarm(model_name=_DEFAULT_MODEL, *, report=None) -> None:
    """Registration warms supported verified caches asynchronously, without devices."""
    _prepare_recognition(model_name, download=False, report=report)


def _looks_like_container(raw_bytes: bytes) -> bool:
    """Sniff known media-container magics — anything else is treated as raw s16le PCM."""
    if raw_bytes.startswith((b"OggS", b"fLaC", b"ID3", b"\x1a\x45\xdf\xa3")):
        return True
    if len(raw_bytes) > 8 and raw_bytes[4:8] == b"ftyp":  # mp4/m4a
        return True
    if raw_bytes[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):  # mp3 frame sync
        return True
    return False


def decode_audio_to_float32(raw_bytes: bytes, sample_rate: int = 16000, mime_type: Optional[str] = None) -> Any:
    """Decode a container or raw s16le PCM; a declared browser MIME type requires container decoding."""
    import numpy as np
    import shutil
    import subprocess

    if not raw_bytes:
        return np.zeros(0, dtype=np.float32)

    # Fast path: plain PCM WAV at the target rate parses in-process — no
    # ffmpeg spawn (~15-25ms). Other containers still route through ffmpeg.
    is_riff = raw_bytes.startswith(b"RIFF") and b"WAVE" in raw_bytes[:16]
    if is_riff:
        try:
            with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
                if wf.getframerate() == sample_rate and wf.getsampwidth() == 2:
                    channels = wf.getnchannels()
                    raw_frames = wf.readframes(wf.getnframes())
                    audio_np = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
                    if channels > 1:
                        audio_np = audio_np.reshape(-1, channels).mean(axis=1)
                    return audio_np
        except Exception as exc:
            logger.warning("WAV parsing error: %s, falling back to ffmpeg", exc)

    ffmpeg_bin = (
        shutil.which("ffmpeg")
        or ("/opt/homebrew/bin/ffmpeg" if os.path.isfile("/opt/homebrew/bin/ffmpeg") else "/usr/local/bin/ffmpeg")
    )
    if is_riff or mime_type or _looks_like_container(raw_bytes):
        if not os.path.isfile(ffmpeg_bin):
            raise RuntimeError("Recorded audio requires ffmpeg. Install ffmpeg and restart Hermes.")
        cmd = [
            ffmpeg_bin, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-threads", "0", "-i", "pipe:0", "-f", "s16le",
            "-ac", "1", "-ar", str(sample_rate), "pipe:1",
        ]
        try:
            proc = subprocess.run(cmd, input=raw_bytes, capture_output=True, check=True)
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", errors="replace").strip()[-500:]
            raise ValueError(f"Could not decode recorded audio: {detail or 'ffmpeg rejected the recording'}") from exc
        if not proc.stdout:
            raise ValueError("Recorded audio decoded to no samples")
        return np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0

    # Raw s16le PCM — what record_microphone produces. No container magic means
    # skipping the ffmpeg spawn entirely.
    if len(raw_bytes) % 2:
        raise ValueError("Raw PCM audio must contain complete 16-bit samples (even byte length)")
    return np.frombuffer(raw_bytes, dtype="<i2").astype(np.float32) / 32768.0


def transcribe_audio_buffer(
    audio_bytes: bytes,
    sample_rate: int = 16000,
    model_name: str = _DEFAULT_MODEL,
    audio_epoch: Optional[float] = None,
    backend: str = "auto",
    mime_type: Optional[str] = None,
    timing=None,
) -> Tuple[str, List[Dict[str, object]]]:
    """Transcribe WebM, WAV, or PCM bytes into text with word-level timestamps.

    ``audio_epoch`` is the wall-clock time (time.time()) when recording began; when
    given, the audio-relative word times are shifted to wall-clock epochs so
    the temporal aligner can weight them against real fixations.

    ``base.en`` and ``tiny.en`` select Whisper directly. ``parakeet-v3``
    tries the NVIDIA worker, then cached Whisper on ordinary runtime failure.
    Removed v2 backend names fail with migration guidance."""
    if backend not in ("auto", "whisper", "parakeet-v3"):
        raise ValueError("Parakeet v2 backends are no longer supported. Select parakeet-v3, or Whisper base.en/tiny.en.")
    import numpy as np

    audio_np = decode_audio_to_float32(audio_bytes, sample_rate=sample_rate, mime_type=mime_type)
    if len(audio_np) == 0:
        return "", []

    peak = float(np.max(np.abs(audio_np)))
    if peak < 1e-5:
        return "", []

    # Normalize quiet microphone input so the ASR reliably detects normal/soft speech
    if 0.002 < peak < 0.65:
        audio_np = np.clip(audio_np * (0.85 / peak), -1.0, 1.0).astype(np.float32)

    global _LAST_BACKEND
    if backend == "parakeet-v3" or model_name == "parakeet-v3" and backend == "auto":
        from .asr.parakeet_v3 import get_runner
        try:
            runner = get_runner()
            if timing is not None:
                timing.mark("asr_model_ready")
                timing.mark("asr_inference_start")
            result = runner.transcribe(audio_np, sample_rate, float(audio_epoch or 0.0))
        except AssetIntegrityError:
            raise
        except Exception as exc:
            logger.warning("Parakeet v3 unavailable (%s); trying cached recognition", exc)
            backend, model_name = "auto", _DEFAULT_MODEL
        else:
            _LAST_BACKEND = "parakeet-v3-metal"
            if timing is not None:
                timing.mark("asr_inference_done")
            return result
    if model_name == "parakeet-v3":
        model_name = _DEFAULT_MODEL

    _LAST_BACKEND = "whisper"
    try:
        model = get_whisper_model(model_name)
    except Exception as exc:
        raise RuntimeError(f"Speech model could not load: {exc}") from exc
    if timing is not None:
        timing.mark("asr_model_ready")
        timing.mark("asr_inference_start")
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
    if timing is not None:
        timing.mark("asr_inference_done")

    full_text = " ".join(text_parts).strip()
    return full_text, words


def record_microphone(
    duration_s: float = 2.5,
    sample_rate: int = 16000,
) -> bytes:
    """Record through the same single-owner native device as the Chrome talk key."""
    from ..browser.cdp_bridge import get_shared_session
    from ..runtime.service import _VOICE_TURNS, _whisper_model_name

    model_name = _whisper_model_name()
    if not recognition_ready(model_name):
        raise RuntimeError(recognition_status(model_name))
    microphone = get_shared_session().microphone
    if _VOICE_TURNS is not None:
        ready = _VOICE_TURNS.prepare_recording()
        if not ready["ok"]:
            raise RuntimeError(ready["error"])
    result = {"ok": False}
    try:
        result = microphone.start("tool", lambda: None, sample_rate=sample_rate)
        if not result["ok"]:
            raise RuntimeError(result["error"])
        if _VOICE_TURNS is not None:
            _VOICE_TURNS.capture_status("recording")
        time.sleep(duration_s)
        return microphone.stop("tool")[0]
    finally:
        if result["ok"]:
            microphone.cancel("tool")
        if _VOICE_TURNS is not None:
            _VOICE_TURNS.capture_status("idle")
