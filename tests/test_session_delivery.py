"""Conversation admission must not fall back, execute or retry across boundaries."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hermes_gaze import service
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.config import GazeConfig
from hermes_gaze.voice_turns import VoiceTurns

from tests.test_cursor_context import capture


class TestSessionDelivery(unittest.TestCase):
    def setUp(self):
        self.session = GazeSession(cdp_http_url="http://127.0.0.1:1")
        self.addCleanup(self.session.close)
        self.patches = [mock.patch.object(service, "get_shared_session", return_value=self.session),
                        mock.patch.object(service, "_VOICE_TURNS", None),
                        mock.patch.object(service, "_CONFIG", GazeConfig()),
                        mock.patch.object(self.session, "eval_js", return_value=True)]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def snapshot(self, text):
        return service.resolve_now(self.session, utterance=text, pushed={"cursor_context": capture()}, activate=False)

    def test_unconnected_question_is_read_only_not_an_action_capability(self):
        with mock.patch.object(service, "_LLM", SimpleNamespace(complete_structured=lambda **_: "Table analysis")):
            result = service.submit_snapshot(self.snapshot("What does this table show?"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["delivery"], "one_shot")
        self.assertFalse(result["session_connected"])
        self.assertFalse(self.session.last_hover_snapshot["actions_allowed"])
        self.assertFalse(self.session.actions.click("@4", result["resolution_id"])["ok"])

    def test_unconnected_action_neither_calls_model_nor_activates_a_snapshot(self):
        epoch = self.session.resolution_id
        client = mock.Mock()
        client.complete_structured.side_effect = AssertionError("action must not use one-shot model")
        with mock.patch.object(service, "_LLM", client):
            result = service.submit_snapshot(self.snapshot("Export this table"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["delivery"], "unavailable")
        self.assertEqual(self.session.resolution_id, epoch)
        self.assertIsNone(self.session.last_hover_snapshot)

    def test_recorder_error_cannot_reject_an_already_admitted_turn(self):
        messages = []
        def inject(text, **kwargs):
            messages.append(text)
            return True
        turns = VoiceTurns(SimpleNamespace(inject_message=inject), self.session)
        turns.bind(session_key="route", session_id="session", platform="tui")
        self.addCleanup(turns.close)
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory) / "file-not-directory"
            blocked.write_text("occupied")
            with mock.patch.object(service, "_VOICE_TURNS", turns), \
                    mock.patch.object(service, "_CONFIG", GazeConfig(record_trials=True)), \
                    mock.patch.object(service, "_record_path", return_value=blocked / "replay.jsonl"):
                result = service.submit_snapshot(self.snapshot("Summarize this table"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["delivery"], "session")
        self.assertIn("record_error", result)

    def test_replay_requires_explicit_development_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.jsonl"
            with mock.patch.object(service, "_record_path", return_value=path):
                service.resolve_now(self.session, utterance="Explain this", pushed={"cursor_context": capture()})
                self.assertFalse(path.exists())
                with mock.patch.object(service, "_CONFIG", GazeConfig(record_trials=True)):
                    service.resolve_now(self.session, utterance="Explain this", pushed={"cursor_context": capture()})
            event = json.loads(path.read_text())
            self.assertEqual(event["type"], "cursor_context")
            self.assertLessEqual(len(event["context"]), 6000)
            self.assertNotIn("audio", event)
    def test_full_connected_queue_cannot_displace_context_with_one_shot(self):
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda *_, **__: True), self.session)
        turns.bind(session_key="route", session_id="session", platform="tui")
        self.addCleanup(turns.close)
        for index in range(turns.MAX_PENDING + 1):
            self.assertTrue(turns.submit(f"queued {index}", self.snapshot("Explain this"))["ok"])
        epoch = self.session.resolution_id
        saved = self.session.last_hover_snapshot
        client = mock.Mock()
        client.complete_structured.side_effect = AssertionError("queue overflow must not use fallback")
        with mock.patch.object(service, "_VOICE_TURNS", turns), mock.patch.object(service, "_LLM", client):
            result = service.submit_snapshot(self.snapshot("What does this table show?"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["delivery"], "unavailable")
        self.assertEqual(self.session.resolution_id, epoch)
        self.assertIs(self.session.last_hover_snapshot, saved)

    def test_connected_targetless_speech_is_plain_text_without_activating_evidence(self):
        messages = []
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda text, **_: messages.append(text) or True), self.session)
        turns.bind(session_key="route", session_id="session", platform="tui")
        self.addCleanup(turns.close)
        epoch = self.session.resolution_id
        with mock.patch.object(service, "_VOICE_TURNS", turns):
            delivered = service.submit_snapshot({"ok": False, "utterance": "Hello there",
                                                 "context": "unavailable target", "error": "No target"})
            self.assertTrue(delivered["ok"])
            self.assertIsNone(turns.pre(session_id="session", turn_id="plain", user_message=messages[0]))
            self.assertEqual(self.session.resolution_id, epoch)
            self.assertIsNone(self.session.last_hover_snapshot)
            refused = service.submit_snapshot({"ok": False, "utterance": "Explain this", "context": "",
                                               "error": "No target"})
            self.assertFalse(refused["ok"])

    def test_inbox_research_cannot_click_and_new_capture_revokes_confirmation(self):
        from hermes_gaze.resolver.cursor_context import build_context
        from tests.test_snapshot_actions import BrowserActions

        browser = BrowserActions()
        self.addCleanup(setattr, self.session, "_cdp", self.session._cdp)
        self.session._cdp = browser
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda *_, **__: True), self.session)
        turns.bind(session_key="route", session_id="session", platform="tui")
        self.addCleanup(turns.close)
        snapshot = {"ok": True, "snapshot_id": "snapshot-1", "mode": "hover",
                    "pointed": [{"id": "@purge", "available": True}],
                    "handles": {h: {"label": n["label"]} for h, n in browser.nodes.items()},
                    "context": build_context(["control @purge: Purge cache"], "Purge this cache", "button Purge cache")}
        turns.submit("Purge this cache", snapshot)
        turns.pre(session_id="session", turn_id="first", user_message=turns.active["wire"])
        epoch = self.session.resolution_id
        self.assertEqual(browser.highlights, [["@purge"]])
        self.assertFalse(self.session.actions.click("@purge", epoch)["ok"])
        # Fresh manual pointing remains the action path; an inbox capture revokes its approval.
        self.session.store_hover_snapshot(snapshot)
        epoch = self.session.resolution_id
        pending = self.session.actions.click("@purge", epoch)
        self.assertTrue(pending["confirmation_required"])
        approval = browser.pending["action_id"]
        turns.submit("Another question", self.snapshot("Explain this"))
        self.assertFalse(self.session.actions.confirm(approval, epoch, True)["ok"])
        self.assertEqual(browser.executed, [])

    def test_connected_typed_deictic_highlights_fresh_evidence_before_answer(self):
        from tests.test_snapshot_actions import BrowserActions
        browser = BrowserActions()
        self.addCleanup(setattr, self.session, "_cdp", self.session._cdp)
        self.session._cdp = browser
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda *_, **__: True), self.session)
        turns.bind(session_key="route", session_id="session")
        self.addCleanup(turns.close)
        saved = self.snapshot("Explain this")
        saved.update(snapshot_id="snapshot-1", pointed=[{"id": "@purge", "available": True}],
                     handles={"@purge": {"label": "Purge"}})
        with mock.patch.object(service, "resolve_now", return_value=saved):
            context = turns.pre(session_id="session", turn_id="typed", user_message="Explain this")
        self.assertEqual(browser.highlights, [["@purge"]])
        self.assertEqual(context["context"], self.session.last_hover_snapshot["context"])

    def test_connected_simulated_turn_preserves_the_lens_choice(self):
        self.session.configure(mode="simulated")
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda *_, **__: True), self.session)
        turns.bind(session_key="route", session_id="session", platform="tui")
        self.addCleanup(turns.close)
        pushed = {"pointer": {"x_vp": 30, "y_vp": 30}, "fixations": [],
                  "candidates": [{"id": "purge", "tag": "button", "role": "button",
                                  "label": "Purge Cache", "selector": "#purge",
                                  "rect_vp": [10, 10, 100, 40], "is_interactive": True,
                                  "is_destructive": True, "is_direct_hit": True}],
                  "page_url": "https://demo.invalid/"}
        resolve = service.resolve_now
        with mock.patch.object(service, "resolve_now",
                               side_effect=lambda session, **kwargs: resolve(session, pushed=pushed, **kwargs)):
            turns.pre(session_id="session", turn_id="simulated", user_message="Purge this cache")
        choice = self.session.choose(resolution_id=self.session.resolution_id, execute=False)
        self.assertTrue(choice["ok"], choice)
        self.assertEqual(choice["selected"]["id"], "purge")

    def test_slow_transcription_releases_intents_and_preserves_capture_order(self):
        import threading
        from hermes_gaze import voice
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        replies = []
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda *_, **__: True), self.session)
        turns.bind(session_key="route", session_id="session")
        self.addCleanup(turns.close)
        def transcribe(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("test ASR release")
            return "What is this?", []
        def reply(result):
            replies.append(result)
            if len([r for r in replies if r.get("type") != "record_reserved"]) == 2:
                finished.set()
        intent = {"type": "record_stop", "nonce": self.session._intent_nonce,
                  "_browser_target": "source", "_browser_document": "document",
                  "cursor_context": capture()}
        with mock.patch.object(service, "_VOICE_TURNS", turns), \
                mock.patch.object(self.session.microphone, "stop", return_value=(b"audio", 100.)), \
                mock.patch.object(voice, "transcribe_audio_buffer", side_effect=transcribe):
            try:
                service.handle_intent(intent, reply)
                self.assertTrue(entered.wait(1))
                service.handle_intent({**intent, "cursor_context": capture()}, reply)
                self.assertEqual([r["status"] for r in turns.pending], ["transcribing", "transcribing"])
                self.assertEqual([r for r in replies if r.get('type') != 'record_reserved'], [])
            finally:
                release.set()
                self.assertTrue(finished.wait(3))
        self.assertTrue(all(r["ok"] for r in replies))
        self.assertEqual(turns.active["snapshot"]["browser_target"], "source")
        self.assertEqual(turns.pending[0]["snapshot"]["browser_document"], "document")



if __name__ == "__main__":
    unittest.main()
