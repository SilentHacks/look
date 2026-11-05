(function () {
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
    dwellMs: 450,
    wiggleTrigger: true,
    tucked: false,
    armed: false, // When true, lockedX / lockedY stay frozen while user interacts with HUD
    armedAt: 0,
    pointerX: prevState && typeof prevState.pointerX === "number" ? prevState.pointerX : Math.round(window.innerWidth * 0.5),
    pointerY: prevState && typeof prevState.pointerY === "number" ? prevState.pointerY : Math.round(window.innerHeight * 0.35),
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
  spotlightTag.textContent = "☤ Gaze σ=18px";
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
        <button class="ctrl-btn" id="hg-mode-btn" title="Switch between Precise Pointer (σ=18px) and Simulated Noisy Eye Gaze (σ=130px)">🎯 Hover (σ=18px)</button>
        <button class="ctrl-btn" id="hg-clear-btn" title="Clear pins & lens overlays (Esc)">Clear</button>
        <button class="ctrl-btn" id="hg-tuck-btn" title="Tuck or expand the plugin HUD">_ Tuck</button>
      </div>
    </div>
    <div class="hud-body">
      <div class="target-bar" id="hg-target-bar">
        <div class="target-info">
          <div class="target-state-label" id="hg-lock-label">🟢 FOLLOWING CURSOR (Press \` or wiggle to lock target)</div>
          <div class="target-name" id="hg-target-name">Move cursor over any page element...</div>
          <div class="target-sub" id="hg-target-sub">—</div>
        </div>
        <button class="ctrl-btn" id="hg-lock-btn" title="Freeze target so you can move your mouse to the HUD">🔒 Lock (\`)</button>
      </div>

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
        <span>Tip: Hold <strong>Spacebar</strong> to speak or press <strong>\`</strong> to lock</span>
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
      modeBtn.textContent = "🎯 Hover (σ=18px)";
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
  });

  clearBtn.addEventListener("click", () => {
    clearOverlays("clearBtn");
  });

  // --- Target Lock / Unlock ---
  function setTargetLocked(locked, triggerSource = "manual") {
    state.armed = locked;
    if (locked) {
      state.armedAt = Date.now() / 1000;
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
      lockLabel.textContent = "🟢 FOLLOWING CURSOR (Press ` or wiggle to lock target)";
      lockBtn.textContent = "🔒 Lock (`)";
      lockBtn.classList.remove("active");
    }
    const activeX = state.armed && state.lockedX !== null ? state.lockedX : state.pointerX;
    const activeY = state.armed && state.lockedY !== null ? state.lockedY : state.pointerY;
    updateSpotlightPosition(activeX, activeY);
  }

  lockBtn.addEventListener("click", () => {
    setTargetLocked(!state.armed, "button");
  });

  function updateSpotlightPosition(x, y) {
    const r = state.mode === "hover" ? 46 : Math.max(state.sigmaPx * 1.45, 110);
    spotlight.style.width = `${r}px`;
    spotlight.style.height = `${r}px`;
    spotlight.style.left = `${x}px`;
    spotlight.style.top = `${y}px`;
    spotlightTag.textContent = state.armed
      ? `🔒 Locked (${state.mode === "hover" ? "σ=18px" : "σ=" + state.sigmaPx + "px"})`
      : `☤ ${state.mode === "hover" ? "Pointer σ=18px" : "Gaze Cone σ=" + state.sigmaPx + "px"}`;
  }

  function updateLiveInspector(x, y) {
    const near = extractCandidatesNear(x, y, 220);
    // Find best candidate directly under or closest to (x, y)
    let best = null;
    let bestDist = Infinity;
    for (const c of near) {
      const [rx, ry, rw, rh] = c.rect_vp;
      const inside = x >= rx && x <= rx + rw && y >= ry && y <= ry + rh;
      const cx = rx + rw / 2;
      const cy = ry + rh / 2;
      const dist = Math.hypot(x - cx, y - cy) + (c.is_container ? 45 : 0) + (inside ? -100 : 0);
      if (dist < bestDist) {
        bestDist = dist;
        best = c;
      }
    }
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

    state.ringBuffer.push({
      x_vp: activeX,
      y_vp: activeY,
      x_doc: activeX + window.scrollX,
      y_doc: activeY + window.scrollY,
      t: Date.now() / 1000,
      sigma: state.mode === "hover" ? 22 : state.sigmaPx,
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

  // --- In-Browser 2D Gaussian Box Integral & Deictic Resolution Engine ---
  function erf(x) {
    const sign = x >= 0 ? 1 : -1;
    x = Math.abs(x);
    const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
    const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
    const t = 1.0 / (1.0 + p * x);
    const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
    return sign * y;
  }

  function gaussianBoxIntegral(rx, ry, rw, rh, gx, gy, sigma) {
    const s = Math.max(sigma, 8.0) * Math.SQRT2;
    const px = 0.5 * (erf((rx + rw - gx) / s) - erf((rx - gx) / s));
    const py = 0.5 * (erf((ry + rh - gy) / s) - erf((ry - gy) / s));
    const areaNorm = Math.pow(Math.max(rw * rh, 1.0) + 1200.0, 0.40);
    return Math.max((px * py) / areaNorm, 1e-12);
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

  function resolveLocallyInBrowser(utterance) {
    const text = (utterance || "").trim();
    if (!text) return;
    const lower = text.toLowerCase();

    const activeX = state.armed && state.lockedX !== null ? state.lockedX : state.pointerX;
    const activeY = state.armed && state.lockedY !== null ? state.lockedY : state.pointerY;
    const sigma = state.mode === "hover" ? 22 : state.sigmaPx;

    const candidates = extractCandidatesNear(activeX, activeY, Math.max(sigma * 2.6, 260));
    if (!candidates.length) {
      showHudMessage("No candidate elements found near the pointed location.");
      return;
    }

    const isReadOnly = /(what|why|how|which|where|who|explain|describe|tell me|show me|inspect|info|happens if|does this)/.test(lower);
    const isPluralOrData = /(these|those|results|rows|table|export|chart|plot|spend|roas)/.test(lower);

    const scored = candidates.map((c) => {
      const [rx, ry, rw, rh] = c.rect_vp;
      const boxMass = gaussianBoxIntegral(rx, ry, rw, rh, activeX, activeY, sigma);
      const spatialLog = Math.log(boxMass);

      let semScore = 0.0;
      if (isPluralOrData && (c.is_container || c.role === "table")) {
        semScore += 4.8;
      } else if (!isPluralOrData && c.is_interactive && !c.is_container) {
        semScore += 3.5;
      } else if (!isPluralOrData && !c.is_container) {
        // Atomic leaf informational elements like th, td, abbr
        semScore += 3.2;
      } else if (!isPluralOrData && c.is_container) {
        semScore -= 5.0;
      }
      if (c.is_direct_hit) {
        semScore += 3.5;
      }
      // Lexical overlap boost
      const labelWords = (c.label + " " + c.id).toLowerCase().split(/\W+/);
      for (const w of labelWords) {
        if (w.length > 2 && lower.includes(w)) semScore += 2.0;
      }

      const logPost = spatialLog + semScore;
      const roleName = formatRoleDisplayName(c.role || c.tag);
      let desc = c.consequence || c.summary;
      if (!desc) {
        if (c.role === "columnheader" || c.tag === "th") {
          desc = `Column header "${c.label}" in table`;
        } else if (c.role === "cell" || c.tag === "td") {
          desc = `Table cell "${c.label}"`;
        } else if (c.is_interactive) {
          desc = `Actionable ${roleName.toLowerCase()} element`;
        } else {
          desc = `Informational ${roleName.toLowerCase()}`;
        }
      }

      return {
        ...c,
        spatial_score: Number(spatialLog.toFixed(4)),
        semantic_score: Number(semScore.toFixed(4)),
        log_post: logPost,
        consequence_preview: desc,
      };
    });

    scored.sort((a, b) => b.log_post - a.log_post);
    const maxLog = scored[0].log_post;
    const exps = scored.map((s) => Math.exp(Math.max(s.log_post - maxLog, -30)));
    const sumExp = exps.reduce((a, b) => a + b, 0) || 1;
    scored.forEach((s, i) => {
      s.probability = Number((exps[i] / sumExp).toFixed(4));
    });

    const top = scored[0];
    const second = scored[1];
    const margin = second ? top.probability - second.probability : 1.0;

    if (isPluralOrData && (top.is_container || top.role === "table")) {
      const tableData = extractTableData(top.selector);
      const svg = renderMiniSvgScatter(tableData);
      renderPins(
        [top],
        `<div style="font-size:13.5px;"><strong style="color:#38bdf8;">📊 Promoted to Container: ${top.label}</strong></div>` +
        `<div style="color:#cbd5e1;font-size:12px;margin-top:3px;">Extracted ${tableData ? tableData.rows.length : 0} rows × ${tableData ? tableData.headers.length : 0} cols</div>` +
        (svg || "") +
        `<div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.08);display:flex;gap:12px;font-size:11px;color:#64748b;font-family:ui-monospace,monospace;">` +
        `<span>Target: ${top.selector}</span><span>Confidence: ${Math.round(top.probability * 100)}%</span>` +
        `</div>`
      );
      return;
    }

    if (isReadOnly) {
      const roleDisplayName = formatRoleDisplayName(top.role || top.tag);
      const fallbackDesc = top.summary || top.consequence || top.consequence_preview || `Informational ${roleDisplayName.toLowerCase()}`;
      const interactiveNote = top.is_interactive
        ? `<div style="margin-top:5px;font-size:11.5px;color:#94a3b8;">Type: Interactive ${roleDisplayName.toLowerCase()} (requires click or action verb to trigger).</div>`
        : "";

      renderPins(
        [top],
        `<div style="font-size:13.5px;"><strong style="color:#38bdf8;">🔍 Inspecting: ${top.label}</strong> <span style="color:#94a3b8;font-size:11.5px;font-weight:500;">(${roleDisplayName})</span></div>` +
        `<div id="gaze-explanation-text" style="margin-top:6px;color:#f8fafc;font-size:12.5px;line-height:1.45;">` +
        `<span style="color:#38bdf8;font-style:italic;">⏳ Asking Hermes...</span>` +
        `</div>` +
        interactiveNote +
        `<div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.08);display:flex;gap:12px;font-size:11px;color:#64748b;font-family:ui-monospace,SFMono-Regular,monospace;">` +
        `<span>Target: ${top.selector}</span><span>Confidence: ${Math.round(top.probability * 100)}%</span>` +
        `</div>`
      );

      // Asynchronously ask Hermes for the semantic explanation
      fetch("http://127.0.0.1:9111/api/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          utterance: text,
          label: top.label,
          role: roleDisplayName,
          summary: top.summary || top.consequence || "",
        }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data && data.ok && data.explanation) {
            const expEl = shadow.querySelector("#gaze-explanation-text");
            if (expEl) {
              expEl.innerHTML = `<span style="color:#f8fafc;">${data.explanation}</span>`;
            }
          }
        })
        .catch(() => {
          const expEl = shadow.querySelector("#gaze-explanation-text");
          if (expEl) {
            expEl.innerHTML = `<span style="color:#cbd5e1;">${fallbackDesc}</span>`;
          }
        });

      return;
    }

    if (margin < 0.35 || top.is_destructive || state.mode === "simulated") {
      const reason = top.is_destructive
        ? "⚠️ High-Consequence Target — Confirm in Semantic Lens"
        : "🔍 Ambiguous Gaze Cone — Pick Target in Semantic Lens (Hover 450ms, Press 1-3, or Click)";
      renderSemanticLens(scored.slice(0, 3), reason);
      return;
    }

    // High-confidence safe action
    selectLensCandidateFromList(scored, 0, "auto-confident");
  }

  function renderMiniSvgScatter(tableData) {
    if (!tableData || !tableData.rows || !tableData.rows.length) return "";
    const pts = tableData.rows.map((r) => {
      const name = r[0] || "Row";
      const spend = parseFloat(String(r[4] || "0").replace(/[^0-9.]/g, "")) || 0;
      const roas = parseFloat(String(r[5] || "0").replace(/[^0-9.]/g, "")) || 0;
      return { name, spend, roas };
    });
    const maxSpend = Math.max(...pts.map((p) => p.spend), 1);
    const maxRoas = Math.max(...pts.map((p) => p.roas), 1);
    const circles = pts.map((p) => {
      const cx = (42 + (p.spend / maxSpend) * 320).toFixed(1);
      const cy = (108 - (p.roas / maxRoas) * 84).toFixed(1);
      return `<circle cx="${cx}" cy="${cy}" r="5" fill="#38bdf8" stroke="#09090b" stroke-width="1.5"/>` +
             `<text x="${Number(cx) + 7}" y="${Number(cy) + 3}" fill="#e2e8f0" font-size="9.5" font-family="monospace">${p.name.slice(0, 14)}</text>`;
    }).join("");
    return `<svg viewBox="0 0 420 128" width="100%" height="128" style="background:#09090b;border:1px solid rgba(99,102,241,0.35);border-radius:6px;margin-top:6px;">` +
           `<line x1="38" y1="16" x2="38" y2="110" stroke="#334155"/><line x1="38" y1="110" x2="395" y2="110" stroke="#334155"/>` +
           `<text x="215" y="124" fill="#94a3b8" font-size="9.5" text-anchor="middle">Spend ($) vs ROAS (x)</text>` +
           circles + `</svg>`;
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
    setTargetLocked(true, "voice");

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

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          audioChunks.push(e.data);
        }
      };

      recorder.onstop = async () => {
        const chunks = audioChunks.slice();
        audioChunks = [];
        const recordedBlob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });

        if (recordedBlob.size < 200) {
          resetMicUiIdle("⚠️ Spoke too briefly. Hold Spacebar or click Speak, then talk.");
          return;
        }

        hudMic.classList.remove("listening");
        hudMic.textContent = "⏳ Transcribing...";
        lockLabel.textContent = "⏳ Transcribing audio with local Whisper (tiny.en)...";

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 12000);

        try {
          const resp = await fetch("http://127.0.0.1:9111/api/transcribe", {
            method: "POST",
            headers: { "Content-Type": recordedBlob.type || "audio/webm" },
            body: recordedBlob,
            signal: controller.signal,
          });
          const data = await resp.json();
          resetMicUiIdle();

          if (data && data.ok && data.text && data.text.trim()) {
            const spoken = data.text.trim();
            hudInput.value = spoken;
            hudInput.dispatchEvent(new Event("input", { bubbles: true }));
            lockLabel.textContent = `🗣️ Heard: "${spoken}"`;
            resolveLocallyInBrowser(spoken);
          } else if (data && data.error) {
            lockLabel.textContent = `❌ ${data.error}`;
          } else {
            lockLabel.textContent = "⚠️ No speech detected in audio. Please speak clearly while holding Spacebar.";
          }
        } catch (err) {
          const msg = err && err.name === "AbortError" ? "Transcription request timed out" : (err.message || err);
          resetMicUiIdle(`❌ Whisper API error: ${msg}`);
        } finally {
          clearTimeout(timeoutId);
        }
      };

      recorder.start(80);
      recordingStartedAt = performance.now();
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
      lockLabel.textContent = "⏳ Transcribing audio with local Whisper (tiny.en)...";

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
      resolveLocallyInBrowser(prompt);
    });
  });

  hudSend.addEventListener("click", () => {
    resolveLocallyInBrowser(hudInput.value);
  });

  hudInput.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      resolveLocallyInBrowser(hudInput.value);
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
    if (e.code === "Backquote" || (e.altKey && e.code === "Space")) {
      e.preventDefault();
      setTargetLocked(!state.armed, "hotkey");
    } else if (state.lensActive && ["Digit1", "Digit2", "Digit3", "Digit4"].includes(e.code)) {
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
    return (
      el.getAttribute("data-gaze-label") ||
      el.getAttribute("aria-label") ||
      el.getAttribute("title") ||
      (el.innerText || "").trim().split("\n")[0].slice(0, 70) ||
      el.id ||
      el.tagName.toLowerCase()
    );
  }

  function buildSelector(el) {
    if (el.id) return `#${el.id}`;
    const tag = el.tagName.toLowerCase();
    if (tag === "th" || tag === "td") {
      const parentTable = el.closest("table");
      const tablePrefix = parentTable && parentTable.id ? `#${parentTable.id} ` : "";
      const idx = el.cellIndex !== undefined ? el.cellIndex + 1 : 1;
      return `${tablePrefix}${tag}:nth-child(${idx})`;
    }
    const cls = Array.from(el.classList || []).slice(0, 2).join(".");
    return cls ? `${tag}.${cls}` : tag;
  }

  function extractCandidatesNear(x, y, radiusPx) {
    const rad = radiusPx || 240;
    const selectors = "button, a, input, select, textarea, [role='button'], [data-gaze-target], table, th, td, [role='columnheader'], [role='cell'], [data-card], section.panel, article.card, [data-metric], abbr";
    const nodes = Array.from(document.querySelectorAll(selectors));

    // Direct hit test via document.elementFromPoint
    const directEl = (typeof document.elementFromPoint === "function" && x >= 0 && y >= 0 && x <= window.innerWidth && y <= window.innerHeight)
      ? document.elementFromPoint(x, y)
      : null;
    const directCandidate = directEl && !directEl.closest("#hermes-gaze-root")
      ? (directEl.closest(selectors) || directEl)
      : null;
    if (directCandidate && !nodes.includes(directCandidate) && !directCandidate.closest("#hermes-gaze-root")) {
      nodes.unshift(directCandidate);
    }

    const results = [];

    for (let i = 0; i < nodes.length; i++) {
      const el = nodes[i];
      if (el.closest("#hermes-gaze-root")) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) continue;

      const cx = Math.max(r.left, Math.min(x, r.right));
      const cy = Math.max(r.top, Math.min(y, r.bottom));
      const dist = Math.hypot(x - cx, y - cy);
      if (dist > rad) continue;

      const tag = el.tagName.toLowerCase();
      const isContainer = ["table", "section", "article", "ul", "ol"].includes(tag) || el.hasAttribute("data-card");
      const role = el.getAttribute("role") || (
        isContainer ? tag :
        tag === "a" ? "link" :
        tag === "th" ? "columnheader" :
        tag === "td" ? "cell" :
        tag === "input" || tag === "textarea" ? "textbox" :
        tag === "button" ? "button" :
        tag
      );
      const label = getAccessibleLabel(el);
      const isDestructive = /delete|remove|purge|drop|destroy|pay|revoke/i.test(label + " " + (el.className || ""));
      const isInteractive = !isContainer && (["button", "a", "input", "select", "textarea"].includes(tag) || el.getAttribute("role") === "button");

      let summary = el.getAttribute("data-gaze-summary") || "";
      if (tag === "table" && !summary) {
        const rows = el.querySelectorAll("tbody tr").length;
        const headers = Array.from(el.querySelectorAll("thead th")).map((th) => th.innerText.trim());
        summary = `Table: ${headers.length} columns (${headers.join(", ")}), ${rows} rows`;
      } else if (tag === "th" && !summary) {
        const table = el.closest("table");
        const tableLabel = table ? (table.getAttribute("data-gaze-label") || table.id || "table") : "table";
        summary = `Column header "${label}" in ${tableLabel}`;
      } else if (tag === "td" && !summary) {
        const table = el.closest("table");
        const tableLabel = table ? (table.getAttribute("data-gaze-label") || table.id || "table") : "table";
        const colIdx = el.cellIndex;
        const th = table && colIdx !== undefined ? table.querySelectorAll("thead th")[colIdx] : null;
        const colName = th ? th.innerText.trim() : `col ${colIdx !== undefined ? colIdx + 1 : ""}`;
        summary = `Table cell "${label}" (${colName}) in ${tableLabel}`;
      }

      const isDirectHit = Boolean(
        !isContainer &&
        (el === directCandidate || (!directCandidate && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom))
      );

      results.push({
        id: el.id || `gaze-cand-${i}`,
        tag,
        role,
        label,
        selector: buildSelector(el),
        rect_vp: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
        rect_doc: [
          Math.round(r.left + window.scrollX),
          Math.round(r.top + window.scrollY),
          Math.round(r.width),
          Math.round(r.height),
        ],
        is_container: isContainer,
        is_interactive: isInteractive,
        is_destructive: isDestructive,
        is_direct_hit: isDirectHit,
        summary,
        consequence: el.getAttribute("data-consequence") || "",
      });
    }
    return results;
  }

  function extractTableData(selector) {
    const el = document.querySelector(selector) || document.querySelector("table");
    if (!el) return null;
    const headers = Array.from(el.querySelectorAll("thead th, tr:first-child th")).map((th) => th.innerText.trim());
    const rows = Array.from(el.querySelectorAll("tbody tr")).map((tr) =>
      Array.from(tr.querySelectorAll("td")).map((td) => td.innerText.trim())
    );
    return { headers, rows };
  }

  function clearOverlays(source) {
    pinsLayer.innerHTML = "";
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

  function renderSemanticLens(candidates, promptMessage) {
    pinsLayer.innerHTML = "";
    svgLeaders.innerHTML = "";
    lensLayer.innerHTML = "";
    state.lensActive = true;
    state.lensCandidates = (candidates || []).slice(0, 4);

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
        <div class="lens-title">${cand.label || cand.selector}</div>
        <div class="lens-desc">↳ ${cand.consequence_preview || cand.consequence || "Execute action"}</div>
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

  function selectLensCandidateFromList(list, idx, modality) {
    const chosen = list[idx];
    if (!chosen) return;
    const roleDisplayName = formatRoleDisplayName(chosen.role || chosen.tag);
    renderPins(
      [chosen],
      `<div style="font-size:13.5px;"><strong style="color:#34d399;">✓ Executed: ${chosen.label}</strong> <span style="color:#94a3b8;font-size:11.5px;">(${roleDisplayName} via ${modality})</span></div>` +
      `<div style="margin-top:5px;color:#cbd5e1;font-size:12px;line-height:1.4;">${chosen.consequence_preview || chosen.summary || ""}</div>` +
      `<div style="margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.08);display:flex;gap:12px;font-size:11px;color:#64748b;font-family:ui-monospace,monospace;">` +
      `<span>Target: ${chosen.selector}</span><span>Modality: ${modality}</span>` +
      `</div>`
    );
    const el = document.querySelector(chosen.selector);
    if (el && typeof el.click === "function") {
      el.click();
    }
  }

  function selectLensCandidate(idx, modality) {
    selectLensCandidateFromList(state.lensCandidates, idx, modality);
  }

  function destroy() {
    if (stopDelayTimer) {
      clearTimeout(stopDelayTimer);
      stopDelayTimer = null;
    }
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
      updateLiveInspector(state.pointerX, state.pointerY);
    },
    getInputValue() {
      return hudInput ? hudInput.value : "";
    },
    destroy,
    startListening,
    stopListening,
    armInteraction,
    extractCandidatesNear,
    extractTableData,
    renderPins,
    renderSemanticLens,
    clearOverlays,
    resolveLocallyInBrowser,
    showHudMessage(htmlText) {
      showHudMessage(htmlText);
    },
  };

  window.__HERMES_GAZE_OVERLAY__ = api;
  return api;
})();

