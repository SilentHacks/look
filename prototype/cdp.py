"""Tiny stdlib-only Chrome DevTools Protocol client (flattened sessions over one socket).

The plugin itself uses `websockets`; this prototype must run with a bare python3.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import urllib.parse
import urllib.request
from concurrent.futures import Future
from typing import Any, Callable


class CDPError(RuntimeError):
    pass


class WebSocket:
    def __init__(self, url: str):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (f"?{u.query}" if u.query else "")
        self.sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head[:200].decode("latin1"))
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.sock.settimeout(None)
        self.lock = threading.Lock()

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self) -> str:
        message = b""
        while True:
            b0, b1 = self._read(2)
            opcode, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            if opcode == 8:
                raise ConnectionError("websocket closed by peer")
            if opcode == 9:
                self._send(10, payload)
                continue
            if opcode == 10:
                continue
            message += payload
            if b0 & 0x80:
                return message.decode("utf-8")

    def _send(self, opcode: int, data: bytes) -> None:
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        # XOR through big ints: answers are small, but screencast acks arrive constantly.
        masked = (int.from_bytes(data, "little") ^ int.from_bytes((mask * (n // 4 + 1))[:n], "little")).to_bytes(n, "little") if n else b""
        with self.lock:
            self.sock.sendall(head + mask + masked)

    def send(self, text: str) -> None:
        self._send(1, text.encode("utf-8"))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    """One socket to the browser endpoint; per-tab traffic carries a sessionId."""

    def __init__(self, port: int):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
            info = json.load(r)
        self.port = port
        self.version = info.get("Browser", "")
        self.ws = WebSocket(info["webSocketDebuggerUrl"])
        self.ids = 0
        self.pending: dict[int, Future] = {}
        self.handlers: list[Callable[[str, dict, str | None], None]] = []
        self.closed = threading.Event()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        try:
            while True:
                msg = json.loads(self.ws.recv())
                if "id" in msg:
                    fut = self.pending.pop(msg["id"], None)
                    if fut:
                        if "error" in msg:
                            fut.set_exception(CDPError(json.dumps(msg["error"])))
                        else:
                            fut.set_result(msg.get("result", {}))
                else:
                    for h in list(self.handlers):
                        try:
                            h(msg.get("method", ""), msg.get("params", {}), msg.get("sessionId"))
                        except Exception as exc:  # a prototype keeps running through a bad event
                            print("[event error]", exc, flush=True)
        except (ConnectionError, OSError):
            pass
        finally:
            self.closed.set()
            for fut in self.pending.values():
                fut.set_exception(ConnectionError("browser closed"))
            self.pending.clear()

    def send_async(self, method: str, params: dict | None = None, session: str | None = None) -> Future:
        self.ids += 1
        msg: dict[str, Any] = {"id": self.ids, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        fut: Future = Future()
        self.pending[self.ids] = fut
        self.ws.send(json.dumps(msg))
        return fut

    def send(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 15.0) -> dict:
        return self.send_async(method, params, session).result(timeout=timeout)

    def on(self, handler: Callable[[str, dict, str | None], None]) -> None:
        self.handlers.append(handler)
