"""Allowlisted environments for local workers and owned desktop processes."""
from __future__ import annotations

import os
import sys


_BASE = (
    "PATH", "HOME", "TMPDIR", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE",
    "LC_COLLATE", "LC_MESSAGES", "LC_MONETARY", "LC_NUMERIC", "LC_TIME",
)
# Linux Chrome needs the display, X11 credentials and desktop portal/session bus.
_DESKTOP = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")


def minimal_env(*, desktop: bool = False) -> dict[str, str]:
    keys = _BASE + _DESKTOP if desktop and sys.platform.startswith("linux") else _BASE
    return {key: os.environ[key] for key in keys if key in os.environ}
