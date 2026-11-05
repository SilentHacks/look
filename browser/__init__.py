"""Chrome DevTools Protocol (CDP) session and Shadow-DOM HUD overlay."""

from __future__ import annotations

from .cdp_bridge import CDPBridge, get_shared_bridge

__all__ = [
    "CDPBridge",
    "get_shared_bridge",
]
