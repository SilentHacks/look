"""Speech generation and output ownership; never opens real audio devices."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hermes_gaze.speech import MODEL_FILES, MODEL_REVISION, VOICE_REVISION, SpeechPlayback
from hermes_gaze.voice_turns import VoiceTurns
from tests.test_voice_turns import Chrome, Host, snapshot


class Stream:
    sample_rate = 24000

    def __init__(self, release=None, pcm=None):
        self.closed = threading.Event()
        self.release = release
        self.chunks = 0
        self.pcm = iter(pcm) if pcm is not None else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed.set()
        if self.release:
            self.release.wait(1)
            raise RuntimeError('old stream closing')

    def __iter__(self):
        return self

    def __next__(self):
        if self.pcm is not None:
            return next(self.pcm)
        self.chunks += 1
        return [0.1] * 1920


class Output:
    def __init__(self, **kwargs):
        self.writing = threading.Event()
        self.aborted = threading.Event()
        self.stopped = False
        self.queued = 0
        self.sizes = []

    def start(self):
        pass

    def write(self, pcm):
        self.queued += len(pcm)
        self.sizes.append(len(pcm))
        self.writing.set()
        time.sleep(0.005)

    def stop(self):
        self.stopped = True
        self.queued = 0

    def abort(self):
        self.queued = 0
        self.aborted.set()

    def close(self):
        pass


class SpeechTests(unittest.TestCase):
    def rig(self, streams):
        self.outputs = []
        def output(**kwargs):
            sink = Output(**kwargs)
            self.outputs.append(sink)
            return sink
        self.enterContext(patch.dict(sys.modules, sounddevice=SimpleNamespace(OutputStream=output)))
        model = SimpleNamespace(stream=Mock(side_effect=streams))
        self.enterContext(patch.object(SpeechPlayback, 'load', return_value=model))
        turns = VoiceTurns(Host(), Chrome())
        turns.bind(session_key='k', session_id='s')
        self.addCleanup(turns.close)
        return turns, model

    def start(self, turns, label):
        run = turns.submit('question', snapshot(label))
        turns.runs[-1]['text'] = '**Private** answer [source](https://example.com/x)'
        self.assertTrue(turns.control('speak', run['item_id'])['ok'])
        deadline = time.monotonic() + 1
        while not self.outputs and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertTrue(self.outputs[-1].writing.wait(1))
        return run

    def finish(self, turns):
        worker = turns._speech_thread
        if worker:
            worker.join(1)
            self.assertFalse(worker.is_alive())

    def test_stop_esc_and_disconnect_abort_audio_and_generation_within_100ms(self):
        for action in ('stop_speaking', 'dismiss', 'disconnect'):
            with self.subTest(action=action):
                stream = Stream()
                turns, model = self.rig([stream])
                self.start(turns, action)
                self.assertEqual(model.stream.call_args.kwargs['voice'], 'Russell')
                spoken = model.stream.call_args.args[0]
                self.assertIn('Private answer', spoken)
                self.assertNotIn('**', spoken)
                start = time.monotonic()
                if action == 'disconnect':
                    turns.bind('disconnect', session_key='k', session_id='s')
                else:
                    turns.control(action)
                self.finish(turns)
                self.assertLess(time.monotonic() - start, 0.1)
                self.assertTrue(stream.closed.is_set())
                self.assertTrue(self.outputs[-1].aborted.is_set())
                self.assertFalse(self.outputs[-1].stopped)
                self.assertEqual(self.outputs[-1].queued, 0)
                self.assertLessEqual(max(self.outputs[-1].sizes), 480)
                self.assertEqual(turns.speaking, '')

    def test_superseded_completion_and_error_cannot_clear_new_speaking_state(self):
        release = threading.Event()
        old, new = Stream(release), Stream()
        turns, _ = self.rig([old, new])
        self.start(turns, 'old')
        second = turns.submit('next question', snapshot('new'))
        turns.runs[-1]['text'] = 'New private answer'
        turns.control('speak', second['item_id'])
        self.assertTrue(old.closed.wait(1))
        self.assertEqual(turns.speaking, second['item_id'])
        self.assertEqual(len(self.outputs), 1)  # No overlap while old stream closes.
        release.set()
        deadline = time.monotonic() + 1
        while len(self.outputs) < 2 and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertTrue(self.outputs[-1].writing.wait(1))
        self.assertEqual(turns.speaking, second['item_id'])
        self.assertEqual(turns.speech_error, '')
        turns.control('stop_speaking')
        self.finish(turns)

    def test_fallback_selected_before_output_for_missing_dependency_assets_or_load_failure(self):
        for error in (ImportError('ptts missing'), FileNotFoundError('assets missing'), RuntimeError('load failed')):
            playback, report = SpeechPlayback(), Mock()
            with patch.object(playback, 'load', side_effect=error), \
                    patch.object(playback, 'say') as fallback, \
                    patch.dict(sys.modules, sounddevice=Mock()) as modules:
                playback.play('answer', 'Russell', threading.Event(), report)
                fallback.assert_called_once()
                self.assertEqual(fallback.call_args.args[-1], str(error))
                modules['sounddevice'].OutputStream.assert_not_called()

    def test_playback_failure_never_replays_answer_with_fallback(self):
        stream = Stream()
        turns, _ = self.rig([stream])
        def broken_write(self, pcm):
            raise RuntimeError('device lost after starting audio')
        with patch.object(Output, 'write', broken_write), patch.object(SpeechPlayback, 'say') as fallback:
            run = turns.submit('question', snapshot('target'))
            turns.runs[-1]['text'] = 'Answer'
            turns.control('speak', run['item_id'])
            self.finish(turns)
            fallback.assert_not_called()
            self.assertIn('device lost', turns.speech_error)
            self.assertEqual(turns.speech_backend, 'phonon')
            self.assertTrue(stream.closed.is_set())

    def test_local_assets_load_once_without_hub_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model, catalog = root / MODEL_REVISION, root / VOICE_REVISION
            model.mkdir()
            catalog.mkdir()
            for name in MODEL_FILES:
                (model / name).touch()
            (catalog / 'russell.safetensors').touch()
            (catalog / 'voices.jsonl').write_text(json.dumps(dict(name='Russell', voice_id='r',
                language='en', filename='russell.safetensors')))
            tts = Mock()
            with patch('hermes_gaze.speech.asset_root', return_value=root), \
                    patch.dict(sys.modules, ptts=SimpleNamespace(TTS=tts)), \
                    patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
                playback = SpeechPlayback()
                self.assertIs(playback.load('Russell'), playback.load('Russell'))
                tts.assert_called_once_with(str(model), lang='en', quant='q8', voice_catalog=str(catalog))
                (catalog / 'russell.safetensors').unlink()
                with self.assertRaisesRegex(FileNotFoundError, 'voice Russell missing'):
                    playback.load('Russell')

    def test_finite_output_drains_before_completion(self):
        stream = Stream(pcm=([0.1] * 1920, [0.2] * 480))
        turns, _ = self.rig([stream])
        run = turns.submit('question', snapshot('finite'))
        turns.runs[-1]['text'] = 'Answer'
        turns.control('speak', run['item_id'])
        self.finish(turns)
        self.assertTrue(self.outputs[-1].stopped)
        self.assertEqual(sum(self.outputs[-1].sizes), 2400)
        self.assertEqual(turns.speaking, '')

    def test_cancel_during_model_load_does_not_block_inbox_or_start_audio(self):
        entered, release = threading.Event(), threading.Event()
        turns, _ = self.rig([])
        def load(voice):
            entered.set()
            release.wait(1)
            return Mock()
        with patch.object(turns._playback, 'load', side_effect=load):
            run = turns.submit('question', snapshot('loading'))
            turns.runs[-1]['text'] = 'Answer'
            turns.control('speak', run['item_id'])
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            turns.control('stop_speaking')
            self.assertLess(time.monotonic() - started, 0.1)
            release.set()
            self.finish(turns)
            self.assertEqual(self.outputs, [])

    def test_say_fallback_reports_reason_and_cancels_without_waiting_under_lock(self):
        cancel, talking = threading.Event(), threading.Event()
        process = Mock()
        process.poll.return_value = None
        def communicate(*args, **kwargs):
            talking.set()
            time.sleep(0.005)
            import subprocess
            raise subprocess.TimeoutExpired('say', .02)
        process.communicate.side_effect = communicate
        report = Mock()
        with patch('hermes_gaze.speech.sys.platform', 'darwin'), \
                patch('hermes_gaze.speech.os.access', return_value=True), \
                patch('hermes_gaze.speech.subprocess.Popen', return_value=process):
            worker = threading.Thread(target=SpeechPlayback.say, args=('private', cancel, report, 'ptts missing'))
            worker.start()
            self.assertTrue(talking.wait(1))
            start = time.monotonic()
            cancel.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic() - start, 0.1)
            process.kill.assert_called_once()
            process.wait.assert_called_once()
            self.assertEqual(report.call_args.args[0], 'say')
            self.assertIn('ptts missing', report.call_args.args[2])
