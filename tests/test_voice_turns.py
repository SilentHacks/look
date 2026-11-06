"""Deterministic ownership and delivery checks; no Hermes or Chrome process needed."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from hermes_gaze.voice_turns import VoiceTurns


class Chrome:
    def __init__(self):
        self.events = []
        self.stored = []
        self.resolution_id = 0

    def eval_js(self, script):
        self.events.append(json.loads(script.split("onSessionEvent(", 1)[1].rsplit(");true", 1)[0]))

    def store_hover_snapshot(self, snapshot):
        self.resolution_id += 1
        snapshot["resolution_id"] = self.resolution_id
        snapshot["context"] = f"Resolution: {self.resolution_id}\n" + snapshot.get("context", "")
        self.stored.append(copy.deepcopy(snapshot))
        return self.resolution_id

    def clear_hover_snapshot(self):
        self.resolution_id += 1


class Host:
    def __init__(self):
        self.messages = []
        self.accept = True
        self.during_inject = None

    def inject_message(self, text, *, session_key):
        self.messages.append((text, session_key))
        if self.during_inject:
            self.during_inject()
        return self.accept


class VoiceTurnsTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.chrome = Chrome()
        self.turns = VoiceTurns(self.host, self.chrome)
        self.turns.bind(session_key="host-A", session_id="agent-A", platform="tui")
        self.chrome.events.clear()

    def test_reconnecting_same_session_preserves_queued_question(self):
        self.turns.submit("question", {"context": "queued evidence"})
        self.turns.bind(session_key="host-A", session_id="agent-A")
        self.assertIn("queued evidence", self.pre("question")["context"])

    def pre(self, text, turn="turn-1", session="agent-A", **kwargs):
        return self.turns.pre(session_id=session, user_message=text, turn_id=turn, **kwargs)

    def test_exact_session_and_text_match_before_inject_returns(self):
        snapshot = {"context": "frozen campaign evidence", "snapshot_id": "capture-1", "handles": {"@1": {"kind": "cell"}}}
        captured = []
        self.host.during_inject = lambda: captured.append(self.pre("  explain this  "))
        result = self.turns.submit("  explain this  ", snapshot)
        snapshot["context"] = "changed after submit"
        self.assertTrue(result["ok"])
        self.assertEqual(self.host.messages, [("  explain this  ", "host-A")])
        self.assertIn("frozen campaign evidence", captured[0]["context"])
        self.assertEqual(self.chrome.events[-1]["status"], "thinking")
        self.assertEqual(self.chrome.events[-1]["request_id"], result["request_id"])
        self.assertIsNone(self.pre("  explain this  ", session="agent-B"))
        self.turns.delta(session_id="agent-B", turn_id="turn-1", delta="foreign")
        self.turns.post(session_id="agent-B", turn_id="turn-1", assistant_response="foreign")
        self.assertNotIn("foreign", json.dumps(self.chrome.events))

    def test_queued_snapshots_do_not_displace_active_and_repeated_text_is_fifo(self):
        first = self.turns.submit("explain this", {"context": "first", "snapshot_id": "one"})
        second = self.turns.submit("explain this", {"context": "second", "snapshot_id": "two"})
        self.assertEqual(self.chrome.stored, [])
        self.assertIn("first", self.pre("explain this")["context"])
        third = self.turns.submit("another question", {"context": "third", "snapshot_id": "three"})
        self.assertEqual(len(self.chrome.stored), 1)
        self.turns.post(session_id="agent-A", turn_id="turn-1", assistant_response="one")
        self.assertIn("second", self.pre("explain this", "turn-2")["context"])
        self.assertEqual(self.chrome.events[-1]["request_id"], second["request_id"])
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.turns.delta(session_id="agent-A", turn_id="turn-1", delta="late")
        self.assertNotIn("late", json.dumps(self.chrome.events))
        self.turns.post(session_id="agent-A", turn_id="turn-2", assistant_response="two")
        self.pre("another question", "turn-3")
        self.assertEqual(self.chrome.events[-1]["request_id"], third["request_id"])

    def test_rejected_injection_leaves_no_pending_or_accepted_turn(self):
        self.host.accept = False
        self.assertFalse(self.turns.submit("hello", {"context": "private"})["ok"])
        self.assertIsNone(self.pre("hello"))
        self.assertEqual(self.chrome.stored, [])
        self.assertFalse(any(event["status"] == "queued" for event in self.chrome.events))
        self.host.during_inject = lambda: self.pre("hello", "early")
        self.assertFalse(self.turns.submit("hello", {"context": "private"})["ok"])
        count = len(self.chrome.events)
        self.turns.post(session_id="agent-A", turn_id="early", assistant_response="must not display")
        self.assertEqual(len(self.chrome.events), count)

    def test_typed_turn_preserves_pending_and_followup_streams_without_reinjecting(self):
        result = self.turns.submit("queued words", {"context": "queued evidence", "snapshot_id": "queued"})
        with patch("hermes_gaze.service.resolve_now", return_value={"context": "fresh typed evidence", "snapshot_id": "typed"}):
            context = self.pre("explain this", "typed")
        self.assertIn("fresh typed evidence", context["context"])
        epoch = self.chrome.resolution_id
        self.turns.post(session_id="agent-A", turn_id="typed", assistant_response="The result is 42.")
        history = [{"role": "assistant", "content": "The result is 42."}]
        followup = self.pre("Why 42?", "followup", conversation_history=history)
        self.assertIsNone(followup)
        self.assertEqual(self.chrome.resolution_id, epoch)
        self.assertEqual(len(self.chrome.stored), 1)
        self.assertEqual(history[0]["content"], "The result is 42.")
        self.turns.post(session_id="agent-A", turn_id="followup", assistant_response="Because of the data.")
        self.assertEqual(self.chrome.events[-1]["text"], "Because of the data.")
        self.assertIn("queued evidence", self.pre("queued words", "queued")["context"])
        self.assertEqual(self.chrome.events[-1]["request_id"], result["request_id"])

    def test_answer_only_stream_final_backstop_and_late_callbacks(self):
        self.turns.submit("question", {"context": "evidence"})
        self.pre("question")
        self.turns.delta(session_id="agent-A", turn_id="turn-1", kind="reasoning", delta="private reasoning")
        self.turns.delta(session_id="agent-A", turn_id="turn-1", delta="answer fragment")
        self.turns.end(session_id="agent-A", turn_id="turn-1", completed=True)
        self.assertEqual(self.chrome.events[-1]["text"], "answer fragment")
        self.turns.post(session_id="agent-A", turn_id="turn-1", assistant_response="final answer")
        self.assertEqual(self.chrome.events[-1]["text"], "final answer")
        self.assertEqual(self.chrome.events[-1]["status"], "complete")
        count = len(self.chrome.events)
        self.turns.delta(session_id="agent-A", turn_id="turn-1", delta="late")
        self.turns.post(session_id="agent-A", turn_id="turn-1", assistant_response="duplicate")
        self.turns.end(session_id="agent-A", turn_id="turn-1", failed=True)
        self.assertEqual(len(self.chrome.events), count)
        self.assertNotIn("private reasoning", json.dumps(self.chrome.events))
        self.assertIsNone(self.pre("question"))

    def test_failed_turn_is_terminal_but_binding_survives_for_followup(self):
        self.turns.submit("question", {"context": "real evidence"})
        self.pre("question")
        self.turns.end(session_id="agent-A", turn_id="turn-1", failed=True, completed=False, turn_exit_reason="API failed")
        self.assertEqual(self.chrome.events[-1]["status"], "error")
        self.turns.post(session_id="agent-A", turn_id="turn-1", assistant_response="late")
        self.assertEqual(self.chrome.events[-1]["error"], "API failed")
        self.assertTrue(self.turns.connected)
        epoch = self.chrome.resolution_id
        self.assertIsNone(self.pre("Try again", "retry"))
        self.assertEqual(self.chrome.resolution_id, epoch)
        self.turns.post(session_id="agent-A", turn_id="retry", assistant_response="Retry answer")
        self.assertEqual(self.chrome.events[-1]["text"], "Retry answer")

    def test_rebinding_disconnect_and_unload_reject_old_owner(self):
        self.turns.submit("private words", {"context": "A private page"})
        self.pre("private words")
        self.turns.bind(session_key="host-B", session_id="agent-B", platform="desktop")
        self.assertIsNone(self.pre("private words", "old", session="agent-A"))
        self.assertIsNone(self.pre("followup", "new", session="agent-B"))
        self.turns.delta(session_id="agent-A", turn_id="turn-1", delta="old stream")
        self.assertNotIn("old stream", json.dumps(self.chrome.events))
        self.turns.bind("disconnect", session_key="host-A", session_id="agent-A")
        self.assertTrue(self.turns.connected)
        self.turns.bind("disconnect", session_key="host-B", session_id="agent-B")
        self.assertFalse(self.turns.connected)
        self.assertFalse(self.turns.submit("question", {})["ok"])
        self.turns.bind(session_key="host-B", session_id="agent-B")
        self.turns.close()
        count = len(self.chrome.events)
        self.assertIsNone(self.pre("this", "unloaded", session="agent-B"))
        self.turns.post(session_id="agent-A", turn_id="turn-1", assistant_response="late")
        self.assertEqual(len(self.chrome.events), count)
        self.assertFalse(self.turns.connected)

    def test_injection_return_after_rebind_cannot_write_old_status(self):
        self.host.accept = False
        self.host.during_inject = lambda: self.turns.bind(
            session_key="host-B", session_id="agent-B", platform="desktop"
        )
        result = self.turns.submit("A question", {"context": "A evidence", "session_key": "forged"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.host.messages, [("A question", "host-A")])
        self.assertEqual(self.chrome.events[-1]["text"], "Chrome voice connected.")
        self.assertTrue(self.chrome.events[-1]["session_connected"])
        self.assertIsNone(self.pre("A question", "old"))
        self.assertIsNone(self.pre("followup", "new", session="agent-B"))

    def test_queue_and_context_are_bounded_and_inputs_are_frozen(self):
        self.assertFalse(self.turns.submit("oversized", {"context": "x" * 6001})["ok"])
        source = {"context": "x" * 3000, "handles": {"@1": {"label": "original"}}}
        for i in range(self.turns.MAX_PENDING):
            self.assertTrue(self.turns.submit(f"question {i}", source)["ok"])
        self.assertFalse(self.turns.submit("overflow", {})["ok"])
        source["handles"]["@1"]["label"] = "mutated"
        self.pre("question 0")
        self.assertEqual(self.chrome.stored[0]["handles"]["@1"]["label"], "original")
        self.assertEqual(len(self.host.messages), self.turns.MAX_PENDING)


if __name__ == "__main__":
    unittest.main()
