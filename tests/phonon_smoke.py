"""Real pinned Phonon/Russell, fake paced output only. No capture or playback.
Run with the Python environment containing ptts, after scripts/setup_speech.py.
"""
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # package shell; does not import Hermes
from hermes_gaze.audio.speech import SpeechPlayback


class Sink:
    def __init__(self, **kwargs):
        self.rate = kwargs['samplerate']
        self.first = threading.Event()
        self.aborted = False
        self.samples = 0

    def start(self):
        pass

    def write(self, pcm):
        assert np.isfinite(pcm).all()
        assert len(pcm) <= self.rate // 50
        if not self.first.is_set():
            self.first_at = time.monotonic()
            self.first.set()
        self.samples += len(pcm)
        time.sleep(len(pcm) / self.rate)  # Exercise bounded playback backpressure.

    def stop(self):
        pass

    def abort(self):
        self.aborted = True

    def close(self):
        pass


def main():
    playback = SpeechPlayback()
    playback.load('Russell')
    results = []
    for _ in range(3):
        sinks, reports, errors = [], [], []
        cancel = threading.Event()
        def output(**kwargs):
            sink = Sink(**kwargs)
            sinks.append(sink)
            return sink
        def run():
            try:
                playback.play('The chart shows revenue rising steadily. ' * 80, 'Russell', cancel,
                              lambda *args: reports.append(args))
            except Exception as exc:
                errors.append(str(exc))
        with patch.dict(sys.modules, sounddevice=SimpleNamespace(OutputStream=output)), \
                patch.object(SpeechPlayback, 'say', side_effect=AssertionError('Real say forbidden')):
            start = time.monotonic()
            worker = threading.Thread(target=run)
            worker.start()
            deadline = start + 5
            while not sinks and worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.001)
            assert sinks and sinks[0].first.wait(5), (reports, errors)
            first_ms = (sinks[0].first_at - start) * 1000
            stopped = time.monotonic()
            cancel.set()
            worker.join(1)
            cancel_ms = (time.monotonic() - stopped) * 1000
            assert not worker.is_alive(), 'generation failed to stop'
            assert not errors, errors
            assert reports[0][0] == 'phonon', reports
            assert sinks[0].aborted
            assert first_ms < 1000, first_ms
            assert cancel_ms < 100, cancel_ms
            results.append(dict(first_chunk_ms=round(first_ms, 3), cancellation_ms=round(cancel_ms, 3),
                                samples=sinks[0].samples))
    print(json.dumps(dict(backend='phonon', voice='Russell', fake_output=True, trials=results), indent=2))


if __name__ == '__main__':
    main()
