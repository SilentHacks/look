"""Local Speech Recognition and Audio Server for hermes-gaze.

Combines:
1. faster-whisper local model (tiny.en / base.en) with word-level timestamps.
2. sounddevice microphone capture from macOS default audio input (MacBook Pro Mic).
3. Built-in lightweight HTTP audio & web server on http://127.0.0.1:9111 for Chrome HUD.
4. Temporal alignment between spoken deictic anchors ('this', 'that', 'these') and gaze fixations.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "tiny.en"
_WHISPER_MODEL = None
_MODEL_LOCK = threading.Lock()
_SHARED_SERVER: Optional["VoiceHttpServer"] = None
_SERVER_LOCK = threading.Lock()
_DEMO_HTML_PATH = Path(__file__).resolve().parent.parent / "benchmark" / "benchmark_page.html"
_OVERLAY_JS_PATH = Path(__file__).resolve().parent.parent / "browser" / "overlay.js"


def _ensure_package_importable() -> None:
    """Ensure hermes_gaze is importable even when voice_listener.py is run directly as a script."""
    if "hermes_gaze" in sys.modules:
        return
    try:
        import hermes_gaze  # noqa: F401
    except ImportError:
        import importlib.util

        plugin_root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "hermes_gaze",
            plugin_root / "__init__.py",
            submodule_search_locations=[str(plugin_root)],
        )
        if spec and spec.loader:
            pkg = importlib.util.module_from_spec(spec)
            sys.modules["hermes_gaze"] = pkg
            spec.loader.exec_module(pkg)


def get_whisper_model(model_name: str = _DEFAULT_MODEL) -> Any:
    """Lazy singleton loader for the local faster-whisper model."""
    global _WHISPER_MODEL
    with _MODEL_LOCK:
        if _WHISPER_MODEL is None:
            from faster_whisper import WhisperModel

            logger.info("Loading faster-whisper model '%s' on CPU (int8)...", model_name)
            _WHISPER_MODEL = WhisperModel(model_name, device="cpu", compute_type="int8")
        return _WHISPER_MODEL


def decode_audio_to_float32(raw_bytes: bytes, sample_rate: int = 16000) -> Any:
    """Decode any audio container (WebM, Opus, WAV, MP3) to 16kHz mono float32 numpy array."""
    import numpy as np
    import shutil
    import subprocess

    if not raw_bytes:
        return np.zeros(0, dtype=np.float32)

    ffmpeg_bin = (
        shutil.which("ffmpeg")
        or ("/opt/homebrew/bin/ffmpeg" if os.path.isfile("/opt/homebrew/bin/ffmpeg") else "/usr/local/bin/ffmpeg")
    )
    if os.path.isfile(ffmpeg_bin):
        try:
            cmd = [
                ffmpeg_bin,
                "-nostdin",
                "-threads", "0",
                "-i", "pipe:0",
                "-f", "s16le",
                "-ac", "1",
                "-ar", str(sample_rate),
                "pipe:1",
            ]
            proc = subprocess.run(cmd, input=raw_bytes, capture_output=True, check=True)
            if len(proc.stdout) > 0:
                return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception as exc:
            logger.warning("ffmpeg decode error: %s, falling back to wav/pcm parsing", exc)

    # Fallback to WAV parsing
    if raw_bytes.startswith(b"RIFF") and b"WAVE" in raw_bytes[:16]:
        try:
            with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
                channels = wf.getnchannels()
                raw_frames = wf.readframes(wf.getnframes())
                audio_np = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
                if channels > 1:
                    audio_np = audio_np.reshape(-1, channels).mean(axis=1)
                return audio_np
        except Exception as exc:
            logger.warning("WAV parsing error: %s, falling back to raw PCM", exc)

    return np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_audio_buffer(
    audio_bytes: bytes,
    sample_rate: int = 16000,
    model_name: str = _DEFAULT_MODEL,
) -> Tuple[str, List[Dict[str, object]]]:
    """Transcribe WebM, WAV, or PCM bytes into text with word-level timestamps."""
    import numpy as np

    audio_np = decode_audio_to_float32(audio_bytes, sample_rate=sample_rate)
    if len(audio_np) == 0:
        return "", []

    peak = float(np.max(np.abs(audio_np)))
    if peak < 1e-5:
        return "", []

    # Normalize quiet microphone input so Whisper reliably detects normal/soft speech
    if 0.002 < peak < 0.65:
        audio_np = np.clip(audio_np * (0.85 / peak), -1.0, 1.0).astype(np.float32)

    model = get_whisper_model(model_name)
    segments, _info = model.transcribe(
        audio_np,
        word_timestamps=True,
        language="en",
        condition_on_previous_text=False,
    )
    words: List[Dict[str, object]] = []
    text_parts: List[str] = []
    for seg in segments:
        text_parts.append(seg.text.strip())
        for w in getattr(seg, "words", None) or []:
            words.append({"word": w.word, "start": float(w.start), "end": float(w.end)})

    full_text = " ".join(text_parts).strip()
    return full_text, words


def record_microphone(
    duration_s: float = 2.5,
    sample_rate: int = 16000,
) -> bytes:
    """Record audio from default macOS microphone using sounddevice."""
    import numpy as np
    import sounddevice as sd

    num_samples = int(duration_s * sample_rate)
    recording = sd.rec(num_samples, samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    return recording.tobytes()


def ask_hermes_explanation(utterance: str, label: str, role: str, summary: str) -> str:
    """Ask Hermes for a concise, helpful explanation of a UI element in context."""
    import shutil
    import subprocess

    hermes_bin = shutil.which("hermes") or "/Users/Abid/.local/bin/hermes"
    prompt = (
        f"The user is looking at a web UI element labeled '{label}' (type: {role}, context: {summary}) "
        f"and asks: '{utterance}'. Answer their question directly in 1-2 clear, helpful sentences (under 35 words). "
        "Do not call tools; output the direct explanation text only."
    )
    if os.path.isfile(hermes_bin):
        try:
            clean_env = {k: v for k, v in os.environ.items() if not k.startswith("VIRTUAL_ENV") and not k.startswith("PYTHON")}
            clean_env["PATH"] = f"/Users/Abid/.local/bin:/opt/homebrew/bin:{os.environ.get('PATH', '')}"
            clean_env["HERMES_GAZE_INTERNAL"] = "1"
            res = subprocess.run(
                [hermes_bin, "--reasoning", "none", "-t", "", "-z", prompt],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=25,
                env=clean_env,
            )
            out = res.stdout.strip()
            if out:
                lines = [
                    l for l in out.splitlines()
                    if not l.startswith("hermes:") and not l.startswith("→") and not l.startswith("✓")
                ]
                ans = "\n".join(lines).strip()
                if ans:
                    return ans
        except Exception as exc:
            logger.warning("hermes -z explanation failed: %s", exc)
    return f"{label} ({role}) in {summary}"


class VoiceServerHandler(BaseHTTPRequestHandler):
    """HTTP endpoint handler for the Chrome Gaze demo & Speech Recognition API."""

    def log_message(self, format: str, *args: Any) -> None:
        # Keep logs clean; only log errors
        if args and str(args[0]).startswith(("4", "5")):
            logger.warning("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            if _DEMO_HTML_PATH.is_file():
                content = _DEMO_HTML_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(content)
                return

        if path == "/overlay.js":
            if _OVERLAY_JS_PATH.is_file():
                content = _OVERLAY_JS_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(content)
                return

        if path == "/api/status":
            _ensure_package_importable()
            from hermes_gaze.browser.cdp_bridge import get_shared_bridge

            bridge = get_shared_bridge()
            status = {
                "ok": True,
                "stt_engine": "faster-whisper",
                "model": _DEFAULT_MODEL,
                "chrome_connected": bridge.is_chrome_reachable(),
                "mode": bridge.tracker.mode,
                "sigma_px": bridge.tracker.sigma_px,
            }
            body = json.dumps(status).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b""
        path = self.path.split("?")[0]

        if path == "/api/transcribe":
            content_type = self.headers.get("Content-Type", "")
            audio_bytes = b""
            sample_rate = 16000

            if "application/json" in content_type:
                try:
                    payload = json.loads(body.decode("utf-8"))
                    import base64

                    b64_data = payload.get("audio_base64", "")
                    if b64_data:
                        audio_bytes = base64.b64decode(b64_data)
                    sample_rate = int(payload.get("sample_rate", 16000))
                except Exception as exc:
                    self._send_json({"error": f"Invalid JSON payload: {exc}"}, status=400)
                    return
            else:
                # Raw audio stream (WebM, Opus, PCM, or WAV)
                audio_bytes = body

            try:
                _ensure_package_importable()
                text, words = transcribe_audio_buffer(audio_bytes, sample_rate=sample_rate)
                from hermes_gaze.resolver.temporal_aligner import extract_deictic_anchors

                anchors = extract_deictic_anchors(text, t_arm=time.time(), word_timestamps=words) if text else []
                resp = {
                    "ok": True,
                    "text": text,
                    "words": words,
                    "anchors": [
                        {"word": a.word, "t_anchor": a.t_anchor, "is_plural": a.is_plural}
                        for a in anchors
                    ],
                }
                self._send_json(resp)
            except Exception as exc:
                logger.exception("Transcription error: %s", exc)
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if path == "/api/resolve_voice":
            try:
                _ensure_package_importable()
                payload = json.loads(body.decode("utf-8"))
                utterance = str(payload.get("utterance", "")).strip()
                words = payload.get("words", [])

                from hermes_gaze.tools import handle_gaze_resolve

                resolve_args = {"utterance": utterance}
                if words:
                    resolve_args["word_timestamps"] = words

                res_json = handle_gaze_resolve(resolve_args)
                self._send_json(json.loads(res_json))
            except Exception as exc:
                logger.exception("Voice resolution error: %s", exc)
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if path == "/api/explain":
            try:
                _ensure_package_importable()
                payload = json.loads(body.decode("utf-8"))
                utterance = str(payload.get("utterance", "What does this mean?")).strip()
                label = str(payload.get("label", "")).strip()
                role = str(payload.get("role", "")).strip()
                summary = str(payload.get("summary", "")).strip()

                explanation = ask_hermes_explanation(utterance, label=label, role=role, summary=summary)
                self._send_json({"ok": True, "explanation": explanation})
            except Exception as exc:
                logger.exception("Explain error: %s", exc)
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        self.send_response(404)
        self.end_headers()

    def _send_json(self, data: Dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)


def _is_voice_server_reachable(host: str = "127.0.0.1", port: int = 9111) -> bool:
    import urllib.request

    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/status")
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            return resp.status == 200
    except Exception:
        return False


class VoiceHttpServer:
    """Background HTTP server serving the Gaze Console and Whisper Speech API."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9111) -> None:
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._server is not None or _is_voice_server_reachable(self.host, self.port):
            return
        try:
            self._server = ThreadingHTTPServer((self.host, self.port), VoiceServerHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            logger.info("VoiceHttpServer running on http://%s:%d", self.host, self.port)
        except OSError as exc:
            logger.warning("VoiceHttpServer could not bind http://%s:%d (%s)", self.host, self.port, exc)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None


def ensure_voice_daemon_running(host: str = "127.0.0.1", port: int = 9111) -> None:
    """Check if the HTTP voice server is reachable; if not, spawn a detached daemon process."""
    import subprocess

    if _is_voice_server_reachable(host, port):
        return

    server_script = str(Path(__file__).resolve())
    cmd = [sys.executable, server_script]
    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(10):
            if _is_voice_server_reachable(host, port):
                return
            time.sleep(0.15)
    except Exception as exc:
        logger.warning("Could not spawn background voice daemon: %s", exc)


def get_shared_voice_server(host: str = "127.0.0.1", port: int = 9111) -> VoiceHttpServer:
    """Singleton getter for the background voice server."""
    global _SHARED_SERVER
    with _SERVER_LOCK:
        if _SHARED_SERVER is None:
            ensure_voice_daemon_running(host=host, port=port)
            _SHARED_SERVER = VoiceHttpServer(host=host, port=port)
            _SHARED_SERVER.start()
        return _SHARED_SERVER


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    _ensure_package_importable()
    # Preload model in background
    get_whisper_model()
    server = VoiceHttpServer(host="127.0.0.1", port=9111)
    print("Starting Hermes Gaze Voice & Web Server on http://127.0.0.1:9111 ...")
    server._server = ThreadingHTTPServer((server.host, server.port), VoiceServerHandler)
    server._server.serve_forever()
