"""Internal Look transport over one explicitly paired Chrome native-message port."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import socket
import struct
import threading
import time

from .consent import ConsentChrome, TargetChannel
from .extension_host import _replace, configuration, read_message, runtime_directory, send_message
from .ownership import OwnershipError, acquire_runtime_lease


class NativeSocket:
    def __init__(self, peer):
        self.peer = peer
        peer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack("ll", 3, 0))
        self.stream = peer.makefile("rwb", buffering=0)
        self.lock = threading.Lock()

    def send(self, raw):
        with self.lock:
            send_message(self.stream, json.loads(raw))

    def __iter__(self):
        while True:
            yield json.dumps(read_message(self.stream))

    def close(self):
        try:
            self.peer.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.peer.close()
        self.stream.close()


class ExtensionChrome(ConsentChrome):
    """Reuse terminal root/channel ownership, not native-consent discovery or Browser APIs."""
    source = "extension"
    def __init__(self, *, lease_dir=None, extension_id=None):
        super().__init__(lease_dir=lease_dir)
        self.extension_id = extension_id or configuration()["extension_id"]
        self._listener = None
        self._path = None
        self._capability = ""
        self._discovery = None
        self._expires = 0.

    def prepare(self, *, timeout=120):
        with self._lock:
            if self.state != "idle":
                raise OwnershipError("Stop Look before starting another extension connection")
            if not 0 < timeout <= 120:
                raise ValueError("Extension approval must expire within 120 seconds")
            self._lease = acquire_runtime_lease(self.lease_dir)
            listener = socket.socket(socket.AF_UNIX)
            try:
                directory = runtime_directory()
                self._path = directory / (secrets.token_hex(12) + ".sock")
                listener.bind(str(self._path))
                os.chmod(self._path, 0o600)
                listener.listen(4)
                listener.settimeout(.2)
                self._listener = listener
                self._capability = secrets.token_hex(32)
                self._expires = time.monotonic() + timeout
                self._discovery = directory / "pending.json"
                _replace(self._discovery, json.dumps(dict(request=self.generation,
                         capability=self._capability, socket=self._path.name, expires=self._expires)).encode(), 0o600)
                self.state = "waiting"
            except BaseException:
                listener.close()
                self.close()
                raise

    def start(self, *, timeout=120):
        try:
            while not self._stopped.is_set() and time.monotonic() < self._expires:
                try:
                    peer, _ = self._listener.accept()
                except socket.timeout:
                    continue
                peer.settimeout(min(2., max(.01, self._expires - time.monotonic())))
                ws = NativeSocket(peer)
                try:
                    request = read_message(ws.stream)
                    if (request.get("op") not in ("status", "pair") or request.get("extension_id") != self.extension_id
                            or request.get("request") != self.generation
                            or not hmac.compare_digest(str(request.get("capability", "")), self._capability)):
                        raise ValueError("Pairing refused")
                    with self._lock:
                        if self._stopped.is_set() or time.monotonic() >= self._expires:
                            raise ValueError("Pairing cancelled or expired")
                        if request["op"] == "status":
                            ws.send(json.dumps(dict(op="status", version=1, request=self.generation)))
                            ws.close()
                            continue
                        self._unpublish()  # Consume before acknowledging; never resumable.
                        self._listener.close()
                        self._listener = None
                        self._path.unlink(missing_ok=True)
                        self._socket, self._ws = peer, ws
                        self.state = "connecting"
                        ws.send(json.dumps(dict(op="paired", request=self.generation, generation=self.generation)))
                        peer.settimeout(None)
                        self._reader = threading.Thread(target=self._read, args=(ws,), name="look-extension-root", daemon=True)
                        self._reader.start()
                    self.command("Look.ready")  # Selected tab must already be attached by the worker.
                    with self._lock:
                        if not self.live or time.monotonic() >= self._expires:
                            raise OwnershipError("Extension connection cancelled or expired before readiness")
                        self.state = "connected"
                    return
                except (OSError, EOFError, ValueError):
                    ws.close()
                    if self._ws is ws:
                        raise OwnershipError("Extension pairing ended before readiness") from None
            raise OwnershipError("Extension pairing expired or was cancelled. Start Look again explicitly.")
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, OwnershipError) else "Extension connection failed. Start Look again explicitly."
            self.close()
            self.state = "failed"
            raise OwnershipError(self.error) from None

    async def channel(self, target):
        result = await asyncio.to_thread(self.command, "Look.channel", {"targetId": target})
        session = result["sessionId"]
        with self._lock:
            if not self.live or session in self._used_sessions:
                self.abort()
                raise OwnershipError("Extension tab session is stale")
            self._used_sessions.add(session)
            channel = TargetChannel(self, target, session, asyncio.get_running_loop())
            self.channels[session] = channel
            return channel

    def detach(self, channel):
        with self._lock:
            if self.channels.get(channel.session) is not channel:
                return
            self.channels.pop(channel.session)
        channel.lost()
        if self.live:
            self.command("Look.detach", {"sessionId": channel.session})

    def forget(self, channel, local_id, *, abort_unknown=True):
        with self._lock:
            unknown = any(value[1] is channel and value[2] == local_id for value in self._pending.values())
        if unknown and abort_unknown:
            self.abort()  # Only the fixed read-only focus probe may time out without revocation.

    def _unpublish(self):
        self._capability = ""
        if self._discovery:
            self._discovery.unlink(missing_ok=True)
            self._discovery = None

    def close(self):
        with self._lock:
            listener, self._listener = self._listener, None
            self._unpublish()
            if listener:
                listener.close()
            if self._path:
                self._path.unlink(missing_ok=True)
        super().close()
