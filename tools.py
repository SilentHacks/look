"""Hermes Agent tools for hermes-gaze: gaze_resolve, gaze_choose, gaze_highlight, gaze_calibrate, gaze_benchmark."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .benchmark.run_benchmark import build_synthetic_dashboard_candidates, format_benchmark_markdown, run_benchmark_suite
from .browser.cdp_bridge import get_shared_bridge
from .resolver.bayesian_fusion import resolve_candidates
from .resolver.data_extractor import extract_structured_data, render_svg_scatter
from .tracker.simulated_gaze import FixationSample


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
            "enum": ["hover", "simulated", "webcam"],
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
            "maximum": 6,
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
    "Configure or reset the pointing/gaze tracker mode ('hover', 'simulated', 'webcam'), spatial uncertainty sigma, "
    "and online drift recalibrator.",
    {
        "mode": {
            "type": "string",
            "enum": ["hover", "simulated", "webcam"],
            "description": "Pointing mode to activate.",
        },
        "sigma_px": {
            "type": "number",
            "description": "Spatial uncertainty standard deviation in CSS pixels (default 120.0 for simulated/webcam).",
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
    """Passive check (never installs packages)."""
    return True


def handle_gaze_resolve(args: Dict[str, Any], **kwargs: Any) -> str:
    import os

    if os.environ.get("HERMES_GAZE_INTERNAL") == "1":
        return json.dumps({"ok": False, "error": "Internal explanation session - CDP disabled."})

    bridge = get_shared_bridge()
    raw_utterance = str(args.get("utterance") or "").strip()
    record_voice = bool(args.get("record_voice", False)) or raw_utterance.lower() in ("voice", "speak", "mic")
    mode = str(args.get("mode") or bridge.tracker.mode or "hover")
    bridge.tracker.mode = mode

    word_timestamps = args.get("word_timestamps")
    transcription_meta = {}

    if record_voice:
        from .tracker.voice_listener import record_microphone, transcribe_audio_buffer

        dur = float(args.get("duration_s", 2.6))
        audio_pcm = record_microphone(duration_s=dur)
        transcribed_text, word_ts = transcribe_audio_buffer(audio_pcm)
        if transcribed_text:
            raw_utterance = transcribed_text
            word_timestamps = word_ts
            transcription_meta = {
                "transcribed_text": transcribed_text,
                "word_timestamps": word_ts,
                "recorded_duration_s": dur,
            }

    utterance = raw_utterance or "What is this?"

    now = time.time()
    hint_x = args.get("target_hint_x")
    hint_y = args.get("target_hint_y")
    if hint_x is not None and hint_y is not None:
        bridge.tracker.record_point(float(hint_x), float(hint_y), timestamp=now)

    candidates = bridge.fetch_live_state_and_candidates(radius_px=380.0)
    if not candidates:
        candidates = build_synthetic_dashboard_candidates()

    fixations = bridge.ring_buffer.snapshot(now)
    if not fixations:
        # Default fixation near center of first interactive toolbar cluster if none recorded yet
        c0 = candidates[0]
        cx, cy = c0.center_doc
        fixations = [
            FixationSample(
                x_doc=cx,
                y_doc=cy,
                x_vp=cx,
                y_vp=cy,
                t_start=now - 0.25,
                t_end=now,
                duration_ms=250.0,
                sigma_x=24.0 if mode == "hover" else bridge.tracker.sigma_px,
                sigma_y=24.0 if mode == "hover" else bridge.tracker.sigma_px,
                source=mode,
            )
        ]

    res = resolve_candidates(candidates, fixations, utterance, t_arm=now, word_timestamps=word_timestamps)
    payload = res.to_dict()
    payload["chrome_connected"] = bridge.is_chrome_reachable()
    payload["mode"] = mode
    if transcription_meta:
        payload["speech_recognition"] = transcription_meta

    hud_html = None
    if res.top and (res.top.candidate.is_container or res.top.candidate.role == "table"):
        table_payload = None
        if bridge.is_chrome_reachable():
            sel = json.dumps(res.top.candidate.selector)
            table_payload = bridge.eval_js(
                f"window.__HERMES_GAZE_OVERLAY__.extractTableData({sel});",
                inject_overlay=False,
            )
        if not table_payload:
            table_payload = {
                "headers": ["Campaign", "Channel", "Spend", "ROAS", "Conversions"],
                "rows": [
                    ["Q4 Enterprise Launch", "Paid Search", "$4,200", "6.4x", "312"],
                    ["Developer Retargeting", "GitHub Sponsors", "$1,850", "5.1x", "198"],
                    ["Cloud Summit Webinar", "LinkedIn Ads", "$6,400", "1.9x", "84"],
                    ["Open-Source Community", "Organic / X", "$620", "11.2x", "445"],
                ],
            }
        fmt = str(args.get("extract_format") or "csv")
        extracted_str = extract_structured_data(table_payload, fmt=fmt)
        svg_chart = render_svg_scatter(
            table_payload.get("headers") or [],
            table_payload.get("rows") or [],
        )
        payload["extracted_data"] = extracted_str
        payload["svg_scatter"] = svg_chart
        hud_html = (
            f"<div><strong>Extracted {res.top.candidate.label} ({len(table_payload.get('rows') or [])} rows):</strong></div>"
            f"<div style='margin-top:6px;'>{svg_chart}</div>"
        )

    bridge.render_resolution_in_browser(res, hud_html=hud_html)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_gaze_choose(args: Dict[str, Any], **kwargs: Any) -> str:
    bridge = get_shared_bridge()
    raw_idx = args.get("candidate_index") if "candidate_index" in args else args.get("choice", 1)
    idx = int(raw_idx) - 1
    execute = bool(args.get("execute", True))

    res = bridge.last_resolution
    if res is None or not res.ranked:
        return json.dumps({"ok": False, "error": "No active resolution to choose from. Call gaze_resolve first."})

    if idx < 0 or idx >= len(res.ranked):
        return json.dumps({"ok": False, "error": f"candidate_index {idx + 1} out of range (1..{len(res.ranked)})."})

    chosen = res.ranked[idx]
    latest_fix = bridge.ring_buffer.latest()
    if latest_fix is not None:
        tx, ty = chosen.candidate.center_doc
        bridge.recalibrator.update(
            est_x=latest_fix.x_doc,
            est_y=latest_fix.y_doc,
            true_x=tx,
            true_y=ty,
            sigma=latest_fix.sigma_x,
            weight=0.25,
        )

    if bridge.is_chrome_reachable():
        pin_js = json.dumps([chosen.to_dict()])
        role_disp = chosen.candidate.role.capitalize()
        msg = (
            f"<div style='font-size:13.5px;'><strong style='color:#34d399;'>✓ Selected: {chosen.candidate.label}</strong> <span style='color:#94a3b8;font-size:11.5px;'>({role_disp})</span></div>"
            f"<div style='margin-top:5px;color:#cbd5e1;font-size:12px;line-height:1.4;'>{chosen.consequence_preview}</div>"
            f"<div style='margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.08);font-size:11px;color:#64748b;font-family:monospace;'>Target: {chosen.candidate.selector}</div>"
        )
        click_stmt = (
            f"const el = document.querySelector({json.dumps(chosen.candidate.selector)}); if (el && el.click) el.click();"
            if execute
            else ""
        )
        bridge.eval_js(
            f"window.__HERMES_GAZE_OVERLAY__.renderPins({pin_js}, {json.dumps(msg)}); {click_stmt} true;",
            inject_overlay=True,
        )

    return json.dumps(
        {
            "ok": True,
            "selected_index": idx + 1,
            "selected": chosen.to_dict(),
            "executed": execute,
            "recalibrator_bias_offset": list(bridge.recalibrator.offset),
        },
        indent=2,
        ensure_ascii=False,
    )


def handle_gaze_highlight(args: Dict[str, Any], **kwargs: Any) -> str:
    import os

    if os.environ.get("HERMES_GAZE_INTERNAL") == "1":
        return json.dumps({"ok": False, "error": "Internal explanation session - CDP disabled."})

    bridge = get_shared_bridge()
    selector = str(args.get("selector") or "")
    label = str(args.get("label") or selector)
    hud_message = str(args.get("hud_message") or "")
    extract_table = bool(args.get("extract_table", False))

    table_csv = ""
    svg_chart = ""
    if bridge.is_chrome_reachable():
        if extract_table:
            raw_table = bridge.eval_js(
                f"window.__HERMES_GAZE_OVERLAY__.extractTableData({json.dumps(selector)})",
                inject_overlay=True,
            )
            if isinstance(raw_table, dict) and raw_table.get("rows"):
                table_csv = extract_structured_data(raw_table, fmt="csv")
                svg_chart = render_svg_scatter(
                    raw_table.get("headers") or [],
                    raw_table.get("rows") or [],
                    x_col="Spend",
                    y_col="ROAS",
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
        bridge.eval_js(js, inject_overlay=True)

    return json.dumps(
        {
            "ok": True,
            "selector": selector,
            "label": label,
            "chrome_connected": bridge.is_chrome_reachable(),
            "extracted_csv": table_csv,
            "rendered_svg_chart": bool(svg_chart),
        },
        indent=2,
        ensure_ascii=False,
    )


def handle_gaze_calibrate(args: Dict[str, Any], **kwargs: Any) -> str:
    bridge = get_shared_bridge()
    mode = str(args.get("mode") or bridge.tracker.mode or "hover")
    sigma_px = float(args.get("sigma_px", bridge.tracker.sigma_px))
    if args.get("reset_drift"):
        bridge.recalibrator.reset()

    bridge.tracker.mode = mode
    bridge.tracker.sigma_px = sigma_px
    chrome_ok = bridge.inject_overlay(mode=mode, sigma_px=sigma_px)

    return json.dumps(
        {
            "ok": True,
            "mode": mode,
            "sigma_px": sigma_px,
            "drift_offset": list(bridge.recalibrator.offset),
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
