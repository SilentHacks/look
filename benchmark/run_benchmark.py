"""Quantitative accuracy benchmark for look across noise levels (sigma = 80, 130, 180 px).

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

def _recorded_fixations(samples: list[dict], index: int, cx: float, cy: float) -> list[FixationSample]:
    """Translate held-out measured residuals to the dashboard; no generated noise."""
    last = samples[index % len(samples)]
    if last["prediction"] is None:
        return []  # A missing current observation must remain a miss.
    window = [last]
    if last["temporal"]:
        for offset in (1, 2):
            at = index % len(samples) - offset
            if at < 0:
                break
            row = samples[at]
            if row["person"] != last["person"] or row["session"] != last["session"] or not 0 < last["t"] - row["t"] <= .4:
                break
            window.insert(0, row)
    fixations = []
    for row in window:
        if row["prediction"] is None:
            continue
        width, height = row["screen"]
        dx = (row["prediction"][0] - row["target"][0]) / width * 1280
        dy = (row["prediction"][1] - row["target"][1]) / height * 900
        t = 9.81 + (row["t"] - last["t"] if last["temporal"] else 0)
        fixations.append(FixationSample(x_doc=cx + dx, y_doc=cy + dy, x_vp=cx + dx, y_vp=cy + dy,
                                       t_start=t - .1, t_end=t, duration_ms=100., sigma_x=120., sigma_y=120.,
                                       source="webcam"))
    return fixations



def run_benchmark_suite(trials_per_sigma: int = 60, seed: int = 42, *,
                        gaze_trace: list[dict] | None = None) -> Dict[str, Dict]:
    """Synthetic noise by default; optional held-out gaze residuals on a 1280×900 dashboard."""
    if trials_per_sigma < 1 or gaze_trace == []:
        raise ValueError("Need positive trials and a non-empty trace")
    rng = random.Random(seed)
    candidates = build_synthetic_dashboard_candidates()
    scenarios = [
        ("btn-purge-cache", "What happens if I press this purge button?"),
        ("btn-export-csv", "Download this CSV file"),
        ("btn-generate-report", "Open this report builder"),
        ("btn-run-query", "Press this to run query"),
        ("campaigns-table", "Export these results and make me a chart"),
    ]
    sigmas = [80, 130, 180] if gaze_trace is None else ["recorded"]
    results: Dict[str, Dict] = {
        "raw_hit_test": {},
        "spatial_box_only": {},
        "fusion_top1": {},
        "top3_coverage": {},
        "full_with_lens": {},
    }

    for sigma in sigmas:
        sigma_px = float(sigma) if gaze_trace is None else 120.
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
            if gaze_trace is not None:
                fixations = _recorded_fixations(gaze_trace, i, cx, cy)
                if not fixations:
                    continue  # Missing/off-screen measured predictions count as misses.
            else:
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
                # Synthetic distractor: never added to measured traces.
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
            last_f = fixations[-2] if gaze_trace is None else fixations[-1]
            if _point_in_rect(last_f.x_doc, last_f.y_doc, target.rect_doc):
                hits_raw += 1

            # 2. Spatial Box-Integral only (no temporal alignment or verb-role semantics)
            best_spatial = max(
                candidates,
                key=lambda c: gaussian_box_integral(c.rect_doc, last_f.x_doc, last_f.y_doc, sigma_px, sigma_px),
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


def format_benchmark_markdown(results: Dict[str, Dict]) -> str:
    columns = list(results["raw_hit_test"])
    labels = {80: "σ = 80 px (~2°)", 130: "σ = 130 px (~3°, typical webcam)",
              180: "σ = 180 px (~4.2°, head drift)", "recorded": "Recorded residuals (σ = 120 px)"}
    names = {"raw_hit_test": "1. Raw Gaze Point Hit-Test (`elementFromPoint`)",
             "spatial_box_only": "2. Spatial Box-Integral + DOM Prior",
             "fusion_top1": "3. Temporal Alignment + Bayesian Semantic Fusion (top-1)",
             "top3_coverage": "4. Fusion Top-3 Coverage",
             "full_with_lens": "5. Full System (top-3 coverage × 0.97 modeled pick)"}
    lines = ["| Resolution Method | " + " | ".join(labels[c] for c in columns) + " |",
             "|---|" + "---|" * len(columns)]
    for key, name in names.items():
        lines.append("| " + name + " | " + " | ".join(f"{results[key][c]}%" for c in columns) + " |")
    if columns == ["recorded"]:
        lines += ["", "Measured held-out residuals are rescaled by screen dimensions to 1280×900 and translated to synthetic dashboard targets.",
                  "This measures the existing resolver, not real spoken-question accuracy or a paid/hosted model. The Lens row remains a modeled assumption."]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--gaze-trace", type=Path, help="held-out *-trace.json from gaze_eval score")
    parser.add_argument("--trials", type=int, default=60)
    args = parser.parse_args()
    trace = json.loads(args.gaze_trace.read_text())["samples"] if args.gaze_trace else None
    print(format_benchmark_markdown(run_benchmark_suite(args.trials, gaze_trace=trace)))
