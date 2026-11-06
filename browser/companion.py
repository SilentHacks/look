"""One isolated overlay per page; reads follow focus, mutations retain their owner."""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from typing import Any

from .cdp_bridge import CdpSession

logger = logging.getLogger(__name__)


class Companion:
    def __init__(self, http_url: str) -> None:
        self.http_url = http_url.rstrip("/")
        self.overlay_config: dict = {}
        self.intent_nonce = ""
        self._tabs: dict[str, CdpSession] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handler = None
        self._local = threading.local()
        self._inbox_event: dict | None = None

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return any(tab.is_connected for tab in self._tabs.values())

    def set_intent_handler(self, handler) -> None:
        self._handler = handler

    def connect(self) -> bool:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._watch, name="hermes-gaze-tabs", daemon=True)
                self._thread.start()
        # Admission waits for the first attachment, not for every background page.
        for _ in range(80):
            if self.is_connected:
                return True
            if self._stop.wait(.1):
                break
        return False

    def open_blank(self) -> None:
        request = urllib.request.Request(self.http_url + "/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(request, timeout=3) as response:
            response.read()

    def _watch(self) -> None:
        while not self._stop.is_set():
            try:
                with urllib.request.urlopen(self.http_url + "/json/list", timeout=2) as response:
                    pages = {str(t["id"]): t for t in json.load(response)
                             if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
                             and str(t.get("url", "")).startswith(("http://", "https://", "file://", "about:blank"))}
                with self._lock:
                    removed = [self._tabs.pop(key) for key in set(self._tabs) - pages.keys()]
                for tab in removed:
                    tab.close()
                for key, page in pages.items():
                    if self._stop.is_set():
                        break
                    with self._lock:
                        tab = self._tabs.get(key)
                    if tab is None:
                        tab = CdpSession(self.http_url)
                        tab.tab = page
                        tab.overlay_config = self.overlay_config
                        tab.intent_nonce = self.intent_nonce
                        tab.set_intent_handler(lambda intent, reply, key=key: self._dispatch(key, intent, reply))
                        with self._lock:
                            self._tabs[key] = tab
                    if not tab.is_connected:
                        tab.connect()
                    self._display_pending(tab)
                    tab.flush_replies()
            except Exception:
                logger.debug("Chrome tab discovery unavailable", exc_info=True)
            self._stop.wait(.25)

    def _dispatch(self, key: str, intent: dict, reply) -> None:
        if self._handler is None:
            return
        self._local.target = key
        try:
            # Source identity comes from the transport, never website-supplied JSON.
            intent["_browser_target"] = key
            self._handler(intent, reply)
        finally:
            self._local.target = None

    def _target(self) -> CdpSession:
        with self._lock:
            target = self._local.__dict__.get("target")
            if target:
                tab = self._tabs.get(target)
                if tab is None:
                    raise ConnectionError("The question's tab was closed")
                return tab
            tabs = list(self._tabs.values())
        for tab in tabs:
            if not tab.is_connected:
                continue
            try:
                if tab.eval_js("document.visibilityState === 'visible' && document.hasFocus()", timeout=.5):
                    return tab
            except Exception:
                continue
        raise ConnectionError("No supported Chrome page has focus")


    def eval_js(self, expression: str, timeout: float = 6.) -> Any:
        return self._target().eval_js(expression, timeout)

    def capture(self, expression: str = "window.__HERMES_GAZE_OVERLAY__?.captureCursorContext()") -> dict:
        tab = self._target()
        document, route = tab._context_unique_id, tab._route_id
        capture = tab.eval_js_once(expression, context_id=document) or {}
        if tab._context_unique_id != document or tab._route_id != route:
            raise ConnectionError("Evidence document or route changed during capture")
        capture.update(browser_target=tab._target_id, browser_document=document, browser_route=route)
        return capture

    def eval_js_once(self, expression: str, timeout: float = 6., *, target: str | None = None,
                     document: str | None = None, route: int | None = None) -> Any:
        if not target or not document:
            raise ConnectionError("Snapshot has no captured browser owner")
        with self._lock:
            tab = self._tabs.get(target)
        if tab is None:
            raise ConnectionError("The snapshot's tab was closed")
        if tab._context_unique_id != document:
            raise ConnectionError("The snapshot's document was replaced")
        if route is not None and tab._route_id != route:
            raise ConnectionError("The snapshot's route changed")
        context_id = document
        # Check and mutation share ONE evaluation. Never reconnect/replay a mutation.
        return tab.eval_js_once(
            "(() => {if(document.visibilityState !== 'visible' || !document.hasFocus()) "
            "throw Error('Snapshot tab is not foreground'); return (" + expression + ");})()", timeout,
            context_id=context_id)

    def recording_loss(self, target: str, document: str) -> str | None:
        """Only definite document/focus loss cancels capture; routes guard actions only."""
        with self._lock:
            tab = self._tabs.get(target)
        if tab is None:
            return "Recording cancelled: the source tab was closed."
        if not tab.is_connected:
            return None
        if tab._context_unique_id != document:
            return "Recording cancelled: the source document changed."
        # No reconnect/retry into another document when checking recording ownership.
        state = tab.eval_js_once(
            "({hidden:document.visibilityState !== 'visible', focused:document.hasFocus()})",
            timeout=.5, context_id=document)
        if tab._context_unique_id != document:
            return "Recording cancelled: the source document changed."
        if isinstance(state, dict):
            if state.get("hidden") is True:
                return "Recording cancelled: the source tab is hidden."
            if state.get("focused") is False:
                return "Recording cancelled: the source tab lost focus."
        return None

    def _display_pending(self, tab: CdpSession) -> None:
        event = self._inbox_event or tab.session_event
        if not event or not tab.is_connected:
            return
        inbox = event.get("type") == "inbox"
        document = tab._context_unique_id
        if (not document or (not inbox and event.get("browser_document") != document)
                or (event is getattr(tab, "_displayed_event", None)
                    and document == getattr(tab, "_displayed_document", None))):
            return
        try:
            if inbox and not tab.eval_js(
                    "document.visibilityState === 'visible' && document.hasFocus()", timeout=.5):
                return
            delivered = tab.eval_js_once(
                "(() => {if(document.visibilityState !== 'visible' || !document.hasFocus()) return false;"
                "window.__HERMES_GAZE_OVERLAY__?.onSessionEvent(" + json.dumps(event) + ");return true})()",
                timeout=1., context_id=document)
            if delivered:
                tab._displayed_event = event
                tab._displayed_document = document
        except Exception:
            logger.debug("Answer display unavailable", exc_info=True)

    def display(self, event: dict) -> None:
        # Inbox recall is session-wide, but only the focused protected renderer receives it.
        with self._lock:
            if event.get("type") == "inbox":
                self._inbox_event = dict(event)
                try:
                    tabs = [self._target()]
                except ConnectionError:
                    tabs = []
            else:
                tab = self._tabs.get(event.get("browser_target"))
                tabs = [tab] if tab is not None else []
                if tab is not None:
                    tab.session_event = dict(event)
        for tab in tabs:
            self._display_pending(tab)

    def push_overlay_config(self) -> None:
        with self._lock:
            tabs = list(self._tabs.values())
        for tab in tabs:
            tab.overlay_config = self.overlay_config
            tab.intent_nonce = self.intent_nonce
            if tab.is_connected:
                tab.push_overlay_config()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=12)
        with self._lock:
            tabs, self._tabs = list(self._tabs.values()), {}
        for tab in tabs:
            tab.close()
