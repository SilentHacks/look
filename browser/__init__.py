"""Chrome DevTools Protocol (CDP) bridge, coordinate mapper, and Shadow-DOM HUD overlay."""

from __future__ import annotations

from .cdp_bridge import CDPBridge, get_shared_bridge
from .coord_mapper import ViewportGeometry, screen_to_viewport, viewport_to_document

__all__ = [
    "CDPBridge",
    "ViewportGeometry",
    "get_shared_bridge",
    "screen_to_viewport",
    "viewport_to_document",
]
