"""Chrome DevTools Protocol (CDP) bridge for hermes-gaze.

Attaches to local Chrome running with ``--remote-debugging-port=9222``, injects ``overlay.js``
into the active page, queries DOM/Accessibility candidates, and renders pins & Semantic Lens cards.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from plugins.plugin_utils import lazy_singleton
except ImportError:
    def lazy_singleton(fn: Callable[..., Any]) -> Callable[..., Any]:
        _inst = None
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal _inst
            if _inst is None:
                _inst = fn(*args, **kwargs)
            return _inst
        return _wrapper

from ..resolver.bayesian_fusion import CandidateElement
from ..tracker.recalibrator import OnlineRecalibrator
from ..tracker.simulated_gaze import FixationRingBuffer, FixationSample, SimulatedPointerTracker

logger = logging.getLogger(__name__)

_OVERLAY_JS_PATH = Path(__file__).with_name("overlay.js")


class CDPBridge:
    """Lightweight CDP client shared across tools, hooks, and the gaze platform adapter."""

    def __init__(self, cdp_http_url: str = "http://127.0.0.1:9222") -> None:
        self.cdp_http_url = cdp_http_url.rstrip("/")
        self.ring_buffer = FixationRingBuffer(window_seconds=10.0)
        self.tracker = SimulatedPointerTracker(ring_buffer=self.ring_buffer, mode="hover", sigma_px=120.0)
        self.recalibrator = OnlineRecalibrator()
        self.last_candidates: List[CandidateElement] = []
        self.last_resolution: Optional[Any] = None
        self._msg_id = 0

    def is_chrome_reachable(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.cdp_http_url}/json/version", timeout=1.2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def get_active_page_ws_url(self) -> Optional[str]:
        try:
            with urllib.request.urlopen(f"{self.cdp_http_url}/json/list", timeout=1.5) as resp:
                tabs = json.loads(resp.read().decode("utf-8"))
            for tab in tabs:
                if tab.get("type") == "page" and not str(tab.get("url", "")).startswith("devtools://"):
                    if tab.get("webSocketDebuggerUrl"):
                        return str(tab["webSocketDebuggerUrl"])
        except Exception as exc:
            logger.debug("CDP get_active_page_ws_url failed: %s", exc)
        return None

    async def _eval_js_async(
        self,
        expression: str,
        inject_overlay: bool = True,
        force_reinject: bool = False,
    ) -> Any:
        import websockets

        ws_url = self.get_active_page_ws_url()
        if not ws_url:
            raise RuntimeError(f"No debuggable Chrome page found at {self.cdp_http_url}")

        async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
            if inject_overlay and _OVERLAY_JS_PATH.is_file():
                overlay_src = _OVERLAY_JS_PATH.read_text(encoding="utf-8")
                inj_expr = (
                    overlay_src
                    if force_reinject
                    else f"if (!window.__HERMES_GAZE_OVERLAY__) {{ {overlay_src} }}"
                )
                self._msg_id += 1
                await ws.send(
                    json.dumps(
                        {
                            "id": self._msg_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": inj_expr, "returnByValue": False},
                        }
                    )
                )
                await ws.recv()

            self._msg_id += 1
            req_id = self._msg_id
            await ws.send(
                json.dumps(
                    {
                        "id": req_id,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": expression,
                            "returnByValue": True,
                            "awaitPromise": True,
                        },
                    }
                )
            )
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == req_id:
                    result = (msg.get("result") or {}).get("result") or {}
                    return result.get("value")

    def eval_js(
        self,
        expression: str,
        inject_overlay: bool = True,
        force_reinject: bool = False,
    ) -> Any:
        """Synchronous wrapper around _eval_js_async."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    lambda: asyncio.run(self._eval_js_async(expression, inject_overlay, force_reinject))
                ).result(timeout=5.0)
        return asyncio.run(self._eval_js_async(expression, inject_overlay, force_reinject))

    def inject_overlay(self, mode: str = "hover", sigma_px: float = 120.0) -> bool:
        if not self.is_chrome_reachable():
            return False
        opts = json.dumps({"mode": mode, "sigmaPx": sigma_px})
        self.eval_js(
            f"window.__HERMES_GAZE_OVERLAY__.Configure({opts}); true;",
            inject_overlay=True,
            force_reinject=True,
        )
        return True

    def is_mic_capture_working(self) -> bool:
        """Check whether getUserMedia resolves quickly in the active Chrome tab (not blocked by macOS TCC)."""
        if not self.is_chrome_reachable():
            return False
        js = """
        Promise.race([
            navigator.mediaDevices.getUserMedia({ audio: true })
                .then(s => { s.getTracks().forEach(t => t.stop()); return true; })
                .catch(() => false),
            new Promise(r => setTimeout(() => r(false), 1200))
        ])
        """
        try:
            return bool(self.eval_js(js, inject_overlay=False))
        except Exception:
            return False

    def fetch_live_state_and_candidates(self, radius_px: float = 320.0) -> List[CandidateElement]:
        """Pull recent fixations and candidate elements near the pointer/gaze from Chrome."""
        if not self.is_chrome_reachable():
            return self.last_candidates

        js = f"""
        (() => {{
          const api = window.__HERMES_GAZE_OVERLAY__;
          const s = api.state;
          return {{
            pointer: {{ x_vp: s.pointerX, y_vp: s.pointerY, scroll_x: window.scrollX, scroll_y: window.scrollY }},
            fixations: s.ringBuffer.slice(-25),
            candidates: api.extractCandidatesNear(s.pointerX, s.pointerY, {float(radius_px)}),
          }};
        }})()
        """
        data = self.eval_js(js, inject_overlay=True) or {}
        for f in data.get("fixations") or []:
            self.ring_buffer.add(
                FixationSample(
                    x_doc=float(f.get("x_doc", 0.0)),
                    y_doc=float(f.get("y_doc", 0.0)),
                    x_vp=float(f.get("x_vp", 0.0)),
                    y_vp=float(f.get("y_vp", 0.0)),
                    t_start=float(f.get("t", 0.0)) - 0.12,
                    t_end=float(f.get("t", 0.0)),
                    duration_ms=120.0,
                    sigma_x=float(f.get("sigma", 24.0)),
                    sigma_y=float(f.get("sigma", 24.0)),
                )
            )
        if not self.ring_buffer.latest() and isinstance(data.get("pointer"), dict):
            p = data["pointer"]
            self.tracker.record_point(
                float(p.get("x_vp", 500.0)),
                float(p.get("y_vp", 300.0)),
                scroll_x=float(p.get("scroll_x", 0.0)),
                scroll_y=float(p.get("scroll_y", 0.0)),
            )

        cands: List[CandidateElement] = []
        for raw in data.get("candidates") or []:
            rvp = tuple(float(v) for v in (raw.get("rect_vp") or [0, 0, 40, 24]))
            rdoc = tuple(float(v) for v in (raw.get("rect_doc") or rvp))
            cands.append(
                CandidateElement(
                    id=str(raw.get("id") or "cand"),
                    tag=str(raw.get("tag") or "div"),
                    role=str(raw.get("role") or "button"),
                    label=str(raw.get("label") or ""),
                    selector=str(raw.get("selector") or ""),
                    rect_doc=rdoc,  # type: ignore[arg-type]
                    rect_vp=rvp,    # type: ignore[arg-type]
                    is_container=bool(raw.get("is_container", False)),
                    is_interactive=bool(raw.get("is_interactive", True)),
                    is_destructive=bool(raw.get("is_destructive", False)),
                    summary=str(raw.get("summary") or ""),
                    consequence=str(raw.get("consequence") or ""),
                )
            )
        self.last_candidates = cands
        return cands

    def render_resolution_in_browser(self, resolution: Any, hud_html: Optional[str] = None) -> None:
        self.last_resolution = resolution
        if not self.is_chrome_reachable():
            return
        if resolution.decision in ("open_semantic_lens", "confirm_destructive"):
            cards = [sc.to_dict() for sc in resolution.ranked[:4]]
            prompt = (
                "⚠️ High-Consequence Action — Confirm in Semantic Lens"
                if resolution.decision == "confirm_destructive"
                else "🔍 Ambiguous Target — Select in Semantic Lens (Hover 450ms, Key 1-4, or Click)"
            )
            js = f"window.__HERMES_GAZE_OVERLAY__.renderSemanticLens({json.dumps(cards)}, {json.dumps(prompt)}); true;"
            self.eval_js(js, inject_overlay=True)
        else:
            pins = [sc.to_dict() for sc in (resolution.multi_referents or resolution.ranked[:1])]
            if pins:
                top_pin = pins[0]
                role_label = str(top_pin.get("role") or top_pin.get("tag") or "Element").capitalize()
                conf_pct = int(top_pin.get("probability", 1.0) * 100)
                msg = hud_html or (
                    f"<div style='font-size:13.5px;'><strong style='color:#38bdf8;'>🔍 Inspecting: {top_pin.get('label', '')}</strong> <span style='color:#94a3b8;font-size:11.5px;'>({role_label})</span></div>"
                    f"<div style='margin-top:5px;color:#f8fafc;font-size:12.5px;line-height:1.45;'>{top_pin.get('consequence_preview') or top_pin.get('summary', '')}</div>"
                    f"<div style='margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.08);display:flex;gap:12px;font-size:11px;color:#64748b;font-family:ui-monospace,monospace;'>"
                    f"<span>Target: {top_pin.get('selector', '')}</span><span>Confidence: {conf_pct}%</span>"
                    f"</div>"
                )
            else:
                msg = hud_html or "No matching target."
            js = f"window.__HERMES_GAZE_OVERLAY__.renderPins({json.dumps(pins)}, {json.dumps(msg)}); true;"
            self.eval_js(js, inject_overlay=True)


@lazy_singleton
def get_shared_bridge() -> CDPBridge:
    return CDPBridge()


def launch_chrome_with_cdp(url: str, port: int = 9222, profile_dir: Optional[Path] = None) -> subprocess.Popen:
    """Launch macOS/Linux Google Chrome with --remote-debugging-port, media permissions, and dedicated profile."""
    import sys
    from plugins.plugin_storage import plugin_data_dir
    from ..tracker.voice_listener import get_shared_voice_server

    # Ensure background voice/demo server is active
    server = get_shared_voice_server()
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
        "--use-fake-ui-for-media-stream",  # auto-grant mic permission for Web Speech & Web Audio
        target_url,
    ]
    if sys.platform == "darwin" and mac_app.exists():
        # Launch via macOS LaunchServices (`open -na`) so `com.google.Chrome` is the
        # TCC Responsible Process with its own `com.apple.security.device.audio-input`
        # entitlement, rather than inheriting a parent IDE/CLI process without mic entitlement.
        cmd = ["/usr/bin/open", "-na", str(mac_app), "--args", *chrome_args]
    else:
        mac_chrome = mac_app / "Contents" / "MacOS" / "Google Chrome"
        exe = str(mac_chrome) if mac_chrome.is_file() else "google-chrome"
        cmd = [exe, *chrome_args]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
