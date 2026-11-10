"""The whole companion flow through the real plugin path: real Hermes backend on the configured
model, real overlay and bridge, private Chrome, real pages, trusted CDP input.

Run with a self-contained virtualenv containing Hermes and its dependencies:
  HERMES_DISABLE_LAZY_INSTALLS=1 <venv>/bin/python benchmark/probe_companion_ui.py --out DIR

Isolated: temporary HERMES_HOME and Chrome profile, own debugging port. Hermes's own auth is
copied into that temporary home with 0600 and deleted with it. Optional early-highlight
credentials are resolved by Hermes; this probe never imports a TypeSafe key file.
Audio is a stub sounddevice that plays synthesized speech; the real microphone is not exercised.
Serial by design: the configured free model is quota-limited.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = Path(__file__).resolve().parents[1]
STUB = '''
import os, threading, time
from types import SimpleNamespace
PCM = open(os.environ["GAZE_FAKE_SPEECH"], "rb").read()
class RawInputStream:
    def __init__(self, samplerate=16000, channels=1, dtype="int16", callback=None, **_):
        self.callback, self.run = callback, False
    def _pump(self):
        pos, chunk, start = 0, 1024, time.time()
        while self.run:
            data = PCM[pos:pos + chunk] or b"\\0" * chunk
            data = data + b"\\0" * (chunk - len(data))
            pos += chunk
            open(os.environ["GAZE_FAKE_SPEECH"] + ".log", "a").write(f"{pos} {time.time()-start:.2f}\\n")
            self.callback(data, chunk // 2, SimpleNamespace(currentTime=time.time(), inputBufferAdcTime=time.time()), None)
            time.sleep(chunk / 2 / 16000)
    def start(self):
        self.run = True
        threading.Thread(target=self._pump, daemon=True).start()
    def stop(self): self.run = False
    def abort(self): self.run = False
    def close(self): self.run = False
'''
CURSOR = r"""(()=>{if(window.__rec)return;const c=document.createElement('div');
c.style.cssText='position:fixed;left:0;top:0;width:18px;height:18px;z-index:2147483647;pointer-events:none;filter:drop-shadow(0 1px 2px rgba(0,0,0,.45))';
c.innerHTML='<svg viewBox="0 0 22 22" width="18" height="18"><path d="M4 2 L4 17 L8 13.4 L10.7 19.6 L13.3 18.5 L10.7 12.5 L16 12.2 Z" fill="#000" stroke="#fff" stroke-width="1.3"/></svg>';
document.documentElement.append(c);window.__rec={move(x,y){c.style.transform=`translate(${x-3}px,${y-2}px)`}};})()"""


class Rpc:
    def __init__(self, cmd, env, log):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, env=env, cwd=env["GAZE_CWD"])
        self.frames = queue.Queue()
        self.seq = 0
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            try:
                self.frames.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        self.frames.put({"backend_exit": self.proc.poll()})

    def wait(self, predicate, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                frame = self.frames.get(timeout=max(.01, min(1, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if "backend_exit" in frame:
                raise RuntimeError(f"Hermes backend exited: {frame}")
            if predicate(frame):
                return frame
        raise TimeoutError("Hermes RPC deadline")

    def call(self, method, timeout=180, **params):
        self.seq += 1
        rid = self.seq
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        response = self.wait(lambda f: f.get("id") == rid, timeout)
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        return response["result"]


class Tab:
    def __init__(self, ws_url):
        from websockets.sync.client import connect
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024)
        self.pending, self.lock, self.seq = {}, threading.Lock(), 0
        self.frames = []
        threading.Thread(target=self.read, daemon=True).start()
        for method in ("Page.enable", "Runtime.enable", "DOM.enable"):
            self.send(method)

    def read(self):
        try:
            for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg:
                    slot = self.pending.pop(msg["id"], None)
                    if slot:
                        slot[1].update(msg)
                        slot[0].set()
                elif msg.get("method") == "Page.screencastFrame":
                    params = msg["params"]
                    self.frames.append((params["metadata"]["timestamp"], params["data"]))
                    threading.Thread(target=self.send, args=("Page.screencastFrameAck", {"sessionId": params["sessionId"]}), daemon=True).start()
        except Exception:
            return

    def send(self, method, params=None, timeout=30):
        with self.lock:
            self.seq += 1
            rid = self.seq
            event, out = threading.Event(), {}
            self.pending[rid] = (event, out)
            self.ws.send(json.dumps({"id": rid, "method": method, "params": params or {}}))
        if not event.wait(timeout):
            raise TimeoutError(method)
        if "error" in out:
            raise RuntimeError(f"{method}: {out['error']}")
        return out.get("result", {})

    def main(self, expr):
        result = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")

    def world(self, frame_id=None):
        frame_id = frame_id or self.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        return self.send("Page.createIsolatedWorld", {"frameId": frame_id, "worldName": "hermes-gaze"})["executionContextId"]

    def iso(self, expr, context=None):
        result = self.send("Runtime.evaluate", {"expression": expr, "contextId": context or self.world(), "returnByValue": True, "awaitPromise": True})
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")

    def panel(self, frame, expr):
        remote = self.send("Runtime.evaluate", {"expression": f"window.__HERMES_GAZE_OVERLAY__.uiFrames.{frame}", "contextId": self.world()})
        node = self.send("DOM.describeNode", {"objectId": remote["result"]["objectId"]})
        return self.iso(expr, self.world(node["node"]["frameId"]))

    def debug(self):
        return self.iso("window.__HERMES_GAZE_OVERLAY__.debug()")


class Flow:
    def __init__(self, tab, out):
        self.tab, self.out = tab, out
        self.x, self.y = 700, 400
        self.results = []

    def note(self, name, passed, detail=""):
        self.results.append({"name": name, "passed": bool(passed), "detail": str(detail)[:400]})
        print(("PASS " if passed else "FAIL ") + name, str(detail)[:200], flush=True)

    def shot(self, name):
        data = self.tab.send("Page.captureScreenshot", {"format": "png"}, 40)["data"]
        (self.out / f"{name}.png").write_bytes(base64.b64decode(data))

    def until(self, fn, seconds=120, what=""):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                value = fn()
                if value:
                    return value
            except Exception:
                pass
            time.sleep(.15)
        raise TimeoutError(what)

    def move(self, x, y, steps=14):
        for i in range(1, steps + 1):
            px, py = self.x + (x - self.x) * i / steps, self.y + (y - self.y) * i / steps
            self.tab.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": px, "y": py})
            try:
                self.tab.main(f"window.__rec&&window.__rec.move({px},{py})")
            except Exception:
                pass
            time.sleep(.012)
        self.x, self.y = x, y

    def rect(self, expr):
        return self.tab.main(f"(()=>{{const e={expr};if(!e)return null;const r=e.getBoundingClientRect();return {{x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2}}}})()")

    def key(self, kind, code, key=None, vk=0):
        self.tab.send("Input.dispatchKeyEvent", {"type": kind, "code": code, "key": key or code, "windowsVirtualKeyCode": vk})

    def press(self, code, key=None, vk=0):
        self.key("keyDown", code, key, vk)
        time.sleep(.04)
        self.key("keyUp", code, key, vk)

    def click(self, x, y):
        self.move(x, y, 8)
        for kind in ("mousePressed", "mouseReleased"):
            self.tab.send("Input.dispatchMouseEvent", {"type": kind, "button": "left", "clickCount": 1, "x": x, "y": y})

    def panel_click(self, selector):
        def locate():
            r = self.tab.panel("card", f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(!e)return null;const r=e.getBoundingClientRect();return {{x:r.x+r.width/2,y:r.y+r.height/2}}}})()")
            if not r:
                return None
            f = self.tab.iso("(()=>{const r=window.__HERMES_GAZE_OVERLAY__.uiFrame.getBoundingClientRect();return {x:r.x,y:r.y}})()")
            return r["x"] + f["x"], r["y"] + f["y"]
        time.sleep(.5)
        x, y = self.until(locate, 10, selector)
        self.click(x, y)

    def typed(self, target, text):
        r = self.rect(target)
        self.move(r["cx"], r["cy"])
        time.sleep(.15)
        self.press("AltRight", "Alt")
        self.until(lambda: self.tab.panel("card", 'document.activeElement?.id==="hg-input"'), 10, "composer")
        time.sleep(.35)
        for char in text:
            self.tab.send("Input.dispatchKeyEvent", {"type": "char", "text": char})
        time.sleep(.2)
        return r

    def enter(self):
        self.press("Enter", "Enter", 13)


def own_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(args):
    import yaml
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    home = Path.home() / ".hermes"
    temp = Path(tempfile.mkdtemp(prefix="gaze-ui-"))
    chrome = rpc = None
    try:
        (temp / "plugins").mkdir()
        (temp / "skills").mkdir()
        (temp / "plugins" / "hermes-gaze").symlink_to(ROOT, target_is_directory=True)
        shutil.copy2(home / "auth.json", temp / "auth.json")
        (temp / "auth.json").chmod(0o600)
        config = yaml.safe_load((home / "config.yaml").read_text())
        port = own_port()
        config["plugins"] = {"enabled": ["hermes-gaze"], "isolation": "in_process", "entries": {"hermes-gaze": {
            "allow_gateway_injection": True, "settings": {"cdp_url": f"http://127.0.0.1:{port}", **json.loads(args.settings)}}}}
        config["mcp_servers"] = {}
        config["fallback_model"] = None
        (temp / "config.yaml").write_text(yaml.safe_dump(config))
        (temp / "config.yaml").chmod(0o600)
        model = {k: config.get("model", {}).get(k) for k in ("default", "provider")}
        print("model", model, flush=True)
        # Speech for the follow-up, through the real ASR path.
        subprocess.run(["say", "-o", str(temp / "speech.aiff"), "Why does that matter?"], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(temp / "speech.aiff"), "-ar", "16000", "-ac", "1", "-f", "s16le", str(temp / "speech.pcm")], check=True)
        (temp / "stub").mkdir()
        (temp / "stub" / "sounddevice.py").write_text(STUB)
        env = {**os.environ, "HOME": str(temp), "HERMES_HOME": str(temp), "HERMES_DISABLE_LAZY_INSTALLS": "1", "HERMES_IGNORE_RULES": "1",
               "PYTHONPATH": f"{temp / 'stub'}:{home / 'hermes-agent'}", "GAZE_FAKE_SPEECH": str(temp / "speech.pcm"), "GAZE_CWD": str(temp)}
        sys.path.insert(0, str(ROOT))
        import tests  # Register the plugin package shell without executing registration.
        from tests.owned_chrome import private_session
        companion = private_session(temp / ".cache/hermes-gaze/chrome-profile", port=port,
            chrome_args=("--window-size=1440,900", *(["--headless=new", "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"] if args.headless else [])))
        chrome = companion.cdp.chrome.process
        companion.close()  # Browser stays warm; the host must acquire its own exclusive runtime lease.
        with (temp / "backend.log").open("w+") as log:
            # Hermes's bootstrap rewrites sys.path, so the stub must already be in sys.modules.
            # Without this the backend opens the real microphone.
            launcher = (f"import sys,runpy;sys.path.insert(0,{str(temp / 'stub')!r});import sounddevice;"
                        "assert sounddevice.__file__.endswith('stub/sounddevice.py');"
                        "sys.argv=['tui_gateway.entry'];runpy.run_module('tui_gateway.entry',run_name='__main__',alter_sys=True)")
            rpc = Rpc([sys.executable, "-c", launcher], env, log)
            rpc.wait(lambda f: f.get("params", {}).get("type") == "gateway.ready", 240)
            sid = rpc.call("session.create", source="tui", cwd=str(temp), title="Companion UI")["session_id"]
            rpc.call("prompt.submit", session_id=sid, text="Reply with Ready.")
            ready = rpc.wait(lambda f: f.get("params", {}).get("session_id") == sid and f.get("params", {}).get("type") in ("message.complete", "error"), 240)["params"]
            print("first turn", ready.get("type"), str(ready.get("payload", {}).get("status")), flush=True)
            print(str(rpc.call("command.dispatch", session_id=sid, name="gaze", arg="connect").get("output"))[:160], flush=True)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as r:
                page = next(t for t in json.load(r) if t["type"] == "page")
            tab = Tab(page["webSocketDebuggerUrl"])
            flow = Flow(tab, out)
            scenario(flow, tab, rpc, sid, args)
            (out / "results.json").write_text(json.dumps({"model": model, "results": flow.results}, indent=2))
            passed = sum(r["passed"] for r in flow.results)
            print(f"{passed}/{len(flow.results)} passed", flush=True)
    finally:
        if args.keep_log and (temp / "backend.log").exists():
            shutil.copy2(temp / "backend.log", out / "backend.log")
        if args.keep_log and (temp / "speech.pcm.log").exists():
            shutil.copy2(temp / "speech.pcm.log", out / "stub-audio.log")
        if rpc:
            try:
                rpc.proc.stdin.close()
                rpc.proc.terminate()
                rpc.proc.wait(timeout=8)
            except Exception:
                rpc.proc.kill()
        if chrome:
            chrome.terminate()
            try:
                chrome.wait(timeout=8)
            except subprocess.TimeoutExpired:
                chrome.kill()
        shutil.rmtree(temp, ignore_errors=True)


def setup_page(tab, url, width=1440, height=900):
    tab.send("Page.bringToFront")
    tab.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
    tab.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 2, "mobile": False})
    tab.send("Page.navigate", {"url": url}, 60)
    for _ in range(150):
        time.sleep(.2)
        try:
            if tab.main("document.readyState") == "complete" and tab.panel("pill", "!!window.__HERMES_GAZE_PANEL__"):
                break
        except Exception:
            continue
    time.sleep(1.5)
    tab.main(CURSOR)


def statuses(tab):
    return [i["status"] for i in tab.debug()["items"]]


def scenario(flow, tab, rpc, sid, args):
    # ---------- Hacker News: several queued typed questions, in-order answers, stack and capsule ----------
    setup_page(tab, "https://news.ycombinator.com/")
    tab.send("Page.startScreencast", {"format": "jpeg", "quality": 70, "maxWidth": 1440, "maxHeight": 900, "everyNthFrame": 2})
    t = lambda n: f'document.querySelectorAll(".titleline > a")[{n}]'
    flow.shot("01-idle-nothing-on-screen")
    flow.note("idle: nothing on screen", tab.debug()["view"] is None and tab.debug()["pill"]["mode"] in ("none", "coach"))
    flow.typed(t(0), "What is this about? Give a one sentence verdict with the key phrase in **bold**, then a short bullet list of two points.")
    flow.shot("02-typed-question")
    flow.enter()
    time.sleep(.5)
    flow.typed(t(3), "Is this worth reading? Answer in two short sentences with one *italic* word.")
    flow.enter()
    flow.typed(t(6), "Give me a small markdown table with two rows comparing this story with the one above it on topic and audience, then a line of inline `code` naming the site.")
    flow.enter()
    time.sleep(.5)
    flow.shot("03-capsule-queued")
    words = tab.panel("pill", 'document.getElementById("pill")?.textContent')
    print("capsule:", words, tab.debug()["pill"], flush=True)
    flow.note("capsule says what's in progress", "Looking into" in (words or ""), words)
    # In-order: record when each answer starts and finishes.
    order, seen, start = [], set(), time.monotonic()
    shots = set()
    while time.monotonic() - start < 300:
        d = tab.debug()
        for n, item in enumerate(d["items"]):
            for state in ("streaming", "complete"):
                if item["status"] and item["status"][0] == state and (n, state) not in seen:
                    seen.add((n, state))
                    order.append((n, state, round(time.monotonic() - start, 1)))
        streaming = next((n for n, i in enumerate(d["items"]) if i["status"] == ["streaming"]), None)
        if streaming is not None and streaming not in shots:
            shots.add(streaming)
            time.sleep(.5)
            flow.shot(f"04-streaming-answer-{streaming + 1}")
        if len(d["items"]) >= 3 and all(i["status"][-1] in ("complete", "failed", "interrupted") for i in d["items"]):
            break
        time.sleep(.12)
    print("order", order, flush=True)
    starts = [n for n, state, _ in order if state == "streaming"] or [n for n, state, _ in order if state == "complete"]
    flow.note("answers arrive in question order", starts == sorted(starts) and len(d["items"]) == 3, order)
    print([i["subject"] for i in tab.debug()["items"]], flush=True)
    time.sleep(1)
    flow.shot("05-stack")
    # ---------- arrows move through the stack, by name ----------
    first = tab.debug()["cur"]
    while tab.debug()["cur"] != tab.debug()["items"][0]["subject"]:
        flow.press("ArrowUp", "ArrowUp", 38)
        time.sleep(.4)
    flow.press("ArrowDown", "ArrowDown", 40)
    time.sleep(.5)
    flow.shot("06-stack-arrow-peeks")
    flow.note("arrows move between answers", tab.debug()["cur"] == tab.debug()["items"][1]["subject"], first)
    flow.press("ArrowDown", "ArrowDown", 40)
    time.sleep(.6)
    table_html = tab.panel("card", 'document.querySelector("#hg-reply")?.innerHTML||""')
    text = tab.panel("card", 'document.querySelector("#hg-reply")?.innerText||""')
    flow.shot("07-markdown-table-answer")
    print(text[:500], flush=True)
    flow.note("markdown answer has no raw markers", "**" not in text and "|---" not in text, text[:120])
    flow.note("markdown table rendered", "<table" in table_html, table_html[:100])
    # ---------- click-back ----------
    tab.main("window.scrollTo(0,700)")
    time.sleep(.7)
    flow.shot("08-scrolled-away-glow")
    d = tab.debug()
    flow.click(d["card"]["x"] + 170, d["card"]["y"] + 22)
    time.sleep(1.0)
    flow.shot("09-click-back-relit")
    target = flow.rect(t(6))
    flow.note("click scrolls back and relights", 0 < target["y"] < 900 and tab.debug()["lit"] >= 1, target)
    # ---------- follow-up by holding Space, through real ASR ----------
    pressed = time.monotonic()
    flow.key("keyDown", "Space", " ", 32)
    flow.until(lambda: tab.debug()["talk"]["micReady"], 10, "Listening")
    print("Listening after", round(time.monotonic() - pressed, 3), flush=True)
    flow.note("follow-up label on the card", "Asking more" in (tab.panel("pill", 'document.getElementById("pill")?.textContent') or ""), tab.debug()["hold"])
    flow.shot("10-follow-up-listening")
    time.sleep(max(0, 2.0 - (time.monotonic() - pressed)))
    flow.key("keyUp", "Space", " ", 32)
    d0 = len(tab.debug()["items"])
    item = flow.until(lambda: (x if len((x := tab.debug()["items"][2])["status"]) == 2 and x["status"][-1] in ("complete", "failed", "interrupted") else None), 150, "follow-up")
    flow.note("follow-up stays in the same card", len(tab.debug()["items"]) == d0 and item["status"][-1] == "complete", [item, tab.debug()["errors"]])
    time.sleep(.6)
    flow.shot("11-follow-up-answer")
    print(tab.panel("card", 'document.querySelector("#hg-reply")?.innerText||""')[-400:], flush=True)
    # ---------- Esc, then Q ----------
    flow.move(1380, 860)
    flow.press("Escape", "Escape", 27)
    time.sleep(.6)
    d = tab.debug()
    flow.shot("12-dismissed-nothing")
    flow.note("Esc leaves nothing on screen", d["view"] is None and d["lit"] == 0)
    flow.press("KeyQ", "q", 81)
    time.sleep(.7)
    flow.shot("13-q-recall")
    flow.note("Q brings answers back", tab.debug()["view"] == "answer")
    flow.press("Escape", "Escape", 27)
    time.sleep(.3)
    # ---------- Try again: interrupt a real turn ----------
    flow.typed(t(9), "Write three long paragraphs about what this story means for the industry.")
    before = len(tab.debug()["items"])
    flow.enter()
    flow.until(lambda: len(tab.debug()["items"]) > before, 15, "new item")
    n = before
    flow.until(lambda: tab.debug()["items"][n]["status"][-1] in ("thinking", "streaming", "complete", "failed"), 60, "turn started")
    print("interrupting at", tab.debug()["items"][n]["status"], tab.debug()["errors"][-1:], flush=True)
    time.sleep(.5)
    print(rpc.call("session.interrupt", session_id=sid), flush=True)
    flow.until(lambda: tab.debug()["items"][n]["status"][-1] in ("interrupted", "failed", "complete"), 60, "interrupted")
    time.sleep(.8)
    status = tab.debug()["items"][n]["status"][-1]
    flow.shot("14-error-try-again")
    words = tab.panel("card", 'document.querySelector(".card")?.innerText||""')
    print(status, words[-160:], flush=True)
    flow.note("failure is one plain sentence with Try again", status != "complete" and "Try again" in words, words[-120:])
    flow.panel_click(".retry")
    flow.until(lambda: tab.debug()["items"][n]["status"][-1] == "complete", 240, "retry")
    time.sleep(.8)
    flow.shot("15-try-again-answered")
    flow.note("Try again produces a real answer", True, tab.debug()["items"][n])
    flow.press("Escape", "Escape", 27)
    tab.send("Page.stopScreencast")
    make_recording(tab, flow.out)
    # ---------- Real deals page: hold Space over two things, soft and dark are separate ----------
    setup_page(tab, "https://www.woot.com/")
    cards = tab.main("""(()=>{const out=[];for(const e of document.querySelectorAll('a')){const r=e.getBoundingClientRect();
      if(r.width>120&&r.height>120&&r.width<500&&r.top>30&&r.bottom<innerHeight-160&&e.querySelector('img'))out.push({x:r.left+r.width/2,y:r.top+r.height/2})}return out})()""") or []
    print("deal cards found:", len(cards), flush=True)
    if len(cards) < 2:
        # Deal sites may show a bot check or banner to a private browser; any real page proves this.
        setup_page(tab, "https://en.wikipedia.org/wiki/Hermes")
        cards = tab.main("""(()=>{const out=[];for(const e of document.querySelectorAll('.mw-parser-output > p')){const r=e.getBoundingClientRect();
          if(r.height>40&&r.top>60&&r.bottom<innerHeight-40)out.push({x:r.left+60,y:r.top+12})}return out})()""") or []
    if len(cards) >= 2:
        flow.move(cards[0]["x"], cards[0]["y"])
        time.sleep(.2)
        flow.key("keyDown", "Space", " ", 32)
        time.sleep(.5)
        flow.move(cards[1]["x"], cards[1]["y"])
        time.sleep(.5)
        flow.shot("16-deals-listening-two")
        lit = tab.debug()["hold"]["targets"]
        flow.key("keyUp", "Space", " ", 32)
        flow.note("each thing pointed at stays lit", lit >= 2, lit)
        time.sleep(.4)
        flow.shot("17-deals-capsule")
        n = len(tab.debug()["items"]) - 1
        flow.until(lambda: tab.debug()["items"][n]["status"][-1] in ("complete", "failed", "interrupted"), 240, "deals answer")
        time.sleep(.6)
        flow.shot("18-deals-answer")
        print("deal subject:", tab.debug()["items"][n]["subject"], flush=True)
    # ---------- Guarded click: a normal Hermes turn on the local page ----------
    setup_page(tab, (ROOT / "benchmark" / "benchmark_page.html").as_uri())
    tab.main("window.__clicks=[];document.querySelector('#btn-purge-cache').addEventListener('click',()=>window.__clicks.push(1))")
    r = flow.rect('document.querySelector("#btn-purge-cache")')
    flow.move(r["cx"], r["cy"])
    time.sleep(.3)
    confirm = False
    for attempt in range(2):
        rpc.call("prompt.submit", session_id=sid, text="Click this button for me now using gaze_click.")
        try:
            flow.until(lambda: tab.debug()["view"] == "confirm", 180, "confirmation")
            confirm = True
            break
        except TimeoutError:
            print("no confirmation on attempt", attempt + 1, flush=True)
    flow.note("guarded click asks for confirmation", confirm)
    if confirm:
        time.sleep(.6)
        flow.shot("19-guarded-click-confirm")
        flow.note("no click before confirmation", tab.main("window.__clicks.length") == 0)
        # A synthetic click inside the protected frame must do nothing.
        tab.panel("card", 'document.querySelector(".choice.yes")?.click();true')
        time.sleep(.4)
        flow.note("synthetic confirm rejected", tab.main("window.__clicks.length") == 0 and tab.debug()["view"] == "confirm")
        flow.panel_click(".choice.yes")
        flow.until(lambda: tab.main("window.__clicks.length") == 1, 15, "clicked")
        flow.note("trusted click executes once", tab.main("window.__clicks.length") == 1)
        time.sleep(.5)
        flow.shot("20-guarded-click-done")
    print(tab.debug()["items"][-1:], flush=True)


def make_recording(tab, out):
    frames = list(tab.frames)
    if len(frames) < 2:
        return
    with tempfile.TemporaryDirectory() as d:
        listing = []
        for i, (stamp, data) in enumerate(frames):
            path = Path(d) / f"{i:05}.jpg"
            path.write_bytes(base64.b64decode(data))
            gap = frames[i + 1][0] - stamp if i + 1 < len(frames) else .1
            listing.append(f"file '{path}'\nduration {min(max(gap, .01), 2.5):.3f}\n")
        (Path(d) / "list.txt").write_text("".join(listing))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(Path(d) / "list.txt"),
                        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", str(out / "flow.mp4")], check=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--settings", default="{}", help="JSON of extra plugin settings")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--keep-log", action="store_true")
    run(parser.parse_args())
