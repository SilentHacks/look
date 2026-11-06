"""Real Hermes TUI/desktop-backend experiment; run with Hermes's Python runtime.

Uses a temporary Hermes home (private copies of config/credentials), a private
headless Chrome, and the configured model. No user config/session is modified.
Desktop renderer and physical microphone are deliberately not simulated.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
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


class Rpc:
    def __init__(self, env: dict, log) -> None:
        self.proc = subprocess.Popen([shutil.which("hermes"), "--run-module", "tui_gateway.entry"],
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


def chrome_eval(port: int, expression: str):
    from websockets.sync.client import connect
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
        tab = next(t for t in json.load(response) if t["type"] == "page")
    with connect(tab["webSocketDebuggerUrl"]) as ws:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": expression, "returnByValue": True}}))
        while True:
            frame = json.loads(ws.recv())
            if frame.get("id") == 1:
                result = frame["result"]
                if result.get("exceptionDetails"):
                    raise RuntimeError(result["exceptionDetails"])
                return result["result"].get("value")


def speech_question(root: Path, temp: Path) -> dict:
    subprocess.run(["say", "-o", str(temp / "speech.aiff"), "Summarize this table in one sentence."], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(temp / "speech.aiff"), "-ar", "16000", "-ac", "1",
                    str(temp / "speech.wav")], check=True)
    spec = importlib.util.spec_from_file_location("gaze_phase0_experiment", root / "__init__.py",
                                                  submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from gaze_phase0_experiment.voice import transcribe_audio_buffer
    start = time.monotonic()
    text, words = transcribe_audio_buffer((temp / "speech.wav").read_bytes(), audio_epoch=time.time())
    if not text.strip() or "table" not in text.lower():
        raise RuntimeError(f"Speech fixture failed to transcribe: {text!r}")
    return {"source": "macOS synthesized speech, not physical microphone", "text": text,
            "word_count": len(words), "elapsed_s": time.monotonic() - start}


def run(args) -> dict:
    import yaml
    import psutil
    from hermes_cli.config import load_config
    from hermes_constants import get_hermes_home
    root = Path(__file__).resolve().parents[1]
    config = load_config()
    home = get_hermes_home()
    report = {"model_config": {k: config.get("model", {}).get(k) for k in ("default", "provider")},
              "scope": "real TUI/desktop backend sessions over stdio RPC; no renderer automation", "surfaces": {}}
    with tempfile.TemporaryDirectory(prefix="gaze-phase0-") as directory:
        temp = Path(directory)
        report["speech"] = speech_question(root, temp)
        (temp / "plugins").mkdir()
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
                                   f"--remote-debugging-port={args.port}", f"--user-data-dir={temp / 'chrome'}",
                                   "--window-size=1440,1100", (root / "benchmark/benchmark_page.html").as_uri()],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with (temp / "backend.log").open("w+") as log:
                rpc = Rpc(env, log)
                try:
                    rpc.wait(lambda f: f.get("params", {}).get("type") == "gateway.ready")
                    for source in args.sources:
                        created = rpc.call("session.create", source=source, cwd=str(temp), title=f"Gaze Phase 0 {source}")
                        sid = created["session_id"]
                        # slash.exec waits on the real agent-ready gate, unlike command.dispatch.
                        tools = rpc.call("slash.exec", session_id=sid, command="/tools")
                        result = {"tools_available": "gaze_highlight" in json.dumps(tools), "trials": []}
                        for trial in range(args.trials):
                            chrome_eval(args.port, "window.__HERMES_GAZE_OVERLAY__?.clearOverlays('phase0');true")
                            reply = rpc.call("command.dispatch", session_id=sid, name="gaze",
                                             arg="probe start " + report["speech"]["text"])
                            try:
                                accepted = json.loads(reply["output"])
                            except (KeyError, json.JSONDecodeError) as exc:
                                raise RuntimeError(f"Probe command returned {reply}") from exc
                            if not accepted.get("accepted"):
                                raise RuntimeError(accepted)
                            completed = rpc.wait(lambda f: f.get("params", {}).get("session_id") == sid and
                                                 f.get("params", {}).get("type") in ("message.complete", "error"))
                            status = rpc.call("command.dispatch", session_id=sid, name="gaze", arg="probe status")
                            initial = json.loads(status["output"])
                            initial["chrome_text"] = chrome_eval(args.port, "document.querySelector('#hermes-gaze-root').shadowRoot.querySelector('#hg-reply').innerText")
                            initial["client_completion"] = completed["params"]
                            initial["highlight_matches_table"] = chrome_eval(args.port, """(() => {
                              const shadow=document.querySelector('#hermes-gaze-root').shadowRoot;
                              return parseFloat(shadow.querySelector('.pin-box')?.style.width) ===
                                Math.round(document.querySelector('#campaigns-table').getBoundingClientRect().width)+8;
                            })()""")
                            checks = {
                                "tools_available": result["tools_available"],
                                "hook": bool(initial.get("hook_fired")),
                                "completed": bool(initial.get("finished")),
                                "model_called_highlight": "gaze_highlight" in initial.get("tools", []),
                                "correct_highlight": initial["highlight_matches_table"],
                                "streamed_to_chrome": initial.get("stream_deltas", 0) > 0 and initial.get("chrome_updates", 0) > 1,
                                "final_in_chrome": bool(initial.get("response")) and initial["response"] in initial["chrome_text"],
                                "used_fixture": "Oriole" in initial.get("response", "") and "Finch" in initial.get("response", ""),
                                "code_not_in_first_answer": initial.get("code") not in initial.get("response", ""),
                            }
                            rpc.call("command.dispatch", session_id=sid, name="gaze", arg="probe followup")
                            rpc.wait(lambda f: f.get("params", {}).get("session_id") == sid and
                                     f.get("params", {}).get("type") in ("message.complete", "error"))
                            status = rpc.call("command.dispatch", session_id=sid, name="gaze", arg="probe status")
                            followup = json.loads(status["output"])
                            checks["followup_recalled_code"] = bool(followup.get("finished") and followup.get("followup_recalled_code"))
                            checks["followup_without_resend"] = not followup.get("with_context")
                            result["trials"].append({"initial": initial, "followup": followup, "checks": checks})
                            print(json.dumps({"source": source, "trial": trial + 1, "checks": checks,
                                              "initial_s": initial.get("elapsed_s"), "followup_s": followup.get("elapsed_s")}), flush=True)
                        report["surfaces"][source] = result
                        rpc.call("session.close", session_id=sid)
                except Exception:
                    log.flush()
                    log.seek(0)
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
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()
    result = run(args)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
