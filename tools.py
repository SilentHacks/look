"""Hermes tools for cursor evidence, snapshot highlighting and guarded actions."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .runtime import service
from .benchmark.run_benchmark import format_benchmark_markdown, run_benchmark_suite
from .browser.cdp_bridge import get_shared_session
from .resolver.bayesian_fusion import LENS_MAX_CARDS


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
    "Hover returns exact pointer evidence, surrounding structure and snapshot handles; the model chooses scope. "
    "Simulated and webcam modes retain ranked candidates and Semantic Lens decisions. Webcam must be started by the user via /gaze.",
    {
        "utterance": {
            "type": "string",
            "description": "The spoken or typed user utterance containing deictic references ('this', 'these', 'that').",
        },
        "mode": {
            "type": "string",
            "enum": ["hover", "simulated", "webcam"],
            "description": "Optional pointing mode override; webcam uses the user's already-running calibrated tracker.",
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
    "Select a numbered candidate (1-4) from an open simulated Semantic Lens and update drift calibration. "
    "Selection never clicks or approves; use fresh gaze_read and guarded action tools for browser input.",
    {
        "candidate_index": {
            "type": "integer",
            "minimum": 1,
            "maximum": LENS_MAX_CARDS,
            "description": "1-based index of the candidate card in the Semantic Lens (e.g. 1 for [1]).",
        },
    },
    required=["candidate_index"],
)

GAZE_HIGHLIGHT_SCHEMA = _schema(
    "gaze_highlight",
    "Change the automatically highlighted pointer to the snapshot scope used in your answer: cell, row, column, table or panel. "
    "No call is needed when using the pointed scope. Use current @ handles and Resolution; omit hud_message while streaming.",
    {
        "handles": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8,
                    "description": "Current snapshot @ handles to highlight; never CSS selectors."},
        "resolution_id": {"type": "integer", "description": "Resolution number in the current gaze context."},
        "hud_message": {"type": "string", "description": "Optional plain text, never HTML; omit while answering a streamed turn."},
    },
    required=["handles", "resolution_id"],
)

GAZE_CLICK_SCHEMA = _schema(
    "gaze_click",
    "Click a captured control requested by the user. Use the current resolution_id from gaze_read. "
    "Consequential or ambiguous controls open trusted confirmation by default. With action_approvals=allow-all "
    "they execute without a Look prompt. Never claim execution unless executed is true. On stale resolution use the returned "
    "fresh structure and retry with its epoch; never retry an unknown outcome. Explicitly choose new_tab: "
    "true for a link when the user requests a NEW tab; false for buttons and same-tab links. "
    "Executed clicks return fresh structure and epoch; use that epoch for the next step.",
    {
        "handle": {"type": "string", "description": "Current @ handle of the control to activate, not the data subject."},
        "resolution_id": {"type": "integer", "description": "Resolution number in the current gaze context."},
        "new_tab": {"type": "boolean", "description": "Required tab choice: true opens a safe captured link in a NEW tab; false activates buttons or same-tab links."},
    },
    required=["handle", "resolution_id", "new_tab"],
)

GAZE_CALIBRATE_SCHEMA = _schema(
    "gaze_calibrate",
    "Configure or reset the pointing mode ('hover', 'simulated', 'webcam'), spatial uncertainty sigma, "
    "and online drift recalibrator. This tool cannot start a camera; the user runs /gaze mode webcam and /gaze calibrate.",
    {
        "mode": {
            "type": "string",
            "enum": ["hover", "simulated", "webcam"],
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

_EPOCH_ARG = {"type": "integer", "description": "Latest resolution_id from gaze_read or a fresh tool structure; not a tab ID."}
_HANDLE_ARG = {"type": "string", "description": "Exact captured @handle from the latest structure; never a selector."}
_URL_ARG = {"type": "string", "description": "Absolute http(s) URL, preferably a discovered page link; no mailto, credentials or invented site."}

GAZE_READ_SCHEMA = _schema("gaze_read",
    "Read bounded current page structure: captured fields, options, controls, links and untrusted text, never field values. "
    "Viewport controls come first within the 64-identity cap; scroll and re-read for later controls. "
    "Start browser tasks here; it returns the integer resolution_id for subsequent operations.", {})
GAZE_FILL_SCHEMA = _schema("gaze_fill",
    "Fill ALL known fields in one batch, including personal details from Hermes memory/context; ask for unknowns. "
    "Native selects take a listed option; dates MUST use ISO YYYY-MM-DD. Existing text is replaced; "
    "typing can itself have effects on rare sites.",
    {"resolution_id": _EPOCH_ARG, "entries": {"type": "array", "minItems": 1, "maxItems": 32,
        "items": {"type": "object", "additionalProperties": False, "properties": {
            "handle": _HANDLE_ARG, "text": {"type": "string", "maxLength": 4000}}, "required": ["handle", "text"]}}},
    ["resolution_id", "entries"])
GAZE_PRESS_SCHEMA = _schema("gaze_press",
    "Press a supported key on one captured nonsensitive field/control. Enter/Space use guarded activation; no shortcuts or approval. "
    "Use gaze_fill for text. Escape is reserved for the user's Stop, not page input.",
    {"resolution_id": _EPOCH_ARG, "handle": _HANDLE_ARG,
        "key": {"type": "string", "enum": ["Enter", "Space", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End", "Tab"]}},
    ["resolution_id", "handle", "key"])
GAZE_OPEN_TAB_SCHEMA = _schema("gaze_open_tab",
    "Open an http(s) URL in a NEW tab, make it the action target and return its fresh page structure and epoch. "
    "For a captured link prefer gaze_click(new_tab:true), which preserves its native destination.",
    {"resolution_id": _EPOCH_ARG, "url": _URL_ARG},
    ["resolution_id", "url"])
GAZE_NAVIGATE_SCHEMA = _schema("gaze_navigate",
    "Navigate the task's foreground tab to an http(s) URL and return fresh structure and epoch.",
    {"resolution_id": _EPOCH_ARG, "url": _URL_ARG}, ["resolution_id", "url"])
GAZE_SCROLL_SCHEMA = _schema("gaze_scroll",
    "Scroll the page or one captured container by bounded pixels, then gaze_read for newly visible controls.",
    {"resolution_id": _EPOCH_ARG, "pixels": {"type": "integer", "minimum": -2000, "maximum": 2000},
     "handle": _HANDLE_ARG}, ["resolution_id", "pixels"])
GAZE_WAIT_SCHEMA = _schema("gaze_wait", "Wait briefly for page changes, then return fresh structure and epoch.",
    {"seconds": {"type": "number", "minimum": 0, "maximum": 2}}, ["seconds"])
GAZE_REQUEST_COMMIT_SCHEMA = _schema("gaze_request_commit",
    "Request a captured Submit/Send/Buy/Delete/publish or ambiguous action. By default this opens protected review. "
    "When gaze_read reports action_approvals=allow-all, this executes without a Look prompt. "
    "Never call for 'prepare only' or 'do not send/submit' in allow-all mode. Stop on confirmation_required and ask the user to click.",
    {"resolution_id": _EPOCH_ARG, "handle": _HANDLE_ARG}, ["resolution_id", "handle"])


def _action(op: str, args: dict, kwargs: dict) -> str:
    result = get_shared_session().tasks.handle(op, args, session_id=kwargs.get("session_id", ""),
                                              turn_id=kwargs.get("turn_id", ""))
    return json.dumps(result, ensure_ascii=False)


def handle_gaze_read(args, **kwargs):
    return _action("read", args, kwargs)


def handle_gaze_fill(args, **kwargs):
    return _action("fill", args, kwargs)


def handle_gaze_press(args, **kwargs):
    return _action("press", args, kwargs)


def handle_gaze_open_tab(args, **kwargs):
    return _action("open_tab", args, kwargs)


def handle_gaze_navigate(args, **kwargs):
    return _action("navigate", args, kwargs)


def handle_gaze_scroll(args, **kwargs):
    return _action("scroll", args, kwargs)


def handle_gaze_wait(args, **kwargs):
    return _action("wait", args, kwargs)


def handle_gaze_request_commit(args, **kwargs):
    return _action("request_commit", args, kwargs)


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
    if (hint_x is not None or hint_y is not None) and str(args.get("mode") or session.tracker.mode) != "simulated":
        return json.dumps({"ok": False, "error": "target hints are unsupported outside simulated mode; use the actual pointing source"})
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
        activate=not (args.get("record_voice") and str(args.get("mode") or session.tracker.mode) == "hover"),
    )
    if args.get("record_voice") and str(args.get("mode") or session.tracker.mode) == "hover":
        payload = service.submit_snapshot(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_gaze_choose(args: Dict[str, Any], **kwargs: Any) -> str:
    session = get_shared_session()
    idx = int(args.get("candidate_index", 1))
    # Tool requests target the active resolution; binding requests supply their own epoch.
    payload = session.choose(resolution_id=session.resolution_id, candidate_index=idx)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def handle_gaze_highlight(args: Dict[str, Any], **kwargs: Any) -> str:
    result = get_shared_session().actions.highlight(
        args.get("handles"), args.get("resolution_id"), str(args.get("hud_message") or ""))
    return json.dumps(result, ensure_ascii=False)


def handle_gaze_click(args: dict[str, Any], **kwargs: Any) -> str:
    return _action("click", args, kwargs)


def handle_gaze_calibrate(args: Dict[str, Any], **kwargs: Any) -> str:
    session = get_shared_session()
    mode = str(args.get("mode") or session.tracker.mode or "hover")
    if mode not in ("hover", "simulated", "webcam"):
        return json.dumps({"ok": False, "error": "Unsupported pointing mode"})
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
    ("gaze_click", GAZE_CLICK_SCHEMA, handle_gaze_click, "🖱️"),
    ("gaze_read", GAZE_READ_SCHEMA, handle_gaze_read, ""),
    ("gaze_fill", GAZE_FILL_SCHEMA, handle_gaze_fill, ""),
    ("gaze_press", GAZE_PRESS_SCHEMA, handle_gaze_press, ""),
    ("gaze_open_tab", GAZE_OPEN_TAB_SCHEMA, handle_gaze_open_tab, ""),
    ("gaze_navigate", GAZE_NAVIGATE_SCHEMA, handle_gaze_navigate, ""),
    ("gaze_scroll", GAZE_SCROLL_SCHEMA, handle_gaze_scroll, ""),
    ("gaze_wait", GAZE_WAIT_SCHEMA, handle_gaze_wait, ""),
    ("gaze_request_commit", GAZE_REQUEST_COMMIT_SCHEMA, handle_gaze_request_commit, ""),
    ("gaze_calibrate", GAZE_CALIBRATE_SCHEMA, handle_gaze_calibrate, "🧭"),
    ("gaze_benchmark", GAZE_BENCHMARK_SCHEMA, handle_gaze_benchmark, "📊"),
)
