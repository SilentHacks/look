"""Python-owned companion state: names, spoken text, plain errors and stack."""
from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace

from hermes_gaze import service
from hermes_gaze.naming import clean_subject, plain_error, safe_link, speech_text, subject_hint
from hermes_gaze.resolver.cursor_context import cursor_result
from hermes_gaze.voice_turns import VoiceTurns


class Chrome:
    def __init__(self):
        self.events = []
        self.actions = SimpleNamespace(invalidate=lambda: None, _lock=threading.RLock())
        self.last_hover_snapshot = None
        self.resolution_id = 0

    def display_session_event(self, event):
        self.events.append(event)

    def clear_hover_snapshot(self):
        pass


def snapshot(name="MacBook deal", count=1, **extra):
    return {"ok": True, "mode": "hover", "utterance": "q", "context": "ctx", "page_url": "https://shop.example/deals",
            "top": {"label": "Long page label"}, "ranked": [{"id": "@1"}], "pointed": [], "subject": {"name": name, "count": count}, **extra}


class Names(unittest.TestCase):
    def test_crude_page_text_becomes_a_short_name(self):
        self.assertEqual(clean_subject("(NEW) Sennheiser Premium Headphones"), "Sennheiser Premium Headphones")
        self.assertEqual(clean_subject("Firecracker VM Escape: PwnEscape Part 2"), "Firecracker VM Escape")
        self.assertEqual(clean_subject("$39.99-$154.99 Altra, Saucony, adidas, & ASICS"), "Altra, Saucony, adidas, & ASICS")
        shortened = clean_subject("A Jev that can ask Opus for help gives Opus accuracy at 4x lower cost")
        self.assertLessEqual(len(shortened), 32)
        self.assertFalse(shortened.lower().startswith("a "))
        self.assertNotIn(shortened.split()[-1].lower(), ("for", "that", "the", "of"))

    def test_names_never_carry_protocol_tokens_or_handles(self):
        for bad in ("Delete @12 row", "[Browsing inbox abc; request def]", "<browser_context>", "resolution 12", "gaze_click now", "</page_data>"):
            self.assertEqual(clean_subject(bad), "", bad)
            self.assertEqual(subject_hint({"name": bad})[0], "", bad)

    def test_count_is_bounded(self):
        self.assertEqual(subject_hint({"name": "A", "count": 99})[1], 5)
        self.assertEqual(subject_hint({"name": "A", "count": "x"})[1], 1)
        self.assertEqual(subject_hint("nope"), ("", 1))


class Spoken(unittest.TestCase):
    def test_read_aloud_has_no_markup_characters(self):
        spoken = speech_text("# Title\n**bold** and *it* `code` ~~gone~~ [link](https://a.test/c) ![img](https://x.test/y.png)\n"
                             "- one\n1. two\n> quote\n```py\nx = 1\n```\n| a | b |\n|---|---|\n| 1 | 2 |\nsnake_case stays and 2 * 3 too\n")
        for raw in ("#", "**", "`", "~~", "](", "https://", "|", "---", "x = 1", ">"):
            self.assertNotIn(raw, spoken, raw)
        for word in ("Title", "bold", "it", "link", "one", "two", "quote", "a, b", "snake_case", "2 * 3"):
            self.assertIn(word, spoken, word)

    def test_turn_reads_the_plain_text(self):
        chrome = Chrome()
        turns = VoiceTurns(SimpleNamespace(inject_message=lambda *a, **k: True), chrome)
        spoken = []
        turns._speak = lambda text: spoken.append(text) or {"ok": True}
        turns.bind(session_key="k", session_id="s")
        item = turns.submit("q", snapshot())["item_id"]
        turns.pre(session_id="s", turn_id="t", user_message=turns.active["wire"])
        turns.post(session_id="s", turn_id="t", assistant_response="**Hello** there")
        turns.end(session_id="s", turn_id="t")
        self.assertTrue(turns.control("speak", item)["ok"])
        self.assertEqual(spoken, ["Hello there"])


class Errors(unittest.TestCase):
    def test_one_plain_sentence_never_raw_provider_text(self):
        cases = [("failed", "HTTP 429 from provider xyz", "rate limited"), ("failed", "No speech recognized", "catch"),
                 ("interrupted", "Disconnected", "disconnected"), ("interrupted", "user stop", "interrupted"),
                 ("failed", "Traceback in provider.py line 3", "couldn’t finish")]
        for status, raw, want in cases:
            sentence = plain_error(status, raw)
            self.assertIn(want, sentence)
            self.assertNotIn("xyz", sentence)
            self.assertNotIn("provider", sentence)


class Links(unittest.TestCase):
    def test_only_clean_http_links(self):
        self.assertEqual(safe_link("https://a.test/x?y=1"), "https://a.test/x?y=1")
        for bad in ("javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "chrome://settings", "https://u:p@a.test/", "https://a.test/\nb", "", None, "/relative"):
            self.assertEqual(safe_link(bad), "", bad)


class Stack(unittest.TestCase):
    def setUp(self):
        self.chrome = Chrome()
        self.ctx = SimpleNamespace(inject_message=lambda *a, **k: True)
        self.turns = VoiceTurns(self.ctx, self.chrome)
        self.turns.bind(session_key="k", session_id="s")

    def finish(self, turn="t"):
        wire = self.turns.active["wire"]
        self.turns.pre(session_id="s", turn_id=turn, user_message=wire)
        self.turns.post(session_id="s", turn_id=turn, assistant_response="answer")
        self.turns.end(session_id="s", turn_id=turn)

    def last(self):
        return self.chrome.events[-1]

    def test_inbox_carries_the_view_state_across_tabs(self):
        item = self.turns.submit("q", snapshot(count=2))["item_id"]
        entry = self.last()["items"][0]
        self.assertEqual((entry["subject"], entry["target_count"], entry["archived"], entry["presented"]), ("MacBook deal", 2, False, False))
        self.finish()
        self.assertFalse(self.last()["items"][0]["presented"])
        self.turns.control("select", item)
        self.assertTrue(self.last()["items"][0]["presented"])
        self.turns.control("retreat")
        self.assertTrue(self.last()["items"][0]["archived"])
        self.assertEqual(self.last()["selected_item_id"], "")
        self.turns.control("recall")
        self.assertFalse(self.last()["items"][0]["archived"])

    def test_retreat_leaves_unseen_answers_but_dismiss_answers_for_them(self):
        one = self.turns.submit("one", snapshot("One"))["item_id"]
        self.finish("a")
        self.turns.submit("two", snapshot("Two"))
        self.finish("b")
        self.turns.control("select", one)
        self.turns.control("retreat")
        self.assertEqual([i["archived"] for i in self.last()["items"]], [True, False])
        self.turns.control("dismiss")
        self.assertEqual([i["archived"] for i in self.last()["items"]], [True, True])

    def test_nothing_in_flight_is_archived(self):
        self.turns.submit("q", snapshot())
        self.turns.control("dismiss")
        self.assertFalse(self.last()["items"][0]["archived"])

    def test_the_open_card_does_not_become_unread_when_it_finishes(self):
        item = self.turns.submit("q", snapshot())["item_id"]
        self.turns.control("select", item)
        self.finish()
        self.assertFalse(self.last()["items"][0]["unread"])

    def test_follow_up_brings_an_archived_card_back(self):
        item = self.turns.submit("q", snapshot())["item_id"]
        self.finish()
        self.turns.control("select", item)
        self.turns.control("retreat")
        self.assertTrue(self.turns.submit("more", {}, item)["ok"])
        self.assertFalse(self.last()["items"][0]["archived"])

    def test_covered_page_says_so_plainly(self):
        self.turns.submit("q", snapshot(ranked=[{"id": "@1", "surface": "Pointer is on an overlay/dialog or wide fixed/sticky surface; underlying page content may be covered."}]))
        self.assertIn("banner or dialog", self.last()["items"][0]["notice"])

    def test_coach_is_bounded(self):
        self.turns.set_coach({"heard": 3, "answered": "x", "evil": 1, "retreated": 1})
        coach = self.last()["coach"]
        self.assertEqual((coach["heard"], coach["answered"], coach["retreated"]), (3, 0, True))
        self.assertNotIn("evil", coach)

    def test_no_dom_identity_reaches_the_ui_state(self):
        self.turns.submit("q", snapshot(handles={"@1": {"selector": "#x"}}))
        self.assertNotIn("@1", json.dumps(self.last()))
        self.assertNotIn("#x", json.dumps(self.last()))



class LitEvidence(unittest.TestCase):
    def test_everything_lit_is_pointed_even_without_timed_words(self):
        def target(handle, label):
            return {"id": handle, "available": True, "label": label, "role": "a", "block_ids": []}
        capture = {"version": 1, "snapshot_id": "s", "captured_at": 10., "page_url": "https://x.test/", "page_title": "T",
                   "history": [{"id": "@1", "start": 1., "end": 2., "last_seen": 2.}, {"id": "@2", "start": 2., "end": 3., "last_seen": 3.}],
                   "targets": [target("@1", "First"), target("@2", "Second")], "blocks": [], "controls": [],
                   "handles": {"@1": {}, "@2": {}}, "lit": ["@1", "@2", "@999"]}
        result = cursor_result(capture, "Compare these", None, 10.)
        self.assertEqual([p["id"] for p in result["pointed"] if p["available"]], ["@2", "@1"])
        self.assertEqual(result["pointed"][-1]["id"], "@999")
        self.assertFalse(result["pointed"][-1]["available"])
        self.assertIn("lit target evidence unavailable", result["context"])
        self.assertIn("First", result["context"])
        self.assertIn("Second", result["context"])


class Intents(unittest.TestCase):
    def test_open_link_rejects_everything_but_clean_http(self):
        session = SimpleNamespace(_intent_nonce="n", cdp=SimpleNamespace(open_url=lambda url: opened.append(url)))
        opened = []
        real, service.get_shared_session = service.get_shared_session, lambda: session
        self.addCleanup(lambda: setattr(service, "get_shared_session", real))
        for url in ("javascript:alert(1)", "data:text/html,x", "file:///x", "https://u:p@a.test/"):
            out = []
            service.handle_intent({"type": "open_link", "url": url, "nonce": "n"}, out.append)
            self.assertFalse(out[0]["ok"])
        out = []
        service.handle_intent({"type": "open_link", "url": "https://a.test/", "nonce": "bad"}, out.append)
        self.assertFalse(out[0]["ok"])
        self.assertEqual(opened, [])
        service.handle_intent({"type": "open_link", "url": "https://a.test/", "nonce": "n"}, out.append)
        self.assertEqual(opened, ["https://a.test/"])


if __name__ == "__main__":
    unittest.main()
