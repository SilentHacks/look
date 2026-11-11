"""Trusted replay duplication and cleanup, plus 30s native cancellation. Own Chrome + authorized audio stub."""
import os,json,time,traceback
from pathlib import Path
OUT=Path(os.environ.get('GAZE_REVIEW_OUT', str(Path(__file__).parent)))
os.environ.update(REVIEW_START_URL=Path(__file__).with_name('hostile.html').as_uri(),SHOTS=str(OUT),HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig,until
r=Rig(scale=1);out={}
try:
    r.tab=next(t for t in r.session.cdp._tabs.values() if t.is_connected);r.front(r.tab)
    # Install a site shortcut before the overlay by reinstalling the overlay afterward.
    r.page("window.playing=false;window.toggles=0;addEventListener('keydown',e=>{if(e.code==='Space'){playing=!playing;toggles++}},true)")
    r.tab._submit(r.tab._on_new_context(force=True),30)
    r.page('document.body.tabIndex=-1;document.body.focus();window.redirect=false;audit.events=[]')
    r.press('Space',' ');time.sleep(.3)
    out['media_with_plugin']=r.page('({playing,toggles,events:audit.events})')
    r.iso('window.__LOOK_OVERLAY__.destroy()');r.page('playing=false;toggles=0;audit.events=[]')
    r.press('Space',' ');time.sleep(.3)
    out['media_without_plugin']=r.page('({playing,toggles,events:audit.events})')
    r.tab._submit(r.tab._on_new_context(force=True),30)
    r.page('danger.focus();audit.clicks=0')
    r.press('Space',' ');time.sleep(.3);out['connected_focused_button_clicks']=r.page('audit.clicks')
    # Native cap under the documented hostile-page suppression of keyup.
    r.page('document.body.focus();window.suppressUp=true')
    r.aim('#first');r.space_down();until(lambda:r.session.microphone._stream is not None)
    start=time.monotonic();r.space_up();time.sleep(.2)
    out['suppressed_release_still_recording']=r.session.microphone._stream is not None
    until(lambda: r.session.microphone._stream is None,33)
    out['deadline']={'elapsed_since_ready':round(time.monotonic()-start,3),'discarded':not r.session.microphone._audio,'private_warning_or_reason':r.panel('pill','document.body.innerText')}
    # Stop only our companion; use a separately owned CDP transport to observe surviving page keys.
    from benchmark.probe_companion_ui import Tab
    import urllib.request
    pages=json.load(urllib.request.urlopen(r.session.cdp_http_url+'/json/list'))
    raw=Tab(next(p['webSocketDebuggerUrl'] for p in pages if p['id']==r.tab._target_id))
    r.session.cdp.close();raw.main('window.suppressUp=false;danger.focus();audit.clicks=0;window.toggles=0')
    def tap():
        for k in ['keyDown','keyUp']:
            raw.send('Input.dispatchKeyEvent',{'type':k,'key':' ','code':'Space','windowsVirtualKeyCode':32});time.sleep(.03)
        time.sleep(.3)
    tap();out['closed_transport_focused_button_clicks']=raw.main('audit.clicks')
    raw.iso('window.__LOOK_OVERLAY__.destroy()');tap();out['destroyed_overlay_focused_button_clicks']=raw.main('audit.clicks')
    raw.send('Browser.close');raw.ws.close()
except Exception:out['error']=traceback.format_exc();print(out['error'])
finally:
    (OUT/'space-results.json').write_text(json.dumps(out,indent=2));r.close()
print(json.dumps(out,indent=2))
assert 'error' not in out, out.get('error')
assert out['media_with_plugin']['toggles'] == out['media_without_plugin']['toggles'] == 1
assert out['connected_focused_button_clicks'] == out['closed_transport_focused_button_clicks'] == 1
assert out['destroyed_overlay_focused_button_clicks'] == 2
assert out['deadline']['discarded'] and 29 <= out['deadline']['elapsed_since_ready'] <= 32
print('PASS F1/F7: no duplicate shortcut, shutdown restores input, native cap discards')
