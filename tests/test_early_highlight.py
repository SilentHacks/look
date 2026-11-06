"""Consent, deadline, frozen identity and fallback semantics for intended scope."""
import copy
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hermes_gaze.config import GazeConfig
from hermes_gaze.early_highlight import EarlyHighlight, request_payload


class EarlyHighlightTests(unittest.TestCase):
    def test_consent_and_frozen_choices(self):
        snapshot = dict(utterance='Compare these cards', top={'role': 'h3'}, pointed=[{}],
                        context='SECRET PAGE @123 https://private.invalid',
                        scope_bundles={'none': [], 'pointed': ['@123'], 'group': ['@456']})
        private = request_payload(snapshot, GazeConfig())
        self.assertNotIn('SECRET', json.dumps(private))
        self.assertNotIn('@123', json.dumps(private))
        self.assertNotIn('private.invalid', json.dumps(private))
        public = request_payload(snapshot, GazeConfig(highlight_include_page_text=True))
        self.assertEqual(public['state']['captured_page_evidence'], snapshot['context'])

    def test_success_none_failure_deadline_and_stale_identity(self):
        for choice in ('row', 'none', 'forged', None, 'late', 'stale'):
            with self.subTest(choice=choice):
                fallback, highlights = [], []
                snapshot = dict(utterance='whole row', context='PRIVATE_PAGE_TEXT', top={'role': 'td'},
                    pointed=[{}], scope_bundles={'none': [], 'row': ['@row']},
                    handles={'@row': {}}, resolution_id=4)
                session = SimpleNamespace(last_hover_snapshot=snapshot, resolution_id=4,
                    actions=SimpleNamespace(_lock=threading.RLock(), highlight=lambda h, r: highlights.append((h, r))))
                release, entered = threading.Event(), threading.Event()
                class Response:
                    def __enter__(self):
                        entered.set()
                        release.wait(2)
                        return self
                    def __exit__(self, *_):
                        pass
                    def read(self, _):
                        return json.dumps({'answers': {'scope': {'choice': 'row' if choice in ('late', 'stale') else choice}}}).encode()
                with patch.dict('os.environ', TYPESAFE_API_KEY='test-only'), patch('urllib.request.urlopen', return_value=Response()) as network:
                    state = EarlyHighlight(session, snapshot, GazeConfig(), lambda *a, **k: fallback.append(a))
                    self.assertTrue(entered.wait(1))
                    wire = json.loads(network.call_args.args[0].data)
                    self.assertNotIn('PRIVATE_PAGE_TEXT', json.dumps(wire))
                    self.assertNotIn('@row', json.dumps(wire))
                    self.assertIs(copy.deepcopy(state), state)
                    state.after_answer('answer')
                    self.assertEqual(fallback, [])
                    if choice == 'late':
                        state.complete(None)  # hard deadline wins over late network success
                    if choice == 'stale':
                        session.resolution_id += 1
                    release.set()
                    # Synchronize completion without a timing assertion on CI scheduling.
                    for thread in threading.enumerate():
                        if thread.name == 'gaze-scope':
                            thread.join(3)
                self.assertEqual(len(highlights), int(choice == 'row'))
                self.assertEqual(len(fallback), int(choice in ('forged', None, 'late')))

    def test_no_key_uses_post_answer_only(self):
        fallback = []
        with patch.dict('os.environ', {}, clear=True), patch('urllib.request.urlopen') as network:
            state = EarlyHighlight(None, {}, GazeConfig(), lambda *a, **k: fallback.append(a))
            state.after_answer('answer')
        network.assert_not_called()
        self.assertEqual(len(fallback), 1)
