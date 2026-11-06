"""Hermes Gaze ("Telepathy") — Multimodal Deictic Reference Resolution for Chrome & Hermes Agent.

Registers:
- 5 tools: ``gaze_resolve``, ``gaze_choose``, ``gaze_highlight``, ``gaze_calibrate``, ``gaze_benchmark``
- 1 hook: ``pre_llm_call`` (auto-injects resolved DOM candidates when deictic pronouns are used)
- In-session slash command ``/gaze`` and CLI subcommand ``hermes gaze``
- Bundled skill ``gaze-telepathy``

Transport: ONE persistent CDP websocket per pinned Chrome tab; the overlay ->
Python channel is a ``Runtime.addBinding`` intent channel (browser/cdp_bridge.py),
not HTTP — the local demo server only serves the page + read-only status.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from . import service
from .browser.cdp_bridge import get_shared_session
from .cli import _handle_slash_command, _run_cli, _setup_cli
from .config import GazeConfig
from .resolver.temporal_aligner import has_deictic_pronoun
from .server import get_shared_server
from .tools import ALL_TOOLS, check_gaze_requirements

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent
_SKILL_PATH = _PLUGIN_DIR / "skills" / "gaze-telepathy" / "SKILL.md"


def _on_pre_llm_call(user_message: Any = "", **kwargs: Any) -> Optional[Dict[str, str]]:
    """When the user types or speaks a deictic pronoun ('this', 'these', 'that') while Chrome is connected,
    resolve the top candidate(s) and inject a structured [gaze_ref] block into the turn context."""
    text = user_message if isinstance(user_message, str) else str(user_message or "")
    if not text or not has_deictic_pronoun(text):
        return None

    session = get_shared_session()
    # Gate on the overlay being live — never lazily connect/inject here, or a stray
    # "this"/"it" in chat would hijack whatever page happens to be pages[0].
    if not session.overlay_is_live():
        return None

    try:
        res = service.resolve_now(session, utterance=text)
        ranked = res.get("ranked") or []
        if res.get("ok") is False or not ranked:
            return None
        context_block = (
            f"{res.get('context', '[gaze_ref]')}\n"
            f"Utterance: {text}\n"
            f"Intent: {res.get('intent_class')} | Decision: {res.get('decision')}\n"
            "Use gaze_highlight to display the answer or gaze_choose to confirm an action."
        )
        return {"context": context_block}
    except Exception as exc:
        logger.debug("hermes-gaze pre_llm_call resolution skipped: %s", exc)
        return None


def register(ctx: Any) -> None:
    """Entry point invoked by Hermes PluginManager."""
    cfg = GazeConfig.from_ctx(ctx)

    session = get_shared_session()
    session.cdp_http_url = cfg.cdp_url
    session.configure(
        mode=cfg.mode,
        sigma_px=cfg.sigma_px,
        dwell_ms=cfg.dwell_ms,
        wiggle_trigger=cfg.wiggle_trigger,
        hotkey=cfg.hotkey,
    )
    service.set_runtime(cfg, llm=getattr(ctx, "llm", None))

    # The CDP intent handler and the demo HTTP server run on bare threads serving
    # machine-scoped resources (Chrome :9222, the :9111 demo page) — they read no
    # per-profile Hermes state at runtime, so no profile binding is needed.
    session.cdp.set_intent_handler(service.handle_intent)
    get_shared_server().start()

    # Pre-warm the CoreML/ANE STT runner on a daemon thread — the first load
    # pays a one-time ~31s ANE compile; better here than on the first utterance.
    from .voice import prewarm

    prewarm()

    for name, schema, handler, emoji in ALL_TOOLS:
        ctx.register_tool(
            name=name,
            toolset="hermes_gaze",
            schema=schema,
            handler=handler,
            check_fn=check_gaze_requirements,
            description=schema["description"],
            emoji=emoji,
        )

    # Phase 0 is opt-in: only /gaze probe turns receive its hardcoded fixture.
    from .phase0 import PhaseZeroProbe

    probe = PhaseZeroProbe(ctx, session)

    def pre_llm_call(**kwargs: Any) -> Any:
        result = probe.pre(**kwargs)
        return result if result is not None else _on_pre_llm_call(**kwargs)

    def gaze_command(raw_args: str, **kwargs: Any) -> str:
        if raw_args.strip().split(maxsplit=1)[:1] == ["probe"]:
            return probe.command(raw_args.strip()[5:].strip(), **kwargs)
        return _handle_slash_command(raw_args)

    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("on_stream_delta", probe.delta)
    ctx.register_hook("post_llm_call", probe.post)
    ctx.register_hook("post_tool_call", probe.tool)
    ctx.register_command(
        "gaze",
        handler=gaze_command,
        description="Control Hermes Gaze ('Telepathy'): launch demo, switch hover/gaze mode, or run benchmarks.",
        args_hint="[status|demo|mode|resolve|benchmark|probe]",
    )
    ctx.register_cli_command(
        name="gaze",
        help="Hermes Gaze ('Telepathy') browser overlay, demo launcher, and accuracy benchmark",
        setup_fn=_setup_cli,
        handler_fn=_run_cli,
        description="Point with your eyes or cursor, command with your voice in Google Chrome.",
    )
    if _SKILL_PATH.is_file():
        ctx.register_skill(
            name="gaze-telepathy",
            path=_SKILL_PATH,
            description="Resolve deictic pronouns ('this', 'these', 'that') in Chrome via pointer/gaze + DOM semantics.",
        )

    ctx.on_unload(session.close)
    ctx.on_unload(lambda: get_shared_server().stop())
