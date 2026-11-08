"""Headless local capture-cost regression; no real devices or sites.
Run with the Hermes venv. CAPTURE_BASELINE=<git-ref> measures the old collector.
"""
import json
import os
import subprocess
from devlib import ROOT, Rig

baseline = os.environ.get('CAPTURE_BASELINE')
if baseline:
    from hermes_gaze.browser import cdp_bridge
    source = subprocess.check_output(['git', 'show', f'{baseline}:browser/overlay.js'], cwd=ROOT, text=True)
    cdp_bridge._overlay_source = lambda: source

r = Rig(headless=True, scale=1)
results = {}
try:
    r.new_tab()
    r.page('''(() => {
      document.body.innerHTML = `<style>
        body {margin:0} #catalog {display:grid;grid-template-columns:repeat(8,150px)}
        article {height:100px;overflow:hidden} img {width:20px;height:20px}
        #pointed {position:fixed;left:450px;top:200px;width:110px;height:50px;background:white}
      </style><main id="catalog"></main>`;
      const catalog = document.getElementById('catalog');
      for(let i=0;i<600;i++) {
        const card=document.createElement('article');
        card.innerHTML=`<h3>Offer ${i}</h3><a href="https://local.invalid/${i}?token=SECRET">Offer link ${i}</a><img alt="local image" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E">`;
        let node=card;
        for(let depth=0;depth<8;depth++) { const wrap=document.createElement('div');wrap.append(node);node=wrap; }
        catalog.append(node);
      }
      const target=document.createElement('button');target.id='pointed';target.textContent='Release target';document.body.append(target);
      const gaze=document.createElement('span');gaze.id='gazed';gaze.textContent='Saved gaze identity';
      gaze.style.cssText='position:fixed;left:30px;top:100px';document.body.append(gaze);
      document.body.insertAdjacentHTML('beforeend', '<div id="private-label" style="position:fixed;top:10px">PRIVATE_LABEL_SECRET</div><input name="otp" aria-labelledby="private-label">');
      return document.querySelectorAll('*').length;
    })()''')
    r.aim('#pointed')
    for mode in ('hover', 'webcam'):
        r.session.configure(mode=mode)
        r.iso('''(() => {const a=window.__HERMES_GAZE_OVERLAY__;
          if(a.state.mode==='webcam') {
            a.acceptWebcamSample({source:'webcam',x_vp:50,y_vp:110,t:Date.now()/1000});
            a.acceptWebcamSample({source:'webcam',x_vp:500,y_vp:220,t:Date.now()/1000});
          }
          else a.recordPoint(500,220);return true})()''')
        results[mode] = r.tab._submit(r.tab._eval_coro('''(() => {
          const a=window.__HERMES_GAZE_OVERLAY__, counts={}, originals=[];
          for(const [obj,key] of [[Element.prototype,'getBoundingClientRect'],[Element.prototype,'checkVisibility'],[Document.prototype,'querySelectorAll']]) {
            const fn=obj[key]; originals.push(()=>obj[key]=fn);
            obj[key]=function(...args){counts[key]=(counts[key]||0)+1;return fn.apply(this,args)};
          }
          document.getElementById('catalog').style.columnGap='1px'; // Force a pending layout at release.
          const before=performance.now(), timing={};let data;
          try {data=a.state.mode==='hover'?a.captureCursorContext(timing):a.captureNoisyContext(380,timing)}
          finally {for(const restore of originals)restore()}
          const frozen=JSON.stringify(data);
          document.getElementById('pointed').textContent='Changed after release';
          const result={ms:performance.now()-before,counts,timing,
            pointed:(data.targets||data.candidates).some(t=>t.label==='Release target'),
            gazed:(data.targets||data.candidates).some(t=>t.label==='Saved gaze identity'),
            private:!frozen.includes('PRIVATE_LABEL_SECRET'),targets:(data.targets||data.candidates).length};
          document.getElementById('pointed').textContent='Release target';
          return result;
        })()''', timeout=90), 92)
        assert results[mode]['pointed'], results
        assert results[mode]['private'], results
        if not os.environ.get('CAPTURE_BASELINE'):
            assert results[mode]['ms'] < 50, results
            if mode == 'webcam':
                assert results[mode]['gazed'], results
finally:
    r.close()
print(json.dumps(results, indent=2))
