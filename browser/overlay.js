(function () {
  // Main frame only — addScriptToEvaluateOnNewDocument runs in EVERY frame; untrusted
  // iframes must not render a second HUD or reach the intent binding.
  if (window.top !== window.self) return;

  // Always tear down any prior overlay instance cleanly (removing window listeners & streams)
  const prevApi = window.__HERMES_GAZE_OVERLAY__;
  const prevState = prevApi && prevApi.state ? prevApi.state : null;
  const prevInputVal = prevApi && typeof prevApi.getInputValue === "function" ? prevApi.getInputValue() : "";
  const prevReplyText = prevApi?.getReplyText?.() || "";
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
    wiggleTrigger: prevState && prevState.wiggleTrigger !== undefined ? prevState.wiggleTrigger : true,
    candidateRadiusPx: (prevState && prevState.candidateRadiusPx) || 380,
    hotkey: (prevState && prevState.hotkey) || "Backquote",
    resolutionId: 0,
    scopes: [],
    selectedScopeId: null,
    scopePending: false,
    armed: false, // When true, lockedX / lockedY stay frozen while user interacts with HUD
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

  // Only geometry lives in the website DOM. Private UI nodes stay detached here
  // and are rendered by CDP in a script-disabled, opaque-origin iframe.
  const host = document.createElement("div");
  host.id = "hermes-gaze-root";
  host.setAttribute("popover", "manual");
  host.style.cssText = "all:initial!important;position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;margin:0!important;padding:0!important;border:0!important;pointer-events:none!important;background:transparent!important";
  const hostStyle = host.style.cssText;
  document.documentElement.appendChild(host);
  host.showPopover();
  const visualShadow = host.attachShadow({ mode: "closed" });
  const shadow = document.implementation.createHTMLDocument("").createElement("div");
  const uiFrame = document.createElement("iframe");
  uiFrame.setAttribute("sandbox", "");
  uiFrame.setAttribute("aria-label", "Hermes Gaze private controls");
  uiFrame.style.cssText = "position:fixed;z-index:1;left:0;top:0;width:1px;height:1px;border:0;pointer-events:none;background:transparent;color-scheme:normal";
  visualShadow.appendChild(uiFrame);
  let uiRevision = 0;
  let uiEvent = null;
  let uiSerial = 0;
  const uiNodes = new Map();
  function trustedUi(event) { return event.isTrusted || event === uiEvent; }
  function takeUiSnapshot() {
    for (const node of shadow.querySelectorAll("*")) {
      if (!node.dataset.hgUi) {
        node.dataset.hgUi = String(++uiSerial);
        uiNodes.set(node.dataset.hgUi, node);
      }
    }
    for (const [id, node] of uiNodes) if (!shadow.contains(node)) uiNodes.delete(id);
    const focus = focusInput;
    focusInput = false;
    const dark = pageIsDark();
    pinsLayer.style.color = dark ? "#ff8b70" : "#c33d26";
    svgLeaders.style.stroke = pinsLayer.style.color;
    return { revision: ++uiRevision, html: shadow.innerHTML, value: hudInput.value, focusInput:focus,
      viewportHeight: Math.max(1, (window.visualViewport?.height || window.innerHeight) - 32), dark, hotkey:state.hotkey, lensActive:state.lensActive };
  }
  const uiObserver = new MutationObserver(() => {
    if (_intentNonce && !destroyed)
      window.__hermesGazeIntent(JSON.stringify({ type: "_ui_render", ...takeUiSnapshot() }));
  });
  uiObserver.observe(shadow, { childList: true, subtree: true, characterData: true, attributes: true,
    attributeFilter: ["style", "class", "hidden", "aria-expanded", "aria-pressed", "aria-label", "disabled"] });
  function fitUiFrame(height) {
    frameHeight = Math.max(1, Math.min(height, (window.visualViewport?.height || window.innerHeight) - 32));
    positionNote();
  }
  function onUiResize() {
    fitUiFrame(uiFrame.getBoundingClientRect().height);
    if (_intentNonce && !destroyed)
      window.__hermesGazeIntent(JSON.stringify({ type: "_ui_render", ...takeUiSnapshot() }));
  }
  window.addEventListener("resize", onUiResize);
  window.visualViewport?.addEventListener("resize", onUiResize);
  window.visualViewport?.addEventListener("scroll", onUiResize);
  function onUiEvent(message) {
    if (document.visibilityState !== "visible" || !document.hasFocus()) return;
    const surface = getComputedStyle(host);
    if (host.style.cssText !== hostStyle || !host.matches(":popover-open") ||
        surface.visibility !== "visible" || surface.opacity !== "1" ||
        surface.transform !== "none" || surface.filter !== "none" ||
        surface.clipPath !== "none" || surface.maskImage !== "none" ||
        surface.scale !== "none" || surface.rotate !== "none" || surface.translate !== "none") return;
    const node = uiNodes.get(message.target);
    // A dismissed iframe may retain browser focus. Its trusted shortcut keys must
    // reopen it; hidden controls still cannot submit text or activate actions.
    if (!node || !shadow.contains(node) ||
        node.closest("[hidden]") && !(node === hud && message.event.startsWith("key"))) return;
    hudInput.value = String(message.value || "");
    if (message.event === "input") return;
    const EventType = message.event.startsWith("key") ? KeyboardEvent : message.pointerType ? PointerEvent : MouseEvent;
    const frame = uiFrame.getBoundingClientRect();
    uiEvent = new EventType(message.event, { ...message, clientX: frame.left + (message.clientX || 0),
      clientY: frame.top + (message.clientY || 0),
      bubbles: !["mouseenter", "mouseleave"].includes(message.event), cancelable: true });
    if (message.event === "mousemove") cursorOverHud = true;
    try { node.dispatchEvent(uiEvent); } finally { uiEvent = null; }
  }


  // System fonts only. Private paper and controls never enter the website DOM.
  const style = document.createElement("style");
  style.textContent = `
    :host{--paper:#fffaf0;--ink:#292b27;--muted:#766f63;--accent:#bd3926;--rule:#d9ccba;color-scheme:light}
    *{box-sizing:border-box} [hidden]{display:none!important}
    button,input{font:inherit} button{cursor:pointer;color:inherit}
    button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
    button:disabled{opacity:.4;cursor:default}
    .hud-shell,.lens-card{position:relative;width:100%;background:var(--paper);color:var(--ink);font:18px/1.5 Georgia,serif;border:1px solid var(--rule);border-top:2px solid var(--accent);box-shadow:0 8px 28px #0002}
    .hud-shell{padding:20px 22px 16px;max-height:var(--hg-max-height);overflow:auto;scrollbar-width:thin;clip-path:polygon(0 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%)}
    .hud-shell.entering{animation:rise .38s cubic-bezier(.2,.8,.2,1) both}
    .note-head{display:flex;gap:12px;align-items:flex-start;padding-right:20px}
    .folio{font:italic 36px/1 Georgia,serif;color:var(--accent)}
    .target-name{font:11px/1.5 "Courier New",monospace;color:var(--accent);overflow-wrap:anywhere;flex:1}
    .source{display:block;color:var(--muted);font-size:10px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .note-close{position:absolute;right:8px;top:8px}
    .icon-btn{display:inline-grid;place-items:center;width:32px;height:32px;flex-shrink:0;border:0;background:transparent;padding:7px;color:var(--muted)}
    .icon-btn:hover,.icon-btn[aria-pressed=true]{color:var(--accent);background:#bc392610}
    .icon-btn svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
    .note-tools{display:flex;flex-wrap:wrap;align-items:center;gap:3px;margin-top:16px;padding-top:9px;border-top:1px solid var(--rule)}
    .note-tools .spacer{flex:1}
    .hud-reply{max-height:min(430px,calc(var(--hg-max-height) - 200px));overflow:auto;scrollbar-width:thin;overflow-wrap:anywhere;user-select:text}
    .question{font:italic 17px/1.5 Georgia,serif;border-bottom:1px solid var(--rule);padding-bottom:12px;margin:20px 0 14px}
    .answer{white-space:pre-wrap;font:19px/1.5 Georgia,serif;margin:0 0 10px}
    .answer.streaming:after{content:"";display:inline-block;height:17px;width:1px;background:var(--accent);margin-left:4px;animation:blink 1s steps(1) infinite}
    .request{margin-bottom:18px}.request:last-child{margin-bottom:0}
    .error{font:14px/1.5 "Courier New",monospace;color:var(--accent);white-space:pre-wrap;margin:12px 0}
    .word-btn{border:0;background:transparent;border-bottom:1px solid var(--accent);padding:4px 0;margin:8px 18px 4px 0;color:var(--accent);font:16px Georgia,serif;min-height:32px}
    .hud-input-row{display:flex;align-items:center;border-bottom:1px solid var(--accent);margin-top:16px;gap:5px}
    .hud-input{min-width:0;width:100%;border:0;background:transparent;padding:8px 0;color:var(--ink);font:italic 18px/1.4 Georgia,serif}
    .capture{display:flex;align-items:center;gap:12px;color:var(--accent);font:italic 19px Georgia,serif}
    .ink-pulse{display:inline-flex;align-items:center;gap:3px;height:24px}
    .ink-pulse i{display:block;background:var(--accent);width:2px;height:8px;animation:breath 1s ease-in-out infinite alternate}
    .ink-pulse i:nth-child(2){height:20px;animation-delay:-.4s}.ink-pulse i:nth-child(3){height:14px;animation-delay:-.7s}
    .capture.pending .ink-pulse i{height:2px;animation:blink 1.3s infinite}
    .capture.disconnected .ink-pulse{display:none}
    .queue-count{font:12px "Courier New",monospace;color:var(--accent);margin-left:auto}
    .unread-button{width:42px;height:42px;border:0;background:var(--paper);color:var(--accent);font:italic 24px Georgia,serif;border-bottom:2px solid var(--accent);box-shadow:0 2px 12px #0002}
    .index-list{display:flex;flex-direction:column;gap:0;margin-top:12px;max-height:calc(var(--hg-max-height) - 160px);overflow:auto}
    .index-item{display:flex;align-items:center;text-align:left;gap:12px;border:0;border-bottom:1px solid var(--rule);background:transparent;padding:12px 0;color:var(--ink);font:italic 18px/1.4 Georgia,serif}
    .index-item .folio{font-size:23px}.index-item.unread:after{content:"";width:5px;height:5px;transform:rotate(45deg);background:var(--accent);margin-left:auto;flex-shrink:0}
    .expired{color:var(--muted)}
    .confirmation{padding:22px;position:relative;background:var(--paper);border-top:2px solid var(--accent);color:var(--ink);font:21px/1.4 Georgia,serif}
    .confirmation h2{font:inherit;margin:0 0 18px;overflow-wrap:anywhere}
    .confirmation button{font:17px Georgia,serif;min-height:40px;padding:8px 15px;border:0;background:transparent;color:var(--ink)}
    .confirmation button:first-of-type{background:var(--accent);color:var(--paper);margin-right:14px}
    .lens-card{padding:14px 20px;text-align:left;display:flex;gap:16px;margin-bottom:8px;font:17px Georgia,serif}
    .lens-card.primary{border-left:2px solid var(--accent)}.dwell-bar{position:absolute;bottom:0;left:0;height:2px;background:var(--accent);width:0}
    .pin-box{position:fixed;pointer-events:none;overflow:hidden;color:inherit}
    .proof-corner{position:absolute;width:23px;height:9px;border:solid currentColor;border-width:1.5px 0 0 1.5px;filter:drop-shadow(0 0 1px #fffaf0)}
    .proof-corner.top-left{left:0;top:0}.proof-corner.top-right{right:0;top:0;transform:scaleX(-1)}
    .proof-corner.bottom-right{right:0;bottom:0;transform:scale(-1)}.proof-corner.bottom-left{left:0;bottom:0;transform:scaleY(-1)}
    .spotlight{position:fixed;pointer-events:none;border:1px dashed #c33d2670;border-radius:45%;transform:translate(-50%,-50%)}
    @keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
    @keyframes breath{to{transform:scaleY(.4)}}@keyframes blink{50%{opacity:.25}}
    .errata-dark{--paper:#26312c;--ink:#f1ecdf;--muted:#b4b6a8;--accent:#ff8b70;--rule:#495448;color-scheme:dark}
    @media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
    .hud-shell.capturing{padding:14px 80px 14px 16px}
    .capturing .note-head,.capturing .hud-reply,.capturing .hud-input-row,.capturing .note-tools>*{display:none}
    .capturing .note-tools{position:absolute;right:36px;top:7px;margin:0;padding:0;border:0}
    .capturing .note-tools #hg-mic-btn{display:inline-grid}
  `;
  shadow.appendChild(style);
  visualShadow.appendChild(style.cloneNode(true));
  const spotlight = document.createElement("div");
  spotlight.className = "spotlight";
  spotlight.style.opacity = "0";
  visualShadow.appendChild(spotlight);
  const pinsLayer = document.createElement("div");
  visualShadow.appendChild(pinsLayer);
  const svgLeaders = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svgLeaders.setAttribute("style", "position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;fill:none;stroke:#c33d26;stroke-width:1.3");
  visualShadow.appendChild(svgLeaders);
  const lensLayer = document.createElement("div");
  shadow.appendChild(lensLayer);
  const hud = document.createElement("section");
  hud.className = "hud-shell";
  hud.setAttribute("aria-label", "Errata note");
  hud.hidden = true;
  hud.innerHTML = `
    <header class="note-head"><span class="folio" id="hg-folio"></span><div class="target-name" id="hg-target-name"></div></header>
    <button class="icon-btn note-close" id="hg-close" aria-label="Dismiss note"></button>
    <div class="capture" id="hg-capture" hidden><span class="ink-pulse" aria-hidden="true"><i></i><i></i><i></i></span><span id="hg-lock-label"></span></div>
    <div class="hud-reply" id="hg-reply" style="display:none"></div>
    <div class="index-list" id="hg-index" hidden></div>
    <div class="hud-input-row" id="hg-compose" hidden><input class="hud-input" id="hg-input" aria-label="Question about pointed source" autocomplete="off" spellcheck="true"><button class="icon-btn" id="hg-send" aria-label="Send question"></button></div>
    <footer class="note-tools">
      <button class="icon-btn" id="hg-index-btn" aria-label="Recall answers (Q)"></button>
      <button class="icon-btn" id="hg-new" aria-label="New question at pointer"></button>
      <button class="icon-btn" id="hg-followup" aria-label="Follow up on this note"></button>
      <span class="spacer"></span><span class="queue-count" id="hg-queue"></span>
      <button class="icon-btn" id="hg-speech" aria-label="Read answer aloud"></button>
      <button class="icon-btn" id="hg-stop-speech" aria-label="Stop reading aloud"></button>
      <button class="icon-btn" id="hg-auto-speech" aria-label="Automatically read completed answers" aria-pressed="false"></button>
      <button class="icon-btn" id="hg-mic-btn" aria-label="Speak question (hold Space)"></button>
      <button class="icon-btn" id="hg-move" aria-label="Move note to opposite side"></button>
    </footer>`;
  shadow.appendChild(hud);
  const unreadMark = document.createElement("button");
  unreadMark.className = "unread-button";
  unreadMark.setAttribute("aria-label", "Recall unread answers");
  unreadMark.hidden = true;
  shadow.appendChild(unreadMark);
  const targetName = hud.querySelector("#hg-target-name");
  const lockLabel = hud.querySelector("#hg-lock-label");
  const hudInput = hud.querySelector("#hg-input");
  const hudSend = hud.querySelector("#hg-send");
  const hudReply = hud.querySelector("#hg-reply");
  const compose = hud.querySelector("#hg-compose");
  const captureStatus = hud.querySelector("#hg-capture");
  const indexList = hud.querySelector("#hg-index");
  const folio = hud.querySelector("#hg-folio");
  const icons = {
    close:"M4 4l10 10M14 4L4 14", index:"M3 4h12M3 9h12M3 14h8", new:"M9 3v12M3 9h12",
    followup:"M7 4L3 8l4 4M3 8h8a4 4 0 0 1 4 4v3", send:"M3 9h12M10 4l5 5-5 5",
    speech:"M3 7h3l4-4v12l-4-4H3zM13 5q5 4 0 8", auto:"M3 6l3-3 3 3M6 3v9a3 3 0 0 0 6 0V8M10 10l2-2 2 2",
    mic:"M7 3a2 2 0 0 1 4 0v6a2 2 0 0 1-4 0zM4 8v1a5 5 0 0 0 10 0V8M9 14v3M6 17h6",
    stop:"M4 4h10v10H4z",
    move:"M2 9h14M5 5L1 9l4 4M13 5l4 4-4 4", expired:"M4 7V5a5 5 0 0 1 10 0v2M3 7h12v9H3z"
  };
  function icon(button, name) {
    button.innerHTML = `<svg viewBox="0 0 18 18" aria-hidden="true"><path d="${icons[name]}"/></svg>`;
  }
  for (const [id, name] of Object.entries({"hg-close":"close","hg-index-btn":"index","hg-new":"new","hg-followup":"followup","hg-send":"send","hg-speech":"speech","hg-stop-speech":"stop","hg-auto-speech":"auto","hg-mic-btn":"mic","hg-move":"move"}))
    icon(hud.querySelector(`#${id}`), name);
  hudInput.value = prevInputVal;
  let noteOpen = false, indexOpen = false, composeOpen = false, noteItem = "";
  let noteSide = 0, frameHeight = 1, cursorOverHud = false, collapseTimer = null;
  let focusInput = false, micReady = false, localError = "";
  const itemAnchors = new Map(), requestAnchors = new Map();
  let pendingAnchor = null;
  function control(action, itemId = "", requestId = "") {
    return _emit({type:"inbox", action, item_id:itemId, request_id:requestId});
  }
  function selectedNote() { return inbox?.items.find(item => item.item_id === noteItem); }
  function openComposer(followup = false) {
    noteOpen = true; indexOpen = false; composeOpen = true; localError = "";
    if (followup && noteItem) control("select", noteItem);
    else { noteItem = ""; control("new"); setTargetLocked(true); }
    pendingAnchor = {node:lockedNode};
    focusInput = true;
    renderNote();
  }
  function dismissNote() {
    if (isListening) cancelListening();
    noteOpen = false; composeOpen = false; indexOpen = false; localError = "";
    clearTimeout(collapseTimer);
    state.lensActive = false;
    state.lensCandidates = [];
    state.choosePending = false;
    lensLayer.replaceChildren();
    clearActionConfirmation();
    setTargetLocked(false);
    if (inbox?.selected_item_id) control("new");
    renderNote();
  }
  function recallNotes() {
    noteOpen = true; indexOpen = true; composeOpen = false; localError = "";
    renderNote();
  }
  hud.querySelector("#hg-close").addEventListener("click", e => { if (trustedUi(e)) dismissNote(); });
  unreadMark.addEventListener("click", e => { if (trustedUi(e)) recallNotes(); });
  hud.querySelector("#hg-index-btn").addEventListener("click", e => { if (trustedUi(e)) recallNotes(); });
  hud.querySelector("#hg-new").addEventListener("click", e => { if (trustedUi(e)) openComposer(); });
  hud.querySelector("#hg-followup").addEventListener("click", e => { if (trustedUi(e)) openComposer(true); });
  hud.querySelector("#hg-speech").addEventListener("click", e => {
    if (trustedUi(e) && noteItem) control("speak", noteItem);
  });
  hud.querySelector("#hg-auto-speech").addEventListener("click", e => { if (trustedUi(e)) control("auto_speak"); });
  hud.querySelector("#hg-stop-speech").addEventListener("click", e => { if (trustedUi(e)) control("stop_speaking"); });
  hud.querySelector("#hg-move").addEventListener("click", e => {
    if (!trustedUi(e)) return;
    const r = uiFrame.getBoundingClientRect(), v = window.visualViewport;
    noteSide = r.left + r.width / 2 < (v?.offsetLeft || 0) + (v?.width || innerWidth) / 2 ? 1 : -1;
    positionNote();
  });
  function syncModeUI() { updateSpotlightPosition(state.pointerX, state.pointerY); }
  function pageIsDark() {
    const node = (noteItem ? itemAnchors.get(noteItem) : pendingAnchor)?.node;
    for (let el = node || document.body; el; el = el.parentElement) {
      const color = getComputedStyle(el).backgroundColor;
      const parts = color?.match(/[\d.]+/g)?.map(Number);
      if (parts?.length >= 3 && (parts.length < 4 || parts[3] > .5))
        return parts[0] * .2126 + parts[1] * .7152 + parts[2] * .0722 < 110;
    }
    return false;
  }
  let lastPlacement = "";
  function positionNote() {
    const visible = noteOpen || !!confirmation || state.lensActive;
    const unread = !!inbox?.items.some(item => item.unread);
    const active = visible || unread;
    const view = window.visualViewport;
    const minX = (view?.offsetLeft || 0) + 16, minY = (view?.offsetTop || 0) + 16;
    const maxX = minX + (view?.width || innerWidth) - 32;
    const maxY = minY + (view?.height || innerHeight) - 32;
    const width = visible ? Math.max(1, Math.min(isListening ? 250 : 344, maxX - minX)) : 42;
    const height = visible ? frameHeight : 42;
    let x = maxX - width, y = minY + 8, anchor = null;
    const saved = noteItem ? itemAnchors.get(noteItem) : pendingAnchor;
    const node = saved?.node;
    if (node?.isConnected && rendered(node)) {
      const r = node.getBoundingClientRect();
      if (r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth) anchor = r;
    } else if (confirmation || state.lensActive) anchor = sourceRect();
    if (saved?.snapshotId === activeSnapshot?.id) anchor = sourceRect() || anchor;
    if (anchor) {
      anchor = {left:Math.max(minX - 16, anchor.left), top:Math.max(minY - 16, anchor.top),
        right:Math.min(maxX + 16, anchor.right), bottom:Math.min(maxY + 16, anchor.bottom)};
      if (anchor.right <= anchor.left || anchor.bottom <= anchor.top) anchor = null;
    }
    if (visible && anchor) {
      const gap = 22;
      const right = {x:anchor.right + gap, y:anchor.top - 8};
      const left = {x:anchor.left - width - gap, y:anchor.top - 8};
      if (noteSide < 0 && left.x >= minX) ({x,y} = left);
      else if (noteSide > 0 && right.x + width < maxX) ({x,y} = right);
      else if (right.x + width <= maxX) ({x,y} = right);
      else if (left.x >= minX) ({x,y} = left);
      else {
        x = noteSide < 0 ? minX : maxX - width;
        y = anchor.bottom + 18;
        if (y + height > maxY && anchor.top - height - 18 >= minY)
          y = anchor.top - height - 18;
        else if (y + height > maxY) y = maxY - height;
      }
    }
    if (noteSide) x = noteSide < 0 ? minX : maxX - width;
    x = Math.max(minX, Math.min(x, maxX - width));
    for (let el = document.elementFromPoint(x + width / 2, minY); el && el !== host; el = el.parentElement) {
      const style = getComputedStyle(el), r = el.getBoundingClientRect();
      if (["fixed","sticky"].includes(style.position) && r.top <= minY && r.bottom < minY + (maxY - minY) / 3)
        y = Math.max(y, r.bottom + 12);
    }
    y = Math.max(minY, Math.min(y, maxY - height));
    const placement = `${x},${y},${width},${height},${active},${anchor?.left},${anchor?.top},${anchor?.right},${anchor?.bottom}`;
    if (placement === lastPlacement) return;
    lastPlacement = placement;
    uiFrame.style.left = `${x}px`; uiFrame.style.top = `${y}px`;
    uiFrame.style.width = `${active ? width : 1}px`; uiFrame.style.height = `${active ? height : 1}px`;
    uiFrame.style.opacity = active ? "1" : "0";
    uiFrame.style.pointerEvents = active ? "auto" : "none";
    svgLeaders.replaceChildren();
    if (visible && anchor && !indexOpen) {
      const ax = x >= anchor.right ? anchor.right : x + width <= anchor.left ? anchor.left : Math.max(anchor.left, Math.min(x + width / 2, anchor.right));
      const ay = Math.max(anchor.top, Math.min(y + 30, anchor.bottom));
      const bx = ax <= x ? x : ax >= x + width ? x + width : ax;
      const by = y > anchor.bottom ? y : y + height < anchor.top ? y + height : y + 30;
      const path = document.createElementNS("http://www.w3.org/2000/svg","path");
      path.setAttribute("d", `M${ax},${ay} C${(ax+bx)/2},${ay} ${(ax+bx)/2},${by} ${bx},${by}`);
      svgLeaders.appendChild(path);
    }
  }
  function setTargetLocked(locked) {
    if (locked && typeof state.pointerX !== "number") return;
    state.armed = locked;
    lockedNode = locked ? cursorRefs.get(cursorHistory.at(-1)?.id) || null : null;
    state.lockedX = locked ? state.pointerX : null;
    state.lockedY = locked ? state.pointerY : null;
    if (locked) state.armedAt = Date.now() / 1000;
    updateSpotlightPosition(state.pointerX, state.pointerY);
  }
  function updateSpotlightPosition(x, y) {
    spotlight.style.opacity = state.mode === "simulated" && (noteOpen || isListening) && typeof x === "number" ? "1" : "0";
    const diameter = Math.max(state.sigmaPx * 1.45, 110);
    spotlight.style.cssText += `;width:${diameter}px;height:${diameter}px;left:${x}px;top:${y}px`;
  }
  function onWindowMouseMove(e) {
    const r = uiFrame.getBoundingClientRect();
    cursorOverHud = uiFrame.style.pointerEvents !== "none" && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
    if (!cursorOverHud) recordPoint(e.clientX, e.clientY);
  }
  window.addEventListener("mousemove", onWindowMouseMove, {passive:true});

  // Identities stay in this closure: a selector is metadata, never a historical lookup.
  const cursorIds = new WeakMap();
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
  let inbox = null;
  let inboxRevision = -1;
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
    let field = el && el.closest("input,textarea,select,[contenteditable]");
    for (let host = el?.getRootNode?.().host; !field && host; host = host.getRootNode?.().host)
      field = host.closest("input,textarea,select,[contenteditable]");
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
        typeof info.action_id !== "string" || !info.action_id)
      return { ok: false, error: "Stale confirmation" };
    noteItem = "";
    pendingAnchor = null;
    const card = document.createElement("section");
    card.className = "confirmation";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-label", "Confirm page action");
    const title = document.createElement("h2");
    title.textContent = String(info.label || "");
    card.appendChild(title);
    const pending = { card, actionId: info.action_id, resolutionId: info.resolution_id };
    confirmation = pending;
    for (const approved of [true, false]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = approved ? "Confirm" : "Cancel";
      button.addEventListener("click", event => {
        if (!trustedUi(event) || event.button !== 0 || event.detail < 1 ||
            event.pointerType && event.pointerType !== "mouse" ||
            confirmation !== pending || !activeSnapshot ||
            activeSnapshot.resolutionId !== pending.resolutionId) return;
        event.stopPropagation();
        clearActionConfirmation();
        _emit({ type: "confirm_action", action_id: pending.actionId,
          resolution_id: pending.resolutionId, approved });
      });
      card.appendChild(button);
    }
    shadow.appendChild(card);
    noteOpen = true;
    renderNote();
    return { ok: true };
  }
  function showPlainMessage(text) {
    localError = String(text);
    noteOpen = true;
    indexOpen = false;
    renderNote();
  }
  function renderNote() {
    const item = selectedNote();
    hud.hidden = !noteOpen || !!confirmation;
    hud.classList.toggle("capturing", isListening);
    const unread = inbox?.items.filter(i => i.unread).length || 0;
    unreadMark.hidden = noteOpen || !!confirmation || state.lensActive || !unread;
    unreadMark.textContent = String(unread || "");
    pinsLayer.style.display = noteOpen || isListening || !!confirmation || state.lensActive ? "" : "none";
    svgLeaders.style.display = pinsLayer.style.display;
    if (!noteOpen && !isListening && !confirmation && !state.lensActive) {
      stopTrackingPins();
      pinsLayer.replaceChildren();
    }
    compose.hidden = !composeOpen;
    indexList.hidden = !indexOpen;
    hudReply.style.display = indexOpen || !item && !localError && !prevReplyText ? "none" : "block";
    const disconnected = inbox?.session_connected === false;
    captureStatus.hidden = !isListening && !["recording","transcribing"].includes(inbox?.capture_state) && !disconnected;
    captureStatus.classList.toggle("pending", !micReady);
    captureStatus.classList.toggle("disconnected", disconnected && !isListening);
    lockLabel.textContent = micReady ? "Listening" : disconnected ? "Disconnected" : "";
    folio.textContent = item ? String(item.capture_order) : "";
    targetName.replaceChildren();
    targetName.textContent = item?.target_label || (composeOpen ? state.hoveredCandidate?.label : "") || "";
    if (item?.source_url) {
      const source = document.createElement("span");
      source.className = "source";
      try { source.textContent = new URL(item.source_url).hostname; } catch (_) { source.textContent = ""; }
      source.setAttribute("title", item.source_url);
      targetName.appendChild(source);
    }
    hud.querySelector("#hg-followup").disabled = !item;
    hud.querySelector("#hg-followup").setAttribute("aria-pressed", String(composeOpen && !!item));
    hudInput.setAttribute("aria-label", composeOpen && item ? `Follow up on ${item.target_label}` : "Question about pointed source");
    hudMic.setAttribute("aria-label", isListening ? "Stop recording; 30-second limit" : "Speak question (hold Space)");
    hud.querySelector("#hg-speech").disabled = !item?.conversation.some(run => run.text);
    hud.querySelector("#hg-auto-speech").setAttribute("aria-pressed", String(!!inbox?.auto_speak));
    hud.querySelector("#hg-auto-speech").setAttribute("aria-label", inbox?.speech_error || "Automatically read completed answers");
    hud.querySelector("#hg-queue").textContent = String(item?.conversation.at(-1)?.queue_position || "") || "";
    hudReply.replaceChildren();
    const textNode = (tag, className, text, parent = hudReply) => {
      const node = document.createElement(tag); node.className = className; node.textContent = text;
      parent.appendChild(node); return node;
    };
    const button = (label, action, itemId = "", requestId = "", parent = hudReply) => {
      const b = textNode("button", "word-btn", label, parent);
      b.type = "button";
      b.addEventListener("click", e => { if (trustedUi(e)) control(action, itemId, requestId); });
    };
    if (localError) textNode("p", "error", localError);
    else if (item && !indexOpen) {
      for (const run of item.conversation) {
        const section = textNode("section", "request", "");
        section.setAttribute("aria-label", run.status);
        if (run.utterance) textNode("p", "question", run.utterance, section);
        if (run.text) textNode("p", `answer${run.status === "streaming" ? " streaming" : ""}`, run.text, section);
        else if (["thinking","queued","transcribing"].includes(run.status)) {
          const pulse = textNode("span", "ink-pulse", "", section);
          pulse.setAttribute("aria-label", run.status);
          pulse.innerHTML = "<i></i><i></i><i></i>";
        }
        if (run.error) textNode("p", "error", run.error, section);
        if (["failed","interrupted"].includes(run.status)) {
          button("Retry","retry",item.item_id,run.request_id,section);
          button("Skip","skip",item.item_id,run.request_id,section);
        }
      }
      const expired = textNode("span", "icon-btn expired", "");
      expired.setAttribute("aria-label", item.action_state || "Actions expired; point again to act");
      icon(expired, "expired");
    } else if (prevReplyText && !indexOpen && !localError) textNode("p", "answer", prevReplyText);
    if (inbox?.speech_error) textNode("p", "error", inbox.speech_error);
    if (inbox?.paused) button("Resume", "resume");
    indexList.replaceChildren();
    if (indexOpen) for (const entry of inbox?.items || []) {
      const b = textNode("button", `index-item${entry.unread ? " unread" : ""}`, "", indexList);
      b.type = "button";
      textNode("span", "folio", String(entry.capture_order), b);
      textNode("span", "", entry.target_label, b);
      b.setAttribute("aria-label", `${entry.target_label}${entry.unread ? ", unread" : ""}`);
      b.addEventListener("click", e => {
        if (!trustedUi(e)) return;
        noteItem = entry.item_id; indexOpen = false; noteSide = 0; localError = "";
        control("select", noteItem); renderNote();
      });
    }
    positionNote();
  }
  function renderInbox(event) {
    if (event.revision <= inboxRevision) return;
    const previous = inbox;
    inboxRevision = event.revision;
    inbox = event;
    if (event.session_connected === false) cancelListening();
    const newest = event.items.at(-1);
    if (newest && !previous?.items.some(i => i.item_id === newest.item_id)) {
      const status = newest.conversation.at(-1)?.status;
      if (!indexOpen && !composeOpen && !["complete","failed","interrupted"].includes(status)) {
        noteItem = newest.item_id; noteOpen = true; noteSide = 0;
        hud.classList.add("entering");
      }
    }
    if (event.selected_item_id && !noteItem) noteItem = event.selected_item_id;
    const last = selectedNote()?.conversation.at(-1);
    if (last && ["complete","failed","interrupted"].includes(last.status) &&
        previous?.items.find(i => i.item_id === noteItem)?.conversation.at(-1)?.status !== last.status) {
      clearTimeout(collapseTimer);
      collapseTimer = setTimeout(() => {
        if (!cursorOverHud && !composeOpen && !indexOpen) { noteOpen = false; renderNote(); }
      }, 12000);
    }
    renderNote();
  }
  function onSessionEvent(event) {
    if (!destroyed && event?.type === "inbox") renderInbox(event);
  }
  function revokeActionAuthority() {
    for (const saved of snapshots.values()) saved.actionRevoked = true;
    clearActionConfirmation();
    state.lensActive = false;
    lensLayer.innerHTML = "";
    cancelListening();
  }
  function onNavigation() {
    activeSnapshot = null;
    snapshots.clear();
    stopTrackingPins();
    pinsLayer.innerHTML = "";
    clearActionConfirmation();
    cancelListening();
  }
  window.addEventListener("pagehide", onNavigation);
  function onCursorScroll() {
    if (!state.armed && !cursorOverHud && typeof state.pointerX === "number")
      rememberHit(hitNode(state.pointerX, state.pointerY));
    positionNote();
  }
  window.addEventListener("scroll", onCursorScroll, { passive: true, capture: true });

  function updateLiveInspector(x, y) {
    const el = state.armed ? lockedNode : hitNode(x, y);
    state.hoveredCandidate = el ? cursorMetadata(el) : null;
    if (composeOpen && !noteItem) targetName.textContent = state.hoveredCandidate?.label || "";
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
      showPlainMessage("Resolver offline. Run /gaze in the Hermes session, then retry.");
      return false;
    }
    if (["submit","record_stop"].includes(intent.type)) {
      pendingAnchor = {node:state.armed ? lockedNode : cursorRefs.get(cursorHistory.at(-1)?.id),
        snapshotId:intent.cursor_context?.snapshot_id};
      requestAnchors.set(intent.id, pendingAnchor);
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
    if (composeOpen && noteItem) {
      return _emit({ type: "followup", item_id: noteItem, utterance: text });
    }
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
      if (current?.available) renderPins([{ ...current, node: cursorRefs.get(current.id), snapshotId: evidence.snapshot_id }]);
    }
    const intent = {
      type: state.mode === "hover" ? "submit" : "resolve",
      utterance: text,
      page_url: location.origin + location.pathname,
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



  function onIntentResult(msg) {
    if (typeof msg === "string") {
      try {
        msg = JSON.parse(msg);
      } catch (_) {
        return;
      }
    }
    if (!msg || typeof msg !== "object") return;
    if (msg.item_id && requestAnchors.has(msg.id)) {
      itemAnchors.set(msg.item_id, requestAnchors.get(msg.id));
      requestAnchors.delete(msg.id);
      noteItem = msg.item_id;
      positionNote();
    }
    if (msg.type === "inbox" || msg.type === "followup") {
      if (!msg.ok) showPlainMessage(msg.error || "Inbox request failed.");
      return;
    }

    if (msg.type === "record_start") {
      if (!msg.ok) {
        isListening = false;
        resetMicUiIdle(msg.error || "Microphone unavailable.");
      } else if (isListening) {
        micReady = true;
        renderNote();
      }
      return;
    }
    if (msg.type === "record_cancel") {
      isListening = false;
      spaceHeld = false;
      resetMicUiIdle(msg.error || "Recording cancelled.");
      return;
    }
    if (msg.type === "record_stop") {
      if (!isListening) resetMicUiIdle(msg.ok ? "" : msg.error || "Recording failed.");
      if (msg.delivery === "one_shot") {
        renderScopeOptions(msg);
        showPlainMessage(msg.explanation || "");
      } else if (!msg.ok) showPlainMessage(msg.error || "Recording failed.");
      return;
    }
    if (msg.type === "confirm_action") {
      if (msg.resolution_id !== state.resolutionId) return;
      if (!msg.ok && msg.error) showPlainMessage(msg.error);
      else dismissNote();
      return;
    }



    if (msg.type === "submit") {
      if (!msg.ok) {
        showPlainMessage(msg.error || "Connect Hermes with /gaze, then retry.");
      } else if (msg.delivery === "session") {
        composeOpen = false;
        hudInput.value = "";
        renderNote();
      } else if (msg.delivery === "one_shot") {
        renderScopeOptions(msg);
        if (msg.mode !== "hover" && Array.isArray(msg.ranked)) renderPins(msg.ranked);
        showPlainMessage(msg.explanation || msg.text || msg.answer || "");
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
      if (msg.scope_id !== state.selectedScopeId || msg.resolution_id !== state.resolutionId) return;
      showPlainMessage(msg.explanation || msg.error || _pendingExplainFallback || "Explanation unavailable.");
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


  const TALK_KEY = "Space";
  const hudMic = hud.querySelector("#hg-mic-btn");
  let isListening = false;
  let spaceHeld = false;

  function resetMicUiIdle(error) {
    micReady = false;
    if (error) localError = error;
    renderNote();
  }

  function startListening() {
    if (isListening || document.visibilityState !== "visible" || !document.hasFocus()) return;
    isListening = true;
    noteOpen = true;
    localError = "";
    pendingAnchor = {node:state.armed ? lockedNode : cursorRefs.get(cursorHistory.at(-1)?.id)};
    renderNote();
    if (!_emit({ type: "record_start" })) {
      isListening = false;
      resetMicUiIdle("Microphone offline.");
    }
  }

  function stopListening() {
    if (!isListening) return;
    isListening = false;
    resetMicUiIdle();
    // Freeze evidence at release, before transcription and before routing can change it.
    const locked = state.armed && state.lockedX !== null;
    const x = locked ? state.lockedX : state.pointerX, y = locked ? state.lockedY : state.pointerY;
    _emit({ type: "record_stop", mode: state.mode, item_id: inbox?.selected_item_id || "",
      ...(state.mode === "hover" ? { cursor_context: captureCursorContext() } : {
        page_url: location.origin + location.pathname,
        pointer: { x_vp: x, y_vp: y, scroll_x: scrollX, scroll_y: scrollY },
        fixations: state.ringBuffer.slice(-25),
        candidates: extractCandidatesNear(x, y, state.candidateRadiusPx || 380) }) });
  }

  function cancelListening() {
    if (!isListening) return;
    isListening = false;
    spaceHeld = false;
    _emit({ type: "record_cancel" });
    resetMicUiIdle();
  }

  hudMic.addEventListener("click", (e) => {
    if (!trustedUi(e)) return;
    e.currentTarget.blur();
    if (isListening) stopListening();
    else startListening();
  });


  hudSend.addEventListener("click", (e) => {
    if (!trustedUi(e)) return;
    submitQuestion();
  });

  hudInput.addEventListener("keydown", (e) => {
    if (!trustedUi(e)) return;
    e.stopPropagation();
    if (e.key === "Enter") {
      e.preventDefault();
      submitQuestion();
    } else if (e.key === "Escape") {
      dismissNote();
    }
  });

  function submitQuestion() {
    if (!emitResolve(hudInput.value)) return;
    composeOpen = false;
    hudInput.value = "";
    setTargetLocked(false);
    renderNote();
  }

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
    if (!trustedUi(e) || document.visibilityState !== "visible") return;
    if (isEditableTarget(e)) return;
    if (!e.altKey && !e.metaKey && !e.ctrlKey && e.code === "KeyQ") {
      e.preventDefault();
      if (!e.repeat) recallNotes();
      return;
    }
    if (e.code === TALK_KEY && !e.altKey && !e.metaKey && !e.ctrlKey) {
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
      if (!e.repeat) openComposer();
    } else if (state.lensActive && /^Digit[1-9]$/.test(e.code)) {
      const idx = parseInt(e.code.replace("Digit", ""), 10) - 1;
      if (idx >= 0 && idx < state.lensCandidates.length) {
        e.preventDefault();
        selectLensCandidate(idx, "key");
      }
    } else if (e.key === "Escape") {
      dismissNote();
    }
  }

  function onWindowKeyUp(e) {
    if (trustedUi(e) && e.code === TALK_KEY && spaceHeld) {
      e.preventDefault();
      e.stopPropagation();
      spaceHeld = false;
      stopListening();
    }
  }

  function onWindowBlur() {
    cancelListening();
  }

  window.addEventListener("keydown", onWindowKeyDown, { capture: true });
  window.addEventListener("keyup", onWindowKeyUp, { capture: true });
  shadow.addEventListener("keydown", onWindowKeyDown);
  shadow.addEventListener("keyup", onWindowKeyUp);
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
    pinsLayer.innerHTML = "";
    state.scopes = [];
    state.selectedScopeId = null;
    activeSnapshot = null;
    snapshots.clear();
    clearActionConfirmation();
    svgLeaders.innerHTML = "";
    lensLayer.innerHTML = "";
    state.lensActive = false;
    state.lensCandidates = [];
    setTargetLocked(false);
    dismissNote();
  }

  function showHudMessage(text) { showPlainMessage(text); }

  let livePins = [];
  let pinFrame = null;
  function stopTrackingPins() {
    if (pinFrame !== null) cancelAnimationFrame(pinFrame);
    pinFrame = null;
    livePins = [];
  }
  function sourceRect() {
    let union = null;
    for (const { candidate, box, rect } of livePins) {
      if (!rect || box.style.display === "none" || !candidate.node.isConnected ||
          !snapshots.has(candidate.snapshotId) || candidate.resolutionId &&
          (activeSnapshot?.id !== candidate.snapshotId || activeSnapshot.resolutionId !== candidate.resolutionId)) continue;
      if (!union) union = { ...rect };
      else {
        union.left = Math.min(union.left, rect.left);
        union.top = Math.min(union.top, rect.top);
        union.right = Math.max(union.right, rect.right);
        union.bottom = Math.max(union.bottom, rect.bottom);
      }
    }
    return union ? { ...union, width: union.right - union.left, height: union.bottom - union.top } : null;
  }
  function refreshPins() {
    pinFrame = null;
    livePins = livePins.filter(pin => {
      const { candidate, box } = pin;
      const { node, snapshotId, resolutionId } = candidate;
      if (destroyed || !node.isConnected || !snapshots.has(snapshotId) ||
          resolutionId && (activeSnapshot?.id !== snapshotId || activeSnapshot.resolutionId !== resolutionId)) {
        box.remove();
        return false;
      }
      const rect = node.getBoundingClientRect();
      let left = Math.max(0, rect.left), top = Math.max(0, rect.top);
      let right = Math.min(window.innerWidth, rect.left + rect.width);
      let bottom = Math.min(window.innerHeight, rect.top + rect.height);
      for (let parent = node.parentElement; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        const clipX = /auto|scroll|hidden|clip/.test(style.overflowX);
        const clipY = /auto|scroll|hidden|clip/.test(style.overflowY);
        if (!clipX && !clipY) continue;
        const r = parent.getBoundingClientRect();
        if (clipX) { left = Math.max(left, r.left); right = Math.min(right, r.left + r.width); }
        if (clipY) { top = Math.max(top, r.top); bottom = Math.min(bottom, r.top + r.height); }
      }
      box.style.display = right > left && bottom > top && rendered(node) && !sensitive(node) ? "" : "none";
      pin.rect = box.style.display === "none" ? null : { left, top, right, bottom };
      box.style.left = `${left}px`;
      box.style.top = `${top}px`;
      box.style.width = `${Math.max(0, right - left)}px`;
      box.style.height = `${Math.max(0, bottom - top)}px`;
      return true;
    });
    positionNote();
    if (livePins.length) pinFrame = requestAnimationFrame(refreshPins);
  }

  function renderPins(candidates, messageHtml) {
    stopTrackingPins();
    pinsLayer.innerHTML = "";
    pinsLayer.style.display = "";
    lensLayer.innerHTML = "";
    state.lensActive = false;

    for (let cand of candidates || []) {
      const entry = !cand.node && activeSnapshot
        ? snapshotEntry(activeSnapshot.id, activeSnapshot.resolutionId, cand.id) : null;
      if (entry) cand = { ...cand, snapshotId: activeSnapshot.id, resolutionId: activeSnapshot.resolutionId };
      const nodes = cand.members || entry?.members || [cand.node || entry?.node || null];
      for (const node of nodes) {
        if (!node && (!Array.isArray(cand.rect_vp) || cand.rect_vp.length !== 4 || !cand.rect_vp.every(Number.isFinite))) continue;
        const box = document.createElement("div");
        box.className = "pin-box";
        box.setAttribute("aria-hidden", "true");
        for (const corner of ["top-left", "top-right", "bottom-left", "bottom-right"]) {
          const mark = document.createElement("span");
          mark.className = `proof-corner ${corner}`;
          box.appendChild(mark);
        }
        pinsLayer.appendChild(box);
        if (node) livePins.push({ candidate: { ...cand, node }, box, rect: null });
        else {
          const [x, y, w, h] = cand.rect_vp;
          const left = Math.max(0, x), top = Math.max(0, y);
          const right = Math.min(window.innerWidth, x + w), bottom = Math.min(window.innerHeight, y + h);
          box.style.display = right > left && bottom > top ? "" : "none";
          box.style.left = `${left}px`;
          box.style.top = `${top}px`;
          box.style.width = `${Math.max(0, right - left)}px`;
          box.style.height = `${Math.max(0, bottom - top)}px`;
        }
      }
    }
    refreshPins();

    if (messageHtml) {
      showHudMessage(messageHtml);
    }
  }

  function renderSemanticLens(candidates, promptMessage, resolutionId) {
    renderPins(candidates);
    state.lensActive = true;
    state.lensCandidates = candidates || [];
    state.resolutionId = resolutionId || 0;

    state.lensCandidates.forEach((cand, idx) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "lens-card open";
      card.setAttribute("aria-label", `Choose ${idx + 1}${cand.label ? `: ${cand.label}` : ""}`);
      const key = document.createElement("span");
      key.className = "lens-key";
      key.textContent = String(idx + 1);
      const title = document.createElement("span");
      title.className = "lens-title";
      title.textContent = cand.label || "";
      const dwellBar = document.createElement("span");
      dwellBar.className = "dwell-bar";
      dwellBar.setAttribute("aria-hidden", "true");
      card.append(key, title, dwellBar);
      let dwellStart = 0;
      let rafId = null;

      function currentLens() {
        return !destroyed && state.lensActive && !state.choosePending &&
          state.resolutionId === (resolutionId || 0) && state.lensCandidates[idx] === cand &&
          lensLayer.contains(card) && document.visibilityState === "visible" && document.hasFocus();
      }
      function tickDwell() {
        rafId = null;
        if (!currentLens()) return;
        const elapsed = performance.now() - dwellStart;
        const pct = Math.min(100, (elapsed / state.dwellMs) * 100);
        if (dwellBar) dwellBar.style.width = `${pct}%`;
        if (pct >= 100) {
          selectLensCandidate(idx, "dwell");
        } else {
          rafId = requestAnimationFrame(tickDwell);
        }
      }

      card.addEventListener("mouseenter", event => {
        if (!trustedUi(event) || !currentLens()) return;
        if (rafId !== null) cancelAnimationFrame(rafId);
        dwellStart = performance.now();
        rafId = requestAnimationFrame(tickDwell);
      });
      card.addEventListener("mouseleave", event => {
        if (!trustedUi(event)) return;
        if (rafId !== null) cancelAnimationFrame(rafId);
        rafId = null;
        dwellBar.style.width = "0%";
      });
      card.addEventListener("click", (e) => {
        if (!trustedUi(e) || !currentLens()) return;
        e.stopPropagation();
        selectLensCandidate(idx, "click");
      });

      lensLayer.appendChild(card);
    });
    renderNote();
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
    uiObserver.disconnect();
    clearTimeout(collapseTimer);
    window.removeEventListener("resize", onUiResize);
    stopTrackingPins();
    activeSnapshot = null;
    snapshots.clear();
    clearActionConfirmation();
    window.removeEventListener("pagehide", onNavigation);
    window.removeEventListener("scroll", onCursorScroll, true);
    window.visualViewport?.removeEventListener("resize", onUiResize);
    window.visualViewport?.removeEventListener("scroll", onUiResize);
    cancelListening();
    window.removeEventListener("mousemove", onWindowMouseMove, { passive: true });
    window.removeEventListener("keydown", onWindowKeyDown, { capture: true });
    window.removeEventListener("keyup", onWindowKeyUp, { capture: true });
    window.removeEventListener("blur", onWindowBlur);
    document.removeEventListener("visibilitychange", onWindowBlur);
    if (host && host.parentNode) {
      host.remove();
    }
  }

  // Initialize spotlight & live inspector immediately on load
  syncModeUI();
  updateLiveInspector(state.pointerX, state.pointerY);

  const api = {
    state,
    uiFrame,
    takeUiSnapshot,
    fitUiFrame,
    onUiEvent,
    getReplyText: () => hudReply.textContent,
    Configure(opts) {
      Object.assign(state, opts || {});
      syncModeUI();
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
    revokeActionAuthority,
    showHudMessage(htmlText) {
      showHudMessage(htmlText);
    },
  };

  window.__HERMES_GAZE_OVERLAY__ = api;
  return api;
})();

