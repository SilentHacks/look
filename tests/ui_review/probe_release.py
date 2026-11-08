"""Real private renderer/input with blocked fake shutdown and ASR; no devices."""
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

os.environ['HERMES_DISABLE_LAZY_INSTALLS'] = '1'
os.environ['SHOTS'] = os.environ.get('GAZE_REVIEW_OUT', '/tmp/hermes-release-probe')
from devlib import FakeInput, Rig, until
from hermes_gaze import cli, voice
from hermes_gaze.release_timing import TIMINGS

r = Rig(scale=1)
results = []
try:
    r.new_tab()
    r.page('''document.body.innerHTML='<p id="topic" style="margin:80px">Release target</p>' +
      '<p>Large local page</p>'.repeat(10000) + '<input id="typing" style="position:fixed;top:20px;left:400px">';
      window.ticks=0;setInterval(()=>ticks++,20);''')
    for blocked in ('stop', 'close', 'asr'):
        entered, release = threading.Event(), threading.Event()
        def wait():
            entered.set()
            assert release.wait(8), 'blocked stage was not released'
        class Input(FakeInput):
            def stop(self):
                super().stop()
                if blocked == 'stop': wait()
            def close(self):
                super().close()
                if blocked == 'close': wait()
        def transcribe(*args, **kwargs):
            if blocked == 'asr': wait()
            return 'Explain this topic', []
        r.host.answers = [{'text': '## Release target\n\nThe release stayed responsive.', 'think': .05, 'step': .01}]
        with patch.object(sys.modules['sounddevice'], 'RawInputStream', Input), \
                patch.object(voice, 'transcribe_audio_buffer', side_effect=transcribe):
            r.press('Escape', 'Escape')
            r.aim('#topic')
            r.space_down()
            until(lambda: r.session.microphone._stream is not None)
            time.sleep(.25)
            started = time.monotonic()
            r.space_up()
            try:
                assert entered.wait(3), blocked
                until(lambda: 'Looking into' in r.panel('pill', 'document.body.innerText'), 2, 'processing capsule')
                visible_ms = (time.monotonic() - started) * 1000
                assert visible_ms < 500, visible_ms
                assert r.turns.pending[0]['status'] == 'transcribing'
                before = r.page('ticks')
                r.page('scrollTo(0,500);typing.focus({preventScroll:true})')
                r.cmd('Input.insertText', {'text': 'responsive'})
                time.sleep(.15)
                assert r.page('ticks') > before
                assert r.page('scrollY') == 500, r.page('scrollY')
                assert r.page('typing.value') == 'responsive'
                r.page('typing.value="";typing.blur();scrollTo(0,0)')
                time.sleep(.25)
                results.append({'blocked': blocked, 'processing_visible_ms': round(visible_ms, 2),
                                'page_input_scroll_and_timers': True})
                r.shot('release-' + blocked)
            finally:
                release.set()
                until(lambda: r.turns.active is None and not r.turns.pending, 8, 'answer completed')
            trace = json.loads(cli._handle_slash_command('timing'))['turns'][-1]
            assert 'first_ui_push' in trace['python_ms'], trace
            assert 'first_delta' in trace['python_ms'], trace
            assert trace['browser_ms']['evidence_frozen'] >= trace['browser_ms']['evidence_start']
            results[-1]['trace'] = trace
finally:
    r.close()
Path(os.environ['SHOTS']).joinpath('release-results.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
print('PASS: blocked native stop, close and ASR preserve private processing UI and page input/scroll/timers')
