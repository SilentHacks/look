"""Trusted request Stop in private Chrome; scripted SDK host, no devices/providers."""
import json
import os
import time
from pathlib import Path

OUT = Path(os.environ.get('GAZE_REVIEW_OUT', '/tmp/hermes-cancel-request'))
OUT.mkdir(parents=True, exist_ok=True)
os.environ.update(SHOTS=str(OUT), HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig, until, service

r = Rig()
try:
    r.tab = next(t for t in r.session.cdp._tabs.values() if t.is_connected)
    r.front(r.tab)
    r.page('document.body.innerHTML = \'<p id="target">Private cancellation fixture</p>\'')
    r.aim('#target')
    wires = []
    r.ctx.inject_message = lambda wire, **kw: wires.append(wire) or True
    snap = service.resolve_now(r.session, utterance='Explain this', activate=False)
    first = r.turns.submit('Explain this', snap)
    run = r.turns.active
    r.turns.pre(session_id='s', turn_id='cancel-turn', user_message=run['wire'])
    r.turns.delta(session_id='s', turn_id='cancel-turn', delta='## Fixture\n\nRetained partial answer.')
    follow = r.turns.submit('Keep this follow-up', {}, item_id=first['item_id'])
    queued = r.turns.submit('Cancel this follow-up', {}, item_id=first['item_id'])
    stop = lambda request: f'[data-act="cancel_request"][data-turn="{request}"]'
    until(lambda: r.panel_rect(stop(queued['request_id'])), what='queued Stop control')
    r.panel('card', f'document.querySelector({json.dumps(stop(queued["request_id"]))}).click();true')
    time.sleep(.15)
    assert r.turns.runs[-1]['status'] == 'queued', 'synthetic Stop accepted'
    r.click_panel(stop(queued['request_id']))
    until(lambda: r.turns.runs[-1]['status'] == 'cancelled', what='trusted queued Stop')
    assert r.turns.active is run and r.turns.pending[0]['request_id'] == follow['request_id']
    r.click_panel(stop(first['request_id']))
    until(lambda: run['status'] == 'cancelling', what='trusted active Stop')
    until(lambda: 'Stop this request in Hermes' in r.text(), what='SDK cancellation limit')
    assert r.turns.active is run and len(wires) == 1
    r.turns.delta(session_id='s', turn_id='cancel-turn', delta='Must not appear')
    assert run['text'] == 'Retained partial answer.'
    assert not r.page('document.body.textContent.includes("Retained partial answer")')
    r.shot('request-stop')
    r.turns.end(session_id='s', turn_id='cancel-turn', interrupted=True)
    assert r.turns.active is None and r.turns.paused and len(wires) == 1
    until(lambda: r.panel_rect('[data-act="resume"]'), what='resume control')
    r.click_panel('[data-act="resume"]')
    until(lambda: r.turns.active and len(wires) == 2, what='remaining FIFO admission')
    assert r.turns.active['request_id'] == follow['request_id']
    result = dict(synthetic_stop_rejected=True, trusted_active_and_queued_stop=True,
                  sdk_limit_visible=True, partial_retained=True, queued_resume=True,
                  website_cannot_read_answer=True, no_replay=True)
    (OUT / 'cancel-results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print('PASS: trusted request cancellation, retained partial, paused FIFO and SDK limit')
finally:
    r.close()
