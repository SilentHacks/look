"""Delayed fake input must never look ready, including a follow-up. No real devices."""
import os
import sys
import threading
import time
from unittest.mock import patch

os.environ['HERMES_DISABLE_LAZY_INSTALLS'] = '1'
os.environ['SHOTS'] = os.environ.get('GAZE_REVIEW_OUT', '/tmp/hermes-mic-startup')
from devlib import FakeInput, Rig, until
from hermes_gaze import voice

r = Rig(headless=True, scale=1)
release = threading.Event()
try:
    r.new_tab()
    r.session.configure(mode='hover')
    r.page('document.body.innerHTML=\'<p id="topic" style="margin:80px">Startup topic</p>\'')
    for followup in (False, True):
        entered = threading.Event()
        release.clear()
        class DelayedInput(FakeInput):
            def start(self):
                entered.set()
                assert release.wait(5), 'fake input was not released'
                super().start()
        with patch.object(sys.modules['sounddevice'], 'RawInputStream', DelayedInput), \
                patch.object(voice, 'transcribe_audio_buffer', return_value=('Explain this topic', [])):
            r.aim('#topic')
            r.space_down()
            try:
                assert entered.wait(3)
                until(lambda: r.panel('pill', 'document.body.innerText') == 'Wait for Listening…', 3)
                assert not r.dbg()['talk']['micReady']
                assert bool(r.dbg()['hold']['follow']) == followup
                release.set()
                until(lambda: r.dbg()['talk']['micReady'], 3)
                until(lambda: r.panel('pill', 'document.body.innerText') == 'Listening', 3)
                time.sleep(.3)  # A real question stays held past the accidental-hold cancellation window.
            finally:
                release.set()
                r.space_up()
            until(lambda: len(r.host.wires) == (2 if followup else 1), 5)
            until(lambda: r.turns.active is None and not r.turns.pending, 8)
            until(lambda: r.panel('card', 'document.body.innerText').find('Hello') >= 0, 5)
    print('PASS: startup wait and native readiness shown for first question and follow-up')
finally:
    release.set()
    r.close()
