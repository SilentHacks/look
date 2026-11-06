"""Python-owned browsing inbox and exact Hermes turn ownership."""
from __future__ import annotations

import copy
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any

from .resolver.cursor_context import MAX_CONTEXT, build_context
from .resolver.temporal_aligner import has_deictic_pronoun

logger = logging.getLogger(__name__)


class VoiceTurns:
    MAX_PENDING = 8
    MAX_TEXT = 12000
    MAX_SNAPSHOT_BYTES = 262144

    def __init__(self, ctx: Any, session: Any) -> None:
        self.ctx, self.session = ctx, session
        self.lock = threading.RLock()
        self.injection_lock = threading.RLock()
        self.binding = None
        self.owner_session = ""
        self.pending = []
        self.active = None
        self.items = []
        self.runs = []
        self.host_turn = ""
        self.host_session = ""
        self.selected = ""
        self.paused = False
        self.seen_turns = deque(maxlen=128)
        self.sequence = 0
        self.revision = 0
        self.closed = False
        self.capture_state = "idle"
        self.auto_speak = False
        self.speech_error = ""
        self._speech_process = None
        self._speech_pending = None
        self._speech_thread = None

    @property
    def connected(self) -> bool:
        with self.lock:
            return self.binding is not None and not self.closed

    def bind(self, raw_args="", *, session_key="", session_id="", platform="", **_) -> str:
        with self.lock:
            if self.closed:
                return "Gaze is unloaded. Reload the plugin before connecting."
            action = raw_args.strip().lower()
            if action == "status":
                return "Chrome voice connected." if self.connected else "Run /gaze connect."
            if action not in ("", "connect", "disconnect", "stop"):
                return "Usage: /gaze connect | disconnect | status"
            if not session_key or not session_id:
                return "Run /gaze connect in a live Hermes TUI or desktop session."
            if action in ("disconnect", "stop"):
                if self.binding and self.binding["session_id"] == session_id:
                    self._disconnect()
                return "Chrome voice disconnected from this session."
            if self.owner_session and self.owner_session != session_id:
                self._disconnect()
                self.items.clear()
                self.pending.clear()
                self.runs.clear()
                self.selected = ""
                self.paused = False
            self.owner_session = session_id
            self.binding = dict(session_key=session_key, session_id=session_id, platform=platform)
            self.publish()
            return "Chrome voice connected. Speak or submit in Chrome."

    def capture_status(self, status):
        with self.lock:
            self.capture_state = status
            self.publish()

    def publish(self):
        """Versioned, UI-independent replacement state; no DOM identities leave Python."""
        self.revision += 1
        waiting = {r["request_id"]: n + 1 for n, r in enumerate(self.pending)}
        items = []
        for item in self.items:
            messages = [{k: r.get(k, "") for k in
                         ("request_id", "utterance", "text", "status", "error")}
                        | {"queue_position": waiting.get(r["request_id"], 0)}
                        for r in self.runs if r["item_id"] == item["item_id"]]
            items.append({k: item[k] for k in
                          ("item_id", "capture_order", "target_label", "source_url", "unread")}
                         | {"conversation": messages, "action_state": "expired: point again to act"})
        event = {"type": "inbox", "version": 1, "revision": self.revision,
                 "sequence": self.revision, "items": items, "selected_item_id": self.selected,
                 "paused": self.paused, "session_connected": self.connected,
                 "capture_state": self.capture_state, "auto_speak": self.auto_speak,
                 "speech_error": self.speech_error}
        try:
            self.session.display_session_event(event)
        except Exception:
            logger.debug("Inbox display unavailable", exc_info=True)

    def _event(self, run, status, **fields):
        previous_status = run["status"]
        run.update(status=status, **fields)
        if status in ("complete", "failed", "interrupted"):
            item = self._item(run["item_id"])
            if item:
                item["unread"] = True
        run["last_display"] = time.monotonic()
        if (status == "complete" and previous_status != "complete" and self.auto_speak
                and self.connected and run["text"].strip()):
            self._speak(run["text"])
        self.publish()

    def _item(self, item_id):
        return next((i for i in self.items if i["item_id"] == item_id), None)

    def _new_run(self, text, snapshot, item_id):
        current = getattr(self.session, "last_hover_snapshot", None) or {}
        if current.get("early_highlight"):
            current["early_highlight"].superseded = True
        self.sequence += 1
        request = secrets.token_hex(12)
        run = dict(request_id=request, sequence=self.sequence, item_id=item_id,
                   session_id=self.binding["session_id"], utterance=text, snapshot=snapshot,
                   wire=f"[Browsing inbox {item_id}; request {request}]\n{text}",
                   resolution_id=0, turn_id="", text="", status="queued", error="",
                   finished=False, ended=False)
        self.runs.append(run)
        self.pending.append(run)
        return run

    def _start_highlight(self, run):
        from .service import start_question_highlight

        if run.get("snapshot", {}).get("early_highlight"):
            return
        item = self._item(run["item_id"])
        if not item["evidence_ready"]:
            return
        snapshot = copy.deepcopy(run["snapshot"])
        snapshot.update(utterance=run["utterance"], context=self._context(run))
        previous = self.items[item["capture_order"] - 2]["snapshot"] if item["capture_order"] > 1 else None
        if (previous and snapshot.get("browser_document") and
                all(snapshot.get(key) == previous.get(key) for key in ("browser_target", "browser_document"))):
            # Reuse only identities also frozen in THIS capture's registry. Never merge or rematch DOM.
            targets = [previous.get("top", {}), snapshot.get("top", {})]
            for name, handles in (
                    ("referents", [t.get("id") for t in targets]),
                    ("rows", [t.get("cell", {}).get("row_handle") for t in targets])):
                if len(set(handles)) == 2 and all(h in snapshot.get("handles", {}) for h in handles):
                    snapshot["scope_bundles"][name] = handles
                    snapshot["decision_referents"] = 2
        start_question_highlight(self.session, snapshot, read_only=True,
                                 display=run["sequence"] == self.sequence)
        run["snapshot"] = snapshot

    def capture(self, snapshot, *, transcribing=False, item_id=""):
        """Reserve capture order before ASR. A transcribing head blocks later admission."""
        with self.lock:
            if not self.connected:
                return {"ok": False, "fallback_allowed": True, "error": "Run /gaze connect."}
            if len(self.pending) >= self.MAX_PENDING:
                return {"ok": False, "error": "Inbox full: eight questions are waiting."}
            try:
                if not isinstance(snapshot, dict) or len(json.dumps(snapshot).encode()) > self.MAX_SNAPSHOT_BYTES:
                    raise ValueError("Cursor evidence is too large or invalid.")
                if not isinstance(snapshot.get("context", ""), str) or len(snapshot.get("context", "")) > MAX_CONTEXT:
                    raise ValueError("Cursor context is too large or invalid.")
                frozen = copy.deepcopy(snapshot)
            except (TypeError, ValueError) as exc:
                return {"ok": False, "error": str(exc)}
            item = self._item(item_id) if item_id else None
            followup = item is not None
            if item_id and item is None:
                return {"ok": False, "error": "Follow-up target unavailable"}
            if item is not None:
                frozen = copy.deepcopy(item["snapshot"])
            else:
                item_id = secrets.token_hex(6)
                top = frozen.get("top") or {}
                item = dict(item_id=item_id, capture_order=len(self.items) + 1,
                            target_label=str(top.get("label") or top.get("text") or "Captured target")[:200],
                            source_url=str(frozen.get("page_url") or ""), unread=False, snapshot=frozen,
                            evidence_ready=not transcribing)
                self.items.append(item)
            self.session.actions.invalidate()
            run = self._new_run(str(snapshot.get("utterance") or ""), frozen, item_id)
            run["followup"] = followup
            if transcribing:
                run["status"] = "transcribing"
                run["utterance"] = ""
            else:
                self._start_highlight(run)
            self.publish()
            return {"ok": True, "item_id": item_id, "request_id": run["request_id"],
                    "sequence": run["sequence"], "delivery": "session", "status": run["status"]}

    def start_transcription(self, request_id, work):
        with self.lock:
            run = next((r for r in self.pending if r["request_id"] == request_id), None)
            if not run or self.closed:
                return
            run["transcribe"] = work
            threading.Thread(target=work, name="gaze-transcribe", daemon=True).start()

    def transcribed(self, request_id, text, snapshot=None, error=""):
        with self.lock:
            run = next((r for r in self.pending if r["request_id"] == request_id), None)
            if not run:
                return {"ok": False, "error": "Capture no longer available"}
            if (not run.get("followup") and snapshot and snapshot.get("ok") is False
                    and isinstance(text, str) and has_deictic_pronoun(text)):
                error = str(snapshot.get("error") or "No available cursor target")
            if not isinstance(text, str) or len(text) > self.MAX_TEXT or error or not text.strip():
                self.paused = True
                self._event(run, "failed", error=error or "No speech recognized")
                return {"ok": False, "error": run["error"], "request_id": request_id, "item_id": run["item_id"]}
            saved = copy.deepcopy(snapshot) if snapshot is not None else run["snapshot"]
            if run.get("followup"):
                saved = run["snapshot"]
            else:
                item = self._item(run["item_id"])
                top = saved.get("top") or {}
                item.update(snapshot=copy.deepcopy(saved), evidence_ready=True,
                            target_label=str(top.get("label") or top.get("text") or "Captured target")[:200])
            run.update(utterance=text, snapshot=saved, status="queued",
                       error="",
                       wire=f"[Browsing inbox {run['item_id']}; request {run['request_id']}]\n{text}")
            run.pop("transcribe", None)
            self._start_highlight(run)
            self.publish()
        self._pump()
        return {"ok": True, "delivery": "session", "request_id": request_id, "item_id": run["item_id"]}

    def submit(self, text, snapshot, item_id=""):
        if not isinstance(text, str) or not text.strip() or len(text) > self.MAX_TEXT:
            return {"ok": False, "error": "Utterance must contain 1–12000 characters."}
        with self.lock:
            if item_id:
                item = self._item(item_id)
                if not self.connected or not item or len(self.pending) >= self.MAX_PENDING:
                    return {"ok": False, "error": "Follow-up target unavailable or queue full"}
                run = self._new_run(text, copy.deepcopy(item["snapshot"]), item_id)
                run["followup"] = True
                self.session.actions.invalidate()
                result = {"ok": True, "delivery": "session", "request_id": run["request_id"]}
                self._start_highlight(run)
                self.publish()
            else:
                result = self.capture({**snapshot, "utterance": text})
                if not result["ok"]:
                    return result
        self._pump()
        return result

    def _pump(self):
        # Host must never receive B/C while A owns a turn: busy injection merges them.
        with self.injection_lock:
            with self.lock:
                if not self.connected or self.paused or self.active or self.host_turn or not self.pending:
                    return
                run = self.pending[0]
                if run["status"] != "queued":
                    return
                if run.get("followup"):
                    item = self._item(run["item_id"])
                    if not item["evidence_ready"]:
                        self.paused = True
                        self._event(run, "failed", error="The original capture has no transcribed evidence.")
                        return
                    if not run["snapshot"].get("early_highlight"):
                        run["snapshot"] = copy.deepcopy(item["snapshot"])
                self._start_highlight(run)
                self.pending.pop(0)
                self.active = run
                key = self.binding["session_key"]
                self._event(run, "thinking")
            try:
                accepted = bool(self.ctx.inject_message(run["wire"], session_key=key))
                error = "Host refused injection; send one normal Hermes message, then Retry."
            except Exception as exc:
                accepted, error = False, f"Injection outcome unknown: {exc}"
            with self.lock:
                if not accepted and self.active is run:
                    run.update(finished=True, ended=True)
                    self.active = None
                    self.paused = True
                    self._event(run, "failed", error=error)

    def _stop_speaking(self):
        """Cancel without waiting on a pipe or child while holding the inbox lock."""
        self._speech_pending = None
        process, self._speech_process = self._speech_process, None
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def _speak(self, text):
        if sys.platform != "darwin" or not os.access("/usr/bin/say", os.X_OK):
            self.speech_error = "Local speech requires macOS with /usr/bin/say."
            return {"ok": False, "error": self.speech_error}
        self._stop_speaking()
        self.speech_error = ""
        self._speech_pending = text
        if self._speech_thread is None:
            self._speech_thread = threading.Thread(
                target=self._speech_loop, name="gaze-speech", daemon=True)
            self._speech_thread.start()
        return {"ok": True}

    def _speech_loop(self):
        # One worker reaps the cancelled child before starting any replacement.
        while True:
            with self.lock:
                text, self._speech_pending = self._speech_pending, None
                if text is None:
                    self._speech_thread = None
                    return
                try:
                    process = subprocess.Popen(
                        ["/usr/bin/say", "-f", "-"], stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        text=True, encoding="utf-8")
                except OSError:
                    self.speech_error = "Local speech could not start. Check /usr/bin/say."
                    self.publish()
                    continue
                self._speech_process = process
            try:
                process.communicate(text)
                failed = process.returncode != 0
            except (OSError, ValueError):
                process.kill()
                process.wait()
                failed = True
            with self.lock:
                if self._speech_process is process:
                    self._speech_process = None
                    if failed:
                        self.speech_error = "Local speech failed. Retry speaking."
                        self.publish()

    def control(self, action, item_id="", request_id=""):
        with self.lock:
            if action == "stop_speaking":
                self._stop_speaking()
                self.speech_error = ""
                self.publish()
                return {"ok": True}
            if action in ("speak", "auto_speak"):
                if not self.connected:
                    return {"ok": False, "error": "Reconnect with /gaze connect before speaking"}
                if action == "auto_speak":
                    self.auto_speak = not self.auto_speak
                    self.publish()
                    return {"ok": True, "auto_speak": self.auto_speak}
                if not self._item(item_id):
                    return {"ok": False, "error": "Answer unavailable. Select a saved item."}
                run = next((r for r in reversed(self.runs)
                            if r["item_id"] == item_id
                            and (r["request_id"] == request_id if request_id else r["text"].strip())), None)
                if run is None or not run["text"].strip():
                    return {"ok": False, "error": "No answer text is available to speak."}
                result = self._speak(run["text"])
                self.publish()
                return result
            if action in ("retry", "resume") and not self.connected:
                return {"ok": False, "error": "Reconnect with /gaze connect before resuming"}
            item = self._item(item_id)
            if action == "select" and item:
                for run in self.runs:
                    early = run["snapshot"].get("early_highlight")
                    if early and run["item_id"] != item_id:
                        early.superseded = True
                self.selected = item_id
                item["unread"] = False
            elif action == "new":
                self.selected = ""
                for run in self.runs:
                    early = run["snapshot"].get("early_highlight")
                    if early:
                        early.superseded = True
            elif action == "resume":
                self.paused = False
            elif action in ("retry", "skip") and item:
                run = next((r for r in reversed(self.runs)
                            if r["item_id"] == item_id and r["status"] in ("failed", "interrupted")
                            and (not request_id or r["request_id"] == request_id)), None)
                if run is None:
                    return {"ok": False, "error": "No failed request to retry or skip"}
                if action == "retry" and not run["utterance"]:
                    if not run.get("transcribe") or not self.connected:
                        return {"ok": False, "error": "Capture is no longer available"}
                    self.paused = False
                    self._event(run, "transcribing", error="")
                    self.start_transcription(run["request_id"], run["transcribe"])
                    return {"ok": True}
                if action == "retry" and len(self.pending) >= self.MAX_PENDING and run not in self.pending:
                    return {"ok": False, "error": "Inbox full"}
                if run in self.pending:
                    self.pending.remove(run)
                if action == "retry":
                    retry = self._new_run(run["utterance"], copy.deepcopy(run["snapshot"]), item_id)
                    retry["followup"] = run.get("followup", False)
                    retry["snapshot"].pop("early_highlight", None)
                    run["status"] = "retried"
                    self.pending.remove(retry)
                    self.pending.insert(0, retry)
                    self.paused = False
                else:
                    run["status"] = "skipped"
                    run.pop("transcribe", None)
            else:
                return {"ok": False, "error": "Unknown inbox command or item"}
            self.publish()
        self._pump()
        return {"ok": True}

    def _context(self, run):
        item = self._item(run["item_id"])
        snapshot = run["snapshot"]
        if snapshot.get("ok") is False:
            return ""
        previous = self.items[item["capture_order"] - 2] if item and item["capture_order"] > 1 else None
        # Rebuild from raw evidence, never truncate a rendered packet's fences.
        if snapshot.get("page_lines") is not None:
            sources = [("Selected item", item, snapshot)]
            if previous:
                sources.append(("Previous captured item (last one)", previous, previous["snapshot"]))
            lines = []
            for label, source, saved in sources:
                lines.append(f"{label}: #{source['capture_order']} {source['item_id']}; {source['target_label']}")
            # Required pointed values/row cells from BOTH captures precede optional
            # headers, history, source URLs and surrounding evidence.
            for key in ("essential_lines", "page_lines"):
                for n in range(max((len(s.get(key, [])) for _, _, s in sources), default=0)):
                    for label, source, saved in sources:
                        if n < len(saved.get(key, [])):
                            lines.append(f"#{source['capture_order']}: {saved[key][n]}")
                if key == "essential_lines":
                    for prior in reversed(self.runs):
                        if prior is not run and prior["item_id"] == run["item_id"] and prior["text"]:
                            # ponytail: latest exchange only; widen if older recall matters.
                            lines.append(f"Saved conversation: question {prior['utterance'][:300]}; answer {prior['text'][:1200]}")
                            break
                    for _, source, _ in sources:
                        if len(source["source_url"]) <= 600:
                            lines.append(f"Source #{source['capture_order']}: {source['source_url']}")
            return build_context(lines, run["utterance"], snapshot.get("pointer_evidence", ""))
        return snapshot.get("context", "")

    def pre(self, *, session_id="", user_message="", turn_id="", **_):
        with self.lock:
            run = self.active
            wire_owned = (run and run["session_id"] == session_id and run["wire"] == user_message)
            if (not turn_id or not (wire_owned or
                    self.connected and session_id == self.binding["session_id"])):
                return None
            if (session_id, turn_id) in self.seen_turns:
                return None
            self.seen_turns.append((session_id, turn_id))
            self.host_turn = turn_id
            self.host_session = session_id
            if wire_owned:
                run["turn_id"] = turn_id
            if not self.connected or session_id != self.binding["session_id"]:
                return None
            run = self.active
            if not run or run["wire"] != user_message:
                # Normal typed turns still attach fresh deictic evidence, but never steal inbox ownership.
                if has_deictic_pronoun(user_message):
                    from .service import resolve_now
                    snapshot = resolve_now(self.session, utterance=user_message, activate=False)
                    if snapshot.get("context"):
                        if snapshot.get("mode") != "simulated":
                            self.session.store_hover_snapshot(snapshot)
                            handles = list(dict.fromkeys(p["id"] for p in snapshot.get("pointed", [])
                                                         if p.get("available") and p.get("id")))
                            if handles:
                                self.session.actions.highlight(handles, self.session.resolution_id)
                            from .service import start_question_highlight
                            start_question_highlight(self.session, snapshot)
                        return {"context": snapshot["context"]}
                return None
            run["turn_id"] = turn_id
            snapshot = copy.deepcopy(run["snapshot"])
            snapshot["context"] = self._context(run)
            snapshot["actions_allowed"] = False
            if snapshot.get("context") and not snapshot.get("early_highlight"):
                try:
                    run["resolution_id"] = self.session.store_hover_snapshot(snapshot)
                    handles = list(dict.fromkeys(p["id"] for p in snapshot.get("pointed", [])
                                                 if p.get("available") and p.get("id")))
                    if handles:
                        self.session.actions.highlight(handles, run["resolution_id"])
                except Exception:
                    # Saved research remains usable after source navigation; actions stay disabled.
                    logger.debug("Saved target no longer highlightable", exc_info=True)
            self._event(run, "thinking")
            return {"context": snapshot["context"]} if snapshot.get("context") else None

    def _owned(self, session_id, turn_id):
        if not self.connected or session_id != self.binding["session_id"] or not turn_id:
            return None
        return next((r for r in reversed(self.runs) if r["session_id"] == session_id
                     and r["turn_id"] == turn_id), None)

    def delta(self, *, session_id="", turn_id="", delta="", kind="text", **_):
        if kind != "text" or not isinstance(delta, str) or not delta:
            return
        with self.lock:
            run = self._owned(session_id, turn_id)
            if not run or run["finished"] or run["ended"]:
                return
            run["text"] = (run["text"] + delta)[-self.MAX_TEXT:]
            if time.monotonic() - run.get("last_display", 0) >= .08:
                self._event(run, "streaming")

    def post(self, *, session_id="", turn_id="", assistant_response="", **_):
        with self.lock:
            run = self._owned(session_id, turn_id)
            if not run or run["finished"] or run["status"] in ("failed", "interrupted"):
                return
            if isinstance(assistant_response, str) and assistant_response:
                run["text"] = assistant_response[-self.MAX_TEXT:]
            run["finished"] = True
            self._event(run, "complete")

    def end(self, *, session_id="", turn_id="", failed=False, interrupted=False,
            completed=True, turn_exit_reason="", **_):
        with self.lock:
            if (self.host_session, self.host_turn) == (session_id, turn_id):
                self.host_turn = ""
                self.host_session = ""
            run = self.active
            if not run or (run["session_id"], run["turn_id"]) != (session_id, turn_id):
                run = self._owned(session_id, turn_id)
            if run and not run["ended"]:
                run["ended"] = True
                visible = (self.connected and session_id == self.binding["session_id"]
                           and run in self.runs)
                if visible and run["status"] not in ("interrupted", "skipped", "retried"):
                    if failed or interrupted or not completed:
                        run["finished"] = True
                        self.paused = True
                        self._event(run, "interrupted" if interrupted else "failed",
                                    error=turn_exit_reason or "Hermes turn failed")
                    else:
                        self._event(run, "complete")
            if self.active is run:
                self.active = None
        self._pump()

    def _disconnect(self):
        self._stop_speaking()
        self.paused = True
        self.capture_state = "idle"
        if self.active:
            self.active.update(finished=True, status="interrupted", error="Disconnected")
            item = self._item(self.active["item_id"])
            if item:
                item["unread"] = True
        self.binding = None
        self.session.clear_hover_snapshot()
        self.publish()

    def close(self):
        with self.lock:
            if not self.closed:
                self._disconnect()
                self.closed = True
