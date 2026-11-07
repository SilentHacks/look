"""Diagnose the existing browser harness's missed real confirmation click, no production edits."""
import os,json,time,traceback
from pathlib import Path
OUT=Path(os.environ.get('GAZE_REVIEW_OUT', str(Path(__file__).parent)))
os.environ.update(REVIEW_START_URL=Path(__file__).with_name('hostile.html').as_uri(),SHOTS=str(OUT),HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig,until,service
r=Rig(scale=1);out={};traffic=[]
def handle(intent,reply):
 def got(msg):
  traffic.append({'intent':intent.get('type'),'reply':msg});reply(msg)
 service.handle_intent(intent,got)
try:
 r.tab=next(t for t in r.session.cdp._tabs.values() if t.is_connected);r.front(r.tab);r.session.cdp.set_intent_handler(handle)
 r.aim('#danger');s=service.resolve_now(r.session,utterance='Delete this',activate=False)
 rid=r.session.store_hover_snapshot(s);hid=s['top']['id'];out['request']=r.session.actions.click(hid,rid)
 until(lambda:r.dbg()['view']=='confirm');time.sleep(.5)
 r.panel('card',"document.querySelector('.choice.yes').click();document.querySelector('.choice.yes').focus();true")
 r.press('Enter','Enter','\r');time.sleep(.3)
 out['keyboard_result']={'clicks':r.page('audit.clicks'),'pending':bool(r.session.actions._pending),'view':r.dbg()}
 out['geometry']=r.panel_rect('.choice.yes');out['before']=r.panel('card','document.body.innerText')
 r.click_panel('.choice.yes');time.sleep(.7)
 out['mouse_result']={'clicks':r.page('audit.clicks'),'pending':bool(r.session.actions._pending),'view':r.dbg(),'traffic':traffic}
 r.shot('confirmation-after-mouse')
 out['rapid_clicks']=[]
 r.panel('card', "window.inputLog=[];for(const kind of ['pointerdown','pointerup','click'])document.addEventListener(kind,e=>inputLog.push({kind,target:e.target.className,detail:e.detail,trusted:e.isTrusted}));true")
 for trial in range(12):
  r.aim('#danger');s=service.resolve_now(r.session,utterance='Delete this',activate=False)
  rid=r.session.store_hover_snapshot(s);hid=s['top']['id']
  assert r.session.actions.click(hid,rid)['confirmation_required']
  until(lambda:r.panel('card',"!!document.querySelector('.choice.yes') && Number(getComputedStyle(document.querySelector('.card')).opacity)>.2"))
  before=r.page('audit.clicks')
  r.click_panel('.choice.yes')
  try:
   until(lambda:r.page('audit.clicks')==before+1,2,'rapid confirmation')
   out['rapid_clicks'].append({'trial':trial,'ok':True})
  except AssertionError:
   out['rapid_clicks'].append({'trial':trial,'ok':False,'geometry':r.panel_rect('.choice.yes'),'view':r.dbg(),'events':r.panel('card','inputLog')})
   raise
except Exception:out['error']=traceback.format_exc();print(out['error'])
finally:
 (OUT/'confirmation-results.json').write_text(json.dumps(out,indent=2));r.close()
print(json.dumps(out,indent=2))
assert 'error' not in out, out.get('error')
assert out['keyboard_result']['clicks']==0 and out['keyboard_result']['pending']
assert out['mouse_result']['clicks']==1 and not out['mouse_result']['pending']
assert len(out['rapid_clicks'])==12 and all(x['ok'] for x in out['rapid_clicks'])
print('PASS confirmation: synthetic and keyboard rejected; mouse plus 12 rapid clicks execute once')
