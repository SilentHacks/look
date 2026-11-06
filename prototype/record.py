#!/usr/bin/env python3
"""Records the demo flow from a running prototype. The cursor and key label are recording aids."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Browser  # noqa: E402
from drive import Page  # noqa: E402

CARDS = """(()=>{const out=[];for(const e of document.querySelectorAll('a')){const r=e.getBoundingClientRect();
 if(r.width>120&&r.height>120&&r.width<500&&r.top>30&&r.bottom<innerHeight-120&&e.querySelector('img'))
 out.push({x:r.left+r.width/2,y:r.top+r.height/2})}return out})()"""


def hold(p, seconds):
    p.label("Holding Space")
    p.space_down()
    time.sleep(seconds)


def release(p):
    p.space_up()
    p.label("")


def tap(p, label, fn, after=.5):
    p.label(label)
    fn()
    time.sleep(.3)
    p.label("")
    time.sleep(after)


def deals(br, out):
    p = Page(br, "https://www.woot.com/", width=1280, height=800, scale=1)
    p.js("window.scrollTo(0,520)")
    time.sleep(.8)
    p.opt("next", "short")
    pts = p.js(CARDS)
    a, b, c = pts[0], pts[1], pts[2]
    p.cursor_on()
    p.move(a["x"] - 200, a["y"] - 60, steps=2, dur=.05)
    p.record_start()
    time.sleep(.7)
    p.move(a["x"], a["y"], dur=.5)
    time.sleep(.25)
    hold(p, 1.0)                                     # "this..."
    p.move(b["x"], b["y"], dur=.45)
    time.sleep(.9)                                   # "...or this"
    release(p)
    time.sleep(1.1)
    p.opt("next", "mid")
    p.move(c["x"], c["y"], dur=.45)
    time.sleep(.2)
    hold(p, .9)
    release(p)                                       # a second question, queued
    p.wait(lambda: p.state()["open"], 9)
    p.wait(lambda: p.state()["items"][0]["status"][0] == "done", 10)
    p.wait(lambda: p.state()["items"][1]["status"][0] in ("streaming", "done"), 9)
    time.sleep(1.2)
    tap(p, "↓", lambda: p.arrow(True), 2.4)           # next answer
    p.wait(lambda: p.state()["items"][1]["status"][0] == "done", 9)
    time.sleep(.5)
    st = p.state()
    p.move(60, 420, dur=.3)
    for _ in range(6):
        p.wheel(180)
        time.sleep(.05)
    time.sleep(.9)
    st = p.state()
    p.click(st["card"]["x"] + 170, st["card"]["y"] + 46)  # back to it, lit again
    time.sleep(1.7)
    st = p.state()
    p.move(st["card"]["x"] + 170, st["card"]["y"] + 46, dur=.15)
    time.sleep(.5)                                   # hover: plain words
    hold(p, 1.1)                                     # follow-up
    release(p)
    p.wait(lambda: p.state()["items"][1]["status"][-1] == "done", 12)
    time.sleep(1.6)
    p.record_stop(out / "1-deals.mp4")
    p.close()


def soft(br, out):
    p = Page(br, "https://news.ycombinator.com/", width=1280, height=800, scale=1)
    p.opt("soft", "soft")
    p.opt("next", "short")
    a, b = p.find(".titleline > a", 3), p.find(".titleline > a", 13)
    p.cursor_on()
    p.move(a["x"], a["y"], steps=2, dur=.05)
    p.record_start()
    time.sleep(.5)
    hold(p, 1.2)
    p.move(b["x"], b["y"], dur=.6)
    time.sleep(1.2)
    release(p)
    p.wait(lambda: p.state()["open"], 9)
    p.wait(lambda: p.state()["items"][0]["status"][0] == "done", 10)
    time.sleep(1.5)
    p.record_stop(out / "2-soft.mp4")
    p.opt("soft", "exact")
    p.close()


def dark(br, out):
    p = Page(br, "https://github.com/astral-sh/ruff", width=1280, height=800, scale=1)
    p.opt("next", "long")
    a = p.find("table a", 8)
    p.cursor_on()
    p.move(a["x"], a["y"], steps=2, dur=.05)
    p.record_start()
    time.sleep(.5)
    hold(p, 1.0)
    release(p)
    p.wait(lambda: p.state()["open"], 9)
    p.wait(lambda: p.state()["items"][0]["status"][0] == "done", 22)
    time.sleep(1.0)
    p.press("Escape", "Escape", 27)
    p.opt("next", "error")
    b = p.find("table a", 20)
    p.move(b["x"], b["y"], dur=.4)
    time.sleep(.2)
    hold(p, .8)
    release(p)
    p.wait(lambda: p.state()["open"], 9)
    time.sleep(1.8)
    p.record_stop(out / "3-dark.mp4")
    p.opt("next", "cycle")
    p.close()


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    br = Browser(int(sys.argv[2]) if len(sys.argv) > 2 else 9333)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        deals(br, tmp)
        soft(br, tmp)
        dark(br, tmp)
        parts = sorted(tmp.glob("*.mp4"))
        (tmp / "list.txt").write_text("".join(f"file '{f}'\n" for f in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-c", "copy", str(out / "flow.mp4")], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out / "flow.mp4"), "-vf",
                        "fps=15,scale=900:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=220:stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle",
                        str(out / "flow.gif")], check=True)


if __name__ == "__main__":
    main()
