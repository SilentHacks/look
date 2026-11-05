"""Hermes Agent tools for hermes-gaze: gaze_resolve, gaze_choose, gaze_highlight, gaze_calibrate, gaze_benchmark."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from . import service
from .benchmark.run_benchmark import format_benchmark_markdown, run_benchmark_suite
from .browser.cdp_bridge import get_shared_session
from .resolver.bayesian_fusion import LENS_MAX_CARDS
from .resolver.data_extractor import extract_structured_data, render_svg_scatter


def _schema(name: str, description: str, properties: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


GAZE_RESOLVE_SCHEMA = _schema(
    "gaze_resolve",
    "Resolve what DOM element(s) the user is pointing or looking at in Chrome when saying a deictic phrase "
    "like 'what happens if I press this?', 'download this', 'export these results', or 'compare this one with this one'. "
    "Returns ranked candidates with probabilities, consequence previews, and renders pins or the Semantic Lens in Chrome.",
    {
        "utterance": {
            "type": "string",
            "description": "The spoken or typed user utterance containing deictic references ('this', 'these', 'that').",
        },
        "mode": {
            "type": "string",
            "enum": ["hover", "simulated"],
            "description": "Optional pointing mode override ('hover' for exact cursor, 'simulated' for noisy gaze).",
        },
        "target_hint_x": {
            "type": "number",
            "description": "Optional viewport X coordinate (used in headless/offline testing when Chrome is not focused).",
        },
        "target_hint_y": {
            "type": "number",
            "description": "Optional viewport Y coordinate (used in headless/offline testing when Chrome is not focused).",
        },
        "record_voice": {
            "type": "boolean",
            "description": "Record the microphone for duration_s and resolve the transcribed utterance instead of 'utterance'.",
        },
        "duration_s": {
            "type": "number",
            "description": "Microphone recording length in seconds when record_voice is true (default 2.6).",
        },
        "word_timestamps": {
            "type": "array",
            "items": {"type": "object"},
            "description": "Optional [{word, start, end}] wall-clock word timestamps to anchor deictics temporally.",
        },
    },
    required=["utterance"],
)

GAZE_CHOOSE_SCHEMA = _schema(
    "gaze_choose",
    "Select a numbered candidate (1-4) from an open Semantic Lens disambiguation overlay, execute or confirm it, "
    "and update the implicit online drift recalibrator.",
    {
        "candidate_index": {
            "type": "integer",
            "minimum": 1,
            "maximum": LENS_MAX_CARDS,
            "description": "1-based index of the candidate card in the Semantic Lens (e.g. 1 for [1]).",
        },
        "execute": {
            "type": "boolean",
            "description": "Whether to click/activate the chosen DOM element in Chrome (default true).",
        },
    },
    required=["candidate_index"],
)

GAZE_HIGHLIGHT_SCHEMA = _schema(
    "gaze_highlight",
    "Pin one or more DOM elements in Chrome's Shadow-DOM overlay and display a concise answer or SVG chart in the bottom HUD.",
    {
        "selector": {
            "type": "string",
            "description": "CSS selector of the target element to pin (e.g. '#btn-purge-cache' or '#campaigns-table').",
        },
        "label": {
            "type": "string",
            "description": "Short badge label for the pin (e.g. 'Purge Cache').",
        },
        "hud_message": {
            "type": "string",
            "description": "Concise explanation or HTML/SVG snippet to display in the bottom glassmorphic HUD.",
        },
        "extract_table": {
            "type": "boolean",
            "description": "If true and the target is a <table>, extract its rows as CSV/Markdown and render an inline SVG scatter plot.",
        },
    },
    required=["selector", "hud_message"],
)

GAZE_CALIBRATE_SCHEMA = _schema(
    "gaze_calibrate",
    "Configure or reset the pointing/gaze tracker mode ('hover', 'simulated'), spatial uncertainty sigma, "
    "and online drift recalibrator.",
    {
        "mode": {
            "type": "string",
            "enum": ["hover", "simulated"],
            "description": "Pointing mode to activate.",
        },
        "sigma_px": {
            "type": "number",
            "description": "Spatial uncertainty standard deviation in CSS pixels (default 120.0 for simulated).",
        },
        "reset_drift": {
            "type": "boolean",
            "description": "Reset the online drift recalibrator bias offset to (0, 0).",
        },
    },
)

GAZE_BENCHMARK_SCHEMA = _schema(
    "gaze_benchmark",
    "Run the quantitative reference resolution benchmark across spatial noise levels (sigma = 80, 130, 180 px) "
    "comparing raw gaze hit-testing vs. spatial box integration vs. full Bayesian fusion + Semantic Lens.",
    {
        "trials_per_sigma": {
            "type": "integer",
            "minimum": 10,
            "maximum": 500,
            "description": "Number of Monte Carlo trials per noise level (default 60).",
        },
    },
)


def check_gaze_requirements() -> bool:
    """Passive check (never installs packages).

    MUST stay constant-true: Hermes re-probes check_fn every turn and drops the
    tool schema when it returns False, mutating the tool surface mid-conversation
    and breaking prompt caching. Chrome health is reported in-band in payloads.
    """
    return True


def handle_gaze_resolve(args: Dict[str, Any], **kwargs: Any) -> str:
    session = get_shared_session()
    hint_x = args.get("target_hint_x")
    hint_y = args.get("target_hint_y")
    if hint_x is not None and hint_y is not None:
        # Record the hint BEFORE the pull so the resolver has at least one fixation.
        session.tracker.record_point(float(hint_x), float(hint_y), timestamp=time.time())
    payload = service.resolve_now(
        session,
        utterance=str(args.get("utterance") or "").strip(),
        words=args.get("word_timestamps"),
        mode=str(args.get("mode") or session.tracker.mode or "hover"),
        record_voice=bool(args.get("record_voice", False)),
        duration_s=float(args.get("duration_s", 2.6)),
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_gaze_choose(args: Dict[str, Any], **kwargs: Any) -> str:
    session = get_shared_session()
    idx = int(args.get("candidate_index", 1))
    execute = bool(args.get("execute", True))
    # Tool requests target the active resolution; binding requests supply their own epoch.
    payload = session.choose(resolution_id=session.resolution_id, candidate_index=idx, execute=execute)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_gaze_highlight(args: Dict[str, Any], **kwargs: Any) -> str:
    session = get_shared_session()
    selector = str(args.get("selector") or "")
    label = str(args.get("label") or selector)
    hud_message = str(args.get("hud_message") or "")
    extract_table = bool(args.get("extract_table", False))

    table_csv = ""
    svg_chart = ""
    if session.is_chrome_reachable():
        if extract_table:
            raw_table = session.eval_js(
                f"window.__HERMES_GAZE_OVERLAY__.extractTableData({json.dumps(selector)})",
            )
            if isinstance(raw_table, dict) and raw_table.get("rows"):
                table_csv = extract_structured_data(raw_table, fmt="csv")
                svg_chart = render_svg_scatter(
                    raw_table.get("headers") or [],
                    raw_table.get("rows") or [],
                )
        if hud_message.strip().startswith("<div"):
            full_hud = hud_message + (f"<div>{svg_chart}</div>" if svg_chart else "")
        else:
            full_hud = (
                f"<div style='font-size:13.5px;'><strong style='color:#38bdf8;'>🔍 {label}</strong></div>"
                f"<div style='margin-top:6px;color:#f8fafc;font-size:12.5px;line-height:1.45;'>{hud_message}</div>"
                + (f"<div style='margin-top:8px;'>{svg_chart}</div>" if svg_chart else "")
                + f"<div style='margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.08);display:flex;gap:12px;font-size:11px;color:#64748b;font-family:ui-monospace,monospace;'>"
                f"<span>Target: {selector}</span>"
                f"</div>"
            )
        js = f"""
        (() => {{
          const el = document.querySelector({json.dumps(selector)});
          const rect = el ? el.getBoundingClientRect() : {{left: 100, top: 100, width: 120, height: 36}};
          const pin = [{{
            selector: {json.dumps(selector)},
            label: {json.dumps(label)},
            rect_vp: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width), Math.round(rect.height)],
            probability: 1.0
          }}];
          window.__HERMES_GAZE_OVERLAY__.renderPins(pin, {json.dumps(full_hud)});
          return true;
        }})()
        """
        session.eval_js(js)

    return json.dumps(
        {
            "ok": True,
            "selector": selector,
            "label": label,
            "chrome_connected": session.is_chrome_reachable(),
            "extracted_csv": table_csv,
            "rendered_svg_chart": bool(svg_chart),
        },
        indent=2,
        ensure_ascii=False,
    )


def handle_gaze_calibrate(args: Dict[str, Any], **kwargs: Any) -> str:
    session = get_shared_session()
    mode = str(args.get("mode") or session.tracker.mode or "hover")
    sigma_px = float(args.get("sigma_px", session.tracker.sigma_px))
    if args.get("reset_drift"):
        session.recalibrator.reset()

    # session.configure stores the values locally AND pushes them to the live overlay.
    chrome_ok = session.configure(mode=mode, sigma_px=sigma_px)

    return json.dumps(
        {
            "ok": True,
            "mode": mode,
            "sigma_px": sigma_px,
            "drift_offset": list(session.recalibrator.offset),
            "chrome_connected": chrome_ok,
        },
        indent=2,
    )


def handle_gaze_benchmark(args: Dict[str, Any], **kwargs: Any) -> str:
    trials = int(args.get("trials_per_sigma") or 60)
    results = run_benchmark_suite(trials_per_sigma=trials)
    md = format_benchmark_markdown(results)
    return json.dumps(
        {
            "ok": True,
            "trials_per_sigma": trials,
            "metrics": results,
            "markdown_table": md,
        },
        indent=2,
        ensure_ascii=False,
    )


ALL_TOOLS = (
    ("gaze_resolve", GAZE_RESOLVE_SCHEMA, handle_gaze_resolve, "👁️"),
    ("gaze_choose", GAZE_CHOOSE_SCHEMA, handle_gaze_choose, "🎯"),
    ("gaze_highlight", GAZE_HIGHLIGHT_SCHEMA, handle_gaze_highlight, "✨"),
    ("gaze_calibrate", GAZE_CALIBRATE_SCHEMA, handle_gaze_calibrate, "🧭"),
    ("gaze_benchmark", GAZE_BENCHMARK_SCHEMA, handle_gaze_benchmark, "📊"),
)
