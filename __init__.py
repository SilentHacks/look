"""Hermes Gaze ("Telepathy") — Multimodal Deictic Reference Resolution for Chrome & Hermes Agent.

Registers:
- 14 tools, including bounded browser structure and guarded general actions.
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
from .cli import _first_run_guide, _handle_slash_command, _run_cli, _setup_cli
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
            service.start_question_highlight(session, res)
        return {"context": res["context"]} if res.get("context") else None
    except Exception as exc:
        logger.debug("hermes-gaze pre_llm_call resolution skipped: %s", exc)
        return None


def register(ctx: Any) -> None:
    """Entry point invoked by Hermes PluginManager."""
    cfg = GazeConfig.from_ctx(ctx)
    rules = EVIDENCE_RULES + TOOL_RULES
    ctx.register_system_prompt_section("hermes_gaze", rules, position="after_memory", max_chars=2200)

    session = get_shared_session()
    session.cdp_http_url = cfg.cdp_url
    session.configure(
        mode=cfg.mode,
        sigma_px=cfg.sigma_px,
        dwell_ms=cfg.dwell_ms,
        wiggle_trigger=cfg.wiggle_trigger,
        hotkey=cfg.hotkey,
        answer_turn_seconds=cfg.answer_turn_seconds,
    )
    service.set_runtime(cfg, llm=getattr(ctx, "llm", None))

    # The CDP intent handler and the demo HTTP server run on bare threads serving
    # machine-scoped resources (owned Chrome and the :9111 demo page) — they read no
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
    answer_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    initialized_sessions: set[str] = set()
    guide_shown = False

    def pre_llm_call(**kwargs: Any) -> Any:
        if kwargs.get("session_id"):
            initialized_sessions.add(kwargs["session_id"])
        with turns.lock:
            if turns.binding and turns.binding["session_id"] == kwargs.get("session_id"):
                result = turns.pre(**kwargs)
            else:
                result = _on_pre_llm_call(**kwargs)
            snapshot = session.last_hover_snapshot
            if turns.active:
                early = turns.active["snapshot"].get("early_highlight")
                if early and result:
                    snapshot = early.snapshot
            if result and snapshot and (snapshot.get("early_highlight") or
                    turns.active and turns.active["turn_id"] == kwargs.get("turn_id") or
                    result.get("context") == snapshot.get("context")):
                key = (kwargs.get("session_id", ""), kwargs.get("turn_id", ""))
                answer_snapshots[key] = snapshot
                while len(answer_snapshots) > 128:
                    answer_snapshots.pop(next(iter(answer_snapshots)))
            return result

    def post_llm_call(**kwargs: Any) -> None:
        body = turns.post(**kwargs)
        with turns.lock:
            snapshot = answer_snapshots.pop((kwargs.get("session_id", ""), kwargs.get("turn_id", "")), None)
        if snapshot:
            service.highlight_answer_scope(session, snapshot,
                                           body if body is not None else kwargs.get("assistant_response", ""))

    def gaze_command(raw_args: str, **kwargs: Any) -> str:
        nonlocal guide_shown
        command = raw_args.strip().lower()
        state = getattr(ctx, "state", None)
        if command == "" and not guide_shown and state is not None:
            try:
                guide_shown = state.get("first_run_shown", False) is True
            except (OSError, RuntimeError):
                logger.debug("Could not read first-run guide state", exc_info=True)
        if command == "setup" or command == "" and not guide_shown:
            result = _first_run_guide(session, initialized=kwargs.get("session_id") in initialized_sessions)
            guide_shown = True
            if state is not None:
                try:
                    state.set("first_run_shown", True)
                except (OSError, RuntimeError):
                    logger.debug("Could not save first-run guide state", exc_info=True)
            return result
        if raw_args.strip() in ("", "connect", "start"):
            result = _handle_slash_command("start")
            if not session.cdp.is_connected:
                return result
            return (result + "\n" + turns.bind("connect", **kwargs)
                    + "\nFresh Hermes sessions still need one normal Hermes message before Chrome turns.")
        if raw_args.strip() == "timing":
            return _handle_slash_command(raw_args)
        if raw_args.strip() == "disconnect":
            session.microphone.cancel()
            session.stop_webcam()
            return turns.bind("disconnect", **kwargs)
        bound = turns.bind("", **kwargs)
        result = _handle_slash_command(raw_args)
        return result + "\n" + bound

    # Restrict the connected companion session, not unrelated Hermes sessions.
    # Raw code/debugger tools can mint trusted CDP clicks; hooks cannot sandbox them.
    safe_names = {name for name, _, _, _ in ALL_TOOLS
                  if name not in ("gaze_calibrate", "gaze_benchmark")} | {"web_search", "web_extract", "memory"}
    bridge_names = {"tool_describe", "tool_call"}

    def safe_call(name, args):
        if name == "tool_describe":
            names = args.get("names") if isinstance(args, dict) else None
            return (isinstance(names, list) and bool(names) and
                    all(isinstance(tool, str) and tool in safe_names for tool in names))
        if name != "tool_call":
            return name in safe_names or name in bridge_names
        calls = args.get("calls") if isinstance(args, dict) else None
        return (isinstance(calls, list) and len(calls) == 1 and
                isinstance(calls[0], dict) and isinstance(calls[0].get("name"), str) and calls[0]["name"] in safe_names)

    def bound(session_id):
        return bool(turns.binding and turns.binding["session_id"] == session_id)

    def pre_tool_call(tool_name="", args=None, session_id="", turn_id="", **kwargs):
        if not bound(session_id):
            return None
        if not safe_call(tool_name, args):
            return {"action": "block", "message": "Companion session uses guarded gaze tools only. Disconnect /gaze before using code or browser tools."}
        return None

    def tool_execution(next_call, tool_name="", args=None, session_id="", turn_id="", **kwargs):
        if not bound(session_id):
            return next_call()
        if not safe_call(tool_name, args):
            return '{"ok":false,"executed":false,"error":"Use guarded companion tools only"}'
        session.tasks.authorize_call(session_id, turn_id)
        try:
            return next_call()
        finally:
            session.tasks.clear_call()

    def llm_request(request, session_id="", **kwargs):
        if not bound(session_id):
            return None
        # Keep Hermes's assembled, provider-native surface and executable names in sync.
        # Deferred gaze tools use the normal guarded tool_call bridge, never ghost schemas.
        def allowed(tool):
            definition = tool.get("function", tool.get("toolSpec", tool))
            return definition.get("name") in safe_names | bridge_names

        result = dict(request)
        if "toolConfig" in request:  # Bedrock Converse
            config = dict(request["toolConfig"])
            config["tools"] = [tool for tool in config.get("tools", []) if allowed(tool)]
            choice = config.get("toolChoice", {}).get("tool", {}).get("name")
            if choice and choice not in safe_names | bridge_names:
                config.pop("toolChoice", None)
            if config["tools"]:
                result["toolConfig"] = config
            else:
                result.pop("toolConfig")
        elif "tools" in request:  # Chat Completions, Responses and Anthropic
            result["tools"] = [tool for tool in request["tools"] if allowed(tool)]
            choice = request.get("tool_choice")
            if isinstance(choice, dict):
                choice_name = choice.get("function", choice).get("name")
                if choice_name and choice_name not in safe_names | bridge_names:
                    result.pop("tool_choice", None)
            if not result["tools"]:
                result.pop("tools")
                result.pop("tool_choice", None)
        return {"request": result}

    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_middleware("llm_request", llm_request)
    ctx.register_middleware("tool_execution", tool_execution)

    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("on_stream_delta", turns.delta)
    ctx.register_hook("post_llm_call", post_llm_call)
    ctx.register_hook("on_session_end", turns.end)
    ctx.register_command(
        "gaze",
        handler=gaze_command,
        description="Connect Chrome, reopen the first-run guide, or control pointing.",
        args_hint="[setup|connect|start|disconnect|status|demo|mode|calibrate|tracker|resolve|listen|benchmark]",
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
