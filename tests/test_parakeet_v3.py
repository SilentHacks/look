"""No devices, model downloads or native library required for boundary regressions."""
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from hermes_gaze.audio import voice
from hermes_gaze.audio.asset_cache import AssetIntegrityError, AssetsMissing
from hermes_gaze.audio.asr import parakeet_v3 as v3


class ParakeetV3Tests(unittest.TestCase):
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
        with patch.object(v3, "get_runner", side_effect=load), \
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

    def test_native_hang_is_bounded_and_closes_worker(self):
        runner = object.__new__(v3.Runner)
        runner.lock, runner.buffer = threading.Lock(), b""
        runner.process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            with self.assertRaises(TimeoutError):
                runner._reply(0.02)
        finally:
            runner.close()
        self.assertFalse(runner.ready)

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
