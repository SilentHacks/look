"""Current-snapshot actions; approval is accepted only from the trusted binding."""
from __future__ import annotations

import json
import logging
import re
import secrets
import threading
from typing import Any

from .resolver.bayesian_fusion import _DESTRUCTIVE_VERBS, classify_utterance_intent

_RISKY_LABEL = re.compile(r"delete|remove|purge|drop|destroy|pay|buy|checkout|submit|send|transfer|revoke|danger|destruct", re.IGNORECASE)
logger = logging.getLogger(__name__)


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "executed": False, "error": error}


class SnapshotActions:
    def __init__(self, session: Any) -> None:
        self.session = session
        # Serialize activation and mutations, without holding the session state lock over CDP.
        self._lock = threading.RLock()
        self._pending: dict[str, Any] | None = None

    def _browser(self, method: str, *args: Any) -> dict[str, Any]:
        expression = f"window.__HERMES_GAZE_OVERLAY__.{method}({','.join(json.dumps(arg) for arg in args)})"
        try:
            result = self.session.eval_js_once(expression)
        except Exception as exc:
            logger.debug("Snapshot browser operation failed", exc_info=True)
            if method == "clickSnapshot":
                return {"ok": False, "executed": None, "outcome": "unknown",
                        "error": f"Click outcome unknown: {exc}. Do not retry automatically."}
            return _failure(f"browser {method} failed: {exc}")
        if not isinstance(result, dict) or result.get("ok") is not True:
            return _failure(str(result.get("error") or f"browser {method} failed") if isinstance(result, dict)
                            else f"browser {method} returned no result")
        return result

    def _current(self, resolution_id: int, handles: list[str], *, highlighting: bool = False) -> tuple[dict[str, Any] | None, str]:
        with self.session._lock:
            snapshot = self.session.last_hover_snapshot
            if type(resolution_id) is not int or resolution_id != self.session.resolution_id:
                return None, "stale resolution"
            if not snapshot or snapshot.get("ok") is not True or not snapshot.get("snapshot_id"):
                return None, "No successful cursor snapshot"
            if snapshot.get("resolution_id") != resolution_id or not snapshot.get("browser_active"):
                return None, "snapshot is not active in Chrome"
            if snapshot.get("actions_allowed") is False and not highlighting:
                return None, "Actions are unavailable for this read-only turn"
            known = snapshot.get("handles")
            if not isinstance(known, dict) or any(not isinstance(h, str) or h not in known for h in handles):
                return None, "unknown snapshot handle"
            return snapshot, ""

    def invalidate(self) -> None:
        with self._lock:
            had_pending = self._pending is not None
            self._pending = None
            if had_pending:
                try:
                    self.session.eval_js_once("window.__HERMES_GAZE_OVERLAY__.clearActionConfirmation()")
                except Exception:
                    logger.debug("Confirmation UI unavailable after revocation", exc_info=True)

    def highlight(self, handles: list[str], resolution_id: int, hud_message: str = "") -> dict[str, Any]:
        with self._lock:
            if not isinstance(handles, list) or not handles:
                return _failure("handles must be a nonempty list")
            snapshot, error = self._current(resolution_id, handles, highlighting=True)
            if error:
                return _failure(error)
            result = self._browser("highlightSnapshot", snapshot["snapshot_id"], resolution_id, handles, str(hud_message))
            _, error = self._current(resolution_id, handles, highlighting=True)
            if error:
                return _failure(error)
            if not result.get("ok"):
                return result
            return {"ok": True, "resolution_id": resolution_id, "handles": handles}

    def _inspect(self, snapshot: dict[str, Any], handle: str, resolution_id: int) -> dict[str, Any]:
        result = self._browser("inspectSnapshot", snapshot["snapshot_id"], resolution_id, handle)
        _, error = self._current(resolution_id, [handle])
        if error:
            return _failure(error)
        if not result.get("ok"):
            return result
        if result.get("handle") != handle or not result.get("fingerprint"):
            return _failure("invalid browser target descriptor")
        if result.get("disabled") or result.get("clickable") is not True:
            return _failure("target is disabled or noninteractive")
        return result

    def _execute(self, snapshot: dict[str, Any], handle: str, resolution_id: int, fingerprint: str) -> dict[str, Any]:
        _, error = self._current(resolution_id, [handle])
        if error:
            return _failure(error)
        result = self._browser("clickSnapshot", snapshot["snapshot_id"], resolution_id, handle, fingerprint)
        if result.get("outcome") == "unknown":
            self.session.clear_hover_snapshot()
            return result
        if not result.get("ok") or result.get("executed") is not True:
            return _failure(str(result.get("error") or "browser did not execute the click"))
        return {"ok": True, "executed": True, "handle": handle, "resolution_id": resolution_id}

    def click(self, handle: str, resolution_id: int) -> dict[str, Any]:
        with self._lock:
            self.invalidate()
            snapshot, error = self._current(resolution_id, [handle])
            if error:
                return _failure(error)
            live = self._inspect(snapshot, handle, resolution_id)
            if not live.get("ok"):
                return live
            utterance = str(snapshot.get("utterance") or "")
            # ponytail: demo-only lexical policy; real-site rollout needs a reviewed action policy.
            risky = (classify_utterance_intent(utterance) == "destructive_action"
                     or bool(set(re.findall(r"[a-z]+", utterance.lower())) & _DESTRUCTIVE_VERBS)
                     or bool(_RISKY_LABEL.search(str(live.get("label") or "") + " " + str(live.get("class_name") or "")))
                     or bool(live.get("form_submit")))
            if not risky:
                return self._execute(snapshot, handle, resolution_id, live["fingerprint"])
            action_id = secrets.token_urlsafe(24)
            label = str(live.get("label") or handle)
            pending = {"action_id": action_id, "resolution_id": resolution_id,
                       "snapshot_id": snapshot["snapshot_id"], "handle": handle,
                       "fingerprint": live["fingerprint"]}
            self._pending = pending
            result = self._browser("requestActionConfirmation", {
                "action_id": action_id, "resolution_id": resolution_id, "label": label, "handle": handle,
                "description": "Confirm this action with a click in Chrome."})
            _, error = self._current(resolution_id, [handle])
            if not result.get("ok") or error or self._pending is not pending:
                self.invalidate()
                return _failure(error or str(result.get("error") or "confirmation invalidated"))
            # The model sees no approval token: only the nonce-checked browser binding can confirm.
            return {"ok": True, "executed": False, "confirmation_required": True,
                    "label": label, "resolution_id": resolution_id}

    def confirm(self, action_id: str, resolution_id: int, approved: bool) -> dict[str, Any]:
        """Internal trusted-binding entry point, never registered as a model tool."""
        with self._lock:
            pending = self._pending
            if (not pending or not isinstance(action_id, str)
                    or not secrets.compare_digest(action_id.encode("utf-8", "surrogatepass"), pending["action_id"].encode("utf-8"))
                    or type(resolution_id) is not int or resolution_id != pending["resolution_id"]):
                return _failure("unknown or stale confirmation")
            self.invalidate()  # Consume before I/O, cancellation, or any failure; never retry approval.
            if type(approved) is not bool:
                return _failure("invalid confirmation decision")
            snapshot, error = self._current(resolution_id, [pending["handle"]])
            if error:
                return _failure(error)
            if snapshot["snapshot_id"] != pending["snapshot_id"]:
                return _failure("stale snapshot")
            if not approved:
                return {"ok": True, "executed": False, "cancelled": True, "resolution_id": resolution_id}
            live = self._inspect(snapshot, pending["handle"], resolution_id)
            if not live.get("ok"):
                return live
            if live["fingerprint"] != pending["fingerprint"]:
                return _failure("target changed since confirmation was requested")
            return self._execute(snapshot, pending["handle"], resolution_id, pending["fingerprint"])
