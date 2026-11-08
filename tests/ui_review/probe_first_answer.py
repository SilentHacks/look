"""Cold private renderer: delayed readiness/metrics, real inbox, stepped streaming; no devices."""
import asyncio
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

OUT = Path(os.environ.get('GAZE_REVIEW_OUT', '/tmp/hermes-first-answer'))
OUT.mkdir(parents=True, exist_ok=True)
os.environ.update(REVIEW_START_URL=Path(__file__).with_name('hostile.html').as_uri(),
                  SHOTS=str(OUT), HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig, until, service
from hermes_gaze.browser.cdp_bridge import CdpSession

r = Rig(scale=1)
results, failures = {}, []


def check(ok, message):
    if not ok:
        failures.append(message)


def sample():
    return {'host': r.dbg(), 'panel': r.panel('card', '''(()=>{
      const b=document.querySelector('.body'), c=document.querySelector('.card');
      return {top:b.scrollTop, bodyH:b.clientHeight, contentH:b.scrollHeight,
        rootH:document.getElementById('root').offsetHeight, cardH:c.offsetHeight,
        selected:String(getSelection()), focused:document.activeElement?.dataset.act};})()''')}


def delta(run, text):
    r.turns.delta(session_id='s', turn_id=run['request_id'], delta=text)
    until(lambda: text.strip()[-30:] in r.text(), what='stream delta')
    time.sleep(.15)


def begin(item=''):
    snap = service.resolve_now(r.session, utterance='Explain this', activate=False)
    result = r.turns.submit('Explain this', snap, item_id=item)
    assert result['ok'], result
    run = next(x for x in r.turns.runs if x['request_id'] == result['request_id'])
    r.turns.pre(session_id='s', user_message=run['wire'], turn_id=run['request_id'])
    return run


def finish(run, failed=False):
    if not failed:
        r.turns.post(session_id='s', turn_id=run['request_id'], assistant_response=run['text'])
    r.turns.end(session_id='s', turn_id=run['request_id'], failed=failed,
                **({'turn_exit_reason': 'scripted failure'} if failed else {}))


try:
    r.tab = next(t for t in r.session.cdp._tabs.values() if t.is_connected)
    r.front(r.tab)
    r.aim('#first')
    r.ctx.inject_message = lambda wire, **kw: True
    # Re-arm an unused renderer, deliberately holding frame initialization while the first
    # answer arrives. This uses the real bridge and cached inbox, not panel helper calls.
    entered, release = threading.Event(), threading.Event()
    original = CdpSession._init_ui

    async def delayed(tab):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.01)
        await original(tab)

    errors = []

    def rearm():
        try:
            r.tab._submit(r.tab._on_new_context(force=True), 15)
        except BaseException as exc:
            errors.append(str(exc))

    with patch.object(CdpSession, '_init_ui', delayed):
        worker = threading.Thread(target=rearm)
        worker.start()
        assert entered.wait(5)
        # The fresh overlay needs the same trusted pointer evidence as ordinary first use.
        r.aim('#first')
        run = begin()
        r.turns.delta(session_id='s', turn_id=run['request_id'], delta='Opening words stay visible. ' * 12)
        until(lambda: r.dbg()['view'] == 'answer', what='first answer before frames')
        results['waiting_for_frames'] = r.dbg()
        check(results['waiting_for_frames']['frame']['h'] == 0,
              'unmeasured first answer exposes a small placeholder card')
        release.set()
        worker.join(15)
        assert not worker.is_alive() and not errors, errors
    until(lambda: 'Opening words' in r.text(), what='first frame render')
    time.sleep(.3)
    results['first'] = sample()
    # Simulate late first-use text metrics with a real browser font load. No further
    # inbox update should be needed to resize the plate after the font settles.
    r.panel('card', '''(()=>{
      const face=new FontFace('ColdMetrics','local(Arial)',{sizeAdjust:'145%'});
      document.fonts.add(face);
      const sheet=new CSSStyleSheet();sheet.replaceSync('.a {font-family:ColdMetrics, monospace}');
      document.adoptedStyleSheets=[...document.adoptedStyleSheets,sheet];
      return face.load().then(()=>true);})()''')
    time.sleep(.4)
    results['late_metrics'] = sample()
    p, h = results['late_metrics']['panel'], results['late_metrics']['host']
    check(h['frame']['h'] >= p['rootH'], 'late first text metrics clip outside the host frame')
    r.shot('first-late-metrics')
    delta(run, '\n\n' + 'A long streamed paragraph with useful reading detail. ' * 150)
    results['overflow'] = sample()
    check(results['overflow']['panel']['bodyH'] >=
          min(results['overflow']['panel']['contentH'], results['overflow']['host']['maxBody']) - 1,
          'long first answer does not use available reading height')
    check(results['overflow']['panel']['top'] == 0, 'first streamed answer follows the bottom')
    r.shot('first-stream-top')
    # Exercise native scrolling through the private iframe before checking the bottom boundary.
    rect = r.panel_rect('.body')
    r.move(rect['cx'], rect['cy'])
    r.cmd('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': rect['cx'], 'y': rect['cy'],
                                      'deltaX': 0, 'deltaY': 240})
    until(lambda: r.panel('card', 'document.querySelector(".body").scrollTop') > 0,
          what='trusted wheel scroll')
    time.sleep(.2)
    wheel_top = sample()['panel']['top']
    delta(run, '\n\nMore detail after a manual wheel scroll. ')
    check(abs(sample()['panel']['top'] - wheel_top) <= 1, 'manual wheel position moved on delta')
    # Preserve a reader at the bottom too: proximity to the bottom must not opt into following.
    r.panel('card', '''(()=>{const b=document.querySelector('.body'); b.scrollTop=b.scrollHeight;
      document.querySelector('[data-act="dismiss"]').focus({preventScroll:true});
      const n=document.querySelector('.a .w').firstChild, sel=getSelection();
      sel.setBaseAndExtent(n,0,n,7);return true;})()''')
    time.sleep(.1)
    before = sample()['panel']
    delta(run, '\n\n' + 'More words must not move the reader. ' * 30)
    results['manual_after'] = sample()
    after = results['manual_after']['panel']
    check(abs(after['top'] - before['top']) <= 1, 'manual bottom position moved on delta')
    check(after['selected'] == before['selected'] == 'Opening', 'selection changed on delta')
    check(after['focused'] == before['focused'] == 'dismiss', 'focus changed on delta')
    finish(run)
    time.sleep(.2)
    check(abs(sample()['panel']['top'] - before['top']) <= 1, 'completion moved the reader')
    # Follow-ups/retries append to the same conversation without moving its reader.
    follow = begin(run['item_id'])
    delta(follow, 'Follow-up opening. ' * 20)
    results['followup'] = sample()
    check(abs(sample()['panel']['top'] - before['top']) <= 1, 'follow-up moved the reader')
    finish(follow, failed=True)
    retry_result = r.turns.control('retry', item_id=run['item_id'], request_id=follow['request_id'])
    results['retry_result'] = retry_result
    retry = r.turns.active
    assert retry is not None
    r.turns.pre(session_id='s', user_message=retry['wire'], turn_id=retry['request_id'])
    delta(retry, 'Retry opening. ' * 20)
    check(abs(sample()['panel']['top'] - before['top']) <= 1, 'retry moved the reader')
    finish(retry)
    r.press('Escape', 'Escape')
    until(lambda: r.dbg()['view'] is None, what='dismiss')
    r.press('KeyQ', 'q')
    until(lambda: r.dbg()['view'] == 'answer', what='recall')
    time.sleep(.3)
    results['recall'] = sample()
    check(sample()['panel']['top'] == 0, 'recalled conversation does not open at its start')
    r.shot('recalled-top')
finally:
    results['failures'] = failures
    (OUT / 'first-answer-results.json').write_text(json.dumps(results, indent=2))
    r.close()
print(json.dumps(results, indent=2))
assert not failures, failures
print('PASS: cold readiness/metrics, streaming top, manual scroll/selection/focus, follow-up/retry/recall')
