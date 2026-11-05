"""Runtime service layer for hermes-gaze.

Holds the live plugin config + optional PluginLlm handle (``set_runtime``),
owns the single resolution path (``resolve_now``) shared by the model tools
and the overlay's CDP intent channel (``handle_intent``), and answers
explanation requests (``explain_element``) via ``ctx.llm``.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import time
from typing import Any, Callable, Dict, Optional, Sequence

from .browser.cdp_bridge import GazeSession, get_shared_session
from .config import GazeConfig
from .resolver.bayesian_fusion import CandidateElement, resolve_candidates
from .resolver.data_extractor import extract_structured_data, render_svg_scatter
from .voice import MAX_AUDIO_BYTES

logger = logging.getLogger(__name__)

_CONFIG: Optional[GazeConfig] = None
_LLM: Any = None


def set_runtime(config: Optional[GazeConfig], llm: Any = None) -> None:
    """Store the live plugin config + LLM handle used by handlers/dispatch."""
    global _CONFIG, _LLM
    _CONFIG = config
    _LLM = llm


def _whisper_model_name() -> str:
    return _CONFIG.whisper_model if _CONFIG is not None else GazeConfig.whisper_model


def resolve_now(
    session: GazeSession,
    *,
    utterance: str,
    words: Optional[Sequence[Dict[str, object]]] = None,
    pushed: Optional[Dict[str, Any]] = None,
    mode: Optional[str] = None,
    llm: Any = None,
    record_voice: bool = False,
    duration_s: float = 2.8,
) -> Dict[str, Any]:
    """THE resolution path: speech -> fixations + candidates -> Bayesian fusion -> render.

    ``pushed`` carries overlay-supplied state ({pointer, fixations, candidates});
    when absent the live state is pulled from the pinned Chrome tab. Returns the
    ResolutionResult dict plus chrome_connected/mode (and speech_recognition meta).
    """
    if mode is not None and str(mode) not in ("hover", "simulated"):
        return {"ok": False, "error": f"unsupported tracking mode: {mode!r} (supported: hover, simulated)"}
    mode = str(mode or session.tracker.mode or "hover")
    session.configure(mode=mode)  # stores; pushes to the overlay only when a ws is live

    raw_utterance = str(utterance or "").strip()
    word_timestamps = words
    transcription_meta: Dict[str, Any] = {}

    if record_voice:
        from .voice import record_microphone, transcribe_audio_buffer

        try:
            audio_epoch = time.time()  # whisper word times are audio-relative; shift to wall-clock
            audio_pcm = record_microphone(duration_s=duration_s)
            transcribed_text, word_ts = transcribe_audio_buffer(
                audio_pcm, model_name=_whisper_model_name(), audio_epoch=audio_epoch
            )
        except Exception as exc:
            return {"ok": False, "error": f"voice capture/transcription failed: {exc}"}
        if transcribed_text:
            raw_utterance = transcribed_text
            word_timestamps = word_ts
            transcription_meta = {
                "transcribed_text": transcribed_text,
                "word_timestamps": word_ts,
                "recorded_duration_s": duration_s,
            }

    if not raw_utterance:
        return {"ok": False, "error": "empty utterance — no spoken or typed query to resolve"}
    utterance = raw_utterance
    now = time.time()

    if pushed is not None:
        session.ingest(pushed.get("fixations") or [])
        pointer = pushed.get("pointer")
        # A null pointer is honest "no pointer yet" — never record it as a fixation.
        if isinstance(pointer, dict) and pointer.get("x_vp") is not None and pointer.get("y_vp") is not None:
            session.tracker.record_point(
                float(pointer["x_vp"]),
                float(pointer["y_vp"]),
                scroll_x=float(pointer.get("scroll_x", 0.0)),
                scroll_y=float(pointer.get("scroll_y", 0.0)),
                timestamp=now,
                bias_offset=session.recalibrator.offset,
            )
        candidates = [
            CandidateElement.from_wire(raw)
            for raw in pushed.get("candidates") or []
            if isinstance(raw, dict)
        ]
        with session._lock:
            session.last_candidates = candidates
    else:
        candidates = session.fetch_live_state_and_candidates(
            radius_px=getattr(session, "_candidate_radius_px", 380.0)
        )

    if not candidates:
        return {"ok": False, "error": "No DOM candidates extracted — is the overlay injected into the Chrome tab?"}
    fixations = session.ring_buffer.snapshot(now)
    if not fixations:
        return {"ok": False, "error": "No pointer/gaze fixations recorded yet."}

    res = resolve_candidates(
        candidates, fixations, utterance, t_arm=now, word_timestamps=word_timestamps,
        llm_client=llm if llm is not None else _LLM,
    )
    payload = res.to_dict()

    hud_html = None
    if res.top and (res.top.candidate.is_container or res.top.candidate.role == "table"):
        table_payload = None
        if session.is_chrome_reachable():
            sel = json.dumps(res.top.candidate.selector)
            try:
                table_payload = session.eval_js(
                    f"window.__HERMES_GAZE_OVERLAY__.extractTableData({sel});",
                )
            except Exception as exc:
                logger.debug("extractTableData eval failed: %s", exc)
        if table_payload:
            extracted_str = extract_structured_data(table_payload, fmt="csv")
            svg_chart = render_svg_scatter(
                table_payload.get("headers") or [],
                table_payload.get("rows") or [],
            )
            payload["extracted_data"] = extracted_str
            payload["svg_scatter"] = svg_chart
            hud_html = (
                f"<div><strong>Extracted {html.escape(str(res.top.candidate.label))} ({len(table_payload.get('rows') or [])} rows):</strong></div>"
                f"<div style='margin-top:6px;'>{svg_chart}</div>"
            )

    session.render_resolution_in_browser(res, hud_html=hud_html)
    payload["resolution_id"] = session.resolution_id
    payload["chrome_connected"] = session.is_chrome_reachable()
    payload["mode"] = mode
    if transcription_meta:
        payload["speech_recognition"] = transcription_meta
    return payload


def explain_element(utterance: str, label: str, role: str, summary: str, llm: Any = None) -> str:
    """Ask Hermes (ctx.llm) for a concise, helpful explanation of a UI element in context."""
    client = llm if llm is not None else _LLM
    if client is not None:
        try:
            res = client.complete_structured(
                instructions=(
                    f"The user is looking at a web UI element labeled '{label}' (type: {role}, context: {summary}) "
                    f"and asks: '{utterance}'. Answer their question directly in 1-2 clear, helpful sentences "
                    "(under 35 words). Do not call tools; output the direct explanation text only."
                ),
                input=[{"type": "text", "text": f"Utterance: {utterance}\nElement: {label} ({role})\nContext: {summary}"}],
                json_mode=False,
                timeout=8.0,
            )
            text = str(getattr(res, "text", res) or "").strip()
            if text:
                return text
        except Exception as exc:
            logger.debug("ctx.llm explanation failed: %s", exc)
    return f"{label} ({role}): {summary}"


def handle_intent(intent: Dict[str, Any], reply: Callable[[Dict[str, Any]], None]) -> None:
    """Dispatch one overlay -> Python intent (Runtime.addBinding) to the right handler."""
    session = get_shared_session()
    if intent.get("nonce") != session._intent_nonce:
        # The binding is callable by any same-frame page script; only the overlay we
        # injected (post-inject setIntentNonce) knows the per-session nonce.
        reply({"ok": False, "error": "unauthorized intent"})
        return
    itype = str(intent.get("type") or "")
    try:
        if itype == "resolve":
            res = resolve_now(
                session,
                utterance=str(intent.get("utterance") or ""),
                words=intent.get("words"),
                pushed={
                    "pointer": intent.get("pointer"),
                    "fixations": intent.get("fixations"),
                    "candidates": intent.get("candidates"),
                },
            )
            if res.get("ok") is False:
                reply({"ok": False, "error": str(res.get("error") or "resolution failed")})
                return
            ranked = res.get("ranked") or []
            top = ranked[0] if ranked else {}
            reply(
                {
                    "ok": True,
                    "decision": res.get("decision"),
                    "intent_class": res.get("intent_class"),
                    "resolution_id": res.get("resolution_id"),
                    "needs_explain": res.get("intent_class") == "read_only" and res.get("decision") == "pin_immediate",
                    "top": {
                        "label": top.get("label"),
                        "role": top.get("role"),
                        "summary": top.get("summary"),
                        "selector": top.get("selector"),
                        "probability": top.get("probability"),
                    }
                    if top
                    else {},
                }
            )
            return

        if itype == "choose":
            # resolution_id 0/absent from the overlay means "active resolution" (no epoch check).
            payload = session.choose(
                resolution_id=intent.get("resolution_id") or None,
                candidate_index=int(intent.get("candidate_index") or 1),
                modality=str(intent.get("modality") or "semantic_lens"),
                execute=bool(intent.get("execute", True)),
            )
            reply(payload)
            return

        if itype == "explain":
            reply(
                {
                    "ok": True,
                    "explanation": explain_element(
                        str(intent.get("utterance") or ""),
                        str(intent.get("label") or ""),
                        str(intent.get("role") or ""),
                        str(intent.get("summary") or ""),
                        llm=_LLM,
                    ),
                }
            )
            return

        if itype == "transcribe":
            from .voice import transcribe_audio_buffer

            b64_data = str(intent.get("audio_base64") or "")
            if len(b64_data) > int(MAX_AUDIO_BYTES * 1.34):
                reply({"ok": False, "error": "audio payload exceeds maximum size"})
                return
            audio_bytes = base64.b64decode(b64_data)
            sample_rate = int(intent.get("sample_rate") or 16000)
            epoch_raw = intent.get("audio_epoch")
            audio_epoch = float(epoch_raw) if epoch_raw else None
            text, words_out = transcribe_audio_buffer(
                audio_bytes, sample_rate=sample_rate, model_name=_whisper_model_name(),
                audio_epoch=audio_epoch,
            )
            reply({"ok": True, "text": text, "words": words_out})
            return

        if itype == "configure":
            ok = session.configure(mode=intent.get("mode"), sigma_px=intent.get("sigma_px"))
            reply({"ok": ok, "mode": session.tracker.mode})
            return

        reply({"ok": False, "error": "unknown intent type"})
    except Exception as exc:
        reply({"ok": False, "error": str(exc)})
