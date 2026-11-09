"""Look — private browser evidence and guarded actions for Chrome and Hermes.

Registers:
- 14 tools, including bounded browser structure and guarded general actions.
- Session-bound voice context, streaming answer hooks, and turn lifecycle hooks.
- In-session ``/look`` and CLI ``hermes look`` (``gaze`` compatibility aliases)
- Bundled skill ``gaze-telepathy``

Transport: ONE persistent CDP websocket per pinned Chrome tab; the overlay ->
Python channel is a ``Runtime.addBinding`` intent channel (browser/cdp_bridge.py),
not HTTP — the local demo server only serves the page + read-only status.
"""

from __future__ import annotations

from contextvars import copy_context
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

    # Transport threads own machine-scoped resources. VoiceTurns separately retains
    # the connecting command's profile context for optional secret resolution.
    session.cdp.set_intent_handler(service.handle_intent)
    get_shared_server().start()

    # Warm supported verified caches only; fetching requires explicit /look setup.
    from .voice import prewarm

    prewarm(cfg.whisper_model)

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
    try:
        from hermes_constants import get_hermes_home
        native_home = Path(get_hermes_home()).resolve()
    except ImportError:
        native_home = None

    def pre_llm_call(**kwargs: Any) -> Any:
        with turns.lock:
            blocked = turns.guard_wire(**kwargs)
            if blocked:
                return blocked
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
        command = " ".join(raw_args.strip().lower().split())
        if command == "setup":
            post = getattr(ctx, "post_message", None)
            context = copy_context()
            report = (lambda text: context.run(post, text)) if callable(post) else None
            return _first_run_guide(session, report=report)
        if command in ("stop", "disconnect"):
            # Resources are machine-scoped, so Stop also releases another session's binding.
            # Keep host admission ownership until its real terminal hook arrives.
            with turns.lock:
                turns._disconnect()
                speech_worker = turns._speech_thread
            result = _handle_slash_command("stop")
            if speech_worker is not None:
                speech_worker.join(1)
                if speech_worker.is_alive():
                    result += "\nRead aloud is still stopping."
            return result
        bind_only = command in ("calibrate", "mode webcam", "setup eyes", "demo")
        if (bind_only or command in ("", "connect", "start") or
                command.split()[:1] in (["start"], ["connect"]) and
                command.split()[1:] in (["--existing"], ["--existing", "--accept"], ["--extension"], ["--separate"])):
            if not kwargs.get("session_id") or not kwargs.get("session_key"):
                return "Run /look start in a live Hermes conversation."
            secret_context = copy_context()
            with turns.lock:
                generation = turns.binding_generation
            native = None
            if kwargs.get("platform") == "local":
                from .native_input import NativeError, NativeInput, consent
                source = kwargs.get("source")
                logical_id = getattr(source, "chat_id", "")
                if not native_home or not logical_id:
                    return "Native Look input needs the canonical local command's profile and source. Use Hermes input."
                with turns.lock:
                    active = turns.active
                    if active and (active["session_id"] != kwargs["session_id"] or
                                   active["session_key"] != kwargs["session_key"]):
                        return "A Look question still has an unresolved outcome. Reconnect its original conversation."
                    previous = turns.connecting_native or turns.native_input
                if (previous is not None and previous.logical_id == logical_id
                        and turns.owner_session == kwargs["session_id"]
                        and previous.reader is not None and not previous.reader.done()
                        and not previous.closed and not previous.receipt_admission
                        and not (active and active.get("outcome_unknown"))):
                    native = previous
                else:
                    receipt_admission = (active.get("admission_id", "") if active and previous
                                         and not consent(native_home, ctx.plugin_id) else "")
                    native = NativeInput(native_home, ctx.plugin_id, logical_id,
                                         identity=previous.identity if previous and active else None,
                                         receipt_admission=receipt_admission)
                    try:
                        native.open()
                    except NativeError as exc:
                        return str(exc)
                    with turns.lock:
                        if turns.closed or turns.binding_generation != generation:
                            native.close()
                            return "Look start was cancelled."
                        turns.connecting_native = native
                    if previous is not None:
                        previous.close()
                    with turns.lock:
                        if turns.closed or turns.binding_generation != generation or native.closed:
                            native.close()
                            return "Look start was cancelled."
                        if native.receipt_admission:
                            turns.connecting_native = None
                            turns._disconnect()  # Observation must not restore input/action authority.
                            turns.native_input = native
                            native.on_disconnect = turns.native_disconnected
                        if active is not None and turns.active is active:
                            active["native_input"] = native
                            native.submit(active, turns.native_receipt)
                        elif native.receipt_admission:
                            native.close()
                    if native.receipt_admission:
                        return "Checking the saved question. Restore this profile’s Look input permission before starting again."
            requested_source = ("existing" if "--existing" in command else
                                "extension" if "--extension" in command else
                                "owned" if "--separate" in command else session.cdp.source)
            def ready():
                with turns.lock:
                    if (not turns.closed and turns.binding_generation == generation
                            and session.cdp.source == requested_source and
                            (native is None or not native.closed and native.reader is not None
                             and not native.reader.done())):
                        turns.connecting_native = None
                        if native is not None:
                            native.on_disconnect = turns.native_disconnected
                        turns.bind("connect", native_input=native, _secret_context=secret_context, **kwargs)
                        return bool(turns.binding and turns.binding["session_id"] == kwargs["session_id"]
                                    and turns.binding["session_key"] == kwargs["session_key"]
                                    and turns.native_input is native)
                    elif native is not None and native is not turns.native_input:
                        native.close()
                    return False
            def failed(text):
                with turns.lock:
                    if (turns.closed or turns.binding_generation != generation
                            or session.cdp.source != requested_source):
                        return
                    if native is not None and native is not turns.native_input:
                        if turns.connecting_native is native:
                            turns.connecting_native = None
                        native.close()
                    post = getattr(ctx, "post_message", None)
                    if callable(post):
                        secret_context.run(post, text)
            # Serialize launch with the companion's existing Stop boundary. The original
            # generation is never refreshed after auth, even if Stop closed the new client.
            with session.cdp._lifecycle:
                if (turns.closed or turns.binding_generation != generation or
                        native is not None and (native.closed or native.reader is None or native.reader.done())):
                    if native is not None and native is not turns.native_input:
                        native.close()
                    return "Look start was cancelled."
                if bind_only:
                    if not ready():
                        return "Look start was cancelled."
                    return _handle_slash_command(raw_args)
                result = (_handle_slash_command(command, on_ready=ready, on_error=failed)
                          if "--existing" in command or "--extension" in command else _handle_slash_command(command or "start"))
            if (command.endswith(("--existing", "--extension")) or session.cdp.source != requested_source
                    or not session.cdp.is_connected):
                return result  # Disclosure/refused source changes never bind the old browser.
            ready()
            if native is None:
                result += "\nThis frontend uses untracked Look input. If no answer arrives, check the conversation in Hermes; do not resend automatically."
            from .voice import recognition_ready, recognition_status
            if not recognition_ready(cfg.whisper_model):
                result += "\n" + recognition_status(cfg.whisper_model)
            return result
        result = _handle_slash_command(raw_args)
        if command == "status" and session.cdp.is_connected:
            with turns.lock:
                if not turns.connected:
                    result += "\n/look start to connect this conversation."
                elif turns.binding["session_id"] != kwargs.get("session_id"):
                    result += "\nConnected to another conversation. /look start to use this one."
        return result

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
        with turns.lock:
            return bool(turns.binding and turns.binding["session_id"] == session_id or
                        turns.active and turns.active.get("native_input") is not None and
                        turns.active["session_id"] == session_id)

    def pre_tool_call(tool_name="", args=None, session_id="", turn_id="", **kwargs):
        if not bound(session_id):
            return None
        if not safe_call(tool_name, args):
            return {"action": "block", "message": "Look uses guarded browser tools. Run /look stop before using code or generic browser tools."}
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
    ctx.register_hook("on_session_reset", turns.session_changed)
    ctx.register_hook("post_compaction", turns.session_changed)
    for name in ("look", "gaze"):
        ctx.register_command(
            name,
            handler=gaze_command,
            description="Start or stop Look in Chrome." if name == "look" else "Compatibility alias for /look.",
            args_hint="[start|stop|status|calibrate|cursor|setup|diagnostics|help]",
        )
        ctx.register_cli_command(
            name=name,
            help="Look: private questions and guarded actions in Chrome" if name == "look" else "Alias for hermes look",
            setup_fn=_setup_cli,
            handler_fn=_run_cli,
            description="Use /look inside Hermes to start or stop the companion.",
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
