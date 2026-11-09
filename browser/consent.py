"""Borrow one explicitly approved Chrome socket; never launch, reconnect or relay it."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import threading

from .ownership import OwnershipError, acquire_runtime_lease, companion_profile

DISCLOSURE = (
    "Chrome grants Look broad debugger access, including signed-in pages and browser data. "
    "Look instruments ordinary web tabs in one supported profile; only the foreground private card receives answers. "
    "The bounded page evidence you ask about goes to your configured model and may stay in Hermes history. "
    "Approve only the Chrome request you just started. Stop disconnects Look, not Chrome's remote-debugging setting."
)
PREPARE = "In Chrome 145+, enter chrome://inspect/#remote-debugging and enable remote debugging."


def discovery_port(path: Path) -> int:
    """Read only the explicitly selected discovery file, never browser profile contents."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o022 or info.st_size > 4096):
                raise ValueError
            data = handle.read(4097)
        if len(data) > 4096:
            raise ValueError
        match = re.fullmatch(rb"([1-9][0-9]{0,4})\n/devtools/browser/"
                             rb"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\n?", data)
        if not match or not 1 <= int(match[1]) <= 65535:
            raise ValueError
        return int(match[1])
    except (OSError, ValueError):
        raise OwnershipError("Chrome discovery is unavailable or invalid. " + PREPARE) from None


class TargetChannel:
    """A private async queue for one root-generation/target/session, consumed by CdpSession."""
    def __init__(self, root, target: str, session: str, loop) -> None:
        self.root, self.target, self.session, self.loop = root, target, session, loop
        self.generation = root.generation
        self.document_prefix = f"{self.generation}:{target}:{session}:"
        self.queue = asyncio.Queue(maxsize=2048)
        self.closed = False

    @property
    def live(self) -> bool:
        return (not self.closed and self.root.live and self.root.generation == self.generation
                and self.root.channels.get(self.session) is self)

    def deliver(self, message) -> None:
        def put():
            if self.closed:
                return
            if self.queue.full():
                self.root.abort()
            else:
                self.queue.put_nowait(message)
        try:
            self.loop.call_soon_threadsafe(put)
        except RuntimeError:
            pass  # The consuming tab is already gone.

    def lost(self) -> None:
        self.deliver(None)

    def forget(self, local_id):
        with self.root._lock:
            for key, value in list(self.root._pending.items()):
                if value[1] is self and value[2] == local_id:
                    self.root._pending.pop(key)

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.queue.get()
        if message is None or not self.live:
            raise StopAsyncIteration
        return json.dumps(message)

    async def send(self, raw: str) -> None:
        await asyncio.to_thread(self.root.send_target, self, json.loads(raw))

    async def close(self) -> None:
        if self.closed:
            return
        await asyncio.to_thread(self.root.detach, self)
        self.closed = True


class ConsentChrome:
    """One human connection attempt. A lost/denied/stopped instance is terminal."""
    def __init__(self, *, metadata_path: Path | None = None, lease_dir: Path | None = None,
                 on_loss=None) -> None:
        self.metadata_path = metadata_path or (Path.home() / "Library/Application Support/Google/Chrome/DevToolsActivePort")
        self.lease_dir = lease_dir or companion_profile()
        self.on_loss = on_loss
        self.generation = secrets.token_hex(16)
        self.state, self.error = "idle", ""
        self.default_context = ""
        self.product = ""
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._lease = None
        self._socket = None
        self._ws = None
        self._reader = None
        self._sequence = 0
        self._pending = {}
        self.channels: dict[str, TargetChannel] = {}
        self._used_sessions = set()

    @property
    def live(self) -> bool:
        return self._ws is not None and not self._stopped.is_set()

    def available(self) -> bool:
        return self.live  # Never read personal discovery or start consent from a health check.

    def attach(self) -> None:
        if not self.live or self.state != "connected":
            raise OwnershipError("Chrome disconnected. Connect again explicitly to continue.")

    def _tcp(self, family, address, port):
        sock = socket.socket(family, socket.SOCK_STREAM)
        with self._lock:
            if self._stopped.is_set():
                sock.close()
                raise OwnershipError("Chrome connection cancelled.")
            self._socket = sock
        sock.settimeout(2)
        try:
            sock.connect((address, port))
            return sock
        except BaseException:
            sock.close()
            raise

    def start(self, *, timeout: float = 120) -> None:
        from websockets.sync.client import connect
        from websockets.exceptions import InvalidStatus
        with self._lock:
            if self.state != "idle":
                raise OwnershipError("This Chrome connection attempt already started. Stop before trying again.")
            self.state = "discovering"
        try:
            with self._lock:
                if self._stopped.is_set():
                    raise OwnershipError("Chrome connection cancelled.")
                self._lease = acquire_runtime_lease(self.lease_dir)
            port = discovery_port(self.metadata_path)
            # Only TCP refusal may try the other loopback family; never retry a handshake.
            for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
                try:
                    probe = self._tcp(family, address, port)
                    break
                except OSError:
                    if self._stopped.is_set() or family == socket.AF_INET6:
                        raise OwnershipError("Chrome's local listener is unavailable. " + PREPARE) from None
            try:
                host = f"[{address}]" if family == socket.AF_INET6 else address
                probe.sendall(f"GET /json/version HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n".encode())
                with http.client.HTTPResponse(probe) as response:
                    response.begin()
                    if response.status != 404:
                        raise OwnershipError("This is not Chrome's native approval endpoint. " + PREPARE)
            finally:
                probe.close()
            sock = self._tcp(family, address, port)
            sock.settimeout(None)  # The WebSocket deadline, not the TCP dial bound, owns human consent.
            with self._lock:
                if self._stopped.is_set():
                    raise OwnershipError("Chrome connection cancelled.")
                self.state = "waiting"
            # sock= forbids every redirect; no proxy, DNS, Origin, guessed GUID or retry.
            ws = connect(f"ws://{host}:{port}/devtools/browser", sock=sock, origin=None, proxy=None,
                         open_timeout=timeout, close_timeout=1, max_size=32 * 1024 * 1024)
            with self._lock:
                if self._stopped.is_set():
                    ws.close()
                    raise OwnershipError("Chrome connection cancelled.")
                self._ws = ws
                self.state = "connecting"
                self._reader = threading.Thread(target=self._read, args=(ws,), name="look-chrome-root", daemon=True)
                self._reader.start()
            self.product = self.command("Browser.getVersion").get("product", "")
            version = re.fullmatch(r"(?:Chrome|HeadlessChrome)/(\d+)\.[0-9.]+", self.product)
            if not version or int(version[1]) < 145:
                raise OwnershipError("Look requires Chrome 145+ with native approval and regular-profile identification. Update Chrome.")
            contexts = self.command("Target.getBrowserContexts")
            context = contexts.get("defaultBrowserContextId")
            if not isinstance(context, str) or not context or context in contexts.get("browserContextIds", []):
                raise OwnershipError("Chrome did not provide a safe regular-profile identity (Target.getBrowserContexts.defaultBrowserContextId). Update to stable Chrome 145+; private/multiple profiles are unsupported.")
            self.default_context = context
            self.command("Target.getTargets")  # Capability check before any Runtime/page access.
            with self._lock:
                if not self.live:
                    raise OwnershipError("Chrome disconnected before it was ready.")
                self.state = "connected"
        except Exception as exc:
            if self._stopped.is_set():
                message = self.error or "Chrome connection cancelled. Cancel any remaining Chrome prompt."
            elif isinstance(exc, InvalidStatus) and exc.response.status_code == 403:
                message = "Chrome declined the connection. Connect again only when you want a new approval request."
            elif isinstance(exc, TimeoutError):
                message = "Chrome approval timed out. Cancel any remaining Chrome prompt before connecting again."
            elif isinstance(exc, OwnershipError):
                message = str(exc)
            else:
                message = "Chrome connection failed; permission or browser policy could not be established. " + PREPARE
            self.error = message
            self.close()
            self.state = "failed"
            raise OwnershipError(message) from None

    def _send(self, method, params, *, channel=None, local_id=None):
        with self._lock:
            if not self.live or (channel is not None and not channel.live):
                raise OwnershipError("Chrome disconnected; outcome unknown. Do not replay the action.")
            self._sequence += 1
            sequence = self._sequence
            future = Future() if channel is None else None
            session = channel.session if channel else None
            self._pending[sequence] = (session, channel, local_id, future)
            message = dict(id=sequence, method=method, params=params)
            if session:
                message["sessionId"] = session
            ws = self._ws
        try:
            ws.send(json.dumps(message))
        except Exception:
            self.abort()
            raise OwnershipError("Chrome connection lost; outcome unknown. Do not replay the action.") from None
        return sequence, future

    def command(self, method: str, params: dict | None = None) -> dict:
        sequence, future = self._send(method, params or {})
        try:
            message = future.result(3)
            if "error" in message:
                raise OwnershipError("Chrome refused the requested operation; browser policy or profile may not support it.")
            return message.get("result") or {}
        except TimeoutError:
            self.abort()
            raise OwnershipError("Chrome reply lost; outcome unknown. Do not replay the action.") from None
        finally:
            with self._lock:
                self._pending.pop(sequence, None)

    def send_target(self, channel, message):
        self._send(message["method"], message.get("params") or {}, channel=channel, local_id=message["id"])

    async def channel(self, target: str):
        info = (await asyncio.to_thread(self.command, "Target.getTargetInfo", {"targetId": target}))["targetInfo"]
        if (info.get("targetId") != target or info.get("type") != "page"
                or info.get("browserContextId") != self.default_context
                or not str(info.get("url", "")).startswith(("http://", "https://"))):
            raise OwnershipError("That tab is outside the authorized ordinary web profile.")
        session = (await asyncio.to_thread(self.command, "Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
        with self._lock:
            if not self.live or not isinstance(session, str) or not session or session in self._used_sessions:
                self.abort()
                raise OwnershipError("Chrome target session identity is unavailable.")
            self._used_sessions.add(session)
            channel = TargetChannel(self, target, session, asyncio.get_running_loop())
            self.channels[session] = channel
        info = (await asyncio.to_thread(self.command, "Target.getTargetInfo", {"targetId": target}))["targetInfo"]
        if info.get("targetId") != target or info.get("browserContextId") != self.default_context:
            await channel.close()
            raise OwnershipError("Chrome target profile changed during attachment.")
        return channel

    def detach(self, channel):
        with self._lock:
            if self.channels.get(channel.session) is not channel:
                return
            self.channels.pop(channel.session)
            pending = [key for key, value in self._pending.items() if value[1] is channel]
            for key in pending:
                self._pending.pop(key)
        channel.lost()
        if self.live:
            try:
                self.command("Target.detachFromTarget", {"sessionId": channel.session})
            except OwnershipError:
                pass

    def _read(self, ws):
        try:
            for raw in ws:
                message = json.loads(raw)
                with self._lock:
                    if self._ws is not ws or not self.live:
                        break
                    session = message.get("sessionId")
                    if "id" in message:
                        pending = self._pending.get(message["id"])
                        if pending is None or session != pending[0]:
                            continue
                        self._pending.pop(message["id"])
                        _, channel, local_id, future = pending
                        if channel is None:
                            future.set_result(message)
                        elif channel.live:
                            channel.deliver(dict(message, id=local_id))
                    elif session:
                        channel = self.channels.get(session)
                        if channel and channel.live:
                            channel.deliver(message)
                    elif message.get("method") == "Target.detachedFromTarget":
                        channel = self.channels.pop((message.get("params") or {}).get("sessionId"), None)
                        if channel:
                            channel.lost()
        except Exception:
            pass  # Never include socket URLs, target inventory or browser errors in logs.
        finally:
            self.abort()

    def abort(self):
        """Revoke before notifying the application; the callback never runs on the reader."""
        with self._lock:
            notify = not self._stopped.is_set() and self._ws is not None
            callback = self.on_loss if notify else None
            self._stopped.set()
            self.state = "disconnected"
            pending, self._pending = self._pending, {}
            channels, self.channels = self.channels, {}
            sock, self._socket = self._socket, None
            ws, self._ws = self._ws, None
        for _, _, _, future in pending.values():
            if future is not None and not future.done():
                future.set_exception(OwnershipError("Chrome connection lost; outcome unknown. Do not replay the action."))
        for channel in channels.values():
            channel.lost()
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        if ws is not None:
            ws.close()
        if callback:
            threading.Thread(target=callback, name="look-chrome-lost", daemon=True).start()

    def close(self):
        self.on_loss = None  # Deliberate Stop is handled by the caller, not a second loss callback.
        self.abort()
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(2)
        with self._lock:
            if self._lease is not None:
                self._lease.close()
                self._lease = None
