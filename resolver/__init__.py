"""Deictic reference resolution, temporal speech alignment, and multi-granularity DOM data extraction."""

from __future__ import annotations

from .bayesian_fusion import (
    CandidateElement,
    Decision,
    IntentClass,
    LENS_MAX_CARDS,
    ResolutionResult,
    resolve_candidates,
)
from .data_extractor import extract_structured_data, render_svg_scatter
from .temporal_aligner import DeicticAnchor, align_fixations_to_utterance, extract_deictic_anchors

__all__ = [
    "CandidateElement",
    "Decision",
    "DeicticAnchor",
    "IntentClass",
    "LENS_MAX_CARDS",
    "ResolutionResult",
    "align_fixations_to_utterance",
    "extract_deictic_anchors",
    "extract_structured_data",
    "render_svg_scatter",
    "resolve_candidates",
]
