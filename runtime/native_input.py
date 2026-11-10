"""Look-owned client for stock Hermes's authenticated canonical local protocol.

No runtime discovery that can start a host, private agent access, or browser auth.
The deliberately narrow lane is an in-process POSIX plugin and its own profile's
private direct control socket. Other frontends retain the SDK injector.
"""
from __future__ import annotations

import asyncio
import ctypes
import ipaddress
import json
import logging
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import threading
import time
from urllib.parse import urlsplit

PROTOCOL = "hermes-gateway-v1"


class NativeError(Exception):
    """Bounded local reason, never a server error body or credential."""


class Refused(NativeError):
    pass


def consent(home, plugin_id):
    # Read the captured profile, not a worker thread's ambient HERMES_HOME.
    import yaml
    try:
        config = yaml.safe_load((home / "config.yaml").read_text()) or {}
        plugins = config.get("plugins") or {}
        # Stock Hermes defaults to in_process when this key is omitted.
        return (plugins.get("isolation", "in_process") == "in_process" and
                plugins.get("entries", {}).get(plugin_id, {}).get("allow_gateway_injection") is True)
    except Exception:
        return False


def _control(home, verb, params=None):
    """Same-OS-user authenticated direct control socket; no fallback path guessing."""
    if os.name != "posix":
        raise NativeError("unsupported_native_transport")
    for path, predicate, mask in ((home, stat.S_ISDIR, 0o022),
                                  (home / "gateway.sock", stat.S_ISSOCK, 0o077)):
        node = path.lstat()
        if (not predicate(node.st_mode) or node.st_uid != os.getuid() or node.st_mode & mask):
            raise NativeError("unsafe_control_permissions")
    deadline = time.monotonic() + 3
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(3)
        peer.connect(str(home / "gateway.sock"))
        if hasattr(socket, "SO_PEERCRED"):
            uid = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
        elif sys.platform == "darwin":
            uid_value, gid = ctypes.c_uint(), ctypes.c_uint()
            getpeereid = ctypes.CDLL(None, use_errno=True).getpeereid
            getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
            getpeereid.restype = ctypes.c_int
            if getpeereid(peer.fileno(), ctypes.byref(uid_value), ctypes.byref(gid)):
                raise NativeError("control_peer_unverified")
            uid = uid_value.value
        else:
            raise NativeError("control_peer_unverified")
        if uid != os.getuid():
            raise NativeError("control_peer_unverified")
        request = dict(protocol=1, id=1, verb=verb)
        if params is not None:
            request["params"] = params
        peer.sendall(json.dumps(request).encode() + b"\n")
        data = bytearray()
        while b"\n" not in data:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativeError("control_timeout")
            peer.settimeout(remaining)
            chunk = peer.recv(4096)
            if not chunk or len(data) + len(chunk) > 65536:
                raise NativeError("invalid_control_response")
            data.extend(chunk)
    result = json.loads(data.split(b"\n", 1)[0])
    if (result.get("protocol") != 1 or result.get("id") != 1 or result.get("ok") is not True
            or not isinstance(result.get("result"), dict)):
        raise NativeError("native_auth_refused")
    return result["result"]


class NativeInput:
    def __init__(self, home, plugin_id, logical_id, *, identity=None, receipt_admission=""):
        self.home, self.plugin_id, self.logical_id = Path(home).resolve(), plugin_id, logical_id
        self.identity = identity
        self.receipt_admission = receipt_admission
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="look-native-input", daemon=True)
        self.thread.start()
        self.ws = None
        self.reader = None
        self.pending = {}
        self.serial = 0
        self.changed = None
        self.closed = False
        self.on_disconnect = None

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()

    def open(self):
        try:
            asyncio.run_coroutine_threadsafe(self._open(), self.loop).result(15)
        except Exception as exc:
            self.close()
            reason = str(exc) if isinstance(exc, NativeError) else "native_connection_unavailable"
            raise NativeError(f"Native Look input unavailable ({reason}). No question was sent. Use Hermes input instead.") from None

    def _bootstrap(self):
        if not consent(self.home, self.plugin_id) and not (self.receipt_admission and self.identity is not None):
            raise NativeError("gateway_injection_not_granted")
        identity = _control(self.home, "identify")
        if (identity.get("pid") != os.getpid() or identity.get("runtime_protocol") != 1
                or identity.get("state") != "ready"
                or "session-authority-v1" not in identity.get("capabilities", [])):
            raise NativeError("not_own_canonical_runtime")
        profiles = [p for p in identity.get("served_profiles", []) if p.get("home") == str(self.home)]
        if len(profiles) != 1 or profiles[0].get("profile_id") != str(self.home):
            raise NativeError("profile_mismatch")
        pinned = (identity.get("instance_id"), identity.get("authority_epoch"))
        if (not isinstance(pinned[0], str) or not pinned[0] or type(pinned[1]) is not int
                or pinned[1] <= 0 or self.identity is not None and self.identity != pinned):
            raise NativeError("native_owner_changed")
        origin = urlsplit(identity.get("api_origin", ""))
        if (origin.scheme != "http" or not origin.hostname or not ipaddress.ip_address(origin.hostname).is_loopback
                or not origin.port or origin.path or origin.query or origin.fragment
                or origin.username is not None or origin.password is not None):
            raise NativeError("invalid_native_endpoint")
        grant = _control(self.home, "session-ticket", dict(
            profile_id=str(self.home), instance_id=pinned[0], purpose="interactive", restart_wait="refuse"))
        if (grant.get("instance_id") != pinned[0] or grant.get("profile_id") != str(self.home)
                or grant.get("runtime_protocol") != 1 or not isinstance(grant.get("ticket"), str)
                or not grant["ticket"]):
            raise NativeError("native_auth_changed")
        return pinned, "ws://" + origin.netloc + "/api/ws", grant["ticket"]

    async def _open(self):
        from websockets.asyncio.client import connect
        identity, url, ticket = await asyncio.to_thread(self._bootstrap)
        endpoint = urlsplit(url)
        peer = socket.socket(socket.AF_INET6 if ":" in endpoint.hostname else socket.AF_INET, socket.SOCK_STREAM)
        peer.setblocking(False)
        try:
            await asyncio.wait_for(self.loop.sock_connect(peer, (endpoint.hostname, endpoint.port)), 5)
            # As in Chrome consent, sock= forbids redirects carrying the auth ticket.
            self.ws = await connect(url, sock=peer,
                                    subprotocols=[PROTOCOL, "hermes-gateway-ticket." + ticket],
                                    proxy=None, open_timeout=5, max_size=8 * 1024 * 1024)
        except BaseException:
            peer.close()
            raise
        if self.ws.subprotocol != PROTOCOL:
            raise NativeError("native_protocol_mismatch")
        self.changed = asyncio.Event()
        self.reader = asyncio.create_task(self._read())
        runtime = await self._rpc("runtime.describe")
        if ((runtime.get("instance_id"), runtime.get("authority_epoch")) != identity
                or runtime.get("profile_id") != str(self.home)
                or not {"durable-admission-v1", "event-replay-v1"} <= set(runtime.get("capabilities", []))):
            raise NativeError("native_owner_changed")
        resumed = await self._rpc("session.resume", session_id=self.logical_id, omit_messages=True)
        if (resumed.get("session_id") != self.logical_id or resumed.get("authority_epoch") != identity[1]
                or resumed.get("info", {}).get("profile_id") != str(self.home)
                or resumed.get("info", {}).get("source") not in ("cli", "tui", "gui")):
            raise NativeError("native_session_mismatch")
        self.identity = identity

    async def _read(self):
        try:
            async for raw in self.ws:
                frame = json.loads(raw)
                future = self.pending.get(frame.get("id"))
                if future is not None and not future.done():
                    future.set_result(frame)
                elif frame.get("method") == "event":
                    event = frame.get("params") or {}
                    if (event.get("session_id") == self.logical_id and self.on_disconnect is not None
                            and (event.get("type") == "session.replay_gap" or
                                 event.get("type") == "session.updated" and
                                 (event.get("payload") or {}).get("operation") in
                                 {"reset", "compress", "rewind", "model", "workspace", "editor_mcp", "edit_policy"})):
                        self.on_disconnect()
                    self.changed.set()
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(NativeError("native_connection_lost"))
            self.changed.set()
            if not self.closed and self.on_disconnect is not None:
                self.on_disconnect()

    async def _rpc(self, method, **params):
        self.serial += 1
        key = str(self.serial)
        future = self.loop.create_future()
        self.pending[key] = future
        try:
            await self.ws.send(json.dumps(dict(jsonrpc="2.0", id=key, method=method, params=params)))
            frame = await asyncio.wait_for(future, 10)
            if "error" in frame:
                reason = frame["error"].get("data", {}).get("reason", "native_request_refused")
                raise Refused(reason if isinstance(reason, str) and reason.replace("_", "").isalnum()
                              and len(reason) <= 80 else "native_request_refused")
            return frame["result"]
        finally:
            self.pending.pop(key, None)

    def submit(self, run, callback):
        """Exactly one stable ID/payload. Never switch to SDK after any handoff."""
        async def observe():
            previous_attempt = bool(run.get("native_attempted"))
            wire = run.setdefault("native_wire", run["wire"])
            try:
                if self.receipt_admission and run.get("admission_id") != self.receipt_admission:
                    callback(run, {"status": "unknown", "error": "receipt_owner_mismatch"})
                    return
                if not run.get("admission_id") and not await asyncio.to_thread(consent, self.home, self.plugin_id):
                    callback(run, {"status": "unknown" if previous_attempt else "refused",
                                   "error": "gateway_injection_not_granted"})
                    return
                if not run.get("admission_id"):
                    # A reconnect reuses this ID only on the exact pinned runtime/profile.
                    run["native_attempted"] = True
                    receipt = await self._rpc("prompt.submit", session_id=self.logical_id,
                                              submission_id=run["request_id"], text=wire)
                    run["admission_id"] = receipt["admission_id"]
                if run.get("cancel_requested"):
                    await self._cancel(run, callback)
                while True:
                    self.changed.clear()
                    receipt = await self._rpc("prompt.receipt", session_id=self.logical_id,
                                              admission_id=run["admission_id"], include_result=True)
                    ref = receipt.get("ref", {})
                    if (ref.get("profile_id") != str(self.home) or ref.get("session_id") != self.logical_id
                            or receipt.get("authority_epoch") != self.identity[1]):
                        raise NativeError("native_owner_changed")
                    if receipt["status"] in ("terminal", "unknown"):
                        callback(run, receipt)
                        return
                    await self.changed.wait()
                    if self.reader.done():
                        raise NativeError("native_connection_lost")
            except Refused as exc:
                # Only a submit refusal is definite. A failed receipt lookup is not.
                callback(run, {"status": "unknown" if previous_attempt or run.get("admission_id") else "refused",
                               "error": str(exc)})
            except Exception:
                callback(run, {"status": "unknown", "error": "Native connection lost with an unknown outcome. Reconnect this conversation. Do not send the question again."})
        return asyncio.run_coroutine_threadsafe(observe(), self.loop)

    async def _cancel(self, run, callback):
        """Stock prompt.cancel retires queued work or interrupts its exact running claim."""
        if not run.get("admission_id") or run.get("cancel_dispatched"):
            return
        run["cancel_dispatched"] = True
        try:
            await self._rpc("prompt.cancel", session_id=self.logical_id,
                            admission_id=run["admission_id"])
        except Exception:
            # A lost interrupt reply is not a terminal receipt or permission to replay.
            logging.getLogger(__name__).warning("Look stop was not confirmed; retaining receipt ownership")
            callback(run, {"status": "cancel_unconfirmed"})

    def cancel(self, run, callback):
        return asyncio.run_coroutine_threadsafe(self._cancel(run, callback), self.loop)

    def close(self):
        if self.closed:
            return
        self.closed = True
        async def shutdown():
            if self.ws is not None:
                await self.ws.close()
            if self.reader is not None:
                await asyncio.gather(self.reader, return_exceptions=True)
        future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
        future.add_done_callback(lambda _: self.loop.call_soon_threadsafe(self.loop.stop))
