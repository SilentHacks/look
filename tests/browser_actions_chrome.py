"""Deterministic private-Chrome checks of production browser actions.

Hermes Python: tests/browser_actions_chrome.py --out /tmp/gaze-production-offline
Uses the production trial's owned HTTP server and Rig fake audio only.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.browser_actions.browser_actions_production import (PROFILE, SECRETS, approve,
    count, oracle, sensitive_unchanged, sync_tab, until)


def probe(rig, tools, fixtures, *, approval_only=False):
    checks = []
    source = rig.tab

    def call(name, **args):
        return json.loads(tools.call(name, args))

    def fresh(kind='form'):
        rig.session.tasks.stop()
        rig.front(source)
        rig.goto(fixtures.url(kind))
        tools.begin()
        info = tools.read()
        assert info.get('ok'), info
        assert not any(s in json.dumps(info) for s in SECRETS)
        return info

    def fill(info):
        entries = [{'handle': f['handle'], 'text': PROFILE[f['label']]}
                   for f in info['fields'] if f['label'] in PROFILE]
        assert entries, info
        result = call('gaze_fill', resolution_id=info['resolution_id'], entries=entries)
        assert result.get('ok') and result.get('executed'), result
        return result

    def commit(info):
        controls = [c for c in info['controls'] if c.get('form_submit')]
        assert len(controls) == 1, info
        result = call('gaze_request_commit', resolution_id=info['resolution_id'], handle=controls[0]['handle'])
        assert result.get('confirmation_required'), result
        assert count(rig) == 0
        return result

    tasks = rig.session.tasks
    try:
        tasks.set_approval_mode('trial', allow_all=True)
        for operation in ('gaze_click', 'gaze_request_commit', 'gaze_press'):
            info = fresh()
            assert info['action_approvals'] == 'allow-all'
            fill(info)
            info = tools.read()
            submit = next(c for c in info['controls'] if c.get('form_submit'))
            args = {'resolution_id': info['resolution_id'], 'handle': submit['handle']}
            if operation == 'gaze_click':
                args['new_tab'] = False
            elif operation == 'gaze_press':
                args['key'] = 'Enter'
            result = call(operation, **args)
            assert result.get('executed') and not result.get('confirmation_required'), result
            assert count(rig) == 1 and tasks.session.actions._pending is None
            assert sensitive_unchanged(rig)
        checks.append('explicit allow-all executes requested submit clicks, commit and Enter without Look review')

        for boundary in ('session', 'turn', 'epoch', 'foreground', 'route', 'document'):
            info = fresh()
            fill(info)
            info = tools.read()
            submit = next(c for c in info['controls'] if c.get('form_submit'))
            args = {'resolution_id': info['resolution_id'], 'handle': submit['handle'], 'new_tab': False}
            if boundary == 'foreground':
                other = rig.new_tab(fixtures.url('unseen'))
            elif boundary == 'route':
                old_route = source._route_id
                rig.page("history.pushState({},'', '?kind=form&route=changed');true")
                until(lambda: source._route_id != old_route)
            elif boundary == 'document':
                rig.goto(fixtures.url('form') + '&document=changed')
            elif boundary == 'epoch':
                tools.read()
            if boundary in ('session', 'turn'):
                result = json.loads(tools.entries['gaze_click'][1](args,
                    session_id='foreign' if boundary == 'session' else 'trial',
                    turn_id='foreign' if boundary == 'turn' else tools.turn_id))
            else:
                result = call('gaze_click', **args)
            assert not result.get('executed') and count(rig) == 0, (boundary, result)
            if boundary == 'foreground':
                rig.front(source)
                rig.cmd('Page.close', tab=other)
            checks.append('allow-all preserves ' + boundary + ' ownership')

        info = fresh()
        fill(info)
        info = tools.read()
        submit = next(c for c in info['controls'] if c.get('form_submit'))
        original = rig.session.eval_js_once
        clicks = []
        def lose_commit_reply(expression, *args, **kwargs):
            result = original(expression, *args, **kwargs)
            if '.clickSnapshot(' in expression:
                clicks.append(expression)
                raise ConnectionError('Owned fixture lost reply after commit')
            return result
        args = {'resolution_id': info['resolution_id'], 'handle': submit['handle']}
        with patch.object(rig.session, 'eval_js_once', side_effect=lose_commit_reply):
            result = call('gaze_request_commit', **args)
        assert result.get('outcome') == 'unknown' and len(clicks) == 1 and count(rig) == 1, result
        assert not call('gaze_request_commit', **args).get('executed') and count(rig) == 1
        assert not tools.read().get('ok')
        checks.append('allow-all lost commit reply revokes task after exactly one execution without replay')
    finally:
        tasks.set_approval_mode()

    info = fresh()
    assert info['action_approvals'] == 'confirm'
    commit(info)
    assert count(rig) == 0
    checks.append('disabling allow-all restores protected default review')
    if approval_only:
        return {'checks': checks, 'calls': tools.calls}

    info = fresh()
    rig.page("""(() => {
      const next=document.createElement('button');next.type='button';next.textContent='Next';
      next.onclick=()=>{
        history.pushState({}, '', location.href+'&step=two');
        const input=document.createElement('input');input.id='next-entry';input.setAttribute('aria-label','Next entry');
        document.body.prepend(input);
      };
      document.body.prepend(next);return true;
    })()""")
    info = tools.read()
    next_control = next(c for c in info['controls'] if c['label'] == 'Next')
    result = call('gaze_click', resolution_id=info['resolution_id'], handle=next_control['handle'], new_tab=False)
    assert result.get('executed'), result
    info = tools.read()
    assert info.get('ok'), info
    field = next(f for f in info['fields'] if f['label'] == 'Next entry')
    assert call('gaze_fill', resolution_id=info['resolution_id'],
                entries=[{'handle':field['handle'], 'text':'Continued'}]).get('executed')
    assert rig.page("document.querySelector('#next-entry').value") == 'Continued'
    checks.append('non-link navigation continues on the same owned tab with fresh destination identities')

    info = fresh()
    rig.page("""(() => {
      const next=document.createElement('button');next.type='button';next.textContent='Next';
      next.onclick=()=>location.assign('/slow-redirect');document.body.prepend(next);return true;
    })()""")
    info = tools.read()
    next_control = next(c for c in info['controls'] if c['label'] == 'Next')
    result = call('gaze_click', resolution_id=info['resolution_id'], handle=next_control['handle'], new_tab=False)
    assert result.get('executed'), result
    assert rig.page('location.pathname') == '/browser_actions_unseen.html', result
    assert tools.read().get('ok')
    checks.append('non-link document navigation waits through a delayed redirect without replay or focus retargeting')

    # Exact values on five generic fixture kinds; no fixture knowledge enters production code.
    for kind in ('form', 'layout', 'wizard', 'unseen'):
        info = fresh(kind)
        if kind == 'form':
            assert len(info['fields']) == 9, info
        fill(info)
        if kind == 'wizard':
            info = tools.read()
            next_control = next(c for c in info['controls'] if c['label'] == 'Next')
            result = call('gaze_click', resolution_id=info['resolution_id'], handle=next_control['handle'], new_tab=False)
            assert result.get('executed') and not result.get('confirmation_required'), result
            info = tools.read()
            fill(info)
        info = tools.read()
        actual, ok = oracle(rig, kind, source._target_id)
        assert ok, (kind, actual)
        assert sensitive_unchanged(rig)
        commit(info)
        approval = approve(rig)
        assert all(approval.values()), approval
        assert count(rig) == 1
        checks.append(kind + ': exact values, sensitive exclusion, zero preapproval commits, synthetic rejection, trusted single-use approval')

    dimensions = rig.width, rig.height
    rig.width, rig.height = 390, 420
    try:
        info = fresh()
        fill(info)
        commit(tools.read())
        time.sleep(.8)
        yes = rig.panel_rect('.choice.yes')
        assert 0 <= yes['cx'] <= 390 and 0 <= yes['cy'] <= 420, yes
        rig.shot('narrow-action-confirmation')
        assert all(approve(rig).values())
        checks.append('content-bound confirmation remains usable in a390-by420 viewport')
    finally:
        rig.width, rig.height = dimensions
        rig.front(source)

    info = fresh()
    compose = next(c for c in info['controls'] if c.get('url') and 'kind=mail' in c['url'])
    result = call('gaze_open_tab', resolution_id=info['resolution_id'], url=compose['url'])
    assert result.get('ok'), result
    until(lambda: rig.session.cdp._target()._target_id != source._target_id)
    sync_tab(rig)
    info = tools.read()
    values = {'To': 'robin@example.test', 'Subject': 'Garden club meeting',
              'Message': 'Robin, our garden club meeting moves to Thursday at 3 PM in the community room. Please bring the seed catalogue. Alex'}
    result = call('gaze_fill', resolution_id=info['resolution_id'], entries=[
        {'handle': f['handle'], 'text': values[f['label']]} for f in info['fields']])
    assert result.get('executed'), result
    actual, ok = oracle(rig, 'mail', source._target_id)
    assert ok and actual == dict(zip(('to', 'subject', 'body'), values.values())), actual
    commit(tools.read())
    assert all(approve(rig).values())
    checks.append('mail: genuinely new foreground tab, exact draft and guarded Send')
    rig.session.tasks.stop()
    mail_tab = rig.tab
    rig.front(source)
    rig.cmd('Page.close', tab=mail_tab)

    info = fresh()
    compose = next(c for c in info['controls'] if c.get('url') and 'kind=mail' in c['url'])
    result = call('gaze_click', resolution_id=info['resolution_id'], handle=compose['handle'], new_tab=False)
    assert result.get('ok') and result.get('executed') and result.get('resolution_id'), result
    assert tools.read().get('ok') and rig.page('location.href') == fixtures.url('mail')
    checks.append('captured navigation link transfers ownership and returns fresh destination structure')

    info = fresh()
    compose = next(c for c in info['controls'] if c.get('url') and 'kind=mail' in c['url'])
    result = call('gaze_click', resolution_id=info['resolution_id'], handle=compose['handle'], new_tab=True)
    assert result.get('ok') and result.get('opened_new_tab'), result
    sync_tab(rig)
    assert rig.tab is not source and rig.page('location.href') == fixtures.url('mail')
    assert tools.read().get('ok')
    checks.append('explicit captured-link tab choice opens and owns a genuinely new tab')
    rig.session.tasks.stop()
    link_tab = rig.tab
    rig.front(source)
    rig.cmd('Page.close', tab=link_tab)

    for new_tab in (False, True):
        info = fresh()
        rig.page("""(() => {const a=document.createElement('a');a.id='private-jump';a.textContent='Jump to notes';
          a.href=location.href+'&access_token=URL_PRIVATE_CANARY#notes';document.body.prepend(a);return true;})()""")
        info = tools.read()
        jump = next(c for c in info['controls'] if c['label'] == 'Jump to notes')
        result = call('gaze_click', resolution_id=info['resolution_id'], handle=jump['handle'], new_tab=new_tab)
        assert result.get('ok') and result.get('executed'), result
        if new_tab:
            sync_tab(rig)
            assert rig.tab is not source
        assert rig.page("location.href.includes('URL_PRIVATE_CANARY') && location.hash === '#notes'")
        assert 'URL_PRIVATE_CANARY' not in json.dumps(result)
        if new_tab:
            rig.session.tasks.stop()
            private_tab = rig.tab
            rig.front(source)
            rig.cmd('Page.close', tab=private_tab)
    checks.append('captured links preserve private query and fragment in current and new tabs without model exposure')

    info = fresh()
    rig.page("document.body.insertAdjacentHTML('afterbegin','<a id=redirect href=/redirect>Read next page</a>');true")
    info = tools.read()
    jump = next(c for c in info['controls'] if c['label'] == 'Read next page')
    result = call('gaze_click', resolution_id=info['resolution_id'], handle=jump['handle'], new_tab=False)
    assert result.get('ok') and result.get('executed') and result.get('fields'), result
    assert rig.tab is source and rig.page('location.href') == fixtures.url('unseen')
    checks.append('captured same-tab links follow HTTP redirects and return the pinned destination structure')

    info = fresh()
    rig.page("""(() => { const titled=document.createElement('input');titled.id='titled-otp';titled.title='One-time code';
      titled.value='OTP_PRIVATE_CANARY';document.querySelector('#registration-form').prepend(titled);
      const label=document.createElement('span');label.id='aria-secret-label';label.textContent='Security code';
      const coded=document.createElement('input');coded.id='aria-otp';coded.setAttribute('aria-labelledby',label.id);
      coded.value='ARIA_PRIVATE_CANARY';document.querySelector('#registration-form').prepend(label,coded);
      const nested=document.createElement('span');nested.id='nested-label';nested.append('Reference');
      const privateText=document.createElement('textarea');privateText.name='password';privateText.textContent='NESTED_PRIVATE_CANARY';
      nested.append(privateText);const ordinary=document.createElement('input');ordinary.setAttribute('aria-labelledby',nested.id);
      document.querySelector('#registration-form').prepend(nested,ordinary);return true;})()""")
    info = tools.read()
    assert not any(f['label'] in ('One-time code', 'Security code') for f in info['fields'])
    assert not any(s in json.dumps(info) for s in ('OTP_PRIVATE_CANARY','ARIA_PRIVATE_CANARY','NESTED_PRIVATE_CANARY','Security code'))
    fill(info)
    commit(info)
    until(lambda: rig.dbg().get('view') == 'confirm')
    assert not any(s in rig.text() for s in ('OTP_PRIVATE_CANARY','ARIA_PRIVATE_CANARY','NESTED_PRIVATE_CANARY'))
    assert rig.page("document.querySelector('#titled-otp').value==='OTP_PRIVATE_CANARY' && document.querySelector('#aria-otp').value==='ARIA_PRIVATE_CANARY'")
    checks.append('title and root-scoped ARIA labels exclude secret fields from reads, writes and approval summaries')

    info = fresh()
    rig.page("""(() => {document.body.replaceChildren();for(let n=0;n<90;n++){
      const field=document.createElement('input');field.id='field-'+n;field.setAttribute('aria-label','Entry '+n);
      field.style.cssText='display:block;height:40px;margin:12px';document.body.append(field);
    }return true;})()""")
    info = tools.read()
    assert 'Entry 0' in [f['label'] for f in info['fields']] and len(info['fields']) <= 64
    rig.page("document.querySelector('#field-89').scrollIntoView();true")
    info = tools.read()
    last = next(f for f in info['fields'] if f['label'] == 'Entry 89')
    assert call('gaze_fill', resolution_id=info['resolution_id'], entries=[{'handle':last['handle'],'text':'Reachable after scroll'}]).get('executed')
    assert rig.page("document.querySelector('#field-89').value") == 'Reachable after scroll'
    checks.append('scrolling and recapture exposes later controls beyond the 64-identity cap')

    info = fresh()
    rig.page("""(() => {const base=document.createElement('base');base.href=location.origin+'/other-root/';
      document.head.append(base);document.querySelector('#submit').setAttribute('formaction','charge');return true;})()""")
    info = tools.read()
    fill(info)
    commit(info)
    until(lambda: '/other-root/charge' in rig.text())
    rig.page("document.querySelector('base').href=location.origin+'/changed-root/';document.querySelector('base').href=location.origin+'/other-root/';true")
    time.sleep(.8)
    rig.click_panel('[data-act="confirm"][data-value="yes"]')
    time.sleep(.2)
    assert count(rig) == 0
    checks.append('confirmation shows browser-resolved base/formaction destination and rejects a changed base')

    info = fresh()
    fill(info)
    field = next(f for f in info['fields'] if f['label'] == 'Full name')
    rig.page("window.keySeen=false;document.querySelector('#full-name').addEventListener('keydown',e=>{window.keySeen=e.isTrusted&&e.key==='ArrowLeft';});true")
    rejected = call('gaze_press', resolution_id=info['resolution_id'], handle=field['handle'], key='Escape')
    assert not rejected.get('executed'), rejected  # Reserved user Stop must not masquerade as a page key.
    result = call('gaze_press', resolution_id=info['resolution_id'], handle=field['handle'], key='ArrowLeft')
    assert result.get('executed') and rig.page('window.keySeen'), result
    result = call('gaze_press', resolution_id=info['resolution_id'], handle=field['handle'], key='Enter')
    assert result.get('confirmation_required') and count(rig) == 0, result
    rig.session.actions.invalidate()
    result = call('gaze_scroll', resolution_id=info['resolution_id'], pixels=120)
    assert result.get('ok'), result
    result = call('gaze_wait', seconds=.05)
    assert result.get('ok'), result
    info = tools.read()
    result = call('gaze_navigate', resolution_id=info['resolution_id'], url=fixtures.url('unseen'))
    assert result.get('ok'), result
    sync_tab(rig)
    assert rig.tab is source and rig.page('location.href') == fixtures.url('unseen')
    checks.append('native navigation keys, guarded Enter, bounded scroll/wait and same-tab HTTP navigation')

    info = fresh()
    fill(info)
    old = info['resolution_id']
    current = tools.read()
    assert current['resolution_id'] != old
    result = call('gaze_fill', resolution_id=old, entries=[{'handle': info['fields'][0]['handle'], 'text': 'SHOULD NOT WRITE'}])
    assert not result.get('ok') and result.get('structure', {}).get('ok'), result
    assert result['structure']['resolution_id'] > old, result
    assert oracle(rig, 'form', source._target_id)[1]
    checks.append('stale epoch rejected with fresh structure and no mutation')

    info = tools.read()
    name = next(f for f in info['fields'] if f['label'] == 'Full name')
    day = next(f for f in info['fields'] if f['label'] == 'Preferred date')
    result = call('gaze_fill', resolution_id=info['resolution_id'], entries=[
        {'handle': name['handle'], 'text': 'MUST NOT PARTIALLY WRITE'},
        {'handle': day['handle'], 'text': 'November 10, 2026'}])
    assert not result.get('ok') and not result.get('executed'), result
    assert oracle(rig, 'form', source._target_id)[1]
    checks.append('invalid native date is rejected before any batch write, preserving existing values')

    info = tools.read()
    result = call('gaze_request_commit', resolution_id=info['resolution_id'], handle='@missing')
    assert not result.get('ok') and not rig.session.actions._pending and count(rig) == 0, result
    rig.page("document.querySelector('#submit').remove();true")
    info = tools.read()
    assert not any(c.get('form_submit') for c in info['controls'])
    assert not call('gaze_request_commit', resolution_id=info['resolution_id'], handle='@missing').get('ok')
    checks.append('missing commit handle fails honestly without inferred target')

    info = fresh()
    fill(info)
    commit(tools.read())
    until(lambda: rig.dbg().get('view') == 'confirm')
    time.sleep(.65)
    point = rig.panel_rect('.choice.yes')
    rig.page("document.querySelector('#city').value='Changed after review';document.querySelector('#city').dispatchEvent(new Event('input',{bubbles:true}));true")
    rig.click(point['cx'], point['cy'])
    time.sleep(.3)
    assert count(rig) == 0 and rig.session.actions._pending is None
    checks.append('content edit invalidates approval before trusted click')

    info = fresh('unseen')
    fill(info)
    rig.page("""(() => {
      const tab = document.createElement('div'); tab.id='choice-tab'; tab.role='tab';
      tab.textContent='Schedule'; tab.tabIndex=0; tab.onclick=()=>audit.choice=(audit.choice||0)+1;
      application.append(tab);
      const chip=document.createElement('span');chip.id='recipient-chip';chip.textContent='robin@example.test';
      application.append(chip);
      const external=document.createElement('button');external.id='outside-submit';external.type='submit';
      external.setAttribute('form','application');external.textContent='Next';document.body.append(external);
      return true;
    })()""")
    info = tools.read()
    tab = next(c for c in info['controls'] if c['label'] == 'Schedule')
    assert call('gaze_click', resolution_id=info['resolution_id'], handle=tab['handle'], new_tab=False).get('executed')
    assert rig.page('audit.choice') == 1
    info = tools.read()
    tab = next(c for c in info['controls'] if c['label'] == 'Schedule')
    rig.page("document.querySelector('#choice-tab').style.opacity='0';true")
    assert not call('gaze_click', resolution_id=info['resolution_id'], handle=tab['handle'], new_tab=False).get('executed')
    external = next(c for c in info['controls'] if c['label'] == 'Next')
    assert call('gaze_click', resolution_id=info['resolution_id'], handle=external['handle'], new_tab=False).get('confirmation_required')
    until(lambda: 'robin@example.test' in rig.text())
    time.sleep(.7)
    point = rig.panel_rect('.choice.yes')
    rig.page("document.querySelector('#recipient-chip').textContent='changed@example.test';true")
    rig.click(point['cx'], point['cy'])
    time.sleep(.3)
    assert count(rig) == 0 and rig.session.actions._pending is None
    checks.append('ARIA selection, hidden rejection, external form submit and content-chip approval binding')

    info = fresh()
    assert not call('gaze_navigate', resolution_id=info['resolution_id'],
                    url=rig.session.cdp_http_url + '/json').get('ok')
    assert rig.page('location.href') == fixtures.url('form')
    checks.append('model navigation cannot reach the companion debugger origin')

    # Foreground, same-document route, replaced document each revoke old action authority.
    for boundary in ('foreground', 'route', 'document'):
        info = fresh()
        if boundary == 'foreground':
            other = rig.new_tab(fixtures.url('unseen'))
        elif boundary == 'route':
            old_route = source._route_id
            rig.page("history.pushState({},'', '?kind=form&route=changed');true")
            until(lambda: source._route_id != old_route)
        else:
            rig.goto(fixtures.url('form') + '&document=changed')
        result = call('gaze_fill', resolution_id=info['resolution_id'], entries=[
            {'handle': info['fields'][0]['handle'], 'text': 'FORBIDDEN BOUNDARY WRITE'}])
        assert not result.get('executed'), (boundary, result)
        assert rig.page("!Array.from(document.querySelectorAll('input')).some(e=>e.value==='FORBIDDEN BOUNDARY WRITE')")
        if boundary == 'foreground':
            rig.front(source)
            rig.cmd('Page.close', tab=other)
        checks.append(boundary + ' boundary rejects stale task mutation')

    info = fresh()
    writes = []
    original = rig.session.eval_js_once
    def lose_reply(expression, *args, **kwargs):
        result = original(expression, *args, **kwargs)
        if '.actionWrite(' in expression:
            writes.append(expression)
            raise ConnectionError('Owned test: mutation reply lost after application')
        return result
    with patch.object(rig.session, 'eval_js_once', side_effect=lose_reply):
        result = call('gaze_fill', resolution_id=info['resolution_id'], entries=[
            {'handle': info['fields'][0]['handle'], 'text': 'Once only'}])
    assert result.get('outcome') == 'unknown' and len(writes) == 1, result
    replay = call('gaze_fill', resolution_id=info['resolution_id'], entries=[
        {'handle': info['fields'][0]['handle'], 'text': 'REPLAY FORBIDDEN'}])
    assert not replay.get('executed'), replay
    assert rig.page("document.querySelector('#full-name').value") == 'Once only'
    assert not tools.read().get('ok'), 'Unknown mutation must revoke the grant, not recover silently'
    checks.append('lost mutation reply revokes grant without replay')

    info = fresh()
    original_command = rig.session.cdp.chrome.command
    created = []
    def malformed_reply(method, *args, **kwargs):
        result = original_command(method, *args, **kwargs)
        if method == 'Target.createTarget':
            created.append(result['targetId'])
            return {}
        return result
    with patch.object(rig.session.cdp.chrome, 'command', side_effect=malformed_reply):
        result = call('gaze_open_tab', resolution_id=info['resolution_id'], url=fixtures.url('mail'))
    assert result.get('outcome') == 'unknown' and result.get('executed') is None, result
    assert len(created) == 1 and not tools.read().get('ok')
    created_tab = until(lambda: (tab if (tab := rig.session.cdp._tabs.get(created[0])) and tab.is_connected else None))
    rig.front(source)
    rig.cmd('Page.close', tab=created_tab)
    checks.append('malformed create-tab reply revokes authority after one real tab creation without replay')

    info = fresh()
    fill(info)
    commit(tools.read())
    result = rig.session.tasks.stop()
    assert result.get('ok') and rig.session.actions._pending is None, result
    result = call('gaze_fill', resolution_id=info['resolution_id'], entries=[
        {'handle': info['fields'][0]['handle'], 'text': 'AFTER STOP'}])
    assert not result.get('executed') and not tools.read().get('ok') and count(rig) == 0, result
    checks.append('Stop cancels pending approval and revokes read/mutation authority')

    info = fresh()
    fill(info)
    commit(info)
    grant = dict(rig.session.tasks.grant)
    rig.session.tasks.finish(grant['session_id'], grant['turn_id'])
    until(lambda: rig.dbg().get('view') == 'confirm')
    time.sleep(.8)
    rig.click_panel('[data-act="stop_action_task"]')
    until(lambda: rig.session.actions._pending is None)
    assert count(rig) == 0
    checks.append('visible confirmation Stop revokes pending approval after model completion')

    # Exercise actual inbox admission from both protected typing and fake native speech.
    from hermes_gaze.audio import voice
    import threading
    from tests.browser_actions.browser_actions_production import FORM_ASK
    admitted, errors = [], []
    done = threading.Event()
    def perform_inbox_task(wire):
        turn = 'input-' + str(len(admitted) + 1)
        try:
            rig.turns.pre(session_id='s', turn_id=turn, user_message=wire)
            def actual(name, args):
                result = json.loads(tools.entries[name][1](args, session_id='s', turn_id=turn))
                assert result.get('ok'), result
                return result
            info = actual('gaze_read', {})
            actual('gaze_fill', {'resolution_id': info['resolution_id'], 'entries': [
                {'handle': f['handle'], 'text': PROFILE[f['label']]} for f in info['fields']]})
            submit = next(c for c in info['controls'] if c.get('form_submit'))
            result = actual('gaze_request_commit', {'resolution_id': info['resolution_id'], 'handle': submit['handle']})
            assert result.get('confirmation_required') and count(rig) == 0, result
            admitted.append(rig.session.tasks.grant['turn_id'])
            rig.turns.post(session_id='s', turn_id=turn, assistant_response='## Prepared\n\nReview the form in Chrome.')
            rig.turns.end(session_id='s', turn_id=turn)
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            done.set()
    with patch.object(rig.host, 'play', side_effect=perform_inbox_task), \
            patch.object(voice, 'transcribe_audio_buffer', return_value=(FORM_ASK, [])):
        for mode in ('typed', 'voice'):
            rig.front(source)
            rig.goto(fixtures.url('form'))
            rig.aim('#form-heading')
            done.clear()
            if mode == 'typed':
                rig.press('AltRight', 'Alt')
                until(lambda: rig.dbg().get('view') == 'compose')
                until(lambda: rig.panel('card', "document.activeElement?.id === 'hg-input'"))
                rig.cmd('Input.insertText', {'text': FORM_ASK})
                rig.press('Enter', 'Enter')
            else:
                rig.ask_voice('#form-heading')
            assert done.wait(15) and not errors, errors
            assert oracle(rig, 'form', source._target_id)[1]
            until(lambda: rig.dbg().get('view') == 'confirm')
            time.sleep(.8)  # Let the existing glass/text arrival finish before visual evidence.
            assert 'Alex Morgan' in rig.text()
            rig.shot(mode + '-action-confirmation')
            assert all(approve(rig).values())
            checks.append(mode + ' inbox user turn runs production read/fill/review with exact source ownership')

    fresh()
    until(lambda: rig.dbg().get('view') == 'doing')
    time.sleep(.8)
    rig.shot('doing-action')
    rig.click_panel('[data-act="stop_action_task"]')
    until(lambda: rig.session.tasks._stopped.is_set())
    assert not tools.read().get('ok') and count(rig) == 0
    checks.append('visible Doing/Stop revokes the task through trusted protected-frame input')
    for selector in (None, '#full-name', '#notes'):
        fresh()
        until(lambda: rig.dbg().get('view') == 'doing')
        if selector:
            rig.page(f"document.querySelector({json.dumps(selector)}).focus();true")
        rig.press('Escape', 'Escape')
        until(lambda: rig.session.tasks._stopped.is_set())
        assert not tools.read().get('ok') and count(rig) == 0
    checks.append('trusted Escape revokes the task from body, input and textarea focus')
    assert not any(s in json.dumps(tools.calls) for s in SECRETS)
    rig.front(source)
    return {'checks': checks, 'calls': tools.calls,
            'limitations': ['Local fixtures do not prove cross-origin frames, closed shadow or canvas/custom widgets.',
                'Native CDP driver stands in for human input. Websites cannot mint it; explicitly granted raw debugger code can.',
                'Typing and GET navigation may trigger site-side effects; no universal application-semantic containment.']}


def main():
    # One implementation of lifecycle/isolation; this entrypoint selects deterministic mode.
    from tests.browser_actions.browser_actions_production import main as trial_main
    if '--offline' not in sys.argv:
        sys.argv.append('--offline')
    trial_main()


if __name__ == '__main__':
    main()
