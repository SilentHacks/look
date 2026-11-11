"""Private Chrome, real inbox/renderer, manually stepped answers; no models or devices."""
import json
import os
import time
from pathlib import Path

OUT = Path(os.environ.get('GAZE_REVIEW_OUT', '/private/tmp/look-stack-review'))
OUT.mkdir(parents=True, exist_ok=True)
os.environ.update(REVIEW_START_URL=Path(__file__).with_name('hostile.html').as_uri(),
                  SHOTS=str(OUT), HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig, until, service

r = Rig(scale=1)
results = []
wires = []
r.ctx.inject_message = lambda wire, **kw: wires.append(wire) or True
service._CONFIG.answer_turn_seconds = 3.5
r.session.configure(answer_turn_seconds=3.5)


def shown(name):
    return r.dbg()['view'] == 'answer' and r.dbg()['cur'] == name


def wait_shown(name):
    until(lambda: shown(name), 8, 'card ' + name)
    until(lambda: r.panel('card', 'document.querySelector(".title")?.textContent') == name)
    until(lambda: r.turns.selected == next(i['item_id'] for i in r.turns.items if i['subject'] == name))


def ask(name, follow=''):
    snap = service.resolve_now(r.session, utterance='Explain this', activate=False)
    snap['subject'] = {'name': name, 'count': 1}
    result = r.turns.submit('Explain ' + name, snap, item_id=follow)
    assert result['ok'], result
    return next(run for run in r.turns.runs if run['request_id'] == result['request_id'])


def begin(run, text='First words '):
    assert r.turns.active is run
    r.turns.pre(session_id='s', user_message=run['wire'], turn_id=run['request_id'])
    r.turns.delta(session_id='s', turn_id=run['request_id'], delta=text)


def finish(run):
    r.turns.post(session_id='s', turn_id=run['request_id'], assistant_response=run['text'])
    r.turns.end(session_id='s', turn_id=run['request_id'])


def reset():
    r.move(10, 850)
    r.press('Escape', 'Escape')
    until(lambda: not r.turns.selected)
    r.iso('window.__LOOK_OVERLAY__.Configure({answerTurnMs: 3500})')
    time.sleep(.3)


def settled(name):
    run = ask(name)
    begin(run)
    wait_shown(name)
    finish(run)
    return run


try:
    r.tab = next(t for t in r.session.cdp._tabs.values() if t.is_connected)
    r.front(r.tab)
    r.aim('#first')
    r.move(10, 850)
    r.iso('window.__LOOK_OVERLAY__.Configure({answerTurnMs: 3500})')
    a = settled('Alpha')
    b = ask('Beta')
    # Thinking retains the actual old renderer, even past its original reading deadline.
    for _ in range(40):
        assert shown('Alpha') and 'First words' in r.text()
        time.sleep(.1)
    begin(b)
    wait_shown('Beta')
    assert b['status'] == 'streaming'
    assert 'First words' in r.text()
    assert 'slide-next' in r.panel('card', 'document.querySelector(".card").className')
    finish(b)
    r.press('ArrowUp', 'ArrowUp')
    wait_shown('Alpha')
    results.append('first-words next slide, no thinking gap, up-arrow history')
    r.shot('stack-old-card-reachable')

    reset()
    a = settled('Hover old')
    b = ask('Hover new')
    rect = r.panel_rect('.title')
    r.move(rect['cx'], rect['cy'])
    time.sleep(.2)
    begin(b)
    finish(b)
    time.sleep(.5)
    assert shown('Hover old')
    r.move(10, 850)
    wait_shown('Hover new')
    results.append('hover defers until pointer leaves')

    reset()
    a = settled('Arrow old')
    b = ask('Arrow new')
    r.press('ArrowUp', 'ArrowUp')  # End-of-stack input still counts as reading.
    begin(b)
    finish(b)
    time.sleep(.7)
    assert shown('Arrow old')
    wait_shown('Arrow new')
    results.append('recent arrow defers for 2.5 seconds')

    for interaction in ('scroll', 'selection'):
        reset()
        a = settled(interaction + ' old')
        b = ask(interaction + ' next')
        time.sleep(.5)  # Let plate placement settle before targeting the real frame.
        if interaction == 'scroll':
            rect = r.panel_rect('.body')
            r.move(rect['cx'], rect['cy'])
            r.cmd('Input.dispatchMouseEvent', {'type': 'mouseWheel', 'x': rect['cx'],
                  'y': rect['cy'], 'deltaX': 0, 'deltaY': 80})
            time.sleep(.15)
            r.move(10, 850)
        else:
            r.panel('card', '(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector(".a"));const s=getSelection();s.removeAllRanges();s.addRange(range);return true})()')
            time.sleep(.15)
        begin(b)
        finish(b)
        time.sleep(.7)
        assert shown(interaction + ' old'), (interaction, r.dbg())
        wait_shown(interaction + ' next')
        results.append(interaction + ' defers for 2.5 seconds')

    reset()
    a = ask('Streaming old')
    begin(a)
    wait_shown('Streaming old')
    b = ask('Burst second')
    c = ask('Burst third')
    finish(a)
    begin(b)
    finish(b)
    begin(c)
    finish(c)
    time.sleep(.7)
    assert shown('Streaming old')
    assert not next(i for i in r.turns.items if i['item_id'] == b['item_id'])['presented']
    assert next(i for i in r.turns.items if i['item_id'] == b['item_id'])['unread']
    wait_shown('Burst second')
    time.sleep(.7)
    assert shown('Burst second')
    wait_shown('Burst third')
    results.append('streaming old gets full turn; burst shown in capture order, unread until shown')

    follow = ask('More detail', c['item_id'])
    begin(follow, 'Follow-up words ')
    assert shown('Burst third')
    finish(follow)
    until(lambda: 'Follow-up words' in r.text())
    results.append('follow-up stays on the same card')

    reset()
    a = settled('Stop old')
    b = ask('Stop new')
    begin(b, '')
    r.iso('window.__LOOK_OVERLAY__.onSessionEvent({type:"action_task",status:"doing",label:"Working"})')
    r.turns.delta(session_id='s', turn_id=b['request_id'], delta='First words ')
    time.sleep(.5)
    assert r.dbg()['view'] == 'doing' and 'Stop' in r.text()
    r.iso('window.__LOOK_OVERLAY__.onSessionEvent({type:"action_task",status:"stopped"})')
    wait_shown('Stop new')
    finish(b)
    results.append('Stop task retains surface, queued answer resumes afterward')

    reset()
    a = settled('Confirm old')
    b = ask('Confirm new')
    begin(b, '')
    r.aim('#danger')
    snap = service.resolve_now(r.session, utterance='Delete this', activate=False)
    rid = r.session.store_hover_snapshot(snap)
    assert r.session.actions.click(snap['top']['id'], rid)['confirmation_required']
    until(lambda: r.dbg()['view'] == 'confirm')
    r.move(10, 850)
    r.turns.delta(session_id='s', turn_id=b['request_id'], delta='First words ')
    finish(b)
    time.sleep(.5)
    assert r.dbg()['view'] == 'confirm' and r.panel('card', '!!document.querySelector(".choice.yes")')
    r.iso('window.__LOOK_OVERLAY__.clearActionConfirmation()')
    wait_shown('Confirm new')
    results.append('confirmation retains surface, queued answer resumes afterward')

    # A new document restores Python's selected/presented state, not an empty stack.
    r.goto(Path(__file__).with_name('hostile.html').as_uri() + '?stack-restore')
    wait_shown('Confirm new')
    r.press('ArrowUp', 'ArrowUp')
    wait_shown('Confirm old')
    results.append('navigation restores selected card and history')

    r.new_tab(Path(__file__).with_name('hostile.html').as_uri() + '?stack-tab')
    wait_shown('Confirm old')
    r.press('ArrowDown', 'ArrowDown')
    wait_shown('Confirm new')
    results.append('tab change restores Python selection and history')

    r.cmd('Emulation.setEmulatedMedia', {'features': [
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
    reset()
    a = settled('Reduced old')
    b = ask('Reduced next')
    begin(b)
    wait_shown('Reduced next')
    assert r.panel('card', 'getComputedStyle(document.querySelector(".card")).animationName') == 'none'
    finish(b)
    results.append('reduced motion swaps without slide animation')
finally:
    (OUT / 'stack-results.json').write_text(json.dumps(results, indent=2))
    r.close()

print(json.dumps(results, indent=2))
print('PASS stack follows question: all approved scenarios')
