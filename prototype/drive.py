#!/usr/bin/env python3
"""Drives a running prototype with real CDP input, for proof screenshots and recordings.

Not needed to play with the prototype. All input goes through Input.dispatch*, so the page
sees trusted events. A visible cursor is drawn for recordings only: screencast omits the OS one.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdp import Browser  # noqa: E402

WORLD = "hermes_gaze_prototype"
CURSOR_JS = r"""(()=>{ if (window.__fakeCursor) return; const h=document.createElement('div');
 h.setAttribute('popover','manual'); h.style.cssText='all:initial;position:fixed;inset:0;pointer-events:none;background:transparent;border:0;margin:0;padding:0;width:100vw;height:100vh;overflow:visible;z-index:2147483647';
 document.documentElement.append(h); const s=h.attachShadow({mode:'closed'}); const c=document.createElement('div');
 c.style.cssText='position:fixed;left:0;top:0;width:22px;height:22px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))';
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 22 22');svg.setAttribute('width','22');svg.setAttribute('height','22');
 const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d','M4 2 L4 17 L8 13.4 L10.7 19.6 L13.3 18.5 L10.7 12.5 L16 12.2 Z');p.setAttribute('fill','#000');p.setAttribute('stroke','#fff');p.setAttribute('stroke-width','1.3');p.setAttribute('stroke-linejoin','round');svg.append(p);c.append(svg);s.append(c);
 const kbd=document.createElement('div');kbd.style.cssText='position:fixed;left:50%;bottom:22px;transform:translateX(-50%);padding:5px 13px;border-radius:8px;background:rgba(20,20,22,.82);color:#fff;font:500 13px -apple-system,system-ui;opacity:0;transition:opacity .1s;white-space:nowrap';s.append(kbd);
 window.__fakeCursor={move(x,y){c.style.transform=`translate(${x-3}px,${y-2}px)`;},key(t){kbd.textContent=t||'';kbd.style.opacity=t?1:0;}};
 h.showPopover();
 setInterval(()=>{try{h.hidePopover();h.showPopover()}catch(e){}},700);
})()"""


class Page:
    def __init__(self, br: Browser, url: str, width=1440, height=900, scale=2, dark_scheme=False):
        self.br = br
        self.width, self.height = width, height
        self.target = br.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        time.sleep(.5)
        self.s = br.send("Target.attachToTarget", {"targetId": self.target, "flatten": True})["sessionId"]
        self.contexts: dict[int, dict] = {}
        br.on(self._on)
        for m in ("Page.enable", "Runtime.enable"):
            br.send(m, session=self.s)
        br.send("Target.activateTarget", {"targetId": self.target})
        br.send("Emulation.setFocusEmulationEnabled", {"enabled": True}, self.s)
        br.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": scale, "mobile": False}, self.s)
        if dark_scheme:
            br.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]}, self.s)
        self.x, self.y = width / 2, height / 2
        self.frames = []
        self.goto(url)

    def _on(self, method, params, sid):
        if sid != self.s:
            return
        if method == "Runtime.executionContextCreated":
            c = params["context"]
            self.contexts[c["id"]] = c
        elif method == "Runtime.executionContextDestroyed":
            self.contexts.pop(params.get("executionContextId"), None)
        elif method == "Runtime.executionContextsCleared":
            self.contexts.clear()
        elif method == "Page.screencastFrame":
            self.frames.append((params["metadata"]["timestamp"], params["data"]))
            self.br.send_async("Page.screencastFrameAck", {"sessionId": params["sessionId"]}, self.s)

    def goto(self, url, settle=2.0):
        self.br.send("Page.navigate", {"url": url}, self.s, timeout=40)
        for _ in range(100):
            time.sleep(.2)
            if self.js("document.readyState") == "complete":
                break
        time.sleep(settle)
        self.wait(lambda: self.world_ctx() is not None, 10)

    def wait(self, fn, t=10.0):
        end = time.time() + t
        while time.time() < end:
            try:
                if fn():
                    return True
            except Exception:
                pass
            time.sleep(.1)
        return False

    def world_ctx(self):
        # The main-frame world is the one holding __HG_PROTO__.
        for cid, c in list(self.contexts.items()):
            if c.get("name") == WORLD and c.get("auxData", {}).get("isDefault") is False:
                try:
                    r = self.br.send("Runtime.evaluate", {"expression": "!!window.__HG_PROTO__", "contextId": cid, "returnByValue": True}, self.s, timeout=3)
                    if r["result"].get("value"):
                        return cid
                except Exception:
                    continue
        return None

    def js(self, expr, ctx=None):
        params = {"expression": expr, "returnByValue": True, "awaitPromise": True}
        if ctx:
            params["contextId"] = ctx
        r = self.br.send("Runtime.evaluate", params, self.s, timeout=20)
        if r.get("exceptionDetails"):
            print("[js error]", json.dumps(r["exceptionDetails"])[:500], flush=True)
        return r.get("result", {}).get("value")

    def state(self):
        return self.js("window.__HG_PROTO__.debug()", self.world_ctx())

    def opt(self, k, v):
        self.js(f"window.__HG_PROTO__.set({json.dumps(k)},{json.dumps(v)})", self.world_ctx())

    def cursor_on(self):
        self.js(CURSOR_JS)
        self.fake = True
        self.js(f"window.__fakeCursor.move({self.x},{self.y})")

    def label(self, text):
        if getattr(self, "fake", False):
            self.js(f"window.__fakeCursor.key({json.dumps(text)})")

    def move(self, x, y, steps=14, dur=.32):
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)
            px, py = x0 + (x - x0) * e, y0 + (y - y0) * e
            self.br.send_async("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": px, "y": py}, self.s)  # acks stall behind a screenshot
            if getattr(self, "fake", False):
                self.br.send_async("Runtime.evaluate", {"expression": f"window.__fakeCursor.move({px},{py})"}, self.s)
            time.sleep(dur / steps)
        self.x, self.y = x, y

    def key(self, kind, code, key=None, vk=None, text=None):
        params = {"type": kind, "code": code, "key": key or code, "windowsVirtualKeyCode": vk or 0}
        if text and kind == "keyDown":
            params["text"] = text
        self.br.send("Input.dispatchKeyEvent", params, self.s)

    def space_down(self):
        self.key("keyDown", "Space", " ", 32, " ")

    def space_up(self):
        self.key("keyUp", "Space", " ", 32)

    def press(self, code, key, vk, text=None):
        self.key("keyDown", code, key, vk, text)
        time.sleep(.05)
        self.key("keyUp", code, key, vk)

    def arrow(self, down=True):
        self.press("ArrowDown" if down else "ArrowUp", "ArrowDown" if down else "ArrowUp", 40 if down else 38)

    def click(self, x, y):
        self.move(x, y, steps=8, dur=.18)
        for kind in ("mousePressed", "mouseReleased"):
            self.br.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1}, self.s)
            time.sleep(.04)

    def wheel(self, dy):
        self.br.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": self.x, "y": self.y, "deltaX": 0, "deltaY": dy}, self.s)

    def shot(self, path):
        data = self.br.send("Page.captureScreenshot", {"format": "png"}, self.s, timeout=30)["data"]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(base64.b64decode(data))
        return path

    def ask(self, x, y, hold=.9, label=None):
        self.move(x, y)
        time.sleep(.15)
        if label:
            self.label(label)
        self.space_down()
        time.sleep(hold)
        self.space_up()
        if label:
            self.label("")

    def find(self, selector, nth=0):
        """Viewport centre of a real element."""
        return self.js(f"""(()=>{{const e=[...document.querySelectorAll({json.dumps(selector)})].filter(n=>{{const r=n.getBoundingClientRect();return r.width>4&&r.height>4&&r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth}})[{nth}];if(!e)return null;const r=e.getBoundingClientRect();return {{x:r.left+Math.min(r.width/2,180),y:r.top+r.height/2,w:r.width,h:r.height,text:(e.innerText||'').slice(0,60)}}}})()""")

    def record_start(self, every=1):
        self.frames = []
        self.br.send("Page.startScreencast", {"format": "jpeg", "quality": 82, "maxWidth": self.width, "maxHeight": self.height, "everyNthFrame": every}, self.s)

    def record_stop(self, out_mp4, out_gif=None, fps=30, gif_width=960):
        self.br.send("Page.stopScreencast", session=self.s)
        frames = sorted(self.frames)
        tmp = Path(tempfile.mkdtemp(prefix="hg-proto-rec-"))
        lines = []
        for i, (t, data) in enumerate(frames):
            p = tmp / f"f{i:05d}.jpg"
            p.write_bytes(base64.b64decode(data))
            dur = max(.001, (frames[i + 1][0] - t) if i + 1 < len(frames) else .5)
            lines += [f"file '{p}'", f"duration {dur:.4f}"]
        lines.append(f"file '{tmp / f'f{len(frames) - 1:05d}.jpg'}'")
        (tmp / "list.txt").write_text("\n".join(lines))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                        "-vf", f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(out_mp4)], check=True)
        if out_gif:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out_mp4), "-vf",
                            f"fps=15,scale={gif_width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=200:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                            str(out_gif)], check=True)
        return len(frames)

    def close(self):
        self.br.send("Target.closeTarget", {"targetId": self.target})
