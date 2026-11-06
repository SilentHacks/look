#!/usr/bin/env python3
"""Feasibility probe: can real page blur exist under the production privacy structure?

Structure under test mirrors overlay.js/cdp_bridge.py: an isolated-world popover host in the
top layer, a closed shadow root, and a script-disabled sandbox iframe driven by a CDP world.
Measures pixel contrast under each surface; hard stripes survive unless they are really blurred.
"""
import base64, http.server, json, shutil, socketserver, struct, subprocess, sys, tempfile, threading, time, zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cdp import Browser

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HEADED = "--headed" in sys.argv
OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path(tempfile.mkdtemp())
OUT.mkdir(parents=True, exist_ok=True)
STRIPES = "repeating-linear-gradient(90deg,#000 0 6px,#fff 6px 12px)"

def page(extra_css="", extra_head="", body_extra=""):
    return f"""<!doctype html><html><head><title>probe</title>{extra_head}<style>
    html,body{{margin:0;height:100%}} body{{background:{STRIPES}}} {extra_css}</style></head><body>{body_extra}</body></html>"""

PAGES = {
    "plain": page(),
    "html-filter": page("html{filter:saturate(1.01)}"),
    "html-opacity": page("html{opacity:.99}"),
    "body-filter": page("body{filter:saturate(1.01)}"),
    "body-opacity": page("body{opacity:.99}"),
    "body-willchange": page("body{will-change:transform}"),
    "html-mask": page("html{mask-image:linear-gradient(#000,#000)}"),
    "html-blend": page("body{mix-blend-mode:multiply}"),
    "dark-meta": page("html{color-scheme:dark}", '<meta name="color-scheme" content="dark">'),
    "iframe-under": page("", "", '<iframe style="position:fixed;inset:0;width:100%;height:100%;border:0" src="/stripes"></iframe>'),
    "video-under": page("", "", '<canvas id=c width=800 height=800 style="position:fixed;inset:0;width:100%;height:100%"></canvas><script>const x=c.getContext("2d");for(let i=0;i<800;i+=12){x.fillStyle="#000";x.fillRect(i,0,6,800);x.fillStyle="#fff";x.fillRect(i+6,0,6,800)}</script>'),
}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = page().encode() if self.path == "/stripes" else PAGES.get(self.path.strip("/"), "").encode()
        self.send_response(200); self.send_header("content-type", "text/html"); self.end_headers(); self.wfile.write(body)
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H); srv.daemon_threads = True
port = srv.server_address[1]; threading.Thread(target=srv.serve_forever, daemon=True).start()

INJECT = r"""(() => {
  const host = document.createElement('div');
  host.id = 'probe-host';
  host.setAttribute('popover','manual');
  host.style.cssText = 'all:initial!important;position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;margin:0!important;padding:0!important;border:0!important;pointer-events:none!important;background:transparent!important';
  document.documentElement.appendChild(host); host.showPopover();
  const s = host.attachShadow({mode:'closed'});
  const css = 'position:fixed;width:200px;height:200px;top:40px;';
  const blur = 'backdrop-filter:blur(30px) saturate(1.8);';
  // A: plate in the closed shadow root, sandbox frame stacked above it (transparent).
  const a = document.createElement('div'); a.style.cssText = css+'left:40px;background:rgba(255,255,255,.1);'+blur; s.append(a);
  const fa = document.createElement('iframe'); fa.setAttribute('sandbox',''); fa.style.cssText = css+'left:40px;border:0;background:transparent;color-scheme:normal'; s.append(fa);
  // B: backdrop-filter directly on the sandbox iframe element.
  const b = document.createElement('iframe'); b.setAttribute('sandbox',''); b.style.cssText = css+'left:280px;border:0;background:rgba(255,255,255,.1);color-scheme:normal;'+blur; s.append(b);
  // C: backdrop-filter INSIDE the sandbox document (set up by CDP below).
  const c = document.createElement('iframe'); c.setAttribute('sandbox',''); c.style.cssText = css+'left:520px;border:0;background:transparent;color-scheme:normal'; s.append(c);
  // D: control, bare sandbox frame: is the frame even transparent?
  const d = document.createElement('iframe'); d.setAttribute('sandbox',''); d.style.cssText = css+'left:760px;border:0;background:transparent;color-scheme:normal'; s.append(d);
  // E: plate, then a real opaque-origin frame above, wrapped in a rounded clipped unit (the real card).
  const e = document.createElement('div'); e.style.cssText = css+'left:40px;top:300px;border-radius:22px;overflow:hidden;background:rgba(255,255,255,.1);'+blur; s.append(e);
  window.__probe = {a,fa,b,c,d,e};
  return true;
})()"""

FRAME_TEST = r"""(async () => {
  const out = {sandboxOrigin: self.origin, canReadParent: false};
  try { out.canReadParent = !!parent.document; } catch(e) {}
  out.raf = await Promise.race([new Promise(r=>requestAnimationFrame(()=>r(true))), new Promise(r=>{const t=Date.now();const i=()=>Date.now()-t>800?r(false):0;}), ]).catch(()=>false);
  return out;
})()"""

def png_rgba(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    i, idat, w, h, ct = 8, b"", 0, 0, 0
    while i < len(data):
        n = struct.unpack(">I", data[i:i+4])[0]; t = data[i+4:i+8]; d = data[i+8:i+8+n]; i += 12 + n
        if t == b"IHDR": w, h, _, ct = struct.unpack(">IIBB", d[:10])
        elif t == b"IDAT": idat += d
    bpp = {2: 3, 6: 4}[ct]; raw = zlib.decompress(idat); stride = w * bpp; rows = []; prev = bytearray(stride); p = 0
    for _ in range(h):
        f = raw[p]; line = bytearray(raw[p+1:p+1+stride]); p += 1 + stride
        for x in range(stride):
            a = line[x-bpp] if x >= bpp else 0; b = prev[x]; c = prev[x-bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b-c), abs(a-c), abs(a+b-2*c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line); prev = line
    return w, h, bpp, rows

def contrast(img, x0, y, x1, dpr):
    w, h, bpp, rows = img
    row = rows[int(y*dpr)]; vals = [row[int(x*dpr)*bpp] for x in range(x0, x1)]
    return max(vals) - min(vals)

prof = tempfile.mkdtemp(prefix="hg-proto-probe-")
cdp_port = 9444
args = [CHROME, f"--user-data-dir={prof}", f"--remote-debugging-port={cdp_port}", "--no-first-run", "--no-default-browser-check", "--window-size=1100,620", "--disable-extensions"]
if not HEADED: args.append("--headless=new")
chrome = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
results = {}
try:
    for _ in range(80):
        try:
            br = Browser(cdp_port); break
        except Exception: time.sleep(.25)
    results["browser"] = br.version; results["headed"] = HEADED
    for name in PAGES:
        tid = br.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        s = br.send("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        ctxs = {}
        def on(m, p, sid, s=s, ctxs=ctxs):
            if sid == s and m == "Runtime.executionContextCreated":
                c = p["context"]; ctxs[c["id"]] = c
        br.on(on)
        for m in ("Page.enable", "Runtime.enable", "DOM.enable"): br.send(m, session=s)
        br.send("Emulation.setDeviceMetricsOverride", {"width": 1100, "height": 620, "deviceScaleFactor": 1, "mobile": False}, session=s)
        br.send("Page.navigate", {"url": f"http://127.0.0.1:{port}/{name}"}, session=s)
        time.sleep(.9)
        frame = br.send("Page.getFrameTree", session=s)["frameTree"]["frame"]["id"]
        wid = br.send("Page.createIsolatedWorld", {"frameId": frame, "worldName": "probe"}, session=s)["executionContextId"]
        br.send("Runtime.evaluate", {"expression": INJECT, "contextId": wid, "returnByValue": True}, session=s)
        def frame_world(var):
            o = br.send("Runtime.evaluate", {"expression": f"window.__probe.{var}", "contextId": wid}, session=s)["result"]["objectId"]
            fid = br.send("DOM.describeNode", {"objectId": o}, session=s)["node"]["frameId"]
            return br.send("Page.createIsolatedWorld", {"frameId": fid, "worldName": "probe-ui"}, session=s)["executionContextId"]
        # C: backdrop-filter inside the sandbox doc.
        cw = frame_world("c")
        br.send("Runtime.evaluate", {"contextId": cw, "expression": "document.documentElement.style.background='transparent';document.body.style.cssText='margin:0;background:transparent';const p=document.createElement('div');p.style.cssText='width:200px;height:200px;background:rgba(255,255,255,.1);backdrop-filter:blur(30px)';document.body.append(p);1"}, session=s)
        # A: real text inside frame above the plate; also capability checks.
        aw = frame_world("fa")
        br.send("Runtime.evaluate", {"contextId": aw, "returnByValue": True, "expression": r"""(()=>{
          document.documentElement.style.background='transparent';document.body.style.cssText='margin:12px;background:transparent;font:600 15px -apple-system;color:#fff';
          document.body.textContent='Private text';
          const o=window.__caps={origin:self.origin,setTimeout:false,raf:false,waapi:false,cssAnimEvent:false,transitionEvent:false,promise:false,clickListener:false};
          try{o.parentDocReadable=!!parent.document}catch(e){o.parentDocReadable=false}
          setTimeout(()=>{o.setTimeout=true},20);
          requestAnimationFrame(()=>{o.raf=true});
          Promise.resolve().then(()=>{o.promise=true});
          const el=document.createElement('div');el.style.cssText='width:4px;height:4px;transition:opacity 50ms';document.body.append(el);
          const an=el.animate([{opacity:0},{opacity:1}],{duration:60});an.onfinish=()=>{o.waapi=true};
          window.__an=an;
          const st=document.createElement('style');st.textContent='@keyframes x{from{opacity:0}to{opacity:1}} .k{animation:x 50ms}';document.head.append(st);
          const e2=document.createElement('div');e2.className='k';e2.style.cssText='width:4px;height:4px';e2.addEventListener('animationend',()=>{o.cssAnimEvent=true});document.body.append(e2);
          window.__e2=e2;
          return true})()"""}, session=s)
        time.sleep(.8)
        caps = br.send("Runtime.evaluate", {"contextId": aw, "returnByValue": True, "expression": "({...window.__caps, waapiPlayState:window.__an.playState, waapiTime:window.__an.currentTime, cssAnimations:window.__e2.getAnimations().length})"}, session=s).get("result", {}).get("value")
        # E: mount a sandbox frame INSIDE the clipped unit.
        br.send("Runtime.evaluate", {"contextId": wid, "expression": "const f=document.createElement('iframe');f.setAttribute('sandbox','');f.style.cssText='width:100%;height:100%;border:0;background:transparent;color-scheme:normal';window.__probe.e.append(f);window.__probe.ef=f;1"}, session=s)
        time.sleep(.15)
        ew = frame_world("ef")
        br.send("Runtime.evaluate", {"contextId": ew, "expression": "document.documentElement.style.background='transparent';document.body.style.cssText='margin:12px;background:transparent;font:600 15px -apple-system;color:#fff';document.body.textContent='Inside clip';1"}, session=s)
        # Hostile main-world reads of the plate & text
        leak = br.send("Runtime.evaluate", {"returnByValue": True, "expression": r"""(()=>{
          const h=document.getElementById('probe-host');
          document.execCommand&&getSelection().selectAllChildren(document.documentElement);
          return {shadowRoot: h.shadowRoot===null?'null':'open', hostChildren:h.children.length,
                  selection:getSelection().toString().includes('Private text'),
                  bodyText:document.documentElement.innerText.includes('Private text'),
                  elementAtPlate:document.elementFromPoint(100,100)?.tagName,
                  framesVisible:window.frames.length}})()"""}, session=s)["result"]["value"]
        br.send("Runtime.evaluate", {"expression": "getSelection().removeAllRanges()"}, session=s)
        time.sleep(.5)
        png = base64.b64decode(br.send("Page.captureScreenshot", {"format": "png"}, session=s, timeout=30)["data"])
        (OUT / f"{name}{'-headed' if HEADED else ''}.png").write_bytes(png)
        img = png_rgba(png); dpr = img[0] / 1100
        m = lambda x0: contrast(img, x0, 200, x0 + 120, dpr)
        row = {"A plate behind frame": m(80), "B filter on iframe": m(320), "C inside sandbox doc": m(560), "D bare frame (control)": m(800), "E clipped unit": contrast(img, 80, 460, 200, dpr), "open page (control)": contrast(img, 980, 200, 1090, dpr)}
        results[name] = {"contrast_0_255": row, "frame_caps": caps, "hostile_page_reads": leak}
        br.send("Target.closeTarget", {"targetId": tid})
finally:
    chrome.terminate()
    try: chrome.wait(8)
    except Exception: chrome.kill()
    shutil.rmtree(prof, ignore_errors=True)
print(json.dumps(results, indent=1))
(OUT / f"results{'-headed' if HEADED else ''}.json").write_text(json.dumps(results, indent=1))
