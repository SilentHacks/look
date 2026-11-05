"""Built-in lightweight HTTP session server for hermes-gaze.

Serves the interactive demo page (benchmark_page.html) and a read-only
``/api/status`` endpoint on http://127.0.0.1:9111 for the Chrome HUD.
GET-only: no CORS headers, no OPTIONS handler, POST returns 404 — the
overlay <-> Python channel is the CDP Runtime.addBinding intent transport
(see browser/cdp_bridge.py), not HTTP.
"""

from __future__ import annotations

import functools
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional

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

from .browser.cdp_bridge import get_shared_session

logger = logging.getLogger(__name__)

_DEMO_HTML_PATH = Path(__file__).resolve().parent / "benchmark" / "benchmark_page.html"


class _SessionRequestHandler(BaseHTTPRequestHandler):
    """GET-only request handler: demo page + /api/status JSON."""

    def log_message(self, format: str, *args: Any) -> None:
        # Keep logs clean; only log errors. BaseHTTPRequestHandler calls this as
        # log_message(template, requestline, code, size) — the status code is args[1].
        if len(args) >= 2 and str(args[1]).startswith(("4", "5")):
            logger.warning("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            if _DEMO_HTML_PATH.is_file():
                content = _DEMO_HTML_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        if path == "/api/status":
            session = get_shared_session()
            status = {
                "ok": True,
                "chrome_connected": session.is_chrome_reachable(),
                "mode": session.tracker.mode,
                "sigma_px": session.tracker.sigma_px,
            }
            body = json.dumps(status).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        self.send_response(404)
        self.end_headers()


class SessionHttpServer:
    """Background HTTP server serving the Gaze demo page and session status."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9111) -> None:
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def is_reachable(self) -> bool:
        """Whether a live server already answers /api/status on host:port."""
        import urllib.request

        try:
            req = urllib.request.Request(f"http://{self.host}:{self.port}/api/status")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start(self) -> None:
        # Pre-check first: a Hermes plugin reload must not fight a live sibling server.
        if self._server is not None or self.is_reachable():
            return
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), _SessionRequestHandler)
        except OSError:
            self._server = ThreadingHTTPServer((self.host, 0), _SessionRequestHandler)
            self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("SessionHttpServer running on http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None


@lazy_singleton
def get_shared_server(host: str = "127.0.0.1", port: int = 9111) -> SessionHttpServer:
    """Singleton getter for the background session server."""
    return SessionHttpServer(host=host, port=port)
