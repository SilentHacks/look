"""Slash-command (`/gaze`) and `hermes gaze` CLI subcommand wiring for hermes-gaze."""

from __future__ import annotations

import argparse
import time

from . import service
from .benchmark.run_benchmark import format_benchmark_markdown, run_benchmark_suite
from .browser.cdp_bridge import get_shared_session, launch_chrome_with_cdp
from .config import GazeConfig
from .server import get_shared_server
from .tools import handle_gaze_resolve


def _config() -> GazeConfig:
    return service._CONFIG or GazeConfig()


def _handle_slash_command(raw_args: str) -> str:
    argv = (raw_args or "").strip().split()
    sub = argv[0].lower() if argv else "status"
    session = get_shared_session()

    if sub == "demo":
        cfg = _config()
        server = get_shared_server()
        server.start()
        url = f"http://{server.host}:{server.port}/"
        if not session.is_chrome_reachable() or not session.is_mic_capture_working():
            try:
                session.eval_js("window.close();")
            except Exception:
                pass
            launch_chrome_with_cdp(url)
            for _ in range(20):
                if session.is_chrome_reachable():
                    break
                time.sleep(0.25)
        session.configure(
            mode=session.tracker.mode,
            sigma_px=session.tracker.sigma_px,
            dwell_ms=cfg.dwell_ms,
            wiggle_trigger=cfg.wiggle_trigger,
            hotkey=cfg.hotkey,
            candidate_radius_px=380,
        )
        return f"Launched Chrome with CDP (:9222) and injected Hermes Gaze HUD on {url}"

    if sub == "mode" and len(argv) >= 2:
        mode = argv[1].lower()
        if mode not in ("hover", "simulated"):
            return "Usage: /gaze mode {hover|simulated}"
        session.configure(mode=mode)
        return f"Hermes Gaze mode set to '{mode}' (sigma={session.tracker.sigma_px}px)."

    if sub == "benchmark":
        return format_benchmark_markdown(run_benchmark_suite(trials_per_sigma=60))

    if sub == "resolve":
        utt = " ".join(argv[1:]) or "What happens if I press this?"
        return handle_gaze_resolve({"utterance": utt})

    if sub in ("listen", "voice"):
        return handle_gaze_resolve({"record_voice": True, "duration_s": 2.8})

    return (
        "Hermes Gaze ('Telepathy') Status:\n"
        f"  Chrome CDP (:9222) Connected : {session.is_chrome_reachable()}\n"
        f"  Active Pointing Mode         : {session.tracker.mode} (sigma={session.tracker.sigma_px}px)\n"
        f"  Online Drift Bias Offset     : {session.recalibrator.offset}\n\n"
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
    p_demo.add_argument("--mode", choices=("hover", "simulated"), default="hover")
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
        session = get_shared_session()
        session.tracker.mode = args.mode
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
