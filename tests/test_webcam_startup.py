"""Responsive startup and revocation; no network, browser or capture devices."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch

from hermes_gaze import service, webcam
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.voice_turns import VoiceTurns


class Startup(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.host = webcam.WebcamHost(lambda *_: False, assets=Path(self.tmp),
                                     profile_path=Path(self.tmp) / "saved.json")
        self.addCleanup(self.host.stop)

    def ready_camera(self):
        self.host.state = "running"
        self.host._ready.set()
        self.host._stop.wait(3)

    def finish(self):
        self.host._thread.join(3)
        self.assertFalse(self.host._thread.is_alive())

    def test_slow_preparation_is_responsive_single_flight_and_cannot_launch_after_stop(self):
        entered, release = threading.Event(), threading.Event()
        def prepare(*_, **__):
            entered.set(); release.wait(3)
            return Path(self.tmp)
        with patch.object(webcam, "prepare_assets", side_effect=prepare) as prepare_mock, \
             patch.object(self.host, "_run", side_effect=self.ready_camera) as launch:
            try:
                self.assertEqual(self.host.start()["state"], "preparing")
                self.assertTrue(entered.wait(1))
                worker = self.host._thread
                self.host.start()
                self.assertIs(self.host._thread, worker)
                self.host.stop()
                self.assertEqual(self.host.state, "stopping")
                self.host.start()  # Cannot clear cancellation while old work is alive.
                self.assertTrue(self.host._stop.is_set())
                launch.assert_not_called()
            finally:
                release.set(); self.finish()
            self.assertEqual(self.host.state, "stopped")
            launch.assert_not_called()
            self.assertEqual(prepare_mock.call_count, 1)
            self.assertEqual(self.host.start(wait=1)["state"], "running")
            self.host.stop(); self.finish()

    def test_preparation_failure_keeps_saved_calibration_and_retry_can_succeed(self):
        self.host.profile_path.write_text("private saved calibration")
        before = self.host.profile_path.read_bytes()
        with patch.object(webcam, "prepare_assets", side_effect=OSError("PRIVATE /Users/person/token?secret=abc\n" * 100)), \
             patch.object(self.host, "_run") as launch:
            self.host.start(wait=1); self.finish()
            self.assertEqual(self.host.state, "failed")
            self.assertEqual(self.host.diagnostic["stage"], "preparing")
            self.assertNotIn("PRIVATE", json.dumps(self.host.status()))
            self.assertEqual(self.host.profile_path.read_bytes(), before)
            launch.assert_not_called()
        self.host.profile_path.unlink()
        with patch.object(webcam, "prepare_assets", return_value=Path(self.tmp)), \
             patch.object(self.host, "_run", side_effect=self.ready_camera):
            self.assertEqual(self.host.start(wait=1)["state"], "running")
            self.host.stop(); self.finish()

    def test_missing_chrome_fails_without_popen_and_keeps_cursor_choice_explicit(self):
        with patch.object(webcam, "prepare_assets", return_value=Path(self.tmp)), \
             patch.object(webcam, "_CHROME", str(Path(self.tmp) / "absent-chrome")), \
             patch.object(webcam.subprocess, "Popen") as launch:
            self.host.start(wait=1); self.finish()
            self.assertEqual(self.host.state, "failed")
            self.assertIn("Google Chrome", self.host.error)
            self.assertEqual(self.host.diagnostic["stage"], "starting")
            launch.assert_not_called()

    def test_cancel_between_setup_capture_and_start_cannot_revive_generation(self):
        setup = self.host.begin_setup(lambda *_: {"ok": True})
        self.host.cancel()
        with patch.object(webcam, "prepare_assets") as prepare:
            self.host.start(setup=setup)
            self.assertIsNone(self.host._thread)
            prepare.assert_not_called()

    def test_cancellation_at_process_handoff_cannot_launch_chrome(self):
        def chrome_exists():
            self.host.cancel()
            return True
        with patch.object(webcam.Path, "is_file", side_effect=chrome_exists), \
             patch.object(webcam.subprocess, "Popen") as launch:
            self.host._run()
            launch.assert_not_called()


    def test_native_diagnostics_retain_only_bounded_categories(self):
        self.host._read_stderr(io.BytesIO(b"permission denied /Users/private/key?token=secret\nFATAL singleton sandbox\x1b[31m" * 200))
        self.host._stage = "starting"
        self.host._fail(OSError(13, "PRIVATE_NATIVE_TEXT"))
        status = self.host.status()
        self.assertEqual(set(status["diagnostic"]["native"]),
                         {"permission_denied", "native_fatal", "profile_in_use", "sandbox"})
        self.assertEqual(status["diagnostic"]["errno"], 13)
        for secret in ("Users", "token", "PRIVATE", "\x1b"):
            self.assertNotIn(secret, json.dumps(status))


class SessionStartup(unittest.TestCase):
    def setUp(self):
        self.session = GazeSession("http://127.0.0.1:1")
        self.addCleanup(self.session.close)
        self.turns = VoiceTurns(SimpleNamespace(), self.session)
        self.turns.bind(session_key="key", session_id="session")
        self.enterContext(patch.object(service, "_VOICE_TURNS", self.turns))
        self.enterContext(patch.object(type(self.session.cdp), "is_connected", new_callable=PropertyMock, return_value=True))
        self.session.configure(mode="webcam")
        self.enterContext(patch.object(self.session.cdp, "capture_return_owner", return_value={"browser_target": "source"}))

    def test_disconnect_rebind_cursor_and_transport_loss_during_preparation_prevent_late_launch(self):
        for action in ("disconnect", "rebind", "cursor", "transport"):
            with self.subTest(action=action):
                self.turns.bind(session_key="key", session_id="session")
                self.session.configure(mode="webcam")
                host = self.session.webcam = webcam.WebcamHost(lambda *_: False)
                entered, release = threading.Event(), threading.Event()
                def prepare(*_, **__):
                    entered.set(); release.wait(3)
                    return Path("unused")
                with patch.object(webcam, "prepare_assets", side_effect=prepare), \
                     patch.object(host, "_run") as launch:
                    try:
                        self.session.start_webcam()
                        self.assertTrue(entered.wait(1))
                        if action == "disconnect":
                            self.turns.bind("disconnect", session_key="key", session_id="session")
                        elif action == "rebind":
                            self.turns.bind(session_key="key", session_id="session")
                            self.session.start_webcam()  # Must not transfer the old worker's authority.
                        elif action == "cursor":
                            self.session.configure(mode="hover")
                        else:
                            with patch.object(type(self.session.cdp), "is_connected", new_callable=PropertyMock, return_value=False):
                                release.set(); host._thread.join(2)
                        release.set(); host._thread.join(2)
                        self.assertFalse(host._thread.is_alive())
                        launch.assert_not_called()
                        self.assertEqual(host.state, "stopped")
                        self.assertIsNone(self.session.ring_buffer.latest())
                        self.assertEqual(self.session.tracker.mode, "hover" if action == "cursor" else "webcam")
                    finally:
                        release.set(); host.stop()

    def test_stop_while_capturing_destination_invalidates_pending_start(self):
        with patch.object(self.session.cdp, "capture_return_owner", side_effect=lambda: self.session.revoke_webcam()), \
             patch.object(webcam, "prepare_assets") as prepare:
            self.session.start_webcam()
            self.assertIsNone(self.session.webcam._thread)
            prepare.assert_not_called()


class Assets(unittest.TestCase):
    def test_cache_only_missing_integrity_and_explicit_cancelled_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w:gz") as tar:
                member = tarfile.TarInfo("package/vision_bundle.mjs")
                member.size = 8
                tar.addfile(member, io.BytesIO(b"verified"))
            data = archive.getvalue()
            with patch.object(webcam, "_ASSETS", {"tasks.tgz": ("https://assets.invalid/pinned", hashlib.sha256(data).hexdigest())}), \
                 patch.object(webcam.urllib.request, "urlopen") as fetch:
                with self.assertRaises(FileNotFoundError):
                    webcam.prepare_assets(root)
                fetch.assert_not_called()
                (root / "tasks.tgz").write_bytes(b"tampered")
                with self.assertRaisesRegex(ValueError, "checksum"):
                    webcam.prepare_assets(root, download=True)
                fetch.assert_not_called()
                (root / "tasks.tgz").write_bytes(data)
                webcam.prepare_assets(root)
                extracted = root / "package/vision_bundle.mjs"
                extracted.write_bytes(b"modified")
                webcam.prepare_assets(root)
                self.assertEqual(extracted.read_bytes(), b"verified")
                fetch.assert_not_called()
                (root / "tasks.tgz").unlink()
                cancelled = threading.Event()
                response = Mock()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                response.read1.side_effect = lambda _: cancelled.set() or data
                fetch.return_value = response
                with self.assertRaises(InterruptedError):
                    webcam.prepare_assets(root, download=True, cancelled=cancelled.is_set)
                self.assertFalse((root / "tasks.tgz").exists())


if __name__ == "__main__":
    unittest.main()
