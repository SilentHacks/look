"""Calibration return authority and recovery; no devices, downloads or model calls."""
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hermes_gaze import service
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.browser.companion import Companion, NoForegroundTab
from hermes_gaze.voice_turns import VoiceTurns
from hermes_gaze.webcam import WebcamHost


class OwnedReturn(unittest.TestCase):
    def setUp(self):
        self.companion = Companion("http://127.0.0.1:1")
        self.tab = SimpleNamespace(_target_id="source", _context_unique_id="document", _route_id=3,
                                   is_connected=True, _ui_frames={"card": True, "pill": True},
                                   _main_frame_loading=False, eval_js_once=Mock(return_value=True))
        self.owner = self.companion._document_owner(self.tab)
        self.companion._tabs["source"] = self.tab
        self.activate = Mock(return_value=True)
        self.companion.show_document = self.activate

    def test_return_observes_the_captured_document_without_replaying_activation(self):
        self.assertEqual(self.companion.return_to_document(self.owner, lambda: True), {"ok": True})
        self.activate.assert_called_once_with("source", "document")
        self.assertEqual(self.companion._last_foreground, self.owner)
        self.tab.eval_js_once.return_value = False
        self.activate.reset_mock()
        with patch("hermes_gaze.browser.companion.time.monotonic", side_effect=[0, 0, 4]):
            result = self.companion.return_to_document(self.owner, lambda: True)
        self.assertFalse(result["ok"])
        self.activate.assert_called_once()  # Acknowledged activation is not observed focus.

    def test_closed_replaced_or_changed_route_never_targets_a_different_page(self):
        for field, value in (("_context_unique_id", "replacement"), ("_route_id", 5)):
            with self.subTest(field=field):
                before = getattr(self.tab, field)
                setattr(self.tab, field, value)
                self.assertTrue(self.companion.return_to_document(self.owner, lambda: True)["missing"])
                setattr(self.tab, field, before)
        self.companion._tabs.clear()
        self.assertTrue(self.companion.return_to_document(self.owner, lambda: True)["missing"])
        self.activate.assert_not_called()

    def test_replacement_or_disconnect_during_focus_observation_cannot_succeed(self):
        def replaced(*_, **__):
            self.tab._route_id += 1
            return True
        self.tab.eval_js_once.side_effect = replaced
        self.assertTrue(self.companion.return_to_document(self.owner, lambda: True)["missing"])
        self.tab._route_id = 3
        live = [True]
        def disconnected(*_, **__):
            live[0] = False
            return True
        self.tab.eval_js_once.side_effect = disconnected
        self.assertFalse(self.companion.return_to_document(self.owner, lambda: live[0])["ok"])

    def test_terminal_capture_uses_only_previously_observed_owner(self):
        self.companion._target = Mock(side_effect=NoForegroundTab())
        self.assertIsNone(self.companion.capture_return_owner())
        self.companion._last_foreground = self.owner
        saved = self.companion.capture_return_owner()
        self.tab._route_id = 4
        self.assertEqual(saved, self.owner)
        self.assertTrue(self.companion.return_to_document(saved, lambda: True)["missing"])

    def test_explicit_fallback_is_owned_static_surface_and_replaced_fallback_is_not_reused(self):
        fallback = SimpleNamespace(**vars(self.tab))
        fallback._target_id = "start"
        self.companion._tabs["start"] = fallback
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"id":"start"}'
        with patch("hermes_gaze.browser.companion.urllib.request.urlopen", return_value=response) as opened:
            owner = self.companion.open_start_page(lambda: True)
            self.assertEqual(owner["browser_target"], "start")
            request = opened.call_args.args[0]
            from urllib.parse import unquote
            self.assertIn(Path("browser/start.html").resolve().as_uri(), unquote(request.full_url))
            self.assertEqual(self.companion.open_start_page(lambda: True), owner)
            self.assertEqual(opened.call_count, 1)
            fallback._route_id += 1
            self.companion.open_start_page(lambda: True)
            self.assertEqual(opened.call_count, 2)
        with self.assertRaises(ConnectionError):
            self.companion.open_start_page(lambda: False)

    def test_fallback_creation_failure_is_not_reported_as_restored_source(self):
        with patch("hermes_gaze.browser.companion.urllib.request.urlopen", side_effect=OSError("Chrome unavailable")):
            with self.assertRaisesRegex(OSError, "Chrome unavailable"):
                self.companion.open_start_page(lambda: True)
        self.assertIsNone(self.companion._start_owner)


class CameraCompletion(unittest.TestCase):
    def setUp(self):
        self.host = WebcamHost(lambda *_: True)
        self.host._context, self.host._nonce = 8, "private"
        self.host.state, self.host.profile = "running", {"saved": True}
        self.ui = []
        self.host._ui = lambda method, value="": self.ui.append((method, value))

    def event(self, kind, context=8, nonce="private", **data):
        self.host._event({"method": "Runtime.bindingCalled", "params": {
            "name": "__hermesGazeIntent", "executionContextId": context,
            "payload": json.dumps(dict(type=kind, nonce=nonce, setup=self.host._setup, **data))}})

    def result(self):
        kind, payload = self.host._commands.get(timeout=2)
        self.assertEqual(kind, "_return_result")
        self.host._return_result(*payload)

    def test_completion_requires_nonce_context_setup_and_is_single_flight(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def returned(start_page, valid):
            calls.append(start_page); entered.set(); release.wait(2)
            return {"ok": valid()}
        self.host.begin_setup(returned)
        self.event("return_browsing", nonce="forged", flow=1)
        self.event("return_browsing", context=7, flow=1)
        old = self.host._setup
        self.host.begin_setup(returned)
        self.host._event({"method": "Runtime.bindingCalled", "params": {"name": "__hermesGazeIntent",
            "executionContextId": 8, "payload": json.dumps(dict(type="return_browsing", nonce="private", setup=old, flow=1))}})
        self.assertEqual(calls, [])
        self.host._practice = {"unfinished": True}
        self.event("return_browsing", flow=1)
        self.assertTrue(entered.wait(2))
        self.event("return_browsing", flow=1)
        self.assertIsNone(self.host._practice)
        release.set(); self.result()
        self.event("return_browsing", flow=1)
        self.assertEqual(calls, [False])
        self.assertEqual(self.ui, [("returnResult", {"ok": True})])
        self.assertEqual(self.host.state, "running")
        self.assertEqual(self.host.profile, {"saved": True})

    def test_late_success_cannot_escape_superseded_flow_or_connection(self):
        self.host.begin_setup(lambda *_: {"ok": True})
        self.event("return_browsing", flow=1)
        self.event("calibration_cancel", flow=2)
        self.result()
        self.assertEqual(self.ui, [])
        live = [True]
        self.host.begin_setup(lambda *_: {"ok": True}, valid=lambda: live[0])
        self.event("return_browsing", flow=3)
        live[0] = False
        self.result()
        self.assertFalse(self.ui[-1][1]["ok"])

    def test_return_errors_are_actionable_and_fresh_retry_can_succeed(self):
        self.host.begin_setup(lambda *_: (_ for _ in ()).throw(OSError("Start page could not attach")))
        self.event("return_browsing", start_page=True, flow=1); self.result()
        self.assertIn("could not attach", self.ui[-1][1]["error"])
        self.host.on_return = lambda *_: {"ok": True}
        self.event("return_browsing", flow=2); self.result()
        self.assertTrue(self.ui[-1][1]["ok"])


class SetupConnection(unittest.TestCase):
    def test_disconnect_revokes_camera_without_joining_under_inbox_lock(self):
        session = GazeSession("http://127.0.0.1:1")
        self.addCleanup(session.close)
        turns = VoiceTurns(SimpleNamespace(), session)
        turns.bind(session_key="key", session_id="session")
        host = WebcamHost(lambda *_: False)
        session.webcam = host
        host._thread = Mock()
        host.state, host.profile = "running", {"saved": True}
        turns.bind("disconnect", session_key="key", session_id="session")
        self.assertTrue(host._stop.is_set())
        self.assertEqual(host.state, "stopping")
        host._thread.join.assert_not_called()
        self.assertFalse(turns.coach["rehearsed"])
        self.assertEqual(host.profile, {"saved": True})

    def test_setup_freezes_destination_and_exact_binding_and_rehearsal_coach(self):
        session = GazeSession("http://127.0.0.1:1")
        self.addCleanup(session.close)
        turns = VoiceTurns(SimpleNamespace(), session)
        turns.bind(session_key="key", session_id="session")
        session.configure(mode="webcam")
        source = dict(browser_target="source", browser_document="document", browser_route=2)
        host = WebcamHost(lambda *_: False)
        session.webcam = host
        returned = []
        with patch.object(service, "_VOICE_TURNS", turns), patch.object(session.cdp, "connect", return_value=True), \
             patch.object(session.cdp, "capture_return_owner", return_value=source), \
             patch.object(host, "start", return_value=host.status()), \
             patch.object(session.cdp, "return_to_document", side_effect=lambda owner, valid: returned.append(dict(owner)) or {"ok": valid()}):
            session.start_webcam()
            host.on_rehearsed()
            self.assertTrue(turns.coach["rehearsed"])
            self.assertTrue(turns.coach["greeted"])
            self.assertTrue(host.on_return(False, lambda: True)["ok"])
            self.assertEqual(returned, [source])
            turns.bind(session_key="key", session_id="session")  # New connection, even to the same session.
            self.assertFalse(host.on_return(False, lambda: True)["ok"])
            self.assertEqual(len(returned), 1)
            turns.coach["rehearsed"] = False
            host.on_rehearsed()
            self.assertFalse(turns.coach["rehearsed"])
            self.assertIsNone(session.microphone._stream)


if __name__ == "__main__":
    unittest.main()
