"""Run with HERMES_DISABLE_LAZY_INSTALLS=1 project .venv Python. Own Chrome only; no model/microphone."""
import os,sys,json,time,traceback
from pathlib import Path
OUT=Path(os.environ.get('GAZE_REVIEW_OUT', str(Path(__file__).parent)))
os.environ['REVIEW_START_URL']=Path(__file__).with_name('hostile.html').as_uri()
os.environ['SHOTS']=str(OUT)
os.environ['HERMES_DISABLE_LAZY_INSTALLS']='1'
from devlib import Rig,until
r=Rig(scale=1)
results={}
def save(): (OUT/'security-results.json').write_text(json.dumps(results,indent=2))
def reset():
    r.page("window.redirect=false;window.suppressUp=false;document.activeElement?.blur();audit.events=[];audit.clicks=0;window.scrollTo(0,0)")
def tap(): r.press('Space',' ');time.sleep(.25)
def arm():
    t=r.tab
    assert t._submit(t._on_new_context(force=True),30)
    time.sleep(.3)
try:
    r.tab=next(t for t in r.session.cdp._tabs.values() if t.is_connected)
    r.front(r.tab);time.sleep(.5)
    # Actual injection happened after fixture installed its main-world API patches.
    results['preinjection_hooks']=r.page('({patches:audit.patches,shadows:audit.shadows.length})')
    r.aim('#first')
    private='PRIVATE-ANSWER-CANARY-48392 with **bold** and [unsafe](javascript:alert(1)) ![remote](https://invalid.test/private.png) <img src=https://invalid.test/x onerror=alert(1)>.'
    r.iso('window.__LOOK_OVERLAY__.showHudMessage('+json.dumps(private)+')')
    time.sleep(.8)
    results['answer_private_frame']=r.text()
    results['answer_page_harvest']=r.page('harvest()')
    r.shot('privacy-answer')
    r.press('Escape','Escape');time.sleep(.3)
    r.aim('#first');r.press('AltRight','Alt');time.sleep(.6)
    until(lambda:r.panel('card','document.activeElement?.id')=='hg-input')
    for c in 'PRIVATE-TYPED-CANARY-29481':r.cmd('Input.dispatchKeyEvent',{'type':'char','text':c})
    results['typed_private_frame']=r.panel('card','document.activeElement.value')
    results['typed_page_harvest']=r.page('harvest()')
    r.shot('privacy-typed')
    r.press('Escape','Escape');time.sleep(.4)
    # Synthetic page keys must not arm the microphone or forge UI.
    r.page("for(const code of ['Space','AltRight','KeyQ','Enter']){for(const type of ['keydown','keyup'])window.dispatchEvent(new KeyboardEvent(type,{code,key:code,bubbles:true}))}")
    time.sleep(.3)
    results['synthetic_keys']=r.dbg()['talk']
    # The same physical tap on body retargeted by a page to a dangerous button.
    reset();r.page('window.redirect=true');tap()
    results['replay_retarget_with_plugin']=r.page('({clicks:audit.clicks,events:audit.events})')
    # Control: no overlay, same already-installed page listener and physical input.
    r.iso('window.__LOOK_OVERLAY__.destroy()');reset();r.page('window.redirect=true');tap()
    results['replay_retarget_without_plugin']=r.page('({clicks:audit.clicks,events:audit.events})')
    arm();reset()
    r.page("edit.focus()")
    r.press('Space',' ',' ');time.sleep(.2)
    results['editable_space']=r.page('({value:edit.value,events:audit.events})')
    reset();r.page('rich.focus()');r.press('Space',' ',' ');time.sleep(.2)
    results['rich_space']=r.page('({text:rich.textContent,events:audit.events})')
    reset();r.page('frame.contentDocument.getElementById("child").focus()')
    r.space_down();time.sleep(.25)
    results['iframe_hold']=r.dbg()['talk']
    r.space_up();time.sleep(.2)
    results['iframe_events']=r.page('frame.contentWindow.events')
    # Voice level should not affect any main document animation or DOM contents.
    reset();r.aim('#first');r.space_down();time.sleep(.5)
    results['stub_recording']=r.dbg()['talk']
    r.tab.push_level(.01);time.sleep(.2);results['level_low_harvest']=r.page('harvest()')
    r.tab.push_level(.99);time.sleep(.2);results['level_high_harvest']=r.page('harvest()')
    r.press('Escape','Escape');r.space_up();time.sleep(.3)
    # Leave the injected renderer alive, as close() actually does, then test ordinary scrolling.
    reset();r.session.cdp.close()
    # Need an independent CDP connection to send real input after plugin disconnect.
    from benchmark.probe_companion_ui import Tab
    import urllib.request
    pages=json.load(urllib.request.urlopen(r.session.cdp_http_url+'/json/list'))
    t=Tab(next(p['webSocketDebuggerUrl'] for p in pages if p['id']==r.tab._target_id))
    t.main('document.activeElement?.blur();window.scrollTo(0,0);audit.events=[]')
    for kind in ['keyDown','keyUp']:
        t.send('Input.dispatchKeyEvent',{'type':kind,'code':'Space','key':' ','windowsVirtualKeyCode':32});time.sleep(.04)
    time.sleep(.8)
    results['disconnected_space']=t.main('({scrollY,events:audit.events})')
    t.iso('window.__LOOK_OVERLAY__.destroy()')
    for kind in ['keyDown','keyUp']:
        t.send('Input.dispatchKeyEvent',{'type':kind,'code':'Space','key':' ','windowsVirtualKeyCode':32});time.sleep(.04)
    time.sleep(.8)
    results['destroyed_control_space']=t.main('({scrollY,events:audit.events})')
    t.send('Browser.close');t.ws.close()
except Exception:
    results['error']=traceback.format_exc();print(results['error'])
finally:
    save();r.close()
print(json.dumps({k:v for k,v in results.items() if 'harvest' not in k},indent=2))
assert 'error' not in results, results.get('error')
assert results['replay_retarget_with_plugin']['clicks'] == results['replay_retarget_without_plugin']['clicks'] == 0
assert len(results['replay_retarget_with_plugin']['events']) == 2
print('PASS F1: a tap cannot retarget privileged input into a dangerous click')
