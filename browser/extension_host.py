"""Look's explicit macOS development native host. No Hermes imports or HTTP listener."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import stat
import struct
import sys
import threading
import tempfile
import time

NAME = "org.look.companion"
MAX_MESSAGE = 768 * 1024  # Below Chrome's 1 MiB native-host output ceiling.
ID = re.compile(r"[a-p]{32}")
REQUEST = re.compile(r"[0-9a-f]{32}")
CAPABILITY = re.compile(r"[0-9a-f]{64}")


def private_directory(path):
    path = Path(path)
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Look directory must be private and owned by this user")
    return path


def runtime_directory():
    # Short enough for macOS's 104-byte Unix socket path limit; never a browser profile.
    return private_directory(Path("/tmp") / f"look-extension-{os.getuid()}")


def install_directory():
    return Path.home() / "Library/Application Support/Look/extension"


def manifest_directory():
    return Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts"


def read_message(stream):
    def exact(size):
        data = bytearray()
        while len(data) < size:
            part = stream.read(size - len(data))
            if not part:
                raise EOFError("Native connection ended")
            data.extend(part)
        return bytes(data)
    size = struct.unpack("<I", exact(4))[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("Native message exceeds Look's bound")
    value = json.loads(exact(size))
    if not isinstance(value, dict):
        raise ValueError("Native message must be an object")
    return value


def send_message(stream, value):
    data = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if not 0 < len(data) <= MAX_MESSAGE:
        raise ValueError("Native message exceeds Look's bound")
    for part in (struct.pack("<I", len(data)), data):
        remaining = memoryview(part)
        while remaining:
            written = stream.write(remaining)
            if not written:
                raise EOFError("Native connection stopped accepting writes")
            remaining = remaining[written:]
    stream.flush()


def configuration(directory=None):
    path = (directory or install_directory()) / "config.json"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Look host configuration is not private")
        config = json.loads(source.read(4097))
    if not isinstance(config, dict) or not isinstance(config.get("extension_id"), str) or not ID.fullmatch(config["extension_id"]):
        raise ValueError("Look extension ID is invalid")
    return config


def pending_request():
    """Private discovery only; never inspect Chrome profiles or choose a runtime."""
    try:
        raw = _read_installed(runtime_directory() / "pending.json")
        if raw is None:
            return None
        value = json.loads(raw)
        if (not isinstance(value, dict) or not REQUEST.fullmatch(value.get("request", ""))
                or not CAPABILITY.fullmatch(value.get("capability", ""))
                or not re.fullmatch(r"[0-9a-f]{24}\.sock", value.get("socket", ""))
                or not isinstance(value.get("expires"), (float, int))
                or not time.monotonic() < value["expires"] <= time.monotonic() + 120):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


@contextmanager
def _setup_lock(directory):
    fd = os.open(directory / ".setup.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "r+") as lock:
        _private_file(os.fstat(lock.fileno()))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Another Look setup is running. Try again when it finishes.") from None
        yield


def _private_file(info):
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Look setup files must be private regular files owned by this user")


def _read_installed(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as source:
        _private_file(os.fstat(source.fileno()))
        return source.read()


def _registration(extension_id, directory):
    return dict(name=NAME, description="Look browser companion", path=str(directory / "host"),
                type="stdio", allowed_origins=[f"chrome-extension://{extension_id}/"])


def _owned_install(directory, manifest):
    config = _read_installed(directory / "config.json")
    registration = _read_installed(manifest)
    if config is None:
        if registration is not None:
            raise ValueError("Native registration belongs to a different install")
        return None
    config = json.loads(config)
    if not isinstance(config, dict) or not isinstance(config.get("extension_id"), str):
        raise ValueError("Look host configuration is invalid")
    extension_id = config.get("extension_id", "")
    if not ID.fullmatch(extension_id):
        raise ValueError("Look extension ID is invalid")
    if registration is not None:
        value = json.loads(registration)
        expected = _registration(extension_id, directory)
        if not isinstance(value, dict) or any(value.get(key) != expected[key] for key in ("name", "path", "type", "allowed_origins")):
            raise ValueError("Native registration belongs to a different install")
    return extension_id


def _replace(path, value, mode):
    fd, temporary = tempfile.mkstemp(prefix=".look-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), mode)
            output.write(value)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


EXTENSION_FILES = ("manifest.json", "worker.js", "popup.html", "popup.js",
                   "icon-16.png", "icon-32.png", "icon-48.png", "icon-128.png")


def install(*, directory=None, manifests=None):
    """Stage fixed-path assets and an exact-origin host; refresh only our owned install."""
    directory = private_directory(Path(directory or install_directory()).absolute())
    manifests = Path(manifests or manifest_directory()).absolute()
    manifests.mkdir(parents=True, exist_ok=True)
    manifest = manifests / (NAME + ".json")
    source = Path(__file__).resolve()
    assets = source.parents[1] / "extension"
    key = json.loads((assets / "manifest.json").read_text())["key"]
    extension_id = "".join(chr(97 + int(c, 16)) for c in hashlib.sha256(base64.b64decode(key)).hexdigest()[:32])
    with _setup_lock(directory):
        previous = _owned_install(directory, manifest)
        if previous is not None and previous != extension_id:
            raise ValueError("An older Look extension ID is registered. Run /look setup extension uninstall first.")
        unpacked = private_directory(directory / "unpacked")
        # Ownership first, Chrome registration last: interrupted setup can be rerun.
        values = {directory / "config.json": json.dumps({"extension_id": extension_id}).encode()}
        values.update({unpacked / name: (assets / name).read_bytes() for name in EXTENSION_FILES})
        values[directory / "host.py"] = source.read_bytes()
        values[directory / "host"] = ("#!/bin/sh\nexec " + shlex.join(
            [sys.executable, str(directory / "host.py"), "--config", str(directory / "config.json")]) + ' "$@"\n').encode()
        values[manifest] = json.dumps(_registration(extension_id, directory)).encode()
        before = {path: _read_installed(path) for path in values}
        if previous is None and any(value is not None for value in before.values()):
            raise ValueError("Look setup found unregistered files and will not overwrite them.")
        changed = []
        try:
            for path, value in values.items():
                if before[path] != value or path.stat().st_mode & 0o777 != (0o700 if path == directory / "host" else 0o600):
                    _replace(path, value, 0o700 if path == directory / "host" else 0o600)
                    changed.append(path)
        except BaseException:
            for path in reversed(changed):
                if before[path] is None:
                    path.unlink()
                else:
                    _replace(path, before[path], 0o700 if path == directory / "host" else 0o600)
            raise
    return manifest


def uninstall(*, directory=None, manifests=None):
    directory = Path(directory or install_directory()).absolute()
    if not directory.exists() and not directory.is_symlink():
        manifest = Path(manifests or manifest_directory()) / (NAME + ".json")
        if manifest.exists() or manifest.is_symlink():
            raise ValueError("Native registration belongs to a different install")
        return
    directory = private_directory(directory)
    manifest = Path(manifests or manifest_directory()) / (NAME + ".json")
    with _setup_lock(directory):
        previous = _owned_install(directory, manifest)
        if previous is None:
            return
        unpacked = directory / "unpacked"
        if unpacked.exists() or unpacked.is_symlink():
            private_directory(unpacked)
        paths = [manifest, *(directory / name for name in ("host", "host.py")),
                 *(unpacked / name for name in EXTENSION_FILES), directory / "config.json"]
        for path in paths:
            _read_installed(path)  # Validate all paths before removing any of them.
        for path in paths:
            path.unlink(missing_ok=True)
        # Keep unknown files, directories and the setup lock; never delete browser data.


def relay(extension_id, origin, source, destination):
    if origin != f"chrome-extension://{extension_id}/":
        raise ValueError("Chrome extension origin does not match Look's registration")
    first = read_message(source)
    pending = pending_request()
    if first.get("op") == "status" and pending is None:
        send_message(destination, {"op": "status", "version": 1, "request": None})
        return
    if (first.get("op") not in ("status", "pair") or pending is None
            or first.get("op") == "pair" and first.get("request") != pending["request"]):
        raise ValueError("Start Look again in the intended Hermes conversation and reopen the popup")
    peer = None
    try:
        path = runtime_directory() / pending["socket"]
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Look session socket is not private")
        peer = socket.socket(socket.AF_UNIX)
        peer.settimeout(3)
        peer.connect(str(path))
        stream = peer.makefile("rwb", buffering=0)
        send_message(stream, dict(op=first["op"], request=pending["request"],
                                 capability=pending["capability"], extension_id=extension_id))
        answer = read_message(stream)
        expected = "status" if first["op"] == "status" else "paired"
        if answer.get("op") != expected or answer.get("request") != pending["request"]:
            raise ValueError("Look refused this connection. Run /look start --extension again.")
        send_message(destination, answer)
        if first["op"] == "status":
            return
        peer.settimeout(None)
        peer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack("ll", 3, 0))
        def upstream():
            try:
                while True:
                    send_message(stream, read_message(source))
            except (OSError, EOFError, ValueError):
                pass
            finally:
                try:
                    peer.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        threading.Thread(target=upstream, name="look-native-input", daemon=True).start()
        while True:
            send_message(destination, read_message(stream))
    except (OSError, EOFError, ValueError):
        if first["op"] != "status":
            raise
        send_message(destination, {"op": "status", "version": 1, "request": None})
    finally:
        if peer is not None:
            peer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action_or_origin", nargs="?")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    try:
        config = configuration(args.config.parent if args.config else None)
        relay(config["extension_id"], args.action_or_origin, sys.stdin.buffer, sys.stdout.buffer)
    except (OSError, EOFError, ValueError, TypeError):
        # Never print capabilities, native messages, browser text or protocol error bodies.
        sys.exit(1)


if __name__ == "__main__":
    main()
