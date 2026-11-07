"""Private Chrome card geometry, including a fresh first answer and follow-up."""
import json
import os
import time
from pathlib import Path

OUT = Path(os.environ.get('GAZE_REVIEW_OUT', '/tmp/hermes-card-size'))
OUT.mkdir(parents=True, exist_ok=True)
os.environ.update(REVIEW_START_URL=Path(__file__).with_name('hostile.html').as_uri(),
                  SHOTS=str(OUT), HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig, until, patch, voice


def measure(r):
    return {'host': r.dbg(), 'panel': r.panel('card', '''(()=>{
      const card=document.querySelector('.card'), body=document.querySelector('.body');
      return {cardH:card.offsetHeight, rootH:document.getElementById('root').offsetHeight,
        bodyH:body.clientHeight, contentH:body.scrollHeight,
        naturalH: [...card.children].reduce((n,e)=>n+e.getBoundingClientRect().height+
          (e.classList.contains('foot') ? 0 : parseFloat(getComputedStyle(e).marginTop))+
          parseFloat(getComputedStyle(e).marginBottom),parseFloat(getComputedStyle(card).paddingTop)),
        viewportW:innerWidth};})()''')}


def run(name, text, streamed=False):
    r = Rig(scale=1, width=int(os.environ.get('CARD_TEST_WIDTH', '1440')))
    result = {}
    try:
        r.tab = next(t for t in r.session.cdp._tabs.values() if t.is_connected)
        r.front(r.tab)
        if os.environ.get('CARD_TEST_TARGET_TOP'):
            r.page("document.getElementById('first').style.cssText = " + json.dumps(
                'position:fixed;left:20px;right:20px;width:auto;top:' +
                os.environ['CARD_TEST_TARGET_TOP'] + 'px;height:65px'))
        r.aim('#first')
        r.host.answers = [{'text': text, 'step': .015 if streamed else 0, 'think': .05},
                          {'text': 'A follow-up answer with more detail. ' * 8, 'step': 0, 'think': .05}]
        with patch.object(voice, 'transcribe_audio_buffer', return_value=('Explain the first topic', [])):
            r.ask_voice('#first')
            until(lambda: r.turns.items and r.host.wires, what='accepted voice question')
        item = r.turns.items[0]['item_id']
        until(lambda: r.dbg()['view'] == 'answer', what='first card')
        if streamed:
            until(lambda: r.panel('card', 'document.querySelector(".a")?.textContent.length > 100'), what='stream')
            with r.turns.lock:
                time.sleep(.15)  # Let the last pushed delta render while the scripted host is paused.
                result['streaming'] = measure(r)
        until(lambda: r.turns.active is None, what='first completion')
        time.sleep(.8)
        result['first'] = measure(r)
        r.shot(name + '-first')
        r.turns.submit('Tell me more', {}, item_id=item)
        until(lambda: len(r.host.wires) == 2 and r.turns.active is None, what='follow-up completion')
        time.sleep(.8)
        result['followup'] = measure(r)
        r.shot(name + '-followup')
    finally:
        r.close()
    return result


results = {}
try:
    for name, text, streamed in [('short', 'A short answer.', False),
                                 ('long', ('A longer first answer with useful detail and clear explanations. ' * 100), False),
                                 ('streamed', ('Streaming useful detail as the answer grows. ' * 30), True)]:
        results[name] = run(name, text, streamed)
finally:
    (OUT / 'card-size-results.json').write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
for name, samples in results.items():
    for stage, sample in samples.items():
        host, panel = sample['host'], sample['panel']
        expected = max(64, ((int(panel['naturalH'] + .999) + 23) // 24) * 24)
        assert abs(host['card']['h'] - expected) <= 1, (name, stage, expected, sample)
        assert panel['bodyH'] >= min(panel['contentH'], host['maxBody']) - 1, (name, stage, sample)
        assert host['frame']['h'] >= panel['rootH'], (name, stage, sample)
print('PASS: fresh short, long, streaming and follow-up card geometry')
