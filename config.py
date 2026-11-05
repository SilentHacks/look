"""Plugin configuration for hermes-gaze, populated from ``ctx.get_config`` (plugin.yaml defaults)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GazeConfig:
    """User-configurable plugin settings (mirrors ``config_schema`` in plugin.yaml)."""

    mode: str = "hover"
    sigma_px: float = 120.0
    cdp_url: str = "http://127.0.0.1:9222"
    dwell_ms: int = 450
    wiggle_trigger: bool = True
    hotkey: str = "AltRight"  # JS KeyboardEvent.code (e.g. "AltRight", "Backquote", "F8")
    whisper_model: str = "base.en"

    @classmethod
    def from_ctx(cls, ctx: Any) -> "GazeConfig":
        """Build a GazeConfig from the plugin ctx; falls back to defaults per key."""
        get = getattr(ctx, "get_config", None)
        if not callable(get):
            return cls()
        return cls(
            mode=str(get("mode", cls.mode) or cls.mode),
            sigma_px=float(get("sigma_px", cls.sigma_px) or cls.sigma_px),
            cdp_url=str(get("cdp_url", cls.cdp_url) or cls.cdp_url),
            dwell_ms=int(get("dwell_ms", cls.dwell_ms) or cls.dwell_ms),
            wiggle_trigger=bool(get("wiggle_trigger", cls.wiggle_trigger)),
            hotkey=str(get("hotkey", cls.hotkey) or cls.hotkey),
            whisper_model=str(get("whisper_model", cls.whisper_model) or cls.whisper_model),
        )
