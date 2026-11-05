"""Temporal eye/pointer-voice alignment (Griffin & Bock 2000; Kumar 2007).

Aligns spoken or typed deictic words ("this", "that", "these", "those", "here", "it")
against the 10-second FixationRingBuffer using an asymmetric skew-normal kernel peaking
at t_anchor - 250 ms. Also supports multi-referent utterances ("Compare this one with this one").
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..tracker.simulated_gaze import FixationSample

SINGULAR_DEICTICS = frozenset({"this", "that", "it", "here"})
PLURAL_DEICTICS = frozenset({"these", "those"})
ALL_DEICTICS = SINGULAR_DEICTICS | PLURAL_DEICTICS

_TOKEN_RE = re.compile(r"[a-zA-Z0-9']+")


@dataclass
class DeicticAnchor:
    """A single deictic token occurrence in an utterance."""

    word: str
    t_anchor: float
    is_plural: bool = False
    index: int = 0


def has_deictic_pronoun(text: str) -> bool:
    tokens = {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}
    return bool(tokens & ALL_DEICTICS)


def extract_deictic_anchors(
    utterance: str,
    t_arm: float,
    word_timestamps: Optional[Sequence[Dict[str, object]]] = None,
    utterance_duration_s: float = 1.8,
) -> List[DeicticAnchor]:
    """Locate deictic tokens and their timestamps (from Whisper word_timestamps or interpolated)."""
    anchors: List[DeicticAnchor] = []
    if word_timestamps:
        for item in word_timestamps:
            raw_word = str(item.get("word") or "").strip().lower()
            clean = re.sub(r"[^a-z]", "", raw_word)
            if clean in ALL_DEICTICS:
                start_v = item.get("start")
                t_start = float(start_v) if start_v is not None else t_arm
                anchors.append(
                    DeicticAnchor(
                        word=clean,
                        t_anchor=t_start,
                        is_plural=(clean in PLURAL_DEICTICS),
                        index=len(anchors),
                    )
                )
    if anchors:
        return anchors

    # Fallback when typed or when word timestamps aren't provided: interpolate across utterance tokens
    tokens = [m.group(0).lower() for m in _TOKEN_RE.finditer(utterance or "")]
    n = max(len(tokens), 1)
    for pos, tok in enumerate(tokens):
        if tok in ALL_DEICTICS:
            frac = pos / float(n)
            # If multiple deictics exist (e.g. "Compare this one with this one"), spread across the last 2.2s
            t_est = t_arm - (1.0 - frac) * min(utterance_duration_s, 2.2)
            anchors.append(
                DeicticAnchor(
                    word=tok,
                    t_anchor=t_est,
                    is_plural=(tok in PLURAL_DEICTICS),
                    index=len(anchors),
                )
            )

    if not anchors:
        anchors.append(DeicticAnchor(word="this", t_anchor=t_arm, is_plural=False, index=0))
    return anchors


def temporal_relevance_weight(
    fixation: FixationSample,
    t_anchor: float,
    peak_lead_s: float = 0.25,
    tau_before_s: float = 0.90,
    tau_after_s: float = 0.45,
) -> float:
    """Asymmetric Gaussian temporal kernel peaking at t_anchor - 250 ms."""
    t_peak = t_anchor - peak_lead_s
    dt = fixation.t_mid - t_peak
    tau = tau_before_s if dt <= 0.0 else tau_after_s
    w_time = math.exp(-0.5 * (dt / max(tau, 1e-3)) ** 2)
    w_dur = min(1.0, max(fixation.duration_ms, 40.0) / 250.0)
    return w_time * w_dur


def align_fixations_to_utterance(
    fixations: Sequence[FixationSample],
    utterance: str,
    t_arm: float,
    word_timestamps: Optional[Sequence[Dict[str, object]]] = None,
) -> List[Tuple[DeicticAnchor, List[Tuple[FixationSample, float]]]]:
    """For each deictic anchor in the utterance, return weighted fixations."""
    anchors = extract_deictic_anchors(utterance, t_arm=t_arm, word_timestamps=word_timestamps)
    results: List[Tuple[DeicticAnchor, List[Tuple[FixationSample, float]]]] = []
    for anchor in anchors:
        weighted: List[Tuple[FixationSample, float]] = []
        for f in fixations:
            w = temporal_relevance_weight(f, anchor.t_anchor)
            if w > 1e-4:
                weighted.append((f, w))
        if not weighted and fixations:
            weighted.append((fixations[-1], 1.0))
        results.append((anchor, weighted))
    return results


