"""Parakeet TDT (0.6B) on CoreML — Apple Neural Engine from Python, in-process.

Vendored and adapted from silicon-asr 0.1.0 (``runners/parakeet_coreml.py``,
``windowing.py``, ``types.py``) — MIT licensed, Copyright (c) 2026 WT-MM.
The adaptation replaces ``coremltools.models.CompiledMLModel`` with
``asr.coreml_model.CoremlModel`` (pyobjc over CoreML.framework), because
coremltools ships no cp314 wheels. Gaze uses only the pinned v2 conversion,
verifies every file before loading and drops ``transcribe_file``: voice.py
decodes audio itself and always hands over numpy PCM.

The FastConformer encoder runs on the ANE (or GPU); the LSTM prediction
network and joint run on CPU — the ANE has no LSTM kernel, and the fused
JointDecision model already folds argmax and the TDT duration head into the
graph so the Python decode loop stays cheap.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from ..asset_cache import COREML, prepare
from .coreml_model import (
    COMPUTE_ALL,
    COMPUTE_CPU_AND_GPU,
    COMPUTE_CPU_AND_NE,
    COMPUTE_CPU_ONLY,
    CoremlModel,
)

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
WINDOW_SAMPLES = 15 * SAMPLE_RATE  # fixed 15 s encoder input
ENCODER_FRAMES = 188  # per 15 s window
SECONDS_PER_FRAME = 15.0 / ENCODER_FRAMES
DEFAULT_OVERLAP_SECONDS = 3.0
MAX_SYMBOLS_PER_FRAME = 10

SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
MAX_SEGMENT_SECONDS = 6.0
SEGMENT_GAP_SECONDS = 0.8

TimedId = Tuple[float, int]  # (absolute seconds, token id)


@dataclass
class Token:
    """A decoded token with its emission time (seconds from audio start)."""

    start: float
    text: str


@dataclass
class Segment:
    """A subtitle-sized span of transcribed speech."""

    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    text: str
    segments: List[Segment]
    tokens: List[Token] = field(default_factory=list)


def tokens_to_segments(tokens: List[Token]) -> List[Segment]:
    """Group tokens into subtitle-sized segments.

    Splits at sentence-ending punctuation, long inter-token gaps, or when a
    segment exceeds MAX_SEGMENT_SECONDS.
    """
    segments: List[Segment] = []
    current: List[Token] = []

    def flush() -> None:
        if not current:
            return
        text = "".join(t.text for t in current).replace("▁", " ").strip()
        if text:
            segments.append(Segment(start=current[0].start, end=current[-1].start + 0.5, text=text))
        current.clear()

    for token in tokens:
        if current:
            gap = token.start - current[-1].start
            too_long = token.start - current[0].start > MAX_SEGMENT_SECONDS
            ended = current[-1].text.rstrip().endswith(SENTENCE_ENDINGS)
            if ended or gap > SEGMENT_GAP_SECONDS or too_long:
                flush()
        current.append(token)
    flush()
    return segments


def iter_windows(
    audio: np.ndarray, window_samples: int, overlap_samples: int
) -> Iterator[Tuple[int, np.ndarray, int]]:
    """Yield (start_sample, padded_chunk, n_valid_samples) fixed-size windows."""
    hop = window_samples - overlap_samples
    for start in range(0, max(len(audio) - overlap_samples, 1), hop):
        chunk = audio[start : start + window_samples]
        n_valid = len(chunk)
        if n_valid < window_samples:
            chunk = np.pad(chunk, (0, window_samples - n_valid))
        yield start, chunk, n_valid


def stitch_windows(
    windows: List[List[TimedId]], starts: List[int], overlap_samples: int
) -> List[TimedId]:
    """Merge overlapped windows, cutting each overlap at its largest silence."""
    overlap_s = overlap_samples / SAMPLE_RATE
    merged: List[TimedId] = []
    prev_cut = 0.0
    for i, window in enumerate(windows):
        if i == len(windows) - 1:
            cut = float("inf")
        else:
            ov_lo = starts[i + 1] / SAMPLE_RATE
            ov_hi = ov_lo + overlap_s
            in_overlap = [at for at, _ in window if ov_lo <= at < ov_hi]
            points = [ov_lo, *in_overlap, ov_hi]
            gaps = [
                (points[j + 1] - points[j], (points[j + 1] + points[j]) / 2)
                for j in range(len(points) - 1)
            ]
            cut = max(gaps)[1]
        merged.extend(item for item in window if prev_cut <= item[0] < cut)
        prev_cut = cut
    return merged


@dataclass(frozen=True)
class TdtVariant:
    model_id: str
    vocab_file: str
    blank_id: int  # = the joint's class count minus one; NOT always len(vocab)


TDT_VARIANTS = {
    # v2's vocab json has stray entries past 1024; the model's blank is 1024.
    "v2": TdtVariant(
        COREML, "parakeet_vocab.json", 1024
    ),
}

ENCODER_UNIT_NAMES = ("auto", "ane", "gpu", "cpu", "all")


def encoder_compute_units(name: str) -> int:
    """Map a compute-units name to an MLComputeUnits ordinal for the encoder."""
    units = {
        "auto": COMPUTE_CPU_AND_NE,
        "ane": COMPUTE_CPU_AND_NE,
        "gpu": COMPUTE_CPU_AND_GPU,
        "cpu": COMPUTE_CPU_ONLY,
        "all": COMPUTE_ALL,
    }.get(name)
    if units is None:
        raise ValueError(
            f"compute_units must be one of {'/'.join(ENCODER_UNIT_NAMES)}, got {name!r}"
        )
    return units


class ParakeetCoreML:
    def __init__(
        self,
        variant: str = "v2",
        compute_units: str = "auto",
        overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    ) -> None:
        if variant != "v2":
            raise ValueError("Only pinned CoreML Parakeet v2 is supported; v3 has unresolved licence terms.")
        spec = TDT_VARIANTS[variant]
        self.name = f"parakeet-{variant}-coreml"
        units = encoder_compute_units(compute_units)
        self._overlap = int(overlap_seconds * SAMPLE_RATE)

        root = prepare(spec.model_id)

        t0 = time.time()
        self._mel = CoremlModel(f"{root}/Melspectrogram_v2.mlmodelc", COMPUTE_CPU_ONLY)
        self._encoder = CoremlModel(f"{root}/Encoder.mlmodelc", units)
        # Decoder and joint pinned to CPU: no ANE LSTM kernel, and the tiny
        # per-step calls are fastest there.
        self._decoder = CoremlModel(f"{root}/Decoder.mlmodelc", COMPUTE_CPU_ONLY)
        self._joint = CoremlModel(f"{root}/JointDecision.mlmodelc", COMPUTE_CPU_ONLY)
        with open(f"{root}/{spec.vocab_file}", encoding="utf-8") as f:
            self._vocab = {int(k): v for k, v in json.load(f).items()}
        self._blank = spec.blank_id
        logger.info("Loaded %s (%s encoder) in %.2fs", spec.model_id, compute_units, time.time() - t0)

    def _encode(self, audio: np.ndarray, n_valid: int) -> Tuple[np.ndarray, int]:
        mel = self._mel.predict(
            {
                "audio_signal": audio[None, :].astype(np.float32),
                "audio_length": np.array([n_valid], dtype=np.int32),
            }
        )
        out = self._encoder.predict(
            {
                "mel": mel["melspectrogram"].astype(np.float32),
                "mel_length": mel["melspectrogram_length"].astype(np.int32),
            }
        )
        return out["encoder"].astype(np.float32), int(out["encoder_length"][0])

    def _decoder_step(
        self, token: int, h: np.ndarray, c: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        out = self._decoder.predict(
            {
                "targets": np.array([[token]], dtype=np.int32),
                "target_length": np.array([1], dtype=np.int32),
                "h_in": h,
                "c_in": c,
            }
        )
        return (
            out["decoder"].astype(np.float32),
            out["h_out"].astype(np.float32),
            out["c_out"].astype(np.float32),
        )

    def _decode_window(self, audio: np.ndarray, n_valid: int) -> List[TimedId]:
        """TDT greedy decode of one window -> [(window-relative seconds, token id)]."""
        enc, n_frames = self._encode(audio, n_valid)

        h = np.zeros((2, 1, 640), np.float32)
        c = np.zeros((2, 1, 640), np.float32)
        dec_out, h, c = self._decoder_step(self._blank, h, c)

        emitted: List[TimedId] = []
        t = 0
        symbols_here = 0
        while t < n_frames:
            j = self._joint.predict(
                {"encoder_step": np.ascontiguousarray(enc[:, :, t : t + 1]), "decoder_step": dec_out}
            )
            token = int(j["token_id"].reshape(-1)[0])
            duration = int(j["duration"].reshape(-1)[0])
            if token != self._blank:
                emitted.append((t * SECONDS_PER_FRAME, token))
                dec_out, h, c = self._decoder_step(token, h, c)
                symbols_here += 1
            if duration > 0:
                t += duration
                symbols_here = 0
            elif token == self._blank or symbols_here >= MAX_SYMBOLS_PER_FRAME:
                t += 1
                symbols_here = 0
        return emitted

    def transcribe_array(self, audio: np.ndarray) -> TranscriptionResult:
        """Transcribe 16 kHz mono float32 audio of any length."""
        windows: List[List[TimedId]] = []
        starts: List[int] = []
        for start, chunk, n_valid in iter_windows(audio, WINDOW_SAMPLES, self._overlap):
            base = start / SAMPLE_RATE
            windows.append([(base + at, tok) for at, tok in self._decode_window(chunk, n_valid)])
            starts.append(start)

        merged = stitch_windows(windows, starts, self._overlap)
        tokens = [Token(start=at, text=self._vocab.get(tok, "")) for at, tok in merged]
        text = "".join(t.text for t in tokens).replace("▁", " ").strip()
        return TranscriptionResult(text=text, segments=tokens_to_segments(tokens), tokens=tokens)


