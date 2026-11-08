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
from collections import deque
from ..resolver.cursor_context import stamp_resolution
from ..release_timing import TIMINGS

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
_PANEL_SOURCES = ("markdown.js", "panel.js")
_UI_FRAMES = ("card", "pill")
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



class CdpSession:
    """Persistent websocket to ONE pinned Chrome tab, serviced by a dedicated
    worker thread that owns an asyncio loop."""

    def __init__(self, http_url: str = "http://127.0.0.1:9333") -> None:
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
        self._main_frame_loading = False
        self._context_id: Optional[int] = None
        self._context_unique_id: Optional[str] = None
        self._ui_context_id: Optional[int] = None
        self._ui_context_unique_id: Optional[str] = None
        self._ui_frames: Dict[str, Tuple[int, str]] = {}
        self._level_busy = False
        self._arm_lock: Optional[asyncio.Lock] = None
        self._route_id = 0
        self._contexts: Dict[int, str] = {}
        self._ready = False
        self.tab: Optional[Dict[str, Any]] = None
        self._reply_queue = deque()
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
                asyncio.run_coroutine_threadsafe(self._shutdown_overlay(), loop).result(timeout=7.0)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        self._handler_pool.shutdown(wait=False)
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    async def _shutdown_overlay(self) -> None:
        try:
            if self._ws is not None and self._context_unique_id:
                await self._eval_coro("window.__HERMES_GAZE_OVERLAY__?.destroy();true", timeout=2.)
        finally:
            await self._drop_ws()

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

    async def _init_ui(self) -> None:
        frames: Dict[str, Tuple[int, str]] = {}
        panel = "\n".join(Path(__file__).with_name(name).read_text() for name in _PANEL_SOURCES)
        for name in _UI_FRAMES:
            remote = await self._send_cmd("Runtime.evaluate", {
                "expression": f"window.__HERMES_GAZE_OVERLAY__.uiFrames.{name}",
                "uniqueContextId": self._context_unique_id}, timeout=5.)
            object_id = remote["result"]["objectId"]
            try:
                node = await self._send_cmd("DOM.describeNode", {"objectId": object_id}, timeout=5.)
            finally:
                await self._send_cmd("Runtime.releaseObject", {"objectId": object_id}, timeout=5.)
            world = await self._send_cmd("Page.createIsolatedWorld", {
                "frameId": node["node"]["frameId"], "worldName": _WORLD}, timeout=5.)
            frames[name] = (world["executionContextId"], await self._context_key(world["executionContextId"]))
            await self._eval_coro(panel, timeout=5., context_id=frames[name][1])
        self._ui_frames = frames
        self._ui_context_id, self._ui_context_unique_id = frames["card"]
        self._displayed_event = None  # Everything is new to this renderer, including recall.
        await self._eval_coro("window.__HERMES_GAZE_OVERLAY__.uiReady();true", timeout=5.)

    async def _render_ui(self, message: dict) -> None:
        frame = self._ui_frames.get(str(message.get("frame") or "card"))
        trace = getattr(self, "_release_trace", None)
        release = getattr(self, "_release_ui", None)
        matches_release = (release is not None and message.get("release_id") == release[0]
                           and self._context_unique_id == release[1])
        if frame:
            if trace is not None and matches_release:
                trace.mark("release_ui_render_start")
            rendered = await self._eval_coro(
                "(() => {const panel = window.__HERMES_GAZE_PANEL__; if (!panel) return false;"
                "panel.render(" + json.dumps(message) + "); return true})()",
                timeout=5., context_id=frame[1])
            if rendered is not True:
                return
            if trace is not None and message.get("mode") != "wave":
                trace.mark("first_ui_push")
                if message.get("frame") == "pill" and message.get("mode") == "capsule":
                    trace.mark("processing_ui_push")
                if (matches_release and self._context_unique_id == release[1]
                        and frame == self._ui_frames.get("pill")):
                    trace.mark("release_ui_push")
                    release[2].set()

    def push_level(self, level: float) -> None:
        """Voice level to the protected capsule only. Drop frames rather than queue them."""
        loop, frame = self._loop, self._ui_frames.get("pill")
        if loop is None or frame is None or self._level_busy or not loop.is_running():
            return
        self._level_busy = True

        async def send() -> None:
            try:
                await self._eval_coro(f"window.__HERMES_GAZE_PANEL__?.level({float(level):.3f})",
                                      timeout=1., context_id=frame[1])
            except Exception:
                logger.debug("Waveform frame dropped", exc_info=True)
            finally:
                self._level_busy = False
        asyncio.run_coroutine_threadsafe(send(), loop)


    async def _deliver_reply(self, document: str, message: dict) -> None:
        if document != self._context_unique_id:
            return
        delivered = await self._eval_coro(
            "(() => {if(document.visibilityState !== 'visible' || !document.hasFocus()) return false;"
            "window.__HERMES_GAZE_OVERLAY__?.onIntentResult(" + json.dumps(message) + ");return true})()",
            timeout=5., context_id=document)
        if not delivered:
            self._reply_queue.append((document, message))

    def flush_replies(self) -> None:
        if self._reply_queue and self.is_connected:
            self._submit(self._flush_replies(), timeout=8.)

    async def _flush_replies(self) -> None:
        queued, self._reply_queue = self._reply_queue, deque()
        for document, message in queued:
            await self._deliver_reply(document, message)

    async def _ui_message(self, payload: Any, *, frame: str = "") -> None:
        try:
            message = json.loads(payload)
            if not isinstance(message, dict):
                return
            if frame:
                await self._eval_coro("window.__HERMES_GAZE_OVERLAY__.fromPanel(" + json.dumps(frame) + ","
                                      + json.dumps(message) + ");true", timeout=5.)
            elif message.get("type") == "_ui_render":
                await self._render_ui(message)
            elif message.get("type") == "_ui_ping":
                await self._eval_coro("window.__HERMES_GAZE_OVERLAY__?.transportAlive();true", timeout=2.)
        except Exception:
            logger.debug("Private UI unavailable", exc_info=True)

    async def _drop_ws(self) -> None:
        self._ready = False
        self._main_frame_loading = False
        self._context_id = None
        self._context_unique_id = None
        self._ui_context_id = None
        self._ui_context_unique_id = None
        self._ui_frames = {}
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
            frame = next((name for name, (uid, _) in self._ui_frames.items() if uid == context), "")
            if frame:
                asyncio.ensure_future(self._ui_message(params.get("payload"), frame=frame))
            elif context == self._context_id:
                payload = params.get("payload")
                try:
                    internal = json.loads(payload).get("type") in ("_ui_render", "_ui_ping")
                except (TypeError, ValueError, AttributeError):
                    return
                if internal:
                    asyncio.ensure_future(self._ui_message(payload))
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
            self._ui_frames = {}
        elif method in ("Page.frameStartedLoading", "Page.frameStoppedLoading"):
            if params.get("frameId") == self._main_frame_id:
                self._main_frame_loading = method == "Page.frameStartedLoading"
        elif method == "Page.loadEventFired" or (
                method == "Page.frameNavigated" and params.get("type") == "BackForwardCacheRestore"):
            asyncio.ensure_future(self._on_new_context())
        elif method == "Page.navigatedWithinDocument":
            if params.get("frameId") == self._main_frame_id:
                self._route_id += 1
                asyncio.ensure_future(self._revoke_route_actions())

    async def _revoke_route_actions(self) -> None:
        try:
            await self._eval_coro("window.__HERMES_GAZE_OVERLAY__?.revokeActionAuthority();true", timeout=5.)
        except Exception:
            logger.debug("Route revocation met a navigating document", exc_info=True)

    async def _on_new_context(self, force: bool = False) -> bool:
        """Re-register the intent binding + re-inject the overlay in a new main-frame context.

        Serialized, and retried: during a navigation a frame or context can be momentarily
        missing, and a half-armed page would swallow keys with nowhere to send them.
        """
        if self._ws is None:
            return False
        if self._arm_lock is None:
            self._arm_lock = asyncio.Lock()
        async with self._arm_lock:
            for attempt in range(5):
                if self._ws is None:
                    return False
                try:
                    tree = await self._send_cmd("Page.getFrameTree", {}, timeout=5.0)
                    frame_id = tree["frameTree"]["frame"]["id"]
                    self._main_frame_id = frame_id
                    world = await self._send_cmd("Page.createIsolatedWorld",
                                                 {"frameId": frame_id, "worldName": _WORLD}, timeout=5.0)
                    self._context_id = world["executionContextId"]
                    self._context_unique_id = await self._context_key(self._context_id)
                    src = _overlay_source()
                    if src and (force or not await self._eval_coro("!!window.__HERMES_GAZE_OVERLAY__", timeout=5.0)):
                        await self._eval_coro(src, timeout=8.0)
                    await self._init_ui()
                    await self._push_overlay_config()
                    self._ready = True
                    return True
                except Exception as exc:
                    logger.debug("context re-arm attempt %d failed: %r", attempt + 1, exc)
                    await asyncio.sleep(.1 * (attempt + 1))
            return False

    async def _context_key(self, context_id: int) -> str:
        # The creation event can still be on its way when the command's reply arrives.
        for _ in range(50):
            key = self._contexts.get(context_id)
            if key:
                return key
            await asyncio.sleep(.01)
        raise ConnectionError("Chrome did not announce the isolated context")

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
        if intent.get("type") == "record_stop" and intent.get("nonce") == self.intent_nonce:
            self._release_trace = TIMINGS.begin(intent.get("release_timing"))
            intent["_release_trace"] = self._release_trace.turn
            # Inbox publication acknowledges the overlay, not its private renderer.
            # Only this release's completed protected-frame render opens the gate.
            ready = threading.Event()
            self._release_ui = (intent.get("id"), context_id, ready)
            self._release_trace.ui_ready = ready

        def reply(reply_payload: Dict[str, Any]) -> None:
            if self._closed:
                return
            msg = dict(reply_payload or {})
            for key in ("id", "type", "resolution_id"):
                if intent.get(key) is not None:
                    msg.setdefault(key, intent[key])
            try:
                self._submit(self._deliver_reply(context_id, msg), timeout=6.)
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
            # A live socket with no document is normal navigation, not transport failure.
            # Reconnecting here races the load-event rearm and can strand its context.
            if self._ws is not None and self._context_unique_id is None:
                raise ConnectionError("Chrome document is navigating")
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
    resolution + the CdpSession. Deliberately process-global — owned Chrome and
    the camera are OS resources shared across Hermes profiles."""

    def __init__(self, cdp_http_url: str = "http://127.0.0.1:9333") -> None:
        from .companion import Companion
        from ..microphone import Microphone
        from ..browser_tasks import BrowserTasks

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
        self.tasks = BrowserTasks(self)
        self.scope_selection: Dict[str, str] = {}
        self.last_candidate_wire: List[Dict[str, Any]] = []
        self.last_resolution_input: Dict[str, Any] = {}
        self.scope_page_url: Optional[str] = None
        self._dwell_ms, self._wiggle_trigger, self._hotkey = 450, False, "AltRight"
        self._answer_turn_seconds = 12.0
        self._candidate_radius_px = 380.0
        self._ingested_keys: set = set()
        self.webcam = None  # Explicit user command only; registration never opens a camera.
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
                                      document=snapshot.get("browser_document"), route=snapshot.get("browser_route"))

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
            "answerTurnMs": round(self._answer_turn_seconds * 1000),
        }

    def configure(self, mode: Optional[str] = None, sigma_px: Optional[float] = None,
                  dwell_ms: Optional[int] = None, wiggle_trigger: Optional[bool] = None,
                  hotkey: Optional[str] = None, candidate_radius_px: Optional[float] = None,
                  answer_turn_seconds: Optional[float] = None) -> bool:
        """Store overlay config (None keeps stored). Pushes to the overlay ONLY when a
        websocket is already live — never connects or injects, so callers inside plugin
        registration cannot block on CDP I/O. Stored opts are pushed post-inject anyway."""
        if mode is not None and mode not in ("hover", "simulated", "webcam"):
            raise ValueError("Unsupported pointing mode")
        changed = mode is not None and mode != self.tracker.mode
        if changed:
            self.clear_hover_snapshot()
            if mode != "webcam":
                self.stop_webcam()
        with self._lock:
            if mode is not None:
                self.tracker.mode = str(mode)
                if changed:
                    self.ring_buffer.clear()
                    self._ingested_keys.clear()
                    self.scope_selection.clear()
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
            if answer_turn_seconds is not None:
                self._answer_turn_seconds = max(1., float(answer_turn_seconds))
            self._sync_overlay_config()
        if not self._cdp.is_connected:
            return False
        try:
            self._cdp.push_overlay_config()
            return True
        except Exception as exc:
            logger.debug("overlay Configure failed: %s", exc)
            return False

    def start_webcam(self) -> dict:
        from ..webcam import WebcamHost
        with self._lock:
            if self.webcam is None:
                self.webcam = WebcamHost(self._accept_webcam_point, on_use_cursor=lambda: self.configure(mode="hover"))
        return self.webcam.start()

    def stop_webcam(self) -> None:
        if self.webcam is not None:
            self.webcam.stop()

    def webcam_status(self) -> dict:
        return self.webcam.status() if self.webcam is not None else {"state": "stopped", "calibrated": False}

    def _accept_webcam_point(self, point, screen: dict) -> bool | str:
        from .companion import NoForegroundTab
        from ..tracker.webcam_gaze import screen_to_viewport
        if self.tracker.mode != "webcam":
            return "mode_changed"
        try:
            geometry = self._cdp.capture(
                f"window.__HERMES_GAZE_OVERLAY__?.webcamViewport({float(screen['dpr'])})")
        except NoForegroundTab:
            return "no_foreground_tab"
        sample = screen_to_viewport(point, geometry, screen, self.tracker.sigma_px)
        if isinstance(sample, str):
            return sample
        if self.tracker.mode != "webcam":
            return "mode_changed"
        delivered = self._cdp.eval_js_once(
            f"window.__HERMES_GAZE_OVERLAY__?.acceptWebcamSample({json.dumps(sample)})",
            target=geometry.get("browser_target"), document=geometry.get("browser_document"),
            route=geometry.get("browser_route"))
        if delivered is True:
            self.ingest([sample])
            return True
        return "rejected_by_page"

    def ingest(self, samples: Any) -> List[FixationSample]:
        """One funnel for ALL fixation sources: dicts -> FixationSample, subtract the
        recalibrator bias offset, dedupe on a (t_end, x_doc, y_doc) watermark set."""
        captured = []
        if not samples:
            return captured
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
                if bias_x or bias_y:
                    s = replace(s, x_doc=s.x_doc - bias_x, y_doc=s.y_doc - bias_y,
                                x_vp=s.x_vp - bias_x, y_vp=s.y_vp - bias_y)
                captured.append(s)
                if key not in self._ingested_keys:
                    self._ingested_keys.add(key)
                    self.ring_buffer.add(s)
        return captured

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

    def fetch_live_state_and_candidates(self, radius_px: float = 380.0) -> Tuple[List[CandidateElement], dict]:
        """Return candidates AND their collection-time evidence/owner in one read."""
        if not self.is_chrome_reachable():
            with self._lock:
                self.last_candidates = []
            return [], {}
        js = f"window.__HERMES_GAZE_OVERLAY__?.captureNoisyContext({float(radius_px)})"
        data = self._cdp.capture(js)
        cands = [CandidateElement.from_wire(raw) for raw in data.get("candidates") or [] if isinstance(raw, dict)]
        return cands, data

    def new_resolution(self, res: ResolutionResult, evidence: Optional[dict] = None) -> int:
        """Activate one locally frozen result, never reread another worker's input."""
        evidence = evidence or {}
        with self.actions._lock:
            self.actions.invalidate()
            with self._lock:
                self.last_resolution = res
                self.last_hover_snapshot = None
                self.last_resolution_input = evidence
                self.last_candidate_wire = list(evidence.get("candidates") or [])
                self._resolution_target = evidence.get("browser_target")
                self._resolution_document = evidence.get("browser_document")
                self._resolution_route = evidence.get("browser_route")
                self.resolution_id += 1
                return self.resolution_id

    def render_resolution_in_browser(self, resolution: Any, *, evidence: dict) -> int:
        rid = self.new_resolution(resolution, evidence)
        if not self.is_chrome_reachable():
            return rid
        if resolution.decision in ("open_semantic_lens", "confirm_destructive"):
            cards = [sc.to_dict() for sc in resolution.ranked[:4]]
            js = f"window.__HERMES_GAZE_OVERLAY__.renderSemanticLens({json.dumps(cards)}, null, {rid}); true;"
        else:
            pins = [sc.to_dict() for sc in (resolution.multi_referents or resolution.ranked[:1])]
            js = f"window.__HERMES_GAZE_OVERLAY__.renderPins({json.dumps(pins)}); true;"
        try:
            self._cdp.eval_js_once(f"(() => {{{js}}})()", target=evidence.get("browser_target"),
                                   document=evidence.get("browser_document"), route=evidence.get("browser_route"))
        except Exception as exc:
            logger.debug("render_resolution_in_browser eval failed: %s", exc)
        return rid

    def choose(self, resolution_id: Optional[int] = None, candidate_index: int = 1,
               modality: str = "semantic_lens") -> Dict[str, Any]:
        """Select a simulated candidate and recalibrate; browser input belongs to guarded tasks."""
        with self.actions._lock:
            with self._lock:
                if (self.tracker.mode != "simulated" or
                        self.last_resolution_input.get("mode", self.tracker.mode) != "simulated"):
                    return {"ok": False, "error": "Choose is simulated-only; webcam research is read-only"}
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
                try:
                    self._cdp.eval_js_once(
                        f"(() => {{window.__HERMES_GAZE_OVERLAY__.renderPins({json.dumps([chosen.to_dict()])});"
                        f"return true;}})()", target=self._resolution_target,
                        document=self._resolution_document, route=self._resolution_route)
                except Exception as exc:
                    self.clear_hover_snapshot()
                    return {"ok": False, "executed": False, "outcome": "failed",
                            "error": f"browser selection failed: {exc}"}
            with self._lock:
                self.last_resolution = None  # One selection per resolution.
            return {
                "ok": True,
                "selected_index": idx + 1,
                "selected": chosen.to_dict(),
                "executed": False,
                "message": "Selection only. Use fresh gaze_read and guarded action tools for browser input.",
                "recalibrator_bias_offset": list(self.recalibrator.offset),
            }


    def close(self) -> None:
        TIMINGS.stop()
        self.microphone.cancel()
        self.stop_webcam()
        self.tasks.stop()
        self._cdp.close()


@lazy_singleton
def get_shared_session() -> GazeSession:
    return GazeSession()


def launch_chrome_with_cdp(url: str, port: int = 9333, profile_dir: Optional[Path] = None) -> subprocess.Popen:
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
