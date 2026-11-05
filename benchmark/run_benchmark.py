"""Quantitative accuracy benchmark for hermes-gaze across noise levels (sigma = 80, 130, 180 px).

Evaluates resolution methods on a realistic dense toolbar + table + cards layout:
1. Raw Gaze Point Hit-Test (elementFromPoint)
2. Spatial Box-Integral + DOM Actionable Prior
3. Temporal Eye-Voice Alignment + Lexical/LLM Fusion (top-1) and its top-3 coverage
4. Full System (top-3 coverage x modeled Semantic Lens pick rate)
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple

from ..resolver.bayesian_fusion import CandidateElement, gaussian_box_integral, resolve_candidates
from ..tracker.simulated_gaze import FixationSample

# Modeled probability the user correctly picks the intended card in the Lens — an assumption, not a measurement.
LENS_PICK_SUCCESS = 0.97


def build_synthetic_dashboard_candidates() -> List[CandidateElement]:
    """Synthetic layout matching benchmark_page.html (dense 32px tall buttons 8px apart + table + cards)."""
    return [
        CandidateElement(
            id="btn-run-query",
            tag="button",
            role="button",
            label="Run Query",
            selector="#btn-run-query",
            rect_doc=(680.0, 28.0, 88.0, 32.0),
            rect_vp=(680.0, 28.0, 88.0, 32.0),
            consequence="Executes active SQL query against Q4 Production warehouse",
        ),
        CandidateElement(
            id="btn-schedule",
            tag="button",
            role="button",
            label="Schedule",
            selector="#btn-schedule",
            rect_doc=(776.0, 28.0, 80.0, 32.0),
            rect_vp=(776.0, 28.0, 80.0, 32.0),
            consequence="Opens cron schedule modal for recurring daily query runs",
        ),
        CandidateElement(
            id="btn-purge-cache",
            tag="button",
            role="button",
            label="Purge Cache",
            selector="#btn-purge-cache",
            rect_doc=(864.0, 28.0, 96.0, 32.0),
            rect_vp=(864.0, 28.0, 96.0, 32.0),
            is_destructive=True,
            consequence="Clears 1.4 GB of cached SQL query results for this workspace",
        ),
        CandidateElement(
            id="btn-export-csv",
            tag="button",
            role="button",
            label="Export CSV",
            selector="#btn-export-csv",
            rect_doc=(976.0, 28.0, 92.0, 32.0),
            rect_vp=(976.0, 28.0, 92.0, 32.0),
            consequence="Downloads 42-row campaign performance table immediately as raw .csv",
        ),
        CandidateElement(
            id="btn-generate-report",
            tag="button",
            role="button",
            label="Generate Report",
            selector="#btn-generate-report",
            rect_doc=(1076.0, 28.0, 118.0, 32.0),
            rect_vp=(1076.0, 28.0, 118.0, 32.0),
            consequence="Opens executive PDF report builder & chart configuration modal",
        ),
        CandidateElement(
            id="campaigns-table",
            tag="table",
            role="table",
            label="Campaign Performance Table",
            selector="#campaigns-table",
            rect_doc=(36.0, 120.0, 740.0, 260.0),
            rect_vp=(36.0, 120.0, 740.0, 260.0),
            is_container=True,
            is_interactive=False,
            summary="Table: 6 columns (Campaign, Channel, Clicks, CTR, Spend, ROAS), 5 rows",
        ),
        CandidateElement(
            id="card-hermes-pro",
            tag="article",
            role="card",
            label="Hermes-4-70B-Pro",
            selector="#card-hermes-pro",
            rect_doc=(800.0, 120.0, 420.0, 120.0),
            rect_vp=(800.0, 120.0, 420.0, 120.0),
            is_container=True,
            is_interactive=False,
            summary="Card: Hermes-4-70B-Pro · 142 tok/s · $0.80/M tokens",
        ),
        CandidateElement(
            id="card-hermes-flash",
            tag="article",
            role="card",
            label="Hermes-4-8B-Flash",
            selector="#card-hermes-flash",
            rect_doc=(800.0, 256.0, 420.0, 120.0),
            rect_vp=(800.0, 256.0, 420.0, 120.0),
            is_container=True,
            is_interactive=False,
            summary="Card: Hermes-4-8B-Flash · 410 tok/s · $0.10/M tokens",
        ),
    ]


def _point_in_rect(x: float, y: float, rect: Tuple[float, float, float, float]) -> bool:
    rx, ry, rw, rh = rect
    return rx <= x <= (rx + rw) and ry <= y <= (ry + rh)


def run_benchmark_suite(trials_per_sigma: int = 60, seed: int = 42) -> Dict[str, Dict[int, float]]:
    """Run reproducible accuracy evaluation across sigma in {80, 130, 180} px."""
    rng = random.Random(seed)
    candidates = build_synthetic_dashboard_candidates()
    scenarios = [
        ("btn-purge-cache", "What happens if I press this purge button?"),
        ("btn-export-csv", "Download this CSV file"),
        ("btn-generate-report", "Open this report builder"),
        ("btn-run-query", "Press this to run query"),
        ("campaigns-table", "Export these results and make me a chart"),
    ]
    sigmas = [80, 130, 180]
    results: Dict[str, Dict[int, float]] = {
        "raw_hit_test": {},
        "spatial_box_only": {},
        "fusion_top1": {},
        "top3_coverage": {},
        "full_with_lens": {},
    }

    for sigma in sigmas:
        hits_raw = 0
        hits_spatial = 0
        hits_fusion = 0
        hits_top3 = 0

        for i in range(trials_per_sigma):
            target_id, utterance = scenarios[i % len(scenarios)]
            target = next(c for c in candidates if c.id == target_id)
            cx, cy = target.center_doc

            # Generate 3 noisy fixations around the deictic anchor (t = 9.75s) plus 1 distractor glance at t = 10.2s
            t_arm = 10.0
            fixations: List[FixationSample] = []
            for k in range(3):
                nx = cx + rng.gauss(0.0, sigma)
                ny = cy + rng.gauss(0.0, sigma)
                t_f = 9.65 + k * 0.08
                fixations.append(
                    FixationSample(
                        x_doc=nx,
                        y_doc=ny,
                        x_vp=nx,
                        y_vp=ny,
                        t_start=t_f - 0.12,
                        t_end=t_f,
                        duration_ms=160.0,
                        sigma_x=float(sigma),
                        sigma_y=float(sigma),
                    )
                )
            # Distractor fixation at end of sentence
            fixations.append(
                FixationSample(
                    x_doc=cx + rng.gauss(180.0, sigma),
                    y_doc=cy + rng.gauss(140.0, sigma),
                    x_vp=cx,
                    y_vp=cy,
                    t_start=10.15,
                    t_end=10.25,
                    duration_ms=90.0,
                    sigma_x=float(sigma),
                    sigma_y=float(sigma),
                )
            )

            # 1. Raw Gaze Point Hit-Test (last fixation at hotkey release)
            last_f = fixations[-2]
            if _point_in_rect(last_f.x_doc, last_f.y_doc, target.rect_doc):
                hits_raw += 1

            # 2. Spatial Box-Integral only (no temporal alignment or verb-role semantics)
            best_spatial = max(
                candidates,
                key=lambda c: gaussian_box_integral(c.rect_doc, last_f.x_doc, last_f.y_doc, float(sigma), float(sigma)),
            )
            if best_spatial.id == target_id:
                hits_spatial += 1

            # 3. Temporal Eye-Voice Alignment + Bayesian Spatial-Semantic Fusion
            res = resolve_candidates(candidates, fixations, utterance, t_arm=t_arm)
            if res.top and res.top.candidate.id == target_id:
                hits_fusion += 1

            # 4. Top-3 coverage: did the target make the Semantic Lens card set at all?
            top3_ids = [sc.candidate.id for sc in res.ranked[:3]]
            if target_id in top3_ids:
                hits_top3 += 1

        results["raw_hit_test"][sigma] = round(100.0 * hits_raw / trials_per_sigma, 1)
        results["spatial_box_only"][sigma] = round(100.0 * hits_spatial / trials_per_sigma, 1)
        results["fusion_top1"][sigma] = round(100.0 * hits_fusion / trials_per_sigma, 1)
        results["top3_coverage"][sigma] = round(100.0 * hits_top3 / trials_per_sigma, 1)
        results["full_with_lens"][sigma] = round(results["top3_coverage"][sigma] * LENS_PICK_SUCCESS, 1)

    return results


def format_benchmark_markdown(results: Dict[str, Dict[int, float]]) -> str:
    r = results
    lines = [
        "| Resolution Method | σ = 80 px (~2°) | σ = 130 px (~3°, typical webcam) | σ = 180 px (~4.2°, head drift) |",
        "|---|---|---|---|",
        f"| **1. Raw Gaze Point Hit-Test (`elementFromPoint`)** | {r['raw_hit_test'][80]}% | {r['raw_hit_test'][130]}% | {r['raw_hit_test'][180]}% |",
        f"| **2. Spatial Box-Integral + DOM Prior** | {r['spatial_box_only'][80]}% | {r['spatial_box_only'][130]}% | {r['spatial_box_only'][180]}% |",
        f"| **3. Temporal Alignment + Bayesian Semantic Fusion (top-1)** | {r['fusion_top1'][80]}% | {r['fusion_top1'][130]}% | {r['fusion_top1'][180]}% |",
        f"| **4. Fusion Top-3 Coverage** | {r['top3_coverage'][80]}% | {r['top3_coverage'][130]}% | {r['top3_coverage'][180]}% |",
        f"| **5. Full System (top-3 coverage × 0.97 modeled pick)** | **{r['full_with_lens'][80]}%** | **{r['full_with_lens'][130]}%** | **{r['full_with_lens'][180]}%** |",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_benchmark_markdown(run_benchmark_suite()))
