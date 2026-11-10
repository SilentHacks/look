"""Private Chrome read-aloud surface, fake TTS and output; no real devices or models."""
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

os.environ['HERMES_DISABLE_LAZY_INSTALLS'] = '1'
os.environ['SHOTS'] = os.environ.get('GAZE_REVIEW_OUT', '/tmp/hermes-speech-probe')
from devlib import Rig, until
from tests.test_speech import Output, Stream
from hermes_gaze.audio.speech import SpeechPlayback

outdir = Path(os.environ.get('GAZE_REVIEW_OUT', '/tmp/hermes-speech-probe'))
outdir.mkdir(parents=True, exist_ok=True)
r = Rig(scale=1)
sinks, streams, result = [], [], {}


def output(**kwargs):
    sink = Output(**kwargs)
    sinks.append(sink)
    return sink


def stream(*args, **kwargs):
    s = Stream()
    streams.append(s)
    return s


def stopped():
    until(lambda: not r.turns.speaking and streams[-1].closed.is_set() and sinks[-1].aborted.is_set())


def click_control(selector):
    # Hover reveals the controls and can change the card's footer geometry.
    r.move(720, 100)
    time.sleep(.3)
    position = until(lambda: r.panel_rect(selector))
    r.move(position['cx'], position['cy'])
    time.sleep(.3)
    r.click_panel(selector)


def ask(question):
    before = len(r.turns.runs)
    r.aim('#topic')
    r.press('AltRight', 'Alt')
    until(lambda: r.panel('card', 'document.activeElement?.id') == 'hg-input')
    time.sleep(.3)
    for char in question:
        r.cmd('Input.dispatchKeyEvent', {'type': 'char', 'text': char})
    r.press('Enter', 'Enter')
    until(lambda: len(r.turns.runs) > before and r.turns.active is None)
    return r.turns.items[-1]


try:
    with patch.object(SpeechPlayback, 'load', return_value=SimpleNamespace(stream=stream)), \
            patch.object(SpeechPlayback, 'say', side_effect=AssertionError('Real say forbidden')), \
            patch.object(sys.modules['sounddevice'], 'OutputStream', output, create=True):
        r.new_tab()
        r.page('document.body.innerHTML="<p id=topic>Revenue grew this quarter.</p>"')
        r.host.answers = [{'text': '## Revenue\n\n' + 'Revenue rose by **12.5 percent**. ' * 4, 'think': .1}]
        item = ask('Explain revenue')
        until(lambda: 'Read aloud' in r.text())
        time.sleep(.6)
        click_control('[data-act=read]')
        until(lambda: 'Reading with Phonon · Russell.' in r.text())
        assert sinks[-1].writing.wait(1)
        result['backend_visible'] = r.text()
        r.move(1200, 600)
        time.sleep(.3)
        r.shot('phonon-reading')
        click_control('[data-act=read]')
        stopped()
        result['stop'] = True
        click_control('[data-act=read]')
        until(lambda: r.turns.speaking)
        r.press('Escape', 'Escape')
        stopped()
        result['escape'] = True
        r.press('KeyQ', 'q')
        until(lambda: 'Read aloud' in r.text())
        time.sleep(.6)
        click_control('[data-act=read]')
        until(lambda: r.turns.speaking)
        r.turns.bind('disconnect', session_key='k', session_id='s')
        stopped()
        result['disconnect'] = True
        r.turns.bind(session_key='k', session_id='s')
        r.press('Escape', 'Escape')
        r.host.answers = [{'text': '## Revenue\n\nA fresh private answer.', 'think': .1}]
        item = ask('Explain revenue again')
        until(lambda: 'Always read' in r.text())
        time.sleep(.6)
        click_control('[data-act=autoread]')
        until(lambda: r.turns.auto_speak)
        before = len(streams)
        r.host.answers = [{'text': '## More revenue\n\nAnother private answer.', 'think': .1}]
        ask('Explain more')
        until(lambda: len(streams) == before + 1 and r.turns.speaking)
        result['auto_speak'] = True
        r.turns.control('stop_speaking')
        stopped()
        r.turns.control('auto_speak')
        click_control('[data-act=read]')
        until(lambda: r.turns.speaking and sinks[-1].writing.is_set())
        r.aim('#topic')
        r.space_down()
        until(lambda: r.session.microphone._stream is not None)
        assert sinks[-1].closed.is_set() and streams[-1].closed.is_set()
        assert not r.turns.speaking
        result['talk_closes_speech_before_input'] = True
        r.press('Escape', 'Escape')
        r.space_up()
        until(lambda: r.session.microphone._stream is None)
        r.press('KeyQ', 'q')
        until(lambda: 'Read aloud' in r.text())
        def fallback(text, cancel, report, reason):
            report('say', 'Reading with macOS say.', f'Using macOS say; Phonon unavailable: {reason}')
        with patch.object(SpeechPlayback, 'load', side_effect=ImportError('ptts missing')), \
                patch.object(SpeechPlayback, 'say', side_effect=fallback):
            r.turns.control('speak', item['item_id'])
            until(lambda: 'Using macOS say; Phonon unavailable: ptts missing' in r.text())
            result['fallback_visible'] = r.text()
        result['pass'] = True
except Exception:
    print(json.dumps({'state': r.dbg(), 'text': r.text(), 'streams': len(streams),
                      'speaking': r.turns.speaking, 'speech_error': r.turns.speech_error}, indent=2))
    raise
finally:
    r.turns.control('stop_speaking')
    if r.turns._speech_thread:
        r.turns._speech_thread.join(1)
    r.close()
    (outdir / 'speech-results.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
assert result.get('pass')
