"""No devices, model downloads or native library required for boundary regressions."""
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from hermes_gaze.audio import voice
from hermes_gaze.audio.asset_cache import AssetIntegrityError, AssetsMissing
from hermes_gaze.audio.asr import parakeet_v3 as v3


class ParakeetV3Tests(unittest.TestCase):
    def setUp(self):
        for name, value in {
            "_COREML_RUNNER": None, "_PARAKEET_MODEL": None, "_WHISPER_MODELS": {},
            "_PREPARING": False, "_PREPARATION_ERROR": "",
            "_PREPARE_DOWNLOAD": False, "_PREPARE_REPORT": None,
        }.items():
            patcher = patch.object(voice, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_and_tampered_runtime_never_download_implicitly(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(v3, "apple_silicon_mac", return_value=True), \
                patch.object(v3.urllib.request, "urlopen", side_effect=AssertionError("network")):
            with self.assertRaises(AssetsMissing):
                v3.assets(directory=directory)
            Path(directory, "runtime.tar.gz").write_bytes(b"tampered")
            for download in (False, True):
                with self.assertRaises(AssetIntegrityError):
                    v3.assets(directory=directory, download=download)

    def test_integrity_failure_does_not_fall_back(self):
        with patch.object(v3, "get_runner", side_effect=AssetIntegrityError("changed")), \
                patch.object(voice, "_transcribe_coreml") as fallback:
            with self.assertRaises(AssetIntegrityError):
                voice.transcribe_audio_buffer(b"\xff\x7f" * 1600, model_name="parakeet-v3")
            fallback.assert_not_called()

    def test_runtime_failure_uses_only_existing_cached_chain(self):
        with patch.object(v3, "get_runner", side_effect=RuntimeError("native worker died")), \
                patch.object(voice, "_transcribe_coreml", return_value=None), \
                patch.object(voice, "_transcribe_parakeet", return_value=None), \
                patch.object(voice, "get_whisper_model", side_effect=AssetsMissing("not installed")), \
                patch("huggingface_hub.hf_hub_download", side_effect=AssertionError("network")):
            with self.assertRaises(RuntimeError) as caught:
                voice.transcribe_audio_buffer(b"\xff\x7f" * 1600, model_name="parakeet-v3")
            self.assertIsInstance(caught.exception.__cause__, AssetsMissing)

    def test_setup_after_cache_only_miss_publishes_readiness(self):
        ready = threading.Event()
        def load(*, download=False):
            if not download:
                raise RuntimeError("previous native worker stopped")
            ready.set()
            return object()
        with patch.object(voice, "prepare", side_effect=AssetsMissing("empty fallback cache")), \
                patch.object(v3, "get_runner", side_effect=load), \
                patch.object(v3, "ready", side_effect=ready.is_set), \
                patch.object(voice, "_PREPARING", False), \
                patch.object(voice, "_PREPARATION_ERROR", ""), \
                patch.object(voice, "_PREPARE_DOWNLOAD", False), \
                patch.object(voice, "_PREPARE_REPORT", None):
            for start in (voice.prewarm, voice.prepare_recognition):
                done = threading.Event()
                start("parakeet-v3", report=lambda _: done.set())
                self.assertTrue(done.wait(2))
            self.assertTrue(voice.recognition_ready("parakeet-v3"))

    def test_blocked_request_write_or_read_kills_and_reaps_without_restart(self):
        import numpy as np
        for mode in ("blocked_write", "blocked_read", "shared_deadline"):
            with self.subTest(mode=mode):
                runner = object.__new__(v3.Runner)
                runner.lock, runner.buffer = threading.Lock(), b""
                script = 'import sys,time; print("ready",flush=True); '
                if mode == "shared_deadline":
                    script += 'time.sleep(.2); '
                if mode != "blocked_write":
                    script += 'sys.stdin.buffer.read(1920008); '
                if mode == "shared_deadline":
                    script += 'time.sleep(.2); print(\'{"text":"","words":[]}\',flush=True); '
                runner.process = subprocess.Popen(
                    [sys.executable, "-u", "-c", script + "time.sleep(60)"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                runner.process.stdout.readline()
                errors = []
                def transcribe():
                    try:
                        runner.transcribe(np.zeros(480000, dtype=np.float32))
                    except Exception as exc:
                        errors.append(exc)
                thread = threading.Thread(target=transcribe)
                try:
                    with patch.object(v3, "REQUEST_TIMEOUT", 0.3 if mode == "shared_deadline" else 0.1):
                        thread.start()
                        thread.join(2)
                        self.assertFalse(thread.is_alive(), "IPC exceeded request deadline")
                    self.assertIsInstance(errors[0], TimeoutError)
                    self.assertIsNotNone(runner.process.returncode, "child was not reaped")
                    self.assertTrue(runner.process.stdin.closed)
                    self.assertTrue(runner.process.stdout.closed)
                    with patch.object(v3, "_RUNNER", runner), patch.object(v3, "_LOAD_ERROR", None), \
                            patch.object(v3, "Runner") as restart:
                        with self.assertRaises(RuntimeError):
                            v3.get_runner()
                        restart.assert_not_called()
                finally:
                    if thread.is_alive():
                        runner.process.kill()
                        thread.join(2)
                    runner.close()

    def test_startup_timeout_kills_and_reaps_worker(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        original = v3.Runner._reply
        try:
            with patch.object(v3.subprocess, "Popen", return_value=process), \
                    patch.object(v3.Runner, "_reply",
                                 lambda runner, _: original(runner, time.monotonic() + 0.02)):
                with self.assertRaises(TimeoutError):
                    v3.Runner(Path("/unused"), Path("/unused"))
            self.assertIsNotNone(process.returncode)
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()

    def test_fresh_start_prepares_cached_fallback_after_v3_failure(self):
        for backend in ("coreml", "mlx", "whisper"):
            for start in (voice.prewarm, voice.prepare_recognition):
                with self.subTest(backend=backend, explicit=start is voice.prepare_recognition):
                    voice._COREML_RUNNER = voice._PARAKEET_MODEL = None
                    voice._WHISPER_MODELS.clear()
                    repo = {"coreml": voice.COREML, "mlx": voice.MLX,
                            "whisper": voice.WHISPER["base.en"]}[backend]
                    def cached(selected, *, download=False):
                        self.assertFalse(download, "fallback must remain cache-only")
                        if selected != repo:
                            raise AssetsMissing("not cached")
                    def coreml():
                        voice._COREML_RUNNER = object()
                        return voice._COREML_RUNNER
                    def mlx():
                        voice._PARAKEET_MODEL = object()
                        return voice._PARAKEET_MODEL
                    def whisper(_):
                        voice._WHISPER_MODELS["base.en"] = object()
                        return voice._WHISPER_MODELS["base.en"]
                    done = threading.Event()
                    with patch.object(v3, "ready", return_value=False), \
                            patch.object(v3, "get_runner", side_effect=RuntimeError("native unavailable")), \
                            patch.object(voice, "apple_silicon_mac", return_value=True), \
                            patch.object(voice, "prepare", side_effect=cached), \
                            patch.object(voice, "_get_coreml_runner", side_effect=coreml), \
                            patch.object(voice, "_get_parakeet_model", side_effect=mlx), \
                            patch.object(voice, "get_whisper_model", side_effect=whisper):
                        self.assertFalse(voice.recognition_ready("parakeet-v3"))
                        start("parakeet-v3", report=lambda _: done.set())
                        self.assertTrue(done.wait(2))
                        self.assertTrue(voice.recognition_ready("parakeet-v3"))
                        self.assertEqual(voice._PREPARATION_ERROR, "")

    def test_v3_preparation_integrity_failure_stops_before_fallback(self):
        done = threading.Event()
        with patch.object(v3, "ready", return_value=False), \
                patch.object(v3, "get_runner", side_effect=AssetIntegrityError("changed")), \
                patch.object(voice, "prepare") as fallback:
            voice.prepare_recognition("parakeet-v3", report=lambda _: done.set())
            self.assertTrue(done.wait(2))
            self.assertFalse(voice.recognition_ready("parakeet-v3"))
            self.assertIn("changed", voice.recognition_status("parakeet-v3"))
            fallback.assert_not_called()

    def test_failed_native_load_is_cached_until_explicit_setup(self):
        with patch.object(v3, "_RUNNER", None), patch.object(v3, "_LOAD_ERROR", None), \
                patch.object(v3, "assets", side_effect=AssetsMissing("missing")) as assets:
            for _ in range(2):
                with self.assertRaises(AssetsMissing):
                    v3.get_runner()
            self.assertEqual(assets.call_count, 1)
            with self.assertRaises(AssetsMissing):
                v3.get_runner(download=True)
            self.assertEqual(assets.call_count, 2)

    def test_warm_fallback_remains_capture_ready_after_native_loss(self):
        with patch.object(v3, "ready", return_value=False), \
                patch.object(voice, "_WHISPER_MODELS", {"base.en": object()}):
            self.assertTrue(voice.recognition_ready("parakeet-v3"))



if __name__ == "__main__":
    unittest.main()
