"""Private-profile launch identity, not authentication against same-user local code."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request

from ..config import local_cdp_url


class OwnershipError(ConnectionError):
    """Refuse an unverified endpoint without touching its pages or process."""


def companion_profile() -> Path:
    # Browser/microphone ownership is account-wide, not scoped to a Hermes profile.
    return Path.home() / ".cache" / "hermes-gaze" / "chrome-profile"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise OwnershipError("Chrome discovery redirected. Refusing this debugging endpoint.")


def acquire_runtime_lease(profile: Path):
    """Lock Look's own runtime directory, never a borrowed Chrome profile."""
    if profile.is_symlink():
        raise OwnershipError("Look's companion profile must not be a symlink.")
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    if profile.stat().st_uid != os.getuid():
        raise OwnershipError("Look's companion profile belongs to another OS user.")
    profile.chmod(0o700)
    fd = os.open(profile / ".look-runtime.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    lease = os.fdopen(fd, "r+")
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lease.close()
        raise OwnershipError("Another Look runtime owns the companion. Stop Look in that Hermes process first.") from None
    return lease


class OwnedChrome:
    def __init__(self, http_url: str, profile_dir: Path | None = None) -> None:
        self.http_url = local_cdp_url(http_url)
        self.profile = (profile_dir or companion_profile()).absolute()
        self.process: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._lease = None
        self._token = ""
        self._ws = None
        self._sequence = 0

    def _listening(self) -> bool:
        with socket.socket() as probe:
            probe.settimeout(1)
            return probe.connect_ex(("127.0.0.1", int(self.http_url.rsplit(":", 1)[1]))) == 0

    def _acquire(self) -> None:
        if self._lease is not None:
            return
        self._lease = acquire_runtime_lease(self.profile)

    def _read_token(self) -> str:
        try:
            fd = os.open(self.profile / ".look-owner", os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd) as handle:
                info = os.fstat(handle.fileno())
                if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
                    raise ValueError("not private")
                token = handle.read(65)
            if not re.fullmatch(r"[0-9a-f]{64}", token):
                raise ValueError("invalid token")
            return token
        except (OSError, ValueError):
            raise OwnershipError("Debugging port is not a verified Look companion. Close only Look's old companion windows, "
                                 "or choose a free local cdp_url port, then /look start. Do not close an unrelated browser.") from None

    def verify_arguments(self, result: dict) -> None:
        args = result.get("arguments", [])
        expected = {"--enable-automation", f"--user-data-dir={self.profile}",
                    f"--remote-debugging-port={self.http_url.rsplit(':', 1)[1]}",
                    f"--hermes-gaze-owner={self._token}"}
        if not self._token or not isinstance(args, list) or not expected.issubset(args):
            raise OwnershipError("Debugging endpoint is another browser, not Look's owned companion. "
                                 "Leave it running. Choose a free local cdp_url port, or close only Look's old companion and retry.")

    def _exchange(self, method: str, params: dict) -> dict:
        self._sequence += 1
        sequence = self._sequence
        self._ws.send(json.dumps({"id": sequence, "method": method, "params": params}))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            message = json.loads(self._ws.recv(timeout=max(.01, deadline - time.monotonic())))
            if message.get("id") == sequence:
                if "error" in message:
                    raise OwnershipError("Chrome could not verify or execute the companion request. Stop Look and /look start again.")
                return message.get("result", {})
        raise TimeoutError("Companion reply deadline")

    def _verify(self) -> None:
        if self._lease is None:
            raise OwnershipError("Look is stopped. Use /look start.")
        if self._ws is not None:
            return  # This socket stays pinned to the already-verified browser process.
        from websockets.sync.client import connect
        self._token = self._read_token()
        # No environment proxy, redirect, DNS alias, or server-supplied WebSocket host.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(self.http_url + "/json/version", timeout=2) as response:
            version = json.loads(response.read(65537))
        ws_url = version.get("webSocketDebuggerUrl", "")
        prefix = self.http_url.replace("http://", "ws://") + "/devtools/browser/"
        if not isinstance(ws_url, str) or not re.fullmatch(re.escape(prefix) + r"[a-zA-Z0-9-]+", ws_url):
            raise OwnershipError("The debugging port is not a local Chrome endpoint. Leave its service running and choose a free cdp_url port.")
        self._ws = connect(ws_url, open_timeout=2, close_timeout=1, max_size=1024 * 1024, proxy=None)
        try:
            self.verify_arguments(self._exchange("Browser.getBrowserCommandLine", {}))
        except Exception:
            self._ws.close()
            self._ws = None
            raise

    def attach(self) -> None:
        with self._lock:
            acquired = self._lease is None
            try:
                if acquired and not self._listening():
                    raise OwnershipError("Look's companion is not running. Use /look start.")
                self._acquire()
                self._verify()
                self.verify_arguments(self._exchange("Browser.getBrowserCommandLine", {}))
            except Exception as exc:
                if self._ws is not None:
                    self._ws.close()
                    self._ws = None
                if acquired:
                    self.close()
                if isinstance(exc, OwnershipError):
                    raise
                raise OwnershipError("Look couldn’t verify its companion browser. Leave unrelated services running. "
                                     "Close only Look's old companion or choose a free local cdp_url port, then run /look start.") from None

    def available(self) -> bool:
        with self._lock:
            acquired = self._lease is None
            try:
                self.attach()
                # attach verifies on the live socket, including warm reuse.
                return True
            except (OSError, RuntimeError):
                return False
            finally:
                if acquired:
                    self.close()

    def start(self, url: str = "about:blank", *, chrome_args: tuple[str, ...] = (), executable: str | None = None) -> None:
        """Explicit start only; never kill an occupant or automatically replay a launch."""
        with self._lock:
            acquired = self._lease is None
            self._acquire()
            try:
                port = int(self.http_url.rsplit(":", 1)[1])
                occupied = self._listening()
                if occupied:
                    self.attach()
                    return
                if self._ws is not None:
                    self._ws.close()
                    self._ws = None
                self._token = secrets.token_hex(32)
                fd = os.open(self.profile / ".look-owner", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as handle:
                    os.fchmod(handle.fileno(), 0o600)
                    handle.write(self._token)
                mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                exe = executable or (str(mac) if sys.platform == "darwin" else "google-chrome")
                args = [exe, f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
                        f"--user-data-dir={self.profile}", "--enable-automation", f"--hermes-gaze-owner={self._token}",
                        "--no-first-run", "--no-default-browser-check", *chrome_args, url]
                self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        break
                    try:
                        self._verify()
                        return
                    except (OSError, ValueError):
                        time.sleep(.1)
                raise OwnershipError("Look's Chrome did not start or its profile is already open. "
                                     "Close only the Look companion windows and retry /look start. Keep unrelated browsers open.")
            except Exception as exc:
                if acquired:
                    self.close()
                if isinstance(exc, OwnershipError):
                    raise
                raise OwnershipError("Chrome could not start. Install Google Chrome, check the local cdp_url port, then /look start.") from None

    def command(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            try:
                self._verify()
                return self._exchange(method, params or {})
            except Exception:
                if self._ws is not None:
                    self._ws.close()
                    self._ws = None
                # The command may have executed. Never reconnect/replay it here.
                raise OwnershipError("Companion connection lost with an unknown outcome. Run /look stop, then /look start. Do not repeat an action automatically.") from None

    def close(self) -> None:
        with self._lock:
            if self._ws is not None:
                self._ws.close()
                self._ws = None
            if self._lease is not None:
                self._lease.close()
                self._lease = None
            self._token = ""
