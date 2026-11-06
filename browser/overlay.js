(function () {
  // Main frame only — addScriptToEvaluateOnNewDocument runs in EVERY frame; untrusted
  // iframes must not render a second HUD or reach the intent binding.
  if (window.top !== window.self) return;

  // Always tear down any prior overlay instance cleanly (removing window listeners & streams)
  const prevApi = window.__HERMES_GAZE_OVERLAY__;
  const prevState = prevApi && prevApi.state ? prevApi.state : null;
  const prevInputVal = prevApi && typeof prevApi.getInputValue === "function" ? prevApi.getInputValue() : "";
  let prevReplyText = "";
  let prevReplyDisplay = "none";
  const existingRoot = document.getElementById("hermes-gaze-root");
  if (existingRoot && existingRoot.shadowRoot) {
    const rEl = existingRoot.shadowRoot.querySelector("#hg-reply");
    if (rEl && rEl.textContent && rEl.style.display !== "none") {
      prevReplyText = rEl.textContent;
      prevReplyDisplay = rEl.style.display;
    }
  }
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
    wiggleTrigger: prevState && prevState.wiggleTrigger !== undefined ? prevState.wiggleTrigger : true,
    candidateRadiusPx: (prevState && prevState.candidateRadiusPx) || 380,
    hotkey: (prevState && prevState.hotkey) || "Backquote",
    resolutionId: 0,
    scopes: [],
    selectedScopeId: null,
    scopePending: false,
    tucked: false,
    armed: false, // When true, lockedX / lockedY stay frozen while user interacts with HUD
    armedAt: 0,
    // null until the first real mousemove — a fabricated center point is never a valid pointer
    pointerX: prevState && typeof prevState.pointerX === "number" ? prevState.pointerX : null,
    pointerY: prevState && typeof prevState.pointerY === "number" ? prevState.pointerY : null,
    choosePending: false,
    recordStartEpoch: 0, // Date.now()/1000 when the current mic recording began (word timestamps are audio-relative)
    lockedX: null,
    lockedY: null,
    ringBuffer: prevState && Array.isArray(prevState.ringBuffer) ? prevState.ringBuffer.slice(-250) : [], // {x_vp, y_vp, x_doc, y_doc, t, sigma}
    wiggleHistory: [],
    lensActive: false,
    lensCandidates: [],
    hoveredCandidate: null,
  };

  // Host element with Closed Shadow DOM so page styles never leak in or out
  const host = document.createElement("div");
  host.id = "hermes-gaze-root";
  host.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483647;";
  document.documentElement.appendChild(host);
  const shadow = host.attachShadow({ mode: "open" });


  const style = document.createElement("style");
  style.textContent = `
    :host {
      color-scheme: dark;
      --surface: #202623;
      --inset: #151917;
      --ink: #eef4ef;
      --muted: #a0b1a7;
      --accent: #a9dfbd;
      --line: #3c4841;
    }
    * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    button, input { font: inherit; }
    button { cursor: pointer; }
    button:focus-visible, input:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 3px;
    }
    button:disabled { opacity: .5; cursor: wait; }
    .spotlight {
      position: fixed;
      border-radius: 50%;
      pointer-events: none;
      transform: translate(-50%, -50%);
      border: 1px solid #76b89199;
      background: #76b8910c;
      transition: width .14s ease, height .14s ease;
    }
    .spotlight.armed { border: 2px solid var(--accent); background: #a9dfbd18; }
    .spotlight-tag {
      position: absolute;
      bottom: -25px;
      left: 50%;
      transform: translateX(-50%);
      background: var(--inset);
      color: var(--accent);
      border: 1px solid var(--line);
      font-size: 10px;
      padding: 3px 8px;
      border-radius: 6px;
      white-space: nowrap;
    }
    .pin-box {
      position: fixed;
      pointer-events: none;
      border: 2px solid #76b891;
      border-radius: 6px;
      background: #76b89112;
    }
    .pin-badge {
      position: absolute;
      top: -23px;
      left: 0;
      background: var(--inset);
      color: var(--accent);
      font-size: 11px;
      font-weight: 600;
      padding: 3px 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      white-space: nowrap;
    }
    .lens-layer { position: fixed; inset: 0; pointer-events: none; }
    .lens-card {
      position: fixed;
      width: min(268px, calc(100vw - 32px));
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px;
      color: var(--ink);
      pointer-events: auto;
      cursor: pointer;
      box-shadow: 0 12px 40px #0004;
      transform: translateY(4px);
      opacity: 0;
      transition: transform .15s ease, opacity .15s ease;
    }
    .lens-card.open { transform: translateY(0); opacity: 1; }
    .lens-card.primary, .lens-card:hover { border-color: var(--accent); }
    .lens-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .lens-key { background: var(--accent); color: var(--inset); padding: 3px 8px; border-radius: 5px; font-size: 11px; }
    .lens-prob { font-size: 11px; color: var(--muted); }
    .lens-title { font-size: 14px; font-weight: 600; margin: 0 0 6px; overflow-wrap: anywhere; }
    .lens-desc { font-size: 12px; color: var(--muted); line-height: 1.6; overflow-wrap: anywhere; }
    .lens-card .ctrl-btn { margin: 8px 6px 0 0; }
    .lens-card[role="dialog"] { border-color: #c7a66d; }
    .lens-card[role="dialog"] button:first-of-type { background: #dfc18e; color: #241d12; }
    .dwell-bar { height: 3px; background: var(--accent); width: 0%; margin-top: 12px; border-radius: 3px; }

    /* Quiet Signal: one compact surface, with target and answer kept distinct. */
    .hud-shell {
      position: fixed;
      right: 24px;
      bottom: 24px;
      width: 420px;
      max-width: calc(100vw - 32px);
      max-height: calc(100dvh - 32px);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 16px;
      color: var(--ink);
      box-shadow: 0 16px 56px #0004, 0 2px 8px #0002;
      pointer-events: auto;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      user-select: none;
      font-size: 12px;
      line-height: 1.5;
    }
    .hud-shell.tucked { width: auto; }
    .hud-dragbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
      cursor: grab;
      gap: 12px;
      flex-shrink: 0;
    }
    .hud-dragbar:active { cursor: grabbing; }
    .hud-shell.tucked .hud-dragbar { border-bottom: none; }
    .plugin-identity { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 13px; font-weight: 600; white-space: nowrap; }
    .drag-grip { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }
    .plugin-pill { display: none; }
    .tucked .plugin-pill { display: block; max-width: 90px; overflow: hidden; text-overflow: ellipsis; font-size: 10px; font-weight: 400; color: var(--muted); }
    .tucked #hg-mode-btn, .tucked #hg-clear-btn { display: none; }
    .hud-controls { display: flex; align-items: center; gap: 4px; }
    .ctrl-btn {
      background: transparent;
      color: var(--muted);
      border: 1px solid transparent;
      border-radius: 6px;
      min-height: 30px;
      padding: 4px 7px;
      font-size: 11px;
      white-space: nowrap;
    }
    .ctrl-btn:hover, .chip:hover { background: #a9dfbd12; color: var(--ink); }
    .ctrl-btn.active { color: var(--accent); border-color: var(--line); }
    .hud-body { padding: 16px; display: flex; flex-direction: column; gap: 14px; overflow-y: auto; min-height: 0; }
    .hud-shell.tucked .hud-body { display: none; }
    .target-bar { display: flex; align-items: center; gap: 12px; }
    .target-info { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
    .target-state-label { font-size: 10px; font-weight: 600; letter-spacing: .08em; color: var(--muted); overflow-wrap: anywhere; }
    .target-bar.locked .target-state-label { color: var(--accent); }
    .target-name { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .target-sub { font-size: 11px; color: var(--muted); overflow-wrap: anywhere; max-height: 48px; overflow-y: auto; }
    #hg-lock-btn { background: var(--inset); color: var(--ink); padding: 5px 10px; }
    .chips-row { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { background: transparent; color: var(--muted); border: 1px solid var(--line); border-radius: 6px; padding: 5px 9px; font-size: 11px; }
    .hud-input-row { display: flex; gap: 5px; align-items: center; background: var(--inset); border: 1px solid var(--line); border-radius: 10px; padding: 5px; }
    .hud-input-row:focus-within { border-color: var(--accent); }
    .hud-input { flex: 1; min-width: 0; width: 0; background: transparent; border: none; padding: 7px 5px; color: var(--ink); font-size: 12px; user-select: text; }
    .hud-input::placeholder { color: var(--muted); }
    .hud-input:focus-visible { outline-offset: 0; border-radius: 4px; }
    .hud-btn { background: var(--accent); color: var(--inset); border: 1px solid transparent; border-radius: 6px; padding: 7px 10px; font-size: 12px; font-weight: 600; white-space: nowrap; }
    .hud-btn:hover { filter: brightness(1.08); }
    #hg-mic-btn { background: var(--surface); color: var(--ink); }
    #hg-mic-btn.listening { background: #783c3c; color: #fff; border-color: #edaaaa; }
    .hud-reply { font-size: 13px; color: var(--ink); line-height: 1.65; border-top: 1px solid var(--line); padding-top: 14px; max-height: 230px; overflow-y: auto; overflow-wrap: anywhere; user-select: text; }
    #gaze-explanation-text { white-space: pre-wrap; overflow-wrap: anywhere; }
    .hud-help { font-size: 10px; color: var(--muted); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px 12px; }
    .hud-help strong { font-weight: 500; color: var(--ink); }
    @media (max-width: 480px) {
      .hud-shell { right: 16px; bottom: 16px; }
      .hud-dragbar { padding: 10px 12px; gap: 6px; }
      .hud-body { padding: 12px; }
      .plugin-identity { font-size: 12px; }
      .ctrl-btn { padding: 4px 5px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { transition: none !important; animation: none !important; }
    }
  `;
  shadow.appendChild(style);

  const spotlight = document.createElement("div");
  spotlight.className = "spotlight";
  const spotlightTag = document.createElement("div");
  spotlightTag.className = "spotlight-tag";
  spotlightTag.textContent = state.mode === "hover"
    ? `☤ Pointer σ=${state.hoverSigmaPx}px`
    : `☤ Gaze Cone σ=${state.sigmaPx}px`;
  spotlight.appendChild(spotlightTag);
  shadow.appendChild(spotlight);

  const pinsLayer = document.createElement("div");
  shadow.appendChild(pinsLayer);

  const svgLeaders = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svgLeaders.setAttribute("style", "position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;");
  shadow.appendChild(svgLeaders);

  const lensLayer = document.createElement("div");
  lensLayer.className = "lens-layer";
  shadow.appendChild(lensLayer);

  const hud = document.createElement("div");
  hud.className = "hud-shell";
  hud.innerHTML = `
    <div class="hud-dragbar" id="hg-dragbar" title="Drag to move the Hermes Gaze HUD anywhere">
      <div class="plugin-identity">
        <span class="drag-grip" aria-hidden="true"></span>
        <span>Hermes Gaze</span>
        <span class="plugin-pill" id="hg-tuck-summary">Ready</span>
      </div>
      <div class="hud-controls">
        <button class="ctrl-btn" id="hg-mode-btn" title="Switch between precise pointer and simulated noisy gaze">Pointer</button>
        <button class="ctrl-btn" id="hg-clear-btn" title="Clear highlights and reply (Esc)">Clear</button>
        <button class="ctrl-btn" id="hg-tuck-btn" aria-expanded="true" aria-controls="hg-body" title="Minimize or expand Hermes Gaze">Minimize</button>
      </div>
    </div>
    <div class="hud-body" id="hg-body">
      <div class="target-bar" id="hg-target-bar">
        <div class="target-info">
          <div class="target-state-label" id="hg-lock-label" role="status">Following cursor</div>
          <div class="target-name" id="hg-target-name">Point at something on the page</div>
          <div class="target-sub" id="hg-target-sub">Your page, in context</div>
        </div>
        <button class="ctrl-btn" id="hg-lock-btn" title="Freeze target so you can move your mouse to the HUD">Lock</button>
      </div>

      <div class="chips-row">
        <button class="chip" data-prompt="What does this do?">Explain this</button>
        <button class="chip" data-prompt="Summarize this">Summarize</button>
        <button class="chip" data-prompt="Compare these">Compare</button>
      </div>

      <div class="hud-input-row">
        <input class="hud-input" id="hg-input" aria-label="Ask Hermes about the page" placeholder="Ask about this…" />
        <button class="hud-btn" id="hg-mic-btn" title="Click to speak or hold Space">Speak</button>
        <button class="hud-btn" id="hg-send" title="Send question">Ask</button>
      </div>

      <div class="hud-reply" id="hg-reply" style="display:none;"></div>

      <div class="hud-help">
        <span id="hg-hotkey-tip">Hold <strong>Space</strong> to speak · <strong>${hotkeyLabel()}</strong> to lock</span>
        <span>Drag header to move</span>
      </div>
    </div>
  `;
  shadow.appendChild(hud);

  const dragbar = hud.querySelector("#hg-dragbar");
  const tuckSummary = hud.querySelector("#hg-tuck-summary");
  const modeBtn = hud.querySelector("#hg-mode-btn");
  const clearBtn = hud.querySelector("#hg-clear-btn");
  const tuckBtn = hud.querySelector("#hg-tuck-btn");
  const targetBar = hud.querySelector("#hg-target-bar");
  const lockLabel = hud.querySelector("#hg-lock-label");
  const targetName = hud.querySelector("#hg-target-name");
  const targetSub = hud.querySelector("#hg-target-sub");
  const lockBtn = hud.querySelector("#hg-lock-btn");
  const hudInput = hud.querySelector("#hg-input");
  const hudSend = hud.querySelector("#hg-send");
  const hudReply = hud.querySelector("#hg-reply");
  if (prevInputVal && hudInput) {
    hudInput.value = prevInputVal;
  }
  if (prevReplyText && prevReplyDisplay === "block") {
    hudReply.textContent = prevReplyText;
    hudReply.style.display = "block";
  }

  // --- Draggable HUD Positioning ---
  let isDragging = false;
  let dragOffsetX = 0;
  let dragOffsetY = 0;

  dragbar.addEventListener("mousedown", (e) => {
    if (e.target.closest("button")) return;
    isDragging = true;
    const rect = hud.getBoundingClientRect();
    dragOffsetX = e.clientX - rect.left;
    dragOffsetY = e.clientY - rect.top;
    hud.style.left = `${rect.left}px`;
    hud.style.top = `${rect.top}px`;
    hud.style.right = "auto";
    hud.style.bottom = "auto";
    e.preventDefault();
  });

  let cursorOverHud = false;
  function onWindowMouseMove(e) {
    if (isDragging) {
      const rect = hud.getBoundingClientRect();
      const maxX = window.innerWidth - rect.width - 8;
      const maxY = window.innerHeight - rect.height - 8;
      const nx = Math.max(8, Math.min(maxX, e.clientX - dragOffsetX));
      const ny = Math.max(8, Math.min(maxY, e.clientY - dragOffsetY));
      hud.style.left = `${nx}px`;
      hud.style.top = `${ny}px`;
      return;
    }

    // Ignore mouse movements inside our own HUD so moving to the HUD doesn't shift the pointer!
    const hudRect = hud.getBoundingClientRect();
    const insideHud = (
      e.clientX >= hudRect.left &&
      e.clientX <= hudRect.right &&
      e.clientY >= hudRect.top &&
      e.clientY <= hudRect.bottom
    );
    cursorOverHud = insideHud;
    if (!insideHud) {
      recordPoint(e.clientX, e.clientY);
    }
  }

  function onWindowMouseUp() {
    isDragging = false;
  }

  window.addEventListener("mousemove", onWindowMouseMove, { passive: true });
  window.addEventListener("mouseup", onWindowMouseUp);

  // --- Tuck / Expand Toggle ---
  tuckBtn.addEventListener("click", () => {
    state.tucked = !state.tucked;
    hud.classList.toggle("tucked", state.tucked);
    tuckBtn.textContent = state.tucked ? "Expand" : "Minimize";
    tuckBtn.setAttribute("aria-expanded", String(!state.tucked));
    if (state.tucked && state.hoveredCandidate) {
      tuckSummary.textContent = state.hoveredCandidate.label.slice(0, 18);
    } else {
      tuckSummary.textContent = "Ready";
    }
  });

  // --- Mode Switcher (Hover vs Simulated Noisy Gaze) ---
  function syncModeUI() {
    if (state.mode === "hover") {
      modeBtn.textContent = "Pointer";
      modeBtn.classList.remove("active");
    } else {
      modeBtn.textContent = "Simulated";
      modeBtn.classList.add("active");
    }
    const activeX = state.armed && state.lockedX !== null ? state.lockedX : state.pointerX;
    const activeY = state.armed && state.lockedY !== null ? state.lockedY : state.pointerY;
    updateSpotlightPosition(activeX, activeY);
  }

  modeBtn.addEventListener("click", () => {
    state.mode = state.mode === "hover" ? "simulated" : "hover";
    syncModeUI();
    _emit({ type: "configure", mode: state.mode });
  });

  clearBtn.addEventListener("click", () => {
    clearOverlays("clearBtn");
  });

  function hotkeyLabel() {
    return { Backquote: "`", AltRight: "Right Alt", AltLeft: "Left Alt", Space: "Space" }[state.hotkey] || state.hotkey;
  }

  function refreshHotkeyLabels() {
    if (!state.armed) {
      lockLabel.textContent = "Following cursor";
      lockBtn.textContent = "Lock";
    }
    const tip = hud.querySelector("#hg-hotkey-tip");
    if (tip) tip.innerHTML = `Hold <strong>Space</strong> to speak · <strong>${escapeHtml(hotkeyLabel())}</strong> to lock`;
  }

  // --- Target Lock / Unlock ---
  function setTargetLocked(locked, triggerSource = "manual") {
    if (locked && (typeof state.pointerX !== "number" || typeof state.pointerY !== "number")) {
      return; // no real pointer position yet — nothing to lock onto
    }
    state.armed = locked;
    if (locked) {
      state.armedAt = Date.now() / 1000;
      lockedNode = cursorRefs.get(cursorHistory[cursorHistory.length - 1]?.id) || null;
      state.lockedX = state.pointerX;
      state.lockedY = state.pointerY;
      spotlight.classList.add("armed");
      targetBar.classList.add("locked");
      lockLabel.textContent = "Target locked · move freely";
      lockBtn.textContent = "Unlock";
      lockBtn.classList.add("active");
    } else {
      state.lockedX = null;
      state.lockedY = null;
      spotlight.classList.remove("armed");
      targetBar.classList.remove("locked");
      lockLabel.textContent = "Following cursor";
      lockBtn.textContent = "Lock";
      lockBtn.classList.remove("active");
      if (!cursorOverHud && typeof state.pointerX === "number") rememberHit(hitNode(state.pointerX, state.pointerY));
    }
    const activeX = state.armed && state.lockedX !== null ? state.lockedX : state.pointerX;
    const activeY = state.armed && state.lockedY !== null ? state.lockedY : state.pointerY;
    updateSpotlightPosition(activeX, activeY);
  }

  lockBtn.addEventListener("click", () => {
    setTargetLocked(!state.armed, "button");
  });

  function updateSpotlightPosition(x, y) {
    if (typeof x !== "number" || typeof y !== "number") {
      spotlight.style.opacity = "0";
      spotlightTag.textContent = "";
      return;
    }
    spotlight.style.opacity = "1";
    const r = state.mode === "hover" ? 46 : Math.max(state.sigmaPx * 1.45, 110);
    spotlight.style.width = `${r}px`;
    spotlight.style.height = `${r}px`;
    spotlight.style.left = `${x}px`;
    spotlight.style.top = `${y}px`;
    const sigmaLabel = state.mode === "hover" ? state.hoverSigmaPx : state.sigmaPx;
    spotlightTag.textContent = state.armed
      ? "Target locked"
      : state.mode === "hover" ? "Pointer" : `Simulated · σ=${sigmaLabel}px`;
  }

  // Identities stay in this closure: a selector is metadata, never a historical lookup.
  const cursorIds = new WeakMap();
  const cursorRefs = new Map();
  const cursorHistory = [];
  let cursorSerial = 0;
  let lockedNode = null;
  const speechCaptures = new Map();
  const snapshots = new Map();
  const snapshotInstance = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  let snapshotSerial = 0;
  let activeSnapshot = null;
  let destroyed = false;
  let confirmation = null;
  let sessionSequence = -1;
  let sessionRequest = null;
  let sessionFinished = false;
  let sessionResolution = 0;
  const fingerprints = new WeakMap();
  let fingerprintSerial = 0;
  function actionFacts(el) {
    const tag = el.tagName.toLowerCase();
    const type = String(el.type || el.getAttribute("type") || "").toLowerCase();
    const role = el.getAttribute("role") || "";
    return { tag, type, role, label: safeLabel(el), class_name: String(el.className || "").slice(0, 300),
      form_submit: !!el.closest("form") && (tag === "button" && (!type || type === "submit") ||
        tag === "input" && (type === "submit" || type === "image")),
      disabled: !!el.disabled || el.matches(":disabled") || el.getAttribute("aria-disabled") === "true" || !!el.closest("[inert]"),
      clickable: tag === "button" || tag === "a" && !!el.getAttribute("href") ||
        tag === "input" && ["button", "submit", "reset", "checkbox", "radio", "image"].includes(type) ||
        role === "button" || role === "link" };
  }
  function fingerprint(el) {
    const descriptor = JSON.stringify([cursorId(el), actionFacts(el), el.getAttribute("href"),
      el.getAttribute("formaction"), el.closest("form") ? cursorId(el.closest("form")) : null,
      el.closest("form")?.getAttribute("action"), el.closest("form")?.getAttribute("method"),
      el.getAttribute("id"), el.getAttribute("name"), el.getAttribute("onclick"), el.getAttribute("target")]);
    const previous = fingerprints.get(el);
    if (previous?.descriptor === descriptor) return previous.token;
    const token = `${snapshotInstance}:fingerprint:${++fingerprintSerial}`;
    fingerprints.set(el, { descriptor, token });
    return token;
  }
  const sensitiveSelector = 'input[type="password"],[autocomplete^="cc-"],[autocomplete="current-password"],[autocomplete="new-password"],[name*="card" i],[name*="payment" i],[name*="cvv" i],[name*="cvc" i],[name^="cc-" i],[id*="card" i],[id*="payment" i],[id*="cvv" i],[id*="cvc" i],[id^="cc-" i]';
  function sensitive(el) {
    const field = el && el.closest("input,textarea,select,[contenteditable]");
    if (!field) return false;
    const tokens = (field.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/);
    return field.matches(sensitiveSelector) ||
      tokens.some(token => token.startsWith("cc-") || token === "current-password" || token === "new-password");
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
    if (el.matches("input,textarea,select,[contenteditable]")) return "";
    if (el.matches("label") && el.htmlFor && sensitive(document.getElementById(el.htmlFor))) return "[redacted]";
    if (!rendered(el) && getComputedStyle(el).display !== "contents") return "";
    // Never read field values, labels/attributes, or ancestor innerText wholesale.
    const parts = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.nodeType === 1 && (excluded?.has(node) ||
            node.matches('input,textarea,select,[contenteditable],script,style,#hermes-gaze-root') || sensitive(node) ||
            !rendered(node) && getComputedStyle(node).display !== "contents"))
          return NodeFilter.FILTER_REJECT;
        if (node.nodeType === 1 && node.matches("label") && node.htmlFor &&
            sensitive(document.getElementById(node.htmlFor))) return NodeFilter.FILTER_REJECT;
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
    if (sensitive(el) || (el.matches("label") && el.htmlFor && sensitive(document.getElementById(el.htmlFor))))
      return "[redacted]";
    return (el.getAttribute("aria-label") || el.getAttribute("title") || safeText(el, max, excluded)).slice(0, max);
  }
  function cursorId(el) {
    if (!cursorIds.has(el)) cursorIds.set(el, `@${++cursorSerial}`);
    return cursorIds.get(el);
  }
  function hitNode(x, y) {
    if (typeof x !== "number" || typeof y !== "number") return null;
    const el = document.elementFromPoint(x, y);
    return el && !el.closest("#hermes-gaze-root") ? el : null;
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
    for (const key of cursorRefs.keys()) if (!keep.has(key)) cursorRefs.delete(key);
  }
  function cursorMetadata(el) {
    const r = el.getBoundingClientRect();
    const hidden = sensitive(el);
    const visible = el.isConnected && rendered(el);
    return { id: cursorId(el), available: visible && !hidden,
      ...(hidden ? { sensitive: true, reason: "sensitive target redacted" } :
        !visible ? { reason: "target not rendered" } : {}),
      tag: el.tagName.toLowerCase(), role: (el.getAttribute("role") || el.tagName.toLowerCase()).slice(0, 40),
      label: hidden ? "[redacted]" : visible ? safeLabel(el, 100) : "",
      selector: hidden ? "" : buildSelector(el).slice(0, 350),
      rect_vp: [r.left, r.top, r.width, r.height],
      rect_doc: [r.left + scrollX, r.top + scrollY, r.width, r.height], block_ids: [] };
  }
  function captureCursorContext() {
    clearActionConfirmation();
    const snapshotId = `${snapshotInstance}:${++snapshotSerial}`;
    const identities = new Map();
    identities.pageUrl = location.href;
    const capture = { version: 1, snapshot_id: snapshotId, captured_at: Date.now() / 1000, page_url: location.origin + location.pathname,
      page_title: String(document.title || "").slice(0, 160),
      history: cursorHistory.map(h => ({ ...h })), targets: [], blocks: [], controls: [], handles: {} };
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
                collection && ownHeading(node))) items.push(node);
          }
          if (items.length >= 2 && (items.includes(item) || scanned > 128 &&
              rendered(item) && (item.matches("article,li,[role=listitem],.card") || collection && ownHeading(item)))) {
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
            (item.matches("article,li,[role=listitem],.card") || collection && ownHeading(item)))) {
          if (!group.items.includes(item)) group.items.push(item);
          group.pointed.add(item);
          const peers = group.items.filter(node => !group.pointed.has(node));
          const kept = [...group.pointed, ...peers.filter(inView), ...peers.filter(node => !inView(node))]
            .slice(0, Math.max(16, group.pointed.size));
          group.block.members = kept.map(node => {
            if (!group.facts.has(node)) {
              const metadata = cursorMetadata(node);
              group.facts.set(node, { id: handle(node), role: metadata.role, label: ownHeading(node) || metadata.label,
                text: safeText(node, 300), rect_vp: metadata.rect_vp, in_view: inView(node) });
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
    const refs = [...new Set(capture.history.map(h => h.id).filter(Boolean).reverse())].slice(0, 64).reverse();
    const capturedTables = new Set(refs.map(id => cursorRefs.get(id))
      .filter(el => el?.isConnected && !sensitive(el)).map(el => el.closest("table,[role=grid]")).filter(Boolean));
    for (const id of refs.slice().reverse()) {
      const el = cursorRefs.get(id);
      if (!el || !el.isConnected) { capture.targets.push({ id, available: false, reason: "historical node detached" }); continue; }
      const target = cursorMetadata(el);
      capture.targets.push(target);
      if (!target.available) continue;
      handle(el);
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
        const indices = block._rows.length <= 12 ? block._rows.map((_, i) => i) : [ri];
        for (const i of indices) if (i >= 0 && block.rows.length < 64 && !block._seen.has(i)) {
          block._seen.add(i);
          const node = block._rows[i];
          block.rows.push({ id: handle(node), index: i + 1, cells: block._cells(node).map(c => safeText(c, 70)) });
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
          text: safeText(parent, 650, capturedTables), text_limit: 650 });
      }
    }
    capture.targets.reverse();
    capture.blocks = [...blocks.values()].map(({ _rows, _cells, _allCells, _header, _seen, _rowIndex, ...block }) => block);
    // One bounded page-control pass per capture, never once per cell/mousemove.
    const controls = document.querySelectorAll('button,a,input,select,[role=button]');
    for (let i = 0; i < controls.length && i < 120 && capture.controls.length < 12; i++) {
      const el = controls[i];
      if (el.closest("#hermes-gaze-root") || sensitive(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width && r.height) { handle(el); capture.controls.push(cursorMetadata(el)); }
    }
    capture.omitted_controls = Math.max(0, controls.length - capture.controls.length);
    snapshots.set(snapshotId, identities);
    while (snapshots.size > 32) {
      const oldest = snapshots.keys().next().value;
      snapshots.delete(oldest);
      if (activeSnapshot?.id === oldest) activeSnapshot = null;
    }
    return capture;
  }
  let latestResolution = 0;
  function activateSnapshot(snapshotId, resolutionId) {
    if (destroyed || !Number.isSafeInteger(resolutionId) || resolutionId <= 0 ||
        resolutionId < latestResolution) return { ok: false, error: "Stale resolution" };
    if (!snapshots.has(snapshotId) || snapshots.get(snapshotId).pageUrl !== location.href)
      return { ok: false, error: "Snapshot expired" };
    clearActionConfirmation();
    latestResolution = resolutionId;
    activeSnapshot = { id: snapshotId, resolutionId, pageUrl: location.href };
    state.resolutionId = resolutionId;
    return { ok: true };
  }
  function snapshotEntry(snapshotId, resolutionId, handle) {
    if (destroyed || !activeSnapshot || activeSnapshot.id !== snapshotId ||
        activeSnapshot.resolutionId !== resolutionId || activeSnapshot.pageUrl !== location.href) return null;
    return snapshots.get(snapshotId)?.get(handle) || null;
  }
  function inspectSnapshot(snapshotId, resolutionId, handle) {
    const entry = snapshotEntry(snapshotId, resolutionId, handle);
    if (entry?.members) {
      if (!entry.table.isConnected || entry.members.some(node => !node.isConnected || sensitive(node) ||
          node.closest("table,[role=grid]") !== entry.table))
        return { ok: false, error: "Snapshot target unavailable" };
      return { ok: true, handle, kind: "column", label: entry.label, tag: "", role: "column",
        type: "", form_submit: false, class_name: "", disabled: false, clickable: false,
        fingerprint: `${snapshotId}:${handle}` };
    }
    if (!entry || !entry.node || !entry.node.isConnected || sensitive(entry.node))
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
      const nodes = entry?.members || (entry?.node ? [entry.node] : []);
      if (!nodes.length || entry?.table && !entry.table.isConnected ||
          nodes.some(node => !node.isConnected || sensitive(node) ||
            entry.table && node.closest("table,[role=grid]") !== entry.table))
        return { ok: false, error: "Snapshot target unavailable" };
      for (const node of nodes) {
        const r = node.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) candidates.push({
          label: snapshots.get(snapshotId) && (entry.kind === "column" ? "Column" : safeLabel(node)),
          rect_vp: [r.left, r.top, r.width, r.height] });
      }
    }
    if (!candidates.length) return { ok: false, error: "No visible target geometry" };
    renderPins(candidates);
    if (hudMessage) showPlainMessage(hudMessage);
    return { ok: true };
  }
  function clickSnapshot(snapshotId, resolutionId, handle, expectedFingerprint) {
    const descriptor = inspectSnapshot(snapshotId, resolutionId, handle);
    if (!descriptor.ok) return { ...descriptor, executed: false };
    if (!expectedFingerprint || expectedFingerprint !== descriptor.fingerprint ||
        descriptor.disabled || !descriptor.clickable)
      return { ok: false, executed: false, error: "Control changed or is not enabled/clickable" };
    const entry = snapshotEntry(snapshotId, resolutionId, handle);
    entry.node.click();
    return { ok: true, executed: true };
  }
  function clearActionConfirmation() {
    if (confirmation) confirmation.card.remove();
    confirmation = null;
    return true;
  }
  function requestActionConfirmation(info) {
    clearActionConfirmation();
    if (destroyed || !activeSnapshot || info?.resolution_id !== activeSnapshot.resolutionId ||
        activeSnapshot.pageUrl !== location.href || typeof info.action_id !== "string" || !info.action_id)
      return { ok: false, error: "Stale confirmation" };
    const card = document.createElement("section");
    card.className = "lens-card open";
    card.style.cssText = "right:24px;top:80px;cursor:default;";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", "Confirm page action");
    const title = document.createElement("h2");
    title.className = "lens-title";
    title.textContent = String(info.label || "Confirm action");
    const description = document.createElement("p");
    description.className = "lens-desc";
    description.textContent = String(info.description || "Click Confirm to perform this page action.");
    card.appendChild(title);
    card.appendChild(description);
    const pending = { card, actionId: info.action_id, resolutionId: info.resolution_id };
    confirmation = pending;
    for (const approved of [true, false]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ctrl-btn";
      button.textContent = approved ? "Confirm action" : "Cancel";
      button.addEventListener("click", event => {
        if (!event.isTrusted || event.button !== 0 || event.detail < 1 ||
            event.pointerType && event.pointerType !== "mouse" ||
            confirmation !== pending || !activeSnapshot ||
            activeSnapshot.resolutionId !== pending.resolutionId || activeSnapshot.pageUrl !== location.href) return;
        event.stopPropagation();
        clearActionConfirmation();
        _emit({ type: "confirm_action", action_id: pending.actionId,
          resolution_id: pending.resolutionId, approved });
      });
      card.appendChild(button);
    }
    shadow.appendChild(card);
    return { ok: true };
  }
  function showPlainMessage(text) {
    hudReply.style.display = "block";
    hudReply.style.whiteSpace = "pre-wrap";
    hudReply.textContent = String(text);
  }
  function onSessionEvent(event) {
    if (destroyed || !event || !Number.isSafeInteger(event.sequence)) return;
    const resolution = Number.isSafeInteger(event.resolution_id) ? event.resolution_id : 0;
    const newTurn = resolution > sessionResolution;
    const ownsAnswer = event.sequence === sessionSequence && event.request_id === sessionRequest;
    if (resolution && (resolution < sessionResolution || (resolution < latestResolution && !ownsAnswer))) return;
    if (!newTurn && event.sequence < sessionSequence) return;
    // Turn-end may complete with partial text before the full final-response hook.
    if (!newTurn && event.sequence === sessionSequence &&
        (event.request_id !== sessionRequest || (sessionFinished && event.status !== "complete"))) return;
    if (!resolution && event.status === "queued" && sessionSequence >= 0 && !sessionFinished) return;
    if (newTurn || event.sequence > sessionSequence) {
      sessionResolution = resolution || sessionResolution;
      sessionSequence = event.sequence;
      sessionRequest = event.request_id;
      sessionFinished = false;
    }
    lockLabel.textContent = String(event.status || "thinking");
    tuckSummary.textContent = event.session_connected === false ? "SESSION DISCONNECTED" : "HERMES SESSION";
    if (event.text !== undefined) showPlainMessage(event.text);
    if (event.error) showPlainMessage(event.error);
    if (["complete", "error", "disconnected"].includes(event.status) || event.session_connected === false)
      sessionFinished = true;
  }
  function onNavigation() {
    activeSnapshot = null;
    snapshots.clear();
    clearActionConfirmation();
    sessionFinished = true;
    releaseAudioStream();
  }
  window.addEventListener("pagehide", onNavigation);
  window.addEventListener("popstate", onNavigation);
  window.addEventListener("hashchange", onNavigation);
  window.navigation?.addEventListener("navigate", onNavigation);
  function onCursorScroll() {
    if (!state.armed && !cursorOverHud && typeof state.pointerX === "number")
      rememberHit(hitNode(state.pointerX, state.pointerY));
  }
  window.addEventListener("scroll", onCursorScroll, { passive: true, capture: true });

  function updateLiveInspector(x, y) {
    if (typeof x !== "number" || typeof y !== "number") {
      state.hoveredCandidate = null;
      targetName.textContent = "Point at something on the page";
      targetSub.textContent = "Your page, in context";
      return;
    }
    const el = state.armed ? lockedNode : hitNode(x, y);
    const best = el ? cursorMetadata(el) : null;
    state.hoveredCandidate = best;
    if (best) {
      targetName.textContent = best.label || "Page element";
      targetSub.textContent = best.consequence || best.summary || formatRoleDisplayName(best.role || best.tag);
      if (state.tucked) {
        tuckSummary.textContent = best.label.slice(0, 18);
      }
    } else {
      targetName.textContent = "No target under the pointer";
      targetSub.textContent = "Point at text, a link or a control";
    }
  }

  function recordPoint(x, y) {
    const now = performance.now() / 1000;
    state.pointerX = x;
    state.pointerY = y;

    // If locked, keep the spotlight and ringBuffer anchored on the locked target!
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

    if (!state.armed) {
      updateSpotlightPosition(x, y);
      updateLiveInspector(x, y);
    }

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

  function armInteraction(triggerSource) {
    setTargetLocked(true, triggerSource);
    if (state.tucked) {
      state.tucked = false;
      hud.classList.remove("tucked");
      tuckBtn.textContent = "Minimize";
      tuckBtn.setAttribute("aria-expanded", "true");
      tuckSummary.textContent = "Ready";
    }
  }

  // --- Resolver Intent Channel (the Python session resolves, explains, transcribes & clicks) ---
  let _intentSeq = 0;
  let _lastSentResolveId = 0;
  let _lastTranscribeId = 0;
  let _pendingUtterance = "";
  let _pendingExplainFallback = "";
  let _pendingExplainRid = 0;
  // Session nonce set via setIntentNonce() after Python (re)injects us. Stays in closure —
  // page scripts can call the binding but cannot read this value, so they cannot forge intents.
  let _intentNonce = "";
  const _transcribeTimers = new Map();

  function _emit(intent) {
    intent.id = ++_intentSeq;
    intent.nonce = _intentNonce;
    if (typeof window.__hermesGazeIntent !== "function") {
      showPlainMessage("Resolver offline. Run /gaze in the Hermes session, then retry.");
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
  function emitResolve(utterance, words, captured) {
    const text = (utterance || "").trim();
    if (!text) return false;
    state.scopePending = false;
    state.scopes = [];
    const locked = state.armed && state.lockedX !== null && state.lockedY !== null;
    const px = locked ? state.lockedX : state.pointerX;
    const py = locked ? state.lockedY : state.pointerY;
    if (typeof px !== "number" || typeof py !== "number") {
      showPlainMessage("Aim the pointer at an element first, then speak or type.");
      return false;
    }
    const evidence = state.mode === "hover" ? captured || captureCursorContext() : null;
    if (evidence) {
      const current = evidence.targets.find(target => target.id === evidence.history.at(-1)?.id);
      if (current?.available) renderPins([current]);
    }
    const intent = {
      type: state.mode === "hover" ? "submit" : "resolve",
      utterance: text,
      page_url: location.href,
      pointer: { x_vp: px, y_vp: py, scroll_x: window.scrollX, scroll_y: window.scrollY },
      fixations: state.ringBuffer.slice(-25),
      ...(state.mode === "hover" ? { cursor_context: evidence } :
        { candidates: extractCandidatesNear(px, py, state.candidateRadiusPx || 380) }),
    };
    if (words) {
      intent.words = words;
    }
    if (!_emit(intent)) return false;
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
      execute: true,
    });
  }

  function emitTranscribe(audioBase64, mimeType, capture, audioEpoch) {
    const intent = {
      type: "transcribe",
      audio_base64: audioBase64,
      mime_type: mimeType || "audio/webm",
      sample_rate: 16000,
      // wall-clock recording start — Python shifts audio-relative whisper timestamps by this
      audio_epoch: audioEpoch,
    };
    if (!_emit(intent)) {
      resetMicUiIdle("⚠️ Resolver offline (session not connected).");
      return false;
    }
    const timerId = setTimeout(() => {
      _transcribeTimers.delete(intent.id);
      speechCaptures.delete(intent.id);
      resetMicUiIdle("❌ Transcription timed out — resolver did not respond.");
    }, 90000); // generous: first-run whisper model download can take tens of seconds
    _transcribeTimers.set(intent.id, timerId);
    _lastTranscribeId = intent.id;
    speechCaptures.set(intent.id, { capture, resolveId: _lastSentResolveId });
    return true;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));
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

    if (msg.type === "confirm_action") {
      if (msg.resolution_id !== state.resolutionId) return;
      const outcome = msg.outcome === "unknown" ? "unknown outcome" : !msg.ok ? "failed" :
        msg.cancelled ? "cancelled" : msg.executed ? "executed" : "not executed";
      lockLabel.textContent = outcome;
      showPlainMessage(msg.error || `Action ${outcome}.`);
      return;
    }

    if (msg.type === "transcribe") {
      const pendingTimer = _transcribeTimers.get(msg.id);
      const frozen = speechCaptures.get(msg.id);
      speechCaptures.delete(msg.id);
      if (pendingTimer) {
        clearTimeout(pendingTimer);
        _transcribeTimers.delete(msg.id);
      }
      if (!frozen || frozen.resolveId !== _lastSentResolveId || msg.id !== _lastTranscribeId || isListening) return;
      if (!isListening) {
        resetMicUiIdle();
      }
      if (msg.ok && msg.text && String(msg.text).trim()) {
        const spoken = String(msg.text).trim();
        hudInput.value = spoken;
        hudInput.dispatchEvent(new Event("input", { bubbles: true }));
        lockLabel.textContent = `🗣️ Heard: "${spoken}"${msg.backend ? ` (${msg.backend})` : ""}`;
        emitResolve(spoken, msg.words, frozen.capture);
      } else {
        lockLabel.textContent = msg.error
          ? `❌ ${msg.error}`
          : "⚠️ No speech detected in audio. Please speak clearly while holding Spacebar.";
      }
      return;
    }


    if (msg.type === "submit") {
      if (msg.id !== _lastSentResolveId) return;
      if (!msg.ok) {
        showPlainMessage(msg.error || "Connect Hermes with /gaze, then retry.");
      } else if (msg.delivery === "session") {
        if (sessionSequence < 0 || sessionFinished) lockLabel.textContent = "queued";
        tuckSummary.textContent = "HERMES SESSION";
      } else if (msg.delivery === "one_shot") {
        renderScopeOptions(msg);
        if (Array.isArray(msg.ranked)) renderPins(msg.ranked);
        showPlainMessage(`${msg.message || "Read-only one-shot fallback — no conversation or actions."}\n${msg.explanation || msg.text || msg.answer || ""}`);
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
        showPlainMessage(msg.error || "Resolver error.");
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
      if (msg.scope_id !== state.selectedScopeId) return;
      const expEl = shadow.querySelector("#gaze-explanation-text");
      // correlate the reply with the pin that asked for it (a newer pin wins the element)
      if (expEl && String(expEl.dataset.rid || "") === String(msg.resolution_id || "")) {
        if (msg.ok && msg.explanation) {
          expEl.textContent = msg.explanation;
        } else {
          const fallback = msg.error || _pendingExplainFallback || "Explanation unavailable.";
          expEl.textContent = fallback;
        }
      }
      return;
    }

    if (msg.type === "choose") {
      state.choosePending = false;
      if (msg.ok) {
        state.lensActive = false; // consumed — Python already re-rendered the pin
      } else {
        // keep the lens live so dwell/keys still work after a failed choose
        showPlainMessage(msg.error || "Selection failed.");
      }
      return;
    }

    // "configure" acks and unknown types are no-ops
  }

  function formatRoleDisplayName(role) {
    const r = (role || "").toLowerCase();
    switch (r) {
      case "columnheader":
      case "th":
        return "Column Header";
      case "cell":
      case "td":
        return "Table Cell";
      case "button":
        return "Button";
      case "link":
      case "a":
        return "Link";
      case "table":
        return "Table";
      case "section":
        return "Section";
      case "article":
      case "card":
        return "Card";
      case "textbox":
      case "input":
        return "Input Field";
      case "select":
        return "Dropdown";
      default:
        return r ? r.charAt(0).toUpperCase() + r.slice(1) : "Element";
    }
  }

  const DEFAULT_PLACEHOLDER = "Ask about this…";
  const hudMic = hud.querySelector("#hg-mic-btn");
  let isListening = false;
  let mediaRecorder = null;
  let activeMediaStream = null;
  let streamAcquirePromise = null;
  let audioChunks = [];
  let spaceHeld = false;
  let recordingStartedAt = 0;
  let stopDelayTimer = null;

  function hasLiveAudioStream(stream) {
    if (!stream || !stream.active) return false;
    const tracks = stream.getAudioTracks();
    return tracks.length > 0 && tracks.every((t) => t.readyState === "live" && t.enabled);
  }

  function releaseAudioStream() {
    if (activeMediaStream) {
      try {
        activeMediaStream.getTracks().forEach((t) => t.stop());
      } catch (_) {}
      activeMediaStream = null;
    }
    streamAcquirePromise = null;
  }

  async function ensureAudioStream() {
    if (hasLiveAudioStream(activeMediaStream)) {
      return activeMediaStream;
    }
    if (streamAcquirePromise) {
      return streamAcquirePromise;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("Browser does not support mediaDevices audio capture.");
    }
    streamAcquirePromise = Promise.race([
      navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      }),
      new Promise((_, reject) =>
        setTimeout(
          () => reject(new Error("Microphone access timed out (check macOS Microphone permission for Chrome)")),
          2500
        )
      ),
    ]);
    try {
      const stream = await streamAcquirePromise;
      activeMediaStream = stream;
      return stream;
    } finally {
      streamAcquirePromise = null;
    }
  }

  // Pre-warm microphone stream quietly so the first Spacebar press has 0ms startup delay
  setTimeout(() => {
    ensureAudioStream().catch(() => {});
  }, 150);

  function resetMicUiIdle(statusMessage) {
    hudMic.classList.remove("listening");
    hudMic.textContent = "Speak";
    hudInput.placeholder = DEFAULT_PLACEHOLDER;
    if (statusMessage) {
      lockLabel.textContent = statusMessage;
    }
  }

  async function startListening() {
    if (isListening) return;
    if (stopDelayTimer) {
      clearTimeout(stopDelayTimer);
      stopDelayTimer = null;
    }
    isListening = true;
    recordingStartedAt = 0;
    audioChunks = [];
    // Do not lock voice: two spoken referents may point to different real nodes.

    hudMic.classList.add("listening");
    hudMic.textContent = "Stop";
    hudInput.placeholder = "Listening…";
    lockLabel.textContent = "Recording · release Space or click Stop";
    targetBar.classList.add("locked");

    try {
      const stream = await ensureAudioStream();

      // If user released Spacebar while microphone stream was still opening
      if (!isListening) {
        resetMicUiIdle("⚠️ Hold Spacebar while speaking (released before mic was ready).");
        return;
      }

      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : (MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "");

      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      mediaRecorder = recorder;
      audioChunks = [];
      const audioEpoch = Date.now() / 1000;

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          audioChunks.push(e.data);
        }
      };

      recorder.onstop = () => {
        const frozenCapture = captureCursorContext();
        const chunks = audioChunks.slice();
        audioChunks = [];
        const recordedBlob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });

        if (recordedBlob.size < 200) {
          resetMicUiIdle("⚠️ Spoke too briefly. Hold Spacebar or click Speak, then talk.");
          return;
        }

        hudMic.classList.remove("listening");
        hudMic.textContent = "Wait";
        lockLabel.textContent = "Transcribing audio locally…";

        const reader = new FileReader();
        reader.onload = () => {
          const dataUrl = String(reader.result || "");
          const commaIdx = dataUrl.indexOf(",");
          const audioBase64 = commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : dataUrl;
          emitTranscribe(audioBase64, recorder.mimeType || "audio/webm", frozenCapture, audioEpoch);
        };
        reader.onerror = () => {
          resetMicUiIdle("❌ Could not encode recorded audio for transcription.");
        };
        reader.readAsDataURL(recordedBlob);
      };

      recorder.start(80);
      recordingStartedAt = performance.now();
      state.recordStartEpoch = Date.now() / 1000; // sent with audio so Python can shift whisper word times to wall-clock
    } catch (err) {
      isListening = false;
      releaseAudioStream();
      resetMicUiIdle(`⚠️ ${err && err.message ? err.message : "Microphone permission needed: Allow mic in Chrome."}`);
    }
  }

  function stopListening() {
    if (!isListening) return;
    isListening = false;
    hudMic.classList.remove("listening");

    if (mediaRecorder && mediaRecorder.state === "recording") {
      hudMic.textContent = "Wait";
      lockLabel.textContent = "Transcribing audio locally…";

      const elapsed = recordingStartedAt ? performance.now() - recordingStartedAt : 500;
      const tailMs = Math.max(150, Math.min(420, 520 - elapsed));
      const activeRecorder = mediaRecorder;

      if (stopDelayTimer) clearTimeout(stopDelayTimer);
      stopDelayTimer = setTimeout(() => {
        stopDelayTimer = null;
        if (activeRecorder && activeRecorder.state === "recording") {
          try {
            activeRecorder.requestData();
          } catch (_) {}
          try {
            activeRecorder.stop();
          } catch (err) {
            resetMicUiIdle(`⚠️ Recorder stop error: ${err.message || err}`);
          }
        }
      }, tailMs);
    } else {
      resetMicUiIdle("⚠️ Hold Spacebar while speaking.");
    }
  }

  hudMic.addEventListener("click", (e) => {
    e.currentTarget.blur();
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  });

  // --- Wire Chips & Input ---
  hud.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const prompt = chip.getAttribute("data-prompt") || "";
      hudInput.value = prompt;
      emitResolve(prompt);
    });
  });

  hudSend.addEventListener("click", () => {
    emitResolve(hudInput.value);
  });

  hudInput.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      emitResolve(hudInput.value);
    } else if (e.key === "Escape") {
      clearOverlays("inputEscape");
    }
  });

  function isEditableTarget(e) {
    const path = e.composedPath ? e.composedPath() : [e.target];
    for (const node of path) {
      if (!node || !node.tagName) continue;
      if (node === hudInput) return true;
      const tag = node.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select" || node.isContentEditable) {
        return true;
      }
    }
    return false;
  }

  function onWindowKeyDown(e) {
    if (isEditableTarget(e)) return;
    if (e.code === "Space" && !e.altKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      e.stopPropagation();
      if (!e.repeat && !spaceHeld) {
        spaceHeld = true;
        startListening();
      }
      return;
    }
    if (e.code === (state.hotkey || "Backquote")) {
      e.preventDefault();
      setTargetLocked(!state.armed, "hotkey");
    } else if (state.lensActive && /^Digit[1-9]$/.test(e.code)) {
      const idx = parseInt(e.code.replace("Digit", ""), 10) - 1;
      if (idx >= 0 && idx < state.lensCandidates.length) {
        e.preventDefault();
        selectLensCandidate(idx, "key");
      }
    } else if (e.key === "Escape") {
      clearOverlays("windowEscape");
    }
  }

  function onWindowKeyUp(e) {
    if (e.code === "Space" && spaceHeld) {
      e.preventDefault();
      e.stopPropagation();
      spaceHeld = false;
      stopListening();
    }
  }

  function onWindowBlur() {
    if (spaceHeld) {
      spaceHeld = false;
      stopListening();
    }
  }

  window.addEventListener("keydown", onWindowKeyDown, { capture: true });
  window.addEventListener("keyup", onWindowKeyUp, { capture: true });
  window.addEventListener("blur", onWindowBlur);
  window.addEventListener("pagehide", releaseAudioStream);

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
    pinsLayer.innerHTML = "";
    state.scopes = [];
    state.selectedScopeId = null;
    activeSnapshot = null;
    snapshots.clear();
    clearActionConfirmation();
    sessionFinished = true;
    svgLeaders.innerHTML = "";
    lensLayer.innerHTML = "";
    state.lensActive = false;
    state.lensCandidates = [];
    setTargetLocked(false);
    hudReply.style.display = "none";
  }

  function showHudMessage(htmlText) {
    if (state.tucked) {
      state.tucked = false;
      hud.classList.remove("tucked");
      tuckBtn.textContent = "Minimize";
      tuckBtn.setAttribute("aria-expanded", "true");
      tuckSummary.textContent = "Ready";
    }
    hudReply.style.display = "block";
    hudReply.innerHTML = htmlText;
  }

  function renderPins(candidates, messageHtml) {
    pinsLayer.innerHTML = "";
    svgLeaders.innerHTML = "";
    lensLayer.innerHTML = "";
    state.lensActive = false;

    (candidates || []).forEach((cand, idx) => {
      if (!Array.isArray(cand.rect_vp) || cand.rect_vp.length !== 4 || !cand.rect_vp.every(Number.isFinite)) return;
      const [x, y, w, h] = cand.rect_vp;
      const box = document.createElement("div");
      box.className = "pin-box";
      box.style.left = `${x - 4}px`;
      box.style.top = `${y - 4}px`;
      box.style.width = `${w + 8}px`;
      box.style.height = `${h + 8}px`;

      const badge = document.createElement("div");
      badge.className = "pin-badge";
      const probPct = cand.probability !== undefined ? ` · ${Math.round(cand.probability * 100)}%` : "";
      badge.textContent = `[${idx + 1}] ${cand.label.slice(0, 26)}${probPct}`;
      box.appendChild(badge);
      pinsLayer.appendChild(box);
    });

    if (messageHtml) {
      showHudMessage(messageHtml);
    }
  }

  function renderSemanticLens(candidates, promptMessage, resolutionId) {
    pinsLayer.innerHTML = "";
    svgLeaders.innerHTML = "";
    lensLayer.innerHTML = "";
    state.lensActive = true;
    state.lensCandidates = candidates || [];
    state.resolutionId = resolutionId || 0;

    if (promptMessage) {
      showPlainMessage(promptMessage);
    }

    const count = state.lensCandidates.length;
    if (!count) return;

    const anchorX = state.lensCandidates[0].rect_vp[0];
    const anchorY = state.lensCandidates[0].rect_vp[1] + state.lensCandidates[0].rect_vp[3] + 26;
    const startX = Math.max(20, Math.min(window.innerWidth - count * 282 - 20, anchorX - 80));
    const cardY = Math.min(window.innerHeight - 190, Math.max(76, anchorY));

    state.lensCandidates.forEach((cand, idx) => {
      const [rx, ry, rw, rh] = cand.rect_vp;
      const pin = document.createElement("div");
      pin.className = "pin-box";
      pin.style.left = `${rx - 2}px`;
      pin.style.top = `${ry - 2}px`;
      pin.style.width = `${rw + 4}px`;
      pin.style.height = `${rh + 4}px`;
      pinsLayer.appendChild(pin);

      const cardX = startX + idx * 280;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(rx + rw / 2));
      line.setAttribute("y1", String(ry + rh));
      line.setAttribute("x2", String(cardX + 134));
      line.setAttribute("y2", String(cardY));
      line.setAttribute("stroke", idx === 0 ? "#38bdf8" : "#6366f1");
      line.setAttribute("stroke-width", idx === 0 ? "2" : "1.5");
      line.setAttribute("stroke-dasharray", "4 4");
      svgLeaders.appendChild(line);

      const card = document.createElement("div");
      card.className = `lens-card ${idx === 0 ? "primary" : ""}`;
      card.style.left = `${cardX}px`;
      card.style.top = `${cardY}px`;
      const probPct = Math.round((cand.probability || 0) * 100);
      card.innerHTML = `
        <div class="lens-header">
          <span class="lens-key">[${idx + 1}] Select</span>
          <span class="lens-prob">P = ${probPct}%</span>
        </div>
        <div class="lens-title">${escapeHtml(cand.label || cand.selector)}</div>
        <div class="lens-desc">↳ ${escapeHtml(cand.consequence_preview || cand.consequence || "Execute action")}</div>
        <div class="lens-desc" style="margin-top:5px;font-size:10px;color:#64748b;">Dwell ${state.dwellMs}ms · Key ${idx + 1} · Click</div>
        <div class="dwell-bar" id="dwell-${idx}"></div>
      `;

      const dwellBar = card.querySelector(`#dwell-${idx}`);
      let dwellStart = 0;
      let rafId = null;

      function tickDwell() {
        const elapsed = performance.now() - dwellStart;
        const pct = Math.min(100, (elapsed / state.dwellMs) * 100);
        if (dwellBar) dwellBar.style.width = `${pct}%`;
        if (pct >= 100) {
          selectLensCandidate(idx, "dwell");
        } else {
          rafId = requestAnimationFrame(tickDwell);
        }
      }

      card.addEventListener("mouseenter", () => {
        dwellStart = performance.now();
        rafId = requestAnimationFrame(tickDwell);
      });
      card.addEventListener("mouseleave", () => {
        if (rafId) cancelAnimationFrame(rafId);
        if (dwellBar) dwellBar.style.width = "0%";
      });
      card.addEventListener("click", (e) => {
        e.stopPropagation();
        selectLensCandidate(idx, "click");
      });

      lensLayer.appendChild(card);
      requestAnimationFrame(() => card.classList.add("open"));
    });
  }

  function selectLensCandidate(idx, modality) {
    if (!state.lensActive || state.choosePending) return;
    if (idx < 0 || idx >= state.lensCandidates.length) return;
    if (emitChoose(idx, modality)) {
      state.choosePending = true; // Python re-renders; cleared by the choose reply
    }
  }

  function destroy() {
    destroyed = true;
    activeSnapshot = null;
    snapshots.clear();
    clearActionConfirmation();
    window.removeEventListener("pagehide", onNavigation);
    window.removeEventListener("popstate", onNavigation);
    window.removeEventListener("hashchange", onNavigation);
    window.navigation?.removeEventListener("navigate", onNavigation);
    window.removeEventListener("scroll", onCursorScroll, true);
    if (stopDelayTimer) {
      clearTimeout(stopDelayTimer);
      stopDelayTimer = null;
    }
    for (const timerId of _transcribeTimers.values()) {
      clearTimeout(timerId);
    }
    _transcribeTimers.clear();
    isListening = false;
    spaceHeld = false;
    if (mediaRecorder && mediaRecorder.state === "recording") {
      try {
        mediaRecorder.onstop = null;
        mediaRecorder.stop();
      } catch (_) {}
    }
    releaseAudioStream();
    window.removeEventListener("mousemove", onWindowMouseMove, { passive: true });
    window.removeEventListener("mouseup", onWindowMouseUp);
    window.removeEventListener("keydown", onWindowKeyDown, { capture: true });
    window.removeEventListener("keyup", onWindowKeyUp, { capture: true });
    window.removeEventListener("blur", onWindowBlur);
    window.removeEventListener("pagehide", releaseAudioStream);
    if (host && host.parentNode) {
      host.remove();
    }
  }

  // Initialize spotlight & live inspector immediately on load
  syncModeUI();
  updateLiveInspector(state.pointerX, state.pointerY);

  const api = {
    state,
    Configure(opts) {
      Object.assign(state, opts || {});
      syncModeUI();
      refreshHotkeyLabels();
      updateLiveInspector(state.pointerX, state.pointerY);
    },
    setIntentNonce(n) {
      _intentNonce = String(n || "");
    },
    getInputValue() {
      return hudInput ? hudInput.value : "";
    },
    destroy,
    startListening,
    stopListening,
    armInteraction,
    extractCandidatesNear,
    captureCursorContext,
    activateSnapshot,
    inspectSnapshot,
    highlightSnapshot,
    clickSnapshot,
    requestActionConfirmation,
    clearActionConfirmation,
    onSessionEvent,
    recordPoint,
    extractTableData,
    renderScopeContext(info) {
      _pendingUtterance = info.utterance || "";
      renderScopeOptions(info);
    },
    renderPins,
    renderSemanticLens,
    clearOverlays,
    onIntentResult,
    showHudMessage(htmlText) {
      showHudMessage(htmlText);
    },
  };

  window.__HERMES_GAZE_OVERLAY__ = api;
  return api;
})();

