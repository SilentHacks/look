"""Hermes Gaze ("Telepathy") — Multimodal Deictic Reference Resolution for Chrome & Hermes Agent.

Registers:
- 5 tools: ``gaze_resolve``, ``gaze_choose``, ``gaze_highlight``, ``gaze_calibrate``, ``gaze_benchmark``
- 1 hook: ``pre_llm_call`` (auto-injects resolved DOM candidates when deictic pronouns are used)
- In-session slash command ``/gaze`` and CLI subcommand ``hermes gaze``
- Bundled skill ``gaze-telepathy``
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .benchmark.run_benchmark import format_benchmark_markdown, run_benchmark_suite
from .browser.cdp_bridge import get_shared_bridge, launch_chrome_with_cdp
from .resolver.bayesian_fusion import resolve_candidates
from .resolver.temporal_aligner import has_deictic_pronoun
from .tools import ALL_TOOLS, check_gaze_requirements, handle_gaze_resolve

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent
_SKILL_PATH = _PLUGIN_DIR / "skills" / "gaze-telepathy" / "SKILL.md"
_DEMO_PAGE_PATH = _PLUGIN_DIR / "benchmark" / "benchmark_page.html"


def _on_pre_llm_call(user_message: Any = "", **kwargs: Any) -> Optional[Dict[str, str]]:
    """When the user types or speaks a deictic pronoun ('this', 'these', 'that') while Chrome is connected,
    resolve the top candidate(s) and inject a structured [gaze_ref] block into the turn context."""
    import os

    if os.environ.get("HERMES_GAZE_INTERNAL") == "1":
        return None

    text = user_message if isinstance(user_message, str) else str(user_message or "")
    if not text or not has_deictic_pronoun(text):
        return None

    bridge = get_shared_bridge()
    if not bridge.is_chrome_reachable():
        return None

    try:
        now = time.time()
        candidates = bridge.fetch_live_state_and_candidates(radius_px=340.0)
        if not candidates:
            return None
        fixations = bridge.ring_buffer.snapshot(now)
        res = resolve_candidates(candidates, fixations, text, t_arm=now)
        bridge.render_resolution_in_browser(res)
        top_list = [sc.to_dict() for sc in res.ranked[:3]]
        context_block = (
            "[gaze_ref — Live Chrome Deictic Resolution]\n"
            f"Utterance: {text}\n"
            f"Intent Class: {res.intent_class} | Decision Policy: {res.decision}\n"
            f"Top Resolved DOM Candidates: {json.dumps(top_list, ensure_ascii=False)}\n"
            "Use `gaze_highlight` to display your answer in the Chrome HUD or `gaze_choose` to confirm a Lens card."
        )
        return {"context": context_block}
    except Exception as exc:
        logger.debug("hermes-gaze pre_llm_call resolution skipped: %s", exc)
        return None



def _handle_slash_command(raw_args: str) -> str:
    argv = (raw_args or "").strip().split()
    sub = argv[0].lower() if argv else "status"
    bridge = get_shared_bridge()

    if sub == "demo":
        from .tracker.voice_listener import get_shared_voice_server

        server = get_shared_voice_server()
        server.start()
        url = f"http://{server.host}:{server.port}/"
        if not bridge.is_chrome_reachable() or not bridge.is_mic_capture_working():
            try:
                bridge.eval_js("window.close();", inject_overlay=False)
            except Exception:
                pass
            launch_chrome_with_cdp(url)
            for _ in range(20):
                if bridge.is_chrome_reachable():
                    break
                time.sleep(0.25)
        bridge.inject_overlay(mode=bridge.tracker.mode, sigma_px=bridge.tracker.sigma_px)
        return f"Launched Chrome with CDP (:9222) and injected Hermes Gaze HUD on {url}"

    if sub == "mode" and len(argv) >= 2:
        mode = argv[1].lower()
        if mode not in ("hover", "simulated", "webcam"):
            return "Usage: /gaze mode {hover|simulated|webcam}"
        bridge.tracker.mode = mode
        bridge.inject_overlay(mode=mode, sigma_px=bridge.tracker.sigma_px)
        return f"Hermes Gaze mode set to '{mode}' (sigma={bridge.tracker.sigma_px}px)."

    if sub == "benchmark":
        return format_benchmark_markdown(run_benchmark_suite(trials_per_sigma=60))

    if sub == "resolve":
        utt = " ".join(argv[1:]) or "What happens if I press this?"
        return handle_gaze_resolve({"utterance": utt})

    if sub in ("listen", "voice"):
        return handle_gaze_resolve({"record_voice": True, "duration_s": 2.8})

    return (
        "Hermes Gaze ('Telepathy') Status:\n"
        f"  Chrome CDP (:9222) Connected : {bridge.is_chrome_reachable()}\n"
        f"  Active Pointing Mode         : {bridge.tracker.mode} (sigma={bridge.tracker.sigma_px}px)\n"
        f"  Online Drift Bias Offset     : {bridge.recalibrator.offset}\n\n"
        "Subcommands:\n"
        "  /gaze demo                   Launch Chrome on the interactive Analytics Dashboard demo page\n"
        "  /gaze listen                 Listen from microphone, transcribe speech, and resolve in Chrome\n"
        "  /gaze mode <hover|simulated> Switch between Magic Pointer hover and noisy gaze simulation\n"
        "  /gaze resolve <utterance>    Resolve a deictic phrase against the live Chrome tab\n"
        "  /gaze benchmark              Run quantitative accuracy benchmark across noise levels"
    )


def _setup_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="gaze_subcommand")
    subs.add_parser("status", help="Show Chrome CDP connection and tracker status")
    p_demo = subs.add_parser("demo", help="Launch Chrome (:9222) with the interactive Analytics & Comparison demo page")
    p_demo.add_argument("--mode", choices=("hover", "simulated", "webcam"), default="hover")
    p_listen = subs.add_parser("listen", help="Record speech from microphone, transcribe with faster-whisper, and resolve in Chrome")
    p_listen.add_argument("--duration", type=float, default=2.8, help="Recording duration in seconds")
    subs.add_parser("voice", parents=[p_listen], add_help=False, help="Alias for listen")
    p_bench = subs.add_parser("benchmark", help="Run quantitative accuracy benchmark across noise levels")
    p_bench.add_argument("--trials", type=int, default=60)
    p_res = subs.add_parser("resolve", help="Resolve a deictic utterance against the active Chrome tab")
    p_res.add_argument("utterance", nargs="+", help="Utterance such as 'What happens if I press this?'")
    subparser.set_defaults(func=_run_cli)


def _run_cli(args: argparse.Namespace) -> int:
    sub = getattr(args, "gaze_subcommand", None) or "status"
    if sub == "demo":
        bridge = get_shared_bridge()
        bridge.tracker.mode = args.mode
        print(_handle_slash_command("demo"))
        return 0
    if sub in ("listen", "voice"):
        dur = float(getattr(args, "duration", 2.8))
        print(f"🎙️ Listening from default microphone for {dur}s...")
        res = handle_gaze_resolve({"record_voice": True, "duration_s": dur})
        print(res)
        return 0
    if sub == "benchmark":
        print(format_benchmark_markdown(run_benchmark_suite(trials_per_sigma=args.trials)))
        return 0
    if sub == "resolve":
        utt = " ".join(args.utterance)
        print(handle_gaze_resolve({"utterance": utt}))
        return 0
    print(_handle_slash_command("status"))
    return 0


def register(ctx: Any) -> None:
    """Entry point invoked by Hermes PluginManager."""
    mode = str(ctx.get_config("mode", "hover") or "hover")
    sigma_px = float(ctx.get_config("sigma_px", 120.0) or 120.0)
    cdp_url = str(ctx.get_config("cdp_url", "http://127.0.0.1:9222") or "http://127.0.0.1:9222")

    bridge = get_shared_bridge()
    bridge.cdp_http_url = cdp_url.rstrip("/")
    bridge.tracker.mode = mode
    bridge.tracker.sigma_px = sigma_px

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

    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_command(
        "gaze",
        handler=_handle_slash_command,
        description="Control Hermes Gaze ('Telepathy'): launch demo, switch hover/gaze mode, or run benchmarks.",
        args_hint="[status|demo|mode|resolve|benchmark]",
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
