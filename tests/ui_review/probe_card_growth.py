"""Fresh protected renderer over a large product comparison; fake host, no devices."""
import json
import os
import time
from pathlib import Path

OUT = Path(os.environ.get('GAZE_REVIEW_OUT', '/tmp/hermes-card-growth'))
OUT.mkdir(parents=True, exist_ok=True)
os.environ.update(SHOTS=str(OUT), HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig, until, patch, voice

results = {}
failures = []
for width, height in [(1440, 900), (800, 700)]:
    r = Rig(width=width, height=height, scale=2)
    try:
        r.tab = next(t for t in r.session.cdp._tabs.values() if t.is_connected)
        r.front(r.tab)
        r.page('''document.body.innerHTML = `<h2>Deals & Discounts</h2>
          <p id="product" style="position:fixed;margin:0;left:20px;right:20px;top:150px;height:340px;
          background:#eef;padding:20px;font:20px system-ui">Samsung Odyssey and another OLED monitor</p>`''')
        r.move(180, 180)
        r.host.hold.clear()
        with patch.object(voice, 'transcribe_audio_buffer', return_value=('Which monitor is better?', [])):
            r.ask_voice(None)
            until(lambda: r.turns.active and r.host.wires, what='captured comparison')
        run = r.turns.active
        until(lambda: run.get('turn_id'), what='host turn binding')
        turn_id = run['turn_id']

        def sample():
            return {'host': r.dbg(), 'panel': r.panel('card', '''(()=>{
              const b=document.querySelector('.body'), c=document.querySelector('.card');
              return {top:b.scrollTop,bodyH:b.clientHeight,contentH:b.scrollHeight,
                cardH:c.offsetHeight,rootH:document.getElementById('root').offsetHeight};})()''')}

        def delta(text):
            r.turns.delta(session_id='s', turn_id=turn_id, delta=text)
            until(lambda: text.strip()[-30:] in r.text(), what='streamed comparison')
            time.sleep(.25)
        delta('## 49-inch OLED monitors\n\nOne of these I can name precisely. ')
        stages = {'opening': sample()}
        assert stages['opening']['host']['targets'], 'comparison must retain its captured target'
        for n in range(8):
            delta(f'\n\nComparison section {n}. ' + 'Useful display details and buying advice. ' * 12)
        stages['streaming'] = sample()
        r.shot(f'{width}-streaming')
        rect = r.panel_rect('.body')
        r.move(rect['cx'], rect['cy'])
        r.cmd('Input.dispatchMouseEvent', {'type':'mouseWheel', 'x':rect['cx'], 'y':rect['cy'],
                                          'deltaX':0, 'deltaY':120})
        until(lambda: sample()['panel']['top'] > 0, what='manual reading')
        time.sleep(.2)
        top = sample()['panel']['top']
        delta('\n\nAdditional comparison details. ' * 20)
        stages['manual'] = sample()
        r.turns.post(session_id='s', turn_id=turn_id, assistant_response=run['text'])
        r.turns.end(session_id='s', turn_id=turn_id)
        time.sleep(.4)
        stages['settled'] = sample()
        r.shot(f'{width}-settled')
        results[str(width)] = stages
        for stage in ['streaming', 'settled']:
            h, p = stages[stage]['host'], stages[stage]['panel']
            if p['bodyH'] < min(300, height * .45): failures.append((width, stage, 'shallow reading area'))
            if h['card']['y'] + h['card']['h'] > height - 13: failures.append((width, stage, 'outside viewport'))
            if h['frame']['h'] < p['rootH']: failures.append((width, stage, 'frame clips renderer'))
            if h['card']['h'] % 24: failures.append((width, stage, 'non-coarse plate'))
        if stages['streaming']['panel']['top'] != 0: failures.append((width, 'stream followed bottom'))
        if abs(stages['manual']['panel']['top'] - top) > 1 or abs(stages['settled']['panel']['top'] - top) > 1:
            failures.append((width, 'manual reading moved'))
    finally:
        r.close()
(OUT / 'card-growth-results.json').write_text(json.dumps({'results':results,'failures':failures}, indent=2))
print(json.dumps({'results':results,'failures':failures}, indent=2))
assert not failures, failures
print('PASS: fresh comparison card grows, stays in viewport, preserves top/manual scroll and coarse geometry')
