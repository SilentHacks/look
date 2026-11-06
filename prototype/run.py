#!/usr/bin/env python3
"""One-command Hermes Gaze UI prototype. Scripted: no model, microphone, plugin or API key.

Starts a private Chrome (own temp profile, own debugging port) and injects the prototype over
the DevTools Protocol, using the same structure as browser/cdp_bridge.py. Your normal Chrome
is not touched. Ctrl-C closes the private Chrome and deletes its profile.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdp import Browser, CDPError  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WORLD = "hermes_gaze_prototype"
BINDING = "__hgProto"
DEFAULT_TABS = [
    "https://news.ycombinator.com/",
    "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)",
    "https://en.wikipedia.org/wiki/Hermes",
    "https://www.woot.com/",
    "https://docs.astral.sh/ruff/",
    (HERE.parent / "benchmark" / "benchmark_page.html").as_uri(),
]


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("no free port")


class Tab:
    def __init__(self, session: str, target: str):
        self.session = session
        self.target = target
        self.main_ctx = None      # uniqueId-free: plain context id of the main-frame world
        self.frame_ctx: dict[str, int] = {}
        self.ctx_owner: dict[int, str] = {}
        self.worlds: set[tuple[int, str]] = set()


class Injector:
    def __init__(self, br: Browser):
        self.br = br
        self.tabs: dict[str, Tab] = {}
        self.page_js = (HERE / "page.js").read_text()
        self.panel_js = (HERE / "panel.js").read_text()
        self.saved: dict[str, dict] = {}
        self.coach = {"heard": False, "answered": 0, "retreated": False}
        self.options: dict = {}
        self.seen: set[str] = set()
        self.lock = threading.Lock()
        br.on(self.on_event)
        # Discovery sees every tab, including ones you open by hand.
        br.send("Target.setDiscoverTargets", {"discover": True})

    def on_event(self, method: str, params: dict, session: str | None) -> None:
        if method in ("Target.targetCreated", "Target.targetInfoChanged"):
            info = params["targetInfo"]
            if info.get("type") == "page" and not info.get("url", "").startswith(("devtools:", "chrome:", "chrome-extension:")):
                with self.lock:
                    if info["targetId"] in self.seen:
                        return
                    self.seen.add(info["targetId"])
                threading.Thread(target=self.attach, args=(info["targetId"],), daemon=True).start()
        elif method == "Target.targetDestroyed":
            for sid, tab in list(self.tabs.items()):
                if tab.target == params["targetId"]:
                    self.tabs.pop(sid, None)
                    self.saved.pop(sid, None)
        elif method == "Runtime.bindingCalled" and params.get("name") == BINDING and session in self.tabs:
            self.on_binding(self.tabs[session], params)
        elif method == "Runtime.executionContextCreated" and session in self.tabs:
            ctx = params["context"]
            if ctx.get("name") == WORLD:
                self.tabs[session].worlds.add((ctx["id"], ctx.get("auxData", {}).get("frameId")))
        elif method == "Runtime.executionContextsCleared" and session in self.tabs:
            tab = self.tabs[session]
            tab.main_ctx = None
            tab.frame_ctx.clear()
            tab.ctx_owner.clear()
            tab.worlds.clear()

    def attach(self, target: str) -> None:
        try:
            session = self.br.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            tab = Tab(session, target)
            self.tabs[session] = tab
            for method, params in (
                ("Page.enable", {}),
                ("DOM.enable", {}),
                ("Runtime.enable", {}),
                ("Runtime.addBinding", {"name": BINDING, "executionContextName": WORLD}),
                ("Page.addScriptToEvaluateOnNewDocument", {"source": self.page_js, "worldName": WORLD}),
            ):
                self.br.send(method, params, session)
            # The script covers every later document. If this one started before it was
            # registered, it has no world of ours yet: inject now, exactly once.
            frame = self.br.send("Page.getFrameTree", session=session)["frameTree"]["frame"]["id"]
            if not any(owner == frame for _, owner in tab.worlds):
                world = self.br.send("Page.createIsolatedWorld", {"frameId": frame, "worldName": WORLD}, session)["executionContextId"]
                self.br.send("Runtime.evaluate", {"expression": self.page_js, "contextId": world}, session)
        except (CDPError, ConnectionError, TimeoutError) as exc:
            if os.environ.get("HG_PROTO_DEBUG"):
                print(f"[attach] {target}: {exc!r}", flush=True)  # chrome:// pages and fast-closing tabs refuse; carry on

    def on_binding(self, tab: Tab, params: dict) -> None:
        ctx = params["executionContextId"]
        msg = json.loads(params["payload"])
        kind = msg.get("t")
        if kind == "boot":
            tab.main_ctx = ctx
            threading.Thread(target=self.init_frames, args=(tab, ctx, msg), daemon=True).start()
        elif kind == "panel":
            frame_ctx = tab.frame_ctx.get(msg["frame"])
            if frame_ctx:
                self.eval(tab, f"window.__HG_PANEL__?.render({json.dumps(msg['msg'])})", frame_ctx)
        elif kind == "persist":
            self.saved[tab.session] = msg["state"]
        elif kind == "coach":
            self.coach = msg["coach"]
        elif kind == "options":
            self.options = msg["options"]
        elif kind == "panelReady":
            pass
        elif tab.main_ctx:
            # Anything from a private frame goes to the page world's isolated renderer, never the page.
            owner = tab.ctx_owner.get(ctx)
            if owner:
                self.eval(tab, f"window.__HG_PROTO__?.fromPanel({json.dumps(owner)},{json.dumps(msg)})", tab.main_ctx)

    def eval(self, tab: Tab, expr: str, ctx: int) -> None:
        self.br.send_async("Runtime.evaluate", {"expression": expr, "contextId": ctx}, tab.session)

    def init_frames(self, tab: Tab, main_ctx: int, boot: dict) -> None:
        try:
            for name in boot["frames"]:
                remote = self.br.send("Runtime.evaluate", {"expression": f"window.__HG_PROTO__.frames.{name}", "contextId": main_ctx}, tab.session)
                object_id = remote["result"]["objectId"]
                frame_id = self.br.send("DOM.describeNode", {"objectId": object_id}, tab.session)["node"]["frameId"]
                self.br.send("Runtime.releaseObject", {"objectId": object_id}, tab.session)
                world = self.br.send("Page.createIsolatedWorld", {"frameId": frame_id, "worldName": WORLD}, tab.session)["executionContextId"]
                tab.frame_ctx[name] = world
                tab.ctx_owner[world] = name
                self.br.send("Runtime.evaluate", {"expression": self.panel_js, "contextId": world}, tab.session)
            saved = dict(self.saved.get(tab.session) or {})
            saved.setdefault("coach", self.coach)
            for key, value in self.options.items():
                saved.setdefault(key, value)
            self.br.send("Runtime.evaluate", {"expression": f"window.__HG_PROTO__.ready({json.dumps(saved)})", "contextId": main_ctx}, tab.session)
        except (CDPError, ConnectionError, TimeoutError) as exc:
            print(f"[frames] {boot.get('url','')[:60]}: {exc}", flush=True)


BANNER = """
  Hermes Gaze UI prototype (scripted: sample answers, no microphone, no model)

  Try it in the Chrome window that just opened:

    Point at anything          move the mouse; nothing shows until you talk
    Hold Space                 "talk": a waveform appears, what you point at lights up and stays lit
    Keep holding, point again  "this... or this"; you can scroll while holding, too
    Let go                     the waveform shrinks into a capsule; do it again to queue more
    Up / Down arrows           move between answers; the next one peeks out behind
    Click an answer            the page scrolls back to that item and lights it up
    Hold Space on an answer    asks a follow-up in the same card
    Q                          bring answers back after they retreat
    Esc                        dismiss
    ?                          prototype controls: soft eye-tracking region, long answer, error,
                               reduced motion, glass vs solid

  A quick tap on Space still pages down. Answers run: short, medium, long, error, then repeat.
  Everything you read is sample text. Point at the real page; the names come from its real text.
  Sites may show consent walls or bot checks to a private browser. Skip them, or open any
  other tab: every new tab is injected automatically.

  Press Ctrl-C here to quit. Your own Chrome and profile are untouched.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("urls", nargs="*", help="pages to open (default: the six test sites)")
    ap.add_argument("--port", type=int, default=9333, help="debugging port (default 9333; falls back to any free port)")
    ap.add_argument("--headless", action="store_true", help="no window (used for automated screenshots)")
    ap.add_argument("--size", default="1440,900", help="window size, e.g. 1440,900")
    args = ap.parse_args()
    if not Path(CHROME).exists():
        print(f"Google Chrome not found at {CHROME}", file=sys.stderr)
        return 1
    port = free_port(args.port)
    profile = tempfile.mkdtemp(prefix="hermes-gaze-proto-")
    cmd = [CHROME, f"--user-data-dir={profile}", f"--remote-debugging-port={port}", "--no-first-run",
           "--no-default-browser-check", "--disable-extensions", "--disable-sync", f"--window-size={args.size}",
           "--disable-features=Translate,PrivacySandboxSettings4", "about:blank"]
    if args.headless:
        cmd.append("--headless=new")
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGHUP, stop)
    signal.signal(signal.SIGINT, stop)
    chrome = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        br = None
        for _ in range(100):
            try:
                br = Browser(port)
                break
            except Exception:
                time.sleep(.2)
        if br is None:
            print("Chrome did not start", file=sys.stderr)
            return 1
        Injector(br)
        print(BANNER, flush=True)
        print(f"  Debugging port {port} · {br.version} · private profile {profile}\n", flush=True)
        # Chrome's initial tab goes last, so the window never reaches zero tabs and quits.
        initial = [t["targetId"] for t in br.send("Target.getTargets")["targetInfos"] if t["type"] == "page"]
        opened = [br.send("Target.createTarget", {"url": url})["targetId"] for url in args.urls or DEFAULT_TABS]
        for target in initial:
            try:
                br.send("Target.closeTarget", {"targetId": target})
            except CDPError:
                pass
        if opened:
            br.send("Target.activateTarget", {"targetId": opened[0]})
        while chrome.poll() is None and not br.closed.is_set():
            time.sleep(.5)
    except KeyboardInterrupt:
        print("\nClosing the private Chrome.", flush=True)
    finally:
        chrome.terminate()
        try:
            chrome.wait(8)
        except subprocess.TimeoutExpired:
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
