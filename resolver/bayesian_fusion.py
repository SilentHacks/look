"""Bayesian spatial-semantic reference resolver and consequence policy engine.

Combines:
1. 2D Gaussian Box Integral over candidate bounding boxes using math.erf (stdlib).
2. Intent Verb -> Role & Granularity Compatibility Matrix (atomic button vs parent table/card).
3. Lexical token overlap (BM25-style boost).
4. Optional ctx.llm structured re-ranking and consequence preview generation.
5. Consequence-aware decision policy (read-only vs reversible vs confirmation-required vs Semantic Lens).
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..tracker.simulated_gaze import FixationSample
from .temporal_aligner import DeicticAnchor, align_fixations_to_utterance

_ACTION_VERBS = frozenset({
    "click", "press", "push", "tap", "open", "toggle", "select", "choose", "switch", "run", "schedule",
})
_DESTRUCTIVE_VERBS = frozenset({
    "delete", "remove", "purge", "drop", "destroy", "pay", "buy", "checkout", "submit", "send", "transfer", "revoke",
})
_DATA_CONTAINER_VERBS = frozenset({
    "export", "download", "chart", "plot", "graph", "table", "rows", "results", "sort", "filter", "copy", "compare",
})
_READONLY_PATTERNS = (
    "what happens",
    "what does",
    "what is",
    "explain",
    "summarize",
    "tell me about",
    "describe",
    "why is",
    "inspect",
)

_INTERACTIVE_ROLES = frozenset({
    "button", "link", "a", "menuitem", "tab", "checkbox", "radio", "switch", "textbox", "input", "select", "combobox",
})
_CONTAINER_ROLES = frozenset({
    "table", "grid", "row", "tr", "section", "article", "form", "list", "ul", "ol", "card", "region", "pre",
})
_LEAF_DATA_ROLES = frozenset({
    "columnheader", "cell", "th", "td", "term", "definition", "heading", "h1", "h2", "h3", "abbr", "label",
})


@dataclass
class CandidateElement:
    """A candidate DOM / Accessibility element extracted from Chrome."""

    id: str
    tag: str
    role: str
    label: str
    selector: str
    rect_doc: Tuple[float, float, float, float]  # (x, y, width, height) in document space
    rect_vp: Tuple[float, float, float, float]   # (x, y, width, height) in viewport space
    is_container: bool = False
    is_interactive: bool = True
    is_destructive: bool = False
    summary: str = ""
    consequence: str = ""
    backend_node_id: Optional[int] = None
    parent_container_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def center_doc(self) -> Tuple[float, float]:
        x, y, w, h = self.rect_doc
        return (x + 0.5 * w, y + 0.5 * h)

    @property
    def center_vp(self) -> Tuple[float, float]:
        x, y, w, h = self.rect_vp
        return (x + 0.5 * w, y + 0.5 * h)

    @property
    def area(self) -> float:
        return max(1.0, self.rect_doc[2] * self.rect_doc[3])


@dataclass
class ScoredCandidate:
    candidate: CandidateElement
    probability: float
    spatial_score: float
    semantic_score: float
    prior_score: float
    consequence_preview: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self.candidate)
        d["probability"] = round(self.probability, 4)
        d["spatial_score"] = round(self.spatial_score, 4)
        d["semantic_score"] = round(self.semantic_score, 4)
        d["consequence_preview"] = self.consequence_preview
        return d


@dataclass
class ResolutionResult:
    utterance: str
    intent_class: str  # "read_only" | "reversible_action" | "destructive_action"
    decision: str      # "pin_immediate" | "execute_safe" | "open_semantic_lens" | "confirm_destructive"
    ranked: List[ScoredCandidate]
    multi_referents: List[ScoredCandidate] = field(default_factory=list)
    anchor_timestamp: float = 0.0

    @property
    def top(self) -> Optional[ScoredCandidate]:
        return self.ranked[0] if self.ranked else None

    @property
    def margin(self) -> float:
        if len(self.ranked) >= 2:
            return self.ranked[0].probability - self.ranked[1].probability
        return self.ranked[0].probability if self.ranked else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "utterance": self.utterance,
            "intent_class": self.intent_class,
            "decision": self.decision,
            "margin": round(self.margin, 4),
            "top": self.top.to_dict() if self.top else None,
            "ranked": [c.to_dict() for c in self.ranked[:6]],
            "multi_referents": [c.to_dict() for c in self.multi_referents],
        }


def gaussian_box_integral(
    rect: Tuple[float, float, float, float],
    mu_x: float,
    mu_y: float,
    sigma_x: float,
    sigma_y: float,
    margin_px: float = 6.0,
    area_exponent: float = 0.40,
    area_floor: float = 1200.0,
) -> float:
    """Integrate 2D Gaussian N((mu_x, mu_y), diag(sigma_x^2, sigma_y^2)) over padded bounding box."""
    x, y, w, h = rect
    x1 = x - margin_px
    x2 = x + w + margin_px
    y1 = y - margin_px
    y2 = y + h + margin_px
    sx = max(sigma_x, 12.0) * math.sqrt(2.0)
    sy = max(sigma_y, 12.0) * math.sqrt(2.0)
    px = 0.5 * abs(math.erf((x2 - mu_x) / sx) - math.erf((x1 - mu_x) / sx))
    py = 0.5 * abs(math.erf((y2 - mu_y) / sy) - math.erf((y1 - mu_y) / sy))
    area_norm = (max(w * h, 1.0) + area_floor) ** area_exponent
    return max((px * py) / area_norm, 1e-12)


def classify_utterance_intent(utterance: str) -> str:
    low = (utterance or "").strip().lower()
    if any(pat in low for pat in _READONLY_PATTERNS) or low.endswith("?"):
        return "read_only"
    tokens = set(re.findall(r"[a-z]+", low))
    if tokens & _DESTRUCTIVE_VERBS:
        return "destructive_action"
    return "reversible_action"


def default_consequence_preview(cand: CandidateElement, intent_class: str) -> str:
    if cand.consequence:
        return cand.consequence
    label = cand.label or cand.selector
    low_label = label.lower()
    if cand.summary:
        return cand.summary
    if cand.role in ("columnheader", "th") or cand.tag == "th":
        return f"Column header '{label}'"
    if cand.role in ("cell", "td") or cand.tag == "td":
        return f"Table data cell '{label}'"
    if cand.role in ("table", "grid") or cand.tag == "table":
        return f"Table containing data rows/columns"
    if any(k in low_label for k in ("delete", "remove", "purge", "revoke", "drop")):
        return f"High-consequence action on '{label}' (requires confirmation)"
    if "csv" in low_label or "export" in low_label:
        return f"Downloads data via '{label}' as CSV file"
    if "report" in low_label or "pdf" in low_label:
        return f"Opens report builder / configuration modal for '{label}'"
    if intent_class == "read_only":
        return f"Inspects '{label}' ({cand.role})"
    return f"Triggers {cand.role} '{label}' ({cand.selector})"


def _lexical_and_role_score(
    cand: CandidateElement,
    utterance: str,
    anchor: DeicticAnchor,
    intent_class: str,
) -> Tuple[float, float]:
    """Return (semantic_log_score, prior_log_score) in 0 ms before any LLM call."""
    low = (utterance or "").lower()
    utt_tokens = set(re.findall(r"[a-z0-9]+", low))
    cand_text = f"{cand.label} {cand.summary} {cand.selector} {cand.role}".lower()
    cand_tokens = set(re.findall(r"[a-z0-9]+", cand_text))

    overlap = len((utt_tokens & cand_tokens) - {"this", "that", "these", "those", "the", "and", "what", "if"})
    sem_score = overlap * 1.35

    role_low = (cand.role or cand.tag).lower()
    is_interactive = cand.is_interactive or (role_low in _INTERACTIVE_ROLES)
    is_container = cand.is_container or (role_low in _CONTAINER_ROLES)
    is_leaf_data = (role_low in _LEAF_DATA_ROLES) or cand.tag.lower() in ("th", "td", "abbr")

    # Granularity promotion: plural deictic ("these results") or data verbs ("export", "chart", "compare")
    wants_container = anchor.is_plural or bool(utt_tokens & _DATA_CONTAINER_VERBS)
    wants_atomic_action = bool(utt_tokens & (_ACTION_VERBS | _DESTRUCTIVE_VERBS)) and not anchor.is_plural

    prior_score = 0.0
    if wants_container:
        if is_container and role_low in ("table", "grid", "list", "ul", "section", "card"):
            sem_score += 2.6
        elif is_interactive and any(k in cand_text for k in ("export", "csv", "download", "report")):
            sem_score += 2.2
        else:
            prior_score -= 0.8
    elif wants_atomic_action:
        if is_interactive and not is_container:
            sem_score += 2.2
        elif is_container:
            sem_score -= 2.2
    else:
        if intent_class == "read_only":
            if is_leaf_data:
                prior_score += 1.8
            elif is_interactive and not is_container:
                prior_score += 1.2
            elif is_container:
                prior_score -= 2.2
        else:
            if is_interactive:
                prior_score += 0.6
            elif is_container:
                prior_score -= 0.8

    if intent_class == "read_only" and is_interactive and bool(utt_tokens & {"press", "click", "button"}):
        sem_score += 1.5

    return sem_score, prior_score


def _score_for_single_anchor(
    candidates: Sequence[CandidateElement],
    weighted_fixations: Sequence[Tuple[FixationSample, float]],
    utterance: str,
    anchor: DeicticAnchor,
    intent_class: str,
) -> List[ScoredCandidate]:
    if not candidates:
        return []

    raw_scores: List[Tuple[CandidateElement, float, float, float, float]] = []
    for cand in candidates:
        spatial_sum = 0.0
        for fix, w_time in weighted_fixations:
            p_box = gaussian_box_integral(
                cand.rect_doc,
                mu_x=fix.x_doc,
                mu_y=fix.y_doc,
                sigma_x=fix.sigma_x,
                sigma_y=fix.sigma_y,
            )
            spatial_sum += w_time * p_box
        log_spatial = math.log(max(spatial_sum, 1e-12))
        sem_score, prior_score = _lexical_and_role_score(cand, utterance, anchor, intent_class)
        total_log = log_spatial + sem_score + prior_score
        raw_scores.append((cand, total_log, log_spatial, sem_score, prior_score))

    max_log = max(item[1] for item in raw_scores)
    exp_scores = [math.exp(item[1] - max_log) for item in raw_scores]
    denom = sum(exp_scores) or 1.0

    scored: List[ScoredCandidate] = []
    for (cand, _tot, log_sp, sem, pri), ex in zip(raw_scores, exp_scores):
        prob = ex / denom
        preview = default_consequence_preview(cand, intent_class)
        scored.append(
            ScoredCandidate(
                candidate=cand,
                probability=prob,
                spatial_score=log_sp,
                semantic_score=sem,
                prior_score=pri,
                consequence_preview=preview,
            )
        )
    scored.sort(key=lambda s: s.probability, reverse=True)
    return scored


def resolve_candidates(
    candidates: Sequence[CandidateElement],
    fixations: Sequence[FixationSample],
    utterance: str,
    t_arm: float,
    word_timestamps: Optional[Sequence[Dict[str, object]]] = None,
    llm_client: Optional[Any] = None,
) -> ResolutionResult:
    """Run full spatial-temporal-semantic Bayesian resolution across candidates."""
    intent_class = classify_utterance_intent(utterance)
    aligned = align_fixations_to_utterance(fixations, utterance, t_arm=t_arm, word_timestamps=word_timestamps)

    multi_referents: List[ScoredCandidate] = []
    primary_ranked: List[ScoredCandidate] = []

    for idx, (anchor, weighted_fixations) in enumerate(aligned):
        ranked = _score_for_single_anchor(candidates, weighted_fixations, utterance, anchor, intent_class)
        if idx == 0:
            primary_ranked = ranked
        if ranked:
            # Avoid picking the exact same element twice for "compare this one with this one"
            chosen = ranked[0]
            if multi_referents and len(ranked) > 1 and chosen.candidate.id == multi_referents[-1].candidate.id:
                chosen = ranked[1]
            multi_referents.append(chosen)

    # Optional LLM re-ranker when top candidate is ambiguous and ctx.llm is supplied
    if (
        llm_client is not None
        and len(primary_ranked) >= 2
        and (primary_ranked[0].probability < 0.88 or (primary_ranked[0].probability - primary_ranked[1].probability) < 0.45)
    ):
        _try_llm_rerank(primary_ranked[:5], utterance, llm_client)

    top = primary_ranked[0] if primary_ranked else None
    margin = (primary_ranked[0].probability - primary_ranked[1].probability) if len(primary_ranked) >= 2 else (top.probability if top else 0.0)

    is_destructive = (
        intent_class == "destructive_action"
        or (top is not None and (top.candidate.is_destructive or any(k in top.candidate.label.lower() for k in ("delete", "purge", "remove", "pay", "revoke"))))
    )

    if top is None:
        decision = "pin_immediate"
    elif intent_class == "read_only":
        decision = "pin_immediate"
    elif is_destructive:
        decision = "confirm_destructive"
    elif top.probability >= 0.76 and margin >= 0.26:
        decision = "execute_safe"
    else:
        decision = "open_semantic_lens"

    return ResolutionResult(
        utterance=utterance,
        intent_class=intent_class,
        decision=decision,
        ranked=primary_ranked,
        multi_referents=multi_referents if len(multi_referents) >= 2 else [],
        anchor_timestamp=aligned[0][0].t_anchor if aligned else t_arm,
    )


def _try_llm_rerank(
    top_candidates: List[ScoredCandidate],
    utterance: str,
    llm_client: Any,
) -> None:
    """Best-effort structured re-ranking via ctx.llm (never raises if unconfigured)."""
    try:
        items = [
            {
                "id": sc.candidate.id,
                "role": sc.candidate.role,
                "label": sc.candidate.label,
                "summary": sc.candidate.summary,
                "spatial_prob": round(sc.probability, 3),
            }
            for sc in top_candidates
        ]
        res = llm_client.complete_structured(
            instructions=(
                "Score each UI element candidate (0.0 to 1.0) for how well it matches the user's spoken "
                "utterance, and provide a concise 1-line consequence preview."
            ),
            input=[{"type": "text", "text": f"Utterance: {utterance}\nCandidates: {items}"}],
            json_mode=True,
            timeout=2.5,
        )
        if isinstance(res.parsed, dict) and isinstance(res.parsed.get("candidates"), list):
            by_id = {str(item.get("id")): item for item in res.parsed["candidates"] if isinstance(item, dict)}
            total = 0.0
            for sc in top_candidates:
                upd = by_id.get(sc.candidate.id)
                if upd:
                    llm_s = float(upd.get("score", 0.5))
                    sc.probability = sc.probability * (0.4 + 0.6 * max(0.05, min(llm_s, 1.0)))
                    if upd.get("consequence"):
                        sc.consequence_preview = str(upd["consequence"])
                total += sc.probability
            if total > 0:
                for sc in top_candidates:
                    sc.probability /= total
            top_candidates.sort(key=lambda s: s.probability, reverse=True)
    except Exception:
        return
