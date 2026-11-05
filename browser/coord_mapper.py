"""macOS Global Screen <-> Chrome Viewport <-> Scroll-Invariant Document coordinate transforms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class ViewportGeometry:
    """Window and viewport metrics queried from Chrome."""

    screen_x: float = 0.0
    screen_y: float = 0.0
    outer_width: float = 1440.0
    outer_height: float = 900.0
    inner_width: float = 1440.0
    inner_height: float = 820.0
    scroll_x: float = 0.0
    scroll_y: float = 0.0
    dpr: float = 2.0

    @property
    def chrome_top_offset(self) -> float:
        return max(0.0, self.outer_height - self.inner_height)


def screen_to_viewport(
    x_screen: float,
    y_screen: float,
    geom: ViewportGeometry,
) -> Tuple[float, float]:
    """Convert macOS global logical screen coordinates into Chrome CSS viewport coordinates."""
    x_vp = x_screen - geom.screen_x
    y_vp = y_screen - (geom.screen_y + geom.chrome_top_offset)
    return (x_vp, y_vp)


def viewport_to_document(
    x_vp: float,
    y_vp: float,
    geom: ViewportGeometry,
) -> Tuple[float, float]:
    """Convert Chrome CSS viewport coordinates into scroll-invariant document coordinates."""
    return (x_vp + geom.scroll_x, y_vp + geom.scroll_y)
