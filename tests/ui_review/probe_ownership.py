"""Private browsing lifecycle smoke: live queued answers, tab recall, navigation cancellation, inert secrets."""
import os,json,time,traceback
from pathlib import Path
OUT=Path(os.environ.get('GAZE_REVIEW_OUT', str(Path(__file__).parent)))
os.environ.update(REVIEW_START_URL=Path(__file__).with_name('hostile.html').as_uri(),SHOTS=str(OUT),HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig,until,patch,voice,service
r=Rig(scale=1);out={}
try:
 a=next(t for t in r.session.cdp._tabs.values() if t.is_connected);r.front(a)
 r.aim('#first');snap=service.resolve_now(r.session,utterance='PRIVATE-OWNER-QUESTION',activate=False)
 r.host.answers=[{'text':'PRIVATE-OWNER-ANSWER', 'think':.4}]
 r.turns.submit('PRIVATE-OWNER-QUESTION',snap);until(lambda:r.turns.active is None)
 out['source_owner']={k:snap.get(k) for k in ['browser_target','browser_document','browser_route']}
 b=r.new_tab(Path(__file__).with_name('hostile.html').as_uri());r.press('KeyQ','q');time.sleep(.5)
 out['other_tab_recall']={'private_frame':r.text(),'view':r.dbg(),'page_leak':'PRIVATE-OWNER' in r.page('JSON.stringify(harvest())')}
 out['saved_snapshot_owner_unchanged']={k:r.turns.items[0]['snapshot'].get(k) for k in ['browser_target','browser_document','browser_route']}
 r.front(a);r.press('Escape','Escape');time.sleep(.3);r.aim('#first')
 # A route change must not stop native recording; full document replacement must.
 r.space_down();until(lambda:r.session.microphone._stream is not None)
 r.page("history.replaceState({},'', '#route-change')");time.sleep(.3)
 out['recording_after_route']=r.session.microphone._stream is not None
 old=a._context_unique_id
 r.goto(Path(__file__).with_name('hostile.html').as_uri()+'?new-document',a,settle=.3)
 until(lambda:r.session.microphone._stream is None)
 out['navigation_cancel']={'document_changed':a._context_unique_id!=old,'discarded':not r.session.microphone._audio,'items':len(r.turns.items)}
 r.space_up();time.sleep(.2)
 # Actual renderer attachment recovers after document replacement.
 out['rearmed_after_navigation']=r.dbg()['talk']
 # Non-visible/sensitive targets must not enter serialized evidence.
 r.page("document.body.innerHTML='<p id=visible>Visible topic</p><input id=password type=password value=PASSWORD_VALUE_CANARY><label for=password>SENSITIVE_LABEL_CANARY</label><p id=hidden style=opacity:0>INVISIBLE_CANARY</p>'")
 r.aim('#password');c=r.session.cdp.capture();p=service.cursor_result(c,'What is this?')
 out['sensitive_wire']={'available':c['targets'][0].get('available'),'sensitive':c['targets'][0].get('sensitive'),'value_or_label_leak':any(x in json.dumps(c)+p['context'] for x in ['PASSWORD_VALUE_CANARY','SENSITIVE_LABEL_CANARY'])}
 r.aim('#hidden');c=r.session.cdp.capture();out['hidden_target']=[{'id':t['id'],'available':t.get('available'),'label':t.get('label'),'reason':t.get('reason')} for t in c['targets'] if t.get('selector')=='#hidden']
 # An ordinary real public article listing, no media/recording/model calls.
 r.goto('https://news.ycombinator.com/',a,settle=.5)
 out['real_news']={'title':r.page('document.title'),'overlay_ready':r.dbg()['talk']['ready'],'headlines':r.page('document.querySelectorAll(".titleline").length')}
 if out['real_news']['headlines']:
  r.aim('.titleline a');c=r.session.cdp.capture();p=service.cursor_result(c,'Explain the link')
  out['real_news'].update(capture_ok=p['ok'],packet_chars=len(p['context']),owner_matches=c['browser_document']==a._context_unique_id)
 # Reads during navigation must not tear down a healthy socket and race the load rearm.
 out['rapid_navigation']=[]
 r.front(a)
 for n in range(40):
  socket=a._ws;start=time.monotonic()
  r.goto('about:blank?navigation='+str(n),a,settle=.01)
  out['rapid_navigation'].append({'seconds':round(time.monotonic()-start,3),
      'same_socket':a._ws is socket,'ready':r.dbg()['talk']['ready']})
except Exception:out['error']=traceback.format_exc();print(out['error'])
finally:
 (OUT/'ownership-results.json').write_text(json.dumps(out,indent=2));r.close()
print(json.dumps(out,indent=2))
assert 'error' not in out, out.get('error')
assert out['recording_after_route'] and out['navigation_cancel']['discarded']
assert out['saved_snapshot_owner_unchanged']==out['source_owner']
assert not out['other_tab_recall']['page_leak'] and not out['sensitive_wire']['value_or_label_leak']
assert len(out['rapid_navigation'])==40
assert all(x['same_socket'] and x['ready'] and x['seconds']<10 for x in out['rapid_navigation'])
print('PASS ownership and 40 document rearms without socket replacement')
