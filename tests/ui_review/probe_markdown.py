"""Hostile model text through real protected renderer, observing local network and DOM."""
import os,json,time,threading,http.server,traceback
from pathlib import Path
OUT=Path(os.environ.get('GAZE_REVIEW_OUT', str(Path(__file__).parent)))
os.environ.update(REVIEW_START_URL=Path(__file__).with_name('hostile.html').as_uri(),SHOTS=str(OUT),HERMES_DISABLE_LAZY_INSTALLS='1')
from devlib import Rig
hits=[]
class Sink(http.server.BaseHTTPRequestHandler):
 def do_GET(self):hits.append(self.path);self.send_response(204);self.end_headers()
 def log_message(self,*args):pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Sink);threading.Thread(target=server.serve_forever,daemon=True).start()
r=Rig(scale=1);out={}
try:
 r.tab=next(t for t in r.session.cdp._tabs.values() if t.is_connected);r.front(r.tab);r.aim('#first')
 dest=f'http://127.0.0.1:{server.server_address[1]}'
 text=f'''PRIVATE-MARKDOWN-CANARY **bold** <script>window.__pwned=1</script> <img src="{dest}/raw-image" onerror="window.__pwned=2"> ![image]({dest}/markdown-image) [unsafe](javascript:alert(1)) [safe]({dest}/clicked-link) <button data-act="confirm" data-value="yes">Confirm</button> <style>body{{display:none}}</style>'''
 r.iso('window.__LOOK_OVERLAY__.showHudMessage('+json.dumps(text)+')');time.sleep(.6)
 out['structure']=r.panel('card',"(()=>{const a=document.querySelector('.a');return {text:a.textContent,tags:[...new Set([...a.querySelectorAll('*')].map(n=>n.tagName))],controls:a.querySelectorAll('img,script,a,button,iframe,style,link,video,audio,object,embed').length,links:[...a.querySelectorAll('.link')].map(n=>n.dataset.url),pwned:window.__pwned||null}})()")
 out['requests_before_click']=list(hits)
 # Synthetic .click() in the private world must not forward a link opening to Python.
 r.panel('card',"document.querySelector('.link').click();true");time.sleep(.3)
 out['requests_after_synthetic_link_click']=list(hits)
 out['page_canary_leak']='PRIVATE-MARKDOWN-CANARY' in r.page('JSON.stringify(harvest())')
 out['page_animations']=r.page("({document:document.getAnimations().length,host:document.getElementById('look-root').getAnimations({subtree:true}).length})")
except Exception:out['error']=traceback.format_exc();print(out['error'])
finally:
 (OUT/'markdown-results.json').write_text(json.dumps(out,indent=2));r.close();server.shutdown();server.server_close()
print(json.dumps(out,indent=2))
