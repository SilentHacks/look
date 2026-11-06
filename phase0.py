"""Opt-in /gaze probe experiment. No cursor extraction or production voice routing."""
from __future__ import annotations

import html
import json
import secrets
import threading
import time
from typing import Any

DEFAULT_QUESTION = "Summarize this table in one sentence."


class PhaseZeroProbe:
    def __init__(self, ctx: Any, session: Any) -> None:
        self.ctx = ctx
        self.session = session
        # ponytail: one diagnostic lock serializes HUD writes; use per-session queues if concurrent probes matter.
        self.runs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def command(self, args: str, *, session_key: str = "", session_id: str = "", platform: str = "", **_: Any) -> str:
        action, _, question = args.strip().partition(" ")
        sid = session_id or session_key
        with self.lock:
            if action == "status":
                return json.dumps(self.runs.get(sid, {"error": "No probe in this session"}), ensure_ascii=False)
            if action == "stop":
                self.runs.pop(sid, None)
                return "Phase 0 probe detached."
            if action not in ("start", "followup"):
                return "Usage: /gaze probe start [question] | followup | status | stop"
            if not session_key or not sid:
                return "Phase 0 needs a live TUI/desktop session; run /gaze probe there."
            if not self.session.overlay_is_live() and not self.session.ensure_overlay():
                return "Run /gaze demo first; Phase 0 requires the live Chrome HUD."
            previous = self.runs.get(sid)
            if previous and not previous.get("finished"):
                return "Phase 0 turn still pending; use /gaze probe status."
            if action == "followup" and not previous:
                return "Run /gaze probe start first."
            code = previous["code"] if action == "followup" else secrets.token_hex(4)
            text = (question or DEFAULT_QUESTION) if action == "start" else (
                "What was the probe code in the earlier page context? Reply with only the code; do not use tools."
            )
            run = {"session_key": session_key, "session_id": sid, "surface": platform,
                   "code": code, "question": text, "with_context": action == "start",
                   "accepted": False, "hook_fired": False, "finished": False,
                   "stream_deltas": 0, "tools": [], "text": "", "chrome_updates": 0,
                   "started": time.monotonic()}
            self.runs[sid] = run
        try:
            accepted = self.ctx.inject_message(text, session_key=session_key)
        except Exception as exc:
            accepted = False
            run["error"] = str(exc)
        with self.lock:
            run["accepted"] = bool(accepted)
            if not accepted:
                run["finished"] = True
                run.setdefault("error", "Host refused injection; check plugins.entries.hermes-gaze.allow_gateway_injection and session ownership.")
            return json.dumps({"accepted": bool(accepted), "session_key": session_key,
                               "error": run.get("error")})

    def pre(self, *, session_id: str = "", user_message: str = "", turn_id: str = "", **kwargs: Any) -> dict | None:
        with self.lock:
            run = self.runs.get(session_id)
            if not run or run["finished"] or run.get("hook_fired") or user_message != run["question"]:
                return None
            run.update(hook_fired=True, turn_id=turn_id, model=kwargs.get("model"),
                       history_contains_code=run["code"] in json.dumps(kwargs.get("conversation_history") or []))
            if not run["with_context"]:
                return {}  # Deliberately do not resend context: measure whether Hermes retained it.
            return {"context": (
                "[gaze_ref — Phase 0 fixture, NOT live DOM]\n"
                "The cursor points at a cell; the table is available as context, not a scope decision.\n"
                "For this diagnostic, call gaze_highlight(selector='#campaigns-table', label='Phase 0 table', "
                "hud_message='Inspecting the fixture table') once before answering. Do not call other tools. "
                "Do not include the probe code in this answer.\n"
                f"<page_data untrusted>Probe code: {run['code']}\n"
                "Campaign | Clicks | Spend\nOriole | 120 | $30\nFinch | 80 | $20\n"
                "</page_data>"
            )}

    def _active(self, session_id: str, turn_id: str) -> dict | None:
        run = self.runs.get(session_id)
        return run if run and run.get("hook_fired") and run.get("turn_id") == turn_id else None

    def _display(self, run: dict, text: str) -> None:
        try:
            markup = '<div data-phase0="true" style="white-space:pre-wrap">' + html.escape(text[-12000:]) + '</div>'
            self.session.eval_js(f"window.__HERMES_GAZE_OVERLAY__.showHudMessage({json.dumps(markup)});true")
            run["chrome_updates"] += 1
            run["last_display"] = time.monotonic()
        except Exception as exc:
            run["chrome_error"] = str(exc)

    def delta(self, *, session_id: str = "", turn_id: str = "", delta: str = "", kind: str = "text", **_: Any) -> None:
        if kind != "text" or not delta:
            return
        with self.lock:
            run = self._active(session_id, turn_id)
            if not run or run["finished"]:
                return
            run.setdefault("first_delta_s", time.monotonic() - run["started"])
            run["stream_deltas"] += 1
            run["text"] += delta
            if time.monotonic() - run.get("last_display", 0) >= .08:
                self._display(run, run["text"])

    def tool(self, *, session_id: str = "", turn_id: str = "", tool_name: str = "", **_: Any) -> None:
        with self.lock:
            run = self._active(session_id, turn_id)
            if run:
                run["tools"].append(tool_name)

    def post(self, *, session_id: str = "", turn_id: str = "", assistant_response: str = "", **_: Any) -> None:
        with self.lock:
            run = self._active(session_id, turn_id)
            if not run:
                return
            run["response"] = str(assistant_response)
            run["elapsed_s"] = time.monotonic() - run["started"]
            run["finished"] = True
            self._display(run, run["response"])
            run["followup_recalled_code"] = not run["with_context"] and run["code"] in run["response"]
