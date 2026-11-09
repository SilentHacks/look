"""Look's explicit macOS development native host. No Hermes imports or HTTP listener."""
from __future__ import annotations

import argparse
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

NAME = "org.look.companion"
MAX_MESSAGE = 768 * 1024  # Below Chrome's 1 MiB native-host output ceiling.
ID = re.compile(r"[a-p]{32}")
TICKET = re.compile(r"([0-9a-f]{24})\.([0-9a-f]{64})")


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
    if not ID.fullmatch(config.get("extension_id", "")):
        raise ValueError("Look extension ID is invalid")
    return config


def install(extension_id, *, directory=None, manifests=None):
    if not ID.fullmatch(extension_id):
        raise ValueError("Expected the exact 32-letter Chrome extension ID")
    directory = private_directory(directory or install_directory())
    manifests = Path(manifests or manifest_directory())
    manifests.mkdir(parents=True, exist_ok=True)
    # Refuse to replace another host. Explicit uninstall is required before relocation/update.
    paths = [directory / "config.json", directory / "host", manifests / (NAME + ".json")]
    if any(p.exists() or p.is_symlink() for p in paths):
        raise ValueError("Look native host already exists; uninstall it before installing again")
    values = [json.dumps({"extension_id": extension_id}),
              "#!/bin/sh\nexec " + shlex.join([sys.executable, str(Path(__file__).resolve()),
                                             "--config", str(paths[0])]) + ' "$@"\n',
              json.dumps(dict(name=NAME, description="Look browser companion", path=str(paths[1]),
                              type="stdio", allowed_origins=[f"chrome-extension://{extension_id}/"]))]
    created = []
    try:
        for path, value in zip(paths, values):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700 if path == paths[1] else 0o600)
            created.append(path)
            with os.fdopen(fd, "w") as output:
                output.write(value)
    except BaseException:
        for path in reversed(created):
            path.unlink()
        raise
    return paths[-1]


def uninstall(*, directory=None, manifests=None):
    directory = directory or install_directory()
    manifest = (manifests or manifest_directory()) / (NAME + ".json")
    # Delete only our exact registration and two launcher files, never any browser directory.
    if manifest.exists():
        value = json.loads(manifest.read_text())
        if value.get("name") != NAME or value.get("path") != str(directory / "host"):
            raise ValueError("Native registration belongs to a different Look install")
        manifest.unlink()
    for name in ("host", "config.json"):
        (directory / name).unlink(missing_ok=True)


def relay(extension_id, origin, source, destination):
    if origin != f"chrome-extension://{extension_id}/":
        raise ValueError("Chrome extension origin does not match Look's registration")
    first = read_message(source)
    ticket = TICKET.fullmatch(first.get("ticket", ""))
    if first.get("op") != "pair" or not ticket:
        raise ValueError("Start Look in Hermes and enter its current pairing ticket")
    path = runtime_directory() / (ticket[1] + ".sock")
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Look session socket is not private")
    peer = socket.socket(socket.AF_UNIX)
    try:
        peer.settimeout(5)
        peer.connect(str(path))
        stream = peer.makefile("rwb", buffering=0)
        send_message(stream, dict(op="pair", ticket=first["ticket"], extension_id=extension_id))
        answer = read_message(stream)
        if answer.get("op") != "paired" or not isinstance(answer.get("generation"), str):
            raise ValueError("Look refused pairing; start a fresh connection in Hermes")
        send_message(destination, answer)
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
    finally:
        peer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action_or_origin", nargs="?")
    parser.add_argument("--extension-id")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.action_or_origin in ("install", "uninstall"):
        if sys.platform != "darwin":
            parser.error("The development installer supports Google Chrome on macOS only")
        if args.action_or_origin == "install":
            print(install(args.extension_id or ""))
        else:
            uninstall()
            print("Look native host removed. Remove the unpacked extension in chrome://extensions.")
        return
    try:
        config = configuration(args.config.parent if args.config else None)
        relay(config["extension_id"], args.action_or_origin, sys.stdin.buffer, sys.stdout.buffer)
    except (OSError, EOFError, ValueError, TypeError):
        # Never print tickets, native messages, browser text or protocol error bodies.
        sys.exit(1)


if __name__ == "__main__":
    main()
