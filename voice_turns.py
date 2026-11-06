"""Bind Chrome voice evidence to real Hermes session and turn ownership."""
from __future__ import annotations

import copy
import json
import logging
import secrets
import threading
import time
from collections import deque
from typing import Any

from .resolver.cursor_context import MAX_CONTEXT
from .resolver.temporal_aligner import has_deictic_pronoun

logger = logging.getLogger(__name__)


class VoiceTurns:
    MAX_PENDING = 8
    MAX_TEXT = 12000
    MAX_SNAPSHOT_BYTES = 262144

    def __init__(self, ctx: Any, session: Any) -> None:
        self.ctx = ctx
        self.session = session
        self.lock = threading.RLock()
        self.injection_lock = threading.Lock()
        self.binding: dict[str, str] | None = None
        self.pending: list[dict[str, Any]] = []
        self.active: dict[str, Any] | None = None
        self.seen_turns: deque[tuple[str, str]] = deque(maxlen=128)
        self.sequence = 0
        self.closed = False

    @property
    def connected(self) -> bool:
        with self.lock:
            return self.binding is not None and not self.closed

    def bind(self, raw_args: str = "", *, session_key: str = "", session_id: str = "",
             platform: str = "", **_: Any) -> str:
        with self.lock:
            if self.closed:
                return "Gaze is unloaded. Reload the plugin before connecting."
            action = raw_args.strip().lower()
            if action == "status":
                return "Chrome voice is connected to this Hermes session." if (
                    self.binding and self.binding["session_id"] == session_id
                ) else "Run /gaze connect in this Hermes session to connect Chrome voice."
            if action not in ("", "connect", "disconnect", "stop"):
                return "Usage: /gaze connect | disconnect | status"
            if not session_key or not session_id:
                return "Run /gaze connect in a live Hermes TUI or desktop session."
            if action in ("disconnect", "stop"):
                if self.binding and self.binding["session_id"] == session_id:
                    self._disconnect()
                return "Chrome voice disconnected from this session."
            if self.binding and (self.binding["session_id"], self.binding["session_key"]) == (session_id, session_key):
                return "Chrome voice is already connected to this Hermes session."
            if self.binding:
                self._disconnect()
            self.binding = {"session_key": session_key, "session_id": session_id, "platform": platform}
            self._event(self._new_run("", {}), "complete", text="Chrome voice connected.")
            return "Chrome voice connected to this Hermes session. Speak or submit in Chrome."

    def _new_run(self, text: str, snapshot: dict) -> dict[str, Any]:
        self.sequence += 1
        return {"request_id": secrets.token_hex(12), "sequence": self.sequence,
                "session_id": self.binding["session_id"] if self.binding else "",
                "utterance": text, "snapshot": snapshot, "resolution_id": 0,
                "turn_id": "", "text": "", "finished": False, "ended": False}

    def _event(self, run: dict, status: str, **fields: Any) -> None:
        event = {"request_id": run["request_id"], "sequence": run["sequence"],
                 "resolution_id": run["resolution_id"], "status": status,
                 "session_connected": self.binding is not None and not self.closed, **fields}
        try:
            self.session.display_session_event(event)
            run["last_display"] = time.monotonic()
        except Exception:
            # Browser loss must not turn accepted host injection into one-shot delivery.
            logger.debug("Chrome voice display unavailable", exc_info=True)

    def _disconnect(self) -> None:
        run = self._new_run("", {})
        self.binding = None
        self.pending.clear()
        self.active = None
        self._event(run, "error", error="Chrome voice disconnected. Run /gaze connect to reconnect.")
        self.session.clear_hover_snapshot()

    def submit(self, text: str, snapshot: dict) -> dict:
        # Serialize host admission without holding the hook lock during injection.
        with self.injection_lock:
            return self._submit(text, snapshot)

    def _submit(self, text: str, snapshot: dict) -> dict:
        with self.lock:
            if not self.binding or self.closed:
                return {"ok": False, "fallback_allowed": True,
                        "error": "Run /gaze connect in the Hermes session that should receive Chrome voice."}
            if not isinstance(text, str) or not text.strip() or len(text) > self.MAX_TEXT:
                return {"ok": False, "error": "Utterance must contain 1–12000 characters."}
            if len(self.pending) >= self.MAX_PENDING:
                return {"ok": False, "error": "Voice queue is full; wait for the pending Hermes turns."}
            try:
                if not isinstance(snapshot, dict) or len(json.dumps(snapshot).encode()) > self.MAX_SNAPSHOT_BYTES:
                    raise ValueError("Cursor evidence is too large or invalid.")
                context = snapshot.get("context") or ""
                if not isinstance(context, str) or len(context) > MAX_CONTEXT:
                    raise ValueError("Cursor context is too large or invalid.")
                frozen = copy.deepcopy(snapshot)
            except (TypeError, ValueError) as exc:
                return {"ok": False, "error": str(exc)}
            frozen["utterance"] = text
            run = self._new_run(text, frozen)
            self.pending.append(run)  # Must exist before inject_message can synchronously fire pre.
            key = self.binding["session_key"]
        error = ("Host refused injection. Fresh Hermes sessions need one normal message before Chrome turns; "
                 "also check plugins.entries.hermes-gaze.allow_gateway_injection.")
        fallback_allowed = True
        try:
            accepted = bool(self.ctx.inject_message(text, session_key=key))
        except Exception as exc:
            fallback_allowed = False
            logger.debug("Hermes injection failed", exc_info=True)
            accepted = False
            error = f"Hermes injection failed: {exc}"
        with self.lock:
            if not accepted:
                visible = (not self.closed and self.binding is not None
                           and run["session_id"] == self.binding["session_id"]
                           and (run in self.pending or self.active is run))
                if run in self.pending:
                    self.pending.remove(run)
                if self.active is run:
                    self.active = None
                run["finished"] = True
                if visible:
                    self._event(run, "error", error=error)
                return {"ok": False, "request_id": run["request_id"], "sequence": run["sequence"],
                        "error": error, "fallback_allowed": fallback_allowed and not run["turn_id"]}
            if run in self.pending and (self.active is None or self.active["finished"] or self.active["ended"]):
                self._event(run, "queued")
            return {"ok": True, "delivery": "session", "status": "queued",
                    "request_id": run["request_id"], "sequence": run["sequence"]}

    def pre(self, *, session_id: str = "", user_message: str = "", turn_id: str = "", **_: Any) -> dict | None:
        with self.lock:
            if (self.closed or not self.binding or session_id != self.binding["session_id"]
                    or not turn_id or not isinstance(user_message, str)):
                return None
            identity = (session_id, turn_id)
            if identity in self.seen_turns:
                return None
            self.seen_turns.append(identity)
            run = next((item for item in self.pending if item["session_id"] == session_id
                        and item["utterance"] == user_message), None)
            if run is not None:
                self.pending.remove(run)
            else:
                if has_deictic_pronoun(user_message):
                    from .service import resolve_now
                    try:
                        snapshot = resolve_now(self.session, utterance=user_message, activate=False)
                    except Exception as exc:
                        logger.debug("Typed cursor capture failed", exc_info=True)
                        snapshot = {"context": "", "error": str(exc)}
                else:
                    snapshot = {}
                run = self._new_run(user_message, snapshot)
            self.active = run
            run["turn_id"] = turn_id
            snapshot = run["snapshot"]
            snapshot["utterance"] = user_message
            context = str(snapshot.get("context") or "")
            run["resolution_id"] = self.session.resolution_id
            if context:
                try:
                    if snapshot.get("mode") != "simulated":
                        run["resolution_id"] = self.session.store_hover_snapshot(snapshot)
                        handles = list(dict.fromkeys(p["id"] for p in snapshot.get("pointed", [])
                                                     if p.get("available") and p.get("id")))
                        if handles:
                            result = self.session.actions.highlight(handles, run["resolution_id"])
                            if not result.get("ok"):
                                logger.debug("Automatic pointer highlight failed: %s", result.get("error"))
                except Exception as exc:
                    logger.debug("Cursor evidence activation failed", exc_info=True)
                    run["finished"] = True
                    self._event(run, "error", error=f"Cursor evidence activation failed: {exc}")
                    return None
                context = str(snapshot.get("context") or "")
            self._event(run, "thinking")
            return {"context": context} if context else None

    def _owned(self, session_id: str, turn_id: str) -> dict | None:
        run = self.active
        if (self.closed or not self.binding or not run or run["finished"]
                or session_id != self.binding["session_id"] or session_id != run["session_id"]
                or not turn_id or turn_id != run["turn_id"]):
            return None
        return run

    def delta(self, *, session_id: str = "", turn_id: str = "", delta: str = "",
              kind: str = "text", **_: Any) -> None:
        if kind != "text" or not isinstance(delta, str) or not delta:
            return
        with self.lock:
            run = self._owned(session_id, turn_id)
            if run is None or run["ended"]:
                return
            run["text"] = (run["text"] + delta)[-self.MAX_TEXT:]
            if time.monotonic() - run.get("last_display", 0) >= .08:
                self._event(run, "thinking", text=run["text"])

    def post(self, *, session_id: str = "", turn_id: str = "", assistant_response: str = "", **_: Any) -> None:
        with self.lock:
            run = self._owned(session_id, turn_id)
            if run is None:
                return
            if isinstance(assistant_response, str) and assistant_response:
                run["text"] = assistant_response[-self.MAX_TEXT:]
            run["finished"] = True
            self._event(run, "complete", text=run["text"])

    def end(self, *, session_id: str = "", turn_id: str = "", failed: bool = False,
            interrupted: bool = False, completed: bool = True, turn_exit_reason: str = "", **_: Any) -> None:
        with self.lock:
            run = self._owned(session_id, turn_id)
            if run is None or run["ended"]:
                return
            run["ended"] = True
            if failed or interrupted or not completed:
                run["finished"] = True
                self._event(run, "error", error=turn_exit_reason or "Hermes turn failed or was interrupted.", text=run["text"])
            else:
                # Host emits this per turn, not per chat. post may arrive after this callback.
                self._event(run, "complete", text=run["text"])

    def close(self) -> None:
        with self.lock:
            if not self.closed:
                self._disconnect()
                self.closed = True
