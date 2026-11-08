"""Slash-command (`/gaze`) and `hermes gaze` CLI subcommand wiring for hermes-gaze."""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
import platform
from pathlib import Path
from urllib.parse import urlparse

from . import service
from .benchmark.run_benchmark import format_benchmark_markdown, run_benchmark_suite
from .browser.cdp_bridge import get_shared_session, launch_chrome_with_cdp
from .config import GazeConfig
from .server import get_shared_server
from .tools import handle_gaze_resolve


def _config() -> GazeConfig:
    return service._CONFIG or GazeConfig()


def _first_run_guide(session, *, initialized: bool = False) -> str:
    """Passive checklist: no connection, model loading or device access."""
    from . import voice

    supported = platform.system() == "Darwin" and platform.machine() == "arm64"
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").is_file()
    modules = ("websockets", "numpy", "sounddevice", "faster_whisper", "parakeet_mlx", "CoreML",
               "ptts", "huggingface_hub")
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if voice._COREML_RUNNER is False:
        recognition = ("The preferred speech recognition model could not prepare. "
                       "A fallback will try on your first question and may need a download.")
    elif voice._COREML_RUNNER is None:
        recognition = ("Local speech recognition is preparing. The first download and preparation can take a while. "
                       "You can type a question while you wait.")
    else:
        recognition = "Local speech recognition is ready."
    return "\n".join((
        "Hermes Gaze first run",
        "Mac: Apple Silicon is supported." if supported else
        "Mac: use an Apple Silicon Mac for this beta.",
        "Chrome: standard Google Chrome is installed." if chrome else
        "Chrome: install Google Chrome in Applications, then run /gaze setup again.",
        "Dependencies: Python packages are present; this does not test audio devices." if not missing else
        "Dependencies: missing " + ", ".join(missing) + ". Quit Hermes, run hermes pm install, then "
        "hermes plugins enable hermes-gaze in your terminal and restart Hermes.",
        recognition,
        "Connection: Chrome is attached." if session.cdp.is_connected else
        "Connection: Chrome is not attached. Run /gaze connect when you are ready to open the companion.",
        "Hermes has received a normal message in this conversation." if initialized else
        "Hermes readiness is not confirmed. Send a normal message here, such as Reply only Ready. "
        "Wait for its answer, then run /gaze connect. Connecting alone cannot prepare a fresh conversation.",
        "Before connecting, set plugins.isolation to in_process and "
        "plugins.entries.hermes-gaze.allow_gateway_injection to true in Hermes config.yaml, then restart Hermes. "
        "This changes plugin isolation for Hermes; the guide never changes it for you.",
        "Launch Hermes from Terminal or another terminal app allowed in macOS System Settings, "
        "Privacy & Security, Microphone and Camera. Camera is only needed for eyes. "
        "Restart that app after changing permissions. Do not use T3 Code's terminal for camera setup.",
        "Your question and captured page context go to the model configured in Hermes and can stay in Hermes history. "
        "Local camera and speech recognition do not make the whole conversation local. "
        "Optional TypeSafe highlighting also receives your question and scope descriptions when configured; "
        "extra page text is off by default.",
        "Failed speech can remain in memory for retry until the plugin exits. "
        "A recognition fallback uses a temporary audio file, normally deleted afterward; "
        "a crash or failed deletion can leave it in the system temporary folder.",
        "Connected conversations use guarded browsing tools. /gaze disconnect restores ordinary Hermes tools.",
        "First cursor question: run /gaze mode hover after connecting. Open a page, or /gaze demo for practice. "
        "Point at something. Hold Space. Wait for Listening, then ask. Let go when you are done.",
        "Text fields and keyboard-focused page controls keep Space. Click ordinary page text first. "
        "A tap scrolls. Right Option opens typed questions without a microphone. "
        "Q recalls answers; Esc stops or dismisses; hold Space on an answer to follow up.",
        "Then try eye tracking, beta: /gaze mode webcam explicitly opens the separate camera window; "
        "/gaze calibrate opens calibration. Follow its check and practice guidance before asking with your eyes. "
        "Use one display and English; move the pointer once in each page and after resizing or zooming. "
        "Broad areas only, not precise controls. /gaze tracker stop returns to cursor.",
        "Read aloud is optional: quit Hermes and run hermes gaze setup-speech in your terminal to download "
        "the local voice without playing sound, then restart Hermes. Automatic reading starts off.",
        "No camera, microphone or sound was started by this guide. Reopen it with /gaze setup.",
    ))


def _handle_slash_command(raw_args: str) -> str:
    argv = (raw_args or "").strip().split()
    sub = argv[0].lower() if argv else "status"
    session = get_shared_session()

    if sub == "timing":
        from .release_timing import TIMINGS
        return json.dumps(TIMINGS.snapshot(), indent=2)

    if sub == "start":
        if not session.is_chrome_reachable():
            port = urlparse(session.cdp_http_url).port or 9333
            try:
                launch_chrome_with_cdp("about:blank", port=port)
            except OSError:
                return ("Chrome could not start. Install Google Chrome in Applications, "
                        "then run /gaze connect again. Use /gaze setup to check readiness.")
            for _ in range(40):
                if session.is_chrome_reachable():
                    break
                time.sleep(.25)
        ready = session.ensure_overlay()
        if not ready and session.is_chrome_reachable():
            try:
                session.cdp.open_blank()
                ready = session.ensure_overlay()
            except OSError:
                pass
        return ("Chrome companion ready. Hold Space; wait for Listening, then speak."
                if ready else "Chrome could not attach. Open an ordinary page in the companion, then run /gaze connect again.")

    if sub == "demo":
        cfg = _config()
        server = get_shared_server()
        server.start()
        url = f"http://{server.host}:{server.port}/"
        if not session.is_chrome_reachable():
            port = urlparse(session.cdp_http_url).port or 9333
            launch_chrome_with_cdp(url, port=port)
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
        # configure() is store-only when disconnected — explicitly connect + inject here.
        # Chrome's first run on a fresh profile can take >5s to expose /json —
        # retry briefly instead of reporting success on a silent miss.
        for _ in range(12):
            if session.ensure_overlay():
                return f"Launched the companion Chrome and injected Hermes Gaze on {url}"
            time.sleep(0.5)
        return (
            f"Chrome launched on {url} but the overlay failed to inject — "
            "Companion CDP unreachable or no page tab. Check `hermes gaze status` and Chrome."
        )

    if sub == "mode" and len(argv) >= 2:
        mode = argv[1].lower()
        if mode not in ("hover", "simulated", "webcam"):
            return "Usage: /gaze mode {hover|simulated|webcam}"
        session.configure(mode=mode)
        if mode == "webcam":
            status = session.start_webcam()
            return json.dumps(status) + "\nUse /gaze calibrate in the owned webcam window before asking."
        return f"Hermes Gaze mode set to '{mode}' (sigma={session.tracker.sigma_px}px)."

    if sub == "calibrate":
        session.configure(mode="webcam")
        status = session.start_webcam()
        if status["state"] == "running":
            session.webcam.calibrate()
        return json.dumps(status) + "\nIn the webcam window, click Calibrate nine points. Look at each dot, then press Space."

    if sub == "tracker":
        if len(argv) > 1 and argv[1] == "stop":
            session.configure(mode="hover")
        return json.dumps(session.webcam_status())

    if sub == "benchmark":
        return format_benchmark_markdown(run_benchmark_suite(trials_per_sigma=60))

    if sub == "resolve":
        utt = " ".join(argv[1:]) or "What happens if I press this?"
        return handle_gaze_resolve({"utterance": utt})

    if sub in ("listen", "voice"):
        return handle_gaze_resolve({"record_voice": True, "duration_s": 2.8})

    return (
        "Hermes Gaze ('Telepathy') Status:\n"
        f"  Chrome companion Connected   : {session.is_chrome_reachable()}\n"
        f"  Active Pointing Mode         : {session.tracker.mode} (sigma={session.tracker.sigma_px}px)\n"
        f"  Online Drift Bias Offset     : {session.recalibrator.offset}\n\n"
        f"  Webcam Tracker               : {json.dumps(session.webcam_status())}\n"
        "Subcommands:\n"
        "  /gaze demo                   Launch Chrome on the interactive Analytics Dashboard demo page\n"
        "  /gaze listen                 Listen from microphone, transcribe speech, and resolve in Chrome\n"
        "  /gaze mode <hover|simulated|webcam> Choose cursor, simulated noise or real webcam\n"
        "  /gaze calibrate              Open the owned nine-point webcam calibration window\n"
        "  /gaze tracker [stop]         Show tracker status, or stop camera and return to cursor\n"
        "  /gaze timing                 Show last eight release traces (monotonic milliseconds only)\n"
        "  /gaze resolve <utterance>    Resolve a deictic phrase against the live Chrome tab\n"
        "  /gaze benchmark              Run quantitative accuracy benchmark across noise levels"
    )


def _setup_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="gaze_subcommand")
    subs.add_parser("status", help="Show Chrome CDP connection and tracker status")
    p_speech = subs.add_parser("setup-speech", help="Download pinned offline Phonon model and voice (no audio devices)")
    p_speech.add_argument("--voice", default="Russell", help="English catalogue voice name")
    p_demo = subs.add_parser("demo", help="Launch the companion Chrome with the interactive Analytics & Comparison demo page")
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
    if sub == "setup-speech":
        from .speech import setup
        setup(args.voice)
        return 0
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
