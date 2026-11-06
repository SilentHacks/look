"""The opt-in experiment must never capture a different session or unrelated turn."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from hermes_gaze.phase0 import PhaseZeroProbe


class TestPhaseZeroProbe(unittest.TestCase):
    def make_probe(self, accepted=True):
        session = SimpleNamespace(overlay_is_live=lambda: True, eval_js=lambda _: True)
        ctx = SimpleNamespace(inject_message=lambda *_, **__: accepted)
        return PhaseZeroProbe(ctx, session)

    def test_exact_session_message_and_turn_are_required(self):
        probe = self.make_probe()
        probe.command("start", session_key="route", session_id="session", platform="tui")
        question = probe.runs["session"]["question"]
        self.assertIsNone(probe.pre(session_id="other", user_message=question, turn_id="one"))
        self.assertIsNone(probe.pre(session_id="session", user_message="unrelated", turn_id="one"))
        context = probe.pre(session_id="session", user_message=question, turn_id="one")
        code = probe.runs["session"]["code"]
        self.assertIn(code, context["context"])
        self.assertIsNone(probe.pre(session_id="session", user_message=question, turn_id="one"))
        probe.delta(session_id="session", turn_id="other", delta="foreign")
        probe.delta(session_id="other", turn_id="one", delta="foreign")
        probe.delta(session_id="session", turn_id="one", delta="private thoughts", kind="reasoning")
        probe.delta(session_id="session", turn_id="one", delta="answer")
        self.assertEqual(probe.runs["session"]["text"], "answer")
        probe.post(session_id="session", turn_id="one", assistant_response="final")
        probe.delta(session_id="session", turn_id="one", delta="late duplicate")
        self.assertEqual(probe.runs["session"]["text"], "answer")
        self.assertEqual(probe.runs["session"]["response"], "final")
        probe.command("followup", session_key="route", session_id="session", platform="tui")
        self.assertEqual(probe.runs["session"]["code"], code)
        context = probe.pre(session_id="session", user_message=probe.runs["session"]["question"], turn_id="two")
        self.assertEqual(context, {})  # The memory experiment must not leak the answer again.
        probe.post(session_id="session", turn_id="one", assistant_response="stale")
        self.assertFalse(probe.runs["session"]["finished"])
        probe.post(session_id="session", turn_id="two", assistant_response=code)
        self.assertTrue(probe.runs["session"]["followup_recalled_code"])

    def test_refused_injection_finishes_and_allows_retry(self):
        probe = self.make_probe(accepted=False)
        response = json.loads(probe.command("start", session_key="route", session_id="session"))
        self.assertFalse(response["accepted"])
        self.assertTrue(probe.runs["session"]["finished"])
        self.assertIn("allow_gateway_injection", response["error"])
        self.assertIsNone(probe.pre(session_id="session", user_message=probe.runs["session"]["question"]))
        probe.ctx.inject_message = lambda *_, **__: True
        self.assertTrue(json.loads(probe.command("start", session_key="route", session_id="session"))["accepted"])
        self.assertIn("still pending", probe.command("start", session_key="route", session_id="session"))
        probe.command("stop", session_key="route", session_id="session")
        self.assertNotIn("session", probe.runs)


if __name__ == "__main__":
    unittest.main()
