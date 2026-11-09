"""Pinned preparation and readiness, using only tiny fake files and fake devices."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hermes_gaze import asset_cache as cache, cli, service, speech, voice
from hermes_gaze.browser.cdp_bridge import GazeSession
from tests import test_first_run
from tests.test_cursor_context import capture


class PinnedDownloadsTests(unittest.TestCase):
    def setUp(self):
        # Keep native NumPy imported outside patch.dict(sys.modules) snapshots.
        __import__("numpy")
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.files = {
            cache.COREML: {"Decoder.mlmodelc/weights/weight.bin": b"coreml"},
            cache.MLX: {"config.json": b"{}", "model.safetensors": b"mlx"},
            cache.WHISPER["base.en"]: {"config.json": b"{}", "model.bin": b"whisper", "tokenizer.json": b"{}"},
            cache.WHISPER["tiny.en"]: {"config.json": b"{}", "model.bin": b"tiny", "tokenizer.json": b"{}"},
            speech.MODEL_REPO: {name: name.encode() for name in speech.MODEL_FILES},
            speech.VOICE_REPO: {"voices.jsonl": json.dumps(dict(name="Russell", voice_id="r", language="en",
                                   filename="voices/r.safetensors")).encode(), "voices/r.safetensors": b"voice"},
        }
        manifests = {repo: {"revision": str(i) * 40, "files": {
            name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()}} for i, (repo, files) in enumerate(self.files.items(), 1)}
        self.enterContext(patch.object(cache, "ASSETS", manifests))
        self.enterContext(patch.object(speech, "ASSETS", manifests))
        self.enterContext(patch.object(voice, "_COREML_RUNNER", None))
        self.enterContext(patch.object(voice, "_PARAKEET_MODEL", None))
        self.enterContext(patch.object(voice, "_WHISPER_MODELS", {}))
        self.enterContext(patch.object(voice, "_PREPARING", False))
        self.enterContext(patch.object(voice, "_PREPARATION_ERROR", ""))
        self.enterContext(patch.object(voice, "_PREPARE_DOWNLOAD", False))
        self.enterContext(patch.object(voice, "_PREPARE_REPORT", None))
        self.enterContext(patch.object(voice, "apple_silicon_mac", return_value=True))
        self.enterContext(patch("huggingface_hub.try_to_load_from_cache", side_effect=self.cached))
        self.download = self.enterContext(patch("huggingface_hub.hf_hub_download", side_effect=self.fetch))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("network forbidden")))

    def path(self, repo, name):
        return self.root / repo.replace("/", "--") / cache.ASSETS[repo]["revision"] / name

    def cached(self, repo, name, **_):
        path = self.path(repo, name)
        return str(path) if path.is_file() else None

    def fetch(self, repo, name, **kwargs):
        self.assertEqual(kwargs["revision"], cache.ASSETS[repo]["revision"])
        self.assertEqual(kwargs["endpoint"], "https://huggingface.co")
        path = self.path(repo, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.files[repo][name])
        return str(path)

    def populate(self, repo):
        for name, data in self.files[repo].items():
            path = self.path(repo, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def fake_loaders(self):
        coreml, mlx, whisper = Mock(), Mock(), Mock()
        self.enterContext(patch.dict(sys.modules, {
            "hermes_gaze.asr.parakeet_coreml": SimpleNamespace(ParakeetCoreML=coreml),
            "parakeet_mlx": SimpleNamespace(from_pretrained=mlx),
            "faster_whisper": SimpleNamespace(WhisperModel=whisper),
        }))
        return coreml, mlx, whisper

    def finish_warmup(self):
        for thread in threading.enumerate():
            if thread.name in ("gaze-asr-prewarm", "gaze-asr-prepare"):
                thread.join(2)
                self.assertFalse(thread.is_alive())

    def test_restart_uses_cached_fallbacks_before_any_download_and_keeps_preference(self):
        coreml, mlx, whisper = self.fake_loaders()
        self.populate(cache.WHISPER["base.en"])
        voice.prewarm()
        self.finish_warmup()
        self.assertTrue(voice.recognition_ready())
        coreml.assert_not_called()
        mlx.assert_not_called()
        whisper.assert_called_once()
        self.download.assert_not_called()
        # A fresh process with both preferred and fallback caches keeps CoreML.
        voice._WHISPER_MODELS.clear()
        self.populate(cache.COREML)
        voice.prewarm()
        self.finish_warmup()
        self.assertIs(voice._COREML_RUNNER, coreml.return_value)
        coreml.return_value.transcribe_array.assert_called_once()
        self.assertEqual(whisper.call_count, 1)
        # An installed but unusable preferred runtime must not strand MLX.
        voice._COREML_RUNNER = None
        coreml.side_effect = ImportError("CoreML unavailable")
        self.populate(cache.MLX)
        voice.prepare_recognition()
        self.finish_warmup()
        self.assertIs(voice._PARAKEET_MODEL, mlx.return_value)
        self.download.assert_not_called()

    def test_non_apple_setup_never_prepares_apple_assets(self):
        coreml, mlx, whisper = self.fake_loaders()
        with patch.object(voice, "apple_silicon_mac", return_value=False):
            voice.prepare_recognition()
            self.finish_warmup()
            self.assertTrue(voice.recognition_ready())
            self.assertEqual({call.args[0] for call in self.download.call_args_list},
                             {cache.WHISPER["base.en"]})
            whisper.assert_called_once()
            coreml.assert_not_called()
            mlx.assert_not_called()

    def test_explicit_setup_uses_offline_fallback_before_missing_preferred(self):
        coreml, mlx, whisper = self.fake_loaders()
        self.populate(cache.WHISPER["base.en"])
        self.download.side_effect = OSError("offline")
        voice.prepare_recognition()
        self.finish_warmup()
        self.assertTrue(voice.recognition_ready())
        whisper.assert_called_once()
        coreml.assert_not_called()
        mlx.assert_not_called()
        self.download.assert_not_called()

    def test_empty_cache_warmup_is_offline_and_setup_can_retry_failed_downloads(self):
        coreml, mlx, whisper = self.fake_loaders()
        voice.prewarm()
        self.finish_warmup()
        self.assertFalse(voice.recognition_ready())
        self.assertIn("not ready", voice.recognition_status())
        self.download.assert_not_called()
        coreml.assert_not_called()
        mlx.assert_not_called()
        whisper.assert_not_called()
        self.download.side_effect = OSError("offline")
        voice.prepare_recognition()
        self.finish_warmup()
        self.assertFalse(voice.recognition_ready())
        self.assertIn("could not prepare", voice.recognition_status())
        self.download.side_effect = self.fetch
        voice.prepare_recognition()
        self.finish_warmup()
        self.assertTrue(voice.recognition_ready())

    def test_cache_integrity_failure_blocks_restart_and_setup_fallback(self):
        coreml, mlx, whisper = self.fake_loaders()
        self.populate(cache.COREML)
        self.populate(cache.WHISPER["base.en"])
        self.path(cache.COREML, "Decoder.mlmodelc/weights/weight.bin").write_bytes(b"broken")
        for start in (voice.prewarm, voice.prepare_recognition):
            start()
            self.finish_warmup()
            self.assertFalse(voice.recognition_ready())
            self.assertIn("changed", voice.recognition_status())
        coreml.assert_not_called()
        mlx.assert_not_called()
        whisper.assert_not_called()
        self.download.assert_not_called()

    def test_setup_overlapping_restart_is_single_flight_and_explicitly_allows_fetch(self):
        coreml, _, _ = self.fake_loaders()
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        original = voice.prepare
        def blocked(repo, **kwargs):
            if repo == cache.COREML and not kwargs.get("download"):
                entered.set()
                self.assertTrue(release.wait(2))
            return original(repo, **kwargs)
        with patch.object(voice, "prepare", side_effect=blocked):
            try:
                voice.prewarm()
                self.assertTrue(entered.wait(1))
                self.assertIn("Preparing", voice.recognition_status())
                for _ in range(3):
                    voice.prepare_recognition(report=lambda _: done.set())
                    voice.prewarm()
                release.set()
                self.assertTrue(done.wait(2))
                self.finish_warmup()
                self.assertTrue(voice.recognition_ready())
                coreml.assert_called_once()
                count = self.download.call_count
                voice.prepare_recognition()
                voice.prewarm()
                self.assertEqual(self.download.call_count, count)
            finally:
                release.set()
                self.finish_warmup()

    def test_linux_restart_loads_configured_whisper_and_first_hold_sees_ready(self):
        _, _, whisper = self.fake_loaders()
        self.populate(cache.WHISPER["tiny.en"])
        with patch.object(voice, "apple_silicon_mac", return_value=False):
            voice.prewarm("tiny.en")
            self.finish_warmup()
            self.assertTrue(voice.recognition_ready("tiny.en"))
            session = GazeSession("http://127.0.0.1:1")
            self.addCleanup(session.close)
            replies = []
            with patch.object(service, "get_shared_session", return_value=session), \
                    patch.object(service, "_VOICE_TURNS", None), \
                    patch.object(service, "_CONFIG", SimpleNamespace(whisper_model="tiny.en")), \
                    patch.object(session.microphone, "start", return_value={"ok": True}) as start:
                service.handle_intent(dict(type="record_start", nonce=session._intent_nonce,
                    _browser_target="tab", _browser_document="doc"), replies.append)
            self.assertTrue(replies[-1]["ok"])
            start.assert_called_once()
            whisper.assert_called_once()
        self.download.assert_not_called()

    def test_changed_cached_and_downloaded_artifacts_fail_closed(self):
        repo = cache.MLX
        self.populate(repo)
        changed = self.path(repo, "config.json")
        changed.write_bytes(b"[]")  # Same size: size checks alone are not integrity checks.
        self.path(repo, "model.safetensors").unlink()
        with self.assertRaises(cache.AssetIntegrityError):
            cache.prepare(repo, download=True)
        self.download.assert_not_called()  # Never fetch another file after detecting corruption.
        changed.unlink()
        with patch.object(self, "fetch", return_value=str(changed)):
            def corrupt(*args, **kwargs):
                changed.write_bytes(b"bad")
                return str(changed)
            self.download.side_effect = corrupt
            with self.assertRaises(cache.AssetIntegrityError):
                cache.prepare(repo, download=True)

    def test_explicit_preparation_pins_missing_files_and_warm_cache_is_offline(self):
        repo = cache.MLX
        root = cache.prepare(repo, download=True)
        self.assertEqual((root / "model.safetensors").read_bytes(), b"mlx")
        self.download.reset_mock()
        self.download.side_effect = AssertionError("warm cache must not download")
        self.assertEqual(cache.prepare(repo, download=True), root)
        cache.prepare(repo)
        self.download.assert_not_called()

    def test_whisper_requires_local_verified_tokenizer_and_rejects_custom_repositories(self):
        repo = cache.WHISPER["base.en"]
        self.populate(repo)
        model = Mock()
        with patch.dict(sys.modules, faster_whisper=SimpleNamespace(WhisperModel=model)):
            voice.get_whisper_model()
            self.assertEqual(model.call_args.args[0], str(self.path(repo, "model.bin").parent))
            self.assertTrue(model.call_args.kwargs["local_files_only"])
            voice._WHISPER_MODELS.clear()
            model.reset_mock()
            self.path(repo, "tokenizer.json").unlink()
            with self.assertRaises(cache.AssetsMissing):
                voice.get_whisper_model()
            for custom in ("owner/repo", "/tmp/custom-model", "large-v3"):
                with self.assertRaises(ValueError):
                    voice.get_whisper_model(custom)
            model.assert_not_called()
        self.download.assert_not_called()

    def test_phonon_checks_cached_inputs_before_native_loading_and_never_speaks_tampered_assets(self):
        root = self.root / "phonon"
        for repo, revision in ((speech.MODEL_REPO, speech.MODEL_REVISION),
                               (speech.VOICE_REPO, speech.VOICE_REVISION)):
            for name, data in self.files[repo].items():
                path = root / revision / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        tts = Mock()
        with patch.object(speech, "asset_root", return_value=root), \
                patch.dict(sys.modules, ptts=SimpleNamespace(TTS=tts)):
            playback = speech.SpeechPlayback()
            playback.load("Russell")
            self.assertEqual(tts.call_count, 1)
            (root / speech.MODEL_REVISION / "tokenizer.json").write_bytes(b"changed")
            with patch.object(playback, "say") as say:
                report = Mock()
                playback.play("Answer", "Russell", threading.Event(), report)
                say.assert_not_called()
                self.assertEqual(report.call_args.args[0], "unavailable")
            self.assertEqual(tts.call_count, 1)
        self.download.assert_not_called()

    def test_registration_never_downloads_and_cached_primary_warms_offline(self):
        class Runner:
            def __init__(self, **_):
                cache.prepare(cache.COREML)
            transcribe_array = Mock()
        module = SimpleNamespace(ParakeetCoreML=Runner)
        for cached in (False, True):
            with self.subTest(cached=cached):
                if cached:
                    self.populate(cache.COREML)
                voice._COREML_RUNNER = None
                Runner.transcribe_array.reset_mock()
                fixture = test_first_run.FirstRunTests()
                self.addCleanup(fixture.doCleanups)
                with patch.dict(sys.modules, {"hermes_gaze.asr.parakeet_coreml": module}):
                    fixture.register(None, warm=True)
                    for thread in threading.enumerate():
                        if thread.name == "gaze-asr-prewarm":
                            thread.join(2)
                            self.assertFalse(thread.is_alive())
                self.assertEqual(voice.recognition_ready(), cached)
                self.assertEqual(Runner.transcribe_array.call_count, int(cached))
        self.download.assert_not_called()

    def test_integrity_failure_stops_preparation_without_fallback(self):
        done = threading.Event()
        with patch.object(voice, "prepare", side_effect=cache.AssetIntegrityError("Downloaded speech file changed")) as prepare, \
                patch.object(voice, "_get_coreml_runner") as coreml, \
                patch.object(voice, "_get_parakeet_model") as mlx, \
                patch.object(voice, "get_whisper_model") as whisper:
            voice.prepare_recognition(report=lambda _: done.set())
            self.assertTrue(done.wait(2))
            self.assertEqual(prepare.call_count, 1)
            coreml.assert_not_called()
            mlx.assert_not_called()
            whisper.assert_not_called()
            self.assertFalse(voice.recognition_ready())
            self.assertIn("changed", voice.recognition_status())

    def test_preparing_refuses_space_and_tool_capture_without_waiting_on_loader_or_blocking_release(self):
        session = GazeSession("http://127.0.0.1:1")
        self.addCleanup(session.close)
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        def prepare(*_, **__):
            entered.set()
            release.wait(3)
        def loaded():
            voice._COREML_RUNNER = object()
            return voice._COREML_RUNNER
        try:
            with patch.object(voice, "prepare", side_effect=prepare), \
                    patch.object(voice, "_get_coreml_runner", side_effect=loaded), \
                    patch.object(service, "get_shared_session", return_value=session), \
                    patch.object(service, "_VOICE_TURNS", None):
                reports = []
                guide = cli._first_run_guide(session, report=lambda text: (reports.append(text), done.set()))
                self.assertIn("Preparing local speech recognition", guide)
                self.assertTrue(entered.wait(1))
                self.assertTrue(voice._PREPARING)
                replies = []
                intent = dict(type="record_start", nonce=session._intent_nonce,
                              _browser_target="tab", _browser_document="doc")
                with voice._COREML_LOCK, patch.object(session.microphone, "start") as start:
                    request = threading.Thread(target=service.handle_intent, args=(intent, replies.append))
                    request.start()
                    request.join(1)
                    self.assertFalse(request.is_alive(), "Space waited for model preparation")
                    start.assert_not_called()
                    self.assertFalse(replies[-1]["ok"])
                    self.assertIn("Preparing local speech recognition", replies[-1]["plain_error"])
                    with self.assertRaises(RuntimeError):
                        voice.record_microphone()
                    # A release/cancel must still shut down an already-owned stream immediately.
                    stream = Mock()
                    session.microphone._stream, session.microphone._owner = stream, "tab:doc"
                    session.microphone._audio.extend(b"pcm")
                    with patch.object(voice, "transcribe_audio_buffer", return_value=("hello", [])), \
                            patch.object(service, "resolve_now", return_value={"ok": True}), \
                            patch.object(service, "submit_snapshot", return_value={"ok": True}):
                        service.handle_intent({**intent, "type": "record_stop", "cursor_context": capture()}, replies.append)
                    stream.stop.assert_called_once()
                    stream.close.assert_called_once()
                release.set()
                self.assertTrue(done.wait(2))
                self.assertTrue(voice.recognition_ready())
                self.assertIn("ready", reports[-1])
        finally:
            release.set()
            done.wait(3)


if __name__ == "__main__":
    unittest.main()
