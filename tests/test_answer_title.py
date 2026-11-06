"""Request-owned headings: streaming, final reconciliation and recovery."""
import time
import unittest
from types import SimpleNamespace

from hermes_gaze.answer_title import INSTRUCTION, TitleStream
from hermes_gaze.voice_turns import VoiceTurns
from .test_companion_ui import Chrome, snapshot


class Parser(unittest.TestCase):
    def test_every_split_and_lossless_fallback(self):
        cases = [("## musl\n\nAnswer prose", "musl", "Answer prose"),
                 ("## Python or\r\n\r\nAnswer", "Python or", "Answer"),
                 ("Ordinary prose", None, "Ordinary prose"),
                 ("## Cut", None, "## Cut"),
                 ("## Title\n\n", None, "## Title\n\n"),
                 ("# Wrong\n\nBody", None, "# Wrong\n\nBody"),
                 ("## One two three four five\n\nBody", None, "## One two three four five\n\nBody"),
                 ("## @1\n\nBody", None, "## @1\n\nBody")]
        for raw, title, body in cases:
            for split in range(len(raw) + 1):
                parser = TitleStream()
                visible = parser.feed(raw[:split]) + parser.feed(raw[split:]) + parser.finish()
                self.assertEqual((parser.title, visible), (title, body), (raw, split))
                self.assertEqual(parser.final(raw), body)
                self.assertEqual(parser.final(raw), body)

    def test_bound_and_no_retroactive_stripping(self):
        parser = TitleStream()
        self.assertEqual(parser.feed("x" * 97), "x" * 97)
        self.assertTrue(parser.decided)
        parser = TitleStream()
        self.assertEqual(parser.feed("## musl\n"), "")
        self.assertEqual(parser.finish(), "## musl\n")
        self.assertEqual(parser.feed("\nBody"), "\nBody")
        self.assertEqual(parser.final("## musl\n\nBody"), "## musl\n\nBody")
        self.assertIsNone(parser.title)


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.chrome = Chrome()
        self.turns = VoiceTurns(SimpleNamespace(inject_message=lambda *a, **k: True), self.chrome)
        self.turns.bind(session_key="k", session_id="s")
        self.addCleanup(self.turns.close)

    def start(self, turn="t"):
        return self.turns.pre(session_id="s", turn_id=turn, user_message=self.turns.active["wire"])

    def delta(self, text, turn="t", **kw):
        self.turns.delta(session_id="s", turn_id=turn, delta=text, **kw)

    def post(self, text, turn="t"):
        return self.turns.post(session_id="s", turn_id=turn, assistant_response=text)

    def test_queue_title_body_final_speech_and_followup(self):
        item = self.turns.submit("q", snapshot("Fallback"))["item_id"]
        self.turns.submit("next", snapshot("Waiting"))
        self.assertEqual(self.start()["context"], INSTRUCTION + "\n\nctx")
        self.delta("## musl\n")
        self.assertEqual(self.turns.items[0]["model_subject"], "")
        self.delta("\nBody")
        self.assertEqual(self.chrome.events[-1]["items"][0]["subject"], "musl")
        self.assertEqual(self.turns.selected, "")
        self.assertFalse(self.turns.items[0]["unread"])
        self.assertEqual(len(self.turns.pending), 1)
        self.assertEqual(self.post("## musl\n\nBody"), "Body")
        self.assertEqual(self.post("## Wrong\n\nLate"), "Body")
        spoken = []
        self.turns._speak = lambda text: spoken.append(text) or {"ok": True}
        self.turns.control("speak", item)
        self.assertEqual(spoken, ["Body"])
        self.turns.end(session_id="s", turn_id="t")
        self.start("next")
        self.post("No heading answer", "next")
        self.turns.end(session_id="s", turn_id="next")
        self.assertEqual(self.turns.items[1]["model_subject"], "")
        self.turns.submit("more", {}, item)
        self.start("follow")
        self.assertEqual(self.post("## Different\n\nFollowup", "follow"), "Followup")
        self.assertEqual(self.turns.items[0]["model_subject"], "musl")

    def test_real_timeout_and_final_passthrough(self):
        self.turns.submit("q", snapshot("Fallback"))
        self.start()
        self.delta("## Slow\n")
        deadline = time.monotonic() + 2
        while not self.turns.active["title_stream"].decided and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.turns.active["text"], "## Slow\n")
        self.delta("\nBody")
        self.assertEqual(self.post("## Slow\n\nBody"), "## Slow\n\nBody")
        self.assertEqual(self.turns.items[0]["model_subject"], "")

    def test_interrupt_retry_and_late_hooks(self):
        item = self.turns.submit("q", snapshot("Fallback"))["item_id"]
        self.start()
        self.delta("## Cut")
        old = self.turns.active
        self.turns.end(session_id="s", turn_id="t", interrupted=True)
        self.assertEqual(old["text"], "## Cut")
        self.turns.control("retry", item)
        self.start("retry")
        self.delta("## Late\n\nWrong", turn="t")
        self.post("## Late\n\nWrong", "t")
        self.assertEqual(self.post("## New title\n\nRetry body", "retry"), "Retry body")
        self.assertEqual(self.turns.items[0]["model_subject"], "")
        self.assertEqual(old["text"], "## Cut")

    def test_disconnect_flushes_and_does_not_release_host(self):
        item = self.turns.submit("q", snapshot())["item_id"]
        self.start()
        self.delta("## Cut")
        old = self.turns.active
        self.turns.bind("disconnect", session_key="k", session_id="s")
        self.assertEqual(old["text"], "## Cut")
        self.assertIsNone(old["title_timer"])
        self.turns.bind(session_key="k", session_id="s")
        self.turns.control("retry", item)
        self.assertIs(self.turns.active, old)
        self.post("## Late\n\nWrong")
        self.assertEqual(self.turns.items[0]["model_subject"], "")
        self.turns.end(session_id="s", turn_id="t", interrupted=True)
        self.assertIsNot(self.turns.active, old)

    def test_foreign_and_reasoning_do_not_name_or_buffer(self):
        self.turns.submit("q", snapshot())
        self.start()
        self.delta("## Reason\n\nWrong", kind="reasoning")
        self.delta("## Foreign\n\nWrong", turn="foreign")
        self.assertFalse(self.turns.active["title_stream"].started)
        self.assertIsNone(self.turns.active["title_timer"])
        self.assertIsNone(self.turns.pre(session_id="s", turn_id="other", user_message="Hello"))

    def test_unheaded_stream_keeps_immediate_name_and_body(self):
        self.turns.submit("q", snapshot("Permanent fallback"))
        self.start()
        self.delta("Plain answer")
        self.assertEqual(self.turns.active["text"], "Plain answer")
        self.assertEqual(self.chrome.events[-1]["items"][0]["subject"], "Permanent fallback")
        self.assertEqual(self.post("Plain answer continues"), "Plain answer continues")
        self.assertEqual(self.chrome.events[-1]["items"][0]["subject"], "Permanent fallback")

    def test_interrupted_body_keeps_promoted_name_through_retry(self):
        item = self.turns.submit("q", snapshot("Fallback"))["item_id"]
        self.start()
        self.delta("## First subject\n\nPartial body")
        self.turns.end(session_id="s", turn_id="t", interrupted=True)
        self.assertEqual(self.turns.runs[0]["text"], "Partial body")
        self.turns.control("retry", item)
        self.start("retry")
        self.post("## Another subject\n\nRecovered", "retry")
        self.assertEqual(self.chrome.events[-1]["items"][0]["subject"], "First subject")


if __name__ == "__main__":
    unittest.main()
