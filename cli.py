"""Look slash commands and shell diagnostics; internal Gaze identifiers stay stable."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import time
from pathlib import Path
from urllib.parse import urlparse

from . import service
from .benchmark.run_benchmark import format_benchmark_markdown, run_benchmark_suite
from .browser.cdp_bridge import get_shared_session, launch_chrome_with_cdp
from .config import GazeConfig
from .server import get_shared_server
from .tools import handle_gaze_resolve


HELP = """/look · /look start     Start in Chrome
/look stop              Stop Look; keep browser tabs
/look status            Show current state
/look calibrate         Set up eye tracking
/look cursor            Turn off the camera; use the pointer
/look setup             Prepare local speech recognition
/look diagnostics       Show technical details
/look help advanced     More commands"""

ADVANCED_HELP = """/look demo                         Open the practice dashboard
/look mode hover|simulated|webcam    Choose pointing source
/look tracker [stop]                Eye tracking state, or return to cursor
/look resolve <question>            Inspect captured evidence
/look listen                       Record and resolve a short question
/look benchmark                    Run the simulated benchmark
/look diagnostics timing           Save recent release traces
/gaze remains an alias for /look. connect=start; disconnect=stop; voice=listen; timing=diagnostics timing.
Shell: hermes look status|diagnostics|setup-speech|demo|resolve|listen|benchmark.
Start and stop inside Hermes; shell commands do not bind or stop a running conversation."""


def _config() -> GazeConfig:
    return service._CONFIG or GazeConfig()


def _first_run_guide(session, *, initialized: bool = False, report=None) -> str:
    """Explicit downloads only; never connect or open a device."""
    from . import voice

    lines = ["Local speech setup may download ~465 MB on Mac (fallbacks up to 2.47 GB). No devices open."]
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        lines.append("This beta supports Apple Silicon Mac.")
    if not Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome").is_file():
        lines.append("Install Google Chrome in Applications.")
    if _missing_modules():
        lines.append("Dependencies missing. Quit Hermes; run hermes pm install and "
                     "hermes plugins enable hermes-gaze, then restart Hermes.")
    voice.prepare_recognition(_config().whisper_model, report=report)
    lines.append(voice.recognition_status(_config().whisper_model))
    if not initialized:
        lines.append("Send a normal message in Hermes and wait for its answer, then /look start.")
    elif not session.cdp.is_connected:
        lines.append("Next: /look start.")
    lines.append("Questions and page context go to your Hermes model and may stay in history.")
    lines.append("/look help for commands; /look diagnostics for troubleshooting.")
    return "\n".join(lines)


def _missing_modules() -> list[str]:
    modules = ["websockets", "numpy", "sounddevice", "faster_whisper", "ptts", "huggingface_hub"]
    if platform.system() == "Darwin":
        modules.extend(("parakeet_mlx", "CoreML"))
    return [name for name in modules if importlib.util.find_spec(name) is None]


def _tracker_summary(session) -> str:
    status = session.webcam_status()
    state = status["state"]
    if state == "stopping":
        return "Camera is stopping."
    if state in ("failed", "stopped"):
        if status.get("error") or state == "failed":
            return "Camera unavailable. Try /look calibrate again; /look diagnostics has details."
        return "Camera stopped. Try /look calibrate for eye tracking."
    if state == "starting":
        return "Camera is starting. Continue in the camera window."
    if not status.get("calibrated") or status.get("calibration_message"):
        return "Eye tracking needs calibration. Continue in the camera window."
    return "Eye tracking is on."


def _handle_slash_command(raw_args: str) -> str:
    argv = (raw_args or "").strip().split()
    sub = argv[0].lower() if argv else "start"
    tail = [arg.lower() for arg in argv[1:]]
    if sub in ("help", "--help", "-h"):
        return ADVANCED_HELP if tail == ["advanced"] else HELP
    session = get_shared_session()

    if sub == "diagnostics":
        if tail == ["timing"]:
            return _handle_slash_command("timing")
        if tail:
            return "Usage: /look diagnostics [timing]"
        from . import voice
        return json.dumps({
            "chrome_connected": session.cdp.is_connected,
            "chrome_reachable": session.is_chrome_reachable(),
            "mode": session.tracker.mode,
            "sigma_px": session.tracker.sigma_px,
            "drift_offset": session.recalibrator.offset,
            "webcam": session.webcam_status(),
            "recognition": voice.recognition_status(_config().whisper_model),
            "missing_dependencies": _missing_modules(),
            "supported_mac": platform.system() == "Darwin" and platform.machine() == "arm64",
        }, indent=2)

    if sub == "timing" and not tail:
        from .release_timing import TIMINGS
        snapshot = TIMINGS.snapshot()
        path = Path.home() / ".cache" / "hermes-gaze" / "release-timing.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(snapshot, handle, indent=2)
        lines = [f"Saved full timing to {path}"]
        for turn in snapshot["turns"]:
            slow = " slow" if turn["slow_release"] else ""
            lines.append(f"turn {turn['turn']}: max gap {turn['heartbeat_max_gap_ms']}ms{slow}")
        return "\n".join(lines)

    if sub in ("start", "connect") and not tail:
        get_shared_server().start()
        if not session.is_chrome_reachable():
            port = urlparse(session.cdp_http_url).port or 9333
            try:
                launch_chrome_with_cdp("about:blank", port=port)
            except OSError:
                return ("Chrome could not start. Install Google Chrome in Applications, "
                        "then /look start. /look setup checks readiness.")
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
        return ("Look is ready in Chrome. Hold Space; wait for Listening, then speak."
                if ready else "Chrome could not attach. Open an ordinary page in the companion, then /look start.")

    if sub in ("stop", "disconnect") and not tail:
        # Detach every overlay and its input handlers, not just the voice binding.
        session.close()
        session.configure(mode="hover")
        get_shared_server().stop()
        return "Look stopped. Browser tabs are still open."

    if sub == "status" and not tail:
        if not session.cdp.is_connected:
            state = session.webcam_status()["state"]
            if state in ("starting", "running", "stopping", "failed"):
                camera = {"starting": "Camera is starting", "running": "Camera is still on",
                          "stopping": "Camera is stopping", "failed": "Camera needs attention"}[state]
                return f"Chrome is disconnected. {camera}. /look stop to close it."
            return "Look is stopped. /look start to begin."
        if session.tracker.mode == "webcam":
            return _tracker_summary(session)
        return "Look is on. " + ("Using the pointer." if session.tracker.mode == "hover" else "Using simulated gaze.")

    if sub == "demo" and not tail:
        cfg = _config()
        server = get_shared_server()
        server.start()
        url = f"http://{server.host}:{server.port}/"
        try:
            if not session.is_chrome_reachable():
                port = urlparse(session.cdp_http_url).port or 9333
                launch_chrome_with_cdp(url, port=port)
                for _ in range(20):
                    if session.is_chrome_reachable():
                        break
                    time.sleep(0.25)
            else:
                session.cdp.open_url(url)
        except OSError:
            return "Practice page could not open. /look diagnostics has connection details."
        session.configure(mode=session.tracker.mode, sigma_px=session.tracker.sigma_px,
                          dwell_ms=cfg.dwell_ms, wiggle_trigger=cfg.wiggle_trigger,
                          hotkey=cfg.hotkey, candidate_radius_px=380)
        for _ in range(12):
            if session.ensure_overlay():
                return f"Practice page ready: {url}"
            time.sleep(0.5)
        return "Practice page could not attach. /look diagnostics has connection details."

    if (sub == "calibrate" and not tail) or sub == "mode" and len(tail) == 1:
        mode = "webcam" if sub == "calibrate" else tail[0]
        if mode not in ("hover", "simulated", "webcam"):
            return "Usage: /look mode hover|simulated|webcam"
        session.configure(mode=mode)
        if mode != "webcam":
            return "Using the pointer. Camera off." if mode == "hover" else "Using simulated gaze. Camera off."
        status = session.start_webcam()
        if status["state"] in ("running", "failed"):
            status = session.webcam.calibrate()
        if status["state"] == "running":
            return "Continue in the camera window."
        if status["state"] == "starting":
            return "Camera is starting. Continue in the camera window."
        return "Camera stopped or could not start. Try /look calibrate again; /look diagnostics has details."

    if sub == "cursor" and not tail or sub == "tracker" and tail == ["stop"]:
        session.configure(mode="hover")
        return "Using the pointer. Camera off."
    if sub == "tracker" and not tail:
        return _tracker_summary(session)
    if sub == "benchmark" and not tail:
        return format_benchmark_markdown(run_benchmark_suite(trials_per_sigma=60))
    if sub == "resolve":
        return handle_gaze_resolve({"utterance": " ".join(argv[1:]) or "What happens if I press this?"})
    if sub in ("listen", "voice") and not tail:
        return handle_gaze_resolve({"record_voice": True, "duration_s": 2.8})
    return "Unknown command or option. /look help shows commands; /look help advanced shows more."


def _setup_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="gaze_subcommand")
    subs.add_parser("status", help="Check whether companion Chrome is available")
    p_diag = subs.add_parser("diagnostics", help="Show technical details")
    p_diag.add_argument("detail", nargs="?", choices=("timing",))
    p_speech = subs.add_parser("setup-speech", help="Download the offline voice without playing audio")
    p_speech.add_argument("--voice", default="Russell", help="English catalogue voice name")
    p_demo = subs.add_parser("demo", help="Open the practice dashboard")
    p_demo.add_argument("--mode", choices=("hover", "simulated"), default="hover")
    p_listen = subs.add_parser("listen", help="Record, transcribe and resolve a short question")
    p_listen.add_argument("--duration", type=float, default=2.8, help="Recording duration in seconds")
    subs.add_parser("voice", parents=[p_listen], add_help=False, help="Alias for listen")
    p_bench = subs.add_parser("benchmark", help="Run the simulated benchmark")
    p_bench.add_argument("--trials", type=int, default=60)
    p_res = subs.add_parser("resolve", help="Inspect captured evidence")
    p_res.add_argument("utterance", nargs="+", help="Question about the active Chrome tab")
    subparser.set_defaults(func=_run_cli)


def _run_cli(args: argparse.Namespace) -> int:
    sub = getattr(args, "gaze_subcommand", None) or "status"
    if sub == "setup-speech":
        from .speech import setup
        setup(args.voice)
        return 0
    if sub == "demo":
        get_shared_session().configure(mode=args.mode)
        print(_handle_slash_command("demo"))
        return 0
    if sub in ("listen", "voice"):
        dur = float(getattr(args, "duration", 2.8))
        print(f"Listening for {dur:g} seconds…")
        print(handle_gaze_resolve({"record_voice": True, "duration_s": dur}))
        return 0
    if sub == "benchmark":
        print(format_benchmark_markdown(run_benchmark_suite(trials_per_sigma=args.trials)))
        return 0
    if sub == "resolve":
        print(handle_gaze_resolve({"utterance": " ".join(args.utterance)}))
        return 0
    if sub == "diagnostics":
        print(_handle_slash_command("diagnostics " + (args.detail or "")))
        return 0
    available = get_shared_session().is_chrome_reachable()
    print("Companion Chrome is available. Use /look status in Hermes for the active session."
          if available else "Companion Chrome is unavailable. Use /look start in Hermes.")
    return 0
