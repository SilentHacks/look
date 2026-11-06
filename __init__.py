"""Hermes Gaze ("Telepathy") — Multimodal Deictic Reference Resolution for Chrome & Hermes Agent.

Registers:
- 6 tools, including current-snapshot highlight and guarded click.
- Session-bound voice context, streaming answer hooks, and turn lifecycle hooks.
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
from .resolver.cursor_context import EVIDENCE_RULES, TOOL_RULES
from .resolver.temporal_aligner import has_deictic_pronoun
from .server import get_shared_server
from .tools import ALL_TOOLS, check_gaze_requirements

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent
_SKILL_PATH = _PLUGIN_DIR / "skills" / "gaze-telepathy" / "SKILL.md"


def _on_pre_llm_call(user_message: Any = "", **kwargs: Any) -> Optional[Dict[str, str]]:
    """Attach current cursor evidence (or simulated resolution) for typed deictics."""
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
        if res.get("mode") == "hover" and res.get("ok"):
            handles = list(dict.fromkeys(p["id"] for p in res.get("pointed", [])
                                         if p.get("available") and p.get("id")))
            if handles:
                session.actions.highlight(handles, res["resolution_id"])
        return {"context": res["context"]} if res.get("context") else None
    except Exception as exc:
        logger.debug("hermes-gaze pre_llm_call resolution skipped: %s", exc)
        return None


def register(ctx: Any) -> None:
    """Entry point invoked by Hermes PluginManager."""
    cfg = GazeConfig.from_ctx(ctx)
    rules = EVIDENCE_RULES + TOOL_RULES
    ctx.register_system_prompt_section("hermes_gaze", rules, position="after_memory", max_chars=800)

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

    from .voice_turns import VoiceTurns

    turns = VoiceTurns(ctx, session)
    service.set_voice_turns(turns)

    def pre_llm_call(**kwargs: Any) -> Any:
        with turns.lock:
            if turns.binding and turns.binding["session_id"] == kwargs.get("session_id"):
                return turns.pre(**kwargs)
        return _on_pre_llm_call(**kwargs)

    def gaze_command(raw_args: str, **kwargs: Any) -> str:
        if raw_args.strip() in ("", "connect", "start"):
            result = _handle_slash_command("start")
            if not session.cdp.is_connected:
                return result
            return (result + "\n" + turns.bind("connect", **kwargs)
                    + "\nFresh Hermes sessions still need one normal Hermes message before Chrome turns.")
        if raw_args.strip() == "disconnect":
            session.microphone.cancel()
            return turns.bind("disconnect", **kwargs)
        bound = turns.bind("", **kwargs)
        result = _handle_slash_command(raw_args)
        return result + "\n" + bound

    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("on_stream_delta", turns.delta)
    ctx.register_hook("post_llm_call", turns.post)
    ctx.register_hook("on_session_end", turns.end)
    ctx.register_command(
        "gaze",
        handler=gaze_command,
        description="Connect this Hermes session to Chrome voice, control pointing, or launch the demo.",
        args_hint="[connect|start|disconnect|status|demo|mode|resolve|listen|benchmark]",
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
    ctx.on_unload(turns.close)
    ctx.on_unload(lambda: get_shared_server().stop())
