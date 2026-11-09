// Runs only through CDP in script-disabled, opaque-origin frames, one for the card stack and one
// for the capsule. Holds every private string and the voice level. setTimeout never fires here,
// so timing comes from outside over CDP; CSS animation and requestAnimationFrame do work.
(() => {
  if (window.__HERMES_GAZE_PANEL__) return;
  const send = m => window.__hermesGazeIntent(JSON.stringify(m));
  // Plates are rounded to coarse steps, so the page cannot read an answer's exact length.
  const STEP_H = 24, STEP_W = 16;
  document.documentElement.style.cssText = 'background:transparent;overflow:hidden;height:100%';
  document.body.style.cssText = 'margin:0;background:transparent;height:100%';
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(`
    :root { color-scheme: light; --label:rgba(0,0,0,.86); --secondary:rgba(60,60,67,.72); --tertiary:rgba(60,60,67,.5);
      --accent:#0066d6; --red:#c9281e; --hover:rgba(0,0,0,.055); --line:rgba(0,0,0,.09); --well:rgba(0,0,0,.05);
      --shimmer-a:rgba(60,60,67,.68); --shimmer-b:rgba(0,0,0,.95); }
    :root.dark { --label:rgba(255,255,255,.92); --secondary:rgba(235,235,245,.68); --tertiary:rgba(235,235,245,.42);
      --accent:#4ea1ff; --red:#ff6b60; --hover:rgba(255,255,255,.08); --line:rgba(255,255,255,.11); --well:rgba(255,255,255,.08);
      --shimmer-a:rgba(235,235,245,.66); --shimmer-b:rgba(255,255,255,1); }
    * { box-sizing:border-box; }
    html,body { font:13px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;
      -webkit-font-smoothing:antialiased; color:var(--label); letter-spacing:-.006em; user-select:none; cursor:default; }
    button { all:unset; cursor:default; }
    button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; border-radius:4px; }
    #root { display:flex; flex-direction:column; width:100%; }

    /* Slivers: the neighbours in the stack, named by subject. */
    .peek { display:flex; align-items:center; gap:6px; height:30px; flex:none; padding:0 22px; font-size:12px; color:var(--secondary);
      transition:color .14s; white-space:nowrap; }
    .peek:hover { color:var(--label); }
    .peek .name { overflow:hidden; text-overflow:ellipsis; font-weight:500; }
    .peek .state { flex:none; color:var(--tertiary); }
    .peek .key { flex:none; margin-left:auto; color:var(--tertiary); font-size:12px; }

    .card { position:relative; display:flex; flex-direction:column; padding:13px 16px 0; }
    .head { display:flex; align-items:baseline; gap:8px; min-height:18px; flex:none; }
    .title { font-size:13.5px; font-weight:600; letter-spacing:-.012em; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
    .slide-next { animation:slide-next .26s cubic-bezier(.2,.9,.3,1) both; }
    .slide-prev { animation:slide-prev .26s cubic-bezier(.2,.9,.3,1) both; }
    .arrive { animation:arrive .3s .07s cubic-bezier(.2,.9,.3,1) both; }
    @keyframes slide-next { from { opacity:0; transform:translateY(16px) } to { opacity:1; transform:none } }
    @keyframes slide-prev { from { opacity:0; transform:translateY(-16px) } to { opacity:1; transform:none } }
    @keyframes arrive { from { opacity:0; transform:translateY(5px) } to { opacity:1; transform:none } }

    .body { flex:none; overflow-y:auto; overscroll-behavior:contain; margin:0 -16px; padding:0 16px; scrollbar-width:none; user-select:text; cursor:text; }
    .body::-webkit-scrollbar { display:none; }
    .body.clipped { mask-image:linear-gradient(#000 calc(100% - 26px),transparent); }
    .body.scrolled { mask-image:linear-gradient(transparent,#000 18px); }
    .body.clipped.scrolled { mask-image:linear-gradient(transparent,#000 18px,#000 calc(100% - 26px),transparent); }
    .turn + .turn { margin-top:12px; padding-top:12px; border-top:.5px solid var(--line); }
    .q { margin-top:3px; color:var(--secondary); font-size:12.5px; line-height:1.35; }
    .notice, .answer-notice { margin-top:5px; color:var(--secondary); font-size:12px; line-height:1.35; }
    .q:empty { display:none; }

    .a { margin-top:7px; font-size:13.5px; line-height:1.43; overflow-wrap:anywhere; }
    .a p, .a ul, .a ol, .a pre, .a blockquote, .a .tablewrap, .a .h1, .a .h2, .a .h3 { margin:8px 0 0; }
    .a > :first-child { margin-top:0; }
    .a li > :first-child { margin-top:0; }
    .a strong { font-weight:600; }
    .a .h1,.a .h2,.a .h3 { font-weight:600; letter-spacing:-.012em; margin-top:11px; }
    .a .h1 { font-size:15px; } .a .h2 { font-size:14px; } .a .h3 { font-size:13.5px; }
    .a ul,.a ol { padding-left:18px; }
    .a li { margin-top:3px; } .a li:first-child { margin-top:0; }
    .a li::marker { color:var(--tertiary); }
    .a code { font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace; background:var(--well); padding:.5px 4px; border-radius:4px; overflow-wrap:anywhere; }
    .a pre { background:var(--well); padding:8px 10px; border-radius:8px; overflow-x:auto; overscroll-behavior-x:contain; scrollbar-width:none; }
    .a pre::-webkit-scrollbar { display:none; }
    .a pre code { display:block; background:none; padding:0; white-space:pre; overflow-wrap:normal; }
    .a blockquote { margin-left:0; padding-left:10px; border-left:2px solid var(--line); color:var(--secondary); }
    .a hr { border:0; border-top:.5px solid var(--line); margin:10px 0; }
    .a del { color:var(--secondary); }
    .a .imgalt { color:var(--secondary); font-style:italic; }
    .a .link { color:var(--accent); cursor:pointer; }
    .a .link:hover { text-decoration:underline; text-underline-offset:2px; }
    .a .link .host { color:var(--tertiary); font-size:11.5px; }
    .a .link .host:only-child { color:inherit; font-size:inherit; }
    .a .tablewrap { overflow-x:auto; overscroll-behavior-x:contain; scrollbar-width:none; }
    .a .tablewrap::-webkit-scrollbar { display:none; }
    .a table { border-collapse:collapse; font-size:12.5px; line-height:1.35; min-width:100%; }
    .a th { font-weight:600; text-align:left; white-space:nowrap; }
    .a th,.a td { padding:3px 10px 3px 0; border-bottom:.5px solid var(--line); vertical-align:top; }
    .a tbody tr:last-child td { border-bottom:0; }
    .a [data-align="right"] { text-align:right; } .a [data-align="center"] { text-align:center; }
    .w { animation:word .22s ease-out both; }
    @keyframes word { from { opacity:0; filter:blur(2px) } to { opacity:1; filter:none } }
    .static .w { animation:none; }

    .looking { margin-top:7px; font-size:13.5px; display:inline-block; color:var(--secondary); }
    .shimmer { background:linear-gradient(100deg,var(--shimmer-a) 30%,var(--shimmer-b) 50%,var(--shimmer-a) 70%);
      background-size:220% 100%; -webkit-background-clip:text; background-clip:text; color:transparent;
      animation:shimmer 1.5s linear infinite; }
    @keyframes shimmer { from { background-position:120% 0 } to { background-position:-100% 0 } }
    .err { margin-top:7px; font-size:13.5px; line-height:1.43; color:var(--label); }
    .row { display:flex; flex-wrap:wrap; gap:14px; margin-top:7px; font-size:13px; }
    .retry { color:var(--accent); font-weight:500; }
    .retry:hover,.skip:hover { text-decoration:underline; text-underline-offset:2px; }
    .skip { color:var(--secondary); }

    /* Plain-word controls, in the space a hint occupies until you hover. */
    .foot { position:relative; flex:none; height:32px; margin-top:auto; padding-top:4px; font-size:12px; }
    .card.quiet .foot { height:12px; }
    .card.quiet:hover .foot, .card.quiet:focus-within .foot { height:32px; }
    .hint, .actions { position:absolute; inset:4px 0 0; display:flex; align-items:center; gap:14px; transition:opacity .16s; }
    .hint { color:var(--tertiary); }
    .hint.alert { color:var(--red); }
    .actions { opacity:0; pointer-events:none; }
    .card:hover .actions, .actions:focus-within { opacity:1; pointer-events:auto; }
    .card:hover .hint { opacity:0; }
    .act { color:var(--accent); font-weight:500; white-space:nowrap; }
    .act:hover { text-decoration:underline; text-underline-offset:2px; }
    .act.quiet { margin-left:auto; color:var(--secondary); font-weight:400; }
    .act.off { color:var(--tertiary); font-weight:400; text-decoration:none; }
    .act.toggle { color:var(--secondary); font-weight:400; }
    .act.toggle[aria-pressed=true] { color:var(--accent); font-weight:500; }

    /* Typed question */
    .ask { display:flex; align-items:center; gap:10px; margin-top:7px; padding-bottom:3px; }
    #hg-input { all:unset; flex:1; min-width:0; font-size:13.5px; line-height:1.43; color:var(--label); user-select:text; cursor:text; }
    #hg-input::placeholder { color:var(--tertiary); }
    #hg-send { color:var(--accent); font-weight:500; font-size:13px; }
    #hg-send:hover { text-decoration:underline; text-underline-offset:2px; }

    /* Confirmation */
    .sub { margin-top:3px; color:var(--secondary); font-size:12.5px; line-height:1.35; }
    .choices { display:flex; gap:8px; margin:11px 0 3px; }
    .choice { padding:5px 13px; border-radius:7px; font-size:13px; font-weight:500; background:var(--hover); color:var(--label); }
    .choice:hover { background:var(--line); }
    .choice.yes { background:var(--red); color:#fff; }
    .choice.yes:hover { filter:brightness(1.08); }

    /* Which one? (noisy pointing) */
    .option { position:relative; display:block; padding:6px 0; border-top:.5px solid var(--line); font-size:13px; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
    .option:first-of-type { margin-top:7px; }
    .option:hover { color:var(--accent); }
    .option .dwell { position:absolute; left:0; bottom:0; height:1.5px; width:100%; background:var(--accent); transform-origin:left; transform:scaleX(0); }
    .option:hover .dwell { animation:dwell var(--dwell,450ms) linear forwards; }
    @keyframes dwell { to { transform:scaleX(1) } }

    /* Capsule */
    #wave { position:absolute; left:0; top:0; width:460px; height:36px; pointer-events:none; }
    .bar { position:absolute; left:0; top:0; width:2.6px; border-radius:1.3px; background:#0a6fe0; opacity:0; will-change:transform,height; }
    :root.dark .bar { background:#5facff; }
    #pill { position:absolute; top:0; height:36px; display:inline-flex; align-items:center; white-space:nowrap;
      font-size:12.5px; font-weight:500; letter-spacing:-.008em; opacity:0; transition:opacity .2s; }
    #pill.on { opacity:1; }
    #pill.plain { color:var(--label); }

    @media (prefers-reduced-motion: reduce) {
      .slide-next,.slide-prev,.arrive,.w,.shimmer { animation:none; }
      .shimmer { background:none; color:var(--secondary); }
    }
    :root.reduce .slide-next,:root.reduce .slide-prev,:root.reduce .arrive,:root.reduce .w,:root.reduce .shimmer { animation:none; }
    :root.reduce .shimmer { background:none; color:var(--secondary); }
  `);
  document.adoptedStyleSheets = [sheet];
  const root = document.createElement('div');
  root.id = 'root';
  document.body.append(root);

  const h = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  };
  const scheme = (dark, reduce) => {
    document.documentElement.classList.toggle('dark', !!dark);
    document.documentElement.classList.toggle('reduce', !!reduce);
  };
  let reduced = false;

  // ---------- capsule: waveform in here, so voice level never reaches the page ----------
  const BARS = 13, BAR_W = 2.6, BAR_GAP = 3, WAVE_W = BARS * BAR_W + (BARS - 1) * BAR_GAP, PILL_H = 36;
  const levels = new Float32Array(BARS);
  // DOM bars, not a canvas: Chrome shows canvas fallback content in a scripts-disabled document.
  let bars = null, label, pillMode = 'off', morph = 0, morphV = 0, pillW = 0, voiceWant = 0, voice = 0, phase = 0, raf = 0, last = 0, startup = false;

  function ensurePill() {
    if (bars) return;
    const layer = h('div'); layer.id = 'wave';
    bars = [];
    for (let i = 0; i < BARS; i++) { const bar = h('i', 'bar'); layer.append(bar); bars.push(bar); }
    label = h('div'); label.id = 'pill';
    root.append(layer, label);
  }
  function clearBars() { for (const bar of bars) bar.style.opacity = 0; }
  function drawPill(now) {
    raf = 0;
    if (pillMode !== 'wave' && pillMode !== 'capsule') { clearBars(); return; }
    const dt = Math.min(.05, Math.max(.001, (now - last) / 1000));
    last = now;
    const target = pillMode === 'capsule' ? 1 : 0;
    if (reduced) morph = target;
    else {
      for (let i = 0; i < 4; i++) { morphV += (-280 * (morph - target) - 30 * morphV) * dt / 4; morph += morphV * dt / 4; }
      if (Math.abs(morph - target) < .002 && Math.abs(morphV) < .02) { morph = target; morphV = 0; }
    }
    const m = Math.max(0, Math.min(1, morph));
    voice += (voiceWant - voice) * Math.min(1, dt * 16);
    if (reduced) voice = Math.min(voice, .4);
    phase += dt * 7;
    for (let i = 0; i < BARS; i++) {
      const c = 1 - Math.abs(i - (BARS - 1) / 2) / ((BARS - 1) / 2);
      const wob = .55 + .45 * Math.sin(phase + i * 1.15 + Math.sin(phase * .37 + i) * 1.4);
      const want = voice * (.38 + .62 * c) * wob;
      levels[i] += (want - levels[i]) * Math.min(1, dt * 26);
    }
    const ch = PILL_H, cy = ch / 2, t = now / 1000, x0 = 13, dotX = [14, 20, 26];
    for (let i = 0; i < BARS; i++) {
      const isDot = i >= 5 && i < 8;
      const alpha = isDot ? 1 : Math.max(0, 1 - m * 2.2);
      const bar = bars[i];
      if (alpha <= 0) { bar.style.opacity = 0; continue; }
      const bx = x0 + i * (BAR_W + BAR_GAP);
      const x = isDot ? bx + (dotX[i - 5] - bx) * m : bx + ((pillW / 2 - bx) * m);
      // While the microphone starts, the bars rest in a slow breath rather than moving with no sound.
      const idle = startup ? 2 * (.5 + .5 * Math.sin(t * 4 - i * .5)) : 0;
      const waveH = 4 + idle + levels[i] * (ch - 14);
      const dotH = reduced ? 7 : 4.5 + 7 * (.5 + .5 * Math.sin(t * 5.2 - (i - 5) * .9));
      const hh = waveH + (dotH - waveH) * m;
      bar.style.opacity = alpha.toFixed(3);
      bar.style.height = `${hh.toFixed(2)}px`;
      bar.style.transform = `translate3d(${x.toFixed(2)}px,${(cy - hh / 2).toFixed(2)}px,0)`;
    }
    raf = requestAnimationFrame(drawPill);
  }
  function renderPill(m) {
    scheme(m.dark, m.reduce);
    reduced = !!m.reduce || matchMedia('(prefers-reduced-motion: reduce)').matches;
    ensurePill();
    const was = pillMode;
    pillMode = m.mode;
    startup = !!m.startup;
    if (m.mode === 'wave' && was !== 'wave') { morph = was === 'capsule' ? morph : 0; voiceWant = 0; voice = 0; }
    if (m.mode === 'capsule' && was === 'coach') { morph = 1; morphV = 0; }
    label.textContent = m.text || '';
    label.classList.toggle('on', !!m.text);
    label.classList.toggle('plain', !m.shimmer);
    label.classList.toggle('shimmer', !!m.shimmer);
    const textW = m.text ? Math.ceil(label.getBoundingClientRect().width) : 0;
    let left = 16, natural = textW + 32;
    if (m.mode === 'wave') { left = WAVE_W + 22; natural = m.text ? left + textW + 14 : WAVE_W + 26; }
    else if (m.mode === 'capsule') { left = 34; natural = textW + 48; }
    const w = Math.ceil(natural / STEP_W) * STEP_W;
    // Centre the rounding slack around the words so it reads as padding.
    label.style.left = `${left + (m.text ? (w - natural) / 2 : 0)}px`;
    pillW = w;
    if ((pillMode === 'wave' || pillMode === 'capsule') && !raf) { last = performance.now(); raf = requestAnimationFrame(drawPill); }
    if (pillMode === 'off' || pillMode === 'coach') clearBars();
    send({t: 'size', w, text: !!m.text});
  }

  // ---------- markdown view to elements: allow-list, text nodes, in-place updates ----------
  const MD = window.__HG_MD__;
  function build(v, animate) {
    if (v.text != null) return v.text;
    if (!MD.ALLOWED.has(v.tag)) return document.createTextNode('');
    const el = document.createElement(v.tag);
    if (v.cls) el.className = v.cls;
    if (v.url) el.dataset.url = v.url;
    if (v.align) el.dataset.align = v.align;
    if (v.start != null) el.setAttribute('start', String(v.start));
    patch(el, v.kids || [], animate);
    return el;
  }
  // Text views become word spans so new words can fade in, and existing ones never restart.
  function flatten(kids) {
    const out = [];
    for (const v of kids) {
      if (v.text == null) { out.push(v); continue; }
      if (!v.words) { out.push(v); continue; }
      for (const tok of v.text.split(/(\s+)/)) {
        if (!tok) continue;
        out.push(/^\s+$/.test(tok) ? {text: ' '} : {word: tok});
      }
    }
    return out;
  }
  function same(node, v) {
    if (v.word != null) return node.nodeType === 1 && node.classList.contains('w');
    if (v.text != null) return node.nodeType === 3;
    return node.nodeType === 1 && node.tagName === v.tag.toUpperCase() && (node.className || '') === (v.cls || '') &&
      (node.dataset.url || '') === (v.url || '') && (node.dataset.align || '') === (v.align || '');
  }
  function patch(parent, kids, animate) {
    const views = flatten(kids);
    views.forEach((v, i) => {
      const node = parent.childNodes[i];
      if (node && same(node, v)) {
        if (v.word != null) { if (node.textContent !== v.word) node.textContent = v.word; }
        else if (v.text != null) { if (node.data !== v.text) node.data = v.text; }
        else {
          if (v.start != null) node.setAttribute('start', String(v.start));
          patch(node, v.kids || [], animate);
        }
        return;
      }
      let fresh;
      if (v.word != null) {
        fresh = h('span', 'w', v.word);
        if (!animate) fresh.style.animation = 'none';
      } else if (v.text != null) fresh = document.createTextNode(v.text);
      else fresh = build(v, animate);
      if (node) parent.replaceChild(fresh, node);
      else parent.append(fresh);
    });
    while (parent.childNodes.length > views.length) parent.lastChild.remove();
  }

  // ---------- answer card ----------
  let shownKey = null, turns = new Map(), body = null, lastSig = '', lastMeasure = '', view = null;
  // Layout can settle after render (frame width, first fonts). Keep the plate in sync
  // without waiting for another answer delta; only coarse sizes cross the binding.
  const sizeObserver = new ResizeObserver(() => { if (view) { report(); clip(); } });

  function peekRow(kind, p) {
    const row = h('button', `peek ${kind}`);
    row.dataset.act = kind;
    row.append(h('span', 'name', p.subject));
    if (p.state) row.append(h('span', 'state', `· ${p.state}`));
    row.append(h('span', 'key', kind === 'next' ? '↓' : '↑'));
    return row;
  }
  const isBusy = s => ['transcribing', 'queued', 'thinking'].includes(s);
  const LOOK = {transcribing: 'Transcribing…', queued: 'Waiting its turn…', thinking: 'Looking into it…'};

  function renderTurn(t, node) {
    if (node.q.textContent !== (t.q || '')) node.q.textContent = t.q || '';
    if (isBusy(t.status)) {
      const word = LOOK[t.status];
      if (!node.look) { node.look = h('div', 'looking shimmer'); node.el.append(node.look); }
      if (node.look.textContent !== word) node.look.textContent = word;
    } else if (node.look) { node.look.remove(); node.look = null; }
    if (t.a) {
      if (!node.ans) { node.ans = h('div', 'a'); node.el.append(node.ans); }
      const settled = t.status === 'complete';
      patch(node.ans, MD.view(t.a, {streaming: !settled && !t.answerNotice}), node.live);
    }
    if (t.answerNotice) {
      if (!node.shortened) { node.shortened = h('div', 'answer-notice'); node.el.append(node.shortened); }
      node.shortened.textContent = t.answerNotice;
    } else if (node.shortened) { node.shortened.remove(); node.shortened = null; }
    if (t.error) {
      if (!node.err) {
        node.err = h('div', 'err');
        const row = h('div', 'row');
        const retry = h('button', 'retry', 'Try again');
        retry.dataset.act = 'retry'; retry.dataset.turn = t.id;
        const skip = h('button', 'skip', 'Skip');
        skip.dataset.act = 'skip'; skip.dataset.turn = t.id;
        row.append(retry, skip);
        node.row = row;
        node.el.append(node.err, row);
      }
      if (node.err.textContent !== t.error) node.err.textContent = t.error;
    } else if (node.err) { node.err.remove(); node.row.remove(); node.err = node.row = null; }
    node.live = true;
  }

  function clearView() {
    sizeObserver.disconnect();
    root.textContent = ''; shownKey = null; turns = new Map(); body = null; lastSig = ''; lastMeasure = ''; view = null;
  }
  function peeks(m) {
    for (const kind of ['prev', 'next']) {
      const old = root.querySelector(`.peek.${kind}`), want = m[kind];
      if (old && (!want || old.dataset.sig !== JSON.stringify(want))) old.remove();
      if (want && !root.querySelector(`.peek.${kind}`)) {
        const row = peekRow(kind, want);
        row.dataset.sig = JSON.stringify(want);
        if (kind === 'prev') root.prepend(row); else root.append(row);
      }
    }
  }
  function renderAnswer(m) {
    const swap = shownKey !== `answer:${m.item.id}`;
    if (swap) {
      clearView();
      shownKey = `answer:${m.item.id}`;
      view = 'answer';
      const card = h('div', `card ${m.dir === 'next' ? 'slide-next' : m.dir === 'prev' ? 'slide-prev' : 'arrive'}`);
      card.setAttribute('role', 'article');
      const head = h('div', 'head');
      head.append(h('div', 'title', m.item.subject));
      body = h('div', 'body');
      body.addEventListener('scroll', () => {
        send({t: 'engaged'});
        clip();
      });
      body.id = 'hg-reply';
      const foot = h('div', 'foot');
      card.append(head, body, foot);
      root.append(card);
    }
    const card = root.querySelector('.card');
    const title = root.querySelector('.title');
    if (title.textContent !== m.item.subject) title.textContent = m.item.subject;
    peeks(m);
    let notice = root.querySelector('.notice');
    if (m.item.notice && !notice) {
      notice = h('div', 'notice', m.item.notice);
      root.querySelector('.head').after(notice);
    } else if (!m.item.notice && notice) notice.remove();
    const want = new Set(m.item.turns.map(t => t.id));
    for (const [id, node] of turns) if (!want.has(id)) { node.el.remove(); turns.delete(id); }
    for (const t of m.item.turns) {
      let node = turns.get(t.id);
      if (!node) {
        const el = h('div', 'turn');
        const q = h('div', 'q');
        el.append(q);
        body.append(el);
        node = {el, q, live: !swap};
        turns.set(t.id, node);
      }
      renderTurn(t, node);
    }
    // Footer: a plain hint until you hover, then plain words. Without a hint it folds away.
    const foot = root.querySelector('.foot');
    const failed = m.item.turns.some(t => t.error);
    const sig = JSON.stringify([m.hint, m.alert, m.reading, m.autoRead, m.canRead, m.eyeTracking, m.item.lost, m.item.host, m.item.gone, m.paused]);
    if (foot.dataset.sig !== sig) {
      foot.dataset.sig = sig;
      foot.textContent = '';
      const text = m.alert || m.hint || '';
      card.classList.toggle('quiet', !text);
      const hint = h('div', `hint${m.alert ? ' alert' : ''}`, text);
      const actions = h('div', 'actions');
      if (m.paused) {
        const resume = h('button', 'act', 'Continue with the rest');
        resume.dataset.act = 'resume';
        actions.append(resume);
      } else {
        const go = h('button', m.item.gone ? 'act off' : 'act', m.item.gone ? 'No longer on this page' : m.item.lost ? `Back to ${m.item.host}` : 'Show on page');
        if (!m.item.gone) go.dataset.act = 'go';
        actions.append(go);
        if (m.canRead) {
          const read = h('button', 'act', m.reading ? 'Stop reading' : 'Read aloud');
          read.dataset.act = 'read';
          actions.append(read);
          // The long "where it went" words need the room; the setting is on every other card.
          if (!m.item.gone && !m.item.lost) {
            const always = h('button', 'act toggle', m.autoRead ? 'Always read: on' : 'Always read');
            always.dataset.act = 'autoread';
            always.setAttribute('aria-pressed', String(!!m.autoRead));
            actions.append(always);
          }
        }
      }
      if (m.eyeTracking) {
        const tracker = h('button', 'act', 'Eye tracking');
        tracker.dataset.act = 'tracking'; actions.append(tracker);
      }
      const close = h('button', 'act quiet', 'Dismiss');
      close.dataset.act = 'dismiss';
      actions.append(close);
      foot.append(hint, actions);
    }
    card.classList.toggle('failed', failed);
    body.style.maxHeight = `${Math.max(60, m.maxBody || 400)}px`;
    // A new/reopened card starts at the beginning. Updates, follow-ups and retries
    // leave the reader alone, even when they have manually reached the bottom.
    if (swap || m.dir === 'open') body.scrollTop = 0;
    clip();
  }
  function clip() {
    if (!body) return;
    body.classList.toggle('clipped', body.scrollHeight - body.scrollTop - body.clientHeight > 6);
    body.classList.toggle('scrolled', body.scrollTop > 2);
  }

  function renderCompose(m) {
    if (shownKey !== 'compose') {
      clearView();
      shownKey = 'compose'; view = 'compose';
      const card = h('div', 'card arrive');
      const head = h('div', 'head');
      head.append(h('div', 'title', m.title || ''));
      const ask = h('div', 'ask');
      const input = h('input');
      input.id = 'hg-input';
      input.setAttribute('aria-label', m.followup ? 'Ask more about this' : 'Ask about this');
      input.setAttribute('autocomplete', 'off');
      input.placeholder = m.followup ? 'Ask more about this…' : 'Ask about this…';
      const go = h('button', '', 'Ask');
      go.id = 'hg-send';
      go.dataset.act = 'submit';
      ask.append(input, go);
      const foot = h('div', 'foot');
      foot.append(h('div', 'hint', 'Enter to ask, Esc to close'));
      card.append(head, ask, foot);
      root.append(card);
      input.focus();
    }
    const title = root.querySelector('.title');
    if (title.textContent !== (m.title || '')) title.textContent = m.title || '';
    if (m.focus) root.querySelector('#hg-input').focus();
  }

  function renderConfirm(m) {
    if (shownKey !== `confirm:${m.id}`) {
      clearView();
      shownKey = `confirm:${m.id}`; view = 'confirm';
      const card = h('div', 'card arrive');
      card.setAttribute('role', 'dialog');
      card.setAttribute('aria-label', 'Confirm page action');
      const head = h('div', 'head');
      head.append(h('div', 'title', m.label || 'This control'));
      const sub = h('div', 'sub', 'Hermes wants to press this on the page. Click to allow it.');
      const summary = h('div', 'sub', m.summary || 'No nonsensitive fields on this page.');
      summary.style.whiteSpace = 'pre-wrap';
      summary.style.overflowWrap = 'anywhere';
      summary.style.maxHeight = `${Math.max(96, Number(m.maxBody) || 300)}px`;
      summary.style.overflowY = 'auto';
      const destination = h('div', 'sub', `Destination: ${m.destination || 'Current page'}`);
      destination.style.overflowWrap = 'anywhere';
      const choices = h('div', 'choices');
      const yes = h('button', 'choice yes', 'Confirm');
      yes.dataset.act = 'confirm'; yes.dataset.value = 'yes';
      const no = h('button', 'choice', 'Cancel');
      no.dataset.act = 'confirm'; no.dataset.value = 'no';
      if (m.doing) {
        const stop = h('button', 'choice', 'Stop');
        stop.dataset.act = 'stop_action_task';
        choices.append(stop);
      }
      choices.append(yes, no);
      card.append(head, sub, summary, destination, choices);
      root.append(card);
    }
  }

  function renderDoing(m) {
    if (shownKey !== 'doing') {
      clearView();
      shownKey = 'doing'; view = 'doing';
      const card = h('div', 'card arrive quiet');
      const head = h('div', 'head');
      head.append(h('div', 'title', 'Doing'));
      const label = h('div', 'sub', m.label || 'Working on this page');
      label.dataset.doingLabel = '';
      const choices = h('div', 'choices');
      const stop = h('button', 'choice', 'Stop');
      stop.dataset.act = 'stop_action_task';
      choices.append(stop);
      card.append(head, label, choices);
      root.append(card);
    } else root.querySelector('[data-doing-label]').textContent = m.label || 'Working on this page';
  }

  function renderLens(m) {
    if (shownKey !== `lens:${m.id}`) {
      clearView();
      shownKey = `lens:${m.id}`; view = 'lens';
      const card = h('div', 'card arrive quiet');
      card.style.setProperty('--dwell', `${m.dwell || 450}ms`);
      const head = h('div', 'head');
      head.append(h('div', 'title', 'Which one did you mean?'));
      card.append(head);
      m.options.forEach((label, i) => {
        const row = h('button', 'option lens-card', label || 'Unnamed item');
        row.dataset.act = 'lens'; row.dataset.value = String(i);
        row.append(h('span', 'dwell'));
        card.append(row);
      });
      card.append(h('div', 'foot'));
      root.append(card);
    }
  }

  function renderNote(m) {
    const swap = shownKey !== `note:${m.id}`;
    if (swap) {
      clearView();
      shownKey = `note:${m.id}`; view = 'note';
      const card = h('div', 'card arrive quiet');
      const head = h('div', 'head');
      head.append(h('div', 'title', m.title || ''));
      body = h('div', 'body');
      body.id = 'hg-reply';
      body.addEventListener('scroll', clip);
      const foot = h('div', 'foot');
      const actions = h('div', 'actions');
      const close = h('button', 'act quiet', 'Dismiss');
      close.dataset.act = 'dismiss';
      actions.append(close);
      foot.append(actions);
      card.append(head, body, foot);
      root.append(card);
      const ans = h('div', 'a static');
      body.append(ans);
    }
    patch(body.querySelector('.a'), MD.view(m.text, {}), false);
    body.style.maxHeight = `${Math.max(60, m.maxBody || 400)}px`;
    clip();
  }

  function renderTracking(m) {
    const state = m.trackerState || 'stopped', key = `tracking:${state}:${!!m.setupRequired}`;
    if (shownKey === key) return;
    clearView(); shownKey = key; view = 'tracking';
    const titles = {preparing: 'Preparing eye tracking', starting: 'Opening camera window',
      loading: 'Loading eye tracking', camera: 'Opening camera — allow access if asked',
      running: 'Eye tracking', stopping: 'Camera is stopping', failed: 'Camera unavailable', stopped: 'Camera stopped'};
    const card = h('div', 'card quiet');
    const head = h('div', 'head'); head.append(h('div', 'title',
      m.setupRequired ? 'Files missing — /look setup eyes' : titles[state] || 'Camera stopped'));
    const choices = h('div', 'choices');
    const actions = m.setupRequired || ['preparing', 'starting', 'loading', 'camera', 'stopping'].includes(state)
      ? [] : [['show_camera', state === 'failed' || state === 'stopped' ? 'Try again' : 'Open camera window']];
    for (const [action, label] of [...actions, ['use_cursor', 'Use cursor'], ['dismiss', 'Dismiss']]) {
      const button = h('button', 'choice', label); button.dataset.act = action; choices.append(button);
    }
    card.append(head, choices); root.append(card);
  }

  function report() {
    const card = root.querySelector('.card');
    const size = el => el ? Math.ceil(el.getBoundingClientRect().height) : 0;
    let cardH = 0;
    if (card) {
      card.style.minHeight = '';
      const natural = size(card);
      cardH = Math.ceil(natural / STEP_H) * STEP_H;
      card.style.minHeight = `${cardH}px`;
    }
    const sizes = {t: 'size', prevH: size(root.querySelector('.peek.prev')), cardH,
      nextH: size(root.querySelector('.peek.next')), contentH: body ? body.scrollHeight : 0, bodyH: body ? body.clientHeight : 0};
    const key = JSON.stringify(sizes);
    if (key !== lastMeasure) { lastMeasure = key; send(sizes); }
  }

  window.__HERMES_GAZE_PANEL__ = {
    render(m) {
      if (m.kind === 'pill') { renderPill(m); return; }
      scheme(m.dark, m.reduce);
      reduced = !!m.reduce;
      if (!m.view) { clearView(); send({t: 'size', prevH: 0, cardH: 0, nextH: 0, contentH: 0, bodyH: 0}); return; }
      if (m.view === 'answer') renderAnswer(m);
      else if (m.view === 'compose') renderCompose(m);
      else if (m.view === 'confirm') renderConfirm(m);
      else if (m.view === 'doing') renderDoing(m);
      else if (m.view === 'lens') renderLens(m);
      else if (m.view === 'tracking') renderTracking(m);
      else renderNote(m);
      report();
      sizeObserver.observe(root);
      if (body) sizeObserver.observe(body);
    },
    level(v) { voiceWant = Math.max(0, Math.min(1, Number(v) || 0)); startup = false; },
  };

  // ---------- trusted input only; nothing reaches the page ----------
  const inField = n => !!n?.closest?.('input,textarea');
  const activateButton = (button, facts = {}) => send({t: 'ui', action: button.dataset.act, turn: button.dataset.turn,
    value: button.dataset.act === 'submit' ? root.querySelector('#hg-input')?.value || '' : button.dataset.value, ...facts});
  let spaceButton = null;
  document.addEventListener('click', e => {
    if (!e.isTrusted) return;
    const facts = {button: e.button, detail: e.detail, pointerType: e.pointerType || ''};
    const link = e.target.closest?.('.link');
    if (link?.dataset.url) { send({t: 'ui', action: 'link', url: link.dataset.url, ...facts}); return; }
    const t = e.target.closest?.('[data-act]');
    if (t) {
      activateButton(t, facts);
      return;
    }
    if (view === 'answer' && e.target.closest?.('.card') && !String(getSelection())) send({t: 'ui', action: 'go', ...facts});
  }, true);
  for (const type of ['keydown', 'keyup']) document.addEventListener(type, e => {
    if (!e.isTrusted) return;
    const c = e.code;
    if (inField(e.target)) {
      // Private typing stays in this frame until it is sent.
      // Leave the field at once: the card fades for a moment, and the next key isn't typing.
      if (type === 'keydown' && c === 'Enter') { e.preventDefault(); const value = e.target.value; e.target.blur(); send({t: 'ui', action: 'submit', value}); }
      else if (type === 'keydown' && c === 'Escape') { e.target.blur(); send({t: 'ui', action: 'cancel'}); }
      return;
    }
    const button = document.activeElement?.closest?.('button[data-act]');
    if (button && (c === 'Enter' || c === 'Space')) {
      // Script-disabled frames have no native button key activation. Forward the
      // trusted gesture, not a synthetic click; keys never carry approval facts.
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      e.preventDefault();
      if (c === 'Enter' && type === 'keydown' && !e.repeat) activateButton(button);
      if (c === 'Space') {
        if (type === 'keydown' && !e.repeat) spaceButton = button;
        if (type === 'keyup') {
          if (spaceButton === button) activateButton(button);
          spaceButton = null;
        }
      }
      return;
    }
    if (c === 'Space' || c.startsWith('Arrow') || c === 'Escape' || c === 'KeyQ' || c === 'Enter' || c.startsWith('Alt') ||
        c === 'Backquote' || /^F\d+$/.test(c) || /^Digit[1-9]$/.test(c)) {
      if (!e.metaKey && !e.ctrlKey && !e.altKey) e.preventDefault();
      send({t: 'key', type, code: c, key: e.key, repeat: e.repeat, shift: e.shiftKey, meta: e.metaKey, ctrl: e.ctrlKey, alt: e.altKey});
    }
  }, true);
  document.addEventListener('blur', () => { spaceButton = null; }, true);
  // Report only interaction, never selection text or scroll position.
  document.addEventListener('wheel', e => {
    if (e.isTrusted && view === 'answer') send({t: 'engaged'});
  }, {passive: true});
  document.addEventListener('selectionchange', () => {
    if (view === 'answer' && !getSelection().isCollapsed) send({t: 'engaged'});
  });
  document.addEventListener('keydown', e => {
    if (e.isTrusted && view === 'answer' && ['PageUp', 'PageDown', 'Home', 'End'].includes(e.code))
      send({t: 'engaged'});
  });
  // Hover changes the footer, and only we can see that happen.
  document.documentElement.addEventListener('mouseenter', e => { if (e.isTrusted) { send({t: 'hover', on: true}); report(); } });
  document.documentElement.addEventListener('mouseleave', e => { if (e.isTrusted) { send({t: 'hover', on: false}); report(); } });
})();
