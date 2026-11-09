"""Platform claims, not a substitute for physical-device acceptance."""
import platform


def apple_silicon_mac() -> bool:
    # An x86_64 Python under Rosetta must not select arm64-only dependencies.
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def platform_notice() -> str:
    system = platform.system()
    if apple_silicon_mac():
        return ""
    if system in ("Darwin", "Linux"):
        return ("Outside the supported Apple Silicon Mac beta: cursor and faster-whisper paths "
                "remain available but unverified here; eye tracking is unavailable. "
                "Use /look cursor; Right Option opens typed questions.")
    return "Unsupported platform. Use an Apple Silicon Mac with standard Google Chrome for this beta."
