(function () {
  // Main frame only — addScriptToEvaluateOnNewDocument runs in EVERY frame; untrusted
  // iframes must not render a second overlay or reach the intent binding.
  if (window.top !== window.self) return;

  // Always tear down any prior overlay instance cleanly (removing window listeners & streams)
  const prevApi = window.__HERMES_GAZE_OVERLAY__;
  const prevState = prevApi && prevApi.state ? prevApi.state : null;
  const existingRoot = document.getElementById("hermes-gaze-root");
  if (prevApi && typeof prevApi.destroy === "function") {
    try {
      prevApi.destroy();
    } catch (_) {}
  }
  if (existingRoot) {
    existingRoot.remove();
  }

  const state = {
    mode: (prevState && prevState.mode) || "hover",
    sigmaPx: (prevState && prevState.sigmaPx) || 120,
    hoverSigmaPx: (prevState && prevState.hoverSigmaPx) || 24,
    dwellMs: (prevState && prevState.dwellMs) || 450,
    wiggleTrigger: prevState && prevState.wiggleTrigger !== undefined ? prevState.wiggleTrigger : false,
    candidateRadiusPx: (prevState && prevState.candidateRadiusPx) || 380,
    hotkey: (prevState && prevState.hotkey) || "Backquote",
    answerTurnMs: (prevState && prevState.answerTurnMs) || 12000,
    resolutionId: 0,
    scopes: [],
    selectedScopeId: null,
    scopePending: false,
    armed: false, // When true, lockedX / lockedY stay frozen while the typed-question card is up
    armedAt: 0,
    // null until the first real mousemove — a fabricated center point is never a valid pointer
    pointerX: prevState && typeof prevState.pointerX === "number" ? prevState.pointerX : null,
    pointerY: prevState && typeof prevState.pointerY === "number" ? prevState.pointerY : null,
    choosePending: false,
    lockedX: null,
    lockedY: null,
    ringBuffer: prevState && Array.isArray(prevState.ringBuffer) ? prevState.ringBuffer.slice(-250) : [], // {x_vp, y_vp, x_doc, y_doc, t, sigma}
    wiggleHistory: [],
    lensActive: false,
    lensCandidates: [],
    hoveredCandidate: null,
  };

  // ---------- tuning ----------
  const CARD_W = 348, PILL_H = 36, ARM_MS = 130, MIN_HOLD_MS = 220, DWELL_MS = 170, MAX_TARGETS = 5;
  const REGION_W = 360, REGION_H = 225, MARGIN = 14, FOLLOW_UP_PX = 90, READING_WPS = 3.6;
  const SPRING = {k: 420, c: 36};        // general: quick, barely overshoots
  const SNAPPY = {k: 620, c: 40};        // rings
  const FOLLOW = {k: 300, c: 28};        // waveform trailing the cursor
  const GAZE = {k: 60, c: 15};           // soft region: slow, heavy, like smoothed gaze

  // ---------- local view state; what must survive a tab or navigation lives in Python ----------
  const S = {
    pointer: {moved: 0},
    keyDown: false, keyArmed: false, armShift: false, armTimer: 0, hold: null,
    items: [], cur: "", view: null, pos: null, capSpot: null, hoverCard: false, retreatTimer: 0, retreatAt: 0,
    ids: 0, sizes: {prevH: 0, cardH: 0, nextH: 0, contentH: 0, bodyH: 0}, maxBody: 420, dark: false, dir: null,
    coach: {greeted: false, heard: 0, answered: 0, retreated: false}, pillMode: "none", pillW: 96, pillLast: "",
    micReady: false, micWarning: "", micSlow: false, localPending: [], compose: null, note: null, frameY: 0, frameH: 0,
    wasBusy: false, cardFade: 0, shown: new Set(), reposition: new Set(), ready: false,
  };
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const reducedTransparency = () => matchMedia("(prefers-reduced-transparency: reduce)").matches;

  // ---------- springs ----------
  const springs = new Set(), fades = new Set();
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
  // Pinch zoom shrinks what's visible; the card fits the visible part.
  const cardWidth = () => {
    const v = window.visualViewport, zoomed = v && v.scale > 1.01;
    return Math.min(CARD_W, zoomed ? v.width - 8 : innerWidth - 2 * MARGIN);
  };
  const box = (x, y, w, h, p) => ({x: new Spring(x, p), y: new Spring(y, p), w: new Spring(w, p), h: new Spring(h, p), o: new Fade(0)});

  // ---------- geometry-only DOM: rings and text-free glass plates, in a closed shadow ----------
  // Words, voice level and input all live in the two sandboxed frames, reached only over CDP.
  const host = document.createElement("div");
  host.id = "hermes-gaze-root";
  host.setAttribute("popover", "manual");
  host.style.cssText = "all:initial!important;position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;margin:0!important;padding:0!important;border:0!important;pointer-events:none!important;background:transparent!important;overflow:visible!important;contain:none!important";
  const hostStyle = host.style.cssText;
  document.documentElement.appendChild(host);
  host.showPopover();
  const visualShadow = host.attachShadow({ mode: "closed" });
  const layerCss = new CSSStyleSheet();
  layerCss.replaceSync(`
    * { box-sizing:border-box; }
    .ring { position:fixed; left:0; top:0; pointer-events:none; will-change:transform,width,height; border-radius:9px;
      background:rgba(var(--a),var(--fill)); box-shadow:0 0 0 var(--stroke) rgba(var(--a),var(--edge)), 0 0 0 calc(var(--stroke) + 4px) rgba(var(--a),var(--halo)); }
    .ring.region { border-radius:50%; box-shadow:none; background:radial-gradient(closest-side, rgba(var(--a),calc(var(--fill)*3.2)) 0%, rgba(var(--a),calc(var(--fill)*2.6)) 45%, rgba(var(--a),calc(var(--fill)*.8)) 78%, rgba(var(--a),0) 100%); }
    .plate { position:fixed; left:0; top:0; pointer-events:none; will-change:transform,width,height,opacity;
      background:var(--fill); -webkit-backdrop-filter:var(--blur); backdrop-filter:var(--blur); box-shadow:var(--shadow); }
    .plate.sliver { background:var(--fill-2); box-shadow:var(--shadow-2); }
    .light { --fill:rgba(250,250,252,.8); --fill-2:rgba(247,247,250,.68); --blur:blur(34px) saturate(1.9);
      --shadow:0 0 0 .5px rgba(0,0,0,.13), 0 12px 36px rgba(0,0,0,.17), 0 3px 8px rgba(0,0,0,.07), inset 0 .5px 0 rgba(255,255,255,.75);
      --shadow-2:0 0 0 .5px rgba(0,0,0,.11), 0 8px 22px rgba(0,0,0,.11), inset 0 .5px 0 rgba(255,255,255,.6); }
    .dark { --fill:rgba(40,40,44,.76); --fill-2:rgba(50,50,54,.66); --blur:blur(34px) saturate(1.7);
      --shadow:0 0 0 .5px rgba(255,255,255,.15), 0 14px 44px rgba(0,0,0,.55), 0 3px 8px rgba(0,0,0,.3), inset 0 .5px 0 rgba(255,255,255,.1);
      --shadow-2:0 0 0 .5px rgba(255,255,255,.12), 0 8px 24px rgba(0,0,0,.4), inset 0 .5px 0 rgba(255,255,255,.08); }
    .solid.light { --fill:rgb(250,250,252); --fill-2:rgb(240,240,243); --blur:none; }
    .solid.dark { --fill:rgb(44,44,47); --fill-2:rgb(58,58,62); --blur:none; }
    .wrap { position:fixed; left:0; top:0; overflow:hidden; will-change:transform,width,height,opacity; }
    iframe { display:block; border:0; background:transparent; color-scheme:normal; }
    #pill { overflow:hidden; }
  `);
  visualShadow.adoptedStyleSheets = [layerCss];
  const add = (tag, cls, parent) => { const n = document.createElement(tag); if (cls) n.className = cls; parent.append(n); return n; };
  function privateFrame(parent, width, height) {
    const f = document.createElement("iframe");
    f.setAttribute("sandbox", "");
    f.setAttribute("aria-label", "Hermes private surface");
    f.style.width = `${width}px`; f.style.height = `${height}px`;
    parent.append(f);
    return f;
  }
  const rings = add("div", "", visualShadow);
  const plates = [];   // [prev, next2, next, front]
  for (let i = 0; i < 4; i++) {
    const plate = add("div", "plate light" + (i < 3 ? " sliver" : ""), visualShadow);
    plate.style.opacity = 0;
    plates.push(plate);
  }
  const cardWrap = add("div", "wrap", visualShadow);
  cardWrap.style.opacity = 0; cardWrap.style.pointerEvents = "none";
  const uiFrame = privateFrame(cardWrap, CARD_W, Math.max(900, innerHeight));
  const pillEl = add("div", "plate light", visualShadow);
  pillEl.id = "pill";
  pillEl.style.opacity = 0;
  const pillWrap = add("div", "wrap", pillEl);
  pillWrap.style.pointerEvents = "none";
  const pillFrame = privateFrame(pillWrap, 460, PILL_H);
  pillFrame.style.pointerEvents = "none";
  const uiFrames = {card: uiFrame, pill: pillFrame};
  const front = box(0, 0, CARD_W, 0), prev = box(0, 0, CARD_W, 0), next = box(0, 0, CARD_W, 0), next2 = box(0, 0, CARD_W, 0);
  const P = {pill: box(0, 0, 0, PILL_H)};
  const lift = new Spring(0, {k: 500, c: 30}); // nudge when you hit the end of the stack

  function rawSend(message) { try { window.__hermesGazeIntent(JSON.stringify(message)); } catch (_) {} }
  function trustedUi(event) { return event.isTrusted === true; }

  // A website dialog opened after us would otherwise sit on top of the top layer.
  function raise() { try { host.hidePopover(); host.showPopover(); } catch (_) {} }
  let raisedFor = 0;
  function raiseIfShowing() {
    if (destroyed || (!S.view && S.pillMode === "none" && !S.hold)) return;
    const now = performance.now();
    if (now - raisedFor < 120) return;
    raisedFor = now;
    raise();
  }
  const dialogWatch = new MutationObserver(records => {
    if (records.some(r => r.target !== host && r.target.hasAttribute?.("open"))) raiseIfShowing();
  });
  dialogWatch.observe(document.documentElement, {subtree: true, attributes: true, attributeFilter: ["open"]});
  // Only someone else's popover opening matters; our own re-raise fires toggle too.
  const onTopLayer = e => { if (e.target !== host && (e.type !== "toggle" || e.newState === "open")) raiseIfShowing(); };
  document.addEventListener("toggle", onTopLayer, true);
  document.addEventListener("fullscreenchange", onTopLayer, true);

  // Tampered geometry or visibility rejects private input: a site may hide us, not fake a click.
  function surfaceIntact() {
    if (document.visibilityState !== "visible" || !document.hasFocus()) return false;
    const surface = getComputedStyle(host);
    return host.style.cssText === hostStyle && host.matches(":popover-open") &&
      surface.visibility === "visible" && surface.opacity === "1" &&
      surface.transform === "none" && surface.filter === "none" &&
      surface.clipPath === "none" && surface.maskImage === "none" &&
      surface.scale === "none" && surface.rotate === "none" && surface.translate === "none";
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
        if (n === host) continue;
        const l = luminance(getComputedStyle(n).backgroundColor);
        if (l != null) { l < .42 ? dark++ : light++; break; }
      }
    }
    if (!dark && !light) {
      // Transparent all the way down: trust the root, then the page's own scheme.
      const l = luminance(getComputedStyle(document.documentElement).backgroundColor) ?? (document.body && luminance(getComputedStyle(document.body).backgroundColor));
      return l != null ? l < .42 : getComputedStyle(document.documentElement).colorScheme.startsWith("dark");
    }
    return dark > light;
  }
  function setTone(dark) {
    S.dark = dark;
    const cls = (dark ? " dark" : " light") + (reducedTransparency() ? " solid" : "");
    plates.forEach((p, i) => { p.className = "plate" + (i < 3 ? " sliver" : "") + cls; });
    pillEl.className = "plate" + cls;
  }

  // Identities stay in this closure: a selector is metadata, never a historical lookup.
  const cursorIds = new WeakMap();
  let litIds = [], cursorOverHud = false;
  const cursorRefs = new Map();
  const cursorHistory = [];
  let cursorSerial = 0;
  let lockedNode = null;
  const snapshots = new Map();
  const snapshotInstance = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  let snapshotSerial = 0;
  let activeSnapshot = null;
  let destroyed = false;
  let confirmation = null;
  let actionApproval = null;
  let actionTask = null;
  let inbox = null;
  let inboxRevision = -1;
  const fingerprints = new WeakMap();
  let fingerprintSerial = 0;
  function actionFacts(el) {
    const tag = el.tagName.toLowerCase();
    const type = String(el.type || el.getAttribute("type") || "").toLowerCase();
    const role = el.getAttribute("role") || "";
    return { tag, type, role, label: safeLabel(el), class_name: String(el.className || "").slice(0, 300),
      url: tag === "a" ? safeActionUrl(el.getAttribute("href")) : "",
      new_tab: tag === "a" && el.getAttribute("target") === "_blank",
      same_document: tag === "a" && String(el.getAttribute("href") || "").includes("#") &&
        String(el.href || "").split("#")[0] === location.href.split("#")[0],
      form_submit: !!(el.form || el.closest("form")) && (tag === "button" && (!type || type === "submit") ||
        tag === "input" && (type === "submit" || type === "image")),
      disabled: !!el.disabled || el.matches(":disabled") || el.getAttribute("aria-disabled") === "true" || !!el.closest("[inert]"),
      clickable: tag === "button" || tag === "a" && !!el.getAttribute("href") ||
        tag === "input" && ["button", "submit", "reset", "checkbox", "radio", "image"].includes(type) ||
        ["button", "link", "tab", "checkbox", "radio"].includes(role) };
  }
  function fingerprint(el) {
    const descriptor = JSON.stringify([cursorId(el), actionFacts(el), el.getAttribute("href"),
      el.getAttribute("formaction"), (el.form || el.closest("form")) ? cursorId(el.form || el.closest("form")) : null,
      (el.form || el.closest("form"))?.getAttribute("action"), (el.form || el.closest("form"))?.getAttribute("method"),
      el.getAttribute("id"), el.getAttribute("name"), el.getAttribute("onclick"), el.getAttribute("target")]);
    const previous = fingerprints.get(el);
    if (previous?.descriptor === descriptor) return previous.token;
    const token = `${snapshotInstance}:fingerprint:${++fingerprintSerial}`;
    fingerprints.set(el, { descriptor, token });
    return token;
  }
  const sensitiveSelector = 'input[type="password"],[autocomplete^="cc-"],[autocomplete="current-password"],[autocomplete="new-password"],[name*="card" i],[name*="payment" i],[name*="cvv" i],[name*="cvc" i],[name^="cc-" i],[id*="card" i],[id*="payment" i],[id*="cvv" i],[id*="cvc" i],[id^="cc-" i]';
  function sensitive(el) {
    let field = el && (el.closest("input,textarea,select,[contenteditable]") || el.closest("label")?.control);
    for (let host = el?.getRootNode?.().host; !field && host; host = host.getRootNode?.().host)
      field = host.closest("input,textarea,select,[contenteditable]");
    if (!field) return false;
    const tokens = (field.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/);
    const descriptor = ["name", "id", "aria-label", "placeholder", "autocomplete"].map(k => field.getAttribute(k) || "").join(" ") +
      " " + [...(field.labels || [])].map(label => label.textContent || "").join(" ");
    return field.matches(sensitiveSelector) ||
      /password|passcode|passphrase|payment|credit.?card|debit.?card|card.?number|card.?holder|expir(?:y|ation)|valid.?thru|cvv|cvc|secret|token|api.?key|access.?key|private.?key|credential|bearer|otp|one.?time|verification.?code|security.?code|security.?answer|(?:^|[^a-z])pin(?:$|[^a-z])|ssn|social.?security|routing|iban|bank.?account|account.?number/i.test(descriptor) ||
      tokens.some(token => token.startsWith("cc-") || ["current-password", "new-password", "one-time-code"].includes(token));
  }
  function rendered(el) {
    return el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  }
  const contextHeadings = "h1,h2,h3,h4,h5,h6,[role=heading],.panel-title";
  const contextRegions = "article,section,.card,[role=region]";
  function ownHeading(container, excluded = null, before = null) {
    let label = "", visited = 0;
    for (const heading of container.querySelectorAll(contextHeadings)) {
      if (++visited > 128) break;
      if (!rendered(heading) || heading.closest(contextRegions) !==
          (container.matches(contextRegions) ? container : container.closest(contextRegions)) ||
          heading.closest("form,label,input,textarea,select,[contenteditable]") ||
          before && !(heading.compareDocumentPosition(before) & 4)) continue;
      let node = heading;
      while (node && node !== container && !excluded?.has(node)) node = node.parentElement;
      if (excluded?.has(node)) continue;
      label = safeText(heading, 80);
      if (label && !before) break;
    }
    return label;
  }
  function safeText(el, max = 160, excluded = null) {
    if (!el) return "";
    if (sensitive(el)) return "[redacted]";
    for (let node = el; node; node = node.getRootNode?.().host)
      if (node.closest("input,textarea,select,[contenteditable]")) return "";
    if (el.matches("label") && el.htmlFor && sensitive(el.getRootNode?.().getElementById?.(el.htmlFor) || document.getElementById(el.htmlFor))) return "[redacted]";
    if (!rendered(el) && getComputedStyle(el).display !== "contents") return "";
    // Never read field values, labels/attributes, or ancestor innerText wholesale.
    const parts = [];
    const walker = document.createTreeWalker(el.shadowRoot || el, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.nodeType === 1 && (excluded?.has(node) ||
            node.matches('input,textarea,select,[contenteditable],script,style,#hermes-gaze-root') || sensitive(node) ||
            !rendered(node) && getComputedStyle(node).display !== "contents"))
          return NodeFilter.FILTER_REJECT;
        if (node.nodeType === 1 && node.matches("label") && node.htmlFor &&
            sensitive(node.getRootNode?.().getElementById?.(node.htmlFor) || document.getElementById(node.htmlFor))) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    let node, visited = 0, length = 0;
    while ((node = walker.nextNode()) && visited++ < 120 && length < max) {
      if (node.nodeType !== 3) continue;
      const text = node.textContent.slice(0, max - length).trim().replace(/\s+/g, " ");
      if (text) { parts.push(text); length += text.length + 1; }
    }
    return parts.join(" ").slice(0, max);
  }
  function safeLabel(el, max = 100, excluded = null) {
    if (sensitive(el) || (el.matches("label") && el.htmlFor && sensitive(el.getRootNode?.().getElementById?.(el.htmlFor) || document.getElementById(el.htmlFor))))
      return "[redacted]";
    return (el.getAttribute("aria-label") || el.getAttribute("title") || safeText(el, max, excluded)).slice(0, max);
  }
  function secretQuery(name, value) {
    name = name.replace(/([a-z0-9])([A-Z])/g, "$1_$2");
    // ponytail: same bounded conservative opaque-value heuristic as Python's serializer.
    return /(?:^|[^a-z0-9])(?:token|key|secret|password|passwd|pwd|auth|authorization|session|sessionid|signature|sig|code|credential|credentials|jwt|bearer|nonce|csrf|xsrf|apikey|accesstoken)(?:$|[^a-z0-9])/i.test(name) ||
      value.length >= 32 && new Set(value).size >= 16 && !/\s/.test(value);
  }
  function safeLinks(el) {
    const links = [];
    const candidates = [el.closest("a[href]"), ...el.querySelectorAll("a[href]")];
    for (const link of candidates.slice(0, 120)) {
      if (!link || links.length >= 3) continue;
      let excluded = false;
      for (let node = link; node; node = node.parentElement || node.getRootNode?.().host) {
        if (sensitive(node) || node.matches("input,textarea,select,[contenteditable],#hermes-gaze-root") ||
            node.matches("label") && node.htmlFor && sensitive(node.getRootNode?.().getElementById?.(node.htmlFor) || document.getElementById(node.htmlFor))) {
          excluded = true;
          break;
        }
      }
      if (excluded || !rendered(link)) continue;
      try {
        const href = link.getAttribute("href");
        if (href.length > 8192) continue;
        const url = new URL(href, document.baseURI || location.href);
        url.username = "";
        url.password = "";
        const params = Array.from(url.searchParams);
        if (params.length > 128) continue;
        url.search = "";
        for (const [name, value] of params)
          if (!secretQuery(name, value)) url.searchParams.append(name, value);
        url.hash = "";
        if (["http:", "https:"].includes(url.protocol) && url.href.length <= 600 && !links.includes(url.href))
          links.push(url.href);
      } catch (_) {}
    }
    return links;
  }
  function cursorId(el) {
    if (!cursorIds.has(el)) cursorIds.set(el, `@${++cursorSerial}`);
    return cursorIds.get(el);
  }
  function hitNode(x, y) {
    if (typeof x !== "number" || typeof y !== "number") return null;
    let el = document.elementFromPoint(x, y);
    if (el?.closest("#hermes-gaze-root")) return null;
    for (let depth = 0; el?.shadowRoot && depth < 16; depth++) {
      const inner = el.shadowRoot.elementFromPoint(x, y);
      if (!inner || inner === el) break;
      el = inner;
    }
    return el;
  }
  function rememberHit(el, now = Date.now() / 1000) {
    const id = el ? cursorId(el) : null;
    if (el) cursorRefs.set(id, el);
    const last = cursorHistory[cursorHistory.length - 1];
    if (last && last.id === id) { last.end = now; last.last_seen = now; }
    else {
      if (last) last.end = now;
      cursorHistory.push({ id, start: now, end: now, last_seen: now });
    }
    while (cursorHistory.length > 256 || (cursorHistory.length > 1 && cursorHistory[0].end < now - 60))
      cursorHistory.shift();
    const keep = new Set(cursorHistory.map(h => h.id));
    for (const id of litIds) keep.add(id);
    for (const target of S.hold?.targets || []) if (target.hit) keep.add(cursorId(target.hit));
    for (const key of cursorRefs.keys()) if (!keep.has(key)) cursorRefs.delete(key);
  }
  function cursorMetadata(el) {
    const r = el.getBoundingClientRect();
    const hidden = sensitive(el);
    const visible = el.isConnected && rendered(el);
    let covering = null;
    for (let node = el; node && node !== document.body; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (node.matches("dialog,[role=dialog],[aria-modal=true]") ||
          ["fixed", "sticky"].includes(style.position) && node.getBoundingClientRect().width > window.innerWidth / 2) {
        covering = node;
        break;
      }
    }
    const surface = el.matches("iframe,frame") ?
      "Pointer is on an embedded frame; its content was not read. Underlying page content is covered at the pointer." :
      covering ? "Pointer is on an overlay/dialog or wide fixed/sticky surface; underlying page content may be covered." :
      el.matches("canvas,object,embed") || el.tagName.includes("-") && !el.shadowRoot && !safeText(el) ?
        "Embedded or closed component content was not readable." : "";
    return { id: cursorId(el), available: visible && !hidden,
      ...(hidden ? { sensitive: true, reason: "sensitive target redacted" } :
        !visible ? { reason: "target not rendered" } : {}),
      tag: el.tagName.toLowerCase(), role: (el.getAttribute("role") || el.tagName.toLowerCase()).slice(0, 40),
      label: hidden ? "[redacted]" : visible ? safeLabel(el, 100) : "",
      ...(surface ? { surface } : {}),
      ...(!hidden && visible ? { urls: safeLinks(el) } : {}),
      selector: hidden ? "" : buildSelector(el).slice(0, 350),
      rect_vp: [r.left, r.top, r.width, r.height],
      rect_doc: [r.left + scrollX, r.top + scrollY, r.width, r.height], block_ids: [] };
  }
  function captureCursorContext() {
    if (!state.armed && typeof state.pointerX === "number" && !cursorOverHud)
      rememberHit(hitNode(state.pointerX, state.pointerY));
    clearActionConfirmation();
    const snapshotId = `${snapshotInstance}:${++snapshotSerial}`;
    const identities = new Map();
    const capture = { version: 1, snapshot_id: snapshotId, captured_at: Date.now() / 1000, page_url: location.origin + location.pathname,
      page_title: String(document.title || "").slice(0, 160),
      history: cursorHistory.map(h => ({ ...h })), targets: [], blocks: [], controls: [], handles: {},
      lit: litIds.slice(0, 5) };
    let capturedMembers = 0;
    function handle(node) {
      const id = cursorId(node);
      if (!capture.handles[id] && !sensitive(node) && identities.size < 8192) {
        const r = node.getBoundingClientRect();
        const facts = actionFacts(node);
        capture.handles[id] = { selector: buildSelector(node).slice(0, 350), rect_vp: [r.left, r.top, r.width, r.height],
          kind: facts.role || facts.tag, ...facts };
        identities.set(id, { node, fingerprint: fingerprint(node), kind: facts.role || facts.tag });
      }
      return id;
    }
    const blocks = new Map();
    const groups = new Map();
    function unwrap(node) {
      for (let depth = 0; depth < 4 && node.matches("div,span") &&
           !node.matches(".card") && node.children.length === 1; depth++) node = node.children[0];
      return node;
    }
    function inView(node) {
      const r = node.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && r.left < window.innerWidth && r.top < window.innerHeight &&
        r.left + r.width > 0 && r.top + r.height > 0;
    }
    function captureGroup(el) {
      // ponytail: bounded DOM/layout groups; portals and canvas need a visual fallback.
      let branch = el;
      for (let depth = 0; branch?.parentElement && depth < 8; depth++, branch = branch.parentElement) {
        const parent = branch.parentElement;
        if (parent === document.body || parent === document.documentElement) break;
        const item = unwrap(branch);
        const collection = parent.matches("ul,ol,[role=list],[role=group],[role=grid]") ||
          ["flex", "inline-flex", "grid", "inline-grid"].includes(getComputedStyle(parent).display);
        const itemClass = branch.getAttribute("class");
        const repeatedLinks = branch.matches("div") && itemClass && branch.querySelector("a[href]") &&
          [...parent.children].slice(0, 128).filter(child => child.tagName === branch.tagName &&
            child.getAttribute("class") === itemClass && child.querySelector("a[href]")).length >= 3;
        let group = groups.get(parent);
        if (!group) {
          const items = [];
          let scanned = 0;
          for (const child of parent.children) {
            if (scanned++ >= 128) break;
            const node = unwrap(child);
            if (!rendered(node) || sensitive(node) ||
                node.matches("section,main,aside,nav,header,footer,form,[role=region]")) continue;
            const r = node.getBoundingClientRect();
            if (r.width > 0 && r.height > 0 && (node.matches("article,li,[role=listitem],.card") ||
                collection && ownHeading(node) || repeatedLinks && child.tagName === branch.tagName &&
                child.getAttribute("class") === itemClass && node.querySelector("a[href]"))) items.push(node);
          }
          if (items.length >= 2 && (items.includes(item) || scanned > 128 &&
              rendered(item) && (item.matches("article,li,[role=listitem],.card") || collection && ownHeading(item) || repeatedLinks))) {
            if (!items.includes(item)) items.push(item);
            const excluded = new Set(items);
            let owner = parent, label = "";
            for (let level = 0; owner && owner !== document.body && level < 8; level++, owner = owner.parentElement) {
              label = ownHeading(owner, excluded);
              if (label || owner.matches("section,[role=region],main,aside,dialog")) break;
            }
            const id = handle(parent);
            const block = { id, kind: "group", label: (label || parent.getAttribute("aria-label") || "").slice(0, 80),
              text: safeText(owner && owner !== document.body ? owner : parent, 300, excluded), text_limit: 300, members: [],
              total_items: items.length, collection_limited: scanned > 128 };
            group = { block, items, pointed: new Set(), facts: new Map() };
            groups.set(parent, group);
            blocks.set(id, block);
          }
        }
        if (group && (group.items.includes(item) || rendered(item) &&
            (item.matches("article,li,[role=listitem],.card") || collection && ownHeading(item) || repeatedLinks))) {
          if (!group.items.includes(item)) group.items.push(item);
          group.pointed.add(item);
          const peers = group.items.filter(node => !group.pointed.has(node));
          const kept = [...group.pointed, ...peers.filter(inView), ...peers.filter(node => !inView(node))]
            .slice(0, Math.max(16, group.pointed.size));
          group.block.members = kept.map(node => {
            if (!group.facts.has(node)) {
              const metadata = cursorMetadata(node);
              group.facts.set(node, { id: handle(node), role: metadata.role, label: ownHeading(node) || metadata.label,
                text: safeText(node, 300), urls: metadata.urls, rect_vp: metadata.rect_vp, in_view: inView(node) });
            }
            return group.facts.get(node);
          });
          group.block.total_items = group.items.length;
          group.block.omitted_items = group.items.length - kept.length;
          group.block.offscreen_items = group.items.filter(node => !inView(node)).length;
          return { id: group.block.id, item_id: handle(item) };
        }
        if (parent.matches("section,[role=region],main,aside,dialog")) break;
      }
      return null;
    }
    const refs = [...new Set([...capture.lit, ...capture.history.map(h => h.id).filter(Boolean).reverse()])].slice(0, 64);
    const capturedTables = new Set(refs.map(id => cursorRefs.get(id))
      .filter(el => el?.isConnected && !sensitive(el)).map(el => el.closest("table,[role=grid]")).filter(Boolean));
    for (const id of refs) {
      const el = cursorRefs.get(id);
      if (!el || !el.isConnected) { capture.targets.push({ id, available: false, reason: "historical node detached" }); continue; }
      const target = cursorMetadata(el);
      capture.targets.push(target);
      if (!target.available) continue;
      handle(el);
      // A frame is the actual hit, not the page behind it. Never collect its page ancestors.
      if (el.matches("iframe,frame,canvas,object,embed")) continue;
      if (target.surface) {
        const surface = el.closest("dialog,[role=dialog],[aria-modal=true]") || el;
        const bid = handle(surface);
        target.block_ids.push(bid);
        blocks.set(bid, { id: bid, kind: "surface", label: safeLabel(surface, 80),
          text: safeText(surface, 650), text_limit: 650 });
        continue;
      }
      const cell = el.closest("th,td,[role=cell],[role=gridcell],[role=columnheader],[role=rowheader]");
      let table = el.closest("table,[role=grid]");
      if (table && !table.matches("table") && !table.querySelector("tr,[role=row]")) table = null;
      if (table) {
        const bid = handle(table);
        if (!blocks.has(bid)) {
          const rowNodes = [];
          const rowCells = new Map();
          let collectionLimited = false;
          for (const row of table.querySelectorAll("tr,[role=row]")) {
            if (rowNodes.length >= 1024 || capturedMembers >= 8192) { collectionLimited = true; break; }
            if (row.closest("table,[role=grid]") !== table) continue;
            const cells = [];
            for (const cell of row.querySelectorAll("th,td,[role=cell],[role=gridcell],[role=columnheader],[role=rowheader]")) {
              if (cells.length >= 64 || capturedMembers >= 8192) { collectionLimited = true; break; }
              if (cell.closest("tr,[role=row]") === row) { cells.push(cell); capturedMembers++; }
            }
            rowNodes.push(row);
            rowCells.set(row, cells);
          }
          const allCells = row => rowCells.get(row) || [];
          const headerRow = rowNodes.find(row => {
            const cells = allCells(row);
            return cells.some(cell => cell.matches("[role=columnheader],th[scope=col],th[scope=colgroup]")) ||
              (cells.length > 0 && cells.every(cell => cell.matches("th") &&
                !cell.matches("[scope=row],[scope=rowgroup],[role=rowheader]")));
          });
          const cellsOf = row => allCells(row).slice(0, 12);
          const dataRows = rowNodes.filter(row => row !== headerRow);
          const columnCount = Math.min(64, Math.max(0, ...[...rowCells.values()].map(cells => cells.length)));
          const columns = [];
          for (let col = 0; col < columnCount; col++) {
            const members = rowNodes.map(row => allCells(row)[col]).filter(node => node && !sensitive(node));
            const id = `${bid}:column:${col + 1}`;
            const label = headerRow && allCells(headerRow)[col] ? safeText(allCells(headerRow)[col], 60) : `Column ${col + 1}`;
            if (members.length && identities.size < 8192) {
              identities.set(id, { kind: "column", label, members, table });
              capture.handles[id] = { kind: "column", label };
              columns.push(`${id} ${label}`);
            }
          }
          let label = safeText(table.querySelector("caption"), 80);
          if (!label) {
            const container = table.parentElement?.closest(contextRegions);
            if (container) label = ownHeading(container, capturedTables, table);
          }
          blocks.set(bid, { id: bid, kind: "table", label,
            headers: headerRow ? cellsOf(headerRow).map(c => `${handle(c)} ${safeText(c, 60)}`) : [],
            columns, total_rows: dataRows.length, collection_limited: collectionLimited,
            rows: [], _rows: dataRows, _cells: cellsOf, _allCells: allCells,
            _header: headerRow, _seen: new Set(), _rowIndex: new Map(dataRows.map((row, index) => [row, index])),
            omitted_columns: headerRow ? Math.max(0, allCells(headerRow).length - 12) : 0 });
        }
        const block = blocks.get(bid);
        target.block_ids.push(bid);
        const row = cell && cell.closest("tr,[role=row]");
        const ri = block._rowIndex.get(row) ?? -1;
        if (cell) {
          const column = row ? block._allCells(row).indexOf(cell) : -1;
          const header = block._header && block._allCells(block._header)[column];
          target.cell = { block: bid, handle: handle(cell), row_handle: row ? handle(row) : null,
            row: ri + 1, column: column + 1, value: safeText(cell, 100),
            header: header ? `${handle(header)} ${safeText(header, 60)}` : "",
            column_handle: capture.handles[`${bid}:column:${column + 1}`] ? `${bid}:column:${column + 1}` : null };
        }
        const peers = block._rows.map((node, index) => ({ node, index }))
          .filter(({ index }) => index !== ri)
          .sort((a, b) => Number(inView(b.node)) - Number(inView(a.node)) ||
            Math.abs(a.index - ri) - Math.abs(b.index - ri));
        const indices = [ri, ...peers.slice(0, 11).map(({ index }) => index)];
        for (const i of indices) if (i >= 0 && block.rows.length < 64 && !block._seen.has(i)) {
          block._seen.add(i);
          const node = block._rows[i];
          block.rows.push({ id: handle(node), index: i + 1, urls: safeLinks(node), in_view: inView(node),
            cells: block._cells(node).map(c => safeText(c, 160)) });
        }
      }
      const group = !table && captureGroup(el);
      if (group) {
        target.block_ids.push(group.id);
        target.group_item_id = group.item_id;
        continue;
      }
      const parents = new Set([el.closest("ul,ol,[role=list],p,h1,h2,h3,h4,h5,h6"), el.closest("article,section,.card")]);
      if (![...parents].some(Boolean)) parents.add(el.parentElement);
      for (const parent of parents) {
        if (!parent || parent === document.body || parent === document.documentElement) continue;
        const bid = handle(parent);
        target.block_ids.push(bid);
        if (!blocks.has(bid)) blocks.set(bid, { id: bid, kind: parent.tagName.toLowerCase(),
          label: ownHeading(parent, capturedTables) || safeLabel(parent, 80, capturedTables),
          text: safeText(parent, 650, capturedTables), urls: safeLinks(parent), text_limit: 650 });
      }
    }
    capture.targets.reverse();
    capture.blocks = [...blocks.values()].map(({ _rows, _cells, _allCells, _header, _seen, _rowIndex, ...block }) => block);
    // One bounded page-control pass per capture, never once per cell/mousemove.
    const controls = document.querySelectorAll('button,a,input,select,[role=button]');
    for (let i = 0; i < controls.length && i < 120 && capture.controls.length < 12; i++) {
      const el = controls[i];
      if (el.closest("#hermes-gaze-root") || sensitive(el) || !rendered(el) || !inView(el)) continue;
      const r = el.getBoundingClientRect();
      const top = hitNode(Math.max(0, r.left) + Math.min(r.width, window.innerWidth - Math.max(0, r.left)) / 2,
        Math.max(0, r.top) + Math.min(r.height, window.innerHeight - Math.max(0, r.top)) / 2);
      if (top && el.contains(top)) { handle(el); capture.controls.push(cursorMetadata(el)); }
    }
    capture.omitted_controls = Math.max(0, controls.length - capture.controls.length);
    identities.actionUrl = location.href;
    identities.actionRevoked = false;
    snapshots.set(snapshotId, identities);
    while (snapshots.size > 32) {
      const oldest = snapshots.keys().next().value;
      snapshots.delete(oldest);
      if (activeSnapshot?.id === oldest) activeSnapshot = null;
    }
    return capture;
  }
  function safeActionUrl(value) {
    try {
      if (typeof value !== "string" || !value || value.length > 8192 || /[\s\\\x00-\x1f\x7f]/.test(value)) return "";
      const url = new URL(value, location.href);
      if (!["http:", "https:"].includes(url.protocol) || [...url.searchParams].length > 128) return "";
      url.username = ""; url.password = "";
      for (const [key, value] of [...url.searchParams])
        if (secretQuery(key, value)) url.searchParams.delete(key);
      url.hash = "";
      return url.href.length <= 600 ? url.href : "";
    } catch (_) { return ""; }
  }
  function captureActionContext() {
    clearActionConfirmation();
    const snapshotId = `${snapshotInstance}:${++snapshotSerial}`, identities = new Map();
    const capture = {version: 1, snapshot_id: snapshotId, captured_at: Date.now() / 1000,
      page_url: safeActionUrl(location.href), page_title: String(document.title || "").slice(0, 160),
      history: [], targets: [], blocks: [], controls: [], handles: {}, lit: []};
    for (const node of document.querySelectorAll('button,a,input,textarea,select,[contenteditable],[role=button],[role=link],[role=tab],[role=checkbox],[role=radio]')) {
      if (identities.size >= 64) break;
      if (node.closest("#hermes-gaze-root") || sensitive(node) || !rendered(node) ||
          node.matches('[contenteditable="false"]') || node.type === "hidden") continue;
      const id = cursorId(node), facts = actionFacts(node), r = node.getBoundingClientRect();
      identities.set(id, {node, fingerprint: fingerprint(node), kind: facts.role || facts.tag});
      capture.handles[id] = {...facts, kind: facts.role || facts.tag, rect_vp: [r.left, r.top, r.width, r.height]};
      capture.controls.push({id, available: true, ...facts});
    }
    identities.actionUrl = location.href;
    identities.actionRevoked = false;
    snapshots.set(snapshotId, identities);
    while (snapshots.size > 32) snapshots.delete(snapshots.keys().next().value);
    return capture;
  }
  function actionStructure(snapshotId, resolutionId) {
    const fields = [], controls = [];
    for (const [handle, entry] of snapshots.get(snapshotId) || []) {
      const d = inspectSnapshot(snapshotId, resolutionId, handle), node = entry.node;
      if (!d.ok || d.disabled || !rendered(node)) continue;
      const label = safeLabel(node) || [...(node.labels || [])].map(n => safeText(n, 100)).join(" ").slice(0, 100);
      if (writableField(node, d)) fields.push({handle, label, type: node.isContentEditable ? "contenteditable" : d.type || d.tag,
        ...(d.tag === "select" ? {options: [...node.options].slice(0, 64).map(o => String(o.label || o.textContent || "").trim().slice(0, 100))} : {})});
      else if (d.clickable) controls.push({handle, label, type: d.type, form_submit: d.form_submit, ...(d.url ? {url: d.url} : {})});
    }
    if (!activeSnapshot || activeSnapshot.id !== snapshotId || activeSnapshot.resolutionId !== resolutionId)
      return {ok: false, error: "Inactive snapshot"};
    return {ok: true, fields, controls, page_text: safeText(document.body, 1800)};
  }
  function writableField(node, d) {
    return node && !sensitive(node) && !node.readOnly && !d.disabled && rendered(node) &&
      (node.isContentEditable || ["textarea", "select"].includes(d.tag) ||
        d.tag === "input" && ["text", "email", "tel", "date", "datetime-local", "month", "week", "time", "number", "search", "url"].includes(d.type));
  }
  function actionWrite(snapshotId, resolutionId, entries) {
    if (!Array.isArray(entries) || !entries.length || entries.length > 64 ||
        new Set(entries.map(e => e?.handle)).size !== entries.length)
      return {ok: false, executed: false, error: "Choose 1–64 distinct fields"};
    let validationError = "";
    function validate(e) {
      if (!e || typeof e.text !== "string" || e.text.length > 20000) return null;
      const d = inspectSnapshot(snapshotId, resolutionId, e.handle), node = snapshotEntry(snapshotId, resolutionId, e.handle)?.node;
      if (!d.ok || !writableField(node, d)) return null;
      if (d.tag === "input" && ["date", "datetime-local", "month", "week", "time", "number"].includes(d.type)) {
        const probe = document.createElement("input");
        probe.type = d.type; probe.value = e.text;
        if (probe.value !== e.text) {
          validationError = `Invalid ${d.type} value; use its native format (date: YYYY-MM-DD).`;
          return null;
        }
      }
      const option = d.tag === "select" ? [...node.options].find(o => !o.disabled && (o.textContent.trim() === e.text || o.value === e.text)) : null;
      if (d.tag === "select" && !option) return null;
      return {node, d, option};
    }
    if (entries.some(e => !validate(e))) return {ok: false, executed: false, error: validationError || "Unavailable field or option"};
    const written = [];
    for (const e of entries) {
      const current = validate(e);
      if (!current) return {ok: false, executed: written.length > 0, written, error: validationError || "Field changed during batch"};
      const {node, d, option} = current;
      if (option) node.selectedIndex = [...node.options].indexOf(option);
      else if (node.isContentEditable) node.textContent = e.text;
      else Object.getOwnPropertyDescriptor(d.tag === "textarea" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value").set.call(node, e.text);
      node.dispatchEvent(new Event("input", {bubbles: true}));
      node.dispatchEvent(new Event("change", {bubbles: true}));
      written.push(e.handle);
    }
    return {ok: true, executed: true, written};
  }
  function actionKeyTarget(snapshotId, resolutionId, handle) {
    const d = inspectSnapshot(snapshotId, resolutionId, handle), node = snapshotEntry(snapshotId, resolutionId, handle)?.node;
    if (!d.ok || d.disabled || !node || !rendered(node)) return {ok: false, error: "Unavailable key target"};
    if (d.clickable) return {ok: true, handle};
    const submit = node.form && [...node.form.elements].find(n => n.type === "submit" && !n.disabled);
    for (const [h, entry] of snapshots.get(snapshotId) || [])
      if (entry.node === submit) return {ok: true, handle: h};
    return {ok: false, error: "No captured activation target; use fill for text"};
  }
  function actionPress(snapshotId, resolutionId, handle, key) {
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown", "Tab", "Escape", "Backspace", "Delete"].includes(key))
      return {ok: false, executed: false, error: "Unsupported key; activation requires guarded click"};
    const d = inspectSnapshot(snapshotId, resolutionId, handle), node = snapshotEntry(snapshotId, resolutionId, handle)?.node;
    if (!d.ok || !node || !rendered(node) || d.disabled || sensitive(node) ||
        !(writableField(node, d) || ["checkbox", "radio"].includes(d.type)))
      return {ok: false, executed: false, error: "Unavailable editable key target"};
    node.focus();
    return {ok: true, focused: document.activeElement === node, key};
  }
  function actionScroll(snapshotId, resolutionId, pixels, handle = null) {
    const saved = snapshots.get(snapshotId);
    if (!activeSnapshot || activeSnapshot.id !== snapshotId || activeSnapshot.resolutionId !== resolutionId ||
        saved?.actionRevoked || saved?.actionUrl !== location.href || !Number.isFinite(pixels) || Math.abs(pixels) > 2000)
      return {ok: false, executed: false, error: "Invalid scroll or snapshot"};
    const node = handle === null ? window : snapshotEntry(snapshotId, resolutionId, handle)?.node;
    if (!node || handle !== null && (!inspectSnapshot(snapshotId, resolutionId, handle).ok || !rendered(node)))
      return {ok: false, executed: false, error: "Unavailable scroll target"};
    node.scrollBy(0, pixels);
    return {ok: true, executed: true};
  }
  let latestResolution = 0;
  function activateSnapshot(snapshotId, resolutionId) {
    if (destroyed || !Number.isSafeInteger(resolutionId) || resolutionId <= 0 ||
        resolutionId < latestResolution) return { ok: false, error: "Stale resolution" };
    if (!snapshots.has(snapshotId))
      return { ok: false, error: "Snapshot expired" };
    clearActionConfirmation();
    latestResolution = resolutionId;
    activeSnapshot = { id: snapshotId, resolutionId };
    state.resolutionId = resolutionId;
    return { ok: true };
  }
  function snapshotEntry(snapshotId, resolutionId, handle) {
    if (destroyed || !activeSnapshot || activeSnapshot.id !== snapshotId ||
        activeSnapshot.resolutionId !== resolutionId) return null;
    return snapshots.get(snapshotId)?.get(handle) || null;
  }
  function inspectSnapshot(snapshotId, resolutionId, handle, readOnly = false) {
    const saved = snapshots.get(snapshotId);
    if (!readOnly && (saved?.actionRevoked || saved?.actionUrl !== location.href))
      return { ok: false, error: "Page route changed since capture" };
    const entry = snapshotEntry(snapshotId, resolutionId, handle);
    if (entry?.members) {
      if (!entry.table.isConnected || entry.members.some(node => !node.isConnected || sensitive(node) ||
          node.closest("table,[role=grid]") !== entry.table))
        return { ok: false, error: "Snapshot target unavailable" };
      return { ok: true, handle, kind: "column", label: entry.label, tag: "", role: "column",
        type: "", form_submit: false, class_name: "", disabled: false, clickable: false,
        fingerprint: `${snapshotId}:${handle}` };
    }
    if (!entry || !entry.node || !entry.node.isConnected || sensitive(entry.node) || !readOnly && !rendered(entry.node))
      return { ok: false, error: "Snapshot target unavailable" };
    const current = fingerprint(entry.node);
    if (current !== entry.fingerprint) return { ok: false, error: "Target changed since capture" };
    return { ok: true, handle, kind: entry.kind, ...actionFacts(entry.node), fingerprint: current };
  }
  function highlightSnapshot(snapshotId, resolutionId, handles, hudMessage) {
    if (!Array.isArray(handles) || !handles.length || handles.length > 64)
      return { ok: false, error: "Choose 1–64 snapshot handles" };
    const candidates = [];
    for (const handle of handles) {
      const entry = snapshotEntry(snapshotId, resolutionId, handle);
      if (!inspectSnapshot(snapshotId, resolutionId, handle, true).ok)
        return { ok: false, error: "Snapshot target unavailable or changed" };
      const nodes = entry?.members || (entry?.node ? [entry.node] : []);
      if (!nodes.length || entry?.table && !entry.table.isConnected ||
          nodes.some(node => !node.isConnected || sensitive(node) ||
            entry.table && node.closest("table,[role=grid]") !== entry.table))
        return { ok: false, error: "Snapshot target unavailable" };
      for (const node of nodes) {
        const r = node.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) candidates.push({
          label: snapshots.get(snapshotId) && (entry.kind === "column" ? "Column" : safeLabel(node)),
          node, snapshotId, resolutionId, rect_vp: [r.left, r.top, r.width, r.height] });
      }
    }
    if (!candidates.length) return { ok: false, error: "No visible target geometry" };
    renderPins(candidates);
    if (hudMessage) showPlainMessage(hudMessage);
    return { ok: true };
  }
  function clickSnapshot(snapshotId, resolutionId, handle, expectedFingerprint, approvalId = null) {
    const approval = actionApproval;
    if (approvalId) {
      actionApproval = null; // Single use, before any page callback.
      const changed = approval ? approval.observer.takeRecords().some(approval.relevant) : false;
      approval?.cleanup();
      if (!approval || !approval.approved || approval.id !== approvalId || approval.invalid || changed ||
          approval.snapshotId !== snapshotId || approval.resolutionId !== resolutionId || approval.handle !== handle ||
          approval.url !== location.href || approval.content !== approvalContent(approval.scope).content)
        return {ok: false, executed: false, error: "Approval content or destination changed"};
    }
    const descriptor = inspectSnapshot(snapshotId, resolutionId, handle);
    if (!descriptor.ok) return { ...descriptor, executed: false };
    if (!expectedFingerprint || expectedFingerprint !== descriptor.fingerprint ||
        descriptor.disabled || !descriptor.clickable)
      return { ok: false, executed: false, error: "Control changed or is not enabled/clickable" };
    const entry = snapshotEntry(snapshotId, resolutionId, handle);
    entry.node.click();
    return { ok: true, executed: true };
  }
  function approvalContent(scope) {
    const fields = [], summary = [];
    let size = 0;
    for (const node of document.querySelectorAll("input,textarea,select,[contenteditable]")) {
      if (!scope.contains(node) && node.form !== scope || node.closest("#hermes-gaze-root") || sensitive(node) ||
          node.type === "hidden" || node.matches('[contenteditable="false"]')) continue;
      const value = node.isContentEditable ? node.textContent : String(node.value || "");
      const label = safeLabel(node) || node.labels?.[0]?.textContent?.trim().slice(0, 100) || "Field";
      size += value.length;
      if (fields.length >= 64 || value.length > 20000 || size > 128000)
        return {error: "Draft too large to bind safely; review and commit it yourself."};
      fields.push([cursorId(node), label, value, !!node.checked, node.selectedIndex ?? null]);
      if (rendered(node)) summary.push(`${label}: ${value.length > 600 ? value.slice(0, 600) + "… (review full text on page)" : value}${["checkbox", "radio"].includes(node.type) ? node.checked ? " (selected)" : " (not selected)" : ""}`);
    }
    const context = safeText(scope, 6000);
    if (context) summary.push(`Page context: ${context}`);
    return {content: JSON.stringify([fields, context]), summary: summary.join("\n")};
  }
  function clearActionConfirmation() {
    const had = !!confirmation;
    confirmation = null;
    if (actionApproval && !actionApproval.approved) { actionApproval.cleanup(); actionApproval = null; }
    if (had) renderNote();
    return true;
  }
  function requestActionConfirmation(info) {
    clearActionConfirmation();
    if (destroyed || !activeSnapshot || info?.resolution_id !== activeSnapshot.resolutionId ||
        typeof info.action_id !== "string" || !info.action_id)
      return { ok: false, error: "Stale confirmation" };
    if (actionApproval) { actionApproval.cleanup(); actionApproval = null; }
    const entry = snapshotEntry(activeSnapshot.id, info.resolution_id, info.handle);
    const live = inspectSnapshot(activeSnapshot.id, info.resolution_id, info.handle);
    if (!entry?.node || !live.ok || !live.clickable || live.disabled)
      return {ok: false, error: "Unavailable confirmation target"};
    const node = entry.node, scope = node.form || node.closest("form,[role=dialog]") || document.body;
    const content = approvalContent(scope);
    if (content.error) return {ok: false, error: content.error};
    const destination = safeActionUrl(node.getAttribute("formaction") || node.form?.action || node.closest("form")?.getAttribute("action") || node.getAttribute("href") || location.href);
    const approval = {id: info.action_id, snapshotId: activeSnapshot.id, resolutionId: info.resolution_id,
      handle: info.handle, url: location.href, scope, content: content.content, invalid: false, approved: false};
    const changed = () => { approval.invalid = true; };
    approval.relevant = r => !host.contains(r.target) &&
      (scope.contains(r.target) || r.target === node || r.target.form === scope);
    const edited = event => { if (approval.relevant(event)) changed(); };
    const observer = new MutationObserver(records => {
      if (records.some(approval.relevant)) changed();
    });
    observer.observe(document.documentElement, {subtree: true, attributes: true, childList: true, characterData: true});
    document.addEventListener("input", edited, true);
    document.addEventListener("change", edited, true);
    window.addEventListener("popstate", changed);
    window.addEventListener("hashchange", changed);
    // Input events and DOM records track edits; isolated-world setters cannot
    // observe main-world writes. The atomic content comparison is authoritative.
    approval.observer = observer;
    approval.cleanup = () => {
      observer.disconnect();
      document.removeEventListener("input", edited, true);
      document.removeEventListener("change", edited, true);
      window.removeEventListener("popstate", changed);
      window.removeEventListener("hashchange", changed);
      // No website properties or history methods are patched.
    };
    actionApproval = approval;
    confirmation = {label: String(info.label || ""), actionId: info.action_id, resolutionId: info.resolution_id,
      handle: info.handle || "", summary: content.summary, destination: destination || "Current page (destination not declared)"};
    renderNote();
    return { ok: true };
  }
  // Only a real primary mouse click in the protected frame may spend this approval, once.
  function confirmClick(approved, event) {
    const pending = confirmation;
    if (!pending || !trustedUi(event) || event.button !== 0 || event.detail < 1 ||
        event.pointerType && event.pointerType !== "mouse" || !activeSnapshot ||
        activeSnapshot.resolutionId !== pending.resolutionId) return false;
    if (actionApproval?.id === pending.actionId) actionApproval.approved = approved === true;
    clearActionConfirmation();
    _emit({ type: "confirm_action", action_id: pending.actionId, resolution_id: pending.resolutionId, approved });
    return true;
  }
  function showPlainMessage(text, answer = false) {
    const words = String(text || "").trim();
    if (!words) return;
    // A short sentence is a passing line; an answer or anything longer gets a card you can read.
    if (!answer && words.length <= 90 && !words.includes("\n")) coachLine(words, 4600);
    else if (confirmation || S.view === "compose") S.laterNote = words; // Never knock a decision or typing aside.
    else {
      S.note = {id: ++S.ids, text: words};
      openView("note", null);
    }
  }

  // ---------- pointing ----------
  const SEMANTIC = "img,video,canvas,svg,picture,button,a,input,select,textarea,label,td,th,li,h1,h2,h3,h4,h5,h6,p,blockquote,figcaption,pre,summary,dt,dd,[role=button],[role=link],[role=row],[role=cell],[role=listitem]";
  const CARDLIKE = 'article,[class*="card" i],[class*="deal" i],[class*="product" i],[class*="listing" i],[class*="result" i],[role=listitem]';
  const ours = n => !n || n === host || n === document.documentElement || n === document.body;

  function pickElement(x, y) {
    const start = hitNode(x, y);
    if (ours(start) || sensitive(start)) return null;
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
      if (up.matches(CARDLIKE) && !up.matches("td,th")) {
        const r = up.getBoundingClientRect();
        if (area(r) < vw * vh * .22 && r.width < vw * .6 && up.querySelector("img,picture") && safeText(up, 40).length > 8) return up;
      }
      up = up.parentElement;
    }
    return n;
  }

  // ---------- subject names: bounded safeText only, never values or ancestor innerText ----------
  const clean = t => (t || "").replace(/\[[^\]]{1,8}\]/g, "").replace(/\s+/g, " ").trim();
  const WEAK_END = new Set(["a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "over", "that", "the", "to", "with", "which", "who", "is", "are", "gives", "can", "using", "via", "your", "my"]);
  function humanName(raw, limit = 30) {
    let t = clean(raw).replace(/[*`#|<>{}]/g, " ").replace(/\s+/g, " ").trim();
    t = t.replace(/^\(?(?:new|sale|hot|ad|sponsored)\)?[:\s-]+/i, "").replace(/^[\d.,#)\s]+(?=\D)/, "");
    t = t.replace(/^(?:[$£€]\s?[\d.,]+[\s–—-]*)+/, "").replace(/^(?:a|an|the)\s+/i, "");
    t = t.replace(/^[\s.,:;–—"'“”-]+|[\s.,:;–—"'“”-]+$/g, "");
    if (t.length <= limit) return t;
    for (const mark of [": ", " – ", " — ", " - ", " | ", ", ", ". ", " ("]) {
      const head = t.split(mark)[0].trim();
      if (head.length >= 6 && head.length <= limit) return head;
    }
    const kept = [];
    for (const word of t.split(" ")) {
      if ((kept.join(" ") + " " + word).trim().length > limit) break;
      kept.push(word);
    }
    while (kept.length > 1 && WEAK_END.has(kept[kept.length - 1].toLowerCase().replace(/[,.:;]+$/, ""))) kept.pop();
    return (kept.join(" ") || t.slice(0, limit)).replace(/[\s.,:;–—-]+$/, "");
  }
  function ownText(n) {
    if (sensitive(n)) return "";
    if (n.matches("input,select,textarea")) return clean(n.getAttribute("aria-label") || n.getAttribute("placeholder") || n.getAttribute("name") || ""); // never .value
    if (n.matches("img,picture,video,svg,canvas")) return clean(n.getAttribute("alt") || n.querySelector?.("img")?.getAttribute("alt") || n.getAttribute("aria-label") || n.getAttribute("title") || "");
    if (n.matches("iframe,frame")) return clean(n.getAttribute("title") || "Embedded frame");
    if (n.matches("p,blockquote,dd,figcaption,pre")) {
      const lead = n.querySelector("b,strong"), opening = clean(safeText(n, 200));
      const bold = lead ? clean(safeText(lead, 80)) : "";
      return bold && opening.startsWith(bold) ? bold : opening;
    }
    const titled = n.matches("a,h1,h2,h3,h4,h5,h6,button") ? n : n.querySelector('h1,h2,h3,h4,[class*="title" i] a,[class*="title" i],a[title],a');
    return clean(titled && safeText(titled, 160) || safeText(n, 160) || n.getAttribute("aria-label") || n.getAttribute("title") || "");
  }
  const dataTable = t => t && t.getAttribute("role") !== "presentation" && !!(t.tHead || t.querySelector("th")) && t.rows?.length > 1;
  function nameOf(n) {
    const cell = n.closest?.("td,th");
    if (cell && dataTable(cell.closest("table"))) {
      const row = cell.closest("tr"), table = cell.closest("table");
      if (row === (table?.tHead?.rows?.[0] || table?.rows?.[0]) && cell.tagName === "TH") {
        // A column header names the column, in sentence case unless it's an abbreviation.
        const own = clean(safeText(cell, 60));
        return {short: humanName(own.length > 4 && own === own.toUpperCase() ? own[0] + own.slice(1).toLowerCase() : own)};
      }
      const first = row?.cells?.[0];
      const label = clean(safeText(row?.querySelector("th") || first, 60));
      if (cell === first || (cell.tagName === "TH" && row?.querySelector("th") === cell)) return {short: humanName(label || ownText(n)), base: label};
      const headRow = table?.tHead?.rows?.[0] || table?.rows?.[0];
      let header = headRow && headRow !== row ? clean(safeText(headRow.cells[cell.cellIndex], 40)) : "";
      header = header.replace(/\s*\([^)]*\)\s*$/, "");
      if (header.length > 4 && header === header.toUpperCase()) header = header[0] + header.slice(1).toLowerCase();
      const col = humanName(header, 14);
      const short = [humanName(label, 18), col].filter(Boolean).join(" · ");
      if (short) return {short, base: label, col};
    }
    const name = humanName(ownText(n));
    return {short: name || "This part of the page"};
  }
  function subjectFor(targets) {
    if (!targets.length) return {name: humanName(document.title || "") || "This page", count: 1};
    const names = targets.map(t => {
      if (!t.soft) return nameOf(t.el || t.els?.[0] || document.body);
      const raw = nameOf(t.anchor || document.body);
      return {short: `Around ${humanName(raw.short, 24)}`, base: raw.base || raw.short, around: true};
    });
    const short = n => humanName(n.base || n.short, 18);
    let name;
    if (names.length === 1) name = names[0].short;
    else if (names.length === 2 && names[0].base && names[0].base === names[1].base && names[0].col && names[1].col)
      name = `${humanName(names[0].base, 18)} · ${names[0].col} and ${names[1].col}`;
    else name = `${names[0].around ? "Around " : ""}${short(names[0])} and ${names.length - 1} more`;
    return {name, count: names.length};
  }

  // ---------- targets ----------
  // Thin anchor so a soft region survives scrolling and inner scrollers.
  function regionAt(cx, cy) {
    const anchor = pickElement(cx, cy) || hitNode(cx, cy);
    const r = anchor?.getBoundingClientRect?.();
    return {soft: true, anchor, dx: r ? cx - r.left : cx + scrollX, dy: r ? cy - r.top : cy + scrollY, cx: cx + scrollX, cy: cy + scrollY};
  }
  function targetRect(t) {
    if (t.soft) {
      let cx, cy;
      if (t.anchor?.isConnected) { const r = t.anchor.getBoundingClientRect(); cx = r.left + t.dx; cy = r.top + t.dy; }
      else { cx = t.cx - scrollX; cy = t.cy - scrollY; }
      return {left: cx - REGION_W / 2, top: cy - REGION_H / 2, right: cx + REGION_W / 2, bottom: cy + REGION_H / 2, width: REGION_W, height: REGION_H};
    }
    if (t.doc) {
      const [x, y, w, h] = t.doc;
      return {left: x - scrollX, top: y - scrollY, right: x - scrollX + w, bottom: y - scrollY + h, width: w, height: h};
    }
    const nodes = t.els || (t.el ? [t.el] : []);
    let u = null;
    for (const node of nodes) {
      if (!node.isConnected || !rendered(node) || sensitive(node)) continue;
      const r = node.getBoundingClientRect();
      if (!r.width && !r.height) continue;
      if (!u) u = {left: r.left, top: r.top, right: r.right, bottom: r.bottom};
      else { u.left = Math.min(u.left, r.left); u.top = Math.min(u.top, r.top); u.right = Math.max(u.right, r.right); u.bottom = Math.max(u.bottom, r.bottom); }
    }
    return u ? {...u, width: u.right - u.left, height: u.bottom - u.top} : null;
  }
  // Scrolling ancestors clip the ring as they clip the thing. Found once; read each frame.
  function clipAncestors(node) {
    const out = [];
    for (let p = node?.parentElement, n = 0; p && n < 32; p = p.parentElement, n++) {
      const cs = getComputedStyle(p);
      const x = /auto|scroll|hidden|clip/.test(cs.overflowX), y = /auto|scroll|hidden|clip/.test(cs.overflowY);
      if ((x || y) && p !== document.body && p !== document.documentElement) out.push({p, x, y});
    }
    return out;
  }
  function clippedRect(t) {
    const r = targetRect(t);
    if (!r || t.soft || t.doc) return r;
    if (!t.clips) t.clips = clipAncestors(t.el || t.els?.[0]);
    let {left, top, right, bottom} = r;
    for (const {p, x, y} of t.clips) {
      const b = p.getBoundingClientRect();
      if (x) { left = Math.max(left, b.left); right = Math.min(right, b.right); }
      if (y) { top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom); }
    }
    if (right <= left || bottom <= top) return null;
    return {left, top, right, bottom, width: right - left, height: bottom - top};
  }

  // ---------- rings ----------
  const lit = new Map(); // key -> {node, g:box, style, target}
  const RING_STYLES = {
    tentative: {fill: .06, edge: .45, halo: .0, stroke: 1.5},
    live:      {fill: .1, edge: 1,   halo: .16, stroke: 1.75},
    answer:    {fill: .08, edge: .9,  halo: .14, stroke: 1.5},
    relit:     {fill: .16, edge: 1,   halo: .32, stroke: 2.5},
  };
  function ringFor(key, target, style) {
    let r = lit.get(key);
    if (!r) {
      const node = add("div", "ring" + (target.soft ? " region" : ""), rings);
      const rect = clippedRect(target) || targetRect(target) || {left: 0, top: 0, width: 0, height: 0};
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
  function dropAllRings() { for (const [k] of lit) dropRing(k); }
  function drawRings(level) {
    const vw = innerWidth, vh = innerHeight;
    for (const [key, r] of lit) {
      const rect = clippedRect(r.target);
      if (!rect) {
        // Gone, hidden, or scrolled out of its own scroller: no light on anything else.
        if (!targetRect(r.target)) dropRing(key);
        else r.g.o.to(0);
      } else {
        if (!r.dying) r.g.o.to(1);
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
      const breathe = r.style === "live" ? level : 0;
      const n = r.node.style;
      n.setProperty("--a", S.dark ? "95,172,255" : "0,122,255");
      n.setProperty("--fill", (st.fill + breathe * .05).toFixed(3));
      n.setProperty("--edge", st.edge.toFixed(3));
      n.setProperty("--halo", (st.halo + breathe * .22).toFixed(3));
      n.setProperty("--stroke", `${st.stroke}px`);
      n.transform = `translate3d(${r.g.x.x}px,${r.g.y.x}px,0)`;
      n.width = `${Math.max(0, r.g.w.x)}px`; n.height = `${Math.max(0, r.g.h.x)}px`;
      n.opacity = r.g.o.x.toFixed(3);
      if (r.dying && r.g.o.x < .01) { r.node.remove(); lit.delete(key); }
    }
  }
  function stopTrackingPins() {
    for (const [, r] of lit) r.node.remove();
    lit.clear();
    anchors.clear();
    snapshotOwner.clear();
    S.localPending = [];
  }
  // A highlight names captured nodes. Questions keep their pointed things lit until scope widens.
  function renderPins(candidates) {
    const targets = [];
    let owner = null, column = null;
    for (const cand of candidates || []) {
      const entry = !cand.node && activeSnapshot ? snapshotEntry(activeSnapshot.id, activeSnapshot.resolutionId, cand.id) : null;
      const nodes = cand.members || entry?.members || (cand.node || entry?.node ? [cand.node || entry.node] : null);
      if (cand.snapshotId && !owner) owner = snapshotOwner.get(cand.snapshotId);
      if (!owner && activeSnapshot) owner = snapshotOwner.get(activeSnapshot.id);
      // One column's cells share one light.
      if (cand.label === "Column" && nodes) {
        if (!column) targets.push(column = {els: [], key: `t${++S.ids}`});
        column.els.push(...nodes);
      } else if (nodes) targets.push(nodes.length > 1 ? {els: nodes, key: `t${++S.ids}`} : {el: nodes[0], key: `t${++S.ids}`});
      else if (Array.isArray(cand.rect_doc) && cand.rect_doc.length === 4 && cand.rect_doc.every(Number.isFinite))
        targets.push({doc: cand.rect_doc, key: `t${++S.ids}`});
    }
    if (!targets.length) return;
    const cur = S.view === "answer" ? current() : null;
    if (owner) {
      const nested = targets.every(t => owner.targets.some(o => {
        const a = o.el, b = t.el || t.els?.[0];
        return a && b && (a === b || a.contains(b));
      }));
      const answered = cur && owner === anchors.get(cur.id) && !isBusyItem(cur);
      // The pointed things are already lit and named. Only a wider scope changes what's shown.
      if (nested && !answered) return;
      owner.targets = targets;
      if (cur && owner === anchors.get(cur.id)) { lightCurrent(cur, "answer"); return; }
      if (S.hold || S.view) return;
    }
    if (S.hold) return;
    const keep = new Set(targets.map(t => t.key));
    for (const [k] of lit) if (!keep.has(k)) dropRing(k);
    for (const t of targets) ringFor(t.key, t, "answer");
  }

  // ---------- free-space placement ----------
  const CELL = 26;
  function occupancy() {
    const vw = innerWidth, vh = innerHeight, cols = Math.ceil(vw / CELL), rows = Math.ceil(vh / CELL);
    const grid = new Float32Array((cols + 1) * (rows + 1)); // summed-area table
    const hit = (x, y) => {
      const n = document.elementFromPoint(x, y);
      if (!n || n === host) return 0;
      if (n.matches("img,video,canvas,svg,path,picture,input,select,textarea,button,iframe")) return 1;
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
      if (cs.backgroundImage !== "none" && n.getBoundingClientRect().width < vw * .5) return .7;
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
  const inflate = (r, p) => ({left: r.left - p, right: r.right + p, top: r.top - p, bottom: r.bottom + p});
  // Things you asked about must stay visible; for a table cell, so should its row and column.
  function avoidance(item) {
    const hard = [], soft = [];
    for (const t of item?.targets || []) {
      const r = targetRect(t);
      if (r && r.bottom > 0 && r.top < innerHeight) hard.push(inflate(r, 14));
      const cell = t.el?.closest?.("td,th");
      if (cell && dataTable(cell.closest("table"))) {
        const row = cell.closest("tr")?.getBoundingClientRect();
        if (row) soft.push(row);
        const table = cell.closest("table");
        const first = table?.rows?.[0]?.cells?.[cell.cellIndex]?.getBoundingClientRect?.();
        const last = table?.rows?.[table.rows.length - 1]?.cells?.[cell.cellIndex]?.getBoundingClientRect?.();
        if (first && last) soft.push({left: first.left, right: first.right, top: first.top, bottom: last.bottom});
      }
    }
    return {hard, soft};
  }
  function place(item, want) {
    const vw = innerWidth, vh = innerHeight;
    const W = Math.min(CARD_W, vw - 2 * MARGIN);
    const occ = occupancy();
    const {hard, soft} = avoidance(item);
    const focus = hard[0] ? {x: (hard[0].left + hard[0].right) / 2, y: (hard[0].top + hard[0].bottom) / 2}
      : {x: state.pointerX ?? vw * .7, y: state.pointerY ?? vh * .3};
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
          let cost = covers * 1000 + softCovers / (W * H) * 26 + frac * 110 + near / vmax * 20 + hi * 7;
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

  // ---------- stack: a view over the Python inbox ----------
  const anchors = new Map();       // item id -> {targets}, only for items captured in this document
  const snapshotOwner = new Map(); // snapshot id -> same record
  const requestOwner = new Map();  // intent id -> same record
  const WAITING = ["transcribing", "queued", "thinking"];
  const hostOf = url => { try { return new URL(url).hostname.replace(/^www\./, "") || "that page"; } catch (_) { return "that page"; } };
  function itemView(raw) {
    const turns = (raw.conversation || []).filter(r => !["retried", "skipped"].includes(r.status)).map(r => ({
      id: r.request_id, q: r.utterance || "", a: r.text || "", status: r.status,
      error: ["failed", "interrupted"].includes(r.status) ? r.plain_error || "Hermes couldn’t finish this answer." : "",
    }));
    const local = anchors.get(raw.item_id);
    return {id: raw.item_id, subject: raw.subject || raw.target_label || "This part of the page", turns,
      targets: local?.targets || [], pointerAnchor: local?.pointerAnchor, local: !!local, archived: !!raw.archived,
      presented: !!raw.presented || S.shown.has(raw.item_id), unread: !!raw.unread, count: raw.target_count || 1,
      notice: raw.notice || "", host: hostOf(raw.source_url), url: raw.source_url || ""};
  }
  const visible = () => S.items.filter(i => !i.archived && i.turns.length);
  const current = () => S.items.find(i => i.id === S.cur) || null;
  const isBusyItem = i => i.turns.some(t => WAITING.includes(t.status) || t.status === "streaming");
  const started = i => i.turns.length && !WAITING.includes(i.turns[0].status);
  const inProgress = () => S.items.filter(i => i.turns.some(t => WAITING.includes(t.status)) && !(S.view === "answer" && S.cur === i.id));
  function stateWord(i) {
    if (i.turns.some(t => t.error)) return "Didn’t finish";
    if (i.turns.some(t => t.status === "streaming")) return "Answering";
    if (i.turns.some(t => t.status === "thinking")) return "Looking into it";
    if (i.turns.some(t => WAITING.includes(t.status))) return "Waiting";
    return i.presented ? "" : "Ready";
  }
  function hintFor(item) {
    if (S.coach.answered > 6 || item.turns.at(-1)?.error) return "";
    return "Hold Space to ask more";
  }
  const viewItem = () => {
    if (S.view === "answer") return current();
    if (S.view === "compose") return S.compose;
    if (S.view === "confirm") return S.confirmItem;
    return S.viewTargets || null;
  };
  function isGone(item) { return item.local && item.targets.length > 0 && !item.targets.some(targetRect); }
  function pushCard() {
    if (!S.ready) return;
    const base = {type: "_ui_render", frame: "card", kind: "card", dark: S.dark, maxBody: S.maxBody, reduce: reduced()};
    if (!S.view) { rawSend({...base, view: null}); return; }
    if (S.view === "compose") {
      rawSend({...base, view: "compose", title: S.compose.title, followup: !!S.compose.itemId, focus: !!S.compose.focus});
      S.compose.focus = false;
      return;
    }
    if (S.view === "confirm") { rawSend({...base, view: "confirm", id: confirmation.actionId, label: confirmation.label,
      summary: confirmation.summary, destination: confirmation.destination, doing: !!actionTask}); return; }
    if (S.view === "doing") { rawSend({...base, view: "doing", label: actionTask?.label || "Working on this page"}); return; }
    if (S.view === "lens") {
      rawSend({...base, view: "lens", id: state.resolutionId, dwell: state.dwellMs,
        options: state.lensCandidates.map(c => humanName(c.label || c.summary || "", 44))});
      return;
    }
    if (S.view === "note") { rawSend({...base, view: "note", id: S.note.id, text: S.note.text, title: "Hermes"}); return; }
    const item = current();
    if (!item) { closeStack("dismiss"); return; }
    const list = visible(), i = list.indexOf(item);
    const peek = p => p && {subject: p.subject, state: stateWord(p)};
    const hasAnswer = item.turns.some(t => t.a.trim());
    rawSend({...base, view: "answer", dir: S.dir, hint: hintFor(item), alert: inbox?.speech_error || "",
      reading: inbox?.speaking_item_id === item.id, autoRead: !!inbox?.auto_speak, canRead: hasAnswer,
      paused: !!inbox?.paused && !item.turns.some(t => t.error) && (inbox?.waiting || 0) > 0,
      prev: peek(list[i - 1]), next: peek(list[i + 1]),
      item: {id: item.id, subject: item.subject, notice: item.notice, lost: !item.local, host: item.host, gone: isGone(item),
        turns: item.turns.map(({id, q, a, status, error}) => ({id, q, a, status, error}))}});
    S.dir = null;
  }
  function renderNote() {
    // Confirmation and the "which one" card take over the surface; the stack resumes after.
    if (confirmation) {
      const entry = confirmation.handle && activeSnapshot ? snapshotEntry(activeSnapshot.id, activeSnapshot.resolutionId, confirmation.handle) : null;
      const targets = entry?.node ? [{el: entry.node, key: `confirm-${confirmation.handle}`}] : [];
      S.confirmItem = {targets};
      for (const t of targets) ringFor(t.key, t, "answer");
      openView("confirm", S.confirmItem);
      return;
    }
    if (S.view === "confirm") {
      dropRingsWithPrefix("confirm-");
      restoreAfterOverlay();
      return;
    }
    if (S.view) { pushCard(); layout(); }
  }
  function dropRingsWithPrefix(prefix) { for (const [k] of lit) if (String(k).startsWith(prefix)) dropRing(k); }
  function restoreAfterOverlay() {
    const item = current();
    S.viewTargets = null;
    if (S.laterNote) { const words = S.laterNote; S.laterNote = ""; S.note = {id: ++S.ids, text: words}; openView("note", null); return; }
    if (item && visible().includes(item)) { S.view = null; openStack(item); }
    else closeStack("cancel");
  }
  // Open any non-stack card on the same plate.
  function openView(view, item) {
    const was = S.view;
    S.view = view;
    S.viewTargets = item;
    clearTimeout(S.retreatTimer); S.retreatAt = 0;
    const W = cardWidth();
    const want = view === "note" ? estimateChars(S.note?.text || "") : view === "lens" ? 200 : 120;
    if (!S.pos || !was || coversTargets(item, S.pos, want)) {
      const spot = place(item, want);
      S.pos = {x: spot.x, y: spot.y};
      setTone(darkAt(spot.x, spot.y, W, Math.min(want, 300)));
    }
    S.maxBody = maxBodyFor(item);
    if (!was) enterPlates(W);
    pushCard();
    layout();
    if (view === "note") armNoteRetreat();
  }
  function enterPlates(W) {
    const pos = S.pos;
    front.x.snap(pos.x + 8); front.y.snap(pos.y + 12); front.w.snap(W - 16); front.h.snap(40); S.morphR = 18;
    front.o.snap(0);
    next.x.snap(pos.x + 8); next.y.snap(pos.y + 20); next.w.snap(W - 16); next.h.snap(30); next.o.snap(0);
    next2.x.snap(pos.x + 18); next2.y.snap(pos.y + 20); next2.w.snap(W - 36); next2.h.snap(30); next2.o.snap(0);
    prev.x.snap(pos.x + 8); prev.y.snap(pos.y); prev.w.snap(W - 16); prev.h.snap(30); prev.o.snap(0);
    S.cardFade = 0;
    raise();
  }
  function openStack(item, dir) {
    const was = S.view === "answer";
    const wasAny = !!S.view;
    S.view = "answer";
    S.cur = item.id;
    S.dir = dir;
    S.note = null;
    S.compose = null;
    if (!S.shown.has(item.id)) {
      S.shown.add(item.id);
      if (!item.presented) {
        S.coach.answered++;
        sendCoach({answered: S.coach.answered});
      }
      item.presented = true;
    }
    control("select", item.id);
    const list0 = visible(), i0 = list0.indexOf(item);
    const peekAbove = i0 > 0 ? 30 : 0, peekBelow = i0 < list0.length - 1 ? 30 : 0;
    const want = estimateH(item) + peekAbove + peekBelow;
    const needMove = !S.pos || coversTargets(item, {x: S.pos.x, y: S.pos.y - peekAbove}, want);
    const W = cardWidth();
    if (!was || needMove) {
      const spot = place(item, want);
      S.pos = {x: spot.x, y: spot.y + peekAbove};
      S.placedH = spot.H;
      setTone(darkAt(spot.x, spot.y, W, Math.min(want, 300)));
    }
    S.maxBody = maxBodyFor(item);
    if (!wasAny) {
      const p = P.pill;
      if (!S.hold && pillVisible() && S.pillMode === "capsule" && !capsuleText()) {
        // The capsule becomes the card: same plate, new shape.
        enterPlates(W);
        front.x.snap(p.x.x); front.y.snap(p.y.x); front.w.snap(p.w.x); front.h.snap(p.h.x); S.morphR = PILL_H / 2;
        front.o.snap(1);
        hidePill(true);
      } else enterPlates(W);
    }
    lightCurrent(item, "answer");
    pushCard();
    S.wasBusy = isBusyItem(item);
    armRetreat();
    layout();
  }
  function estimateChars(text) { return Math.min(innerHeight - 2 * MARGIN, 96 + Math.ceil(text.length / 48) * 19.3); }
  function estimateH(item) {
    // Questions and notices take room too, or a card near the bottom edge runs out of it.
    return estimateChars(item.turns.map(t => t.q + t.a).join("") + (item.notice ? " ".repeat(96) : ""));
  }
  function coversTargets(item, pos, h) {
    const W = cardWidth();
    const rect = {left: pos.x, top: pos.y, right: pos.x + W, bottom: pos.y + h};
    return avoidance(item).hard.some(r => overlap(rect, r) > 0);
  }
  function maxBodyFor(item) {
    // The extra 24 is room for the plate's coarse rounding.
    const chrome = 78 + (S.sizes.prevH || 0) + (S.sizes.nextH || 0);
    let limit = innerHeight - MARGIN - (S.pos?.y ?? MARGIN) - chrome;
    const {hard} = avoidance(item);
    const W = cardWidth();
    // Stop growing before reaching what you asked about.
    for (const r of hard) {
      if (S.pos && r.left < S.pos.x + W && r.right > S.pos.x && r.top > S.pos.y) limit = Math.min(limit, r.top - S.pos.y - chrome - 8);
    }
    const vv = window.visualViewport;
    if (vv && vv.scale > 1.01) limit = Math.min(limit, vv.height - chrome - 8);
    return Math.max(70, limit);
  }
  function lightCurrent(item, style) {
    const keep = new Set();
    for (const t of item?.targets || []) { keep.add(t.key); ringFor(t.key, t, style); }
    for (const [k] of lit) if (!keep.has(k) && !(S.hold?.targets || []).some(t => t.key === k) && !String(k).startsWith("confirm-")) dropRing(k);
  }
  function layout() {
    if (!S.view) return;
    const W = cardWidth();
    const {prevH, cardH, nextH} = S.sizes;
    const h = Math.max(cardH, 64);
    const pos = S.pos;
    const item = viewItem();
    // Long answer keeps growing: slide up if that's possible without covering the target.
    const total = h + nextH;
    let y = pos.y;
    const over = y + total - (innerHeight - MARGIN);
    if (over > 0) {
      const ny = Math.max(MARGIN + prevH, y - over);
      if (!coversTargets(item, {x: pos.x, y: ny}, total)) { y = ny; S.pos.y = y; }
    }
    if (prevH && y - prevH < MARGIN) { y = MARGIN + prevH; S.pos.y = y; }
    // Pinch zoom magnifies the layout viewport: stay inside the part you can actually see.
    const vv = window.visualViewport;
    if (vv && vv.scale > 1.01) {
      pos.x = Math.max(vv.offsetLeft + 4, Math.min(pos.x, vv.offsetLeft + vv.width - W - 4));
      y = Math.max(vv.offsetTop + 4 + prevH, Math.min(y, Math.max(vv.offsetTop + 4 + prevH, vv.offsetTop + vv.height - total - 4)));
      S.pos.y = y;
    }
    const list = S.view === "answer" ? visible() : [], i = list.indexOf(current());
    front.x.to(pos.x); front.y.to(y); front.w.to(W); front.h.to(h); front.o.to(1);
    const showPrev = i > 0 && prevH, showNext = i >= 0 && i < list.length - 1 && nextH, showNext2 = i >= 0 && i < list.length - 2 && nextH;
    prev.x.to(pos.x + 7); prev.w.to(W - 14); prev.h.to((prevH || 30) + 14); prev.y.to(y - (prevH || 30)); prev.o.to(showPrev ? 1 : 0);
    next.x.to(pos.x + 7); next.w.to(W - 14); next.h.to((nextH || 30) + 14); next.y.to(y + h - 14); next.o.to(showNext ? 1 : 0);
    next2.x.to(pos.x + 16); next2.w.to(W - 32); next2.h.to(24); next2.y.to(y + h + (nextH || 30) - 16); next2.o.to(showNext2 ? 1 : 0);
    S.frameY = y - (showPrev ? prevH : 0);
    S.frameH = (showPrev ? prevH : 0) + h + (showNext ? nextH : 0);
    placeCapsule();
    wake();
  }
  function closeStack(reason) {
    if (!S.view) return;
    const item = S.view === "answer" ? current() : null;
    S.view = null;
    S.compose = null;
    S.note = null;
    S.viewTargets = null;
    clearTimeout(S.retreatTimer);
    S.retreatAt = 0;
    if (item) {
      // Retreat back toward what it was about; it's going home, not vanishing.
      const r = item.targets?.[0] && targetRect(item.targets[0]);
      if (r && !reduced() && reason === "retreat") {
        front.x.to(front.x.t + (r.left + r.width / 2 - (front.x.t + CARD_W / 2)) * .22);
        front.y.to(front.y.t + (r.top + r.height / 2 - front.y.t) * .22);
      }
    }
    front.w.to(front.w.t - 24); front.h.to(Math.max(40, front.h.t - 26));
    for (const b of [front, prev, next, next2]) b.o.to(0);
    S.frameH = 0;
    dropAllRings();
    if (reason !== "cancel") {
      S.cur = "";
      for (const i of visible()) if (reason === "dismiss" || i.presented) if (!isBusyItem(i)) i.archived = true;
      control(reason === "retreat" ? "retreat" : "dismiss");
    } else setTimeout(refresh, 260);
    if (reason === "retreat" && !S.coach.retreated) {
      S.coach.retreated = true;
      sendCoach({retreated: true});
      coachLine("Press Q to bring answers back", 3600);
    } else updateCapsule();
    // Wait for the fade so words don't vanish before glass does.
    setTimeout(() => { if (!S.view) { pushCard(); S.pos = null; S.sizes = {prevH: 0, cardH: 0, nextH: 0, contentH: 0, bodyH: 0}; } }, reduced() ? 180 : 240);
  }
  function armNoteRetreat() {
    clearTimeout(S.retreatTimer);
    const words = (S.note?.text || "").split(/\s+/).length;
    S.retreatTimer = setTimeout(function again() {
      if (S.view !== "note") return;
      if (S.hoverCard || document.hidden) { S.retreatTimer = setTimeout(again, 1500); return; }
      closeStack("cancel");
    }, Math.max(state.answerTurnMs, words / READING_WPS * 1000));
  }
  // Each unseen answer gets its own turn; long answers get reading time. Hover holds it.
  function armRetreat() {
    clearTimeout(S.retreatTimer);
    S.retreatAt = 0;
    const item = S.view === "answer" ? current() : null;
    if (!item) return;
    if (isBusyItem(item) || S.hoverCard || S.hold || inbox?.speaking_item_id === item.id) return;
    const words = item.turns.reduce((n, t) => n + t.a.split(/\s+/).length, 0);
    const ms = Math.max(state.answerTurnMs, words / READING_WPS * 1000);
    S.retreatAt = performance.now() + ms;
    S.retreatTimer = setTimeout(retreatStep, ms);
  }
  function retreatStep() {
    if (document.hidden) { S.retreatTimer = setTimeout(retreatStep, 2000); return; }
    // Anything you haven't seen comes forward first, one stage at a time, so nothing gets buried.
    const list = visible(), i = list.indexOf(current());
    const nextUnseen = list.slice(i + 1).find(x => !x.presented && started(x));
    if (nextUnseen) { go(nextUnseen, "next"); return; }
    closeStack("retreat");
  }
  function go(item, dir) {
    openStack(item, dir);
    if (dir && !reduced()) lift.kick(dir === "next" ? -420 : 420);
  }
  function step(delta) {
    const list = visible(), i = list.indexOf(current());
    const target = list[i + delta];
    if (!target) { lift.kick(delta * 260); return; } // gentle end-of-stack bump
    go(target, delta > 0 ? "next" : "prev");
  }
  function recallNotes() {
    if (!S.items.some(i => i.turns.length)) { coachLine("Nothing here yet. Point at something and hold Space", 2800); return; }
    for (const i of S.items) i.archived = false;
    control("recall");
    const list = visible();
    const last = [...list].reverse().find(started) || list[list.length - 1];
    if (last) openStack(last);
  }
  // Click an answer: back to the thing, lit again.
  function goBack(item) {
    if (!item) return;
    const t = item.targets[0];
    if (!item.local || !t) { _emit({type: "show_source", item_id: item.id}); return; }
    const r = targetRect(t);
    if (!r) { pushCard(); return; } // the page removed it: the card says so, we don't guess
    const inView = r.top > 40 && r.bottom < innerHeight - 40;
    if (!inView) {
      const y = scrollY + r.top + r.height / 2 - innerHeight / 2;
      const node = t.el || t.els?.[0];
      if (node) node.scrollIntoView({block: "center", inline: "nearest", behavior: reduced() ? "auto" : "smooth"});
      else window.scrollTo({top: y, behavior: reduced() ? "auto" : "smooth"});
    }
    relight(item);
    armRetreat();
  }
  function relight(item) {
    for (const t of item.targets || []) {
      const ring = ringFor(t.key, t, "relit");
      if (!reduced() && !t.soft) { ring.g.w.kick(180); ring.g.h.kick(180); ring.g.x.kick(-90); ring.g.y.kick(-90); }
    }
    clearTimeout(S.relitTimer);
    S.relitTimer = setTimeout(() => { for (const t of item.targets || []) if (lit.get(t.key)) lit.get(t.key).style = "answer"; }, 1100);
  }

  // ---------- capsule ----------
  function pillVisible() { return P.pill.o.t > 0; }
  function pushPill(mode, text, shimmer) {
    if (!S.ready) return;
    const startup = mode === "wave" && !S.micReady;
    const key = JSON.stringify([mode, text, shimmer, S.dark, startup]);
    if (key === S.pillLast) return;
    S.pillLast = key;
    rawSend({type: "_ui_render", frame: "pill", kind: "pill", mode, text, shimmer: !!shimmer, startup, dark: S.dark, reduce: reduced()});
  }
  function hidePill(instant) {
    P.pill.o.to(0);
    S.pillMode = "none";
    if (instant) { P.pill.o.snap(0); pushPill("off", "", false); }
    else setTimeout(() => { if (S.pillMode === "none") pushPill("off", "", false); }, 200);
    wake();
  }
  function capsuleText() {
    const waiting = inProgress();
    const local = S.localPending;
    const total = waiting.length + local.length;
    if (!total) return "";
    if (inbox?.paused) return `Paused. Press Q to sort it out`;
    const things = waiting.reduce((n, i) => n + Math.max(1, i.count), 0) + local.reduce((n, r) => n + Math.max(1, r.subject?.count || 1), 0);
    if (things === 1) return `Looking into ${waiting[0]?.subject || local[0].subject?.name || "this"}`;
    return `Looking into ${things} things`;
  }
  function updateCapsule() {
    if (S.hold || S.coachTimer) return;
    const text = capsuleText();
    if (!text) { if (S.pillMode === "capsule") hidePill(); return; }
    S.pillMode = "capsule";
    P.pill.o.to(1);
    pushPill("capsule", text, !inbox?.paused);
    placeCapsule();
  }
  function capsuleSpot(w) {
    if (S.view && S.pos) {
      const {hard} = avoidance(viewItem());
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
    const rec = S.localPending.at(-1) || anchors.get(inProgress().at(-1)?.id);
    const {hard} = avoidance(rec);
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
    if (S.pillMode !== "capsule") return;
    const w = S.pillW || 170;
    const spot = capsuleSpot(w);
    P.pill.x.to(spot.x); P.pill.y.to(spot.y); P.pill.w.to(w); P.pill.h.to(PILL_H);
    wake();
  }
  function coachLine(text, ms) {
    clearTimeout(S.coachTimer);
    S.pillMode = "coach";
    const w = Math.ceil((text.length * 6.6 + 34) / 16) * 16, vw = innerWidth;
    P.pill.x.snap(vw / 2 - w / 2); P.pill.y.snap(innerHeight - 76); P.pill.w.snap(w); P.pill.h.snap(PILL_H);
    P.pill.o.to(1);
    setTone(darkAt(vw / 2 - w / 2, innerHeight - 76, w, PILL_H));
    raise();
    pushPill("coach", text, false);
    S.coachTimer = setTimeout(() => {
      S.coachTimer = 0;
      if (S.pillMode === "coach") hidePill();
      updateCapsule();
    }, ms);
    wake();
  }

  // ---------- talking ----------
  function waveText() {
    if (S.micWarning) return S.micWarning;
    if (S.hold?.follow) return "Asking more about this";
    if (!S.micReady) return S.micSlow ? "Starting…" : "";
    return S.coach.heard < 3 ? "Listening" : "";
  }
  function refreshWave() { if (S.hold) { pushPill("wave", waveText(), false); } }
  function startListening() {
    if (isListening || document.visibilityState !== "visible" || !document.hasFocus()) return false;
    isListening = true;
    S.micReady = false; S.micSlow = false; S.micWarning = "";
    clearTimeout(S.micTimer);
    // Only a slow start earns a word. A quick one just goes straight to Listening.
    S.micTimer = setTimeout(() => { if (isListening && !S.micReady) { S.micSlow = true; refreshWave(); } }, 250);
    if (!_emit({ type: "record_start" })) { isListening = false; return false; }
    return true;
  }
  function holdStart() {
    S.keyArmed = false;
    if (state.mode === "webcam" && !freshWebcam()) {
      coachLine("No fresh gaze. Check /gaze tracker; move the pointer once in this page.", 4000);
      return;
    }
    clearTimeout(S.retreatTimer); S.retreatAt = 0;
    if (S.coachTimer) { clearTimeout(S.coachTimer); S.coachTimer = 0; }
    raise();
    const item = S.view === "answer" ? current() : null;
    // Small pointer travel keeps the card, unless the page moved a different identity underneath.
    const follow = item && followsCurrent(item) ? item : null;
    S.hold = {started: performance.now(), targets: [], tentative: null, dwellFrom: 0, follow, region: null, moved: S.pointer.moved, onCard: !!follow && S.hoverCard};
    if (!S.view && typeof state.pointerX === "number") setTone(darkAt(Math.max(0, state.pointerX - 150), Math.max(0, state.pointerY - 100), 300, 200));
    if (!S.view) { dropAllRings(); S.capSpot = null; }
    const {x, y} = pillAnchor();
    S.pillMode = "wave";
    const p = P.pill;
    if (p.o.t === 0 || p.o.x < .05) { p.x.snap(x + 34); p.y.snap(y); p.w.snap(28); p.h.snap(PILL_H - 8); }
    p.x.to(x); p.y.to(y); p.h.to(PILL_H);
    p.o.to(1);
    if (!startListening()) { S.hold = null; hidePill(); updateCapsule(); armRetreat(); return; }
    refreshWave();
    if (state.mode !== "hover") S.gaze = {x: new Spring(state.pointerX ?? innerWidth / 2, GAZE), y: new Spring(state.pointerY ?? innerHeight / 2, GAZE), stillAt: performance.now(), lockX: null, lockY: null};
    updatePointing(performance.now(), true);
    wake();
  }
  function pillAnchor() {
    const vw = innerWidth, vh = innerHeight;
    const w = S.pillW || 96;
    if (S.hold?.follow && S.view === "answer" && !pointedElsewhere()) {
      // A follow-up belongs to the card: dock on its lower edge.
      const dockY = Math.min(vh - PILL_H - 10, front.y.t + front.h.t - PILL_H / 2 + 2);
      return {x: S.pos.x + (front.w.t - w) / 2, y: dockY};
    }
    const soft = state.mode !== "hover" && S.gaze;
    const anchorX = soft ? S.gaze.x.x : state.pointerX ?? vw / 2, anchorY = soft ? S.gaze.y.x : state.pointerY ?? vh / 2;
    let x = anchorX + 18, y = anchorY + 22;
    if (soft) { x = anchorX - w / 2; y = anchorY + REGION_H / 2 - 10; }
    if (x + w > vw - 10) x = anchorX - w - 16;
    if (y + PILL_H > vh - 10) y = Math.max(10, anchorY - PILL_H - 16);
    return {x: Math.max(10, x), y: Math.max(10, y)};
  }
  function followsCurrent(item) {
    if (S.hoverCard) return true;
    if (S.pointer.moved >= FOLLOW_UP_PX) return false;
    const anchor = item.pointerAnchor;
    return !!anchor && hitNode(anchor.x, anchor.y) === anchor.hit;
  }
  // Talking stops the card taking hover, which itself fires a mouse event with no travel.
  // So a hold that began on the card stays on it until the pointer really travels.
  function pointedElsewhere() {
    const H = S.hold;
    if (H?.onCard) return S.pointer.moved - H.moved >= FOLLOW_UP_PX;
    return !S.hoverCard && (S.pointer.moved >= FOLLOW_UP_PX || H?.follow && !followsCurrent(H.follow));
  }
  function updatePointing(now, immediate) {
    const H = S.hold;
    if (!H || typeof state.pointerX !== "number") return;
    if (H.follow && !pointedElsewhere()) return; // still on the card
    if (state.mode === "webcam" && !freshWebcam()) { dropTentative(H); return; }
    if (state.mode !== "hover") { updateSoft(now); return; }
    const n = pickElement(state.pointerX, state.pointerY);
    const already = n && H.targets.find(t => t.el === n);
    if (!n || already) { dropTentative(H); return; }
    if (H.tentative?.el !== n) {
      dropTentative(H);
      const t = {el: n, hit: hitNode(state.pointerX, state.pointerY), key: `t${++S.ids}`};
      H.tentative = t;
      H.dwellFrom = now;
      ringFor(t.key, t, "tentative");
    }
    if (immediate || now - H.dwellFrom >= DWELL_MS) {
      if (H.targets.length >= MAX_TARGETS) return;
      H.targets.push(H.tentative);
      const ring = lit.get(H.tentative.key);
      if (ring) ring.style = "live";
      H.tentative = null;
    }
  }
  function dropTentative(H) { if (H.tentative) { dropRing(H.tentative.key); H.tentative = null; } }
  // Soft region: a real state for any noisy pointing source. Feed it with api.pointSoft(x, y).
  function updateSoft(now) {
    const H = S.hold, G = S.gaze;
    if (!G) return;
    const feed = S.softPoint && now - S.softPoint.at < 800 ? S.softPoint : null;
    if (state.mode === "webcam" && !feed) return;
    const sx = feed ? feed.x : state.pointerX, sy = feed ? feed.y : state.pointerY;
    const t = now / 1000;
    // Without a feed, simulated mode adds the slow wander of a smoothed gaze estimate.
    G.x.to(sx + (feed || reduced() ? 0 : Math.sin(t * 1.3) * 16 + Math.sin(t * 3.1) * 6));
    G.y.to(sy + (feed || reduced() ? 0 : Math.sin(t * 1.7 + 1) * 11 + Math.sin(t * 2.7) * 5));
    if (!H.tentative) {
      const c = regionAt(G.x.x, G.y.x);
      c.key = `t${++S.ids}`;
      H.tentative = c;
      ringFor(c.key, c, "live");
    }
    // The live region follows gaze; a long enough look leaves one lit behind.
    const c = H.tentative;
    const r = c.anchor?.getBoundingClientRect?.();
    c.cx = G.x.x + scrollX; c.cy = G.y.x + scrollY;
    if (r) { c.dx = G.x.x - r.left; c.dy = G.y.x - r.top; }
    const dist = Math.hypot(sx - (G.lockX ?? sx), sy - (G.lockY ?? sy));
    if (G.lockX == null || dist > 130) { G.lockX = sx; G.lockY = sy; G.stillAt = now; }
    const nearPin = H.targets.some(tt => {
      const r2 = targetRect(tt);
      return r2 && Math.hypot(r2.left + REGION_W / 2 - G.x.x, r2.top + REGION_H / 2 - G.y.x) < 170;
    });
    if (now - G.stillAt > 340 && !nearPin && H.targets.length < MAX_TARGETS) {
      const pinned = {...regionAt(G.x.x, G.y.x), key: `t${++S.ids}`};
      ringFor(pinned.key, pinned, "live");
      H.targets.push(pinned);
    }
    // The moving pool gives way to a pinned one, so light never stacks up.
    lit.get(c.key)?.g.o.to(nearPin || (now - G.stillAt > 340) ? 0 : 1);
  }
  function holdEnd(cancelled, reason) {
    const H = S.hold;
    if (!H) return;
    S.hold = null;
    // A quick look still counts: what was under the pointer at release is what you meant.
    if (H.tentative && !H.targets.length && !(H.follow && !pointedElsewhere()) && !cancelled) {
      H.targets.push(H.tentative);
      H.tentative = null;
    }
    dropTentative(H);
    S.gaze = null;
    const heldFor = performance.now() - H.started;
    const tooShort = heldFor < MIN_HOLD_MS;
    if (cancelled || tooShort) {
      for (const t of H.targets) dropRing(t.key);
      cancelListening(cancelled ? reason : "");
      if (S.pillMode === "wave") hidePill();
      updateCapsule();
      armRetreat();
      if (S.view === "answer") lightCurrent(current(), "answer");
      return;
    }
    S.coach.heard++;
    sendCoach({heard: S.coach.heard});
    // Pointing somewhere else makes it a new question; otherwise it stays with the card.
    const follow = H.follow && !H.targets.length ? H.follow : null;
    const rec = follow ? null : {targets: H.targets, subject: subjectFor(H.targets)};
    stopListening(rec, follow);
    S.pointer.moved = 0;
    if (S.pillMode === "wave") hidePill(!!follow);
    if (rec) {
      S.pillW = S.pillW || 170;
      updateCapsule();
      P.pill.w.kick(70);
    } else updateCapsule();
    armRetreat();
    // What you pointed at goes into the capsule, so you can see where your question went.
    // The answer lights it again.
    setTimeout(() => {
      if (S.hold) return;
      const cur = S.view === "answer" ? current() : null;
      for (const t of H.targets) {
        if (cur?.targets.includes(t)) continue;
        const ring = lit.get(t.key);
        if (ring && S.pillMode === "capsule" && !reduced() && !t.soft) {
          ring.fly = {x: () => P.pill.x.x + 8, y: () => P.pill.y.x + 11};
          // Collapse first, then travel: a small spark, never a big box sliding over the page.
          ring.g.w.k = ring.g.h.k = 900; ring.g.w.c = ring.g.h.c = 60;
          ring.g.x.k = ring.g.y.k = 170; ring.g.x.c = ring.g.y.c = 24;
          setTimeout(() => { if (ring.fly) dropRing(t.key); }, 170);
        } else dropRing(t.key);
      }
    }, 230);
  }
  function stopListening(rec, follow) {
    if (!isListening) return;
    isListening = false;
    resetMic();
    // Freeze evidence at release, before transcription and before routing can change it.
    litIds = rec ? rec.targets.map(t => t.hit ? cursorId(t.hit) : null).filter(Boolean) : [];
    const intent = { type: "record_stop", mode: state.mode, item_id: follow?.id || "", subject: rec?.subject,
      ...(state.mode === "hover" ? { cursor_context: captureCursorContext() } : captureNoisyContext()) };
    litIds = [];
    if (rec) bindRequest(intent, rec);
    _emit(intent);
    if (rec) { requestOwner.set(intent.id, rec); }
  }
  function bindRequest(intent, rec) {
    rec.pointerAnchor = {x: state.pointerX, y: state.pointerY, hit: hitNode(state.pointerX, state.pointerY)};
    if (state.mode === "webcam") webcamAskedAt = {x: state.pointerX, y: state.pointerY};
    if (intent.cursor_context?.snapshot_id) snapshotOwner.set(intent.cursor_context.snapshot_id, rec);
    S.localPending.push(rec);
  }
  function resetMic() {
    S.micReady = false; S.micWarning = ""; S.micSlow = false;
    clearTimeout(S.micTimer);
  }
  function cancelListening(reason = "") {
    if (!isListening) return;
    isListening = false;
    spaceHeld = false;
    _emit({ type: "record_cancel" });
    resetMic();
    if (reason) coachLine(reason, 4600);
  }

  // ---------- typed questions: private input, in the frame until sent ----------
  function openComposer() {
    if (S.hold) return;
    if (S.coachTimer) { clearTimeout(S.coachTimer); S.coachTimer = 0; if (S.pillMode === "coach") hidePill(true); }
    const open = S.view === "answer" ? current() : null;
    const follow = open && followsCurrent(open) ? open : null;
    if (!follow) setTargetLocked(true);
    const node = lockedNode;
    const target = !follow && node && !ours(node) ? {el: pickElement(state.lockedX, state.lockedY) || node, hit: node, key: `t${++S.ids}`} : null;
    const targets = target ? [target] : [];
    const subject = subjectFor(targets);
    S.compose = {title: follow ? follow.subject : subject.name, itemId: follow?.id || "", targets: follow ? follow.targets : targets, subject, focus: true};
    if (target) { dropAllRings(); ringFor(target.key, target, "live"); }
    openView("compose", S.compose);
  }
  function closeComposer() {
    const compose = S.compose;
    S.compose = null;
    setTargetLocked(false);
    for (const t of compose?.targets || []) if (!compose?.itemId) dropRing(t.key);
    restoreAfterOverlay();
  }
  function submitTyped(value) {
    const compose = S.compose;
    if (!compose) return;
    const text = String(value || "").trim();
    if (!text) { compose.focus = true; pushCard(); return; }
    if (compose.itemId) {
      _emit({ type: "followup", item_id: compose.itemId, utterance: text });
      S.pointer.moved = 0;
      closeComposer();
      return;
    }
    const rec = {targets: compose.targets, subject: compose.subject};
    litIds = compose.targets.map(t => t.hit ? cursorId(t.hit) : null).filter(Boolean);
    const sent = emitResolve(text, null, null, rec);
    litIds = [];
    if (!sent) { compose.focus = true; pushCard(); return; }
    S.compose = null;
    setTargetLocked(false);
    S.pointer.moved = 0;
    S.capSpot = null;
    closeStack("cancel");
    if (compose.targets.length && !reduced()) {
      for (const t of compose.targets) dropRing(t.key);
    }
    updateCapsule();
  }
  function setTargetLocked(locked) {
    if (locked && typeof state.pointerX !== "number") return;
    state.armed = locked;
    lockedNode = locked ? cursorRefs.get(cursorHistory.at(-1)?.id) || null : null;
    state.lockedX = locked ? state.pointerX : null;
    state.lockedY = locked ? state.pointerY : null;
    if (locked) state.armedAt = Date.now() / 1000;
  }
  function dismissNote() {
    if (isListening && S.hold) holdEnd(true, "Recording cancelled by you.");
    else if (isListening) cancelListening("Recording cancelled by you.");
    state.lensActive = false;
    state.lensCandidates = [];
    state.choosePending = false;
    clearActionConfirmation();
    setTargetLocked(false);
    if (S.view) closeStack(S.view === "answer" ? "dismiss" : "cancel");
    else dropAllRings();
  }

  // ---------- private frames back to this world ----------
  function positionNote() { wake(); }
  function fromPanel(frame, m) {
    if (destroyed || !m || typeof m !== "object") return;
    if (m.t === "size") {
      if (frame === "pill") {
        if (!(m.w > 0)) return;
        S.pillW = Math.min(460, m.w);
        if (S.pillMode === "capsule") placeCapsule();
        if (S.pillMode === "wave" && S.hold) { const {x, y} = pillAnchor(); P.pill.x.to(x); P.pill.y.to(y); P.pill.w.to(S.pillW); }
        if (S.pillMode === "coach") { P.pill.w.snap(S.pillW); P.pill.x.snap(innerWidth / 2 - S.pillW / 2); }
        wake();
        return;
      }
      S.sizes = {prevH: +m.prevH || 0, cardH: +m.cardH || 0, nextH: +m.nextH || 0, contentH: +m.contentH || 0, bodyH: +m.bodyH || 0};
      if (S.view) {
        const item = viewItem();
        const mb = maxBodyFor(item);
        if (Math.abs(mb - S.maxBody) > 2) { S.maxBody = mb; pushCard(); }
        // Long answer ran out of room where it is: find better room once, before it clips hard.
        if (S.view === "answer" && S.sizes.contentH > S.sizes.bodyH + 20 && S.maxBody < 300 && !S.reposition.has(S.cur)) {
          S.reposition.add(S.cur);
          const spot = place(item, Math.min(innerHeight - 2 * MARGIN, S.sizes.contentH + 90));
          if (spot.covers === 0) { S.pos = {x: spot.x, y: spot.y}; S.maxBody = maxBodyFor(item); pushCard(); }
        }
        layout();
      }
      return;
    }
    if (m.t === "hover") {
      if (frame !== "card") return;
      S.hoverCard = !!m.on;
      cursorOverHud = S.hoverCard;
      if (m.on) { clearTimeout(S.retreatTimer); S.retreatAt = 0; } else if (S.view === "answer") armRetreat();
      return;
    }
    if (!surfaceIntact()) return;
    if (m.t === "key") {
      onWindowKey({type: m.type, code: String(m.code), key: String(m.key), repeat: !!m.repeat, shiftKey: !!m.shift, metaKey: !!m.meta,
        ctrlKey: !!m.ctrl, altKey: !!m.alt, fromFrame: true, isTrusted: true, preventDefault() {}, stopImmediatePropagation() {}, stopPropagation() {}, composedPath: () => []});
      return;
    }
    if (m.t !== "ui") return;
    const item = S.view === "answer" ? current() : null;
    const a = m.action;
    if (a === "stop_action_task") { stopActionTask(); return; }
    if (a === "next") step(1);
    else if (a === "prev") step(-1);
    else if (a === "dismiss") dismissNote();
    else if (a === "go") { goBack(item); releaseFrameFocus(); }
    else if (a === "read" && item) control(inbox?.speaking_item_id === item.id ? "stop_speaking" : "speak", item.id);
    else if (a === "autoread") control("auto_speak");
    else if (a === "retry" && item) control("retry", item.id, m.turn || "");
    else if (a === "skip" && item) control("skip", item.id, m.turn || "");
    else if (a === "resume") control("resume");
    else if (a === "submit") submitTyped(m.value);
    else if (a === "cancel") closeComposer();
    else if (a === "confirm") confirmClick(m.value === "yes", {isTrusted: true, button: m.button, detail: m.detail, pointerType: m.pointerType});
    else if (a === "lens") selectLensCandidate(Number(m.value), m.modality || "click");
    else if (a === "link" && m.detail >= 1) _emit({type: "open_link", url: m.url});
  }
  // A click in a frame keeps keyboard focus there. Give it back unless someone is typing.
  function releaseFrameFocus() { if (S.view !== "compose") { try { window.focus(); } catch (_) {} } }

  function control(action, itemId = "", requestId = "") {
    return _emit({type: "inbox", action, item_id: itemId, request_id: requestId});
  }
  function sendCoach(fields) { _emit({type: "inbox", action: "coach", coach: fields}); }

  function renderInbox(event) {
    if (event.revision <= inboxRevision) return;
    const previous = inbox;
    inboxRevision = event.revision;
    inbox = event;
    if (event.coach) {
      for (const key of ["heard", "answered"]) S.coach[key] = Math.max(S.coach[key], event.coach[key] || 0);
      S.coach.retreated = S.coach.retreated || !!event.coach.retreated;
      S.coach.greeted = S.coach.greeted || !!event.coach.greeted;
    }
    S.items = event.items.map(itemView);
    if (event.session_connected === false && previous?.session_connected !== false) {
      if (S.hold) holdEnd(true, "Recording cancelled: disconnected from Hermes.");
      else {
        cancelListening("Recording cancelled: disconnected from Hermes.");
        coachLine("Hermes is disconnected. Run /gaze in Hermes to reconnect", 6000);
      }
    }
    if (event.session_connected && !S.coach.greeted && !event.items.length) {
      S.coach.greeted = true;
      sendCoach({greeted: true});
      if (!S.hold) coachLine("Point at anything, hold Space and ask", 7000);
    }
    refresh();
  }
  // Answers that have started arrive by themselves, one at a time, in question order.
  function refresh() {
    if (!S.hold && !S.view) {
      const first = visible().find(i => !i.presented && started(i));
      if (first) { openStack(first); updateCapsule(); return; }
    }
    updateCapsule();
    if (S.view === "answer") {
      const item = current();
      if (!item || !visible().includes(item)) {
        // This answer was skipped away. Move on, or leave.
        const list = visible();
        const nextUp = list.find(i => started(i) && !i.presented) || (S.items.some(i => i.id === S.cur) ? list[0] : null);
        if (nextUp) openStack(nextUp); else closeStack("dismiss");
        return;
      }
      const busy = isBusyItem(item);
      if (S.wasBusy && !busy) armRetreat();
      else if (busy) { clearTimeout(S.retreatTimer); S.retreatAt = 0; }
      else if (S.wasReading && inbox?.speaking_item_id !== item.id) armRetreat();
      S.wasBusy = busy;
      S.wasReading = inbox?.speaking_item_id === item.id;
      if (S.wasReading) { clearTimeout(S.retreatTimer); S.retreatAt = 0; }
      pushCard();
      layout();
    }
  }
  function stopActionTask() {
    if (!actionTask) return;
    actionTask = null;
    revokeActionAuthority();
    if (actionApproval) { actionApproval.cleanup(); actionApproval = null; }
    if (S.view === "doing") restoreAfterOverlay();
    _emit({type: "stop_action_task"});
  }
  function onSessionEvent(event) {
    if (destroyed) return;
    if (event?.type === "inbox") renderInbox(event);
    if (event?.type === "action_task") {
      actionTask = event.status === "doing" ? {label: String(event.label || "Working on this page")} : null;
      if (event.status === "stopped") {
        clearActionConfirmation();
        if (actionApproval) { actionApproval.cleanup(); actionApproval = null; }
      }
      if (confirmation) pushCard();
      else if (actionTask) openView("doing", {targets: []});
      else if (S.view === "doing") restoreAfterOverlay();
    }
  }
  function revokeActionAuthority() {
    for (const saved of snapshots.values()) saved.actionRevoked = true;
    clearActionConfirmation();
    if (actionApproval) { actionApproval.cleanup(); actionApproval = null; }
    state.lensActive = false;
  }
  function onNavigation() {
    activeSnapshot = null;
    snapshots.clear();
    stopTrackingPins();
    clearActionConfirmation();
    cancelListening("Recording cancelled: the source document changed.");
  }
  window.addEventListener("pagehide", onNavigation);
  function onCursorScroll() {
    if (state.mode !== "webcam" && !state.armed && !cursorOverHud && typeof state.pointerX === "number")
      rememberHit(hitNode(state.pointerX, state.pointerY));
    positionNote();
  }
  window.addEventListener("scroll", onCursorScroll, { passive: true, capture: true });

  function updateLiveInspector(x, y) {
    const el = state.armed ? lockedNode : hitNode(x, y);
    state.hoveredCandidate = el ? cursorMetadata(el) : null;
  }

  function recordPoint(x, y) {
    if (state.mode === "webcam") return; // Mouse movement is geometry only, never gaze evidence.
    const now = performance.now() / 1000;
    state.pointerX = x;
    state.pointerY = y;

    // If locked, keep the ringBuffer anchored on the locked target!
    const activeX = state.armed && state.lockedX !== null ? state.lockedX : x;
    const activeY = state.armed && state.lockedY !== null ? state.lockedY : y;
    if (!state.armed) rememberHit(hitNode(x, y));

    state.ringBuffer.push({
      x_vp: activeX,
      y_vp: activeY,
      x_doc: activeX + window.scrollX,
      y_doc: activeY + window.scrollY,
      t: Date.now() / 1000,
      sigma: state.mode === "hover" ? state.hoverSigmaPx : state.sigmaPx,
    });
    const cutoff = (Date.now() / 1000) - 10.0;
    while (state.ringBuffer.length > 250 || (state.ringBuffer.length > 1 && state.ringBuffer[0].t < cutoff)) {
      state.ringBuffer.shift();
    }

    if (!state.armed) updateLiveInspector(x, y);

    // Cursor wiggle detector (>= 3 horizontal direction flips within 450 ms)
    if (state.wiggleTrigger && !state.armed) {
      state.wiggleHistory.push({ x, t: now });
      while (state.wiggleHistory.length > 0 && now - state.wiggleHistory[0].t > 0.48) {
        state.wiggleHistory.shift();
      }
      if (state.wiggleHistory.length >= 6) {
        let flips = 0;
        let prevSign = 0;
        let totalTravel = 0;
        for (let i = 1; i < state.wiggleHistory.length; i++) {
          const dx = state.wiggleHistory[i].x - state.wiggleHistory[i - 1].x;
          if (Math.abs(dx) > 12) {
            totalTravel += Math.abs(dx);
            const sign = dx > 0 ? 1 : -1;
            if (prevSign !== 0 && sign !== prevSign) flips++;
            prevSign = sign;
          }
        }
        if (flips >= 3 && totalTravel > 95) {
          state.wiggleHistory = [];
          armInteraction("wiggle");
        }
      }
    }
  }
  let webcamAnchor = null, webcamAskedAt = null, lastWebcamAt = 0;
  function freshWebcam() { return performance.now() - lastWebcamAt < 800 && lastWebcamAt > 0; }
  function webcamViewport(screenDpr) {
    const a = webcamAnchor;
    if (!a || a.dpr !== devicePixelRatio || a.width !== innerWidth || a.height !== innerHeight ||
        a.outerWidth !== outerWidth || a.outerHeight !== outerHeight || visualViewport?.scale !== 1) return {};
    const zoom = devicePixelRatio / screenDpr;
    return {origin_x: a.sx - a.x * zoom + screenX - a.windowX,
      origin_y: a.sy - a.y * zoom + screenY - a.windowY,
      dpr: devicePixelRatio, width: innerWidth, height: innerHeight, scroll_x: scrollX, scroll_y: scrollY,
      screen_left: screen.availLeft, screen_top: screen.availTop, screen_width: screen.width, screen_height: screen.height};
  }
  function acceptWebcamSample(s) {
    if (state.mode !== "webcam" || !s || s.source !== "webcam" ||
        ![s.x_vp, s.y_vp, s.t].every(Number.isFinite) || Math.abs(Date.now() / 1000 - s.t) > 1) return false;
    lastWebcamAt = performance.now();
    state.pointerX = s.x_vp; state.pointerY = s.y_vp;
    if (webcamAskedAt) S.pointer.moved = Math.hypot(s.x_vp - webcamAskedAt.x, s.y_vp - webcamAskedAt.y);
    state.ringBuffer.push(s);
    while (state.ringBuffer.length > 100 || state.ringBuffer[0]?.t < s.t - 10) state.ringBuffer.shift();
    api.pointSoft(s.x_vp, s.y_vp);
    return true;
  }
  function captureNoisyContext(radius = state.candidateRadiusPx || 380) {
    const usable = state.mode !== "webcam" || freshWebcam();
    const locked = state.mode !== "webcam" && state.armed && state.lockedX !== null;
    const x = locked ? state.lockedX : state.pointerX, y = locked ? state.lockedY : state.pointerY;
    return {page_url: location.origin + location.pathname,
      pointer: {x_vp: x, y_vp: y, scroll_x: scrollX, scroll_y: scrollY},
      fixations: usable ? state.ringBuffer.slice(-25) : [],
      candidates: usable ? extractCandidatesNear(x, y, radius) : []};
  }
  function onWindowMouseMove(e) {
    if (!e.isTrusted) return;
    if (state.mode === "webcam") {
      webcamAnchor = {sx: e.screenX, sy: e.screenY, x: e.clientX, y: e.clientY, windowX: screenX, windowY: screenY,
        dpr: devicePixelRatio, width: innerWidth, height: innerHeight, outerWidth, outerHeight};
      return;
    }
    if (typeof state.pointerX === "number") S.pointer.moved += Math.hypot(e.clientX - state.pointerX, e.clientY - state.pointerY);
    S.hoverCard = false;
    cursorOverHud = false;
    recordPoint(e.clientX, e.clientY);
    if (S.hold) wake();
  }
  window.addEventListener("mousemove", onWindowMouseMove, {passive: true, capture: true});

  function armInteraction() { openComposer(); }

  // --- Resolver Intent Channel (the Python session resolves, explains, transcribes & clicks) ---
  let _intentSeq = 0;
  let _lastSentResolveId = 0;
  let _pendingUtterance = "";
  let _pendingExplainFallback = "";
  let _pendingExplainRid = 0;
  // Session nonce set via setIntentNonce() after Python (re)injects us. Stays in closure —
  // page scripts can call the binding but cannot read this value, so they cannot forge intents.
  let _intentNonce = "";

  function _emit(intent) {
    intent.id = ++_intentSeq;
    intent.nonce = _intentNonce;
    if (typeof window.__hermesGazeIntent !== "function") {
      coachLine("Hermes isn’t connected. Run /gaze in Hermes, then try again", 4600);
      return false;
    }
    window.__hermesGazeIntent(JSON.stringify(intent));
    return true;
  }

  function renderScopeOptions(msg) {
    state.resolutionId = msg.resolution_id || 0;
    state.scopes = msg.scopes || [];
    state.selectedScopeId = msg.selected_scope_id;
  }
  function emitResolve(utterance, words, captured, rec) {
    const text = (utterance || "").trim();
    if (!text) return false;
    if (state.mode === "webcam" && !freshWebcam()) {
      coachLine("No fresh gaze. Check /gaze tracker; move the pointer once in this page.", 4000);
      return false;
    }
    state.scopePending = false;
    state.scopes = [];
    const locked = state.armed && state.lockedX !== null && state.lockedY !== null;
    const px = locked ? state.lockedX : state.pointerX;
    const py = locked ? state.lockedY : state.pointerY;
    if (typeof px !== "number" || typeof py !== "number") {
      coachLine("Point at something first, then ask", 3200);
      return false;
    }
    const evidence = state.mode === "hover" ? captured || captureCursorContext() : null;
    const owner = rec || {targets: [], subject: {name: "", count: 1}};
    const intent = {
      type: state.mode === "hover" ? "submit" : "resolve",
      utterance: text,
      subject: owner.subject,
      page_url: location.origin + location.pathname,
      pointer: { x_vp: px, y_vp: py, scroll_x: window.scrollX, scroll_y: window.scrollY },
      fixations: state.ringBuffer.slice(-25),
      ...(state.mode === "hover" ? { cursor_context: evidence } : captureNoisyContext()),
    };
    if (words) {
      intent.words = words;
    }
    bindRequest(intent, owner);
    if (!_emit(intent)) { S.localPending = S.localPending.filter(r => r !== owner); return false; }
    requestOwner.set(intent.id, owner);
    _lastSentResolveId = intent.id;
    _pendingUtterance = text;
    return true;
  }

  function emitChoose(idx, modality) {
    return _emit({
      type: "choose",
      resolution_id: state.resolutionId || 0,
      candidate_index: idx + 1,
      modality: modality || "click",
    });
  }

  function settleRequest(msg) {
    const rec = requestOwner.get(msg.id);
    if (!rec) return;
    requestOwner.delete(msg.id);
    S.localPending = S.localPending.filter(r => r !== rec);
    if (msg.item_id) {
      anchors.set(msg.item_id, rec);
      S.items = (inbox?.items || []).map(itemView);
      if (S.view === "answer" && S.cur === msg.item_id) lightCurrent(current(), "answer");
    }
    updateCapsule();
    if (S.view === "answer") pushCard();
  }

  function onIntentResult(msg) {
    if (typeof msg === "string") {
      try {
        msg = JSON.parse(msg);
      } catch (_) {
        return;
      }
    }
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "record_reserved") {
      settleRequest(msg);
      refresh();
      return;
    }
    if (requestOwner.has(msg.id) && (msg.item_id || msg.ok === false || msg.delivery)) settleRequest(msg);
    if (msg.type === "inbox" || msg.type === "followup" || msg.type === "open_link" || msg.type === "show_source") {
      if (!msg.ok && msg.error) showPlainMessage(msg.error);
      return;
    }

    if (msg.type === "record_warning") {
      if (isListening) {
        S.micWarning = `${msg.seconds_remaining} seconds left. Let go of Space`;
        refreshWave();
        wake();
      }
      return;
    }
    if (msg.type === "record_start") {
      if (!msg.ok) {
        isListening = false;
        resetMic();
        spaceHeld = false;
        S.keyDown = false;
        if (S.hold) { S.hold.tentative && dropRing(S.hold.tentative.key); for (const t of S.hold.targets) dropRing(t.key); S.hold = null; }
        if (S.pillMode === "wave") hidePill(true);
        coachLine(msg.error || "The microphone isn’t available", 4600);
        armRetreat();
      } else if (isListening) {
        S.micReady = true;
        S.micSlow = false;
        clearTimeout(S.micTimer);
        refreshWave();
      }
      return;
    }
    if (msg.type === "record_cancel") {
      if (msg.cancelled && !isListening) return; // Keep the local, specific cancellation reason.
      isListening = false;
      spaceHeld = false;
      S.keyDown = false;
      resetMic();
      const reason = msg.error || "Recording cancelled.";
      if (S.hold) {
        S.hold.tentative && dropRing(S.hold.tentative.key);
        for (const t of S.hold.targets) dropRing(t.key);
        S.hold = null;
        S.gaze = null;
        if (S.pillMode === "wave") hidePill(true);
        armRetreat();
      }
      coachLine(reason, 5200);
      return;
    }
    if (msg.type === "record_stop") {
      if (msg.delivery === "one_shot") {
        renderScopeOptions(msg);
        showPlainMessage(msg.explanation || "", true);
      } else if (!msg.ok && !msg.item_id) showPlainMessage(msg.error || "That recording didn’t work.");
      return;
    }
    if (msg.type === "confirm_action") {
      if (msg.resolution_id !== state.resolutionId && activeSnapshot?.resolutionId !== msg.resolution_id) return;
      if (!msg.ok && msg.error) showPlainMessage(msg.error);
      return;
    }

    if (msg.type === "submit") {
      if (!msg.ok) {
        showPlainMessage(msg.error || "Run /gaze in Hermes, then try again.");
      } else if (msg.delivery === "one_shot") {
        renderScopeOptions(msg);
        if (msg.mode !== "hover" && Array.isArray(msg.ranked)) renderPins(msg.ranked);
        showPlainMessage(msg.explanation || msg.text || msg.answer || "", true);
      }
      return;
    }
    if (msg.type === "resolve" || msg.type === "scope") {
      if (msg.type === "resolve" && msg.id < _lastSentResolveId) return;
      if (msg.type === "scope") {
        state.scopePending = false;
        if (msg.resolution_id && msg.resolution_id < state.resolutionId) return;
      }
      if (!msg.ok) {
        showPlainMessage(msg.error || "That didn’t work.");
        return;
      }
      renderScopeOptions(msg);
      if (msg.needs_explain && msg.top) {
        _pendingExplainFallback = msg.top.summary || "";
        _pendingExplainRid = msg.resolution_id || 0;
        _emit({
          type: "explain",
          utterance: _pendingUtterance,
          scope_id: state.selectedScopeId,
          resolution_id: _pendingExplainRid,
        });
      }
      return;
    }

    if (msg.type === "explain") {
      if (msg.scope_id !== state.selectedScopeId || msg.resolution_id !== state.resolutionId) return;
      showPlainMessage(msg.explanation || msg.error || _pendingExplainFallback || "No explanation is available.", true);
      return;
    }

    if (msg.type === "choose") {
      state.choosePending = false;
      if (msg.ok) {
        state.lensActive = false; // consumed — Python already re-rendered the pin
        if (S.view === "lens") restoreAfterOverlay();
      } else {
        // keep the lens live so dwell/keys still work after a failed choose
        showPlainMessage(msg.error || "That selection didn’t work.");
      }
      return;
    }

    // "configure" acks and unknown types are no-ops
  }

  const TALK_KEY = "Space";
  let isListening = false;
  let spaceHeld = false;
  let mouseFocus = false;
  function onWindowPointerDown(e) { if (e.isTrusted) mouseFocus = true; }
  window.addEventListener("pointerdown", onWindowPointerDown, true);
  let transportUntil = 0;
  const transportTimer = setInterval(() => {
    if (performance.now() >= transportUntil && spaceHeld) {
      clearTimeout(S.armTimer);
      S.keyArmed = false;
      spaceHeld = false;
      if (S.hold) holdEnd(true);
    }
    rawSend({type: "_ui_ping"});
  }, 1000);

  function isEditableTarget(e) {
    const path = e.composedPath ? e.composedPath() : [e.target];
    for (const node of path) {
      if (!node || !node.tagName) continue;
      const tag = node.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || node.isContentEditable) {
        return true;
      }
      if (["combobox", "searchbox", "textbox"].includes(node.getAttribute?.("role"))) return true;
    }
    return false;
  }

  function onWindowKey(e) {
    if (!trustedUi(e) || document.visibilityState !== "visible" || performance.now() >= transportUntil) return;
    const down = e.type === "keydown";
    if (down && e.code !== TALK_KEY) mouseFocus = false;
    const swallow = () => { e.preventDefault(); e.stopImmediatePropagation(); };
    // A held key always finishes, wherever the release lands.
    if (e.code === TALK_KEY && !down && spaceHeld) {
      swallow();
      spaceHeld = false;
      S.keyDown = false;
      clearTimeout(S.armTimer);
      if (S.hold) holdEnd(false);
      else if (S.keyArmed) tapThrough(e);
      return;
    }
    if (!e.fromFrame && (isEditableTarget(e) ||
        e.code === TALK_KEY && !mouseFocus && document.activeElement !== document.body && document.activeElement?.matches(":focus-visible"))) return;
    if (e.code === (state.hotkey || "Backquote")) {
      if (down && !e.repeat) { swallow(); openComposer(); }
      return;
    }
    if (e.altKey || e.metaKey || e.ctrlKey) return;
    if (e.code === TALK_KEY) {
      if (!down) return;
      S.tapHandled = e.defaultPrevented;
      swallow();
      if (e.repeat || spaceHeld) return;
      spaceHeld = true;
      S.keyDown = true;
      S.keyArmed = true;
      S.armShift = !!e.shiftKey;
      S.tapFromFrame = !!e.fromFrame;
      clearTimeout(S.armTimer);
      S.armTimer = setTimeout(() => { if (spaceHeld) holdStart(); }, ARM_MS);
      return;
    }
    if (!down) return;
    if (e.key === "Escape") {
      if (actionTask) { swallow(); stopActionTask(); return; }
      if (S.hold) { swallow(); spaceHeld = false; S.keyDown = false; holdEnd(true, "Recording cancelled by you."); return; }
      if (S.view === "compose") { swallow(); closeComposer(); return; }
      if (S.view || lit.size) { swallow(); dismissNote(); }
      return;
    }
    if (e.code === "KeyQ" && !e.shiftKey) {
      if (S.hold || e.repeat) { if (S.hold) swallow(); return; }
      swallow();
      if (S.view !== "answer") recallNotes();
      return;
    }
    if (state.lensActive && /^Digit[1-9]$/.test(e.code)) {
      const idx = parseInt(e.code.replace("Digit", ""), 10) - 1;
      if (idx >= 0 && idx < state.lensCandidates.length) { swallow(); selectLensCandidate(idx, "key"); }
      return;
    }
    if (S.view !== "answer") return;
    if (e.code === "ArrowDown" || e.code === "ArrowRight") { swallow(); if (!e.repeat) step(1); }
    else if (e.code === "ArrowUp" || e.code === "ArrowLeft") { swallow(); if (!e.repeat) step(-1); }
    else if (e.code === "Enter") { swallow(); goBack(current()); }
  }
  // Never mint input. Earlier site listeners may already have handled the original key.
  function tapThrough() {
    S.keyArmed = false;
    if (S.tapFromFrame) releaseFrameFocus();
    if (!S.tapHandled)
      window.scrollBy({top: innerHeight * .85 * (S.armShift ? -1 : 1), behavior: reduced() ? "auto" : "smooth"});
  }

  function onWindowBlur() {
    if (document.visibilityState !== "visible") {
      if (S.hold) holdEnd(true, "Recording cancelled: the source tab is hidden.");
      else cancelListening("Recording cancelled: the source tab is hidden.");
      spaceHeld = false; S.keyDown = false; clearTimeout(S.armTimer);
    } else if (!document.hasFocus()) {
      if (S.hold) holdEnd(true, "Recording cancelled: the source tab lost focus.");
      else cancelListening("Recording cancelled: the source tab lost focus.");
      spaceHeld = false; S.keyDown = false; clearTimeout(S.armTimer);
    }
  }

  window.addEventListener("keydown", onWindowKey, { capture: true });
  window.addEventListener("keyup", onWindowKey, { capture: true });
  window.addEventListener("blur", onWindowBlur);
  document.addEventListener("visibilitychange", onWindowBlur);

  function getAccessibleLabel(el) {
    if (!el) return "";
    return safeText(el, 70) || el.tagName.toLowerCase();
  }

  function buildSelector(el) {
    if (!el || !el.tagName) return "";
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1) {
      const tag = node.tagName.toLowerCase();
      if (node.id) {
        const idSelector = `#${CSS.escape(node.id)}`;
        if (document.querySelectorAll(idSelector).length === 1) {
          parts.unshift(idSelector);
          break;
        }
      }
      const siblings = node.parentElement
        ? Array.from(node.parentElement.children).filter((sibling) => sibling.tagName === node.tagName)
        : [];
      parts.unshift(siblings.length > 1 ? `${tag}:nth-of-type(${siblings.indexOf(node) + 1})` : tag);
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  function extractCandidatesNear(x, y, radiusPx) {
    const rad = radiusPx || 240;
    const selectors = "button, a, input, select, textarea, [role='button'], [data-gaze-target], table, tr, th, td, [role='grid'], [role='row'], [role='columnheader'], [role='cell'], [role='gridcell'], [role='rowheader'], [data-card], section, article, [data-metric], abbr";
    const nodes = Array.from(document.querySelectorAll(selectors));
    const directEl = typeof document.elementFromPoint === "function" && x >= 0 && y >= 0 && x <= window.innerWidth && y <= window.innerHeight
      ? document.elementFromPoint(x, y) : null;
    const directCandidate = directEl && !directEl.closest("#hermes-gaze-root")
      ? directEl.closest(selectors) || directEl : null;
    if (directCandidate && !nodes.includes(directCandidate)) nodes.unshift(directCandidate);

    const results = [];
    const byElement = new Map();
    const tableRows = (table) => Array.from(table.querySelectorAll("tr,[role='row']"));
    const tableHeaders = (table) => Array.from(table.querySelectorAll("thead th, thead [role='columnheader'], [role='row'] [role='columnheader']"));
    const containerFor = (el) => el.parentElement && el.parentElement.closest("table,[role='grid'],[data-card],article.card,section.panel,section,article");
    const shortText = (el, max = 120) => safeText(el, max);
    const contextLabel = (el) => {
      const labelledBy = el.getAttribute("aria-labelledby");
      if (labelledBy) {
        const labels = labelledBy.split(/\s+/).map((id) => document.getElementById(id)).filter(Boolean).map((node) => shortText(node));
        if (labels.length) return labels.join(" ").slice(0, 100);
      }
      const heading = el.querySelector("h1,h2,h3,h4,h5,h6,[role='heading']");
      return heading ? shortText(heading, 80) : (el.id || "");
    };
    const scopeId = (el) => buildSelector(el);
    const addCandidate = (el, {scope, id, selector, rect, summary, parent} = {}) => {
      if (!el || sensitive(el) || el.closest("#hermes-gaze-root")) return null;
      const actualSelector = selector || buildSelector(el);
      if (!actualSelector) return null;
      const r = rect || el.getBoundingClientRect();
      const tag = el.tagName.toLowerCase();
      const label = getAccessibleLabel(el);
      const role = el.getAttribute("role") || (tag === "th" ? "columnheader" : tag === "td" ? "cell" :
        tag === "tr" ? "row" : tag === "table" ? "table" : tag === "a" ? "link" :
        tag === "button" ? "button" : ["section", "article"].includes(tag) ? "panel" : tag);
      const isContainer = ["table", "grid", "row", "column", "panel", "card", "section", "article", "ul", "ol"].includes(scope || role) ||
        ["table", "section", "article", "ul", "ol"].includes(tag) || el.hasAttribute("data-card");
      const isInteractive = ["button", "a", "input", "select", "textarea"].includes(tag) || role === "button";
      const isDestructive = /delete|remove|purge|drop|destroy|pay|revoke/i.test(label + " " + (el.className || ""));
      const candidate = {
        id: id || actualSelector, tag, role, label, selector: actualSelector, scope: scope || role,
        scope_ids: [], parent_container_id: parent ? scopeId(parent) : "",
        rect_vp: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
        rect_doc: [Math.round(r.left + window.scrollX), Math.round(r.top + window.scrollY), Math.round(r.width), Math.round(r.height)],
        is_container: isContainer, is_interactive: isInteractive, is_destructive: isDestructive,
        is_direct_hit: Boolean(el === directCandidate), summary: summary || shortText(el),
        consequence: "", actions: [],
      };
      const existing = byElement.get(id || actualSelector);
      if (existing) {
        if (scope) existing.scope = scope;
        if (summary) existing.summary = summary;
        return existing;
      }
      byElement.set(id || actualSelector, candidate);
      results.push(candidate);
      return candidate;
    };
    const getCellContext = (cell) => {
      const row = cell.closest("tr,[role='row']");
      const table = cell.closest("table,[role='grid']");
      if (!row || !table) return { row, table, header: null, value: shortText(cell), key: "" };
      const cells = Array.from(row.querySelectorAll("th,td,[role='cell'],[role='gridcell'],[role='columnheader']"));
      const col = Math.max(0, cells.indexOf(cell));
      const headers = tableHeaders(table);
      const header = headers[col] || null;
      const rowKey = cells.find((item) => item !== cell && item.matches("th,[role='rowheader']")) ||
        (cells[0] !== cell ? cells[0] : null);
      return { row, table, header, value: shortText(cell), key: rowKey ? shortText(rowKey, 60) : "", col };
    };

    for (const el of nodes) {
      if (el.closest("#hermes-gaze-root")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) continue;
      const cx = Math.max(r.left, Math.min(x, r.right));
      const cy = Math.max(r.top, Math.min(y, r.bottom));
      if (Math.hypot(x - cx, y - cy) > rad && el !== directCandidate) continue;

      const scopeCell = el.closest("th,td,[role='cell'],[role='gridcell'],[role='columnheader']");
      const context = scopeCell ? getCellContext(scopeCell) : null;
      const table = context && context.table || el.closest("table,[role='grid']") || (el.matches("table,[role='grid']") ? el : null);
      const row = context && context.row || (el.matches("tr,[role='row']") ? el : null);
      const cell = scopeCell || null;
      const ancestorScopes = [];
      for (let ancestor = el.parentElement; ancestor; ancestor = ancestor.parentElement) {
        if (ancestor.matches("[data-card],article.card,section.panel,section,article")) ancestorScopes.push(ancestor);
      }
      const card = ancestorScopes.find((ancestor) => ancestor.matches("[data-card],article.card"));
      const panel = ancestorScopes.find((ancestor) => ancestor.matches("section.panel,section,article"));
      const parent = containerFor(el);
      let summary = "";
      if (context) {
        const tableName = contextLabel(table) || "table";
        summary = `${context.key ? `${context.key}: ` : ""}${context.header ? shortText(context.header, 60) : `Column ${context.col + 1}`} = ${context.value} in ${tableName}`.slice(0, 180);
      } else if (row) {
        const cells = Array.from(row.querySelectorAll("th,td,[role='cell'],[role='gridcell'],[role='rowheader']"));
        const headers = table ? tableHeaders(table) : [];
        const values = cells.map((item, index) => `${headers[index] ? `${shortText(headers[index], 40)}: ` : ""}${shortText(item, 60)}`).filter(Boolean);
        summary = `Row${values.length ? `: ${values.join("; ")}` : ""}`.slice(0, 180);
      } else if (table) {
        const headers = tableHeaders(table).map((header) => shortText(header, 50)).filter(Boolean);
        summary = `Table${contextLabel(table) ? ` ${contextLabel(table)}` : ""}: ${tableRows(table).length} rows${headers.length ? `, columns ${headers.join(", ")}` : ""}`.slice(0, 180);
      } else if (panel) summary = `Panel${contextLabel(panel) ? ` ${contextLabel(panel)}` : ""}: ${shortText(panel, 140)}`;

      const candidate = addCandidate(el, {
        scope: context ? (el === scopeCell ? "cell" : (el.getAttribute("role") || el.tagName.toLowerCase())) : row ? "row" : el.matches("table,[role='grid']") ? "table" : el.matches("[data-card],article.card") ? "card" : panel ? "panel" : undefined,
        summary, parent,
      });
      if (!candidate) continue;

      const scopes = [];
      const pushScope = (scopeEl, scope, custom) => {
        if (!scopeEl) return;
        const item = addCandidate(scopeEl, custom || { scope, parent: containerFor(scopeEl) });
        if (item && !scopes.some((entry) => entry.id === item.id)) scopes.push(item);
      };
      if (candidate.id !== (cell && scopeId(cell))) pushScope(el, candidate.scope);
      if (cell) pushScope(cell, "cell", { scope: "cell", summary });
      if (row) pushScope(row, "row");
      if (context && context.header) {
        const h = context.header;
        const hr = h.getBoundingClientRect();
        const colCells = tableRows(table).map((tr) => Array.from(tr.querySelectorAll("th,td,[role='cell'],[role='gridcell'],[role='columnheader']"))[context.col]).filter(Boolean);
        if (colCells.length) {
          const rects = colCells.map((item) => item.getBoundingClientRect());
          const top = Math.min(...rects.map((item) => item.top));
          const bottom = Math.max(...rects.map((item) => item.bottom));
          const left = Math.min(...rects.map((item) => item.left));
          const right = Math.max(...rects.map((item) => item.right));
          pushScope(h, "column", {
            scope: "column", id: `${scopeId(h)}::column:${context.col + 1}`, selector: scopeId(h),
            rect: { left, top, width: right - left, height: bottom - top }, parent: table,
            summary: `Column ${shortText(h, 60)} in ${contextLabel(table) || "table"}`,
          });
        } else if (hr.width) pushScope(h, "column");
      }
      if (table) pushScope(table, "table");
      for (const ancestor of ancestorScopes) {
        if (ancestor !== table) pushScope(ancestor, ancestor.matches("[data-card],article.card") ? "card" : "panel");
      }
      candidate.scope = cell && el === cell ? "cell" : candidate.scope;
      candidate.scope_ids = scopes.map((item) => item.id);

      const actionRoot = panel || table;
      if (actionRoot) {
        const controls = Array.from(document.querySelectorAll("button,a,[role='button'],input[type='button'],input[type='submit']"));
        for (const control of controls) {
          const controlsTarget = control.getAttribute("aria-controls");
          const explicitlyAssociated = controlsTarget && table && controlsTarget.split(/\s+/).includes(table.id);
          const consequence = "";
          const tableName = table && contextLabel(table);
          const consequenceMatchesTable = Boolean(tableName && consequence.toLowerCase().includes(tableName.toLowerCase()));
          if (sensitive(control) || control.closest("#hermes-gaze-root") || (table
            ? !table.contains(control) && !explicitlyAssociated && !consequenceMatchesTable
            : !actionRoot.contains(control))) continue;
          const actionLabel = getAccessibleLabel(control);
          const action = {
            label: actionLabel, selector: buildSelector(control),
            consequence: consequence || actionLabel,
            is_destructive: /delete|remove|purge|drop|destroy|pay|revoke/i.test(actionLabel + " " + (control.className || "")),
          };
          if (action.selector && !candidate.actions.some((item) => item.selector === action.selector)) candidate.actions.push(action);
        }
      }
    }

    for (const candidate of results) {
      if (!candidate.is_interactive) continue;
      if (!candidate.actions.some((action) => action.selector === candidate.selector)) {
        candidate.actions.push({
          label: candidate.label, selector: candidate.selector,
          consequence: candidate.consequence || candidate.label, is_destructive: candidate.is_destructive,
        });
      }
    }
    return results;
  }

  function extractTableData(selector) {
    const el = selector ? document.querySelector(selector) : null;
    if (!el) return null;
    const text = (node) => safeText(node, 120);
    const headers = Array.from(el.querySelectorAll("thead th, thead [role='columnheader'], tr:first-child th")).map((th) => text(th));
    const rows = Array.from(el.querySelectorAll("tbody tr,[role='rowgroup'] [role='row']")).map((tr) =>
      Array.from(tr.querySelectorAll("td,[role='cell'],[role='gridcell']")).map((td) => text(td))
    );
    return { headers, rows };
  }

  function clearOverlays(source) {
    stopTrackingPins();
    state.scopes = [];
    state.selectedScopeId = null;
    activeSnapshot = null;
    snapshots.clear();
    clearActionConfirmation();
    state.lensActive = false;
    state.lensCandidates = [];
    setTargetLocked(false);
    dismissNote();
  }

  function renderSemanticLens(candidates, promptMessage, resolutionId) {
    renderPins(candidates);
    state.lensActive = true;
    state.lensCandidates = candidates || [];
    state.resolutionId = resolutionId || 0;
    openView("lens", {targets: []});
  }
  function selectLensCandidate(idx, modality) {
    if (!state.lensActive || state.choosePending) return;
    if (idx < 0 || idx >= state.lensCandidates.length) return;
    if (emitChoose(idx, modality)) {
      state.choosePending = true; // Python re-renders; cleared by the choose reply
    }
  }

  // ---------- pointer & scroll motion ----------
  let scrollEnd = 0;
  function onMotionScroll() {
    S.scrollingAt = performance.now();
    wake();
    clearTimeout(scrollEnd);
    scrollEnd = setTimeout(() => {
      // Settled: if the page moved what you asked about under the card, step aside.
      const item = viewItem();
      if (S.view && item && !S.hold) {
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
  }
  window.addEventListener("scroll", onMotionScroll, {capture: true, passive: true});
  function onViewportResize() {
    uiFrame.style.height = `${Math.max(900, innerHeight)}px`;
    if (S.view) {
      const item = viewItem();
      const spot = place(item, S.sizes.cardH || 200);
      S.pos = {x: spot.x, y: spot.y};
      S.maxBody = maxBodyFor(item);
      pushCard();
      layout();
    }
  }
  window.addEventListener("resize", onViewportResize);
  const onVisualViewport = () => {
    if (!S.view) return;
    S.maxBody = maxBodyFor(viewItem());
    pushCard();
    layout();
  };
  window.visualViewport?.addEventListener("resize", onVisualViewport);
  window.visualViewport?.addEventListener("scroll", onVisualViewport);

  // ---------- frame loop: only while something is alive ----------
  let raf = 0, last = 0, lastPoint = 0, ticking = false;
  function wake() { if (!raf && !ticking && !destroyed) { last = performance.now(); raf = requestAnimationFrame(frameTick); } }
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
    if (destroyed) return;
    ticking = true; // anything woken mid-tick is picked up by the reschedule at the end
    const dt = Math.min(.05, Math.max(.001, (now - last) / 1000));
    last = now;
    for (const sp of [...springs]) sp.step(dt);
    for (const f of [...fades]) f.step(dt);
    // Pointing while held
    if (S.hold) {
      if (now - lastPoint > 30) { lastPoint = now; updatePointing(now); }
      if (S.pillMode === "wave") {
        const a = pillAnchor();
        const lag = S.hold.follow && !pointedElsewhere() ? SPRING : FOLLOW;
        P.pill.x.k = lag.k; P.pill.x.c = lag.c; P.pill.y.k = lag.k; P.pill.y.c = lag.c;
        P.pill.x.to(a.x); P.pill.y.to(a.y);
        P.pill.w.to(S.pillW || 96);
      }
    } else {
      P.pill.x.k = SPRING.k; P.pill.x.c = SPRING.c; P.pill.y.k = SPRING.k; P.pill.y.c = SPRING.c;
    }
    // Plates
    apply(prev, plates[0], 15);
    apply(next2, plates[1], 12);
    apply(next, plates[2], 15);
    const morph = S.morphR != null ? S.morphR : 18;
    const rad = Math.min(front.h.x / 2, 18 + (morph - 18) * Math.max(0, Math.abs(front.w.x - front.w.t) / 200));
    apply(front, plates[3], Math.max(rad, 14));
    plates.forEach(p => { p.style.visibility = parseFloat(p.style.opacity) < .004 ? "hidden" : "visible"; });
    if (lift.x !== 0 || lift.v !== 0 || lift.t !== 0) {
      const off = lift.x * .06;
      for (const p of plates) p.style.translate = `0 ${off}px`;
      cardWrap.style.translate = `0 ${off}px`;
    } else {
      for (const p of plates) p.style.translate = "";
      cardWrap.style.translate = "";
    }
    // Words fade in just after the glass has shape.
    const wrapOn = !!S.view && front.h.x > 40;
    S.cardFade = wrapOn ? Math.min(1, (S.cardFade || 0) + dt / (reduced() ? .14 : .1)) : Math.max(0, (S.cardFade || 0) - dt / .09);
    const w = cardWrap.style;
    w.transform = `translate3d(${front.x.x}px,${(S.frameY ?? front.y.x) + (front.y.x - front.y.t)}px,0)`;
    w.width = `${cardWidth()}px`;
    uiFrame.style.width = w.width;
    w.height = `${S.frameH || 0}px`;
    w.opacity = S.cardFade.toFixed(3);
    w.pointerEvents = S.view && !S.hold ? "auto" : "none";
    w.visibility = S.cardFade < .004 ? "hidden" : "visible";
    // Pill
    const pv = P.pill;
    apply(pv, pillEl, Math.min(pv.h.x / 2, 20));
    pillEl.style.visibility = pv.o.x < .004 ? "hidden" : "visible";
    const pw = pillWrap.style;
    pw.transform = `translate3d(0,${(pv.h.x - PILL_H) / 2}px,0)`;
    pw.width = `${Math.max(0, pv.w.x)}px`;
    pw.height = `${PILL_H}px`;
    drawRings(0);
    const alive = springs.size || fades.size || S.hold || lit.size > 0 || (S.cardFade > 0 && S.cardFade < 1);
    ticking = false;
    if (alive) raf = requestAnimationFrame(frameTick);
  }

  function destroy() {
    destroyed = true;
    dialogWatch.disconnect();
    document.removeEventListener("toggle", onTopLayer, true);
    document.removeEventListener("fullscreenchange", onTopLayer, true);
    clearInterval(transportTimer);
    clearTimeout(S.retreatTimer); clearTimeout(S.coachTimer); clearTimeout(S.armTimer); clearTimeout(S.micTimer);
    if (raf) cancelAnimationFrame(raf);
    window.removeEventListener("resize", onViewportResize);
    window.visualViewport?.removeEventListener("resize", onVisualViewport);
    window.visualViewport?.removeEventListener("scroll", onVisualViewport);
    window.removeEventListener("scroll", onMotionScroll, true);
    stopTrackingPins();
    activeSnapshot = null;
    snapshots.clear();
    clearActionConfirmation();
    window.removeEventListener("pagehide", onNavigation);
    window.removeEventListener("scroll", onCursorScroll, true);
    cancelListening();
    window.removeEventListener("mousemove", onWindowMouseMove, { passive: true, capture: true });
    window.removeEventListener("pointerdown", onWindowPointerDown, true);
    window.removeEventListener("keydown", onWindowKey, { capture: true });
    window.removeEventListener("keyup", onWindowKey, { capture: true });
    window.removeEventListener("blur", onWindowBlur);
    document.removeEventListener("visibilitychange", onWindowBlur);
    if (host && host.parentNode) {
      host.remove();
    }
  }

  updateLiveInspector(state.pointerX, state.pointerY);

  const api = {
    state,
    uiFrame,
    uiFrames,
    transportAlive() { transportUntil = performance.now() + 4000; },
    uiReady() {
      transportUntil = performance.now() + 4000;
      S.ready = true;
      setTone(false);
      S.pillLast = "";
      if (S.view) pushCard();
    },
    fromPanel,
    // Observable surface for tests; carries no private strings beyond this world.
    debug() {
      const item = S.view === "answer" ? current() : null;
      return {view: S.view, cur: item?.subject || null, pos: S.pos,
        card: {x: front.x.t, y: front.y.t, w: front.w.t, h: front.h.t},
        frame: {y: S.frameY, h: S.frameH},
        targets: (item?.targets || []).map(targetRect).filter(Boolean).map(r => ({left: r.left, top: r.top, right: r.right, bottom: r.bottom})),
        sizes: S.sizes, maxBody: S.maxBody, dark: S.dark, lit: lit.size,
        hold: S.hold ? {targets: S.hold.targets.length, follow: S.hold.follow?.subject || null} : null,
        pill: {mode: S.pillMode, x: P.pill.x.t, y: P.pill.y.t, w: P.pill.w.t, h: P.pill.h.t, o: P.pill.o.t},
        items: S.items.map(i => ({subject: i.subject, archived: i.archived, presented: i.presented, status: i.turns.map(t => t.status)})),
        retreatInMs: S.retreatAt ? Math.round(S.retreatAt - performance.now()) : null,
        errors: (inbox?.items || []).flatMap(i => i.conversation.map(r => r.error).filter(Boolean)),
        talk: {micReady: S.micReady, spaceHeld, armed: S.keyArmed, listening: isListening, focused: document.hasFocus(), nonce: !!_intentNonce, ready: S.ready}};
    },
    Configure(opts) {
      if (opts?.mode && opts.mode !== state.mode) {
        if (S.hold) holdEnd(true, "Recording cancelled: pointing mode changed.");
        state.ringBuffer = []; lastWebcamAt = 0; S.softPoint = null; webcamAskedAt = null;
        if (state.mode === "webcam" || opts.mode === "webcam") {
          state.pointerX = state.pointerY = null; state.armed = false;
          state.lockedX = state.lockedY = null; lockedNode = null;
          cursorHistory.length = 0; webcamAnchor = null;
        }
      }
      Object.assign(state, opts || {});
      updateLiveInspector(state.pointerX, state.pointerY);
    },
    setIntentNonce(n) {
      _intentNonce = String(n || "");
    },
    destroy,
    startListening,
    armInteraction,
    extractCandidatesNear,
    captureCursorContext,
    captureActionContext,
    actionStructure,
    actionWrite,
    actionKeyTarget,
    actionPress,
    actionScroll,
    activateSnapshot,
    inspectSnapshot,
    highlightSnapshot,
    clickSnapshot,
    requestActionConfirmation,
    clearActionConfirmation,
    onSessionEvent,
    recordPoint,
    webcamViewport,
    acceptWebcamSample,
    captureNoisyContext,
    extractTableData,
    renderScopeContext(info) {
      _pendingUtterance = info.utterance || "";
      renderScopeOptions(info);
    },
    renderPins,
    renderSemanticLens,
    // A noisy pointing source (eye tracking next) feeds its estimate here while talking.
    pointSoft(x, y) { S.softPoint = {x: +x, y: +y, at: performance.now()}; if (S.hold) wake(); },
    clearOverlays,
    onIntentResult,
    revokeActionAuthority,
    showHudMessage(text) {
      showPlainMessage(text);
    },
  };

  window.__HERMES_GAZE_OVERLAY__ = api;
  return api;
})();
