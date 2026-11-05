"""Chrome DevTools Protocol (CDP) session and Shadow-DOM HUD overlay."""

from __future__ import annotations

from .cdp_bridge import CdpSession, GazeSession, get_shared_session

__all__ = [
    "CdpSession",
    "GazeSession",
    "get_shared_session",
]
