"""Inbox ordering, frozen evidence, ownership and recovery; no host process."""
import copy
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from hermes_gaze.runtime.voice_turns import VoiceTurns
from hermes_gaze.resolver.cursor_context import build_context, stamp_resolution


class Chrome:
    def __init__(self):
        self.events, self.stored = [], []
        self.resolution_id = 0
        self.actions = SimpleNamespace(invalidate=lambda: None)

    def display_session_event(self, event):
        self.events.append(copy.deepcopy(event))

    def store_hover_snapshot(self, snapshot):
        self.resolution_id += 1
        snapshot['context'] = stamp_resolution(snapshot['context'], self.resolution_id)
        self.stored.append(copy.deepcopy(snapshot))
        snapshot['resolution_id'] = self.resolution_id
        self.last_hover_snapshot = copy.deepcopy(snapshot)
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


def snapshot(label):
    lines = [f'pointed deal {label}; price {label} pounds', 'peer ' * 300]
    return dict(ok=True, mode='hover', context=build_context(lines, 'price?', label),
                page_lines=lines, pointer_evidence=label, top={'label': label},
                page_url='https://deals.invalid/' + label, snapshot_id=label)


class VoiceTurnsTests(unittest.TestCase):
    def setUp(self):
        self.host, self.chrome = Host(), Chrome()
        self.turns = VoiceTurns(self.host, self.chrome)
        self.turns.bind(session_key='route', session_id='session')

    def pre(self, turn):
        return self.turns.pre(session_id='session', turn_id=turn,
                              user_message=self.host.messages[-1][0])

    def post(self, turn, answer):
        self.turns.post(session_id='session', turn_id=turn, assistant_response=answer)

    def end(self, turn, **kwargs):
        self.turns.end(session_id='session', turn_id=turn, **kwargs)

    def test_failed_asr_retains_retry_but_does_not_block_resume(self):
        first = self.turns.capture(snapshot('first'), transcribing=True)
        second = self.turns.capture(snapshot('second'), transcribing=True)
        self.turns.transcribed(first['request_id'], '', error='No speech recognized')
        self.turns.transcribed(second['request_id'], 'Second question', snapshot('second'))
        self.assertEqual(self.host.messages, [])
        self.turns.control('resume')
        self.assertIn('Second question', self.host.messages[0][0])
        self.assertEqual(self.turns.runs[0]['status'], 'failed')
        self.assertEqual(self.turns.items[0]['item_id'], first['item_id'])
        # Retried ASR returns to FIFO, but cannot steal the active host turn.
        ready = threading.Event()
        def retry():
            self.turns.transcribed(first['request_id'], 'First retried')
            ready.set()
        self.turns.runs[0]['transcribe'] = retry
        self.assertTrue(self.turns.control('retry', first['item_id'], first['request_id'])['ok'])
        self.assertTrue(ready.wait(1))
        self.assertEqual(len(self.host.messages), 1)
        self.pre('second')
        self.end('second')
        self.assertIn('First retried', self.host.messages[-1][0])
        self.turns.close()

    def test_long_multichunk_answer_keeps_opening_through_final_recall_and_speech(self):
        item = self.turns.submit('Explain this', snapshot('target'))
        self.pre('long')
        body = 'Opening recommendation.\n\n```python\n' + 'x = 1\n' * 2200 + 'CLOSING'
        answer = '## Target\n\n' + body
        spoken = []
        self.turns._playback.play = lambda text, *_: spoken.append(text)
        self.turns.control('auto_speak')
        for chunk in ('## Tar', 'get\n\n', body[:7000], body[7000:12000], body[12000:]):
            self.turns.delta(session_id='session', turn_id='long', delta=chunk)
        run = self.turns.active
        self.assertEqual(run['text'], body[:self.turns.MAX_TEXT])
        streamed = self.chrome.events[-1]['items'][0]['conversation'][0]
        self.assertEqual(streamed['text'], body[:self.turns.MAX_TEXT])
        self.assertEqual(streamed['answer_notice'], self.turns.TRUNCATION_NOTICE)
        self.post('long', answer)
        if self.turns._speech_thread:
            self.turns._speech_thread.join(1)
        self.end('long')
        self.turns.control('dismiss')
        self.turns.control('recall')
        recalled = self.chrome.events[-1]['items'][0]['conversation'][0]
        self.assertEqual(recalled['text'], body[:self.turns.MAX_TEXT])
        self.assertEqual(recalled['answer_notice'], self.turns.TRUNCATION_NOTICE)
        self.assertTrue(self.turns.control('speak', item['item_id'], item['request_id'])['ok'])
        if self.turns._speech_thread:
            self.turns._speech_thread.join(1)
        self.assertEqual(len(spoken), 2)
        for text in spoken:
            self.assertTrue(text.startswith('Opening recommendation.'))
            self.assertEqual(text.count(self.turns.TRUNCATION_NOTICE), 1)
            self.assertNotIn('```', text)
            self.assertNotIn('CLOSING', text)
            self.assertLessEqual(len(text), self.turns.MAX_TEXT + len(self.turns.TRUNCATION_NOTICE) + 2)
        self.assertEqual(run['text'], body[:self.turns.MAX_TEXT])
        self.assertEqual(run['title_stream'].pending, '')
        self.turns.close()

    def test_retention_boundary_final_replacement_and_large_single_chunk(self):
        self.turns.submit('Explain', snapshot('target'))
        self.pre('limit')
        opening = 'First words. ' + 'a' * (self.turns.MAX_TEXT - len('First words. '))
        self.turns.delta(session_id='session', turn_id='limit', delta=opening)
        run = self.turns.active
        self.assertEqual(run['text'], opening)
        self.assertFalse(run['truncated'])
        # Crossing the cap publishes the notice even inside the stream throttle window.
        self.turns.delta(session_id='session', turn_id='limit', delta='overflow')
        self.assertEqual(self.chrome.events[-1]['items'][0]['conversation'][0]['answer_notice'],
                         self.turns.TRUNCATION_NOTICE)
        self.turns.delta(session_id='session', turn_id='limit', delta='tail' * 100000)
        self.assertEqual(run['text'], opening)
        self.post('limit', 'Short final answer.')
        self.assertEqual(run['text'], 'Short final answer.')
        self.assertFalse(run['truncated'])
        self.assertEqual(self.chrome.events[-1]['items'][0]['conversation'][0]['answer_notice'], '')
        self.end('limit')
        self.turns.submit('Next', snapshot('next'))
        self.pre('huge')
        huge = '## Next\n\nOpening.\n\n[unfinished](https://example.invalid/' + 'z' * 100000
        self.turns.delta(session_id='session', turn_id='huge', delta=huge)
        run = self.turns.active
        expected = huge.partition('\n\n')[2][:self.turns.MAX_TEXT]
        self.assertEqual(run['text'], expected)
        self.assertTrue(run['truncated'])
        self.assertEqual(run['title_stream'].pending, '')
        self.post('huge', huge)
        self.end('huge')
        self.assertEqual(run['text'], expected)
        self.assertEqual(self.chrome.events[-1]['items'][1]['conversation'][0]['answer_notice'],
                         self.turns.TRUNCATION_NOTICE)
        self.turns.close()

    def test_final_only_and_interrupted_stream_use_the_same_prefix_bound(self):
        self.turns.submit('Explain', snapshot('target'))
        self.pre('final-only')
        body = 'Opening.\n\n' + '<script>not executable</script> ' * 1000
        self.post('final-only', '## Target\n\n' + body)
        self.assertEqual(self.turns.active['text'], body[:self.turns.MAX_TEXT])
        self.assertTrue(self.turns.active['truncated'])
        self.end('final-only')
        self.turns.submit('Next', snapshot('next'))
        self.pre('interrupted')
        for chunk in ('Opening.\n\n', 'body ' * 2400, 'tail'):
            self.turns.delta(session_id='session', turn_id='interrupted', delta=chunk)
        self.end('interrupted', interrupted=True)
        run = self.turns.runs[-1]
        self.assertTrue(run['text'].startswith('Opening.'))
        self.assertEqual(len(run['text']), self.turns.MAX_TEXT)
        self.assertTrue(run['truncated'])
        self.assertEqual(self.chrome.events[-1]['items'][1]['conversation'][0]['answer_notice'],
                         self.turns.TRUNCATION_NOTICE)
        self.turns.close()

    def test_local_speech_owns_answer_text_and_only_autoplays_completed_answers(self):
        processes = []

        def spawn(*args, **kwargs):
            process = Mock(returncode=0)
            processes.append((process, args, kwargs))
            return process

        def flush():
            worker = self.turns._speech_thread
            if worker:
                worker.join(1)
                self.assertFalse(worker.is_alive())

        with patch('hermes_gaze.audio.speech.sys.platform', 'darwin'), \
                patch('hermes_gaze.audio.speech.os.access', return_value=True), \
                patch('hermes_gaze.audio.speech.SpeechPlayback.load', side_effect=ImportError('ptts missing')), \
                patch('hermes_gaze.audio.speech.subprocess.Popen', side_effect=spawn):
            first = self.turns.submit('private question', snapshot('private target'))
            second = self.turns.submit('another question', snapshot('another target'))
            self.pre('first')
            self.assertFalse(self.chrome.events[-1]['auto_speak'])
            self.assertFalse(self.turns.control('speak', first['item_id'])['ok'])
            self.turns.delta(session_id='session', turn_id='first', delta='Retained partial')
            self.assertFalse(self.turns.control('speak', 'unknown')['ok'])
            self.assertFalse(self.turns.control(
                'speak', first['item_id'], second['request_id'])['ok'])
            self.assertTrue(self.turns.control(
                'speak', first['item_id'], first['request_id'])['ok'])
            flush()
            self.assertEqual(processes[0][0].communicate.call_args.args[0], 'Retained partial')
            self.post('first', 'First complete answer')
            self.end('first')
            self.assertEqual(len(processes), 1)  # Off by default.
            self.pre('second')
            self.assertTrue(self.turns.control('auto_speak')['auto_speak'])
            self.assertTrue(self.chrome.events[-1]['auto_speak'])
            self.turns.delta(session_id='session', turn_id='second', delta='Streaming')
            self.post('foreign-turn', 'Foreign text')
            self.turns.post(session_id='foreign-session', turn_id='second',
                            assistant_response='Foreign session text')
            self.assertEqual(len(processes), 1)
            self.post('second', 'Second complete answer')
            flush()
            self.end('second')
            self.assertEqual(len(processes), 2)  # Terminal hook does not repeat speech.
            self.assertEqual(processes[1][0].communicate.call_args.args[0], 'Second complete answer')
            self.assertFalse(self.turns.control('auto_speak')['auto_speak'])
            self.assertTrue(self.turns.control('speak', first['item_id'])['ok'])
            flush()
            self.assertEqual(processes[2][0].communicate.call_args.args[0], 'First complete answer')
            with patch('hermes_gaze.audio.speech.sys.platform', 'linux'):
                self.assertTrue(self.turns.control('speak', first['item_id'])['ok'])
                flush()
                self.assertEqual(self.chrome.events[-1]['speech_backend'], 'unavailable')
                self.assertIn('macOS say', self.chrome.events[-1]['speech_error'])
        self.turns.close()

    def test_three_frozen_targets_serial_terminal_admission_and_unique_labels(self):
        source = snapshot('10')
        first = self.turns.submit('price?', source)
        source['page_lines'][0] = 'mutated'
        self.turns.submit('price?', snapshot('20'))
        third = self.turns.submit('price?', snapshot('30'))
        self.assertEqual(len(self.host.messages), 1)
        self.assertEqual([m['conversation'][0]['queue_position'] for m in self.chrome.events[-1]['items']], [0, 1, 2])
        context = self.pre('A')['context']
        self.assertIn('10 pounds', context)
        self.assertNotIn('mutated', context)
        self.post('A', 'Ten pounds')
        self.assertEqual(len(self.host.messages), 1)  # post is not the terminal hook
        self.end('A')
        self.assertEqual(len(self.host.messages), 2)
        self.assertIn('20 pounds', self.pre('B')['context'])
        self.end('B')
        self.assertIn('30 pounds', self.pre('C')['context'])
        self.post('C', 'Thirty pounds')
        self.end('C')
        self.assertEqual(len(set(text for text, _ in self.host.messages)), 3)
        self.assertIn(first['item_id'], self.host.messages[0][0])
        self.assertIn(third['item_id'], self.host.messages[2][0])
        self.assertTrue(all(i['unread'] for i in self.chrome.events[-1]['items']))
        self.assertFalse(any(s['actions_allowed'] for s in self.chrome.stored))

    def test_followup_selection_compare_capture_order_and_fences(self):
        a = self.turns.submit('price?', snapshot('10'))
        b = self.turns.submit('price?', snapshot('20'))
        self.pre('A'); self.post('A', 'Ten'); self.end('A')
        self.pre('B'); self.post('B', 'Twenty'); self.end('B')
        self.turns.control('select', a['item_id'])
        self.turns.submit('why?', {}, a['item_id'])
        self.pre('follow'); self.post('follow', 'Because'); self.end('follow')
        self.turns.submit('Compare this with the last one', {}, b['item_id'])
        context = self.pre('compare')['context'].partition('\n\n')[2]
        self.assertIn('10 pounds', context)
        self.assertIn('20 pounds', context)
        self.assertIn('Previous captured item (last one)', context)
        self.assertLessEqual(len(context), 6000)
        stamp_resolution(context, 99)
        self.assertEqual(self.chrome.events[-1]['selected_item_id'], a['item_id'])
        self.assertIn('Because', str(self.chrome.events[-1]['items'][0]['conversation']))

    def test_failure_partial_retry_skip_resume_and_foreign_deltas(self):
        a = self.turns.submit('price?', snapshot('10'))
        self.turns.submit('price?', snapshot('20'))
        self.pre('A')
        self.turns.delta(session_id='foreign', turn_id='A', delta='secret')
        self.turns.delta(session_id='session', turn_id='A', kind='reasoning', delta='secret')
        self.turns.delta(session_id='session', turn_id='A', delta='Partial answer')
        self.end('A', failed=True, completed=False, turn_exit_reason='quota exhausted')
        self.assertTrue(self.turns.paused)
        self.assertEqual(len(self.host.messages), 1)
        self.assertIn('Partial answer', str(self.chrome.events[-1]))
        self.assertNotIn('secret', str(self.chrome.events))
        self.turns.control('retry', a['item_id'])
        self.assertEqual(len(self.host.messages), 2)
        self.pre('retry')
        self.end('retry', interrupted=True)
        self.turns.control('skip', a['item_id'])
        self.assertTrue(self.turns.paused)
        self.turns.control('resume')
        self.assertEqual(len(self.host.messages), 3)
        self.assertIn('20 pounds', self.pre('B')['context'])
        self.post('A', 'late answer')
        self.assertNotIn('late answer', str(self.chrome.events))

    def test_transcription_reserves_order_and_late_final_does_not_steal_focus(self):
        a = self.turns.capture(snapshot('10'), transcribing=True)
        self.turns.submit('second', snapshot('20'))
        self.assertEqual(self.host.messages, [])
        self.assertEqual(self.chrome.events[-1]['items'][0]['conversation'][0]['status'], 'transcribing')
        self.turns.transcribed(a['request_id'], 'first', snapshot('10'))
        self.pre('A')
        self.end('A')
        self.pre('B')
        self.post('A', 'late full answer')
        self.assertIn('late full answer', str(self.chrome.events[-1]['items'][0]))
        self.assertEqual(self.chrome.events[-1]['selected_item_id'], '')
        self.post('A', 'duplicate')
        self.assertNotIn('duplicate', str(self.chrome.events))

    def test_disconnect_preserves_inbox_and_revokes_old_streams(self):
        a = self.turns.submit('first', snapshot('10'))
        self.turns.submit('second', snapshot('20'))
        self.pre('A')
        self.turns.bind('disconnect', session_key='route', session_id='session')
        self.turns.delta(session_id='session', turn_id='A', delta='late')
        self.assertEqual(len(self.chrome.events[-1]['items']), 2)
        self.assertFalse(self.chrome.events[-1]['session_connected'])
        self.turns.bind(session_key='route', session_id='session')
        self.assertTrue(self.turns.paused)
        self.turns.control('skip', a['item_id'])
        self.turns.control('resume')
        self.assertEqual(len(self.host.messages), 1)
        self.end('A')
        self.assertEqual(len(self.host.messages), 2)

    def test_limits_and_refused_injection_pause_without_one_shot_fallback(self):
        self.assertFalse(self.turns.submit('x', {'context': 'x' * 6001})['ok'])
        self.host.accept = False
        first = self.turns.submit('first', snapshot('10'))
        self.assertTrue(first['ok'])  # retained failure, not duplicate one-shot delivery
        self.assertTrue(self.turns.paused)
        for n in range(8):
            self.assertTrue(self.turns.submit(str(n), snapshot(str(n)))['ok'])
        self.assertFalse(self.turns.submit('overflow', {})['ok'])
        self.assertFalse(self.turns.control('retry', first['item_id'])['ok'])
        self.assertEqual(len(self.host.messages), 1)

    def test_exact_wire_match_in_synchronous_hook(self):
        contexts = []
        self.host.during_inject = lambda: contexts.append(self.pre('sync'))
        self.turns.submit('question', snapshot('10'))
        self.assertIn('10 pounds', contexts[0]['context'])
        self.assertIsNone(self.pre('sync'))

    def test_different_session_after_disconnect_cannot_recall_previous_items(self):
        first = self.turns.submit('private A', snapshot('10'))
        self.turns.submit('waiting A', snapshot('20'))
        self.pre('A')
        self.turns.bind('disconnect', session_key='route', session_id='session')
        self.turns.bind(session_key='other-route', session_id='other-session')
        self.assertEqual(self.chrome.events[-1]['items'], [])
        self.assertFalse(self.turns.control('select', first['item_id'])['ok'])
        self.turns.control('resume')
        self.assertEqual(len(self.host.messages), 1)

    def test_transcription_retry_preserves_item_and_unblocks_fifo(self):
        import threading
        failed, retried = threading.Event(), threading.Event()
        first = self.turns.capture(snapshot('20'), transcribing=True)
        self.turns.submit('Why that price?', {}, first['item_id'])
        def work():
            if not failed.is_set():
                self.turns.transcribed(first['request_id'], '', error='ASR unavailable')
                failed.set()
            else:
                self.turns.transcribed(first['request_id'], 'first', snapshot('10'))
                retried.set()
        self.turns.start_transcription(first['request_id'], work)
        self.assertTrue(failed.wait(1))
        self.assertTrue(self.turns.paused)
        self.assertTrue(self.turns.control('retry', first['item_id'])['ok'])
        self.assertTrue(retried.wait(1))
        self.assertEqual(len(self.host.messages), 1)
        self.assertEqual(self.turns.items[0]['target_label'], '10')
        self.assertIn('10 pounds', self.pre('first')['context'])
        self.end('first')
        self.assertEqual(len(self.host.messages), 2)
        self.assertIn('10 pounds', self.pre('followup')['context'])
        self.assertNotIn('20 pounds', self.chrome.stored[-1]['context'])

    def test_voice_missing_target_fails_but_recalled_followup_uses_saved_target(self):
        missing = {'ok': False, 'context': '', 'page_lines': ['unavailable page'], 'error': 'No cursor target'}
        failed = self.turns.capture(missing, transcribing=True)
        self.assertFalse(self.turns.transcribed(failed['request_id'], 'What is this?', missing)['ok'])
        self.assertEqual(self.host.messages, [])
        self.turns.control('skip', failed['item_id'])
        self.turns.control('resume')
        item = self.turns.submit('price?', snapshot('10'))
        self.pre('first'); self.post('first', 'Ten'); self.end('first')
        follow = self.turns.capture(missing, transcribing=True, item_id=item['item_id'])
        self.assertTrue(self.turns.transcribed(follow['request_id'], 'Why this price?', missing)['ok'])
        self.assertIn('10 pounds', self.pre('follow')['context'])

    def test_reconnect_before_pre_and_retry_wait_for_original_terminal(self):
        first = self.turns.submit('first', snapshot('10'))
        wire = self.host.messages[0][0]
        self.turns.bind('disconnect', session_key='route', session_id='session')
        self.assertIsNone(self.turns.pre(session_id='session', turn_id='original', user_message=wire))
        self.turns.bind(session_key='route', session_id='session')
        self.assertTrue(self.turns.control('retry', first['item_id'], first['request_id'])['ok'])
        self.assertEqual(len(self.host.messages), 1)
        self.end('original')
        self.assertEqual(len(self.host.messages), 2)
        self.assertIn('10 pounds', self.pre('retry')['context'])

    def test_skip_failed_asr_with_newer_followup_does_not_wedge_queue(self):
        first = self.turns.capture(snapshot('10'), transcribing=True)
        follow = self.turns.submit('why?', {}, first['item_id'])
        self.turns.submit('third', snapshot('30'))
        self.turns.transcribed(first['request_id'], '', error='ASR failed')
        self.assertTrue(self.turns.control('skip', first['item_id'], first['request_id'])['ok'])
        self.turns.control('resume')
        self.assertEqual(self.host.messages, [])
        self.assertTrue(self.turns.control('skip', first['item_id'], follow['request_id'])['ok'])
        self.turns.control('resume')
        self.assertIn('30 pounds', self.pre('third')['context'])

    def test_wide_comparison_keeps_pointed_cells_and_row_values_before_history(self):
        from tests.test_cursor_context import capture
        from hermes_gaze.resolver.cursor_context import cursor_result
        def wide(price, last):
            data = capture()
            data['blocks'][0]['headers'] = ['Header ' + str(i) + 'x' * 100 for i in range(12)]
            data['blocks'][0]['columns'] = ['column' + 'x' * 100 for _ in range(12)]
            values = ['value' + str(i) + 'x' * 65 for i in range(12)]
            values[1], values[-1] = price, last
            data['blocks'][0]['rows'] = [{'id': '@r1', 'index': 1, 'cells': values}]
            data['targets'][0]['cell']['value'] = price
            data['targets'][0]['surface'] = 'Covered by consent gate ' + price
            return cursor_result(data, 'this', [{'word': 'this', 'start': 11}])
        self.turns.submit('first', wide('£111.19', '£901.42'))
        second = self.turns.submit('second', wide('£222.37', '£902.43'))
        self.pre('first'); self.end('first')
        self.pre('second'); self.post('second', 'long answer ' * 1000); self.end('second')
        self.turns.submit('Compare this with the last one', {}, second['item_id'])
        context = self.pre('compare')['context'].partition('\n\n')[2]
        for value in ('£111.19', '£222.37', '£901.42', '£902.43'):
            self.assertIn(value, context)
        for price in ('£111.19', '£222.37'):
            self.assertIn('Covered by consent gate ' + price, context)
        self.assertLessEqual(len(context), 6000)
        stamp_resolution(context, 999)

    def test_saved_comparison_uses_only_current_capture_identities_in_same_document(self):
        from unittest.mock import patch

        def saved(name, document, handles):
            return {**snapshot(name), "browser_target": "tab", "browser_document": document,
                    "top": {"id": name, "cell": {"row_handle": name + "-row"}},
                    "handles": {h: {} for h in handles},
                    "scope_bundles": {"none": [], "pointed": [name], "row": [name + "-row"]}}

        with patch.dict("sys.modules", {"agent.secret_scope": SimpleNamespace(get_secret=lambda _: None)}):
            self.turns.submit("first", saved("@a", "doc", ["@a", "@a-row"]))
            self.turns.submit("Compare this row with the previous one",
                              saved("@b", "doc", ["@a", "@a-row", "@b", "@b-row"]))
            chosen = self.turns.runs[-1]["snapshot"]["scope_bundles"]
            self.assertEqual(chosen["rows"], ["@a-row", "@b-row"])
            self.assertEqual(chosen["referents"], ["@a", "@b"])
            self.turns.submit("Compare this with the previous one",
                              saved("@c", "replacement", ["@b", "@b-row", "@c", "@c-row"]))
            self.assertNotIn("referents", self.turns.runs[-1]["snapshot"]["scope_bundles"])
            self.turns.submit("Compare this with the previous one",
                              saved("@d", "replacement", ["@d", "@d-row"]))
            self.assertNotIn("rows", self.turns.runs[-1]["snapshot"]["scope_bundles"])


if __name__ == '__main__':
    unittest.main()
