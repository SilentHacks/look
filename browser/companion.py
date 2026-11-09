"""One isolated overlay per page; reads follow focus, mutations retain their owner."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from .cdp_bridge import CdpSession
from .consent import ConsentChrome
from .ownership import OwnedChrome, OwnershipError

logger = logging.getLogger(__name__)


class NoForegroundTab(ConnectionError):
    """No attached supported document currently owns native foreground focus."""


class Companion:
    def __init__(self, http_url: str, *, profile_dir=None) -> None:
        self.chrome = OwnedChrome(http_url, profile_dir)
        self._owned_chrome = self.chrome
        self.source = "owned"
        self.on_disconnect = None
        self._consent_worker = None
        self._lifecycle = threading.RLock()
        self.overlay_config: dict = {}
        self.intent_nonce = ""
        self._tabs: dict[str, CdpSession] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._handler = None
        self._local = threading.local()
        self._inbox_event: dict | None = None
        self._last_foreground: dict | None = None
        self._start_owner: dict | None = None

    @property
    def http_url(self) -> str:
        return self._owned_chrome.http_url

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return any(tab.is_connected for tab in self._tabs.values())

    def set_intent_handler(self, handler) -> None:
        self._handler = handler

    def start(self, url: str = "about:blank") -> bool:
        if self.source == "existing":
            self.chrome.attach()  # Never launch or obtain new consent implicitly.
            return self.is_connected
        with self._lifecycle:
            try:
                self.chrome.start(url)
                return self.connect()
            except Exception:
                self.close()
                raise

    @property
    def connection_status(self) -> dict:
        if self.source == "existing":
            return dict(source=self.source, state=self.chrome.state, error=self.chrome.error)
        return dict(source=self.source, state="connected" if self.is_connected else "stopped", error="")

    def start_existing(self, *, metadata_path=None, timeout=120, on_ready=None, on_error=None) -> dict:
        """Explicit disclosed action only; return immediately so Stop can cancel consent."""
        with self._lifecycle:
            if self.source == "owned" and (self.is_connected or self._thread and self._thread.is_alive()):
                raise OwnershipError("Stop Look before changing browser source.")
            if (self._consent_worker and self._consent_worker.is_alive()
                    and self.chrome.state not in ("disconnected", "failed")):
                return self.connection_status
            if self.source == "existing" and self.chrome.live:
                return self.connection_status
            self.close()
            self.source = "existing"
            chrome = ConsentChrome(metadata_path=metadata_path, lease_dir=self._owned_chrome.profile)
            self.chrome = chrome
            stopped = self._stop = threading.Event()
            chrome.on_loss = lambda: self._consent_lost(chrome)

            def run():
                try:
                    chrome.start(timeout=timeout)
                    with self._lifecycle:
                        if chrome is not self.chrome or not chrome.live:
                            return
                        self.connect()
                    while chrome is self.chrome and chrome.live and not self._stop.is_set():
                        if self.is_connected:
                            # Stop and binding cannot pass each other after a late Allow.
                            with self._lifecycle:
                                if chrome is self.chrome and chrome.live and not self._stop.is_set() and on_ready:
                                    on_ready()
                            break
                        self._stop.wait(.1)
                except (OSError, ValueError):
                    with self._lifecycle:
                        if chrome is self.chrome and not stopped.is_set() and chrome.error and on_error:
                            on_error(chrome.error)
            self._consent_worker = threading.Thread(target=run, name="look-chrome-approval", daemon=True)
            self._consent_worker.start()
            return self.connection_status

    def use_owned(self) -> None:
        with self._lifecycle:
            if self.source == "existing":
                if self.chrome.live or self._consent_worker and self._consent_worker.is_alive():
                    raise OwnershipError("Stop Look before changing browser source.")
                self.close()
                self.chrome = self._owned_chrome
                self.source = "owned"

    def _consent_lost(self, chrome) -> None:
        if self.chrome is chrome:
            self._stop.set()  # Wake startup before its lifecycle lock is available.
        with self._lifecycle:
            if self.chrome is chrome:
                self._stop.set()
                if self.on_disconnect:
                    self.on_disconnect()

    def connect(self) -> bool:
        with self._lifecycle:
            self.chrome.attach()
            with self._lock:
                if self._stop.is_set() and self._thread and self._thread.is_alive():
                    raise OwnershipError("Look is still stopping. Retry /look start.")
                if self._thread is None or not self._thread.is_alive():
                    self._stop = threading.Event()
                    self._thread = threading.Thread(target=self._watch, name="hermes-gaze-tabs", daemon=True)
                    self._thread.start()
            # Admission waits for the first attachment, not every background page.
            for _ in range(80):
                if self.is_connected:
                    return True
                if self._stop.wait(.1):
                    break
            return False

    def push_level(self, target: str, level: float) -> None:
        with self._lock:
            tab = self._tabs.get(target)
        if tab is not None:
            tab.push_level(level)

    def open_url(self, url: str, *, target: str | None = None, document: str | None = None) -> None:
        """Open beside an exact source, never Chrome's mutable last-used profile."""
        source = None
        if self.source == "existing":
            if target:
                with self._lock:
                    source = self._tabs.get(target)
                if source is None or not document or source._context_unique_id != document:
                    raise OwnershipError("The source profile cannot be proved. Open the page yourself.")
            else:
                source = self._target()
        self._create_target(url, source)

    def _create_target(self, url: str, source: CdpSession | None = None) -> str:
        params = {"url": url}
        if self.source == "existing":
            self.chrome.attach()
            if source is None or not source.is_connected:
                raise OwnershipError("The source profile cannot be proved. Open the page yourself.")
            context = self.chrome.command("Target.getBrowserContexts").get("defaultBrowserContextId")
            info = self.chrome.command("Target.getTargetInfo", {"targetId": source._target_id})["targetInfo"]
            if (context != self.chrome.default_context or info.get("browserContextId") != context
                    or info.get("targetId") != source._target_id):
                raise OwnershipError("Chrome's profile changed. Stop Look and connect again explicitly.")
            if not url.startswith(("http://", "https://")):
                raise OwnershipError("Existing Chrome supports ordinary web pages only.")
            params["browserContextId"] = context
        target = self.chrome.command("Target.createTarget", params)["targetId"]
        if self.source == "existing":
            info = self.chrome.command("Target.getTargetInfo", {"targetId": target})["targetInfo"]
            if info.get("targetId") != target or info.get("browserContextId") != params["browserContextId"]:
                raise OwnershipError("New tab profile could not be verified; outcome unknown. Do not repeat the action.")
        return target

    def show_document(self, target: str | None, document: str | None) -> bool:
        """Bring a captured source tab forward only if that exact document still exists."""
        with self._lock:
            tab = self._tabs.get(target) if target else None
        if tab is None or not document or tab._context_unique_id != document:
            return False
        try:
            tab._submit(tab._send_cmd("Page.bringToFront", {}, timeout=2.), 3.)
            return True
        except Exception:
            logger.debug("Source tab could not come forward", exc_info=True)
            return False

    def open_blank(self) -> None:
        self.open_url("about:blank")

    @staticmethod
    def _document_owner(tab: CdpSession) -> dict:
        return dict(browser_target=tab._target_id, browser_document=tab._context_unique_id,
                    browser_route=tab._route_id)

    def capture_return_owner(self) -> dict | None:
        """Terminal setup may use the last observed page, never an arbitrary listed tab."""
        try:
            return self._document_owner(self._target())
        except NoForegroundTab:
            return dict(self._last_foreground) if self._last_foreground else None

    def _return_tab(self, owner: dict | None) -> CdpSession | None:
        with self._lock:
            tab = self._tabs.get((owner or {}).get("browser_target"))
        if (tab is None or not owner.get("browser_document") or
                self._document_owner(tab) != owner):
            return None
        return tab

    def open_start_page(self, valid) -> dict:
        """Explicit fallback only. Never navigate an existing, unrelated tab."""
        from pathlib import Path
        if self.source == "existing":
            raise OwnershipError("Open an ordinary web page in your Chrome, then return to it. Look will not open a local setup file there.")
        if not valid():
            raise ConnectionError("Setup connection changed. Start setup again in Hermes.")
        if self._return_tab(self._start_owner) is not None:
            return dict(self._start_owner)
        url = Path(__file__).with_name("start.html").resolve().as_uri()
        target = self.chrome.command("Target.createTarget", {"url": url})["targetId"]
        deadline = time.monotonic() + 5
        while valid() and not self._stop.is_set() and time.monotonic() < deadline:
            with self._lock:
                tab = self._tabs.get(target)
            if tab and tab.is_connected and tab._context_unique_id and tab._ui_frames and not tab._main_frame_loading:
                self._start_owner = self._document_owner(tab)
                return dict(self._start_owner)
            self._stop.wait(.05)
        raise ConnectionError("Start page did not attach. Open a page in the companion and restart setup.")

    def return_to_document(self, owner: dict | None, valid) -> dict:
        """One activation, then bounded exact-document foreground/renderer observations."""
        if not valid():
            return {"ok": False, "error": "Setup connection changed. Start setup again in Hermes."}
        tab = self._return_tab(owner)
        if tab is None:
            return {"ok": False, "missing": True}
        if not tab.is_connected or not self.show_document(owner["browser_target"], owner["browser_document"]):
            return {"ok": False, "error": "Chrome did not acknowledge activation. Try again or open the start page."}
        deadline = time.monotonic() + 3
        while valid() and not self._stop.is_set() and time.monotonic() < deadline:
            if self._return_tab(owner) is not tab:
                return {"ok": False, "missing": True}
            if tab.is_connected and tab._ui_frames and not tab._main_frame_loading:
                frames = dict(tab._ui_frames)
                try:
                    ready = tab.eval_js_once(
                        "document.visibilityState === 'visible' && document.hasFocus() && "
                        "!!window.__HERMES_GAZE_OVERLAY__?.returnFromCalibration()",
                        timeout=.4, context_id=owner["browser_document"])
                    if (ready and set(frames) == {"card", "pill"} and
                            all(tab.eval_js_once("!!window.__HERMES_GAZE_PANEL__", timeout=.4, context_id=context[1])
                                for context in frames.values()) and frames == tab._ui_frames
                            and tab.eval_js_once("document.visibilityState === 'visible' && document.hasFocus()",
                                                 timeout=.4, context_id=owner["browser_document"])
                            and valid() and self._return_tab(owner) is tab):
                        self._last_foreground = dict(owner)
                        return {"ok": True}
                except (ConnectionError, RuntimeError, TimeoutError):
                    pass  # Read observations only; never repeat the foreground command.
            self._stop.wait(.05)
        return {"ok": False, "error": "Chrome foreground focus was not observed. Try again or open the start page."}

    def _owned_tab(self, owner: dict) -> CdpSession:
        with self._lock:
            tab = self._tabs.get(owner.get("browser_target"))
        if (tab is None or tab._context_unique_id != owner.get("browser_document")
                or tab._route_id != owner.get("browser_route")):
            raise ConnectionError("Task document or route changed")
        self.eval_js_once("true", target=tab._target_id, document=owner["browser_document"],
                          route=owner["browser_route"])
        return tab

    def action_navigate(self, url: str, *, new_tab: bool, **owner) -> dict:
        """One navigation command; wait only for reads, never replay it."""
        from ..browser_tasks import navigation_url
        url = navigation_url(url)
        tab = self._owned_tab(owner)
        old_document = tab._context_unique_id
        if new_tab:
            target = self._create_target(url, tab)
            self.chrome.command("Target.activateTarget", {"targetId": target})
        else:
            result = tab._submit(tab._send_cmd("Page.navigate", {"url": url}, timeout=5.), 6.)
            if result.get("errorText"):
                raise ValueError("Navigation failed: " + result["errorText"])
            target = tab._target_id
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with self._lock:
                destination = self._tabs.get(target)
            if destination and destination.is_connected and destination._ui_frames and not destination._main_frame_loading:
                document, route = destination._context_unique_id, destination._route_id
                # Same-document navigation may retain the exact document.
                if (new_tab or document != old_document or destination._route_id != owner["browser_route"]
                        or not result.get("loaderId")):
                    if (document == destination._context_unique_id and route == destination._route_id
                            and destination.eval_js_once("document.readyState !== 'loading' && document.hasFocus()",
                                                         timeout=1., context_id=document)):
                        return dict(browser_target=target, browser_document=document, browser_route=route)
            if self._stop.wait(.05):
                break
        raise ConnectionError("Navigation outcome unknown; do not repeat it automatically")

    def action_after_click(self, *, same_document: bool, **owner) -> dict:
        """Follow only the clicked target through redirects; never retarget by focus."""
        with self._lock:
            tab = self._tabs.get(owner["browser_target"])
        if tab is None:
            raise ConnectionError("The clicked tab was closed")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            document, route = tab._context_unique_id, tab._route_id
            capture = None
            if document and tab.is_connected and not tab._main_frame_loading and (same_document or document != owner["browser_document"] or route != owner["browser_route"]):
                try:
                    capture = tab.eval_js_once(
                        "document.visibilityState === 'visible' && document.hasFocus() ? "
                        "window.__HERMES_GAZE_OVERLAY__?.captureActionContext() : {foreground:false}",
                        timeout=1., context_id=document)
                except (ConnectionError, RuntimeError, TimeoutError):
                    pass  # Retriable read while the owned document rearms, never another click.
            if isinstance(capture, dict):
                if capture.get("foreground") is False:
                    raise ConnectionError("Clicked tab lost foreground")
                if (capture.get("snapshot_id") and not tab._main_frame_loading
                        and document == tab._context_unique_id and route == tab._route_id):
                    capture.update(browser_target=owner["browser_target"], browser_document=document, browser_route=route)
                    return capture
            if self._stop.wait(.05):
                break
        raise ConnectionError("Click destination is unavailable; do not repeat the click")


    def action_key(self, key: str, **owner) -> None:
        codes = {"ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
                 "Home": 36, "End": 35, "Tab": 9}
        if key not in codes:
            raise ValueError("Unsupported nonactivation key")
        tab = self._owned_tab(owner)
        for kind in ("keyDown", "keyUp"):
            if tab._context_unique_id != owner["browser_document"] or tab._route_id != owner["browser_route"]:
                raise ConnectionError("Key target document changed")
            tab._submit(tab._send_cmd("Input.dispatchKeyEvent", {
                "type": kind, "key": key, "code": key, "windowsVirtualKeyCode": codes[key]}, timeout=2.), 3.)

    def _watch(self) -> None:
        while not self._stop.is_set():
            try:
                targets = self.chrome.command("Target.getTargets")["targetInfos"]
                if self.source == "existing":
                    context = self.chrome.command("Target.getBrowserContexts").get("defaultBrowserContextId")
                    if context != self.chrome.default_context:
                        self.chrome.abort()
                        raise OwnershipError("Chrome's profile changed. Connect again explicitly.")
                targets = [dict(t, id=t["targetId"]) for t in targets]
                pages = {str(t["id"]): t for t in targets
                         if t.get("type") == "page"
                         and str(t.get("url", "")).startswith(
                             ("http://", "https://") if self.source == "existing"
                             else ("http://", "https://", "file://", "about:blank"))
                         and (self.source != "existing" or t.get("browserContextId") == self.chrome.default_context)}
                # Navigation can temporarily clear a listed target's URL. It is not a closed tab.
                # Keep the pinned transport; only eligible URLs admit new attachments below.
                with self._lock:
                    retained = {str(t["id"]) for t in targets if self.source != "existing"
                                or t.get("browserContextId") == self.chrome.default_context}
                    removed = [self._tabs.pop(key) for key in set(self._tabs) - retained]
                for tab in removed:
                    tab.close()
                for key, page in pages.items():
                    if self._stop.is_set():
                        break
                    with self._lock:
                        if self._stop.is_set():
                            break
                        tab = self._tabs.get(key)
                        if tab is None:
                            tab = CdpSession(self.http_url, owner=self.chrome)
                            tab.tab = page
                            tab.overlay_config = self.overlay_config
                            tab.intent_nonce = self.intent_nonce
                            tab.set_intent_handler(lambda intent, reply, key=key: self._dispatch(key, intent, reply))
                            self._tabs[key] = tab
                    if not tab.is_connected:
                        self._attach(tab)
                        continue
                    self._display_pending(tab)
                    if tab._context_unique_id:
                        try:
                            owner = self._document_owner(tab)
                            if tab.eval_js_once("document.visibilityState === 'visible' && document.hasFocus()",
                                                timeout=.3, context_id=owner["browser_document"]):
                                if self._document_owner(tab) == owner:
                                    self._last_foreground = owner
                        except (ConnectionError, RuntimeError, TimeoutError):
                            pass
                    tab.flush_replies()
            except Exception:
                logger.debug("Chrome tab discovery unavailable", exc_info=True)
                # Existing transports belong to the lost browser, not its replacement.
                with self._lock:
                    tabs, self._tabs = list(self._tabs.values()), {}
                    self._last_foreground = self._start_owner = None
                for tab in tabs:
                    tab.close()
                if self.source == "existing":
                    self.chrome.abort()
                    self.chrome.close()
                    break  # No new authorization from discovery/reconnect loops.
            self._stop.wait(.25)
        if self.source == "existing":
            with self._lock:
                tabs, self._tabs = list(self._tabs.values()), {}
            for tab in tabs:
                tab.close()
            self.chrome.close()

    def _attach(self, tab: CdpSession) -> None:
        """A page that won't load must not hold up every other tab; retry it now and then."""
        now = time.monotonic()
        if getattr(tab, "_attaching", False) or now < getattr(tab, "_attach_after", 0.):
            return
        tab._attaching = True

        def run() -> None:
            try:
                tab.connect()
            finally:
                tab._attaching = False
                tab._attach_after = time.monotonic() + 2.

        threading.Thread(target=run, name="hermes-gaze-attach", daemon=True).start()

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
                    self._last_foreground = self._document_owner(tab)
                    return tab
            except Exception:
                continue
        raise NoForegroundTab("No supported Chrome page has focus")


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

    def _display_pending(self, tab: CdpSession, event: dict | None = None) -> None:
        pending = tab.session_event
        if event is None:
            event = (pending if pending and pending.get("type") == "action_task"
                     and pending.get("browser_document") == tab._context_unique_id
                     and pending is not getattr(tab, "_delivered_task_event", None)
                     else self._inbox_event or pending)
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
                if event.get("type") == "action_task":
                    tab._delivered_task_event = event
        except Exception:
            logger.debug("Answer display unavailable", exc_info=True)

    def display(self, event: dict) -> None:
        # Inbox recall is session-wide, but only the focused protected renderer receives it.
        with self._lock:
            if event.get("type") == "inbox":
                self._inbox_event = dict(event)
                event = self._inbox_event
                try:
                    tabs = [self._target()]
                except ConnectionError:
                    tabs = []
            else:
                tab = self._tabs.get(event.get("browser_target"))
                tabs = [tab] if tab is not None else []
                if tab is not None:
                    tab.session_event = dict(event)
                    event = tab.session_event
        for tab in tabs:
            self._display_pending(tab, event)

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
        if (self.source == "existing" and self._consent_worker and self._consent_worker.is_alive()
                and self.chrome.state in ("idle", "discovering", "waiting")):
            self.chrome.close()  # Cancel the handshake before waiting for startup.
        with self._lifecycle:
            if self._thread:
                self._thread.join()
            with self._lock:
                tabs, self._tabs = list(self._tabs.values()), {}
                self._last_foreground = self._start_owner = None
            for tab in tabs:
                tab.close()
            # All input transports are terminal before another runtime can acquire.
            self.chrome.close()
