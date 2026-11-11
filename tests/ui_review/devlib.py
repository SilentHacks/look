"""Dev harness: private headless Chrome, real overlay/bridge/inbox, scripted host."""
import base64, json, subprocess, sys, tempfile, threading, time, urllib.request, shutil, os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import tests
from look.runtime import service
from look.audio import voice
from look.config import GazeConfig
from look.runtime.voice_turns import VoiceTurns
from tests.owned_chrome import private_session
CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
SHOTS=Path(os.environ.get('SHOTS', str(Path(__file__).parent/'shots')))
SHOTS.mkdir(exist_ok=True, parents=True)

def until(fn, seconds=10, what='condition'):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        v=fn()
        if v: return v
        time.sleep(.03)
    raise AssertionError('timed out: '+what)

class FakeInput:
    def __init__(self, **kw):
        self.cb=kw['callback']; self.go=True; self.t=None
    def start(self):
        self.cb(b'\x01\x00'*160,160,SimpleNamespace(currentTime=1.,inputBufferAdcTime=1.),None)
        import math, random, array
        def run():
            n=0
            while self.go:
                time.sleep(.03); n+=1
                amp=int(4000*abs(math.sin(n*.35))*(random.random()*.6+.4))
                self.cb(array.array('h',[amp if i%2 else -amp for i in range(480)]).tobytes(),480,SimpleNamespace(currentTime=1.,inputBufferAdcTime=1.),None)
        self.t=threading.Thread(target=run,daemon=True); self.t.start()
    def stop(self): self.go=False
    def abort(self): self.go=False
    def close(self): self.go=False

class Host:
    """Stands in for Hermes: receives injected wires and plays scripted answers serially."""
    def __init__(self):
        self.queue=[]; self.turns=None; self.n=0; self.answers=[]; self.hold=threading.Event(); self.hold.set(); self.wires=[]
    def inject_message(self, wire, **kw):
        self.wires.append(wire)
        threading.Thread(target=self.play,args=(wire,),daemon=True).start()
        return True
    def play(self, wire):
        self.n+=1; turn=f't{self.n}'
        script=self.answers.pop(0) if self.answers else {'text':'Hello **there**.'}
        t=self.turns
        t.pre(session_id='s',user_message=wire,turn_id=turn)
        self.hold.wait()
        time.sleep(script.get('think',.6))
        if script.get('fail'):
            t.end(session_id='s',turn_id=turn,failed=True,turn_exit_reason=script['fail']); return
        text=script['text']; step=script.get('step',.03); i=0
        import re
        for m in re.finditer(r'\S+\s*',text):
            t.delta(session_id='s',turn_id=turn,delta=m.group(0)); time.sleep(step)
        t.post(session_id='s',turn_id=turn,assistant_response=text)
        t.end(session_id='s',turn_id=turn)

class Rig:
    def __init__(self, width=1440,height=900,headless=True,scale=2):
        self.tmp=tempfile.mkdtemp(prefix='hermes-ui-dev-')
        args=[f'--window-size={width},{height}']
        if headless: args += ['--headless=new','--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36']
        try:
            self.session=private_session(self.tmp, chrome_args=args, url=os.environ.get('REVIEW_START_URL','about:blank'))
        except BaseException:
            shutil.rmtree(self.tmp,ignore_errors=True)
            raise
        self.chrome=self.session.cdp.chrome.process
        time.sleep(.7)  # Let hostile fixture install page-world hooks BEFORE plugin attachment.
        assert self.session.cdp.connect()
        self.host=Host()
        self.ctx=SimpleNamespace(inject_message=self.host.inject_message)
        self.turns=VoiceTurns(self.ctx,self.session)
        self.host.turns=self.turns
        self.turns.bind(session_key='k',session_id='s')
        self.session.cdp.set_intent_handler(service.handle_intent)
        self.width,self.height,self.scale=width,height,scale
        from benchmark.probe_companion_ui import STUB
        import types
        pcm=Path(self.tmp)/'speech.pcm'; pcm.write_bytes(b'\x01\x00'*16000)
        os.environ['GAZE_FAKE_SPEECH']=str(pcm)
        stub=types.ModuleType('sounddevice'); exec(STUB,stub.__dict__)
        self.patches=[patch.object(service,'get_shared_session',return_value=self.session),patch.object(service,'_VOICE_TURNS',self.turns),
            patch.object(service,'_CONFIG',GazeConfig(early_highlight=False)),patch.dict(sys.modules,sounddevice=SimpleNamespace(RawInputStream=stub.RawInputStream)),
            patch.object(voice, 'recognition_ready', return_value=True),  # Scripted ASR, never prepare real models.
            patch('look.audio.speech.SpeechPlayback.say',side_effect=AssertionError('Real say forbidden'))]
        for p in self.patches: p.start()
        self.session.configure(hotkey='AltRight')
        self.tab=None
    def new_tab(self,url='about:blank'):
        req=urllib.request.Request(self.session.cdp_http_url+'/json/new?about:blank',method='PUT')
        with urllib.request.urlopen(req) as r: target=json.load(r)['id']
        tab=until(lambda:(t if (t:=self.session.cdp._tabs.get(target)) and t.is_connected else None),15,'tab')
        self.front(tab)
        if url!='about:blank': self.goto(url,tab)
        self.tab=tab
        return tab
    def front(self,tab):
        for t in tuple(self.session.cdp._tabs.values()):
            if t is not tab and t.is_connected:
                try: self.cmd('Emulation.setFocusEmulationEnabled',{'enabled':False},t)
                except Exception: pass
        self.cmd('Page.bringToFront',{},tab)
        self.cmd('Emulation.setFocusEmulationEnabled',{'enabled':True},tab)
        self.cmd('Emulation.setDeviceMetricsOverride',{'width':self.width,'height':self.height,'deviceScaleFactor':self.scale,'mobile':False},tab)
        self.tab=tab
    def goto(self,url,tab=None,settle=1.2):
        tab=tab or self.tab
        old=tab._context_unique_id
        self.cmd('Page.navigate',{'url':url},tab,timeout=40)
        until(lambda: tab._context_unique_id!=old and tab._ui_frames and self.page('document.readyState',tab)=='complete',40,'navigate')
        self.cmd('Emulation.setFocusEmulationEnabled',{'enabled':True},tab)
        time.sleep(settle)
    def cmd(self,m,p=None,tab=None,timeout=8):
        tab=tab or self.tab
        return tab._submit(tab._send_cmd(m,p or {},timeout=timeout),timeout+2)
    def page(self,expr,tab=None):
        r=self.cmd('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True},tab)
        assert not r.get('exceptionDetails'),r
        return r['result'].get('value')
    def iso(self,expr,tab=None):
        return (tab or self.tab).eval_js(expr)
    def dbg(self): return self.iso('window.__LOOK_OVERLAY__.debug()')
    def panel(self,frame,expr,tab=None):
        tab=tab or self.tab
        return tab._submit(tab._eval_coro(expr,5.,context_id=tab._ui_frames[frame][1]),7)
    def text(self,frame='card'): return self.panel(frame,'document.getElementById("root").innerText')
    def move(self,x,y,steps=8):
        x0,y0=getattr(self,'mx',x),getattr(self,'my',y)
        for i in range(1,steps+1):
            self.cmd('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x0+(x-x0)*i/steps,'y':y0+(y-y0)*i/steps})
            time.sleep(.012)
        self.mx,self.my=x,y
    def rect(self,sel,tab=None):
        return self.page(f'(()=>{{const e=document.querySelector({json.dumps(sel)});if(!e)return null;const r=e.getBoundingClientRect();return {{x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2}}}})()',tab)
    def aim(self,sel):
        r=self.rect(sel); assert r,sel
        self.move(r['cx'],r['cy']); time.sleep(.05); return r
    def key(self,kind,code,key=None,text=None,**kw):
        vk={'Space':32,'Escape':27,'Enter':13,'ArrowDown':40,'ArrowUp':38,'KeyQ':81}.get(code,0)
        p={'type':kind,'code':code,'key':key or code,'windowsVirtualKeyCode':vk,**kw}
        if text is not None and kind=='keyDown': p['text']=text
        self.cmd('Input.dispatchKeyEvent',p)
    def press(self,code,key=None,text=None):
        self.key('keyDown',code,key,text); time.sleep(.03); self.key('keyUp',code,key)
    def space_down(self): self.key('keyDown','Space',' ')
    def space_up(self): self.key('keyUp','Space',' ')
    def ask_voice(self,sel,hold=.7):
        if sel: self.aim(sel)
        self.space_down(); time.sleep(hold); self.space_up()
    def click(self,x,y):
        self.move(x,y,3)
        for k in ('mousePressed','mouseReleased'):
            self.cmd('Input.dispatchMouseEvent',{'type':k,'button':'left','clickCount':1,'x':x,'y':y})
    def panel_rect(self,sel):
        r=self.panel('card',f'(()=>{{const e=document.querySelector({json.dumps(sel)});if(!e)return null;const r=e.getBoundingClientRect();return {{x:r.x,y:r.y,w:r.width,h:r.height}}}})()')
        if not r: return None
        f=self.iso('(()=>{const r=window.__LOOK_OVERLAY__.uiFrame.getBoundingClientRect();return {x:r.x,y:r.y}})()')
        return {'cx':r['x']+f['x']+r['w']/2,'cy':r['y']+f['y']+r['h']/2,**r}
    def click_panel(self,sel):
        r=until(lambda:self.panel_rect(sel),5,'panel '+sel)
        self.click(r['cx'],r['cy'])
    def shot(self,name):
        data=self.cmd('Page.captureScreenshot',{'format':'png'},timeout=20)['data']
        p=SHOTS/f'{name}.png'; p.write_bytes(base64.b64decode(data)); print('shot',p,flush=True); return p
    def close(self):
        for p in self.patches:
            try: p.stop()
            except Exception: pass
        try: self.turns.close()
        except Exception: pass
        try:
            live=next((t for t in self.session.cdp._tabs.values() if t.is_connected),None)
            if live: self.cmd('Browser.close',{},live)
        except Exception: pass
        self.session.close()
        try: self.chrome.wait(8)
        except Exception: self.chrome.kill()
        shutil.rmtree(self.tmp,ignore_errors=True)
