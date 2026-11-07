"""Private Chrome: keyboard/mouse focus, tap scroll, dead transport and real media compatibility."""
import os, json, time, traceback
from pathlib import Path
OUT = Path(os.environ.get('GAZE_REVIEW_OUT', str(Path(__file__).parent)))
os.environ['HERMES_DISABLE_LAZY_INSTALLS'] = '1'
from devlib import Rig, until
r = Rig(scale=1); out = {}
try:
    r.new_tab()
    r.page('document.body.innerHTML=`<button id=b>Button</button><div style="height:4000px">Page</div>`;window.clicks=0;b.onclick=()=>clicks++;document.body.tabIndex=-1;document.body.focus()')
    r.press('Tab', 'Tab')
    out['keyboard_focus'] = r.page('({id:document.activeElement.id,visible:document.activeElement.matches(":focus-visible")})')
    r.press('Space', ' ')
    out['keyboard_clicks'] = r.page('clicks')
    r.click(35, 18)
    out['mouse_focus_visible'] = r.page('document.activeElement.matches(":focus-visible")')
    r.space_down(); until(lambda: r.session.microphone._stream is not None)
    out['mouse_focus_can_talk'] = True
    r.press('Escape', 'Escape'); r.space_up()
    r.page('document.body.focus();scrollTo(0,0)')
    r.press('Space', ' ')
    until(lambda: r.page('scrollY') > 100)
    out['tap_scroll'] = r.page('scrollY')
    out['tap_state'] = r.dbg()['talk']
    # Trial of the proposed direct media toggle: an earlier site listener already toggles.
    # This is deliberately NOT installed in the plugin: keyup cannot know who handled keydown.
    import io, wave, base64
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0\0'*80000)
    r.page('scrollTo(0,0);document.body.innerHTML="<video id=v muted style=width:640px;height:360px></video>";v.src='+
           json.dumps('data:audio/wav;base64,'+base64.b64encode(audio.getvalue()).decode())+
           ';addEventListener("keydown",e=>{if(e.code==="Space"){v.paused?v.play():v.pause();e.preventDefault()}},true);document.body.focus()')
    r.tab._submit(r.tab._on_new_context(force=True),30)  # site listener predates overlay
    until(lambda:r.page('v.readyState') >= 2)
    r.press('Space',' ');time.sleep(.1)
    first = r.page('({paused:v.paused,time:v.currentTime})')
    second = r.page('''(()=>{
      const media=[...document.querySelectorAll('video,audio')].filter(e=>e.checkVisibility()).sort((a,b)=>b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight)[0];
      if(media)media.paused?media.play():media.pause();
      return {paused:media.paused,time:media.currentTime};
    })()''')
    out['direct_toggle_trial'] = {'after_original':first,'after_direct':second,
        'decision':'drop direct media toggle: it undoes the earlier site shortcut'}
    assert first['paused'] is False and second['paused'] is True
    # Real YouTube, if reachable. Never claim playback success from a mere loaded DOM.
    try:
        if os.environ.get('GAZE_REVIEW_LOCAL_ONLY') == '1':
            raise RuntimeError('External media check omitted: local-fixture-only run')
        r.goto('https://www.youtube.com/watch?v=aqz-KE-bpKQ', settle=3)
        out['youtube_before'] = r.page('({url:location.href,title:document.title,videos:[...document.querySelectorAll("video")].map(v=>({paused:v.paused,time:v.currentTime,ready:v.readyState,error:v.error?.code})),message:document.body.innerText.slice(0,1200)})')
        r.page('document.activeElement?.blur();document.body.tabIndex=-1;document.body.focus()')
        r.press('Space',' '); time.sleep(1)
        out['youtube_after_tap'] = r.page('({scroll:scrollY,videos:[...document.querySelectorAll("video")].map(v=>({paused:v.paused,time:v.currentTime,ready:v.readyState,error:v.error?.code}))})')
        out['youtube_talk_state'] = r.dbg()['talk']
        button=r.aim('.ytp-play-button');r.click(button['cx'],button['cy']);time.sleep(.5)
        out['youtube_after_mouse_play']=r.page('({paused:document.querySelector("video").paused,time:document.querySelector("video").currentTime})')
        r.page('document.activeElement?.blur();document.body.focus()')
        r.press('Space',' ');time.sleep(.5)
        out['youtube_playing_tap']=r.page('({paused:document.querySelector("video").paused,time:document.querySelector("video").currentTime,scroll:scrollY})')
    except Exception as exc:
        out['youtube_limit'] = str(exc)
    # Unexpected socket loss, not the normal explicit close path. Stop only our discovery loop.
    r.new_tab()
    r.page('document.body.innerHTML="<div style=height:4000px>Page</div>";document.body.tabIndex=-1;document.body.focus();window.late=0;window.prevented=null;addEventListener("keydown",e=>{late++;prevented=e.defaultPrevented})')
    from benchmark.probe_companion_ui import Tab
    import urllib.request
    pages=json.load(urllib.request.urlopen(r.session.cdp_http_url+'/json/list'))
    raw=Tab(next(p['webSocketDebuggerUrl'] for p in pages if p['id']==r.tab._target_id))
    r.session.cdp._stop.set(); r.session.cdp._thread.join(12)
    r.tab._submit(r.tab._drop_ws(), 5)
    time.sleep(4.5)
    for kind in ('keyDown','keyUp'):
        raw.send('Input.dispatchKeyEvent',{'type':kind,'key':' ','code':'Space','windowsVirtualKeyCode':32});time.sleep(.03)
    time.sleep(.5)
    out['lost_transport'] = raw.main('({scroll:scrollY,late,prevented})')
    raw.send('Browser.close'); raw.ws.close()
except Exception:
    out['error'] = traceback.format_exc()
finally:
    (OUT/'input-results.json').write_text(json.dumps(out,indent=2));r.close()
print(json.dumps(out,indent=2))
assert 'error' not in out, out.get('error')
assert out['keyboard_focus']['visible'] and out['keyboard_clicks'] == 1
assert out['mouse_focus_can_talk']
assert out['tap_scroll'] > 100 and not out['tap_state']['listening']
assert out['lost_transport']['late'] == 1 and out['lost_transport']['prevented'] is False
print('PASS F1/F7 focus, scroll and fail-open; see JSON for real-site media limits')
