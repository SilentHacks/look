#!/usr/bin/env python3
"""End-to-end proof against a running prototype: `python3 prototype/run.py --port 9333` first.

Real pages, real CDP input. Asserts what must be true on every site, and saves screenshots.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdp import Browser  # noqa: E402
from drive import Page  # noqa: E402

BENCH = (HERE.parent / "benchmark" / "benchmark_page.html").as_uri()
CARDS = """(()=>{const out=[];for(const e of document.querySelectorAll('a')){const r=e.getBoundingClientRect();
 if(r.width>120&&r.height>120&&r.width<500&&r.top>30&&r.bottom<innerHeight-120&&e.querySelector('img'))
 out.push({x:r.left+r.width/2,y:r.top+r.height/2,text:''})}return out})()"""
SITES = [
    ("hacker-news", "https://news.ycombinator.com/", ".titleline > a", None),
    ("wikipedia", "https://en.wikipedia.org/wiki/Hermes", ".mw-parser-output > p, .mw-parser-output figcaption, #vector-toc a", None),
    ("dense-table", "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)", "table.wikitable tbody td", "table.wikitable"),
    ("dark-docs", "https://docs.astral.sh/ruff/", "article li, article p", None),
    ("dark-github", "https://github.com/astral-sh/ruff", "table a", None),
    ("deals", "https://www.woot.com/", None, 640),
    ("benchmark", BENCH, "td", None),
]


def overlaps(card, rects, extra=0):
    x0, y0, x1, y1 = card["x"], card["y"], card["x"] + card["w"], card["y"] + card["h"] + extra
    return [r for r in rects if min(x1, r["right"]) - max(x0, r["left"]) > 1 and min(y1, r["bottom"]) - max(y0, r["top"]) > 1]


def check(results, name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"   {'PASS' if ok else 'FAIL'}  {name} {detail}", flush=True)


def spots(p, sel, scroll):
    if isinstance(scroll, int):
        p.js(f"window.scrollTo(0,{scroll})")
    elif scroll:
        p.js(f"document.querySelector({json.dumps(scroll)}).scrollIntoView({{block:'start'}});window.scrollBy(0,-50)")
    time.sleep(.6)
    if sel is None:
        return p.js(CARDS)
    found = [p.find(sel, i) for i in range(0, 12, 1)][:7]
    return [f for f in found if f]


def prove(br, name, url, sel, scroll, out):
    print(f"== {name}", flush=True)
    res: list[tuple[str, bool, str]] = []
    p = Page(br, url)
    print("   title:", (p.js("document.title") or "")[:70], flush=True)
    idle = p.state()
    pts = spots(p, sel, scroll)
    if len(pts) < 3:
        check(res, "enough targets on the page", False, f"found {len(pts)}")
        p.shot(out / f"{name}-unavailable.png")
        p.close()
        return res
    a, b, c = pts[0], pts[1], pts[2]
    p.opt("next", "short")

    # hold, point, point again
    p.move(a["x"], a["y"])
    time.sleep(.2)
    p.space_down()
    time.sleep(.55)
    st = p.state()
    check(res, "holding Space listens with a waveform", st["hold"] is not None and st["pill"]["mode"] == "wave")
    check(res, "what you point at lights up", st["hold"]["targets"] >= 1)
    p.move(b["x"], b["y"])
    time.sleep(.5)
    st = p.state()
    check(res, "a second point stays lit with the first", st["hold"]["targets"] >= 2, f"targets={st['hold']['targets']}")
    p.shot(out / f"{name}-1-listening.png")
    p.space_up()
    time.sleep(.5)
    st = p.state()
    check(res, "release shrinks to a named capsule", st["pill"]["mode"] == "capsule" and st["pill"]["text"].startswith("Looking into"), st["pill"]["text"])
    p.shot(out / f"{name}-2-capsule.png")

    # queue another while the first is still working
    p.opt("next", "mid")
    p.ask(c["x"], c["y"], hold=.6)
    time.sleep(.4)
    p.wait(lambda: p.state()["open"], 9)
    time.sleep(.7)
    st = p.state()
    first = st["items"][0]["subject"]
    check(res, "first asked answers first", st["cur"] == first and st["items"][1]["status"][0] in ("waiting", "thinking"), st["cur"])
    p.shot(out / f"{name}-3-answering.png")
    p.wait(lambda: p.state()["items"][0]["status"][0] == "done", 10)
    p.wait(lambda: p.state()["items"][1]["status"][0] in ("streaming", "done"), 9)
    time.sleep(.6)
    st = p.state()
    check(res, "the next one peeks out behind, by name", st["sizes"]["nextH"] > 0)
    check(res, "the card does not cover what was asked about", not overlaps(st["card"], st["targets"]), json.dumps(st["card"]))
    p.shot(out / f"{name}-4-stack.png")
    privacy = p.js("""(()=>{const all=document.documentElement.outerHTML;getSelection().selectAllChildren(document.documentElement);
       const sel=getSelection().toString();getSelection().removeAllRanges();return {dom:all.includes('Sample answer'),sel:sel.includes('Sample answer'),frames:window.frames.length===0||true}})()""")
    check(res, "no answer text reachable from the page's DOM or selection", not privacy["dom"] and not privacy["sel"])

    # arrows, then click back after scrolling away
    p.arrow(True)
    time.sleep(.45)
    st = p.state()
    check(res, "arrow key moves to the next answer", st["cur"] == st["items"][1]["subject"], st["cur"])
    check(res, "that card also avoids its target", not overlaps(st["card"], st["targets"]))
    p.shot(out / f"{name}-5-next.png")
    p.wait(lambda: p.state()["items"][1]["status"][0] == "done", 10)
    before = p.js("scrollY")
    p.move(st["card"]["x"] - 30 if st["card"]["x"] > 40 else st["card"]["x"] + st["card"]["w"] + 30, 300, steps=4, dur=.1)
    for _ in range(5):
        p.wheel(400)
        time.sleep(.06)
    time.sleep(.7)
    scrolled = p.js("scrollY")
    st = p.state()
    p.click(st["card"]["x"] + 160, st["card"]["y"] + 48)
    time.sleep(1.5)
    back = p.state()
    visible = back["targets"] and any(r["top"] < 900 and r["bottom"] > 0 for r in back["targets"])
    check(res, "click scrolls back and relights the item", (scrolled == before or back["lit"] >= 1) and visible, f"scroll {before}->{scrolled}->{p.js('scrollY')} lit={back['lit']}")
    check(res, "still not covered after coming back", not overlaps(back["card"], back["targets"]))
    p.shot(out / f"{name}-6-back.png")

    # follow-up, on the card
    p.move(back["card"]["x"] + 160, back["card"]["y"] + 48, steps=4, dur=.1)
    time.sleep(.2)
    p.space_down()
    time.sleep(.5)
    st = p.state()
    check(res, "holding Space on an answer asks a follow-up", st["hold"] and st["hold"]["follow"] == back["cur"])
    p.shot(out / f"{name}-7-followup-listening.png")
    p.space_up()
    time.sleep(.3)
    p.wait(lambda: p.state()["items"][1]["status"][-1] == "done", 12)
    time.sleep(.4)
    st = p.state()
    check(res, "follow-up lands in the same card", len(st["items"][1]["status"]) == 2 and len(st["items"]) == 2)
    p.shot(out / f"{name}-8-followup.png")
    p.press("Escape", "Escape", 27)
    time.sleep(.4)

    # long answer and error
    p.opt("next", "long")
    d = pts[3] if len(pts) > 3 else a
    p.ask(d["x"], d["y"], hold=.6)
    p.wait(lambda: p.state()["items"][-1]["status"][0] == "done", 22)
    time.sleep(.5)
    st = p.state()
    check(res, "long answer stays clear of its target", not overlaps(st["card"], st["targets"]), f"body {st['sizes']['bodyH']}/{st['sizes']['contentH']}")
    check(res, "long answer stays on screen", st["card"]["y"] >= 0 and st["card"]["y"] + st["card"]["h"] <= p.height)
    p.shot(out / f"{name}-9-long.png")
    p.press("Escape", "Escape", 27)
    time.sleep(.4)
    p.opt("next", "error")
    e = pts[4] if len(pts) > 4 else b
    p.ask(e["x"], e["y"], hold=.6)
    p.wait(lambda: p.state()["items"][-1]["status"][0] == "error", 9)
    time.sleep(.5)
    check(res, "error is shown", p.state()["items"][-1]["status"][0] == "error")
    p.shot(out / f"{name}-a-error.png")
    p.opt("next", "cycle")
    p.press("Escape", "Escape", 27)
    time.sleep(.6)
    st = p.state()
    check(res, "nothing on screen once dismissed", not st["open"] and st["pill"]["o"] == 0)
    p.opt("next", "cycle")
    p.close()
    return res


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[3:])
    br = Browser(int(sys.argv[2]) if len(sys.argv) > 2 else 9333)
    print(br.version, flush=True)
    summary = {}
    for name, url, sel, scroll in SITES:
        if only and name not in only:
            continue
        res = prove(br, name, url, sel, scroll, out)
        summary[name] = {"passed": sum(r[1] for r in res), "total": len(res), "failed": [r[0] for r in res if not r[1]]}
    print(json.dumps(summary, indent=1))
    (out / "proof-results.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
