"""Real browser/bridge/service, scripted answers, authorized sounddevice stub, no paid/model calls."""
import os,json,time,traceback
from pathlib import Path
OUT=Path(os.environ.get('GAZE_REVIEW_OUT', str(Path(__file__).parent)))
os.environ.update(REVIEW_START_URL=Path(__file__).with_name('hostile.html').as_uri(),SHOTS=str(OUT),HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig,until,patch,voice,service
r=Rig(scale=1);out={};captured=[]
def intercept(intent,reply):
    if intent.get('type') in ['record_stop','submit','followup']:
        captured.append({k:v for k,v in intent.items() if k!='nonce'})
    service.handle_intent(intent,reply)
def typed(text):
    r.press('AltRight','Alt');until(lambda:r.panel('card','document.activeElement?.id')=='hg-input')
    time.sleep(.3)
    for c in text:r.cmd('Input.dispatchKeyEvent',{'type':'char','text':c})
    r.press('Enter','Enter');time.sleep(.7)
try:
    r.tab=next(t for t in r.session.cdp._tabs.values() if t.is_connected);r.front(r.tab);time.sleep(.3)
    r.session.cdp.set_intent_handler(intercept)
    with patch.object(voice,'transcribe_audio_buffer',return_value=('Explain the topic',[])):
        r.aim('#first');typed('Explain the first topic')
        until(lambda:r.dbg()['view']=='answer');out['initial_answer']=r.dbg()
        first_id=r.turns.items[0]['item_id'];out['initial_top']=r.turns.runs[0]['snapshot'].get('top')
        r.move(280,130);r.space_down();time.sleep(.6)
        out['nearby_hold']=r.dbg()['hold'];r.space_up();time.sleep(.8)
        out['nearby_item_count']=len(r.turns.items)
        r.move(280,70)
        r.page('scrollTo(0,80)');time.sleep(.3)
        out['scrolled_pointer_hit']=r.page('document.elementFromPoint(280,70)?.textContent')
        out['pointer_before_scroll_hold']=r.iso('({x:window.__HERMES_GAZE_OVERLAY__.state.pointerX,y:window.__HERMES_GAZE_OVERLAY__.state.pointerY})')
        r.space_down();time.sleep(.6);out['scrolled_hold']=r.dbg();r.space_up();time.sleep(.8)
        out['scrolled_request']={k:v for k,v in captured[-1].items() if k!='cursor_context'}
        out['scrolled_run_top']=r.turns.runs[-1]['snapshot'].get('top')
        out['scrolled_item_count']=len(r.turns.items)
        r.page('scrollTo(0,0)');time.sleep(.2);r.press('AltRight','Alt')
        until(lambda:r.dbg()['view']=='compose')
        out['typed_after_scroll']=r.panel('card','document.querySelector(".title")?.textContent')
        r.press('Escape','Escape')
        # Clear view. Dense ordinary links let the user cross >64 identities during a single hold.
        r.press('Escape','Escape');time.sleep(.3)
        r.page("scrollTo(0,0);document.body.innerHTML='<div id=grid style=\"display:grid;grid-template-columns:repeat(10,120px);gap:8px\">'+Array.from({length:80},(_,i)=>'<a id=n'+i+' href=\"https://example.test/'+i+'\" style=\"display:block;height:45px;background:#eef\">Topic '+i+'</a>').join('')+'</div>'")
        r.aim('#n0');r.space_down();time.sleep(.3)
        for i in range(1,5):r.aim('#n'+str(i));time.sleep(.2)
        out['five_lit']=r.dbg()
        for i in range(5,80):
            q=r.rect('#n'+str(i));r.move(q['cx'],q['cy'],steps=1)
        out['after_many_hits']=r.dbg()
        r.space_up();time.sleep(1)
        cap=captured[-1]['cursor_context'];out['lit_capture']={'lit':cap.get('lit'),'captured_target_ids':[t['id'] for t in cap['targets']],'history_count':len(cap['history']),'lit_labels':[t.get('label') for t in cap['targets'] if t['id'] in cap.get('lit',[])]}
        out['many_hits_result']={'pointed':r.turns.runs[-1]['snapshot'].get('pointed'),'ranked_labels':[t.get('label') for t in r.turns.runs[-1]['snapshot'].get('ranked',[])],'context_length':len(r.turns.runs[-1]['snapshot'].get('context',''))}
        # Forge pointer motion from page script while real mouse remains on n0.
        r.press('Escape','Escape');time.sleep(.3);r.aim('#n0');r.space_down();time.sleep(.3)
        r.page("(()=>{const r=document.getElementById('n79').getBoundingClientRect();window.dispatchEvent(new MouseEvent('mousemove',{clientX:r.x+r.width/2,clientY:r.y+r.height/2,bubbles:true}))})()")
        time.sleep(.3);out['synthetic_pointer_hold']=r.dbg();r.space_up();time.sleep(.8)
        out['synthetic_pointer_result']={'ranked_labels':[t.get('label') for t in r.turns.runs[-1]['snapshot'].get('ranked',[])],'physical_mouse':[r.mx,r.my]}
    # Browser engine check: unfinished hostile markdown can recurse beyond intended depth limit.
    out['markdown_browser']=r.panel('card',"(()=>{const out=[];for(const n of [1000,6000,11999]){const t=performance.now();try{window.__HG_MD__.view('['.repeat(n)+' ',{streaming:true});out.push({n,ok:true,ms:performance.now()-t})}catch(e){out.push({n,error:e.name,message:e.message,ms:performance.now()-t})}}return out})()")
    # Observe the actual renderer, not only the parser.
    out['markdown_render']=r.panel('card',"(()=>{try{window.__HERMES_GAZE_PANEL__.render({kind:'card',view:'answer',item:{id:'adversarial',subject:'Model response',turns:[{id:'turn',q:'Question',a:'['.repeat(11999)+' ',status:'streaming'}]}});return {ok:true}}catch(e){return {error:e.name,message:e.message,visible:document.body.innerText}}})()")
    out['pathological_markdown']=r.panel('card', """(()=>{
      const cases={nesting:'> '.repeat(6000)+'word ', fences:'`'.repeat(12000)+'\\nbody\\n',
        table:'|x'.repeat(3000)+'|\\n'+'|-'.repeat(3000)+'|\\n'+('|x|\\n'.repeat(3000)),
        closedBrackets:'['.repeat(6000)+']'.repeat(6000)};
      return Object.entries(cases).map(([name,text])=>{const start=performance.now();
        window.__HERMES_GAZE_PANEL__.render({kind:'card',view:'answer',item:{id:name,subject:name,
          turns:[{id:name,q:'Question',a:text,status:'streaming'}]}});
        return {name,ms:performance.now()-start,controls:!!document.querySelector('[data-act="dismiss"]')};
      });
    })()""")
except Exception:out['error']=traceback.format_exc();print(out['error'])
finally:
    (OUT/'evidence-results.json').write_text(json.dumps(out,indent=2));r.close()
print(json.dumps(out,indent=2))
assert 'error' not in out, out.get('error')
assert out['scrolled_request']['item_id'] == '' and out['scrolled_item_count'] == 2
assert out['scrolled_run_top']['label'] == 'Another source topic Beta'
assert out['nearby_hold']['follow'] == 'Ordinary source topic Alpha' and out['nearby_item_count'] == 1
assert out['typed_after_scroll'] == 'Ordinary source topic Alpha'
assert len(out['lit_capture']['lit']) == 5
assert set(out['lit_capture']['lit']) <= set(out['lit_capture']['captured_target_ids'])
assert len(out['lit_capture']['captured_target_ids']) <= 64
assert all('Topic '+str(i) in out['many_hits_result']['ranked_labels'] for i in range(5))
assert out['many_hits_result']['context_length'] <= 6000
assert out['synthetic_pointer_result']['ranked_labels'] == ['Topic 0']
assert all(x.get('ok') for x in out['markdown_browser']) and out['markdown_render'].get('ok')
assert all(x['controls'] and x['ms'] < 2000 for x in out['pathological_markdown'])
print('PASS F2/F3/F4/F6')
