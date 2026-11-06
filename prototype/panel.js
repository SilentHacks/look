// Runs only through CDP in a script-disabled, opaque-origin frame (same structure as
// browser/panel.js). Holds every private string. setTimeout never fires here, so anything
// timed comes from outside; CSS animation, WAAPI and requestAnimationFrame do work.
(() => {
  if (window.__HG_PANEL__) return;
  const send = m => window.__hgProto(JSON.stringify(m));
  document.documentElement.style.cssText = 'background:transparent;overflow:hidden;height:100%';
  document.body.style.cssText = 'margin:0;background:transparent;height:100%';
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(`
    :root { color-scheme: light; --label:rgba(0,0,0,.86); --secondary:rgba(60,60,67,.72); --tertiary:rgba(60,60,67,.5);
      --accent:#0066d6; --red:#c9281e; --hover:rgba(0,0,0,.055); --line:rgba(0,0,0,.09);
      --shimmer-a:rgba(60,60,67,.68); --shimmer-b:rgba(0,0,0,.95); }
    :root.dark { --label:rgba(255,255,255,.92); --secondary:rgba(235,235,245,.68); --tertiary:rgba(235,235,245,.42);
      --accent:#4ea1ff; --red:#ff6b60; --hover:rgba(255,255,255,.08); --line:rgba(255,255,255,.11);
      --shimmer-a:rgba(235,235,245,.66); --shimmer-b:rgba(255,255,255,1); }
    * { box-sizing:border-box; }
    html,body { font:13px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;
      -webkit-font-smoothing:antialiased; color:var(--label); letter-spacing:-.006em; user-select:none; cursor:default; }
    button { all:unset; cursor:default; }
    #root { display:flex; flex-direction:column; width:100%; }

    /* Slivers: the neighbours in the stack, named by subject. */
    .peek { display:flex; align-items:center; gap:6px; height:30px; flex:none; padding:0 22px; font-size:12px; color:var(--secondary);
      transition:color .14s; white-space:nowrap; }
    .peek:hover { color:var(--label); }
    .peek .name { overflow:hidden; text-overflow:ellipsis; font-weight:500; }
    .peek .state { flex:none; color:var(--tertiary); }
    .peek .key { flex:none; margin-left:auto; color:var(--tertiary); font-size:12px; }

    .card { position:relative; padding:13px 16px 0; }
    .head { display:flex; align-items:baseline; gap:8px; min-height:18px; }
    .title { font-size:13.5px; font-weight:600; letter-spacing:-.012em; overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
    .slide-next { animation:slide-next .26s cubic-bezier(.2,.9,.3,1) both; }
    .slide-prev { animation:slide-prev .26s cubic-bezier(.2,.9,.3,1) both; }
    .arrive { animation:arrive .3s .07s cubic-bezier(.2,.9,.3,1) both; }
    @keyframes slide-next { from { opacity:0; transform:translateY(16px) } to { opacity:1; transform:none } }
    @keyframes slide-prev { from { opacity:0; transform:translateY(-16px) } to { opacity:1; transform:none } }
    @keyframes arrive { from { opacity:0; transform:translateY(5px) } to { opacity:1; transform:none } }

    .body { overflow-y:auto; overscroll-behavior:contain; margin:0 -16px; padding:0 16px; scrollbar-width:none; user-select:text; cursor:text; }
    .body::-webkit-scrollbar { display:none; }
    .body.clipped { mask-image:linear-gradient(#000 calc(100% - 26px),transparent); }
    .turn + .turn { margin-top:12px; padding-top:12px; border-top:.5px solid var(--line); }
    .q { margin-top:3px; color:var(--secondary); font-size:12.5px; line-height:1.35; }
    .a { margin-top:7px; font-size:13.5px; line-height:1.43; }
    .a p { margin:0; } .a p + p { margin-top:8px; }
    .w { animation:word .22s ease-out both; }
    @keyframes word { from { opacity:0; filter:blur(2px) } to { opacity:1; filter:none } }
    .static .w { animation:none; }

    .looking { margin-top:7px; font-size:13.5px; display:inline-block; color:var(--secondary); }
    .shimmer { background:linear-gradient(100deg,var(--shimmer-a) 30%,var(--shimmer-b) 50%,var(--shimmer-a) 70%);
      background-size:220% 100%; -webkit-background-clip:text; background-clip:text; color:transparent;
      animation:shimmer 1.5s linear infinite; }
    @keyframes shimmer { from { background-position:120% 0 } to { background-position:-100% 0 } }
    .err { margin-top:7px; font-size:13.5px; line-height:1.43; color:var(--label); }
    .retry { display:inline-block; margin-top:7px; color:var(--accent); font-weight:500; font-size:13px; }
    .retry:hover { text-decoration:underline; text-underline-offset:2px; }

.card.failed .body { padding-bottom:13px; } .card.failed .foot { display:none; }
    /* Plain-word controls, in the space a hint occupies until you hover. */
    .foot { position:relative; height:32px; margin-top:4px; font-size:12px; }
    .hint, .actions { position:absolute; inset:0; display:flex; align-items:center; gap:14px; transition:opacity .16s; }
    .hint { color:var(--tertiary); }
    .actions { opacity:0; pointer-events:none; }
    .card:hover .actions, .actions:focus-within { opacity:1; pointer-events:auto; }
    .card:hover .hint { opacity:0; }
    .act { color:var(--accent); font-weight:500; white-space:nowrap; }
    .act:hover { text-decoration:underline; text-underline-offset:2px; }
    .act.quiet { margin-left:auto; color:var(--secondary); font-weight:400; }
    .act.off { color:var(--tertiary); font-weight:400; text-decoration:none; }

    /* Capsule label */
    #pill { position:absolute; left:0; top:0; height:36px; display:inline-flex; align-items:center; white-space:nowrap;
      font-size:12.5px; font-weight:500; letter-spacing:-.008em; opacity:0; transition:opacity .2s; }
    #pill.on { opacity:1; }
    #pill.plain { color:var(--label); }

    /* Prototype sheet: visibly not part of the product. */
    #sheet { padding:14px 16px 12px; font-size:12.5px; }
    #sheet h1 { margin:0; font-size:13.5px; font-weight:600; }
    #sheet .sub { margin:2px 0 10px; color:var(--secondary); }
    .row { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:6px 0; border-top:.5px solid var(--line); }
    .seg { display:flex; gap:2px; padding:2px; border-radius:7px; background:var(--hover); }
    .seg button { padding:2px 9px; border-radius:5px; color:var(--secondary); white-space:nowrap; }
    .seg button.on { background:var(--accent); color:#fff; font-weight:500; }
    .keys { margin:8px 0 2px; color:var(--secondary); line-height:1.6; font-size:12px; }
    b.k { font-weight:600; color:var(--label); }

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

  // ---------- capsule label ----------
  function renderPill(m) {
    scheme(m.dark, m.reduce);
    let el = root.querySelector('#pill');
    if (!el) { el = h('div'); el.id = 'pill'; root.append(el); }
    if (m.text) { el.textContent = m.text; }
    el.classList.toggle('on', !!m.text);
    el.classList.toggle('plain', !m.shimmer);
    el.classList.toggle('shimmer', !!m.shimmer);
    send({t: 'size', frame: 'pill', w: Math.ceil(el.getBoundingClientRect().width), text: m.text || ''});
  }

  // ---------- answer card ----------
  let shown = null;            // current item id
  let turns = new Map();       // turn id -> {el, a:string, ansEl, status}
  let body = null, stick = true;

  function peekRow(kind, p) {
    const row = h('button', `peek ${kind}`);
    row.dataset.act = kind;
    row.append(h('span', 'name', p.subject));
    if (p.state) row.append(h('span', 'state', `· ${p.state}`));
    row.append(h('span', 'key', kind === 'next' ? '↓' : '↑'));
    return row;
  }

  function appendWords(ans, text, animate) {
    let p = ans.lastElementChild;
    if (!p) { p = h('p'); ans.append(p); }
    for (const tok of text.split(/(\n\n|\s+)/)) {
      if (!tok) continue;
      if (tok === '\n\n') { p = h('p'); ans.append(p); continue; }
      if (/^\s+$/.test(tok)) { p.append(document.createTextNode(' ')); continue; }
      const w = h('span', 'w', tok);
      if (!animate) w.style.animation = 'none';
      p.append(w);
    }
  }

  function renderTurn(t, node) {
    // node: {el, a, ans, state}
    const state = t.status;
    if (node.state !== state) {
      const wasText = node.ans && (state === 'streaming' || state === 'done');
      if (!wasText) {
        node.ans?.remove(); node.look?.remove(); node.err?.remove(); node.retry?.remove();
        node.ans = node.look = node.err = node.retry = null; node.a = '';
        if (state === 'waiting' || state === 'thinking') {
          node.look = h('div', 'looking shimmer', state === 'waiting' ? 'Waiting its turn…' : 'Looking into it…');
          node.el.append(node.look);
        } else if (state === 'error') {
          node.err = h('div', 'err', t.error);
          node.retry = h('button', 'retry', 'Try again');
          node.retry.dataset.act = 'retry';
          node.retry.dataset.turn = t.id;
          node.el.append(node.err, node.retry);
          root.querySelector('.card')?.classList.add('failed');
        } else {
          node.ans = h('div', 'a');
          node.el.append(node.ans);
        }
      }
      node.state = state;
    }
    if (node.ans && t.a.length > node.a.length) {
      appendWords(node.ans, t.a.slice(node.a.length), node.live);
      node.a = t.a;
    }
    node.live = true;
  }

  function renderCard(m) {
    scheme(m.dark, m.reduce);
    if (!m.item) { root.textContent = ''; shown = null; turns = new Map(); body = null; send({t: 'size', frame: 'card', prevH: 0, cardH: 0, nextH: 0}); return; }
    const swap = shown !== m.item.id;
    if (swap) {
      root.textContent = '';
      turns = new Map(); stick = true;
      shown = m.item.id;
      const card = h('div', `card ${m.dir === 'next' ? 'slide-next' : m.dir === 'prev' ? 'slide-prev' : 'arrive'}`);
      const head = h('div', 'head');
      head.append(h('div', 'title', m.item.subject));
      body = h('div', 'body');
      body.addEventListener('scroll', () => {
        stick = body.scrollHeight - body.scrollTop - body.clientHeight < 12;
        clip();
      });
      const foot = h('div', 'foot');
      card.append(head, body, foot);
      root.append(card);
    }
    const card = root.querySelector('.card');
    root.querySelector('.title').textContent = m.item.subject;
    // Neighbours
    for (const kind of ['prev', 'next']) {
      const old = root.querySelector(`.peek.${kind}`);
      const want = m[kind];
      if (old && (!want || old.dataset.sig !== JSON.stringify(want))) old.remove();
      if (want && !root.querySelector(`.peek.${kind}`)) {
        const row = peekRow(kind, want);
        row.dataset.sig = JSON.stringify(want);
        if (kind === 'prev') root.prepend(row); else root.append(row);
      }
    }
    // Turns
    if (!m.item.turns.some(t => t.status === 'error')) card.classList.remove('failed');
    for (const t of m.item.turns) {
      let node = turns.get(t.id);
      if (!node) {
        const el = h('div', 'turn');
        el.append(h('div', 'q', t.q));
        body.append(el);
        node = {el, a: '', state: null, live: !swap};
        turns.set(t.id, node);
      }
      renderTurn(t, node);
    }
    // Footer: a plain hint until you hover, then plain words.
    const foot = root.querySelector('.foot');
    const sig = JSON.stringify([m.hint, m.reading, m.item.lost, m.item.host, m.item.gone]);
    if (foot.dataset.sig !== sig) {
      foot.dataset.sig = sig;
      foot.textContent = '';
      const hint = h('div', 'hint', m.hint || '');
      const actions = h('div', 'actions');
      const go = h('button', m.item.gone ? 'act off' : 'act', m.item.gone ? 'No longer on this page' : m.item.lost ? `Back to ${m.item.host}` : 'Show on page');
      if (!m.item.gone) go.dataset.act = 'go';
      const read = h('button', 'act', m.reading ? 'Stop reading' : 'Read aloud');
      read.dataset.act = 'read';
      const close = h('button', 'act quiet', 'Dismiss');
      close.dataset.act = 'dismiss';
      actions.append(go, read, close);
      foot.append(hint, actions);
    }
    body.style.maxHeight = `${Math.max(60, m.maxBody || 400)}px`;
    if (stick) body.scrollTop = body.scrollHeight;
    clip();
    report();
  }

  function clip() {
    if (body) body.classList.toggle('clipped', body.scrollHeight - body.scrollTop - body.clientHeight > 6);
  }
  function report() {
    const size = el => el ? Math.ceil(el.getBoundingClientRect().height) : 0;
    send({t: 'size', frame: 'card', prevH: size(root.querySelector('.peek.prev')), cardH: size(root.querySelector('.card')),
      nextH: size(root.querySelector('.peek.next')), contentH: body ? body.scrollHeight : 0, bodyH: body ? body.clientHeight : 0});
  }

  // ---------- prototype sheet ----------
  function renderSheet(m) {
    scheme(m.dark, m.reduce);
    root.textContent = '';
    const s = h('div'); s.id = 'sheet';
    s.append(h('h1', '', 'Prototype controls'), h('div', 'sub', 'Not part of the product. Sample answers only.'));
    for (const r of m.rows) {
      const row = h('div', 'row');
      row.append(h('span', '', r.label));
      const seg = h('div', 'seg');
      for (const [value, word] of r.options) {
        const b = h('button', value === r.value ? 'on' : '', word);
        b.dataset.act = 'set'; b.dataset.key = r.key; b.dataset.value = value;
        seg.append(b);
      }
      row.append(seg);
      s.append(row);
    }
    const keys = h('div', 'keys');
    keys.append('Hold ', h('b', 'k', 'Space'), ' and talk · ', h('b', 'k', '↑ ↓'), ' move · ', h('b', 'k', 'Q'), ' bring back · ', h('b', 'k', 'Esc'), ' dismiss · ', h('b', 'k', '?'), ' this sheet');
    s.append(keys);
    root.append(s);
    send({t: 'size', frame: 'sheet', h: Math.ceil(s.getBoundingClientRect().height)});
  }

  window.__HG_PANEL__ = { render(m) {
    if (m.kind === 'pill') renderPill(m);
    else if (m.kind === 'card') renderCard(m);
    else if (m.kind === 'sheet') renderSheet(m);
  }};

  // ---------- trusted input only; nothing reaches the page ----------
  document.addEventListener('click', e => {
    if (!e.isTrusted) return;
    const t = e.target.closest?.('[data-act]');
    if (t) { send({t: 'ui', action: t.dataset.act, turn: t.dataset.turn, key: t.dataset.key, value: t.dataset.value}); return; }
    // A click on the card means "take me back", unless you were selecting text.
    if (e.target.closest?.('.card') && !String(getSelection())) send({t: 'ui', action: 'go'});
  }, true);
  for (const type of ['keydown', 'keyup']) document.addEventListener(type, e => {
    if (!e.isTrusted) return;
    const c = e.code;
    if (c === 'Space' || c.startsWith('Arrow') || c === 'Escape' || c === 'KeyQ' || c === 'Enter' || (e.key === '?')) {
      if (!e.metaKey && !e.ctrlKey && !e.altKey) e.preventDefault();
      send({t: 'key', type, code: c, key: e.key, repeat: e.repeat, shift: e.shiftKey, meta: e.metaKey, ctrl: e.ctrlKey, alt: e.altKey});
    }
  }, true);
  document.documentElement.addEventListener('mouseenter', () => send({t: 'hover', on: true}));
  document.documentElement.addEventListener('mouseleave', () => send({t: 'hover', on: false}));
  send({t: 'panelReady'});
})();
