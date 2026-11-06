(function () {
  // Main frame only — addScriptToEvaluateOnNewDocument runs in EVERY frame; untrusted
  // iframes must not render a second HUD or reach the intent binding.
  if (window.top !== window.self) return;

  // Always tear down any prior overlay instance cleanly (removing window listeners & streams)
  const prevApi = window.__HERMES_GAZE_OVERLAY__;
  const prevState = prevApi && prevApi.state ? prevApi.state : null;
  const prevInputVal = prevApi && typeof prevApi.getInputValue === "function" ? prevApi.getInputValue() : "";
  let prevReplyHtml = "";
  let prevReplyDisplay = "none";
  const existingRoot = document.getElementById("hermes-gaze-root");
  if (existingRoot && existingRoot.shadowRoot) {
    const rEl = existingRoot.shadowRoot.querySelector("#hg-reply");
    if (rEl && rEl.innerHTML && rEl.style.display !== "none") {
      prevReplyHtml = rEl.innerHTML;
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
    * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif; }

    /* Spotlight & Locked Reticle */
    .spotlight {
      position: fixed;
      border-radius: 50%;
      pointer-events: none;
      transform: translate(-50%, -50%);
      border: 2px dashed rgba(99, 102, 241, 0.65);
      background: radial-gradient(circle, rgba(99, 102, 241, 0.16) 0%, rgba(56, 189, 248, 0.05) 65%, transparent 100%);
      transition: width 0.14s ease, height 0.14s ease, border-color 0.14s ease, box-shadow 0.14s ease;
      opacity: 1;
    }
    .spotlight.armed {
      border: 2.5px solid #38bdf8;
      background: radial-gradient(circle, rgba(56, 189, 248, 0.24) 0%, rgba(99, 102, 241, 0.08) 65%, transparent 100%);
      box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.18), 0 0 28px rgba(56, 189, 248, 0.45);
    }
    .spotlight-tag {
      position: absolute;
      bottom: -24px;
      left: 50%;
      transform: translateX(-50%);
      background: #0f172a;
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.5);
      font-family: ui-monospace, SFMono-Regular, monospace;
      font-size: 10px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 999px;
      white-space: nowrap;
      box-shadow: 0 4px 10px rgba(0,0,0,0.35);
    }

    /* Pinned Element Highlight Box */
    .pin-box {
      position: fixed;
      pointer-events: none;
      border: 2.5px solid #6366f1;
      border-radius: 8px;
      background: rgba(99, 102, 241, 0.12);
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.28), 0 8px 24px rgba(15, 23, 42, 0.35);
      transition: all 0.16s cubic-bezier(0.22, 1, 0.36, 1);
    }
    .pin-badge {
      position: absolute;
      top: -12px;
      left: 8px;
      background: linear-gradient(135deg, #4f46e5, #0284c7);
      color: #ffffff;
      font-family: ui-monospace, SFMono-Regular, monospace;
      font-size: 11px;
      font-weight: 700;
      padding: 2px 9px;
      border-radius: 999px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      white-space: nowrap;
      border: 1px solid rgba(255,255,255,0.25);
    }

    /* Semantic Lens Disambiguation Cards */
    .lens-layer {
      position: fixed;
      inset: 0;
      pointer-events: none;
    }
    .lens-card {
      position: fixed;
      width: 268px;
      background: rgba(13, 16, 29, 0.96);
      backdrop-filter: blur(18px);
      border: 1.5px solid rgba(99, 102, 241, 0.55);
      border-radius: 12px;
      padding: 12px 14px;
      color: #f8fafc;
      pointer-events: auto;
      cursor: pointer;
      box-shadow: 0 16px 40px rgba(2, 6, 23, 0.65), 0 0 0 1px rgba(255,255,255,0.06);
      transform: scale(0.92);
      opacity: 0;
      transition: transform 0.18s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.15s ease, border-color 0.15s ease;
    }
    .lens-card.open {
      transform: scale(1);
      opacity: 1;
    }
    .lens-card.primary, .lens-card:hover {
      border-color: #38bdf8;
      box-shadow: 0 16px 40px rgba(56, 189, 248, 0.32);
    }
    .lens-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }
    .lens-key {
      background: linear-gradient(135deg, #38bdf8, #6366f1);
      color: #09090b;
      font-family: ui-monospace, monospace;
      font-size: 10.5px;
      font-weight: 800;
      padding: 2px 8px;
      border-radius: 6px;
    }
    .lens-prob {
      font-family: ui-monospace, monospace;
      font-size: 11px;
      color: #38bdf8;
      font-weight: 600;
    }
    .lens-title {
      font-size: 13.5px;
      font-weight: 700;
      margin-bottom: 4px;
      color: #ffffff;
    }
    .lens-desc {
      font-size: 11.5px;
      color: #cbd5e1;
      line-height: 1.38;
    }
    .dwell-bar {
      height: 3.5px;
      background: linear-gradient(90deg, #38bdf8, #818cf8);
      width: 0%;
      margin-top: 8px;
      border-radius: 3px;
      transition: width 0.05s linear;
    }

    /* Floating, Draggable, Tuckable Hermes Gaze Plugin HUD */
    .hud-shell {
      position: fixed;
      right: 24px;
      bottom: 24px;
      width: 488px;
      max-width: calc(100vw - 32px);
      background: rgba(13, 16, 28, 0.95);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1.5px solid rgba(99, 102, 241, 0.6);
      border-radius: 14px;
      color: #f8fafc;
      box-shadow: 0 22px 50px rgba(2, 6, 23, 0.65), 0 0 0 1px rgba(56, 189, 248, 0.22);
      pointer-events: auto;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      transition: width 0.2s cubic-bezier(0.22, 1, 0.36, 1), border-radius 0.2s ease, opacity 0.2s ease;
      user-select: none;
    }
    .hud-shell.tucked {
      width: auto;
      min-width: 260px;
      border-radius: 999px;
    }

    /* Distinct Plugin Top Accent Ribbon & Drag Bar */
    .hud-dragbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 9px 13px;
      background: linear-gradient(90deg, rgba(79, 70, 229, 0.38) 0%, rgba(14, 165, 233, 0.25) 100%);
      border-bottom: 1px solid rgba(99, 102, 241, 0.35);
      cursor: grab;
      gap: 8px;
      white-space: nowrap;
    }
    .hud-dragbar:active { cursor: grabbing; }
    .hud-shell.tucked .hud-dragbar {
      border-bottom: none;
      padding: 8px 14px;
    }

    .plugin-identity {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.02em;
      color: #e0e7ff;
      white-space: nowrap;
    }
    .drag-grip {
      color: #818cf8;
      font-size: 14px;
      line-height: 1;
    }
    .plugin-pill {
      font-family: ui-monospace, SFMono-Regular, monospace;
      font-size: 9.5px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 6px;
      border-radius: 4px;
      background: rgba(56, 189, 248, 0.2);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.4);
      white-space: nowrap;
    }

    .hud-controls {
      display: flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }
    .ctrl-btn {
      background: rgba(30, 41, 59, 0.85);
      color: #cbd5e1;
      border: 1px solid rgba(148, 163, 184, 0.3);
      border-radius: 6px;
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.12s;
    }
    .ctrl-btn:hover {
      background: rgba(51, 65, 85, 0.95);
      color: #ffffff;
      border-color: #38bdf8;
    }
    .ctrl-btn.active {
      background: rgba(56, 189, 248, 0.22);
      color: #38bdf8;
      border-color: rgba(56, 189, 248, 0.6);
    }

    /* Body inside HUD */
    .hud-body {
      padding: 12px 14px 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .hud-shell.tucked .hud-body {
      display: none;
    }

    /* Live Target Inspector Bar */
    .target-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(2, 6, 23, 0.65);
      border: 1px solid rgba(99, 102, 241, 0.35);
      border-radius: 8px;
      padding: 7px 10px;
      gap: 8px;
    }
    .target-bar.locked {
      border-color: #38bdf8;
      background: rgba(14, 165, 233, 0.14);
    }
    .target-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
      flex: 1;
    }
    .target-state-label {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: #94a3b8;
    }
    .target-bar.locked .target-state-label {
      color: #38bdf8;
    }
    .target-name {
      font-size: 12.5px;
      font-weight: 600;
      color: #f8fafc;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .target-sub {
      font-family: ui-monospace, monospace;
      font-size: 10.5px;
      color: #94a3b8;
    }

    /* Quick Action Chips */
    .chips-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .chip {
      background: rgba(30, 41, 59, 0.75);
      color: #e2e8f0;
      border: 1px solid rgba(99, 102, 241, 0.35);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.12s;
    }
    .chip:hover {
      background: rgba(79, 70, 229, 0.35);
      border-color: #38bdf8;
      color: #ffffff;
    }

    /* Input Row */
    .hud-input-row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .hud-input {
      flex: 1;
      background: rgba(2, 6, 23, 0.8);
      border: 1px solid rgba(148, 163, 184, 0.35);
      border-radius: 8px;
      padding: 7px 11px;
      color: #f8fafc;
      font-size: 12.5px;
      outline: none;
      user-select: text;
    }
    .hud-input:focus {
      border-color: #38bdf8;
      box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
    }
    @keyframes mic-pulse {
      0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
      70% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
      100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
    }
    .hud-btn {
      background: linear-gradient(135deg, #38bdf8, #6366f1);
      color: #09090b;
      border: none;
      border-radius: 8px;
      padding: 7px 13px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.12s ease;
    }
    .hud-btn:hover { opacity: 0.92; }
    .hud-btn.listening {
      background: #ef4444 !important;
      color: #ffffff !important;
      animation: mic-pulse 1.2s infinite;
    }

    /* Reply / Output Drawer */
    .hud-reply {
      font-size: 12px;
      color: #e2e8f0;
      line-height: 1.48;
      background: rgba(2, 6, 23, 0.6);
      border: 1px solid rgba(148, 163, 184, 0.22);
      border-radius: 8px;
      padding: 9px 11px;
      max-height: 230px;
      overflow-y: auto;
      user-select: text;
    }
    #gaze-explanation-text {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .hud-help {
      font-size: 10.5px;
      color: #94a3b8;
      display: flex;
      justify-content: space-between;
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
        <span class="drag-grip">⠿</span>
        <span>☤ HERMES GAZE</span>
        <span class="plugin-pill" id="hg-tuck-summary">PLUGIN HUD</span>
      </div>
      <div class="hud-controls">
        <button class="ctrl-btn" id="hg-mode-btn" title="Switch between Precise Pointer (σ=${state.hoverSigmaPx}px) and Simulated Noisy Eye Gaze (σ=${state.sigmaPx}px)">🎯 Hover (σ=${state.hoverSigmaPx}px)</button>
        <button class="ctrl-btn" id="hg-clear-btn" title="Clear pins & lens overlays (Esc)">Clear</button>
        <button class="ctrl-btn" id="hg-tuck-btn" title="Tuck or expand the plugin HUD">_ Tuck</button>
      </div>
    </div>
    <div class="hud-body">
      <div class="target-bar" id="hg-target-bar">
        <div class="target-info">
          <div class="target-state-label" id="hg-lock-label">🟢 FOLLOWING CURSOR (Press ${hotkeyLabel()} or wiggle to lock target)</div>
          <div class="target-name" id="hg-target-name">Move cursor over any page element...</div>
          <div class="target-sub" id="hg-target-sub">—</div>
        </div>
        <button class="ctrl-btn" id="hg-lock-btn" title="Freeze target so you can move your mouse to the HUD">🔒 Lock (${hotkeyLabel()})</button>
      </div>
      <nav id="hg-scopes" aria-label="Subject scope" style="display:none;margin:8px 0;font-size:12px;">
        <div id="hg-scope-options" style="display:flex;flex-wrap:wrap;gap:5px;"></div>
        <div style="margin-top:5px;color:#94a3b8;">↑/↓ change scope · Row and column are alternatives, not ancestors.</div>
        <button class="ctrl-btn" id="hg-record" style="margin-top:5px;">Confirm intended scope &amp; save trial</button>
        <span id="hg-record-status" role="status"></span>
      </nav>

      <div class="chips-row">
        <button class="chip" data-prompt="What happens if I press this?">❓ What does this do?</button>
        <button class="chip" data-prompt="Click this">⚡ Click this</button>
        <button class="chip" data-prompt="Export these results and chart Spend vs ROAS">📊 Export &amp; chart table</button>
      </div>

      <div class="hud-input-row">
        <input class="hud-input" id="hg-input" placeholder="Point & speak or ask: 'What happens if I press this?'..." />
        <button class="hud-btn" id="hg-mic-btn" style="background:rgba(239,68,68,0.22);border:1px solid rgba(239,68,68,0.5);color:#fca5a5;" title="Click to speak or hold Spacebar (Push-to-Talk)">🎙️ Speak</button>
        <button class="hud-btn" id="hg-send">Resolve</button>
      </div>

      <div class="hud-reply" id="hg-reply" style="display:none;"></div>

      <div class="hud-help">
        <span id="hg-hotkey-tip">Tip: Hold <strong>Spacebar</strong> to speak or press <strong>${hotkeyLabel()}</strong> to lock</span>
        <span>Drag header ⠿ to move</span>
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
  const scopeNav = hud.querySelector("#hg-scopes");
  const scopeOptions = hud.querySelector("#hg-scope-options");
  const recordStatus = hud.querySelector("#hg-record-status");
  hud.querySelector("#hg-record").addEventListener("click", () => {
    if (state.selectedScopeId && !state.scopePending) {
      recordStatus.textContent = "Saving…";
      _emit({ type: "record", resolution_id: state.resolutionId, scope_id: state.selectedScopeId });
    }
  });
  if (prevInputVal && hudInput) {
    hudInput.value = prevInputVal;
  }
  if (prevReplyHtml && prevReplyDisplay === "block") {
    hudReply.innerHTML = prevReplyHtml;
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
    tuckBtn.textContent = state.tucked ? "Expand ☤" : "_ Tuck";
    if (state.tucked && state.hoveredCandidate) {
      tuckSummary.textContent = `🎯 ${state.hoveredCandidate.label.slice(0, 18)}`;
    } else {
      tuckSummary.textContent = "PLUGIN HUD";
    }
  });

  // --- Mode Switcher (Hover vs Simulated Noisy Gaze) ---
  function syncModeUI() {
    if (state.mode === "hover") {
      modeBtn.textContent = `🎯 Hover (σ=${state.hoverSigmaPx}px)`;
      modeBtn.classList.remove("active");
    } else {
      modeBtn.textContent = `👁️ Gaze Sim (σ=${state.sigmaPx}px)`;
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
      lockLabel.textContent = `🟢 FOLLOWING CURSOR (Press ${hotkeyLabel()} or wiggle to lock target)`;
      lockBtn.textContent = `🔒 Lock (${hotkeyLabel()})`;
    }
    const tip = hud.querySelector("#hg-hotkey-tip");
    if (tip) tip.innerHTML = `Tip: Hold <strong>Spacebar</strong> to speak or press <strong>${escapeHtml(hotkeyLabel())}</strong> to lock`;
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
      lockLabel.textContent = `🔒 TARGET LOCKED (${triggerSource}) — Safe to move mouse to HUD`;
      lockBtn.textContent = "🔓 Unlock";
      lockBtn.classList.add("active");
    } else {
      state.lockedX = null;
      state.lockedY = null;
      spotlight.classList.remove("armed");
      targetBar.classList.remove("locked");
      lockLabel.textContent = `🟢 FOLLOWING CURSOR (Press ${hotkeyLabel()} or wiggle to lock target)`;
      lockBtn.textContent = `🔒 Lock (${hotkeyLabel()})`;
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
      ? `🔒 Locked (σ=${sigmaLabel}px)`
      : `☤ ${state.mode === "hover" ? "Pointer" : "Gaze Cone"} σ=${sigmaLabel}px`;
  }

  // Identities stay in this closure: a selector is metadata, never a historical lookup.
  const cursorIds = new WeakMap();
  const cursorRefs = new Map();
  const cursorHistory = [];
  let cursorSerial = 0;
  let lockedNode = null;
  const speechCaptures = new Map();
  const sensitiveSelector = 'input[type="password"],[autocomplete^="cc-"],[autocomplete="current-password"],[autocomplete="new-password"],[name*="card" i],[name*="payment" i],[name*="cvv" i],[name*="cvc" i],[name^="cc-" i],[id*="card" i],[id*="payment" i],[id*="cvv" i],[id*="cvc" i],[id^="cc-" i]';
  function sensitive(el) {
    const field = el && el.closest("input,textarea,select,[contenteditable]");
    return !!field && field.matches(sensitiveSelector);
  }
  function safeText(el, max = 160) {
    if (!el) return "";
    if (sensitive(el)) return "[redacted]";
    if (el.matches("input,textarea,select")) return "";
    if (el.matches("label") && el.htmlFor && sensitive(document.getElementById(el.htmlFor))) return "[redacted]";
    // Never read field values, labels/attributes, or ancestor innerText wholesale.
    const parts = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (node.nodeType === 1 && (node.matches('input,textarea,select,script,style,#hermes-gaze-root') || sensitive(node)))
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
  function safeLabel(el, max = 100) {
    if (sensitive(el) || (el.matches("label") && el.htmlFor && sensitive(document.getElementById(el.htmlFor))))
      return "[redacted]";
    return (el.getAttribute("aria-label") || el.getAttribute("title") || safeText(el, max)).slice(0, max);
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
    return { id: cursorId(el), available: el.isConnected && !hidden,
      ...(hidden ? { sensitive: true, reason: "sensitive target redacted" } : {}),
      tag: el.tagName.toLowerCase(), role: (el.getAttribute("role") || el.tagName.toLowerCase()).slice(0, 40),
      label: hidden ? "[redacted]" : safeLabel(el, 100),
      selector: hidden ? "" : buildSelector(el).slice(0, 350),
      rect_vp: [r.left, r.top, r.width, r.height],
      rect_doc: [r.left + scrollX, r.top + scrollY, r.width, r.height], block_ids: [] };
  }
  function captureCursorContext() {
    const capture = { version: 1, captured_at: Date.now() / 1000, page_url: location.origin + location.pathname,
      page_title: String(document.title || "").slice(0, 160),
      history: cursorHistory.map(h => ({ ...h })), targets: [], blocks: [], controls: [], handles: {} };
    function handle(node) {
      const id = cursorId(node);
      if (!capture.handles[id] && !sensitive(node)) {
        const r = node.getBoundingClientRect();
        capture.handles[id] = { selector: buildSelector(node).slice(0, 350), rect_vp: [r.left, r.top, r.width, r.height] };
      }
      return id;
    }
    const blocks = new Map();
    const refs = [...new Set(capture.history.map(h => h.id).filter(Boolean))].slice(-64);
    for (const id of refs) {
      const el = cursorRefs.get(id);
      if (!el || !el.isConnected) { capture.targets.push({ id, available: false, reason: "historical node detached" }); continue; }
      const target = cursorMetadata(el);
      capture.targets.push(target);
      if (!target.available) continue;
      handle(el);
      const cell = el.closest("th,td,[role=cell],[role=gridcell],[role=columnheader],[role=rowheader]");
      const table = el.closest("table,[role=grid]");
      if (table) {
        const bid = handle(table);
        if (!blocks.has(bid)) {
          const rowNodes = [...table.querySelectorAll("tr,[role=row]")].filter(row => row.closest("table,[role=grid]") === table);
          const headerRow = rowNodes.find(row => row.querySelector("th,[role=columnheader]"));
          const allCells = row => [...row.querySelectorAll("th,td,[role=cell],[role=gridcell],[role=columnheader],[role=rowheader]")]
            .filter(cell => cell.closest("tr,[role=row]") === row);
          const cellsOf = row => allCells(row).slice(0, 12);
          const dataRows = rowNodes.filter(row => row !== headerRow);
          blocks.set(bid, { id: bid, kind: "table", label: safeText(table.querySelector("caption"), 80),
            headers: headerRow ? cellsOf(headerRow).map(c => `${handle(c)} ${safeText(c, 60)}`) : [],
            total_rows: dataRows.length, rows: [], _rows: dataRows, _cells: cellsOf, _allCells: allCells,
            _header: headerRow, omitted_columns: headerRow ? Math.max(0, allCells(headerRow).length - 12) : 0 });
        }
        const block = blocks.get(bid);
        target.block_ids.push(bid);
        const row = cell && cell.closest("tr,[role=row]");
        const ri = block._rows.indexOf(row);
        if (cell) {
          const column = row ? block._allCells(row).indexOf(cell) : -1;
          const header = block._header && block._allCells(block._header)[column];
          target.cell = { block: bid, row: ri + 1, column: column + 1, value: safeText(cell, 100),
            header: header ? `${handle(header)} ${safeText(header, 60)}` : "" };
        }
        const indices = block._rows.length <= 12 ? block._rows.map((_, i) => i) : [ri];
        for (const i of indices) if (i >= 0 && block.rows.length < 64 && !block.rows.some(r => r.index === i + 1)) {
          const node = block._rows[i];
          block.rows.push({ id: handle(node), index: i + 1, cells: block._cells(node).map(c => safeText(c, 70)) });
        }
      }
      const parents = new Set([el.closest("ul,ol,[role=list],p,h1,h2,h3,h4,h5,h6"), el.closest("article,section,.card")]);
      if (![...parents].some(Boolean)) parents.add(el.parentElement);
      for (const parent of parents) {
        if (!parent || parent === document.body || parent === document.documentElement) continue;
        const bid = handle(parent);
        target.block_ids.push(bid);
        if (!blocks.has(bid)) blocks.set(bid, { id: bid, kind: parent.tagName.toLowerCase(),
          label: safeLabel(parent.querySelector("h1,h2,h3,h4,h5,h6") || parent, 80),
          text: safeText(parent, 650), text_limit: 650 });
      }
    }
    capture.blocks = [...blocks.values()].map(({ _rows, _cells, _allCells, _header, ...block }) => block);
    // One bounded page-control pass per capture, never once per cell/mousemove.
    const controls = document.querySelectorAll('button,a,input,select,[role=button]');
    for (let i = 0; i < controls.length && i < 120 && capture.controls.length < 12; i++) {
      const el = controls[i];
      if (el.closest("#hermes-gaze-root") || sensitive(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width && r.height) { handle(el); capture.controls.push(cursorMetadata(el)); }
    }
    capture.omitted_controls = Math.max(0, controls.length - capture.controls.length);
    return capture;
  }
  function onCursorScroll() {
    if (!state.armed && !cursorOverHud && typeof state.pointerX === "number")
      rememberHit(hitNode(state.pointerX, state.pointerY));
  }
  window.addEventListener("scroll", onCursorScroll, { passive: true, capture: true });

  function updateLiveInspector(x, y) {
    if (typeof x !== "number" || typeof y !== "number") {
      state.hoveredCandidate = null;
      targetName.textContent = "Move cursor over any page element...";
      targetSub.textContent = "—";
      return;
    }
    const el = state.armed ? lockedNode : hitNode(x, y);
    const best = el ? cursorMetadata(el) : null;
    state.hoveredCandidate = best;
    if (best) {
      targetName.textContent = `${best.label} (${formatRoleDisplayName(best.role || best.tag)})`;
      targetSub.textContent = best.consequence || best.summary || `Role: ${best.role} · [${Math.round(best.rect_vp[0])}, ${Math.round(best.rect_vp[1])}]`;
      if (state.tucked) {
        tuckSummary.textContent = `🎯 ${best.label.slice(0, 18)}`;
      }
    } else {
      targetName.textContent = "No interactive target under pointer";
      targetSub.textContent = `Cursor at (${Math.round(x)}, ${Math.round(y)})`;
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
      tuckBtn.textContent = "_ Tuck";
      tuckSummary.textContent = "PLUGIN HUD";
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
      showHudMessage('<div style="color:#f87171;">⚠️ Resolver offline (session not connected).</div>');
      return false;
    }
    window.__hermesGazeIntent(JSON.stringify(intent));
    return true;
  }

  function renderScopeOptions(msg) {
    state.resolutionId = msg.resolution_id;
    state.scopes = msg.scopes || [];
    state.selectedScopeId = msg.selected_scope_id;
    scopeOptions.replaceChildren();
    scopeNav.style.display = state.scopes.length ? "block" : "none";
    recordStatus.textContent = "";
    for (const scope of state.scopes) {
      const button = document.createElement("button");
      button.className = "ctrl-btn";
      button.textContent = scope.scope || scope.role;
      button.title = `${scope.label}: ${scope.summary || ""}`;
      button.setAttribute("aria-pressed", String(scope.id === state.selectedScopeId));
      if (scope.id === state.selectedScopeId) button.style.borderColor = "#38bdf8";
      button.addEventListener("click", () => selectScope(scope.id));
      scopeOptions.appendChild(button);
    }
  }

  function selectScope(scopeId) {
    if (state.scopePending || scopeId === state.selectedScopeId) return;
    state.scopePending = _emit({
      type: "scope", resolution_id: state.resolutionId, scope_id: scopeId,
    });
  }

  function stepScope(direction) {
    const index = state.scopes.findIndex((scope) => scope.id === state.selectedScopeId);
    const next = state.scopes[index + direction];
    if (next) selectScope(next.id);
  }
  function emitResolve(utterance, words, captured) {
    const text = (utterance || "").trim();
    if (!text) return false;
    state.scopePending = false;
    state.scopes = [];
    scopeNav.style.display = "none";
    const locked = state.armed && state.lockedX !== null && state.lockedY !== null;
    const px = locked ? state.lockedX : state.pointerX;
    const py = locked ? state.lockedY : state.pointerY;
    if (typeof px !== "number" || typeof py !== "number") {
      showHudMessage('<div style="color:#fbbf24;">🎯 Aim the pointer at an element first, then speak or type.</div>');
      return false;
    }
    const intent = {
      type: "resolve",
      utterance: text,
      page_url: location.href,
      pointer: { x_vp: px, y_vp: py, scroll_x: window.scrollX, scroll_y: window.scrollY },
      fixations: state.ringBuffer.slice(-25),
      ...(state.mode === "hover" ? { cursor_context: captured || captureCursorContext() } :
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

    if (msg.type === "record") {
      if (msg.resolution_id && msg.resolution_id !== state.resolutionId) return;
      recordStatus.textContent = msg.ok ? `Saved: ${msg.path}` : `Save failed: ${msg.error}`;
      return;
    }

    if (msg.type === "resolve" || msg.type === "scope") {
      if (msg.type === "resolve" && msg.id < _lastSentResolveId) return;
      if (msg.type === "scope") {
        state.scopePending = false;
        if (msg.resolution_id && msg.resolution_id < state.resolutionId) return;
      }
      if (!msg.ok) {
        showHudMessage(`<div style="color:#f87171;">⚠️ ${escapeHtml(msg.error || "Resolver error.")}</div>`);
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
          expEl.innerHTML = `<span style="color:#f8fafc;">${escapeHtml(msg.explanation)}</span>`;
        } else {
          const fallback = msg.error || _pendingExplainFallback || "Explanation unavailable.";
          expEl.innerHTML = `<span style="color:#cbd5e1;">${escapeHtml(fallback)}</span>`;
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
        showHudMessage(`<div style="color:#f87171;">⚠️ ${escapeHtml(msg.error || "Selection failed.")}</div>`);
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

  const DEFAULT_PLACEHOLDER = "Point & speak or ask: 'What happens if I press this?'...";
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
    hudMic.textContent = "🎙️ Speak";
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
    hudMic.textContent = "⏹️ Stop";
    hudInput.placeholder = "🎙️ Listening... Speak your query (e.g. 'What does this button do?')";
    lockLabel.textContent = "🎙️ RECORDING VOICE... (Speak now, click Stop or release Space)";
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
        hudMic.textContent = "⏳ Transcribing...";
        lockLabel.textContent = "⏳ Transcribing audio locally…";

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
      hudMic.textContent = "⏳ Transcribing...";
      lockLabel.textContent = "⏳ Transcribing audio locally…";

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
    if ((e.key === "ArrowUp" || e.key === "ArrowDown") && state.scopes.length) {
      e.preventDefault();
      stepScope(e.key === "ArrowUp" ? 1 : -1);
      return;
    }
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
    if ((e.key === "ArrowUp" || e.key === "ArrowDown") && state.scopes.length) {
      e.preventDefault();
      e.stopPropagation();
      stepScope(e.key === "ArrowUp" ? 1 : -1);
      return;
    }
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
    scopeNav.style.display = "none";
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
      tuckBtn.textContent = "_ Tuck";
      tuckSummary.textContent = "PLUGIN HUD";
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
      const [x, y, w, h] = cand.rect_vp || [100, 100, 120, 36];
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
      showHudMessage(`<div style="color:#38bdf8;font-weight:600;">${promptMessage}</div>`);
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

