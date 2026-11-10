"""Real private renderer/input with blocked fake shutdown and ASR; no devices."""
import asyncio
import ctypes
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
from hermes_gaze import cli
from hermes_gaze.audio import voice
from hermes_gaze.runtime.release_timing import TIMINGS

r = Rig(headless=True, scale=1)
results = []
try:
    r.new_tab()
    r.page('''document.body.innerHTML='<p id="topic" style="margin:80px">Release target</p>' +
      '<p>Large local page</p>'.repeat(10000) + '<input id="typing" style="position:fixed;top:20px;left:400px">';
      window.ticks=0;setInterval(()=>ticks++,20);''')
    native_sleep = ctypes.PyDLL(None).sleep  # Deliberately holds the GIL; no native devices.
    native_sleep.argtypes = [ctypes.c_uint]
    for blocked in ('stop', 'close', 'asr', 'gil-stop', 'gil-close', 'gil-asr', 'webcam-gaze'):
        entered, release = threading.Event(), threading.Event()
        def wait():
            entered.set()
            if blocked.startswith('gil-'):
                native_sleep(2)
            else:
                assert release.wait(8), 'blocked stage was not released'
        class Input(FakeInput):
            def stop(self):
                super().stop()
                if blocked in ('stop', 'gil-stop'): wait()
            def close(self):
                super().close()
                if blocked in ('close', 'gil-close'): wait()
        def transcribe(*args, **kwargs):
            if blocked in ('asr', 'gil-asr'): wait()
            return 'Explain this topic', []
        render = r.tab._render_ui
        async def delayed_render(message):
            if blocked.startswith('gil-') and message.get('mode') != 'wave':
                await asyncio.sleep(.1)  # The second CDP hop is in flight when shutdown starts.
            return await render(message)
        original_ingest = r.session.ingest
        def ingest(samples):
            if blocked == 'webcam-gaze': wait()
            return original_ingest(samples)
        r.session.configure(mode='webcam' if blocked == 'webcam-gaze' else 'hover')
        r.host.answers = [{'text': '## Release target\n\nThe release stayed responsive.', 'think': .05, 'step': .01}]
        with patch.object(sys.modules['sounddevice'], 'RawInputStream', Input), \
                patch.object(voice, 'transcribe_audio_buffer', side_effect=transcribe), \
                patch.object(r.tab, '_render_ui', side_effect=delayed_render), \
                patch.object(r.session, 'ingest', side_effect=ingest):
            r.press('Escape', 'Escape')
            r.aim('#topic')
            if blocked == 'webcam-gaze':
                assert r.iso("window.__HERMES_GAZE_OVERLAY__.acceptWebcamSample("
                             "{source:'webcam',x_vp:100,y_vp:90,t:Date.now()/1000})")
            r.space_down()
            until(lambda: r.session.microphone._stream is not None)
            time.sleep(.25)
            started = time.monotonic()
            r.space_up()
            try:
                assert entered.wait(3), blocked
                until(lambda: 'Looking into' in r.panel('pill', 'document.body.innerText'), 2, 'processing capsule')
                visible_ms = (time.monotonic() - started) * 1000
                stages = r.tab._release_trace.snapshot()['python_ms']
                assert stages['release_ui_push'] < 500, stages
                first_work = stages.get('stream_stop_start', stages.get('capture_resolve_start'))
                assert stages['release_ui_push'] <= first_work, stages
                if blocked in ('stop', 'close', 'asr'):
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
                results.append({'blocked': blocked, 'processing_observed_ms': round(visible_ms, 2),
                                'processing_render_ms': stages['release_ui_push'],
                                'page_input_scroll_and_timers': True,
                                'interaction_during_block': not blocked.startswith('gil-')})
                r.shot('release-' + blocked)
            finally:
                release.set()
                until(lambda: not r.session.microphone._closing and r.turns.active is None
                      and not r.turns.pending, 8, 'answer completed')
            with patch.object(cli.Path, 'home', return_value=Path(r.tmp)):
                cli._handle_slash_command('timing')
            timing_file = Path(r.tmp) / '.cache/hermes-gaze/release-timing.json'
            trace = json.loads(timing_file.read_text())['turns'][-1]
            assert timing_file.stat().st_mode & 0o777 == 0o600
            assert 'first_ui_push' in trace['python_ms'], trace
            assert 'first_delta' in trace['python_ms'], trace
            assert trace['browser_ms']['evidence_frozen'] >= trace['browser_ms']['evidence_start']
            results[-1]['trace'] = trace
finally:
    r.close()
Path(os.environ['SHOTS']).joinpath('release-results.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
print('PASS: release render precedes blocking stop/close/ASR/gaze, including GIL-holding native fakes with delayed CDP')
