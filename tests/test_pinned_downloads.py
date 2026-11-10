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

from hermes_gaze.audio import asset_cache as cache, speech, voice
from hermes_gaze import cli
from hermes_gaze.runtime import service
from hermes_gaze.browser.cdp_bridge import GazeSession
from tests import test_first_run
from tests.test_cursor_context import capture


class PinnedDownloadsTests(unittest.TestCase):
    def setUp(self):
        # Keep native NumPy imported outside patch.dict(sys.modules) snapshots.
        __import__("numpy")
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.files = {
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
        self.enterContext(patch.object(voice, "_WHISPER_MODELS", {}))
        self.enterContext(patch.object(voice, "_PREPARING", False))
        self.enterContext(patch.object(voice, "_PREPARATION_ERROR", ""))
        self.enterContext(patch.object(voice, "_PREPARE_DOWNLOAD", False))
        self.enterContext(patch.object(voice, "_PREPARE_REPORT", None))
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
        self.assertIs(kwargs["token"], False)
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
            "hermes_gaze.audio.asr.parakeet_coreml": SimpleNamespace(ParakeetCoreML=coreml),
            "parakeet_mlx": SimpleNamespace(from_pretrained=mlx),
            "faster_whisper": SimpleNamespace(WhisperModel=whisper),
        }))
        return coreml, mlx, whisper

    def finish_warmup(self):
        for thread in threading.enumerate():
            if thread.name in ("gaze-asr-prewarm", "gaze-asr-prepare"):
                thread.join(2)
                self.assertFalse(thread.is_alive())

    def test_public_downloads_never_resolve_or_send_ambient_credentials(self):
        from huggingface_hub.utils import build_hf_headers

        fetch = self.fetch
        def anonymous_fetch(repo, name, **kwargs):
            headers = build_hf_headers(token=kwargs.get("token"))
            self.assertNotIn("authorization", {key.lower() for key in headers})
            return fetch(repo, name, **kwargs)

        with patch("huggingface_hub.utils._headers.get_token",
                   side_effect=AssertionError("ambient credential resolution forbidden")), \
                patch("huggingface_hub.utils._auth.get_token",
                      side_effect=AssertionError("credential store access forbidden")):
            self.download.side_effect = anonymous_fetch
            for repo in self.files:
                with self.subTest(repo=repo):
                    cache.prepare(repo, download=True)

    def test_restart_uses_cached_whisper_without_downloads(self):
        coreml, mlx, whisper = self.fake_loaders()
        self.populate(cache.WHISPER["base.en"])
        voice.prewarm()
        self.finish_warmup()
        self.assertTrue(voice.recognition_ready())
        coreml.assert_not_called()
        mlx.assert_not_called()
        whisper.assert_called_once()
        self.download.assert_not_called()

    def test_old_explicit_choices_and_v3_fallback_ignore_installed_v2_and_caches(self):
        from hermes_gaze import config
        from hermes_gaze.audio.asr import parakeet_v3 as v3
        # Make both removed loaders and their old cache files available.
        coreml, mlx, whisper = self.fake_loaders()
        coreml.side_effect = mlx.side_effect = AssertionError("removed backend executed")
        old_repos = ("FluidInference/parakeet-tdt-0.6b-v2-coreml",
                     "mlx-community/parakeet-tdt-0.6b-v2")
        for repo in old_repos:
            root = self.root / repo.replace("/", "--")
            root.mkdir()
            (root / "model.safetensors").write_bytes(b"old cached model")
        segment = SimpleNamespace(text="hello", words=[
            SimpleNamespace(word="hello", start=0.2, end=0.6)])
        whisper.return_value.transcribe.return_value = ([segment], {})
        self.populate(cache.WHISPER["base.en"])
        self.populate(cache.WHISPER["tiny.en"])
        for system, machine in (("Darwin", "arm64"), ("Darwin", "x86_64"),
                                ("Linux", "x86_64"), ("Linux", "aarch64")):
            for selected in ("auto", "base.en", "tiny.en", "parakeet-v3"):
                for start in (voice.prewarm, voice.prepare_recognition):
                    with self.subTest(system=system, machine=machine, selected=selected, start=start.__name__), \
                            patch("platform.system", return_value=system), \
                            patch("platform.machine", return_value=machine), \
                            patch.object(v3, "get_runner", side_effect=RuntimeError("native unavailable")), \
                            patch.object(v3, "ready", return_value=False), \
                            patch("huggingface_hub.try_to_load_from_cache", side_effect=self.cached) as lookup:
                        voice._WHISPER_MODELS.clear()
                        model = config.GazeConfig(whisper_model=selected).whisper_model
                        start(model)
                        self.finish_warmup()
                        self.assertTrue(voice.recognition_ready(model))
                        text, words = voice.transcribe_audio_buffer(
                            b"\xff\x7f" * 1600, model_name=model, audio_epoch=100.0)
                        self.assertEqual(text, "hello")
                        self.assertEqual(words, [{"word": "hello", "start": 100.2, "end": 100.6}])
                        self.assertTrue(all(call.args[0] not in old_repos for call in lookup.call_args_list))
        coreml.assert_not_called()
        mlx.assert_not_called()
        self.download.assert_not_called()

    def test_removed_sources_and_backend_names_fail_before_fetch_or_execution(self):
        for repo in ("FluidInference/parakeet-tdt-0.6b-v2-coreml",
                     "mlx-community/parakeet-tdt-0.6b-v2"):
            for download in (False, True):
                with self.assertRaisesRegex(ValueError, "v2 was removed"):
                    cache.prepare(repo, download=download, local_dir=self.root)
        for backend in ("parakeet", "coreml", "mlx", "parakeet-v2"):
            with self.assertRaisesRegex(ValueError, "no longer supported"):
                voice.transcribe_audio_buffer(b"\xff\x7f" * 1600, backend=backend)
        for selected in ("parakeet-v2", "coreml", "mlx"):
            for start in (voice.prewarm, voice.prepare_recognition):
                start(selected)
                self.finish_warmup()
                self.assertFalse(voice.recognition_ready(selected))
                self.assertIn("Supported speech models", voice.recognition_status(selected))
        self.download.assert_not_called()

    def test_non_apple_setup_never_prepares_apple_assets(self):
        coreml, mlx, whisper = self.fake_loaders()
        with patch.object(cli, "apple_silicon_mac", return_value=False):
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
        self.populate(cache.WHISPER["base.en"])
        self.path(cache.WHISPER["base.en"], "model.bin").write_bytes(b"broken")
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
        _, _, whisper = self.fake_loaders()
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        original = voice.prepare
        def blocked(repo, **kwargs):
            if repo == cache.WHISPER["base.en"] and not kwargs.get("download"):
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
                whisper.assert_called_once()
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
        with patch.object(cli, "apple_silicon_mac", return_value=False):
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
        repo = cache.WHISPER["base.en"]
        self.populate(repo)
        changed = self.path(repo, "config.json")
        changed.write_bytes(b"[]")  # Same size: size checks alone are not integrity checks.
        self.path(repo, "model.bin").unlink()
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
        repo = cache.WHISPER["base.en"]
        root = cache.prepare(repo, download=True)
        self.assertEqual((root / "model.bin").read_bytes(), b"whisper")
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
        _, _, whisper = self.fake_loaders()
        from hermes_gaze import config
        for cached in (False, True):
            with self.subTest(cached=cached), patch.object(config, "apple_silicon_mac", return_value=False):
                if cached:
                    self.populate(cache.WHISPER["base.en"])
                voice._WHISPER_MODELS.clear()
                fixture = test_first_run.FirstRunTests()
                self.addCleanup(fixture.doCleanups)
                fixture.register(None, warm=True)
                self.finish_warmup()
                self.assertEqual(voice.recognition_ready(), cached)
                self.assertEqual(whisper.call_count, int(cached))
        self.download.assert_not_called()

    def test_delayed_registration_readiness_follows_binding_and_respects_stop_unload_failure(self):
        for outcome in ("rebound", "stopped", "unloaded", "failed"):
            with self.subTest(outcome=outcome):
                entered, release = threading.Event(), threading.Event()
                voice._WHISPER_MODELS.clear()

                def load(_):
                    entered.set()
                    release.wait(3)
                    if outcome == "failed":
                        raise cache.AssetIntegrityError("Downloaded speech file changed")
                    voice._WHISPER_MODELS["base.en"] = object()
                    return voice._WHISPER_MODELS["base.en"]

                fixture = test_first_run.FirstRunTests()
                self.addCleanup(fixture.doCleanups)
                events = []
                try:
                    from hermes_gaze import config
                    with patch.object(config, "apple_silicon_mac", return_value=False), \
                            patch.object(voice, "prepare"), patch.object(voice, "get_whisper_model", side_effect=load):
                        _, session, ctx, _, _ = fixture.register(None, warm=True)
                        self.assertTrue(entered.wait(1))
                        session.display_session_event = lambda event: events.append(event)
                        ctx.turns.bind(session_key="old", session_id="old")
                        self.assertFalse(events[-1]["recognition"]["ready"])
                        if outcome == "rebound":
                            ctx.turns.bind(session_key="new", session_id="new")
                        elif outcome == "stopped":
                            with ctx.turns.lock:
                                ctx.turns._disconnect()
                        elif outcome == "unloaded":
                            ctx.turns.close()
                        count = len(events)
                        release.set()
                        self.finish_warmup()
                        if outcome in ("stopped", "unloaded"):
                            self.assertEqual(len(events), count)
                        elif outcome == "failed":
                            self.assertFalse(events[-1]["recognition"]["ready"])
                            self.assertIn("changed", events[-1]["recognition"]["status"])
                        else:
                            self.assertEqual(ctx.turns.binding["session_id"], "new")
                            self.assertTrue(events[-1]["recognition"]["ready"])
                        ctx.inject_message.assert_not_called()
                finally:
                    release.set()
                    self.finish_warmup()

    def test_integrity_failure_stops_preparation_without_fallback(self):
        done = threading.Event()
        with patch.object(voice, "prepare", side_effect=cache.AssetIntegrityError("Downloaded speech file changed")) as prepare, \
                patch.object(voice, "get_whisper_model") as whisper:
            voice.prepare_recognition(report=lambda _: done.set())
            self.assertTrue(done.wait(2))
            self.assertEqual(prepare.call_count, 1)
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
        def loaded(_):
            voice._WHISPER_MODELS["base.en"] = object()
            return voice._WHISPER_MODELS["base.en"]
        try:
            with patch.object(voice, "prepare", side_effect=prepare), \
                    patch.object(voice, "get_whisper_model", side_effect=loaded), \
                    patch.object(service, "get_shared_session", return_value=session), \
                    patch.object(service, "_VOICE_TURNS", None), \
                    patch.object(service, "_CONFIG", SimpleNamespace(whisper_model="base.en")):
                reports = []
                guide = cli._first_run_guide(session, report=lambda text: (reports.append(text), done.set()))
                self.assertIn("Preparing local speech recognition", guide)
                self.assertTrue(entered.wait(1))
                self.assertTrue(voice._PREPARING)
                replies = []
                intent = dict(type="record_start", nonce=session._intent_nonce,
                              _browser_target="tab", _browser_document="doc")
                with voice._MODEL_LOCK, patch.object(session.microphone, "start") as start:
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
