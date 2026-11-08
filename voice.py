"""Local speech recognition helpers for hermes-gaze.

Three transcription backends behind one contract (``transcribe_audio_buffer``
— ``(text, [{word, start, end}])`` with audio-relative times shifted by
``audio_epoch``):

- Parakeet TDT on CoreML/ANE **in-process** via ``asr.parakeet_coreml``
  (macOS only, ~65-75ms for a 3s clip). coremltools ships no cp314 wheels, so
  ``asr.coreml_model`` drives ``.mlmodelc`` models through pyobjc instead.
  SentencePiece tokens with start times are grouped on ``▁`` boundaries into
  words.
- ``parakeet-mlx`` Parakeet TDT 0.6B on Apple-silicon MLX (macOS only,
  ~180ms for a 3s clip) — in-process middle tier when the CoreML runner
  cannot load. Downloads happen only during explicit preparation.
- ``faster-whisper`` (tiny.en / base.en) — fallback on Linux or when both
  Parakeet paths fail to load.

Plus sounddevice microphone capture from the default OS audio input. Optional
dependencies (numpy, faster-whisper, parakeet-mlx, pyobjc, sounddevice) are
imported lazily inside each function so importing this module never requires
them.
"""

from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
import threading
import time
import wave
from typing import Any, Dict, List, Optional, Tuple

from .asset_cache import AssetIntegrityError, AssetsMissing, COREML, MLX, WHISPER, prepare


logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "base.en"
_WHISPER_MODELS: Dict[str, Any] = {}  # per-name cache — config may switch models mid-session
_MODEL_LOCK = threading.Lock()

# English-only Parakeet TDT 0.6B v2 on MLX — best English WER of the
# parakeet family; v3 trades a little English accuracy for 24 languages.
_PARAKEET_MODEL_REPO = MLX
_PARAKEET_MODEL: Any = None  # model | False (load attempted and failed)
_PARAKEET_LOCK = threading.Lock()

# CoreML/ANE runner — in-process via asr.parakeet_coreml (pyobjc). Same TDT
# 0.6B v2 checkpoints as the MLX backend, converted for the Neural Engine.
_COREML_RUNNER: Any = None  # ParakeetCoreML | False (load attempted and failed)
_COREML_LOCK = threading.Lock()
_PREPARE_LOCK = threading.Lock()
_PREPARING = False
_PREPARATION_ERROR = ""

# Which backend served the most recent transcribe_audio_buffer call — the
# overlay labels itself "local Whisper" otherwise, which lies whenever ANE
# or MLX actually did the work.
_LAST_BACKEND: Optional[str] = None

# Base64 audio payloads from the overlay's transcribe intent are bounded before decode.
MAX_AUDIO_BYTES = 12 * 1024 * 1024


def get_whisper_model(model_name: str = _DEFAULT_MODEL) -> Any:
    """Lazy per-name singleton loader for the local faster-whisper model."""
    if model_name not in WHISPER:
        raise ValueError("Supported speech models are base.en and tiny.en; custom repositories and paths are unsupported.")
    with _MODEL_LOCK:
        model = _WHISPER_MODELS.get(model_name)
        if model is None:
            from faster_whisper import WhisperModel

            logger.info("Loading faster-whisper model '%s' on CPU (int8)...", model_name)
            root = prepare(WHISPER[model_name])
            model = WhisperModel(str(root), device="cpu", compute_type="int8", local_files_only=True)
            _WHISPER_MODELS[model_name] = model
        return model


def _get_parakeet_model() -> Any:
    """Lazy singleton for the parakeet-mlx model; None when unavailable."""
    global _PARAKEET_MODEL
    if sys.platform != "darwin":
        return None
    with _PARAKEET_LOCK:
        if _PARAKEET_MODEL is None:
            try:
                from parakeet_mlx import from_pretrained

                logger.info("Loading parakeet-mlx model '%s'...", _PARAKEET_MODEL_REPO)
                _PARAKEET_MODEL = from_pretrained(str(prepare(MLX)))
            except AssetIntegrityError:
                raise
            except AssetsMissing:
                return None
            except Exception as exc:
                logger.warning("parakeet-mlx unavailable (%s); using faster-whisper", exc)
                _PARAKEET_MODEL = False
        return _PARAKEET_MODEL or None


def _get_coreml_runner() -> Any:
    """Lazy singleton for the in-process CoreML/ANE runner; None when unavailable."""
    global _COREML_RUNNER
    if sys.platform != "darwin":
        return None
    with _COREML_LOCK:
        if _COREML_RUNNER is None:
            try:
                from .asr.parakeet_coreml import ParakeetCoreML
                import numpy as np

                logger.info("Loading Parakeet TDT on CoreML/ANE...")
                runner = ParakeetCoreML(variant="v2", compute_units="ane")
                # Loading alone leaves the first encoder/decoder prediction cold.
                runner.transcribe_array(np.zeros(16000, dtype=np.float32))
                _COREML_RUNNER = runner
            except AssetIntegrityError:
                raise
            except AssetsMissing:
                return None
            except Exception as exc:
                logger.warning("CoreML parakeet unavailable (%s); using parakeet-mlx", exc)
                _COREML_RUNNER = False
        return _COREML_RUNNER or None


def recognition_ready(model_name=_DEFAULT_MODEL):
    """Constant-time capture gate: never take a model loader lock or touch disk."""
    return (sys.platform == "darwin" and (
        _COREML_RUNNER is not None and _COREML_RUNNER is not False or
        _PARAKEET_MODEL is not None and _PARAKEET_MODEL is not False)
        or model_name in _WHISPER_MODELS)


def recognition_status(model_name=_DEFAULT_MODEL):
    if recognition_ready(model_name):
        return "Local speech recognition is ready."
    if _PREPARING or _COREML_LOCK.locked():
        return "Preparing local speech recognition. You can type with Right Option while you wait."
    if _PREPARATION_ERROR:
        return _PREPARATION_ERROR
    return "Local speech recognition is not ready. Run /gaze setup; use Right Option to type."


def prepare_recognition(model_name=_DEFAULT_MODEL, *, report=None):
    """Only explicit first-run setup may fetch; all heavy work stays off intent threads."""
    global _PREPARING
    with _PREPARE_LOCK:
        if _PREPARING or recognition_ready(model_name):
            return
        _PREPARING = True

    def work():
        global _PREPARING, _PREPARATION_ERROR, _COREML_RUNNER, _PARAKEET_MODEL
        try:
            if model_name not in WHISPER:
                raise ValueError("Supported speech models are base.en and tiny.en; custom models are unsupported.")
            loaders = ([(COREML, _get_coreml_runner), (MLX, _get_parakeet_model)]
                       if sys.platform == "darwin" else [])
            loaders.append((WHISPER[model_name], lambda: get_whisper_model(model_name)))
            for repo, load in loaders:
                prepare(repo, download=True)
                # An explicit retry may repair unavailable dependencies, not bypass checksums.
                if repo == COREML and _COREML_RUNNER is False:
                    _COREML_RUNNER = None
                if repo == MLX and _PARAKEET_MODEL is False:
                    _PARAKEET_MODEL = None
                if load() is not None:
                    break
            _PREPARATION_ERROR = ""
        except Exception as exc:
            _PREPARATION_ERROR = (str(exc) if isinstance(exc, AssetIntegrityError) or model_name not in WHISPER else
                                  "Local speech recognition could not prepare. Check internet, disk space and "
                                  "dependencies, then run /gaze setup. Use Right Option to type.")
            logger.warning("Speech recognition preparation stopped: %s", exc)
        finally:
            _PREPARING = False
            if report is not None:
                report(recognition_status(model_name))

    threading.Thread(target=work, name="gaze-asr-prepare", daemon=True).start()


def prewarm() -> None:
    """Warm verified cached models only; plugin registration never downloads."""
    if sys.platform != "darwin":
        return

    def warm():
        global _PREPARATION_ERROR
        try:
            _get_coreml_runner()
        except AssetIntegrityError as exc:
            _PREPARATION_ERROR = str(exc)
            logger.warning("Speech recognition preparation stopped: %s", exc)

    threading.Thread(target=warm, name="gaze-asr-prewarm", daemon=True).start()


def _tokens_to_words(tokens: List[Any], end_s: float, epoch_off: float) -> List[Dict[str, object]]:
    """Group SentencePiece tokens (``▁`` = word boundary) into word dicts; uses token ``end`` when present."""
    # Subword tokens mark each word start with a leading space or the
    # SentencePiece ▁ marker (parakeet-mlx does the former). When a model
    # already emits word-level tokens there are no markers and every token
    # stays its own word.
    has_boundary = any(
        (getattr(t, "text", "") or "")[:1] in (" ", "▁") for t in tokens)
    groups: List[List[Any]] = []
    for tok in tokens:
        text = getattr(tok, "text", "") or ""
        if not text.strip():
            continue
        if not has_boundary or text[:1] in (" ", "▁") or not groups:
            groups.append([])
        groups[-1].append(tok)
    words: List[Dict[str, object]] = []
    for i, group in enumerate(groups):
        text = "".join(t.text for t in group).replace("▁", " ").strip()
        if not text:
            continue
        last_end = getattr(group[-1], "end", None)
        end = float(last_end) if last_end is not None else (
            float(groups[i + 1][0].start) if i + 1 < len(groups) else end_s)
        words.append({"word": text, "start": float(group[0].start) + epoch_off,
                      "end": end + epoch_off})
    return words


def _transcribe_coreml(audio_np: Any, sample_rate: int, epoch_off: float, timing=None) -> Optional[Tuple[str, List[Dict[str, object]]]]:
    """CoreML/ANE path: feed the float32 array straight to the in-process runner."""
    runner = _get_coreml_runner()
    if runner is None:
        return None
    if timing is not None:
        timing.mark("asr_model_ready")
        timing.mark("asr_inference_start")
    try:
        res = runner.transcribe_array(audio_np)
        if timing is not None:
            timing.mark("asr_inference_done")
    except Exception as exc:
        logger.warning("coreml parakeet transcription failed (%s); using parakeet-mlx", exc)
        return None
    tokens = list(getattr(res, "tokens", None) or [])
    segs = getattr(res, "segments", None) or []
    end_s = float(segs[-1].end) if segs else (tokens[-1].start + 0.3 if tokens else 0.0)
    return (res.text or "").strip(), _tokens_to_words(tokens, end_s, epoch_off)


def _transcribe_parakeet(audio_np: Any, sample_rate: int, epoch_off: float, timing=None) -> Optional[Tuple[str, List[Dict[str, object]]]]:
    """parakeet-mlx path: write PCM to a temp WAV (the model only takes file paths)."""
    import numpy as np

    model = _get_parakeet_model()
    if model is None:
        return None
    if timing is not None:
        timing.mark("asr_model_ready")
    pcm16 = (np.clip(audio_np, -1.0, 1.0) * 32767.0).astype(np.int16)
    tmp = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm16.tobytes())
        if timing is not None:
            timing.mark("asr_inference_start")
        res = model.transcribe(tmp)
        if timing is not None:
            timing.mark("asr_inference_done")
    except Exception as exc:
        logger.warning("parakeet-mlx transcription failed (%s); using faster-whisper", exc)
        return None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    tokens = [t for s in (getattr(res, "sentences", None) or []) for t in getattr(s, "tokens", [])]
    end_s = float(tokens[-1].end) if tokens and getattr(tokens[-1], "end", None) is not None else (
        float(tokens[-1].start) + 0.3 if tokens else 0.0)
    return (res.text or "").strip(), _tokens_to_words(tokens, end_s, epoch_off)


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

    ``backend``: ``"auto"`` (CoreML Parakeet on macOS when available, else
    faster-whisper), ``"parakeet"`` (try CoreML first, same fallback), or
    ``"whisper"`` (force the faster-whisper path)."""
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
    if backend in ("auto", "parakeet"):
        result = _transcribe_coreml(audio_np, sample_rate, float(audio_epoch or 0.0), timing)
        if result is not None:
            _LAST_BACKEND = "parakeet-coreml-ane"
            return result
        result = _transcribe_parakeet(audio_np, sample_rate, float(audio_epoch or 0.0), timing)
        if result is not None:
            _LAST_BACKEND = "parakeet-mlx"
            return result

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
    from .browser.cdp_bridge import get_shared_session
    from .service import _VOICE_TURNS, _whisper_model_name

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
