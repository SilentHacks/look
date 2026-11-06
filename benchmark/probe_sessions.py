"""Real cursor voice turns in Hermes TUI/desktop backends and private Chrome.

Uses private config/credential copies and private Chrome. The harness replaces
the fake microphone's captured audio with synthesized WAV before the real
transcribe binding. Physical capture and desktop renderer automation are not claimed.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)


class Rpc:
    def __init__(self, env: dict, log) -> None:
        self.proc = subprocess.Popen([sys.executable, "-m", "tui_gateway.entry"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                     text=True, env=env)
        self.frames = queue.Queue()
        self.events = []
        self.seq = 0
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in self.proc.stdout:
            try:
                self.frames.put(json.loads(line))
            except json.JSONDecodeError:
                continue  # dependency startup progress is not an RPC frame
        self.frames.put({"backend_exit": self.proc.poll()})

    def wait(self, predicate, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self.frames.get(timeout=max(.01, deadline - time.monotonic()))
            if "backend_exit" in frame:
                raise RuntimeError(f"Hermes backend exited: {frame}")
            if predicate(frame):
                return frame
            self.events.append(frame)
        raise TimeoutError("Hermes RPC deadline exceeded")

    def call(self, method, **params):
        self.seq += 1
        rid = self.seq
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        response = self.wait(lambda frame: frame.get("id") == rid)
        if "error" in response:
            raise RuntimeError(f"{method}: {response['error']}")
        return response["result"]

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=10)


def chrome_command(port, method, params):
    from websockets.sync.client import connect
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
        tab = next(t for t in json.load(response) if t["type"] == "page")
    with connect(tab["webSocketDebuggerUrl"]) as ws:
        ws.send(json.dumps({"id": 1, "method": method, "params": params}))
        while True:
            frame = json.loads(ws.recv())
            if frame.get("id") == 1:
                if frame.get("error"):
                    raise RuntimeError(frame["error"])
                return frame["result"]


def chrome_eval(port: int, expression: str):
    result = chrome_command(port, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
    if result.get("exceptionDetails"):
        raise RuntimeError(result["exceptionDetails"])
    return result["result"].get("value")


def speech_question(root: Path, temp: Path) -> dict:
    subprocess.run(["say", "-o", str(temp / "speech.aiff"), "Summarize this table in one sentence."], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(temp / "speech.aiff"), "-ar", "16000", "-ac", "1",
                    str(temp / "speech.wav")], check=True)
    import wave
    with wave.open(str(temp / "speech.wav"), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    return {"source": "Synthesized WAV replaces Chrome fake-device audio before the real transcription binding",
            "duration_s": duration, "text": "Summarize this table in one sentence."}


def browser_wait(port, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if chrome_eval(port, predicate):
                return
        except Exception:
            logger.debug("Chrome context temporarily unavailable", exc_info=True)
        time.sleep(.05)
    raise TimeoutError("Chrome condition did not arrive: " + predicate[:100])


def trusted_click(port, x, y):
    for event in ("mousePressed", "mouseReleased"):
        chrome_command(port, "Input.dispatchMouseEvent",
                       {"type": event, "x": x, "y": y, "button": "left", "clickCount": 1})


def screenshot(args, source, state):
    if args.screenshot:
        image = chrome_command(args.port, "Page.captureScreenshot", {"format": "png"})
        path = args.screenshot.with_name(f"{args.screenshot.stem}-{source}-{state}.png")
        path.write_bytes(base64.b64decode(image["data"]))


def run(args) -> dict:
    import psutil
    import yaml
    from hermes_cli.config import load_config
    from hermes_constants import get_hermes_home

    root = Path(__file__).resolve().parents[1]
    config = load_config()
    home = get_hermes_home()
    report = {"scope": "real Hermes TUI/desktop backend, Chrome microphone/transcription/binding and model",
              "model_config": {k: config.get("model", {}).get(k) for k in ("default", "provider")},
              "surfaces": {}}
    with tempfile.TemporaryDirectory(prefix="gaze-sessions-") as directory:
        temp = Path(directory)
        report["speech"] = speech_question(root, temp)
        (temp / "plugins").mkdir()
        (temp / "skills").mkdir()  # Hermes omits even plugin skill hints when this directory is absent.
        (temp / "plugins" / "hermes-gaze").symlink_to(root, target_is_directory=True)
        for name in (".env", "auth.json"):
            if (home / name).exists():
                shutil.copy2(home / name, temp / name)
                (temp / name).chmod(0o600)
        config["plugins"] = {"enabled": ["hermes-gaze"], "isolation": "in_process",
                             "entries": {"hermes-gaze": {"allow_gateway_injection": True,
                                                        "settings": {"cdp_url": f"http://127.0.0.1:{args.port}"}}}}
        config["mcp_servers"] = {}
        config["fallback_model"] = None
        (temp / "config.yaml").write_text(yaml.safe_dump(config))
        (temp / "config.yaml").chmod(0o600)
        env = {**os.environ, "HERMES_HOME": str(temp), "HERMES_IGNORE_RULES": "1"}
        chrome = subprocess.Popen([args.chrome, "--headless=new", "--no-first-run", "--no-default-browser-check",
                                   "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                                   f"--remote-debugging-port={args.port}", f"--user-data-dir={temp / 'chrome'}",
                                   "--window-size=1440,1100", (root / "benchmark/benchmark_page.html").as_uri()],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with (temp / "backend.log").open("w+") as log:
                rpc = Rpc(env, log)
                try:
                    rpc.wait(lambda f: f.get("params", {}).get("type") == "gateway.ready")
                    foreign = rpc.call("session.create", source="tui", cwd=str(temp), title="Unbound control session")["session_id"]
                    for source in args.sources:
                        created = rpc.call("session.create", source=source, cwd=str(temp), title=f"Gaze {source}")
                        sid = created["session_id"]
                        tools = rpc.call("slash.exec", session_id=sid, command="/tools")
                        assert "gaze_click" in json.dumps(tools), tools
                        result = {"trials": []}
                        for trial in range(args.trials):
                            if report["surfaces"] or trial:
                                chrome_eval(args.port, "location.reload();true")
                                browser_wait(args.port, "!!window.__HERMES_GAZE_OVERLAY__")
                            connected = rpc.call("command.dispatch", session_id=sid, name="gaze", arg="connect")
                            assert "connected" in connected["output"].lower(), connected
                            browser_wait(args.port, "!!window.__HERMES_GAZE_OVERLAY__")
                            chrome_eval(args.port, "window.__speechWav=" +
                                        json.dumps(base64.b64encode((temp / "speech.wav").read_bytes()).decode()) + ";true")
                            chrome_eval(args.port, """(() => {
                              const api=window.__HERMES_GAZE_OVERLAY__;
                              const binding=window.__hermesGazeIntent;
                              window.__hermesGazeIntent=raw=>{const msg=JSON.parse(raw);
                                if(msg.type==='transcribe'){msg.audio_base64=window.__speechWav;msg.mime_type='audio/wav'}
                                binding(JSON.stringify(msg))};
                              window.__snapshotCalls=[];
                              for(const name of ['highlightSnapshot','clickSnapshot','requestActionConfirmation']){
                                const original=api[name];api[name]=(...args)=>{const result=original(...args);
                                  window.__snapshotCalls.push({name,args,result});return result};
                              }
                              window.__intentReplies=[];const onReply=api.onIntentResult;
                              api.onIntentResult=e=>{window.__intentReplies.push(e);onReply(e)};
                              window.__sessionEvents=[];const onEvent=api.onSessionEvent;
                              api.onSessionEvent=e=>{window.__sessionEvents.push(e);onEvent(e)};
                              window.__websiteClicks=[];
                              document.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>window.__websiteClicks.push(b.id)));
                              return true})()""")

                            def aim(selector):
                                return chrome_eval(args.port, f"""(() => {{
                                  const e=document.querySelector({json.dumps(selector)});e.scrollIntoView({{block:'nearest'}});
                                  const r=e.getBoundingClientRect();window.__HERMES_GAZE_OVERLAY__.recordPoint(r.x+r.width/2,r.y+r.height/2);
                                  return true}})()""")

                            def finish_turn():
                                frame = rpc.wait(lambda f: f.get("params", {}).get("session_id") == sid and
                                                 f.get("params", {}).get("type") in ("message.complete", "error"), timeout=240)
                                assert frame["params"]["type"] != "error", frame
                                browser_wait(args.port, "window.__sessionEvents.some(e=>e.status==='complete'&&e.text)", timeout=30)
                                events = chrome_eval(args.port, "window.__sessionEvents")
                                complete = next(e for e in reversed(events) if e["status"] == "complete" and e.get("text"))
                                assert complete["text"] in chrome_eval(args.port,
                                    "document.querySelector('#hermes-gaze-root').shadowRoot.querySelector('#hg-reply').innerText")
                                assert not any(f.get("params", {}).get("session_id") == foreign and
                                               f.get("params", {}).get("type") == "message.complete" for f in rpc.events)
                                return {"events": events, "completion": frame["params"], "answer": complete["text"]}

                            def submit(text):
                                chrome_eval(args.port, f"""(() => {{window.__sessionEvents=[];
                                  const s=document.querySelector('#hermes-gaze-root').shadowRoot;
                                  s.querySelector('#hg-input').value={json.dumps(text)};s.querySelector('#hg-send').click();return true}})()""")
                                return finish_turn()

                            aim("#campaigns-table tbody tr:nth-child(3) td:nth-child(3)")
                            chrome_eval(args.port, "window.__HERMES_GAZE_OVERLAY__.startListening();true")
                            time.sleep(report["speech"]["duration_s"] + .15)
                            chrome_eval(args.port, "window.__HERMES_GAZE_OVERLAY__.stopListening();true")
                            browser_wait(args.port, "window.__intentReplies.some(e=>e.type==='submit'||e.type==='transcribe'&&!e.ok)", timeout=120)
                            admission = chrome_eval(args.port, "window.__intentReplies")
                            assert not any(not e.get("ok") for e in admission), admission
                            assert any(e.get("delivery") == "session" for e in admission), admission
                            initial = finish_turn()
                            assert any(e.get("text") and e["status"] == "thinking" for e in initial["events"]), initial
                            assert "campaign" in initial["answer"].lower(), initial
                            pins = chrome_eval(args.port, """(() => {
                              const s=document.querySelector('#hermes-gaze-root').shadowRoot;
                              return [...s.querySelectorAll('.pin-box')].map(e=>({width:parseFloat(e.style.width),height:parseFloat(e.style.height)}))})()""")
                            table_rect = chrome_eval(args.port, "document.querySelector('#campaigns-table').getBoundingClientRect().toJSON()")
                            assert any(abs(pin["width"] - table_rect["width"]) < 12 for pin in pins), pins
                            screenshot(args, source, "answer")
                            followup = submit("No, the whole table. Compare all five campaigns, including Enterprise Outbound.")
                            assert "Enterprise" in followup["answer"], followup
                            exported = submit("Export this table using its Export CSV control.")
                            browser_wait(args.port, "window.__websiteClicks.includes('btn-export-csv')")
                            assert "btn-purge-cache" not in chrome_eval(args.port, "window.__websiteClicks")
                            aim("#btn-purge-cache")
                            purge = submit("Purge this cache.")
                            assert "btn-purge-cache" not in chrome_eval(args.port, "window.__websiteClicks"), purge
                            screenshot(args, source, "confirmation")
                            card = chrome_eval(args.port, """(() => {
                              const s=document.querySelector('#hermes-gaze-root').shadowRoot;
                              const b=[...s.querySelectorAll('button')].find(e=>/^confirm/i.test(e.textContent.trim()));
                              if(!b)return null;b.click();const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()""")
                            assert card, purge
                            assert "btn-purge-cache" not in chrome_eval(args.port, "window.__websiteClicks")
                            trusted_click(args.port, card["x"], card["y"])
                            browser_wait(args.port, "window.__websiteClicks.includes('btn-purge-cache')")
                            clicks = chrome_eval(args.port, "window.__websiteClicks")
                            assert clicks.count("btn-purge-cache") == 1, clicks
                            disconnected = rpc.call("command.dispatch", session_id=sid, name="gaze", arg="disconnect")
                            result["trials"].append({"initial": initial, "followup": followup, "export": exported,
                                                     "purge": purge, "website_clicks": clicks, "pins": pins,
                                                     "disconnected": disconnected, "synthetic_confirmation_blocked": True,
                                                     "trusted_confirmation_executed_once": True})
                            print(json.dumps({"source": source, "trial": trial + 1, "voice": True,
                                              "followup": True, "export": True, "trusted_confirmation": True}), flush=True)
                        report["surfaces"][source] = result
                        rpc.call("session.close", session_id=sid)
                    rpc.call("session.close", session_id=foreign)
                except Exception:
                    log.flush()
                    log.seek(0)
                    try:
                        report["failure"] = chrome_eval(args.port, """({
                          events:window.__sessionEvents,replies:window.__intentReplies,calls:window.__snapshotCalls,
                          hud:document.querySelector('#hermes-gaze-root')?.shadowRoot?.textContent?.slice(-5000)})""")
                        args.output.write_text(json.dumps(report, indent=2) + "\n")
                    except Exception:
                        logger.debug("Unable to save Chrome failure evidence", exc_info=True)
                    print(log.read()[-6000:], file=sys.stderr)
                    raise
                finally:
                    rpc.close()
        finally:
            processes = [psutil.Process(chrome.pid)]
            processes.extend(processes[0].children(recursive=True))
            for process in processes:
                try:
                    process.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(processes, timeout=10)
            for process in alive:
                process.kill()
            psutil.wait_procs(alive, timeout=5)
            chrome.wait(timeout=10)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9334)
    parser.add_argument("--chrome", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    parser.add_argument("--sources", nargs="+", default=["tui", "desktop"])
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--screenshot", type=Path, help="PNG prefix for real answer and confirmation surfaces")
    args = parser.parse_args()
    result = run(args)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
