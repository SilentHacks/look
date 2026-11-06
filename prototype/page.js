// Main-frame isolated world, injected over CDP like browser/overlay.js.
// Owns input, pointing, placement, motion and geometry. The website's closed shadow tree gets
// geometry only (rings, glass plates, waveform bars). All words are pushed to sandbox frames.
(function () {
  if (window.top !== window.self || window.__HG_PROTO__) return;
  const send = m => { try { window.__hgProto(JSON.stringify(m)); } catch (_) {} };

  // ---------- tuning ----------
  const CARD_W = 348, PILL_H = 36, RETREAT_MS = 12000, ARM_MS = 130, DWELL_MS = 170, MAX_TARGETS = 5;
  const REGION_W = 360, REGION_H = 225, MARGIN = 14;
  const SPRING = {k: 420, c: 36};        // general: quick, barely overshoots
  const SNAPPY = {k: 620, c: 40};        // rings
  const FOLLOW = {k: 300, c: 28};        // waveform trailing the cursor
  const GAZE = {k: 60, c: 15};           // soft region: slow, heavy, like smoothed gaze

  // ---------- samples, plainly sample ----------
  const Q1 = ['What’s the catch with this?', 'Is this worth my time?', 'Explain this to me.', 'What should I know about this?', 'How does this compare?'];
  const Q2 = ['Which of these is better?', 'How do these two differ?'];
  const QF = ['And what would you pick instead?', 'Why does that matter?', 'Is there a cheaper option?'];
  const shortAnswer = s => `Sample answer about “${s}”. The real one reads what’s on this page and tells you in a couple of plain sentences, right here beside it.`;
  const midAnswer = s => `Sample answer about “${s}”. Answers finish in the order you asked, so this one waited for the one before it.\n\nPress the down arrow, or click the name below, to move through the rest of the stack.`;
  const longAnswer = s => `Sample of a long answer about “${s}”. Nothing here is real yet; it is here to show how length behaves.\n\nThe card grows into free space on the page, and stops before it would reach the thing you asked about. When there’s no room left it keeps its size and scrolls inside itself, so the page beneath it never moves.\n\nThe bottom edge fades to show there is more. Scroll with the trackpad and the answer stays where you left it, even while new words are arriving.\n\nA real answer to a broad question might run about this long: a short verdict first, a paragraph of reasoning, then a caveat worth knowing before you act on it.\n\nOnly after you’ve had time to read does it retreat. Hovering over it holds it in place for as long as you like.`;
  const followAnswer = s => `Sample follow-up. Hermes still knows you mean “${s}”, so you can just keep talking without pointing again.`;
  const FAIL = 'Hermes couldn’t finish this answer.';

  // ---------- state ----------
  const S = {
    pointer: {x: null, y: null, moved: 0, at: 0},
    soft: false, solid: false, reduceForce: null, next: 'cycle', asked: 0,
    keyDown: false, armTimer: 0, hold: null,
    items: [], cur: -1, open: false, pos: null, cap: null, hoverCard: false, retreatTimer: 0, retreatAt: 0,
    queue: [], active: null, ids: 0,
    sizes: {prevH: 0, cardH: 0, nextH: 0, contentH: 0, bodyH: 0}, maxBody: 420, dark: false, dir: null, reading: null,
    coach: {heard: false, answered: 0, retreated: false}, sheet: false, ringsWanted: false,
  };
  const reduced = () => S.reduceForce ?? matchMedia('(prefers-reduced-motion: reduce)').matches;
  const reducedTransparency = () => S.solid || matchMedia('(prefers-reduced-transparency: reduce)').matches;

  // ---------- springs ----------
  const springs = new Set();
  class Spring {
    constructor(v, p = SPRING) { this.x = this.t = v; this.v = 0; this.k = p.k; this.c = p.c; }
    to(t) { if (reduced()) this.snap(t); else { this.t = t; springs.add(this); wake(); } return this; }
    snap(t) { this.x = this.t = t; this.v = 0; springs.delete(this); wake(); return this; }
    kick(v) { if (!reduced()) { this.v += v; springs.add(this); wake(); } }
    step(dt) {
      for (let i = 0; i < 4; i++) {
        this.v += (-this.k * (this.x - this.t) - this.c * this.v) * dt / 4;
        this.x += this.v * dt / 4;
      }
      if (Math.abs(this.x - this.t) < .02 && Math.abs(this.v) < .3) { this.x = this.t; this.v = 0; springs.delete(this); }
    }
  }
  // Opacity on a calmer curve, so reduced motion still gets a crossfade rather than a jump.
  class Fade {
    constructor(v) { this.x = this.t = v; }
    to(t) { this.t = t; if (this.x !== t) { fades.add(this); wake(); } return this; }
    snap(t) { this.x = this.t = t; fades.delete(this); wake(); return this; }
    step(dt) {
      const d = this.t - this.x, r = dt / (reduced() ? .16 : .11);
      if (Math.abs(d) < .004) { this.x = this.t; fades.delete(this); } else this.x += d * Math.min(1, r);
    }
  }
  const fades = new Set();
  const box = (x, y, w, h, p) => ({x: new Spring(x, p), y: new Spring(y, p), w: new Spring(w, p), h: new Spring(h, p), o: new Fade(0)});

  // ---------- geometry-only DOM ----------
  let host, shadow, rings, canvas, ctx, pillEl, pillFrameWrap, cardWrap, sheetWrap;
  const frames = {};
  const plates = [];      // [prev, next2, next, front]
  const P = {pill: box(0, 0, 0, PILL_H), pm: new Spring(0, {k: 280, c: 30})}; // pm: 0 waveform, 1 capsule
  const front = box(0, 0, CARD_W, 0), prev = box(0, 0, CARD_W, 0), next = box(0, 0, CARD_W, 0), next2 = box(0, 0, CARD_W, 0);
  const lift = new Spring(0, {k: 500, c: 30}); // nudge when you hit the end of the stack

  const CSS = `
    * { box-sizing:border-box; }
    .ring { position:fixed; left:0; top:0; pointer-events:none; will-change:transform,width,height; border-radius:9px;
      background:rgba(var(--a),var(--fill)); box-shadow:0 0 0 var(--stroke) rgba(var(--a),var(--edge)), 0 0 0 calc(var(--stroke) + 4px) rgba(var(--a),var(--halo)); }
    .ring.region { border-radius:50%; box-shadow:none; background:radial-gradient(closest-side, rgba(var(--a),calc(var(--fill)*3.2)) 0%, rgba(var(--a),calc(var(--fill)*2.6)) 45%, rgba(var(--a),calc(var(--fill)*.8)) 78%, rgba(var(--a),0) 100%); }
    .plate { position:fixed; left:0; top:0; pointer-events:none; will-change:transform,width,height,opacity;
      background:var(--fill); -webkit-backdrop-filter:var(--blur); backdrop-filter:var(--blur); box-shadow:var(--shadow); }
    .plate.sliver { background:var(--fill-2); box-shadow:var(--shadow-2); }
    .light { --fill:rgba(250,250,252,.8); --fill-2:rgba(247,247,250,.68); --blur:blur(34px) saturate(1.9);
      --shadow:0 0 0 .5px rgba(0,0,0,.13), 0 12px 36px rgba(0,0,0,.17), 0 3px 8px rgba(0,0,0,.07), inset 0 .5px 0 rgba(255,255,255,.75);
      --shadow-2:0 0 0 .5px rgba(0,0,0,.11), 0 8px 22px rgba(0,0,0,.11), inset 0 .5px 0 rgba(255,255,255,.6); --bar:rgba(0,102,214,1); }
    .dark { --fill:rgba(40,40,44,.76); --fill-2:rgba(50,50,54,.66); --blur:blur(34px) saturate(1.7);
      --shadow:0 0 0 .5px rgba(255,255,255,.15), 0 14px 44px rgba(0,0,0,.55), 0 3px 8px rgba(0,0,0,.3), inset 0 .5px 0 rgba(255,255,255,.1);
      --shadow-2:0 0 0 .5px rgba(255,255,255,.12), 0 8px 24px rgba(0,0,0,.4), inset 0 .5px 0 rgba(255,255,255,.08); --bar:rgba(95,172,255,1); }
    .solid.light { --fill:rgb(250,250,252); --fill-2:rgb(240,240,243); --blur:none; }
    .solid.dark { --fill:rgb(44,44,47); --fill-2:rgb(58,58,62); --blur:none; }
    .wrap { position:fixed; left:0; top:0; overflow:hidden; will-change:transform,width,height,opacity; }
    iframe { display:block; border:0; background:transparent; color-scheme:normal; }
    canvas { position:absolute; left:0; top:0; pointer-events:none; }
    #pill { overflow:hidden; }
  `;

  function el(tag, cls, parent) { const n = document.createElement(tag); if (cls) n.className = cls; parent.append(n); return n; }
  function frame(name, parent, w, h) {
    const f = document.createElement('iframe');
    f.setAttribute('sandbox', '');
    f.setAttribute('aria-label', 'Hermes private surface');
    f.style.width = `${w}px`; f.style.height = `${h}px`;
    parent.append(f);
    frames[name] = f;
    return f;
  }

  function boot() {
    if (host) return;
    host = document.createElement('div');
    host.setAttribute('popover', 'manual');
    host.style.cssText = 'all:initial!important;position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;margin:0!important;padding:0!important;border:0!important;pointer-events:none!important;background:transparent!important;overflow:visible!important;contain:none!important';
    document.documentElement.appendChild(host);
    host.showPopover();
    shadow = host.attachShadow({mode: 'closed'});
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(CSS);
    shadow.adoptedStyleSheets = [sheet];
    rings = el('div', '', shadow);
    for (let i = 0; i < 4; i++) {
      const p = el('div', 'plate light' + (i < 3 ? ' sliver' : ''), shadow);
      p.style.opacity = 0;
      plates.push(p);
    }
    cardWrap = el('div', 'wrap', shadow);
    cardWrap.style.opacity = 0; cardWrap.style.pointerEvents = 'none';
    frame('card', cardWrap, CARD_W, 900);
    pillEl = el('div', 'plate light', shadow);
    pillEl.id = 'pill';
    pillEl.style.opacity = 0;
    canvas = el('canvas', '', pillEl);
    ctx = canvas.getContext('2d');
    pillFrameWrap = el('div', 'wrap', pillEl);
    pillFrameWrap.style.pointerEvents = 'none';
    frame('pill', pillFrameWrap, 420, PILL_H);
    pillFrameWrap.firstChild.style.pointerEvents = 'none';
    sheetWrap = el('div', 'wrap', shadow);
    sheetWrap.style.cssText += ';border-radius:16px;display:none';
    frame('sheet', sheetWrap, 330, 420);
    S.ready = false;
    send({t: 'boot', url: location.href, frames: ['card', 'pill', 'sheet']});
  }

  function raise() { // A website dialog opened after us would otherwise sit on top.
    try { host.hidePopover(); host.showPopover(); } catch (_) {}
  }

  // ---------- page tone ----------
  function luminance(c) {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const [r, g, b, a = 1] = m[1].split(/[ ,/]+/).map(Number);
    if (a < .5) return null;
    return (.2126 * r + .7152 * g + .0722 * b) / 255;
  }
  function darkAt(x0, y0, w, h) {
    let dark = 0, light = 0;
    for (const fx of [.15, .5, .85]) for (const fy of [.15, .5, .85]) {
      const stack = document.elementsFromPoint(x0 + w * fx, y0 + h * fy);
      for (const n of stack) {
        const l = luminance(getComputedStyle(n).backgroundColor);
        if (l != null) { l < .42 ? dark++ : light++; break; }
      }
    }
    if (!dark && !light) {
      // Transparent all the way down: trust the root, then the page's own scheme.
      const l = luminance(getComputedStyle(document.documentElement).backgroundColor) ?? luminance(getComputedStyle(document.body).backgroundColor);
      return l != null ? l < .42 : getComputedStyle(document.documentElement).colorScheme.startsWith('dark');
    }
    return dark > light;
  }
  function setTone(dark) {
    S.dark = dark;
    const cls = (dark ? ' dark' : ' light') + (reducedTransparency() ? ' solid' : '');
    plates.forEach((p, i) => { p.className = 'plate' + (i < 3 ? ' sliver' : '') + cls; });
    pillEl.className = 'plate' + cls;
    sheetWrap.className = 'wrap plate' + cls; sheetWrap.style.pointerEvents = 'auto';
  }

  // ---------- pointing ----------
  const SEMANTIC = 'img,video,canvas,svg,picture,button,a,input,select,textarea,label,td,th,li,h1,h2,h3,h4,h5,h6,p,blockquote,figcaption,pre,summary,dt,dd,[role=button],[role=link],[role=row],[role=cell],[role=listitem]';
  const CARDLIKE = 'article,[class*="card" i],[class*="deal" i],[class*="product" i],[class*="listing" i],[class*="result" i],[role=listitem]';
  const ours = n => !n || n === host || n === document.documentElement || n === document.body;

  function pickElement(x, y) {
    let start = document.elementFromPoint(x, y);
    if (ours(start)) return null;
    const vw = innerWidth, vh = innerHeight;
    let n = start.closest(SEMANTIC) || start;
    if (ours(n)) return null;
    const area = r => r.width * r.height;
    // Whole-column links and giant list items: step down to the thing actually under the cursor.
    if (area(n.getBoundingClientRect()) > vw * vh * .45) n = start;
    if (area(n.getBoundingClientRect()) > vw * vh * .55) return null;
    // A compact card reads better as one thing than as its image or title alone.
    let up = n.parentElement, hops = 0;
    while (up && hops++ < 5 && !ours(up)) {
      if (up.matches(CARDLIKE) && !up.matches('td,th')) {
        const r = up.getBoundingClientRect();
        if (area(r) < vw * vh * .22 && r.width < vw * .6 && up.querySelector('img,picture') && up.textContent.trim().length > 8) return up;
      }
      up = up.parentElement;
    }
    return n;
  }

  const clean = t => (t || '').replace(/\[[^\]]{1,8}\]/g, '').replace(/\s+/g, ' ').trim(); // minus footnote marks
  function ownText(n) {
    if (n.matches('input,select,textarea')) return clean(n.getAttribute('aria-label') || n.placeholder || n.name || ''); // never .value
    if (n.matches('img,picture,video,svg,canvas')) return clean(n.getAttribute('alt') || n.querySelector?.('img')?.alt || n.getAttribute('aria-label') || n.title || '');
    if (n.matches('p,blockquote,dd,figcaption,pre')) {
      const lead = n.querySelector('b,strong');
      const opening = clean(n.innerText);
      return lead && opening.startsWith(clean(lead.innerText)) ? clean(lead.innerText) : opening;
    }
    const titled = n.matches('a,h1,h2,h3,h4,h5,h6,button') ? n : n.querySelector('h1,h2,h3,h4,[class*="title" i] a,[class*="title" i],a[title],a');
    const raw = (titled || n).innerText || (titled || n).textContent || '';
    // A deal card opens with its price; the name is the first line made of words.
    const words = raw.split('\n').map(clean).find(l => /\p{L}{3,}/u.test(l));
    return words || clean(raw) || clean(n.getAttribute('aria-label') || n.title || '');
  }
  function clip(t, max = 30) {
    t = t.replace(/^[\d.,#)\s]+(?=\D)/, '').replace(/[.,:;–—-]+$/, '');
    if (t.length <= max) return t;
    const cut = t.slice(0, max);
    const sp = cut.lastIndexOf(' ');
    return (sp > 5 ? cut.slice(0, sp) : cut).replace(/[.,:;–—-]+$/, '') + '…';
  }
  // Old sites lay out whole pages with tables. Only a real data table has rows and columns to name.
  const dataTable = t => t && t.getAttribute('role') !== 'presentation' && !!(t.tHead || t.querySelector('th')) && t.rows.length > 1;
  function nameOf(n) {
    const cell = n.closest?.('td,th');
    if (cell && dataTable(cell.closest('table'))) {
      const row = cell.closest('tr'), table = cell.closest('table');
      const first = row?.cells?.[0];
      const label = clean(row?.querySelector('th')?.innerText || first?.innerText);
      if (cell === first || (cell.tagName === 'TH' && row?.querySelector('th') === cell)) return {short: clip(label || ownText(n)), base: label, full: clean(n.innerText)};
      const col = cell.cellIndex;
      const headRow = table?.tHead?.rows?.[0] || table?.rows?.[0];
      let header = headRow && headRow !== row ? clean(headRow.cells[col]?.innerText) : '';
      header = header.replace(/\s*\([^)]*\)\s*$/, '');
      if (header.length > 4 && header === header.toUpperCase()) header = header[0] + header.slice(1).toLowerCase();
      const short = [clip(label, 20), clip(header, 14)].filter(Boolean).join(' · ');
      if (short) return {short, base: label, col: clip(header, 14), full: `${label}${header ? `, ${header}` : ''}: ${clean(cell.innerText)}`};
    }
    const t = ownText(n);
    return t ? {short: clip(t), full: t.length > 120 ? t.slice(0, 120).trim() + '…' : t} : {short: 'This part of the page', full: 'this part of the page'};
  }

  // Thin anchor so a soft region survives scrolling and inner scrollers.
  function regionAt(cx, cy) {
    const anchor = pickElement(cx, cy) || document.elementFromPoint(cx, cy);
    const r = anchor?.getBoundingClientRect?.();
    return {soft: true, anchor, dx: r ? cx - r.left : cx + scrollX, dy: r ? cy - r.top : cy + scrollY, cx, cy};
  }
  function targetRect(t) {
    if (t.soft) {
      let cx, cy;
      if (t.anchor?.isConnected) { const r = t.anchor.getBoundingClientRect(); cx = r.left + t.dx; cy = r.top + t.dy; }
      else { cx = t.cx - scrollX; cy = t.cy - scrollY; }
      return {left: cx - REGION_W / 2, top: cy - REGION_H / 2, right: cx + REGION_W / 2, bottom: cy + REGION_H / 2, width: REGION_W, height: REGION_H};
    }
    if (t.el?.isConnected) return t.el.getBoundingClientRect();
    return null;
  }

  // ---------- rings ----------
  const lit = new Map(); // key -> {node, g:box, level, style, target}
  const RING_STYLES = {
    tentative: {fill: .06, edge: .45, halo: .0, stroke: 1.5},
    live:      {fill: .1, edge: 1,   halo: .16, stroke: 1.75},
    answer:    {fill: .08, edge: .9,  halo: .14, stroke: 1.5},
    relit:     {fill: .16, edge: 1,   halo: .32, stroke: 2.5},
  };
  function ringFor(key, target, style) {
    let r = lit.get(key);
    if (!r) {
      const node = el('div', 'ring' + (target.soft ? ' region' : ''), rings);
      const rect = targetRect(target) || {left: 0, top: 0, width: 0, height: 0};
      const grow = reduced() || target.soft ? 0 : 16;
      const pad = ringPad(rect);
      r = {node, target, key, g: box(rect.left - pad - grow, rect.top - pad - grow, rect.width + 2 * (pad + grow), rect.height + 2 * (pad + grow), SNAPPY), style};
      r.g.o.snap(0);
      lit.set(key, r);
    }
    r.style = style; r.dying = false; r.fly = null;
    r.g.x.k = r.g.y.k = r.g.w.k = r.g.h.k = SNAPPY.k;
    r.g.x.c = r.g.y.c = r.g.w.c = r.g.h.c = SNAPPY.c;
    r.g.o.to(1);
    wake();
    return r;
  }
  function ringPad(rect) { return rect.height > 120 ? 6 : rect.height < 26 ? 2 : 3; }
  function dropRing(key) { const r = lit.get(key); if (r) { r.dying = true; r.g.o.to(0); wake(); } }
  function dropAllRings(except) { for (const [k] of lit) if (k !== except) dropRing(k); }
  function drawRings(level) {
    const vw = innerWidth, vh = innerHeight;
    for (const [key, r] of lit) {
      const rect = targetRect(r.target);
      if (!rect) { dropRing(key); }
      else {
        const pad = r.target.soft ? 0 : ringPad(rect);
        let x = rect.left - pad, y = rect.top - pad, w = rect.width + 2 * pad, h = rect.height + 2 * pad;
        if (!r.target.soft) {
          // Off-screen: squash into a glow on the edge it went past, so it's still visibly held.
          if (y + h < 2) { w = Math.min(w, 140); x = Math.max(8, Math.min(vw - w - 8, x)); y = 3; h = 4; }
          else if (y > vh - 2) { w = Math.min(w, 140); x = Math.max(8, Math.min(vw - w - 8, x)); y = vh - 7; h = 4; }
        }
        if (r.fly) { x = r.fly.x(); y = r.fly.y(); w = 20; h = 10; }
        r.g.x.to(x); r.g.y.to(y); r.g.w.to(w); r.g.h.to(h);
        // Track scroll exactly; the spring is only for arrival and for moving between states.
        if (r.seen && !r.fly && (S.scrollingAt && performance.now() - S.scrollingAt < 140)) { r.g.x.snap(x); r.g.y.snap(y); r.g.w.snap(w); r.g.h.snap(h); }
        r.seen = true;
      }
      const st = RING_STYLES[r.style] || RING_STYLES.live;
      const breathe = r.style === 'live' ? level : 0;
      const n = r.node.style;
      n.setProperty('--a', S.dark ? '95,172,255' : '0,122,255');
      n.setProperty('--fill', (st.fill + breathe * .05).toFixed(3));
      n.setProperty('--edge', st.edge.toFixed(3));
      n.setProperty('--halo', (st.halo + breathe * .22).toFixed(3));
      n.setProperty('--stroke', `${st.stroke}px`);
      n.transform = `translate3d(${r.g.x.x}px,${r.g.y.x}px,0)`;
      n.width = `${Math.max(0, r.g.w.x)}px`; n.height = `${Math.max(0, r.g.h.x)}px`;
      n.opacity = r.g.o.x.toFixed(3);
      if (r.dying && r.g.o.x < .01) { r.node.remove(); lit.delete(key); }
    }
  }

  // ---------- waveform ----------
  const BARS = 13, BAR_W = 2.6, BAR_GAP = 3;
  const levels = new Float32Array(BARS);
  let voice = 0, voiceTarget = 0, syllable = 0, phase = 0;
  function waveLevel(dt, now) {
    // A simulated voice: syllable bursts with pauses. Real capture would push levels here.
    syllable -= dt;
    if (syllable <= 0) {
      const pause = Math.random() < .14;
      voiceTarget = pause ? .06 : .5 + Math.random() * .5;
      syllable = pause ? .18 + Math.random() * .25 : .08 + Math.random() * .16;
    }
    voice += (voiceTarget - voice) * Math.min(1, dt * 16);
    phase += dt * 7;
    if (reduced()) voice = Math.min(voice, .4);
    for (let i = 0; i < BARS; i++) {
      const c = 1 - Math.abs(i - (BARS - 1) / 2) / ((BARS - 1) / 2);
      const wob = .55 + .45 * Math.sin(phase + i * 1.15 + Math.sin(phase * .37 + i) * 1.4);
      const want = voice * (.38 + .62 * c) * wob;
      levels[i] += (want - levels[i]) * Math.min(1, dt * 26);
    }
    return voice;
  }
  function drawPill(now) {
    const w = P.pill.w.x, h = P.pill.h.x, m = Math.max(0, Math.min(1, P.pm.x));
    const dpr = devicePixelRatio || 1;
    const cw = Math.ceil(Math.max(w, 1)), ch = Math.ceil(Math.max(h, 1));
    if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
      canvas.width = cw * dpr; canvas.height = ch * dpr; canvas.style.width = `${cw}px`; canvas.style.height = `${ch}px`;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    ctx.fillStyle = S.dark ? '#5facff' : '#0a6fe0';
    const cy = h / 2;
    const waveW = BARS * BAR_W + (BARS - 1) * BAR_GAP;
    const wx0 = S.hold?.follow ? 13 : (w - waveW) / 2;
    // In the capsule, three of the bars become a small working pulse at the left.
    const dotX = [14, 20, 26];
    for (let i = 0; i < BARS; i++) {
      const isDot = i >= 5 && i < 8;
      const alpha = isDot ? 1 : Math.max(0, 1 - m * 2.2);
      if (alpha <= 0) continue;
      const bx = wx0 + i * (BAR_W + BAR_GAP);
      const x = isDot ? bx + (dotX[i - 5] - bx) * m : bx + ((w / 2 - bx) * m);
      const waveH = 4 + levels[i] * (h - 14);
      const t = now / 1000;
      const dotH = reduced() ? 7 : 4.5 + 7 * (.5 + .5 * Math.sin(t * 5.2 - (i - 5) * .9));
      const hh = waveH + (dotH - waveH) * m;
      ctx.globalAlpha = alpha;
      ctx.beginPath();
      ctx.roundRect(x, cy - hh / 2, BAR_W, hh, BAR_W / 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  // ---------- free-space placement ----------
  const CELL = 26;
  function occupancy() {
    const vw = innerWidth, vh = innerHeight, cols = Math.ceil(vw / CELL), rows = Math.ceil(vh / CELL);
    const grid = new Float32Array((cols + 1) * (rows + 1)); // summed-area table
    const hit = (x, y) => {
      const n = document.elementFromPoint(x, y);
      if (!n || n === host) return 0;
      if (n.matches('img,video,canvas,svg,path,picture,input,select,textarea,button,iframe')) return 1;
      const c = document.caretRangeFromPoint?.(x, y);
      const node = c?.startContainer;
      if (node?.nodeType === 3 && node.data.trim()) {
        const rng = document.createRange();
        rng.setStart(node, Math.max(0, c.startOffset - 1));
        rng.setEnd(node, Math.min(node.length, c.startOffset + 1));
        const r = rng.getBoundingClientRect();
        if (x >= r.left - 8 && x <= r.right + 8 && y >= r.top - 5 && y <= r.bottom + 5) return 1;
      }
      const cs = getComputedStyle(n);
      if (cs.backgroundImage !== 'none' && n.getBoundingClientRect().width < vw * .5) return .7;
      return 0;
    };
    for (let r = 1; r <= rows; r++) for (let c = 1; c <= cols; c++) {
      const v = hit((c - .5) * CELL, (r - .5) * CELL);
      grid[r * (cols + 1) + c] = v + grid[(r - 1) * (cols + 1) + c] + grid[r * (cols + 1) + c - 1] - grid[(r - 1) * (cols + 1) + c - 1];
    }
    return (x, y, w, h) => {
      const c0 = Math.max(0, Math.floor(x / CELL)), c1 = Math.min(cols, Math.ceil((x + w) / CELL));
      const r0 = Math.max(0, Math.floor(y / CELL)), r1 = Math.min(rows, Math.ceil((y + h) / CELL));
      const sum = grid[r1 * (cols + 1) + c1] - grid[r0 * (cols + 1) + c1] - grid[r1 * (cols + 1) + c0] + grid[r0 * (cols + 1) + c0];
      return sum / Math.max(1, (c1 - c0) * (r1 - r0));
    };
  }
  const overlap = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  // Things you asked about must stay visible; for a table cell, so should its row and column.
  function avoidance(item) {
    const hard = [], soft = [];
    for (const t of item?.targets || []) {
      const r = targetRect(t);
      if (r && r.bottom > 0 && r.top < innerHeight) hard.push(inflate(r, 14));
      const cell = t.el?.closest?.('td,th');
      if (cell && dataTable(cell.closest('table'))) {
        const row = cell.closest('tr')?.getBoundingClientRect();
        if (row) soft.push(row);
        const table = cell.closest('table');
        const first = table?.rows?.[0]?.cells?.[cell.cellIndex]?.getBoundingClientRect?.();
        const last = table?.rows?.[table.rows.length - 1]?.cells?.[cell.cellIndex]?.getBoundingClientRect?.();
        if (first && last) soft.push({left: first.left, right: first.right, top: first.top, bottom: last.bottom});
      }
    }
    return {hard, soft};
  }
  const inflate = (r, p) => ({left: r.left - p, right: r.right + p, top: r.top - p, bottom: r.bottom + p});

  function place(item, want) {
    const vw = innerWidth, vh = innerHeight;
    const W = Math.min(CARD_W, vw - 2 * MARGIN);
    const occ = occupancy();
    const {hard, soft} = avoidance(item);
    const focus = hard[0] ? {x: (hard[0].left + hard[0].right) / 2, y: (hard[0].top + hard[0].bottom) / 2}
      : {x: S.pointer.x ?? vw * .7, y: S.pointer.y ?? vh * .3};
    const vmax = Math.max(vw, vh);
    let best = null;
    const heights = [want, Math.max(170, want * .66), 170].filter((h, i, a) => a.indexOf(h) === i && h <= vh - 2 * MARGIN);
    if (!heights.length) heights.push(vh - 2 * MARGIN);
    heights.forEach((H, hi) => {
      for (let y = MARGIN; y <= Math.max(MARGIN, vh - H - MARGIN); y += 13) {
        for (let x = MARGIN; x <= Math.max(MARGIN, vw - W - MARGIN); x += 13) {
          const rect = {left: x, top: y, right: x + W, bottom: y + H};
          let covers = 0, softCovers = 0;
          for (const r of hard) covers += overlap(rect, r);
          for (const r of soft) softCovers += overlap(rect, r);
          const frac = occ(x, y, W, H);
          const dx = Math.max(hard[0]?.left - rect.right || 0, rect.left - (hard[0]?.right ?? 1e9), 0);
          const dy = Math.max(hard[0]?.top - rect.bottom || 0, rect.top - (hard[0]?.bottom ?? 1e9), 0);
          const near = hard[0] ? Math.hypot(dx, dy) : Math.hypot(x + W / 2 - focus.x, y + H / 2 - focus.y);
          let cost = covers * 1000 + softCovers / (W * H) * 26 + frac * 60 + near / vmax * 20 + hi * 7;
          // No margins anywhere: hug an edge rather than float over the middle of the content.
          if (frac > .15) cost += Math.min(vw - rect.right, rect.left, vh - rect.bottom) / vmax * 26;
          if (hard[0]) {
            if (rect.right <= hard[0].left) cost += 2;                       // prefer right of or below
            cost += Math.abs(y - hard[0].top) / vmax * 9;                    // and lined up with it
          }
          if (S.pos) cost += Math.hypot(x - S.pos.x, y - S.pos.y) / vmax * 5; // don't wander
          if (!best || cost < best.cost) best = {x, y, H, cost, frac, covers};
        }
      }
    });
    return best;
  }

  // ---------- stack ----------
  const visible = () => S.items.filter(i => !i.archived);
  const inProgress = () => S.items.filter(i => i.turns.some(t => t.status === 'waiting' || t.status === 'thinking') && !(S.open && current() === i));
  const notYetShown = () => S.items.filter(i => i.turns[0].status === 'waiting' || i.turns[0].status === 'thinking');
  const current = () => S.items.find(i => i.id === S.cur) || null;
  function stateWord(i) {
    if (i.turns.some(t => t.status === 'error')) return 'Didn’t finish';
    if (i.turns.some(t => t.status === 'streaming')) return 'Answering';
    if (i.turns.some(t => t.status === 'thinking')) return 'Looking into it';
    if (i.turns.some(t => t.status === 'waiting')) return 'Waiting';
    return i.seen ? '' : 'Ready';
  }

  function hintFor(item) {
    if (S.coach.answered > 6) return '';
    const t = item.turns[item.turns.length - 1];
    if (t.status === 'error') return '';
    return 'Hold Space to ask more';
  }

  function pushCard() {
    const item = current();
    if (!S.open || !item) { send({t: 'panel', frame: 'card', msg: {kind: 'card', item: null, dark: S.dark}}); return; }
    const list = visible(), i = list.indexOf(item);
    const pv = list[i - 1], nx = list[i + 1];
    const peek = p => p && {subject: p.subject, state: stateWord(p)};
    send({t: 'panel', frame: 'card', msg: {
      kind: 'card', dark: S.dark, reduce: S.reduceForce, dir: S.dir, maxBody: S.maxBody,
      reading: S.reading === item.id, hint: hintFor(item),
      prev: peek(pv), next: peek(nx),
      item: {id: item.id, subject: item.subject, lost: item.lost, host: item.host,
        gone: !item.lost && item.targets.length > 0 && !item.targets.some(targetRect),
        turns: item.turns.map(t => ({id: t.id, q: t.q, a: t.shown, status: t.status, error: t.error}))},
    }});
    S.dir = null;
  }
  function pushPill(text, shimmer) {
    if (S.pillText === text && S.pillShimmer === shimmer && S.pillDark === S.dark) return;
    S.pillText = text; S.pillShimmer = shimmer; S.pillDark = S.dark;
    send({t: 'panel', frame: 'pill', msg: {kind: 'pill', text, shimmer, dark: S.dark, reduce: S.reduceForce}});
  }

  function openStack(item, dir) {
    const was = S.open;
    S.open = true;
    S.cur = item.id;
    S.dir = dir;
    item.seen = true;
    S.coach.answered++;
    const list0 = visible(), i0 = list0.indexOf(item);
    const peekAbove = i0 > 0 ? 30 : 0, peekBelow = i0 < list0.length - 1 ? 30 : 0;
    const want = estimateH(item) + peekAbove + peekBelow;
    const needMove = !S.pos || coversTargets(item, {x: S.pos.x, y: S.pos.y - peekAbove}, want);
    if (!was || needMove) {
      const spot = place(item, want);
      S.pos = {x: spot.x, y: spot.y + peekAbove};
      S.placedH = spot.H;
      setTone(darkAt(spot.x, spot.y, Math.min(CARD_W, innerWidth), Math.min(want, 300)));
    }
    S.maxBody = maxBodyFor(item);
    if (!was) {
      const p = P.pill;
      if (!S.hold && pillVisible() && !inProgress().length) {
        // The capsule becomes the card: same plate, new shape.
        front.x.snap(p.x.x); front.y.snap(p.y.x); front.w.snap(p.w.x); front.h.snap(p.h.x); S.morphR = PILL_H / 2;
        front.o.snap(1);
        hidePill(true);
      } else {
        front.x.snap(S.pos.x + 8); front.y.snap(S.pos.y + 12); front.w.snap(Math.min(CARD_W, innerWidth - 2 * MARGIN) - 16); front.h.snap(40); S.morphR = 18;
        front.o.snap(0);
      }
      next.x.snap(S.pos.x + 8); next.y.snap(S.pos.y + 20); next.w.snap(CARD_W - 16); next.h.snap(30); next.o.snap(0);
      next2.x.snap(S.pos.x + 18); next2.y.snap(S.pos.y + 20); next2.w.snap(CARD_W - 36); next2.h.snap(30); next2.o.snap(0);
      prev.x.snap(S.pos.x + 8); prev.y.snap(S.pos.y); prev.w.snap(CARD_W - 16); prev.h.snap(30); prev.o.snap(0);
      S.cardFade = 0;
      raise();
    }
    lightCurrent(item, 'answer');
    pushCard();
    armRetreat();
    layout();
  }
  function estimateH(item) {
    const words = item.turns.reduce((n, t) => n + (t.a?.length || 0), 0);
    const lines = Math.ceil(words / 48);
    return Math.min(innerHeight - 2 * MARGIN, 96 + lines * 19.3);
  }
  function coversTargets(item, pos, h) {
    const W = Math.min(CARD_W, innerWidth - 2 * MARGIN);
    const rect = {left: pos.x, top: pos.y, right: pos.x + W, bottom: pos.y + h};
    return avoidance(item).hard.some(r => overlap(rect, r) > 0);
  }
  function maxBodyFor(item) {
    const chrome = 54 + (S.sizes.prevH || 0) + (S.sizes.nextH || 0);
    let limit = innerHeight - MARGIN - (S.pos?.y ?? MARGIN) - chrome;
    const {hard} = avoidance(item);
    const W = Math.min(CARD_W, innerWidth - 2 * MARGIN);
    // Stop growing before reaching what you asked about.
    for (const r of hard) {
      if (S.pos && r.left < S.pos.x + W && r.right > S.pos.x && r.top > S.pos.y) limit = Math.min(limit, r.top - S.pos.y - chrome - 8);
    }
    return Math.max(70, limit);
  }
  function lightCurrent(item, style) {
    const keep = new Set();
    for (const t of item?.targets || []) { keep.add(t.key); ringFor(t.key, t, style); }
    for (const [k] of lit) if (!keep.has(k) && !(S.hold?.targets || []).some(t => t.key === k)) dropRing(k);
  }

  function layout() {
    const item = current();
    if (!S.open || !item) return;
    const W = Math.min(CARD_W, innerWidth - 2 * MARGIN);
    const {prevH, cardH, nextH} = S.sizes;
    const h = Math.max(cardH, 64);
    const pos = S.pos;
    // Long answer keeps growing: slide up if that's possible without covering the target.
    const total = h + nextH;
    let y = pos.y;
    const over = y + total - (innerHeight - MARGIN);
    if (over > 0) {
      const ny = Math.max(MARGIN + prevH, y - over);
      if (!coversTargets(item, {x: pos.x, y: ny}, total)) { y = ny; S.pos.y = y; }
    }
    if (prevH && y - prevH < MARGIN) { y = MARGIN + prevH; S.pos.y = y; }
    const list = visible(), i = list.indexOf(item);
    front.x.to(pos.x); front.y.to(y); front.w.to(W); front.h.to(h); front.o.to(1);
    const showPrev = i > 0 && prevH, showNext = i < list.length - 1 && nextH, showNext2 = i < list.length - 2 && nextH;
    prev.x.to(pos.x + 7); prev.w.to(W - 14); prev.h.to((prevH || 30) + 14); prev.y.to(y - (prevH || 30)); prev.o.to(showPrev ? 1 : 0);
    next.x.to(pos.x + 7); next.w.to(W - 14); next.h.to((nextH || 30) + 14); next.y.to(y + h - 14); next.o.to(showNext ? 1 : 0);
    next2.x.to(pos.x + 16); next2.w.to(W - 32); next2.h.to(24); next2.y.to(y + h + (nextH || 30) - 16); next2.o.to(showNext2 ? 1 : 0);
    S.frameY = y - (showPrev ? prevH : 0);
    S.frameH = (showPrev ? prevH : 0) + h + (showNext ? nextH : 0);
    placeCapsule();
    wake();
  }

  function closeStack(reason) {
    if (!S.open) return;
    const item = current();
    S.open = false;
    clearTimeout(S.retreatTimer);
    S.retreatAt = 0;
    S.reading = null;
    for (const i of visible()) if (i.seen && !i.turns.some(t => ['waiting', 'thinking', 'streaming'].includes(t.status))) i.archived = true;
    if (item) {
      // Retreat back toward what it was about; it's going home, not vanishing.
      const r = item.targets?.[0] && targetRect(item.targets[0]);
      if (r && !reduced() && reason === 'retreat') {
        front.x.to(front.x.t + (r.left + r.width / 2 - (front.x.t + CARD_W / 2)) * .22);
        front.y.to(front.y.t + (r.top + r.height / 2 - front.y.t) * .22);
      }
      front.w.to(front.w.t - 24); front.h.to(Math.max(40, front.h.t - 26));
    }
    for (const b of [front, prev, next, next2]) b.o.to(0);
    S.frameH = 0;
    dropAllRings();
    send({t: 'persist', state: persistable()});
    if (reason === 'retreat' && !S.coach.retreated) {
      S.coach.retreated = true;
      send({t: 'coach', coach: S.coach});
      coachLine('Press Q to bring answers back', 3600);
    } else updateCapsule();
    // Wait for the fade so words don't vanish before glass does.
    setTimeout(() => { if (!S.open) { pushCard(); S.pos = null; } }, reduced() ? 180 : 240);
  }

  function armRetreat() {
    clearTimeout(S.retreatTimer);
    S.retreatAt = 0;
    const item = current();
    if (!S.open || !item) return;
    const busy = item.turns.some(t => t.status === 'streaming' || t.status === 'thinking' || t.status === 'waiting');
    if (busy || S.hoverCard || S.hold || S.reading === item.id || S.sheet) return;
    const words = item.turns.reduce((n, t) => n + t.a.split(/\s+/).length, 0);
    const ms = Math.max(RETREAT_MS, words / 3.6 * 1000); // long answers get reading time
    S.retreatAt = performance.now() + ms;
    S.retreatTimer = setTimeout(retreatStep, ms);
  }
  function retreatStep() {
    if (document.hidden) { S.retreatTimer = setTimeout(retreatStep, 2000); return; }
    // Anything you haven't seen comes forward first, one stage at a time, so nothing gets buried.
    const list = visible(), i = list.indexOf(current());
    const nextUnseen = list.slice(i + 1).find(x => !x.seen && !['waiting', 'thinking'].includes(x.turns[0].status));
    if (nextUnseen) { go(nextUnseen, 'next'); return; }
    closeStack('retreat');
  }
  function go(item, dir) {
    const was = current();
    if (was && was !== item) was.seen = true;
    S.reading = null;
    openStack(item, dir);
    if (dir && !reduced()) lift.kick(dir === 'next' ? -420 : 420);
  }
  function step(delta) {
    const list = visible(), i = list.indexOf(current());
    const target = list[i + delta];
    if (!target) { lift.kick(delta * 260); return; } // gentle end-of-stack bump
    go(target, delta > 0 ? 'next' : 'prev');
  }
  function recall() {
    const all = S.items;
    if (!all.length) { coachLine('Nothing here yet. Point at something and hold Space', 2800); return; }
    for (const i of all) i.archived = false;
    const last = [...all].reverse().find(i => i.turns[0].status !== 'waiting' && i.turns[0].status !== 'thinking') || all[all.length - 1];
    openStack(last);
  }

  // Click an answer: back to the thing, lit again.
  function goBack(item) {
    const t = item.targets?.[0];
    if (!t || item.lost) {
      if (item.url && item.url !== location.href) location.href = item.url;
      return;
    }
    const r = targetRect(t);
    if (!r) { pushCard(); return; } // the page removed it: the card says so, we don't guess
    const inView = r.top > 40 && r.bottom < innerHeight - 40;
    if (!inView) {
      const y = scrollY + r.top + r.height / 2 - innerHeight / 2;
      t.soft ? window.scrollTo({top: y, behavior: reduced() ? 'auto' : 'smooth'})
        : t.el.scrollIntoView({block: 'center', inline: 'nearest', behavior: reduced() ? 'auto' : 'smooth'});
    }
    relight(item);
    S.settleItem = item;
    armRetreat();
  }
  function relight(item) {
    for (const t of item.targets || []) {
      const ring = ringFor(t.key, t, 'relit');
      if (!reduced() && !t.soft) { ring.g.w.kick(180); ring.g.h.kick(180); ring.g.x.kick(-90); ring.g.y.kick(-90); }
    }
    clearTimeout(S.relitTimer);
    S.relitTimer = setTimeout(() => { for (const t of item.targets || []) if (lit.get(t.key)) lit.get(t.key).style = 'answer'; }, 1100);
  }

  // ---------- capsule ----------
  function pillVisible() { return P.pill.o.t > 0; }
  function hidePill(instant) {
    P.pill.o.to(0);
    if (instant) P.pill.o.snap(0);
    pushPill('', false);
    S.pillMode = 'none';
    wake();
  }
  function capsuleText() {
    const waiting = inProgress();
    if (!waiting.length) return '';
    const things = waiting.reduce((n, i) => n + Math.max(1, i.targets.length), 0);
    if (things === 1) return `Looking into ${waiting[0].subject}`;
    return `Looking into ${things} things`;
  }
  function updateCapsule() {
    if (S.hold || S.coachTimer) return;
    const text = capsuleText();
    if (!text) { if (S.pillMode === 'capsule') hidePill(); return; }
    S.pillMode = 'capsule';
    P.pm.to(1);
    P.pill.o.to(1);
    pushPill(text, true);
    placeCapsule();
  }
  function capsuleSpot(w) {
    if (S.open && S.pos) {
      const {hard} = avoidance(current());
      const clear = (x, y) => y >= MARGIN && y + PILL_H <= innerHeight - MARGIN &&
        !hard.some(r => overlap({left: x, top: y, right: x + w, bottom: y + PILL_H}, r) > 0);
      const x = Math.min(S.pos.x + 2, innerWidth - w - MARGIN);
      const above = (S.frameY ?? S.pos.y) - PILL_H - 8, below = (S.frameY ?? S.pos.y) + S.frameH + 8;
      if (clear(x, above)) return {x, y: above};
      if (clear(x, below)) return {x, y: below};
      return {x: innerWidth - w - MARGIN, y: MARGIN};
    }
    if (S.capSpot) return {...S.capSpot, x: S.capSpot.right - w}; // keep the right edge still as the words change
    // Where notifications live, nudged off anything we can see.
    const item = S.items[S.items.length - 1];
    const {hard} = avoidance(item);
    const occ = occupancy();
    let best = null;
    const vw = innerWidth;
    for (let y = MARGIN; y < 150; y += 13) for (let x = vw - w - MARGIN; x > vw * .45; x -= 26) {
      const rect = {left: x, top: y, right: x + w, bottom: y + PILL_H};
      const cost = hard.reduce((c, r) => c + overlap(rect, r) * 100, 0) + occ(x, y, w, PILL_H) * 40 + (vw - w - MARGIN - x) / vw * 10 + y / 150 * 4;
      if (!best || cost < best.cost) best = {x, y, cost, right: x + w};
    }
    S.capSpot = best;
    setTone(darkAt(best.x, best.y, w, PILL_H));
    return best;
  }
  function placeCapsule() {
    if (S.pillMode !== 'capsule') return;
    const w = (S.pillLabelW || 120) + 34 + 14;
    const spot = capsuleSpot(w);
    P.pill.x.to(spot.x); P.pill.y.to(spot.y); P.pill.w.to(w); P.pill.h.to(PILL_H);
    wake();
  }
  function coachLine(text, ms) {
    clearTimeout(S.coachTimer);
    S.pillMode = 'coach';
    const w = text.length * 6.6 + 34;
    const vw = innerWidth;
    P.pill.x.snap(vw / 2 - w / 2); P.pill.y.snap(innerHeight - 76); P.pill.w.snap(w); P.pill.h.snap(PILL_H);
    P.pill.o.to(1); P.pm.snap(1);
    S.coachPlain = true;
    setTone(darkAt(vw / 2 - w / 2, innerHeight - 76, w, PILL_H));
    pushPill(text, false);
    S.coachTimer = setTimeout(() => {
      S.coachTimer = 0; S.coachPlain = false;
      if (S.pillMode === 'coach') { hidePill(); }
      updateCapsule();
    }, ms);
    wake();
  }

  // ---------- talking ----------
  function holdStart() {
    S.keyArmed = false;
    clearTimeout(S.retreatTimer); S.retreatAt = 0;
    if (S.coachTimer) { clearTimeout(S.coachTimer); S.coachTimer = 0; S.coachPlain = false; }
    raise();
    const item = current();
    // Pointing grammar: where you point says what it's about. Over the card, or not moved
    // since it arrived, you're still talking about the card.
    const follow = S.open && item && (S.hoverCard || (S.pointer.moved < 90)) ? item : null;
    S.hold = {started: performance.now(), targets: [], tentative: null, dwellFrom: 0, follow, region: null};
    if (!S.open) setTone(darkAt(Math.max(0, S.pointer.x - 150), Math.max(0, S.pointer.y - 100), 300, 200));
    cardWrap.style.pointerEvents = 'none'; // keep pointing through it
    S.capSpot = S.open ? S.capSpot : null;
    const {x, y} = pillAnchor();
    S.pillMode = 'wave';
    const p = P.pill;
    if (p.o.t === 0 || p.o.x < .05) { p.x.snap(x + 34); p.y.snap(y); p.w.snap(28); p.h.snap(PILL_H - 8); }
    P.pm.to(0);
    p.x.to(x); p.y.to(y); p.w.to(waveW(follow)); p.h.to(PILL_H);
    p.o.to(1);
    if (follow) {
      S.pillLabelW = 0;
      pushPill('Asking more about this', false);
    } else if (!S.coach.heard) {
      pushPill('', false);
    } else pushPill('', false);
    voice = 0; syllable = 0;
    if (S.soft) S.gaze = {x: new Spring(S.pointer.x, GAZE), y: new Spring(S.pointer.y, GAZE), stillAt: performance.now(), lockX: null, lockY: null};
    updatePointing(performance.now(), true);
    wake();
  }
  const waveW = follow => BARS * BAR_W + (BARS - 1) * BAR_GAP + 26 + (follow ? (S.pillLabelW || 150) + 8 : 0);
  function pillAnchor() {
    const vw = innerWidth, vh = innerHeight;
    const w = waveW(S.hold?.follow);
    if (S.hold?.follow && S.open) {
      // A follow-up belongs to the card: dock on its lower edge.
      const dockY = Math.min(vh - PILL_H - 10, front.y.t + front.h.t - PILL_H / 2 + 2);
      return {x: S.pos.x + (front.w.t - w) / 2, y: dockY};
    }
    const anchorX = S.soft && S.gaze ? S.gaze.x.x : S.pointer.x, anchorY = S.soft && S.gaze ? S.gaze.y.x : S.pointer.y;
    let x = anchorX + 18, y = anchorY + 22;
    if (S.soft) { x = anchorX - w / 2; y = anchorY + REGION_H / 2 - 10; }
    if (x + w > vw - 10) x = anchorX - w - 16;
    if (y + PILL_H > vh - 10) y = Math.max(10, anchorY - PILL_H - 16);
    return {x: Math.max(10, x), y: Math.max(10, y)};
  }

  function updatePointing(now, immediate) {
    const H = S.hold;
    if (!H || S.pointer.x == null) return;
    if (H.follow && (S.hoverCard || S.pointer.moved < 90)) return; // still on the card
    if (S.soft) { updateSoft(now, immediate); return; }
    const n = pickElement(S.pointer.x, S.pointer.y);
    const already = n && H.targets.find(t => t.el === n);
    if (!n || already) { dropTentative(H); return; }
    if (H.tentative?.el !== n) {
      dropTentative(H);
      const t = {el: n, key: `t${++S.ids}`};
      H.tentative = t;
      H.dwellFrom = now;
      ringFor(t.key, t, 'tentative');
    }
    if (immediate || now - H.dwellFrom >= DWELL_MS) {
      if (H.targets.length >= MAX_TARGETS) return;
      H.targets.push(H.tentative);
      const ring = lit.get(H.tentative.key);
      if (ring) ring.style = 'live';
      H.tentative = null;
    }
  }
  function dropTentative(H) { if (H.tentative) { dropRing(H.tentative.key); H.tentative = null; } }
  function updateSoft(now, immediate) {
    const H = S.hold, G = S.gaze;
    if (!G) return;
    // Simulated gaze: the pointer, plus a little slow wander, through a heavy spring.
    const t = now / 1000;
    G.x.to(S.pointer.x + (reduced() ? 0 : Math.sin(t * 1.3) * 16 + Math.sin(t * 3.1) * 6));
    G.y.to(S.pointer.y + (reduced() ? 0 : Math.sin(t * 1.7 + 1) * 11 + Math.sin(t * 2.7) * 5));
    if (!H.tentative) {
      const c = regionAt(G.x.x, G.y.x);
      c.key = `t${++S.ids}`;
      H.tentative = c;
      ringFor(c.key, c, 'live');
    }
    // The live region follows gaze; a long enough look leaves one lit behind.
    const c = H.tentative;
    const r = c.anchor?.getBoundingClientRect?.();
    c.cx = G.x.x + scrollX; c.cy = G.y.x + scrollY;
    if (r) { c.dx = G.x.x - r.left; c.dy = G.y.x - r.top; }
    const dist = Math.hypot(S.pointer.x - (G.lockX ?? S.pointer.x), S.pointer.y - (G.lockY ?? S.pointer.y));
    if (G.lockX == null || dist > 130) { G.lockX = S.pointer.x; G.lockY = S.pointer.y; G.stillAt = now; }
    const nearPin = H.targets.some(tt => {
      const r2 = targetRect(tt);
      return r2 && Math.hypot(r2.left + REGION_W / 2 - G.x.x, r2.top + REGION_H / 2 - G.y.x) < 170;
    });
    if (now - G.stillAt > 340 && !nearPin && H.targets.length < MAX_TARGETS) {
      const pinned = {...regionAt(G.x.x, G.y.x), key: `t${++S.ids}`};
      ringFor(pinned.key, pinned, 'live');
      H.targets.push(pinned);
    }
    // The moving pool gives way to a pinned one, so light never stacks up.
    lit.get(c.key)?.g.o.to(nearPin || (now - G.stillAt > 340) ? 0 : 1);
  }

  function holdEnd(cancelled) {
    const H = S.hold;
    if (!H) return;
    S.hold = null;
    cardWrap.style.pointerEvents = S.open ? 'auto' : 'none';
    // A quick look still counts: what was under the pointer at release is what you meant.
    if (H.tentative && !H.targets.length && !H.follow && !cancelled) {
      H.targets.push(H.tentative);
      H.tentative = null;
    }
    dropTentative(H);
    S.gaze = null;
    const heldFor = performance.now() - H.started;
    if (cancelled || heldFor < 220) {
      for (const t of H.targets) dropRing(t.key);
      hidePill();
      updateCapsule();
      armRetreat();
      if (S.open) lightCurrent(current(), 'answer');
      return;
    }
    S.coach.heard = true;
    if (H.follow && !H.targets.length) {
      askFollowUp(H.follow);
    } else if (H.follow) {
      askFollowUp(H.follow, H.targets);
    } else {
      askNew(H.targets);
    }
    S.pointer.moved = 0;
    send({t: 'coach', coach: S.coach});
    // What you pointed at goes into the capsule, so you can see where your question went.
    // The answer lights it again.
    setTimeout(() => {
      if (S.hold) return;
      const cur = S.open ? current() : null;
      for (const t of H.targets) {
        if (cur?.targets.includes(t)) continue;
        const ring = lit.get(t.key);
        if (ring && S.pillMode === 'capsule' && !reduced() && !t.soft) {
          ring.fly = {x: () => P.pill.x.x + 8, y: () => P.pill.y.x + 11};
          // Collapse first, then travel: a small spark, never a big box sliding over the page.
          ring.g.w.k = ring.g.h.k = 900; ring.g.w.c = ring.g.h.c = 60;
          ring.g.x.k = ring.g.y.k = 170; ring.g.x.c = ring.g.y.c = 24;
          setTimeout(() => { if (ring.fly) dropRing(t.key); }, 170);
        } else dropRing(t.key);
      }
    }, 230);
  }
  function subjectFor(targets) {
    if (!targets.length) return {short: clip(document.title || 'This page'), full: document.title || 'this page'};
    const names = targets.map(t => {
      const raw = t.soft ? nameOf(t.anchor || document.body) : nameOf(t.el);
      return t.soft ? {short: `Around ${clip(raw.short, 26)}`, base: raw.base || clip(raw.short, 20), around: true, full: `the area around ${raw.full}`} : raw;
    });
    if (names.length === 1) return names[0];
    // Two cells of one row: name the row once.
    if (names.length === 2 && names[0].base && names[0].base === names[1].base && names[0].col && names[1].col) {
      return {short: `${clip(names[0].base, 20)} · ${names[0].col} and ${names[1].col}`, full: names.map(n => n.full).join(' and ')};
    }
    return {short: `${names[0].around ? 'Around ' : ''}${clip(names[0].base || names[0].short, 20)} and ${names.length > 2 ? 'others' : clip(names[1].base || names[1].short, 20)}`, full: names.map(n => n.full).join(' and ')};
  }
  function askNew(targets) {
    S.asked++;
    const sub = subjectFor(targets);
    const kind = S.next === 'cycle' ? ['short', 'mid', 'long', 'error'][(S.asked - 1) % 4] : S.next;
    const answer = kind === 'long' ? longAnswer(sub.full) : kind === 'mid' ? midAnswer(sub.full) : shortAnswer(sub.full);
    const qPool = targets.length > 1 ? Q2 : Q1;
    const turn = {id: `q${++S.ids}`, q: `Sample question: ${qPool[(S.asked - 1) % qPool.length]}`, a: answer, shown: '', status: 'waiting', fail: kind === 'error', error: ''};
    const item = {id: `i${++S.ids}`, subject: sub.short, full: sub.full, targets, turns: [turn], seen: false, archived: false, url: location.href, host: location.host || 'this page', lost: false};
    S.items.push(item);
    S.queue.push({item, turn});
    S.pillLabelW = S.pillLabelW || 150;
    updateCapsule();
    P.pill.w.kick(70);
    pump();
  }
  function askFollowUp(item, extra) {
    if (extra?.length) item.targets = item.targets.concat(extra);
    const turn = {id: `q${++S.ids}`, q: `Sample question: ${QF[item.turns.length % QF.length]}`, a: followAnswer(item.full), shown: '', status: 'waiting', fail: false, error: ''};
    item.turns.push(turn);
    S.queue.push({item, turn});
    hidePill();
    pushCard();
    updateCapsule();
    armRetreat();
    pump();
  }

  // ---------- scripted brain: strictly in order ----------
  function pump() {
    if (S.active || !S.queue.length) { refresh(); return; }
    const job = S.queue.shift();
    S.active = job;
    job.turn.status = 'thinking';
    refresh();
    setTimeout(() => {
      if (job.turn.fail) {
        job.turn.status = 'error'; job.turn.error = FAIL; job.turn.fail = false;
        S.active = null;
        arrived(job.item);
        pump();
        return;
      }
      job.turn.status = 'streaming';
      arrived(job.item);
      stream(job);
    }, 2300 + Math.random() * 1300);
  }
  function stream(job) {
    const toks = job.turn.a.match(/\S+\s*/g) || [];
    let i = 0;
    const tickWord = () => {
      if (i >= toks.length) {
        job.turn.status = 'done';
        S.active = null;
        refresh();
        if (current() === job.item) armRetreat();
        send({t: 'persist', state: persistable()});
        pump();
        return;
      }
      const chunk = 1 + (Math.random() < .3 ? 1 : 0);
      job.turn.shown = toks.slice(0, i += chunk).join('');
      if (current() === job.item && S.open) pushCard();
      setTimeout(tickWord, 28 + Math.random() * 42);
    };
    tickWord();
  }
  function arrived(item) {
    if (!S.open) { item.archived = false; openStack(item); }
    refresh();
  }
  function refresh() { updateCapsule(); if (S.open) { pushCard(); layout(); } }

  // ---------- from the private frames ----------
  function fromPanel(frameName, m) {
    if (m.t === 'size') {
      if (frameName === 'card') {
        const was = S.sizes;
        S.sizes = {prevH: m.prevH || 0, cardH: m.cardH || 0, nextH: m.nextH || 0, contentH: m.contentH || 0, bodyH: m.bodyH || 0};
        if (S.open) {
          const item = current();
          if (item) {
            const mb = maxBodyFor(item);
            if (Math.abs(mb - S.maxBody) > 2) { S.maxBody = mb; pushCard(); }
            // Long answer ran out of room where it is: find better room once, before it clips hard.
            if (S.sizes.contentH > S.sizes.bodyH + 20 && S.maxBody < 300 && !item.replaced) {
              item.replaced = true;
              const spot = place(item, Math.min(innerHeight - 2 * MARGIN, S.sizes.contentH + 90));
              if (spot.covers === 0) { S.pos = {x: spot.x, y: spot.y}; S.maxBody = maxBodyFor(item); pushCard(); }
            }
          }
          layout();
        }
      } else if (frameName === 'pill') {
        if (m.w > 0) S.pillLabelW = m.w;
        if (S.pillMode === 'capsule') placeCapsule();
        if (S.pillMode === 'wave' && S.hold?.follow) { const {x, y} = pillAnchor(); P.pill.x.to(x); P.pill.y.to(y); P.pill.w.to(waveW(S.hold.follow)); }
        if (S.pillMode === 'coach') { const w = (S.pillLabelW || 200) + 32; P.pill.w.snap(w); P.pill.x.snap(innerWidth / 2 - w / 2); }
      } else if (frameName === 'sheet') {
        sheetWrap.style.height = `${m.h}px`;
      }
    } else if (m.t === 'ui') {
      const item = current();
      if (m.action === 'go' && item) goBack(item);
      else if (m.action === 'next') step(1);
      else if (m.action === 'prev') step(-1);
      else if (m.action === 'dismiss') closeStack('dismiss');
      else if (m.action === 'read' && item) readAloud(item);
      else if (m.action === 'retry' && item) retry(item, m.turn);
      else if (m.action === 'set') setOption(m.key, m.value);
    } else if (m.t === 'key') {
      onKey({type: m.type, code: m.code, key: m.key, repeat: m.repeat, shiftKey: m.shift, metaKey: m.meta, ctrlKey: m.ctrl, altKey: m.alt, fromFrame: true, preventDefault() {}, stopImmediatePropagation() {}});
    } else if (m.t === 'hover' && frameName === 'card') {
      S.hoverCard = m.on;
      if (m.on) { clearTimeout(S.retreatTimer); S.retreatAt = 0; } else armRetreat();
    }
  }
  function readAloud(item) {
    if (S.reading === item.id) { S.reading = null; clearTimeout(S.readTimer); pushCard(); armRetreat(); return; }
    S.reading = item.id;
    pushCard();
    clearTimeout(S.retreatTimer);
    S.readTimer = setTimeout(() => { S.reading = null; pushCard(); armRetreat(); }, 6000);
  }
  function retry(item, turnId) {
    const turn = item.turns.find(t => t.id === turnId);
    if (!turn) return;
    turn.status = 'waiting'; turn.shown = ''; turn.error = '';
    S.queue.unshift({item, turn});
    pushCard();
    pump();
  }

  // ---------- prototype sheet ----------
  function pushSheet() {
    send({t: 'panel', frame: 'sheet', msg: {kind: 'sheet', dark: S.dark, reduce: S.reduceForce, rows: [
      {key: 'soft', label: 'Pointing', value: S.soft ? 'soft' : 'exact', options: [['exact', 'Exact element'], ['soft', 'Soft region']]},
      {key: 'next', label: 'Next answer', value: S.next, options: [['cycle', 'Mixed'], ['short', 'Short'], ['long', 'Long'], ['error', 'Error']]},
      {key: 'motion', label: 'Motion', value: S.reduceForce ? 'reduced' : 'full', options: [['full', 'Full'], ['reduced', 'Reduced']]},
      {key: 'material', label: 'Material', value: S.solid ? 'solid' : 'glass', options: [['glass', 'Glass'], ['solid', 'Solid']]},
      {key: 'clear', label: 'Answers', value: '', options: [['all', 'Clear all']]},
    ]}});
  }
  function setOption(k, v) {
    if (k === 'soft') S.soft = v === 'soft';
    if (k === 'next') S.next = v;
    if (k === 'motion') S.reduceForce = v === 'reduced' ? true : null;
    if (k === 'material') { S.solid = v === 'solid'; setTone(S.dark); }
    if (k === 'clear') { closeStack('dismiss'); S.items = []; S.queue = []; S.active = null; S.cur = -1; hidePill(); }
    send({t: 'options', options: {soft: S.soft, next: S.next, reduceForce: S.reduceForce, solid: S.solid}});
    pushSheet();
    if (S.open) pushCard();
  }
  function toggleSheet() {
    S.sheet = !S.sheet;
    if (S.sheet) {
      setTone(darkAt(20, innerHeight - 300, 300, 280));
      pushSheet();
      raise();
      sheetWrap.style.cssText = `position:fixed;left:16px;bottom:16px;top:auto;width:330px;height:300px;overflow:hidden;border-radius:16px;pointer-events:auto;display:block;background:var(--fill);`;
    } else sheetWrap.style.display = 'none';
    armRetreat();
  }

  // ---------- keyboard ----------
  const editable = n => {
    n = n?.shadowRoot?.activeElement || n;
    return n && (n.isContentEditable || n.matches?.('input,textarea,select,[contenteditable],[role=textbox],[role=combobox],[role=searchbox]'));
  };
  const typing = () => editable(document.activeElement);
  const activatable = () => document.activeElement?.matches?.('button,a[href],summary,[role=button],[role=link],video,audio');
  function onKey(e) {
    if (!e.fromFrame && (typing() || e.metaKey || e.ctrlKey || e.altKey)) {
      if (e.code === 'Space' && e.type === 'keyup' && (S.keyDown || S.hold)) { /* fall through to finish */ }
      else return;
    }
    const swallow = () => { e.preventDefault(); e.stopImmediatePropagation(); };
    if (e.code === 'Space') {
      if (e.type === 'keydown') {
        swallow();
        if (e.repeat || S.keyDown) return;
        S.keyDown = true;
        S.keyArmed = true;
        S.armShift = e.shiftKey;
        clearTimeout(S.armTimer);
        S.armTimer = setTimeout(() => { if (S.keyDown) holdStart(); }, ARM_MS);
      } else {
        if (!S.keyDown) return;
        swallow();
        S.keyDown = false;
        clearTimeout(S.armTimer);
        if (S.hold) holdEnd(false);
        else if (S.keyArmed) {
          // A quick tap stays what it has always been: page down.
          S.keyArmed = false;
          if (activatable()) { document.activeElement.click(); return; } // a tap still presses what has focus
          window.scrollBy({top: innerHeight * .85 * (S.armShift ? -1 : 1), behavior: reduced() ? 'auto' : 'smooth'});
        }
      }
      return;
    }
    if (e.type !== 'keydown') return;
    if (e.code === 'Escape') {
      if (S.hold) { swallow(); holdEnd(true); S.keyDown = false; return; }
      if (S.sheet) { swallow(); toggleSheet(); return; }
      if (S.open) { swallow(); closeStack('dismiss'); }
      return;
    }
    if (e.key === '?' ) { swallow(); if (!e.repeat) toggleSheet(); return; }
    if (e.code === 'KeyQ' && !e.shiftKey) {
      if (!S.open && !S.hold && !e.repeat) { swallow(); recall(); }
      return;
    }
    if (!S.open) return;
    if (e.code === 'ArrowDown' || e.code === 'ArrowRight') { swallow(); if (!e.repeat) step(1); }
    else if (e.code === 'ArrowUp' || e.code === 'ArrowLeft') { swallow(); if (!e.repeat) step(-1); }
    else if (e.code === 'Enter') { swallow(); goBack(current()); }
  }
  window.addEventListener('keydown', onKey, true);
  window.addEventListener('keyup', onKey, true);
  window.addEventListener('blur', () => {
    if (document.hasFocus()) return; // focus only moved into our own private frame
    clearTimeout(S.armTimer);
    if (S.keyDown || S.hold) { S.keyDown = false; if (S.hold) holdEnd(true); }
  });

  // ---------- pointer & scroll ----------
  window.addEventListener('mousemove', e => {
    const p = S.pointer;
    if (p.x != null) p.moved += Math.hypot(e.clientX - p.x, e.clientY - p.y);
    p.x = e.clientX; p.y = e.clientY; p.at = performance.now();
    if (S.hold) wake();
  }, {capture: true, passive: true});
  let scrollEnd = 0;
  window.addEventListener('scroll', () => {
    S.scrollingAt = performance.now();
    wake();
    clearTimeout(scrollEnd);
    scrollEnd = setTimeout(() => {
      // Settled: if the page moved what you asked about under the card, step aside.
      const item = current();
      if (S.open && item && !S.hold) {
        const total = S.sizes.prevH + S.sizes.cardH + S.sizes.nextH;
        if (coversTargets(item, {x: S.pos.x, y: S.pos.y}, total)) {
          const spot = place(item, total);
          S.pos = {x: spot.x, y: spot.y};
          S.maxBody = maxBodyFor(item);
          setTone(darkAt(spot.x, spot.y, CARD_W, total));
          pushCard();
          layout();
        }
      }
    }, 130);
  }, {capture: true, passive: true});
  window.addEventListener('resize', () => { if (S.open) { const it = current(); const spot = place(it, S.sizes.cardH || 200); S.pos = {x: spot.x, y: spot.y}; S.maxBody = maxBodyFor(it); pushCard(); layout(); } });
  window.addEventListener('pagehide', () => send({t: 'persist', state: persistable()}));

  // ---------- frame loop: only while something is alive ----------
  let raf = 0, last = 0, lastPoint = 0, ticking = false;
  function wake() { if (!raf && !ticking && host) { last = performance.now(); raf = requestAnimationFrame(frameTick); } }
  function apply(b, n, r) {
    const s = n.style;
    s.transform = `translate3d(${b.x.x}px,${b.y.x}px,0)`;
    s.width = `${Math.max(0, b.w.x)}px`;
    s.height = `${Math.max(0, b.h.x)}px`;
    s.opacity = b.o.x.toFixed(3);
    if (r != null) s.borderRadius = `${r}px`;
  }
  function frameTick(now) {
    raf = 0;
    ticking = true; // anything woken mid-tick is picked up by the reschedule at the end
    const dt = Math.min(.05, Math.max(.001, (now - last) / 1000));
    last = now;
    for (const sp of [...springs]) sp.step(dt);
    for (const f of [...fades]) f.step(dt);
    // Pointing while held
    let level = 0;
    if (S.hold) {
      level = waveLevel(dt, now);
      if (now - lastPoint > 30) { lastPoint = now; updatePointing(now); }
      if (S.pillMode === 'wave') {
        const a = pillAnchor();
        const lag = S.hold.follow ? SPRING : FOLLOW;
        P.pill.x.k = lag.k; P.pill.x.c = lag.c; P.pill.y.k = lag.k; P.pill.y.c = lag.c;
        P.pill.x.to(a.x); P.pill.y.to(a.y);
      }
    } else {
      P.pill.x.k = SPRING.k; P.pill.x.c = SPRING.c; P.pill.y.k = SPRING.k; P.pill.y.c = SPRING.c;
    }
    // Plates
    apply(prev, plates[0], 15);
    apply(next2, plates[1], 12);
    apply(next, plates[2], 15);
    const morph = S.morphR != null ? S.morphR : 18;
    const rad = Math.min(front.h.x / 2, 18 + (morph - 18) * Math.max(0, 1 - Math.abs(front.w.x - front.w.t) / 80 < 0 ? 1 : Math.max(0, (Math.abs(front.w.x - front.w.t)) / 200)));
    apply(front, plates[3], Math.max(rad, 14));
    plates.forEach(p => { p.style.visibility = parseFloat(p.style.opacity) < .004 ? 'hidden' : 'visible'; });
    if (lift.x !== 0 || lift.v !== 0 || lift.t !== 0) {
      const off = lift.x * .06;
      for (const p of plates) p.style.translate = `0 ${off}px`;
      cardWrap.style.translate = `0 ${off}px`;
    } else {
      for (const p of plates) p.style.translate = '';
      cardWrap.style.translate = '';
    }
    // Words fade in just after the glass has shape.
    const wrapOn = S.open && front.h.x > 40;
    S.cardFade = wrapOn ? Math.min(1, (S.cardFade || 0) + dt / (reduced() ? .14 : .1)) : Math.max(0, (S.cardFade || 0) - dt / .09);
    const w = cardWrap.style;
    w.transform = `translate3d(${front.x.x}px,${(S.frameY ?? front.y.x) + (front.y.x - front.y.t)}px,0)`;
    w.width = `${Math.min(CARD_W, innerWidth - 2 * MARGIN)}px`;
    w.height = `${S.frameH || 0}px`;
    w.opacity = S.cardFade.toFixed(3);
    w.pointerEvents = S.open && !S.hold ? 'auto' : 'none';
    w.visibility = S.cardFade < .004 ? 'hidden' : 'visible';
    // Pill
    const pv = P.pill;
    apply(pv, pillEl, Math.min(pv.h.x / 2, 20));
    pillEl.style.visibility = pv.o.x < .004 ? 'hidden' : 'visible';
    if (pv.o.x > .004 && S.pillMode !== 'coach') drawPill(now);
    else if (S.pillMode === 'coach') { ctx.clearRect(0, 0, canvas.width, canvas.height); }
    const pw = pillFrameWrap.style;
    const m = Math.max(0, Math.min(1, P.pm.x));
    const labelX = S.pillMode === 'coach' ? 16 : S.pillMode === 'capsule' ? 34 : BARS * BAR_W + (BARS - 1) * BAR_GAP + 22;
    pw.transform = `translate3d(${labelX}px,0,0)`;
    pw.width = `${Math.max(0, pv.w.x - labelX - 6)}px`;
    pw.height = `${PILL_H}px`;
    // The label waits until the bars have settled into their small pulse.
    pw.opacity = S.pillMode === 'capsule' ? Math.max(0, Math.min(1, (m - .72) / .28)).toFixed(3) : '1';
    drawRings(level);
    const anyLit = lit.size > 0;
    const alive = springs.size || fades.size || S.hold || anyLit || (pv.o.x > .004) || (S.cardFade > 0 && S.cardFade < 1);
    ticking = false;
    if (alive) raf = requestAnimationFrame(frameTick);
  }

  // ---------- persistence across navigation (real product keeps this in Python too) ----------
  function persistable() {
    return {soft: S.soft, next: S.next, solid: S.solid, reduceForce: S.reduceForce, coach: S.coach, asked: S.asked,
      items: S.items.filter(i => i.turns.every(t => !['waiting', 'thinking', 'streaming'].includes(t.status))).map(i => ({
        id: i.id, subject: i.subject, full: i.full, url: i.url, host: i.host,
        turns: i.turns.map(t => ({id: t.id, q: t.q, a: t.a, shown: t.shown, status: t.status, error: t.error, fail: false}))}))};
  }

  // ---------- bridge ----------
  window.__HG_PROTO__ = {
    frames,
    fromPanel,
    ready(saved) {
      S.ready = true;
      setTone(false);
      if (saved) {
        Object.assign(S, {soft: !!saved.soft, next: saved.next || 'cycle', solid: !!saved.solid, reduceForce: saved.reduceForce ?? null, asked: saved.asked || 0});
        if (saved.coach) S.coach = saved.coach;
        S.items = (saved.items || []).map(i => ({...i, targets: [], seen: true, archived: true, lost: true}));
        S.ids = 100000;
      }
      if (!S.coach.heard && !S.items.length) {
        setTimeout(() => { if (!S.hold && !S.coach.heard) coachLine('Point at anything, hold Space and ask', 7000); }, 700);
      }
    },
    setCoach(c) { S.coach = c; },
    debug() {
      const it = current();
      const rects = it ? (it.targets || []).map(targetRect).filter(Boolean).map(r => ({left: r.left, top: r.top, right: r.right, bottom: r.bottom})) : [];
      return {
        open: S.open, cur: it?.subject, pos: S.pos,
        card: {x: front.x.t, y: front.y.t, w: front.w.t, h: front.h.t},
        frame: {y: S.frameY, h: S.frameH}, targets: rects, sizes: S.sizes, maxBody: S.maxBody, dark: S.dark, soft: S.soft,
        targetTags: it ? (it.targets || []).map(t => t.el ? `${t.el.tagName}.${t.el.className}`.slice(0, 60) + (t.el.isConnected ? '' : ' (detached)') : 'region') : [],
        hold: S.hold ? {targets: S.hold.targets.length, follow: S.hold.follow?.subject || null} : null,
        lit: lit.size, pill: {mode: S.pillMode, text: S.pillText, x: P.pill.x.t, y: P.pill.y.t, w: P.pill.w.t, h: P.pill.h.t, o: P.pill.o.t},
        items: S.items.map(i => ({subject: i.subject, archived: i.archived, seen: i.seen, status: i.turns.map(t => t.status)})),
        retreatInMs: S.retreatAt ? Math.round(S.retreatAt - performance.now()) : null,
        solid: reducedTransparency(), reduced: reduced(),
      };
    },
    set: setOption,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true});
  else boot();
})();
