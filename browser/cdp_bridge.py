"""Chrome DevTools Protocol (CDP) bridge for hermes-gaze.

Companion discovery follows foreground Chrome pages. Each page has one persistent
websocket and worker loop; the overlay and nonce-checked intent binding live in
the named CDP isolated world. Python retains replies only for their source document.
Reads may reconnect; mutations use ``eval_js_once`` and never replay.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import functools
import html
import json
import logging
import secrets
import subprocess
import threading
import time
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from ..resolver.cursor_context import stamp_resolution

try:
    from plugins.plugin_utils import lazy_singleton
except ImportError:
    def lazy_singleton(fn: Callable[..., Any]) -> Callable[..., Any]:
        """Thread-safe local copy of plugins.plugin_utils.lazy_singleton."""
        lock, inst = threading.Lock(), [None]

        @functools.wraps(fn)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            if inst[0] is None:
                with lock:
                    if inst[0] is None:
                        inst[0] = fn(*args, **kwargs)
            return inst[0]

        return _wrapper

from ..actions import SnapshotActions
from ..resolver.bayesian_fusion import CandidateElement, ResolutionResult
from ..tracker.recalibrator import OnlineRecalibrator
from ..tracker.simulated_gaze import FixationRingBuffer, FixationSample, SimulatedPointerTracker

logger = logging.getLogger(__name__)

_OVERLAY_JS_PATH = Path(__file__).with_name("overlay.js")
_INTENT_BINDING = "__hermesGazeIntent"
_WORLD = "hermes-gaze"
_overlay_cache: Tuple[float, str] = (0.0, "")


def _overlay_source() -> str:
    """Overlay JS source, cached keyed by file mtime."""
    global _overlay_cache
    try:
        mtime = _OVERLAY_JS_PATH.stat().st_mtime
        src = _overlay_cache[1] if _overlay_cache[0] == mtime else _OVERLAY_JS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""
    _overlay_cache = (mtime, src)
    return src


def _guarded_inject(src: str) -> str:
    # The overlay IIFE tears down and replaces any prior instance (preserving input
    # state) — always re-run it so a stale api from an older build never survives an
    # upgrade (e.g. one missing setIntentNonce).
    return src


def _fixation_from_wire(raw: Dict[str, Any], source: str = "hover") -> FixationSample:
    t_end = float(raw.get("t", raw.get("t_end", 0.0)) or 0.0)
    sigma = float(raw.get("sigma", raw.get("sigma_x", 24.0)) or 24.0)
    return FixationSample(
        x_doc=float(raw.get("x_doc", 0.0)), y_doc=float(raw.get("y_doc", 0.0)),
        x_vp=float(raw.get("x_vp", 0.0)), y_vp=float(raw.get("y_vp", 0.0)),
        t_start=float(raw.get("t_start", t_end - 0.12)), t_end=t_end,
        duration_ms=float(raw.get("duration_ms", 120.0)),
        sigma_x=sigma, sigma_y=float(raw.get("sigma_y", sigma) or sigma),
        source=str(raw.get("source") or source),
    )


def _candidate_from_wire(raw: Dict[str, Any]) -> CandidateElement:
    """CandidateElement from the overlay's wire dict (prefers CandidateElement.from_wire)."""
    from_wire = getattr(CandidateElement, "from_wire", None)
    if callable(from_wire):
        return from_wire(raw)
    rvp = tuple(float(v) for v in (raw.get("rect_vp") or [0, 0, 40, 24]))
    rdoc = tuple(float(v) for v in (raw.get("rect_doc") or rvp))
    return CandidateElement(
        id=str(raw.get("id") or "cand"), tag=str(raw.get("tag") or "div"),
        role=str(raw.get("role") or "button"), label=str(raw.get("label") or ""),
        selector=str(raw.get("selector") or ""),
        rect_doc=rdoc, rect_vp=rvp,  # type: ignore[arg-type]
        is_container=bool(raw.get("is_container", False)),
        is_interactive=bool(raw.get("is_interactive", True)),
        is_destructive=bool(raw.get("is_destructive", False)),
        summary=str(raw.get("summary") or ""), consequence=str(raw.get("consequence") or ""),
    )


class CdpSession:
    """Persistent websocket to ONE pinned Chrome tab, serviced by a dedicated
    worker thread that owns an asyncio loop."""

    def __init__(self, http_url: str = "http://127.0.0.1:9222") -> None:
        self.http_url = http_url.rstrip("/")
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()
        self._state_lock = threading.Lock()
        self._ws: Any = None
        self._pump_task: Optional[asyncio.Task] = None
        self._pending: Dict[int, asyncio.Future] = {}
        self._msg_id = 0
        self._target_id: Optional[str] = None
        self._main_frame_id: Optional[str] = None
        self._context_id: Optional[int] = None
        self._context_unique_id: Optional[str] = None
        self._ui_context_id: Optional[int] = None
        self._ui_context_unique_id: Optional[str] = None
        self._route_id = 0
        self._contexts: Dict[int, str] = {}
        self._ready = False
        self.tab: Optional[Dict[str, Any]] = None
        self.session_event: Optional[Dict[str, Any]] = None
        self._intent_handler: Optional[Callable[[Dict[str, Any], Callable[[Dict[str, Any]], None]], None]] = None
        self._handler_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="hermes-gaze-intent"
        )
        self._closed = False
        # Pushed after every (re)injection so the overlay survives navigations/reloads
        # with the latest config; the nonce keeps in-page scripts from forging intents.
        self.overlay_config: Dict[str, Any] = {}
        self.intent_nonce: str = ""

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()
            self._loop = None

    def _ensure_thread(self) -> None:
        with self._state_lock:
            if self._closed:
                if self._thread is not None and self._thread.is_alive():
                    raise RuntimeError("CdpSession is closing")
                # Reopen after close(): the shared session outlives plugin unload/reload
                # cycles, so the transport must be restartable rather than one-shot.
                self._closed = False
                self._handler_pool = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="hermes-gaze-intent"
                )
            if self._thread is None or not self._thread.is_alive():
                self._loop_ready.clear()
                self._thread = threading.Thread(target=self._thread_main, name="hermes-gaze-cdp", daemon=True)
                self._thread.start()
        if not self._loop_ready.wait(timeout=5.0):
            raise RuntimeError("CDP worker thread failed to start")

    def _submit(self, coro: Any, timeout: float) -> Any:
        try:
            self._ensure_thread()
            loop = self._loop
            if loop is None or not loop.is_running():
                raise ConnectionError("CDP worker loop is not running")
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            coro.close()
            raise
        try:
            return fut.result(timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise TimeoutError(f"CDP call timed out after {timeout:.1f}s") from None

    def connect(self) -> bool:
        """Attach the assigned tab and initialize its isolated overlay."""
        try:
            return self._ready if self._ws is not None else bool(self._submit(self._connect_async(), timeout=20.0))
        except Exception as exc:
            logger.debug("CDP connect failed: %s", exc)
            return False

    def eval_js(self, expression: str, timeout: float = 6.0) -> Any:
        """Evaluate JS in the pinned tab; returns ``Runtime.evaluate`` ``result.value``.
        Thread-safe. Raises on timeout or page exception; one reconnect attempt on ws failure."""
        return self._submit(self._eval_with_reconnect(expression, timeout), timeout + 15.0)

    def eval_js_once(self, expression: str, timeout: float = 6.0, *,
                     context_id: Optional[str] = None) -> Any:
        """Evaluate a mutation in one document; never reconnect/replay."""
        return self._submit(self._eval_coro(expression, timeout, context_id=context_id), timeout + 1.0)

    def set_intent_handler(self, fn: Callable[[Dict[str, Any], Callable[[Dict[str, Any]], None]], None]) -> None:
        """Register fn(intent, reply) invoked on the intent pool for each binding call."""
        self._intent_handler = fn

    @property
    def is_connected(self) -> bool:
        """True only when a websocket is already live — never attempts a connection."""
        return self._ws is not None and self._ready

    def push_overlay_config(self) -> None:
        """Push stored overlay config + intent nonce into the live overlay (post-inject)."""
        self._submit(self._push_overlay_config(), timeout=8.0)

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            loop, thread = self._loop, self._thread
        if loop is not None and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._drop_ws(), loop).result(timeout=3.0)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        self._handler_pool.shutdown(wait=False)
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    # -- connection machinery (all coroutines run on the worker loop) --


    async def _connect_async(self) -> bool:
        try:
            import websockets
        except ImportError:
            logger.warning("websockets package is not installed; CDP transport unavailable")
            return False
        await self._drop_ws()
        tab = self.tab
        if tab is None:
            return False
        self._target_id = str(tab.get("id") or "") or None
        # 32 MiB > the service's max transcribe payload (~16.9M base64 chars + envelope)
        self._ws = await websockets.connect(str(tab["webSocketDebuggerUrl"]), max_size=32 * 1024 * 1024)
        self._pump_task = asyncio.ensure_future(self._pump(self._ws))
        try:
            for method, params in (
                ("Runtime.enable", {}),
                ("Page.enable", {}),
                ("Runtime.addBinding", {"name": _INTENT_BINDING, "executionContextName": _WORLD}),
            ):
                await self._send_cmd(method, params, timeout=5.0)
            src = _overlay_source()
            if src:
                await self._send_cmd("Page.addScriptToEvaluateOnNewDocument",
                                     {"source": src, "worldName": _WORLD}, timeout=5.0)
            if not await self._on_new_context(force=True):
                raise ConnectionError("Isolated Chrome overlay did not initialize")
        except Exception:
            await self._drop_ws()
            raise
        return True

    async def _push_overlay_config(self) -> None:
        # IIFE is mandatory: top-level const/let in Runtime.evaluate persists in the
        # page's global lexical scope and would collide on the next push/re-inject.
        expr = (
            "(() => { const api = window.__HERMES_GAZE_OVERLAY__; if (api) {"
            f"api.Configure({json.dumps(self.overlay_config)});"
            f"api.setIntentNonce({json.dumps(self.intent_nonce)});"
            "} return true; })()"
        )
        await self._eval_coro(expr, timeout=5.0)
        if (self.session_event is not None and
                self.session_event.get("browser_document") == self._context_unique_id):
            await self._display_event(self.session_event)

    async def _display_event(self, event: dict) -> None:
        await self._eval_coro(
            "if(document.visibilityState === 'visible' && document.hasFocus()) "
            "window.__HERMES_GAZE_OVERLAY__?.onSessionEvent(" + json.dumps(event) + ");true", timeout=5.)

    async def _init_ui(self) -> None:
        remote = await self._send_cmd("Runtime.evaluate", {
            "expression": "window.__HERMES_GAZE_OVERLAY__.uiFrame",
            "uniqueContextId": self._context_unique_id}, timeout=5.)
        object_id = remote["result"]["objectId"]
        try:
            node = await self._send_cmd("DOM.describeNode", {"objectId": object_id}, timeout=5.)
        finally:
            await self._send_cmd("Runtime.releaseObject", {"objectId": object_id}, timeout=5.)
        world = await self._send_cmd("Page.createIsolatedWorld", {
            "frameId": node["node"]["frameId"], "worldName": _WORLD}, timeout=5.)
        self._ui_context_id = world["executionContextId"]
        self._ui_context_unique_id = self._contexts[self._ui_context_id]
        await self._eval_coro(Path(__file__).with_name("panel.js").read_text(),
                              timeout=5., context_id=self._ui_context_unique_id)
        snapshot = await self._eval_coro("window.__HERMES_GAZE_OVERLAY__.takeUiSnapshot()", timeout=5.)
        await self._render_ui(snapshot)

    async def _render_ui(self, message: dict) -> None:
        if self._ui_context_unique_id:
            await self._eval_coro("window.__HERMES_GAZE_PANEL__?.render(" + json.dumps(message) + ")",
                                  timeout=5., context_id=self._ui_context_unique_id)

    async def _ui_message(self, payload: Any, *, from_ui: bool) -> None:
        try:
            message = json.loads(payload)
            if not isinstance(message, dict):
                return
            if not from_ui and message.get("type") == "_ui_render":
                await self._render_ui(message)
            elif from_ui and message.get("type") == "_ui_size":
                height = max(1, min(2000, int(message["height"])))
                await self._eval_coro(
                    f"window.__HERMES_GAZE_OVERLAY__.uiFrame.style.height='{height}px';true", timeout=5.)
            elif from_ui and message.get("type") == "_ui_event":
                await self._eval_coro("window.__HERMES_GAZE_OVERLAY__.onUiEvent("
                                      + json.dumps(message) + ");true", timeout=5.)
        except Exception:
            logger.debug("Private UI unavailable", exc_info=True)
    async def _drop_ws(self) -> None:
        self._ready = False
        self._context_id = None
        self._context_unique_id = None
        self._ui_context_id = None
        self._ui_context_unique_id = None
        self._contexts.clear()
        self._fail_pending(ConnectionError("CDP connection reset"))
        task, self._pump_task = self._pump_task, None
        if task is not None:
            task.cancel()
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    def _fail_pending(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    # -- message pump + events --

    async def _pump(self, ws: Any) -> None:
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if "id" in msg:
                    fut = self._pending.get(msg["id"])
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                else:
                    self._handle_event(str(msg.get("method") or ""), msg.get("params") or {})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("CDP pump ended: %s", exc)
        finally:
            if self._ws is ws:
                self._ws = None
                self._fail_pending(ConnectionError("CDP websocket closed"))

    def _handle_event(self, method: str, params: Dict[str, Any]) -> None:
        if method == "Runtime.bindingCalled" and params.get("name") == _INTENT_BINDING:
            context = params.get("executionContextId")
            if context == self._ui_context_id:
                asyncio.ensure_future(self._ui_message(params.get("payload"), from_ui=True))
            elif context == self._context_id:
                payload = params.get("payload")
                try:
                    internal = json.loads(payload).get("type") == "_ui_render"
                except (TypeError, ValueError, AttributeError):
                    return
                if internal:
                    asyncio.ensure_future(self._ui_message(payload, from_ui=False))
                else:
                    self._dispatch_intent(payload)
        elif method == "Runtime.executionContextCreated":
            context = params.get("context") or {}
            if context.get("name") == _WORLD and context.get("uniqueId"):
                self._contexts[context["id"]] = context["uniqueId"]
        elif method == "Runtime.executionContextsCleared":
            self._context_id = None
            self._context_unique_id = None
            self._contexts.clear()
            self._ui_context_id = None
            self._ui_context_unique_id = None
        elif method == "Page.loadEventFired" or (
                method == "Page.frameNavigated" and params.get("type") == "BackForwardCacheRestore"):
            asyncio.ensure_future(self._on_new_context())
        elif method == "Page.navigatedWithinDocument":
            if params.get("frameId") == self._main_frame_id:
                self._route_id += 1
                asyncio.ensure_future(self._eval_coro(
                    "window.__HERMES_GAZE_OVERLAY__?.revokeActionAuthority();true", timeout=5.))

    async def _on_new_context(self, force: bool = False) -> bool:
        """Re-register the intent binding + re-inject the overlay in a new main-frame context."""
        if self._ws is None:
            return False
        try:
            tree = await self._send_cmd("Page.getFrameTree", {}, timeout=5.0)
            frame_id = tree["frameTree"]["frame"]["id"]
            self._main_frame_id = frame_id
            world = await self._send_cmd("Page.createIsolatedWorld",
                                         {"frameId": frame_id, "worldName": _WORLD}, timeout=5.0)
            self._context_id = world["executionContextId"]
            self._context_unique_id = self._contexts.get(self._context_id)
            src = _overlay_source()
            if src and (force or not await self._eval_coro("!!window.__HERMES_GAZE_OVERLAY__", timeout=5.0)):
                await self._eval_coro(_guarded_inject(src), timeout=8.0)
            await self._init_ui()
            await self._push_overlay_config()
            self._ready = True
            return True
        except Exception as exc:
            logger.debug("context re-arm failed: %s", exc)
            return False

    def _dispatch_intent(self, payload: Any) -> None:
        handler = self._intent_handler
        if handler is None:
            return
        try:
            intent = json.loads(payload)
        except (TypeError, ValueError):
            logger.debug("intent payload is not JSON: %r", str(payload)[:200])
            return
        if not isinstance(intent, dict):
            return
        context_id = self._context_unique_id
        intent["_browser_document"] = context_id
        intent["_browser_route"] = self._route_id

        def reply(reply_payload: Dict[str, Any]) -> None:
            if self._closed:
                return
            msg = dict(reply_payload or {})
            for key in ("id", "type", "resolution_id"):
                if intent.get(key) is not None:
                    msg.setdefault(key, intent[key])
            try:
                self._submit(self._eval_coro(
                    "window.__HERMES_GAZE_OVERLAY__?.onIntentResult(" + json.dumps(msg) + ");true",
                    timeout=5.0, context_id=context_id), timeout=6.0)
            except Exception as exc:
                logger.debug("onIntentResult reply failed: %s", exc)

        def run() -> None:
            try:
                handler(intent, reply)
            except Exception as exc:
                logger.warning("intent handler raised: %s", exc)
                reply({"ok": False, "error": str(exc)})

        self._handler_pool.submit(run)

    # -- request/response --

    async def _send_cmd(self, method: str, params: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        if self._ws is None:
            raise ConnectionError("CDP websocket is not connected")
        self._msg_id += 1
        req_id = self._msg_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            await self._ws.send(json.dumps({"id": req_id, "method": method, "params": params or {}}))
            msg = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(req_id, None)
        if "error" in msg:
            err = msg["error"]
            raise RuntimeError(f"CDP {method} failed: {err.get('code')} {err.get('message')}")
        return msg.get("result") or {}

    async def _eval_coro(self, expression: str, timeout: float, context_id: Optional[str] = None) -> Any:
        context_id = context_id or self._context_unique_id
        if context_id is None:
            raise ConnectionError("Chrome document is navigating")
        result = await self._send_cmd(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True,
             "uniqueContextId": context_id},
            timeout=timeout,
        )
        exc = result.get("exceptionDetails")
        if exc:
            detail = (exc.get("exception") or {}).get("description") or exc.get("text") or "unknown JS exception"
            raise RuntimeError(f"JS exception in eval_js: {detail}")
        return (result.get("result") or {}).get("value")

    async def _eval_with_reconnect(self, expression: str, timeout: float) -> Any:
        import websockets

        last_exc: Optional[Exception] = None
        for _attempt in range(2):
            try:
                if self._ws is None and not await self._connect_async():
                    raise ConnectionError(f"No debuggable Chrome page found at {self.http_url}")
                return await self._eval_coro(expression, timeout)
            except TimeoutError:
                raise
            except (OSError, EOFError, ConnectionError, websockets.exceptions.ConnectionClosed) as exc:
                last_exc = exc
                await self._drop_ws()
        raise last_exc if last_exc is not None else ConnectionError("CDP eval_js failed")


class GazeSession:
    """Machine-scoped shared state: buffer + tracker + recalibrator + last
    resolution + the CdpSession. Deliberately process-global — Chrome :9222 and
    the camera are OS resources shared across Hermes profiles."""

    def __init__(self, cdp_http_url: str = "http://127.0.0.1:9222") -> None:
        from .companion import Companion
        from ..microphone import Microphone

        self._cdp = Companion(http_url=cdp_http_url)
        self.microphone = Microphone()
        self._lock = threading.RLock()
        self.ring_buffer = FixationRingBuffer(window_seconds=10.0)
        self._resolution_target: Optional[str] = None
        self._resolution_document: Optional[str] = None
        self.tracker = SimulatedPointerTracker(ring_buffer=self.ring_buffer, mode="hover", sigma_px=120.0)
        self.recalibrator = OnlineRecalibrator()
        self.last_candidates: List[CandidateElement] = []
        self.last_resolution: Optional[ResolutionResult] = None
        self.last_hover_snapshot: dict[str, Any] | None = None
        self.resolution_id = 0
        self.actions = SnapshotActions(self)
        self.scope_selection: Dict[str, str] = {}
        self.last_candidate_wire: List[Dict[str, Any]] = []
        self.last_resolution_input: Dict[str, Any] = {}
        self.scope_page_url: Optional[str] = None
        self._dwell_ms, self._wiggle_trigger, self._hotkey = 450, True, "AltRight"
        self._candidate_radius_px = 380.0
        self._ingested_keys: set = set()
        # Intents must carry this nonce; pushed into the overlay via setIntentNonce so a
        # hostile in-page script cannot forge resolves/transcribes/explains on the binding.
        self._intent_nonce = secrets.token_hex(8)
        self._cdp.intent_nonce = self._intent_nonce
        self._sync_overlay_config()

    @property
    def cdp(self) -> Any:
        return self._cdp

    @property
    def cdp_http_url(self) -> str:
        return self._cdp.http_url

    @cdp_http_url.setter
    def cdp_http_url(self, value: str) -> None:
        self._cdp.http_url = value.rstrip("/")

    def is_chrome_reachable(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.cdp_http_url}/json/version", timeout=1.2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ensure_connected(self) -> bool:
        return self.is_chrome_reachable() and self._cdp.connect()

    def eval_js(self, expression: str, timeout: float = 6.0) -> Any:
        return self._cdp.eval_js(expression, timeout=timeout)

    def eval_js_once(self, expression: str, timeout: float = 6.0) -> Any:
        snapshot = self.last_hover_snapshot or {}
        return self._cdp.eval_js_once(expression, timeout=timeout, target=snapshot.get("browser_target"),
                                      document=snapshot.get("browser_document"))

    def display_session_event(self, event: dict[str, Any]) -> None:
        self._cdp.display(event)

    def ensure_overlay(self) -> bool:
        """Attach supported pages without requiring a foreground page."""
        return self.ensure_connected()

    def overlay_is_live(self) -> bool:
        """Read-only probe: True only if the overlay api already answers in the pinned tab.
        Never connects or injects — used to gate hooks so they don't hijack pages[0]."""
        if not self._cdp.is_connected:
            return False
        try:
            return bool(self.eval_js("!!window.__HERMES_GAZE_OVERLAY__", timeout=2.0))
        except Exception:
            return False

    def _sync_overlay_config(self) -> None:
        self._cdp.overlay_config = {
            "mode": self.tracker.mode, "sigmaPx": self.tracker.sigma_px,
            "dwellMs": self._dwell_ms, "wiggleTrigger": self._wiggle_trigger,
            "hotkey": self._hotkey, "candidateRadiusPx": self._candidate_radius_px,
        }

    def configure(self, mode: Optional[str] = None, sigma_px: Optional[float] = None,
                  dwell_ms: Optional[int] = None, wiggle_trigger: Optional[bool] = None,
                  hotkey: Optional[str] = None, candidate_radius_px: Optional[float] = None) -> bool:
        """Store overlay config (None keeps stored). Pushes to the overlay ONLY when a
        websocket is already live — never connects or injects, so callers inside plugin
        registration cannot block on CDP I/O. Stored opts are pushed post-inject anyway."""
        with self._lock:
            if mode is not None:
                self.tracker.mode = str(mode)
            if sigma_px is not None:
                self.tracker.sigma_px = float(sigma_px)
            if dwell_ms is not None:
                self._dwell_ms = int(dwell_ms)
            if wiggle_trigger is not None:
                self._wiggle_trigger = bool(wiggle_trigger)
            if hotkey is not None:
                self._hotkey = str(hotkey)
            if candidate_radius_px is not None:
                self._candidate_radius_px = float(candidate_radius_px)
            self._sync_overlay_config()
        if not self._cdp.is_connected:
            return False
        try:
            self._cdp.push_overlay_config()
            return True
        except Exception as exc:
            logger.debug("overlay Configure failed: %s", exc)
            return False

    def inject_overlay(self, mode: Optional[str] = None, sigma_px: Optional[float] = None) -> bool:
        """Thin back-compat wrapper: configure() with stored defaults."""
        return self.configure(mode=mode, sigma_px=sigma_px)

    def ingest(self, samples: Any) -> None:
        """One funnel for ALL fixation sources: dicts -> FixationSample, subtract the
        recalibrator bias offset, dedupe on a (t_end, x_doc, y_doc) watermark set."""
        if not samples:
            return
        with self._lock:
            bias_x, bias_y = self.recalibrator.offset
            if len(self._ingested_keys) > 400:  # prune watermark with the buffer window
                cutoff = time.time() - self.ring_buffer.window_seconds
                self._ingested_keys = {k for k in self._ingested_keys if k[0] >= cutoff}
            for raw in samples:
                try:
                    s = raw if isinstance(raw, FixationSample) else _fixation_from_wire(raw, self.tracker.mode)
                except (TypeError, ValueError, AttributeError) as exc:
                    logger.debug("skipping malformed fixation %r: %s", raw, exc)
                    continue
                key = (round(s.t_end, 3), round(s.x_doc, 1), round(s.y_doc, 1))
                if key in self._ingested_keys:
                    continue
                self._ingested_keys.add(key)
                if bias_x or bias_y:
                    s = replace(s, x_doc=s.x_doc - bias_x, y_doc=s.y_doc - bias_y,
                                x_vp=s.x_vp - bias_x, y_vp=s.y_vp - bias_y)
                self.ring_buffer.add(s)

    def fetch_cursor_context(self) -> dict[str, Any]:
        """Capture actual DOM identities without invoking the simulated extractor."""
        if not self.is_chrome_reachable():
            return {}
        return self._cdp.capture()

    def store_hover_snapshot(self, payload: dict[str, Any]) -> int:
        with self.actions._lock:
            self.actions.invalidate()
            with self._lock:
                self.last_resolution = None
                self.last_candidates = []
                self.last_candidate_wire = []
                self.scope_selection.clear()
                self.resolution_id += 1
                rid = self.resolution_id
                try:
                    context = stamp_resolution(payload.get("context"), rid)
                except ValueError as exc:
                    context = ""
                    payload.update(ok=False, error=str(exc))
                payload.update(resolution_id=rid, epoch=rid, context=context, browser_active=False)
                snapshot = copy.deepcopy(payload)
                self.last_hover_snapshot = snapshot
            if snapshot.get("ok") is True and snapshot.get("snapshot_id"):
                result = self.actions._browser("activateSnapshot", snapshot["snapshot_id"], rid)
                with self._lock:
                    if self.last_hover_snapshot is snapshot and self.resolution_id == rid:
                        snapshot["browser_active"] = result.get("ok") is True
                        payload["browser_active"] = snapshot["browser_active"]
                        if not result.get("ok"):
                            snapshot["activation_error"] = result.get("error", "snapshot activation failed")
                            payload["activation_error"] = snapshot["activation_error"]
            return rid

    def clear_hover_snapshot(self) -> None:
        """Revoke action ownership when the connected Hermes session changes."""
        self.microphone.cancel()
        with self.actions._lock:
            self.actions.invalidate()
            with self._lock:
                self.last_hover_snapshot = None
                self.last_resolution = None
                self.resolution_id += 1

    def fetch_live_state_and_candidates(self, radius_px: float = 380.0) -> List[CandidateElement]:
        """Pull pointer + fixations + nearby candidates from the pinned tab in ONE eval.
        Returns [] honestly — never stale last_candidates — when Chrome or a real
        pointer position is unavailable."""
        if not self.is_chrome_reachable():
            with self._lock:
                self.last_candidates = []
            return []
        js = (
            "(() => { const api = window.__HERMES_GAZE_OVERLAY__; if (!api || !api.state) return null;"
            " const s = api.state; const locked = s.armed && s.lockedX !== null; return {"
            " page_url: location.href,"
            " pointer: { x_vp: locked ? s.lockedX : s.pointerX, y_vp: locked ? s.lockedY : s.pointerY, scroll_x: window.scrollX, scroll_y: window.scrollY },"
            " fixations: s.ringBuffer.slice(-25),"
            f" candidates: api.extractCandidatesNear(locked ? s.lockedX : s.pointerX, locked ? s.lockedY : s.pointerY, {float(radius_px)})"
            " }; })()"
        )
        data = self._cdp.capture(js)
        self.last_resolution_input = data
        self.ingest(data.get("fixations") or [])
        p = data.get("pointer") if isinstance(data.get("pointer"), dict) else {}
        if p.get("x_vp") is None or p.get("y_vp") is None:
            with self._lock:
                self.last_candidates = []
            return []
        if not self.ring_buffer.latest():
            self.tracker.record_point(
                float(p["x_vp"]), float(p["y_vp"]),
                scroll_x=float(p.get("scroll_x", 0.0)), scroll_y=float(p.get("scroll_y", 0.0)),
                bias_offset=self.recalibrator.offset)

        cands = [_candidate_from_wire(raw) for raw in data.get("candidates") or [] if isinstance(raw, dict)]
        with self._lock:
            self.last_candidates = cands
        return cands

    def new_resolution(self, res: ResolutionResult) -> int:
        """Store res as the active resolution and bump + return the epoch resolution_id."""
        target = self.last_resolution_input.get("browser_target")
        document = self.last_resolution_input.get("browser_document")
        with self.actions._lock:
            self.actions.invalidate()
            with self._lock:
                self.last_resolution = res
                self.last_hover_snapshot = None
                self._resolution_target = target
                self._resolution_document = document
                self._resolution_route = self.last_resolution_input.get("browser_route")
                self.resolution_id += 1
                return self.resolution_id

    def render_resolution_in_browser(self, resolution: Any, hud_html: Optional[str] = None) -> None:
        # new_resolution under the lock; browser I/O outside it so slow evals don't
        # serialize choose/ingest/intent dispatch behind a potentially slow tab.
        rid = self.new_resolution(resolution)
        if not self.is_chrome_reachable():
            return
        esc = html.escape
        if resolution.decision in ("open_semantic_lens", "confirm_destructive"):
            cards = [sc.to_dict() for sc in resolution.ranked[:4]]
            prompt = (
                "⚠️ High-Consequence Action — Confirm in Semantic Lens"
                if resolution.decision == "confirm_destructive"
                else f"🔍 Ambiguous Target — Select in Semantic Lens (Hover {self._dwell_ms}ms, Key 1-{len(cards)}, or Click)"
            )
            js = f"window.__HERMES_GAZE_OVERLAY__.renderSemanticLens({json.dumps(cards)}, {json.dumps(prompt)}, {rid}); true;"
        else:
            pins = [sc.to_dict() for sc in (resolution.multi_referents or resolution.ranked[:1])]
            if pins:
                top_pin = pins[0]
                role_label = esc(str(top_pin.get("role") or top_pin.get("tag") or "Element")).capitalize()
                conf_pct = int(top_pin.get("probability", 1.0) * 100)
                msg = hud_html or (
                    f"<div style='font-size:13.5px;'><strong style='color:#38bdf8;'>🔍 Inspecting: {esc(str(top_pin.get('label', '')))}</strong> <span style='color:#94a3b8;font-size:11.5px;'>({role_label})</span></div>"
                    f"<div style='margin-top:5px;color:#f8fafc;font-size:12.5px;line-height:1.45;'>{esc(str(top_pin.get('consequence_preview') or top_pin.get('summary', '')))}</div>"
                    f"<div style='margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.08);display:flex;gap:12px;font-size:11px;color:#64748b;font-family:ui-monospace,monospace;'>"
                    f"<span>Target: {esc(str(top_pin.get('selector', '')))}</span><span>Confidence: {conf_pct}%</span>"
                    f"</div>"
                )
            else:
                msg = hud_html or "No matching target."
            if resolution.intent_class == "read_only":
                # The overlay emits an `explain` intent for read_only + pin_immediate and
                # writes the reply into this element inside the pin HUD; data-rid ties the
                # reply to THIS resolution epoch.
                msg += (
                    f'<div id="gaze-explanation-text" data-rid="{rid}" style="margin-top:6px;color:#cbd5e1;font-size:12px;line-height:1.4;">'
                    "⏳ Asking Hermes...</div>"
                )
            js = f"window.__HERMES_GAZE_OVERLAY__.renderPins({json.dumps(pins)}, {json.dumps(msg)}); true;"
        try:
            self._cdp.eval_js_once(f"(() => {{{js}}})()", target=self._resolution_target,
                                   document=self._resolution_document, route=self._resolution_route)
        except Exception as exc:
            logger.debug("render_resolution_in_browser eval failed: %s", exc)

    def choose(self, resolution_id: Optional[int] = None, candidate_index: int = 1,
               modality: str = "semantic_lens", execute: bool = True) -> Dict[str, Any]:
        """Validate the epoch + index, recalibrate from the latest fixation, click, and re-pin."""
        with self._lock:
            res = self.last_resolution
            if res is None or not res.ranked:
                return {"ok": False, "error": "No active resolution to choose from. Call gaze_resolve first."}
            if resolution_id is None:
                return {"ok": False, "error": "resolution_id is required"}
            if int(resolution_id) != self.resolution_id:
                return {"ok": False, "error": "stale resolution"}
            idx = int(candidate_index) - 1
            if idx < 0 or idx >= len(res.ranked):
                return {"ok": False, "error": f"candidate_index {candidate_index} out of range (1..{len(res.ranked)})."}
            chosen = res.ranked[idx]
            latest_fix = self.ring_buffer.latest()
            if latest_fix is not None:
                true_x, true_y = chosen.candidate.center_doc
                self.recalibrator.update(
                    est_x=latest_fix.x_doc, est_y=latest_fix.y_doc, true_x=true_x, true_y=true_y,
                    sigma=latest_fix.sigma_x, weight=0.25,
                )
        if self.is_chrome_reachable():
            esc = html.escape
            role_disp = esc(chosen.candidate.role).capitalize()
            msg = (
                f"<div style='font-size:13.5px;'><strong style='color:#34d399;'>✓ Selected: {esc(chosen.candidate.label)}</strong> <span style='color:#94a3b8;font-size:11.5px;'>({role_disp} via {esc(str(modality))})</span></div>"
                f"<div style='margin-top:5px;color:#cbd5e1;font-size:12px;line-height:1.4;'>{esc(str(chosen.consequence_preview))}</div>"
                f"<div style='margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.08);font-size:11px;color:#64748b;font-family:monospace;'>Target: {esc(chosen.candidate.selector)}</div>"
            )
            click_stmt = (
                f"const el = document.querySelector({json.dumps(chosen.candidate.selector)}); if (el && el.click) el.click();"
                if execute else "")
            try:
                self._cdp.eval_js_once(
                    f"(() => {{window.__HERMES_GAZE_OVERLAY__.renderPins({json.dumps([chosen.to_dict()])}, {json.dumps(msg)});"
                    f"{click_stmt} return true;}})()", target=self._resolution_target,
                    document=self._resolution_document, route=self._resolution_route)
            except Exception as exc:
                self.clear_hover_snapshot()
                return {"ok": False, "executed": None if execute else False,
                        "outcome": "unknown" if execute else "failed",
                        "error": f"browser choose failed; do not retry automatically: {exc}"}
        with self._lock:
            self.last_resolution = None  # consume — a second choose must not re-click stale state
        return {
            "ok": True,
            "selected_index": idx + 1,
            "selected": chosen.to_dict(),
            "executed": execute,
            "recalibrator_bias_offset": list(self.recalibrator.offset),
        }


    def close(self) -> None:
        self.microphone.cancel()
        self.actions.invalidate()
        self._cdp.close()


@lazy_singleton
def get_shared_session() -> GazeSession:
    return GazeSession()


def launch_chrome_with_cdp(url: str, port: int = 9222, profile_dir: Optional[Path] = None) -> subprocess.Popen:
    """Launch macOS/Linux Google Chrome with CDP and a dedicated profile, without media grants."""
    import sys
    try:
        from plugins.plugin_storage import plugin_data_dir
    except ImportError:
        def plugin_data_dir(name: str) -> Path:
            return Path.home() / ".cache" / name
    from ..server import get_shared_server

    # Ensure background demo session server is active
    server = get_shared_server()
    server.start()

    # Use HTTP server origin if url is file URI or default
    target_url = url
    if not url or url.startswith("file://"):
        target_url = f"http://{server.host}:{server.port}/"

    prof = profile_dir or (plugin_data_dir("hermes-gaze") / "chrome-profile")
    prof.mkdir(parents=True, exist_ok=True)
    mac_app = Path("/Applications/Google Chrome.app")
    chrome_args = [
        f"--remote-debugging-port={port}",
        f"--user-data-dir={prof}",
        "--no-first-run",
        "--no-default-browser-check",
        target_url,
    ]
    if sys.platform == "darwin" and mac_app.exists():
        cmd = ["/usr/bin/open", "-na", str(mac_app), "--args", *chrome_args]
    else:
        mac_chrome = mac_app / "Contents" / "MacOS" / "Google Chrome"
        exe = str(mac_chrome) if mac_chrome.is_file() else "google-chrome"
        cmd = [exe, *chrome_args]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
