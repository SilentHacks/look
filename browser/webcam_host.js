// Loaded by CDP only, in the tracker window's isolated world. No website runs here.
(async function (opts) {
  "use strict";
  const emit = (type, data = {}) => __hermesGazeIntent(JSON.stringify({type, nonce: opts.nonce, ...data}));
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; };
  const style = make("style");
  style.textContent = `
    :root { color-scheme:light dark; --label:rgba(0,0,0,.86); --secondary:rgba(60,60,67,.72); --tertiary:rgba(60,60,67,.5);
      --accent:#0066d6; --on-accent:#fff; --hover:rgba(0,0,0,.055); --line:rgba(0,0,0,.09); --ground:#e8eaef;
      --wash-a:rgba(120,160,235,.55); --wash-b:rgba(232,190,170,.5); --fill:rgba(250,250,252,.72); --blur:blur(34px) saturate(1.9);
      --edge:rgba(255,255,255,.7); --shadow:0 24px 70px rgba(30,35,60,.18); --dot:#111316; --region:rgba(0,102,214,.5); --blend:multiply; }
    @media (prefers-color-scheme: dark) { :root { --label:rgba(255,255,255,.92); --secondary:rgba(235,235,245,.68); --tertiary:rgba(235,235,245,.42);
      --accent:#4ea1ff; --on-accent:#05121f; --hover:rgba(255,255,255,.08); --line:rgba(255,255,255,.11); --ground:#141518;
      --wash-a:rgba(52,88,160,.5); --wash-b:rgba(120,70,90,.35); --fill:rgba(40,40,44,.66); --blur:blur(34px) saturate(1.7);
      --edge:rgba(255,255,255,.12); --shadow:0 24px 80px rgba(0,0,0,.5); --dot:#fff; --region:rgba(150,200,255,.6); --blend:screen; } }
    * { box-sizing:border-box; }
    html,body { height:100%; margin:0; }
    body { background:var(--ground); color:var(--label); overflow:hidden; -webkit-font-smoothing:antialiased;
      font:15px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif; }
    #wash { position:fixed; inset:-20%; pointer-events:none; transition:opacity .6s ease;
      background:radial-gradient(38% 42% at 30% 30%,var(--wash-a),transparent 70%),radial-gradient(40% 44% at 72% 72%,var(--wash-b),transparent 70%); }
    body.focus #wash { opacity:.28; }
    main { position:fixed; inset:0; display:grid; place-items:center; padding:24px; }
    .glass { background:var(--fill); -webkit-backdrop-filter:var(--blur); backdrop-filter:var(--blur);
      box-shadow:var(--shadow),inset 0 0 0 .5px var(--edge); }
    #card { width:min(480px,100%); max-height:100%; overflow:auto; scrollbar-width:none; border-radius:28px; padding:30px 32px 26px;
      animation:rise .42s cubic-bezier(.2,.8,.2,1); }
    @keyframes rise { from { opacity:0; transform:translateY(8px) scale(.985); } }
    .beta { margin:0 0 14px; font-size:12px; color:var(--tertiary); }
    h1 { margin:0 0 12px; font:600 25px/1.2 -apple-system,BlinkMacSystemFont,"SF Pro Display",system-ui,sans-serif; letter-spacing:-.02em; }
    p { margin:0 0 10px; color:var(--secondary); }
    p.say { color:var(--label); }
    p.detail { font-size:12px; color:var(--tertiary); overflow-wrap:anywhere; }
    .live { position:relative; margin:4px 0 12px; height:176px; border-radius:18px; overflow:hidden; background:var(--hover); }
    video { width:100%; height:100%; object-fit:cover; transform:scaleX(-1); display:block; }
    #feed { position:fixed; left:0; top:0; width:2px; height:2px; opacity:0; pointer-events:none; }
    .sees { margin:0 0 14px; color:var(--label); font-weight:500; }
    .steps { margin:4px 0 16px; padding:0; list-style:none; }
    .steps li { padding:9px 0; color:var(--label); border-top:.5px solid var(--line); }
    .steps li:first-child { border-top:0; }
    .row { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:18px; }
    button { white-space:nowrap; font:inherit; font-weight:500; border:0; border-radius:12px; padding:9px 18px; cursor:default; color:var(--label); background:var(--hover); transition:background .16s ease,opacity .16s ease; }
    button.primary { background:var(--accent); color:var(--on-accent); }
    button.quiet { background:transparent; color:var(--secondary); padding:9px 10px; }
    button:hover { filter:brightness(1.07); } button:active { opacity:.78; }
    button:disabled { opacity:.42; filter:none; }
    button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
    #rehearse { margin:2px 0 0; padding:13px 16px; border-radius:14px; background:var(--hover); color:var(--secondary); transition:background .2s ease,color .2s ease; }
    #rehearse.on { color:var(--label); box-shadow:inset 0 0 0 1.5px var(--accent); }
    #dot { position:fixed; left:0; top:0; width:0; height:0; display:none; transition:transform .5s cubic-bezier(.3,.7,.2,1); }
    #dot i,#dot b { position:absolute; border-radius:50%; transform:translate(-50%,-50%); }
    #dot i { width:14px; height:14px; background:var(--dot); }
    #dot b { width:42px; height:42px; box-shadow:inset 0 0 0 1px var(--dot); opacity:.32; }
    #dot.collect b { animation:draw var(--ms,1.1s) linear forwards; }
    @keyframes draw { to { width:14px; height:14px; opacity:.85; } }
    #tip { position:fixed; left:0; top:0; display:none; padding:7px 14px; border-radius:12px; color:var(--label); white-space:nowrap; font-size:14px; transition:opacity .2s ease; }
    #practice { position:fixed; inset:0; display:none; padding:28px 28px 104px; grid:1fr 1fr / 1fr 1fr 1fr; gap:18px; }
    .topic { display:grid; place-items:center; border-radius:24px; font:600 24px/1.2 -apple-system,BlinkMacSystemFont,"SF Pro Display",system-ui,sans-serif; letter-spacing:-.02em; }
    #region { position:fixed; left:0; top:0; width:44vmin; height:44vmin; margin:-22vmin 0 0 -22vmin; border-radius:50%; pointer-events:none; opacity:0;
      mix-blend-mode:var(--blend); background:radial-gradient(closest-side,var(--region) 0%,color-mix(in srgb,var(--region) 62%,transparent) 32%,color-mix(in srgb,var(--region) 22%,transparent) 62%,color-mix(in srgb,var(--region) 5%,transparent) 84%,transparent 100%); transition:transform .3s cubic-bezier(.3,.7,.3,1),opacity .35s ease; }
    #bar { position:fixed; left:50%; bottom:24px; transform:translateX(-50%); display:none; align-items:center; gap:6px; max-width:calc(100vw - 32px); padding:9px 10px 9px 20px; border-radius:20px; }
    #bar span { white-space:nowrap; margin-right:14px; color:var(--secondary); }
    @media (max-width:760px) { #bar { flex-wrap:wrap; } #bar span { white-space:normal; } }
    @media (prefers-reduced-motion: reduce) { #card { animation:none; } #dot,#region,#wash { transition:none; }
      #dot.collect b { animation:none; opacity:.85; } }
    @media (prefers-reduced-transparency: reduce) { :root { --fill:#f4f4f6; } .glass { -webkit-backdrop-filter:none; backdrop-filter:none; } #wash { display:none; } }
    @media (prefers-reduced-transparency: reduce) and (prefers-color-scheme: dark) { :root { --fill:#2a2a2e; } }`;
  document.head.append(style);
  document.title = "Hermes Gaze";
  const wash = make("div"); wash.id = "wash";
  const main = make("main"), card = make("section", "", "glass"); card.id = "card"; main.append(card);
  // The detection video never leaves the DOM: removing a media element pauses it.
  const video = make("video"); video.autoplay = true; video.muted = true; video.playsInline = true; video.id = "feed";
  const preview = make("video"); preview.autoplay = true; preview.muted = true; preview.playsInline = true;
  const live = make("div", "", "live"); live.append(preview);
  const sees = make("p", "", "sees");
  const dot = make("div"); dot.id = "dot"; dot.append(make("b"), make("i"));
  const tip = make("div", "", "glass"); tip.id = "tip";
  const practice = make("div"); practice.id = "practice";
  for (const topic of ["Saturn’s rings", "Coral reefs", "Sourdough", "The Silk Road", "Honeybees", "Northern lights"]) practice.append(make("div", topic, "topic glass"));
  const region = make("div"); region.id = "region";
  const bar = make("div", "", "glass"); bar.id = "bar";
  const barText = make("span");
  document.body.append(video, wash, main, practice, region, dot, tip, bar);

  const POINTS = [.1, .5, .9].flatMap(y => [.1, .5, .9].map(x => [x, y]));
  const NO_FACE = "Hermes can’t see your eyes. Check the light and face the screen.";
  const OFF_SCREEN = "Your gaze looks off this screen, so nothing is shown.";
  const ESTIMATE = "This is an estimate, not a pointer.";
  const REMIND = "Moved, changed glasses or adjusted the camera? Recalibrate.";
  const CURSOR = ["cursor", "Use cursor"];
  // Display only: a coarse cell, so the area never reads as a precise pointer.
  const REGION_COLS = 8, REGION_ROWS = 6, LOST_AFTER_MS = 700, TAP_HOLD_MS = 220;

  let model, stream, timer, active = true, index = -1, collecting = false, until = 0, lastVideoTime = -1, awaiting = false;
  let frames = 0, firstFrame = 0, lastFrame = 0, frameMs = 0, featureMs = 0;
  let phase = "start", locked = null, calibrated = !!opts.calibrated, notice = opts.calibration_notice || "", faceAt = 0, faceShown = null;
  let check = null, checkIndex = -1, checkObserving = false, checkTimer = 0;
  let seenAt = 0, lostWhy = "", barWords = "", practiceTick = 0;
  let holdStart = 0, holdTimer = 0, rehearsal = null, finished = false;

  const windowNow = () => [screenX, screenY, innerWidth, innerHeight, devicePixelRatio];
  const faceVisible = () => performance.now() - faceAt < 800;
  function setFocus(on) { document.body.classList.toggle("focus", on); document.body.classList.toggle("calibrating", on); }

  function buttons(list) {
    const row = make("div", "", "row");
    list.forEach(([action, label, disabled], i) => {
      const b = make("button", label, i === 0 ? "primary" : (action === "cursor" ? "quiet" : ""));
      b.dataset.action = action; b.disabled = !!disabled; b.addEventListener("click", e => act(action, e)); row.append(b);
    });
    return row;
  }
  function showCard({title, lines = [], say = [], extra = [], actions = [], withCamera = false, detail = ""}) {
    card.replaceChildren(make("p", "Eye tracking is in beta", "beta"));
    card.append(make("h1", title));
    if (withCamera && stream) { card.append(live, sees); preview.srcObject = stream; preview.play().catch(() => {}); }
    for (const line of say) card.append(make("p", line, "say"));
    for (const line of lines) if (line) card.append(make("p", line));
    card.append(...extra);
    if (detail) card.append(make("p", detail, "detail"));
    card.append(buttons(actions));
    main.style.display = ""; card.style.animation = "none"; void card.offsetWidth; card.style.animation = "";
    updateFace();
  }
  function updateFace() {
    if (!stream) return;
    const visible = faceVisible();
    if (visible === faceShown && sees.textContent) return;
    faceShown = visible;
    sees.textContent = visible ? "Hermes can see your face." : "Move into the picture so Hermes can see your face.";
    const begin = card.querySelector('[data-action="calibrate"]');
    if (begin && phase === "home" && !calibrated) begin.disabled = !visible;
  }
  function home() {
    phase = "home"; locked = null; hideFlow();
    if (calibrated && finished) {
      showCard({title: "Eye tracking is on", say: ["Leave this window open. It’s the only place the camera runs."],
        lines: [REMIND], withCamera: true, actions: [["check", "Check my gaze"], ["calibrate", "Recalibrate"], CURSOR]});
    } else if (calibrated) {
      showCard({title: "Welcome back", say: ["Your saved calibration is on. A quick check tells you if it still fits."],
        lines: [notice, REMIND], withCamera: true,
        actions: [["check", "Check my gaze"], ["calibrate", "Recalibrate"], CURSOR]});
    } else {
      showCard({title: "Set up eye tracking", withCamera: true, lines: [notice],
        say: ["Sit the way you normally sit, with your glasses on if you wear them. Keep this window large and on one screen."],
        extra: [make("p", "At each dot, look at it and tap Space, then keep looking. Just a tap: holding Space is for talking later, in Chrome.", "say"),
                make("p", "The picture from your camera stays in this window.")],
        actions: [["calibrate", "Begin", !faceVisible()], CURSOR]});
    }
    notice = ""; finished = false;
  }
  function hideFlow() {
    index = -1; collecting = false; awaiting = false; checkObserving = false; checkIndex = -1; clearTimeout(checkTimer); check = null;
    dot.style.display = "none"; tip.style.display = "none"; practice.style.display = "none"; bar.style.display = "none"; region.style.opacity = "0";
    dot.classList.remove("collect"); setFocus(false);
  }
  function fatal(raw, plain) {
    active = false; clearInterval(timer); stream?.getTracks().forEach(t => t.stop()); stream = null; video.srcObject = null; preview.srcObject = null;
    hideFlow(); phase = "error";
    showCard({title: "The camera didn’t start", say: [plain], detail: raw, actions: [["retry", "Try again"], CURSOR]});
  }
  function plainCameraError(e) {
    const name = e && e.name;
    if (name === "NotAllowedError") return "Chrome wasn’t allowed to use the camera. Allow it for this window, then try again.";
    if (name === "NotFoundError") return "No camera was found on this computer.";
    if (name === "NotReadableError") return "The camera couldn’t be opened. Another app may be using it.";
    return "Something stopped the camera from starting.";
  }
  function moveDot(x, y) { dot.style.transform = `translate(${x * innerWidth}px,${y * innerHeight}px)`; }
  function placeTip(text, x, y) {
    tip.textContent = text; tip.style.display = "block";
    const r = tip.getBoundingClientRect();
    const px = Math.min(innerWidth - r.width - 16, Math.max(16, x * innerWidth - r.width / 2));
    const py = y > .7 ? y * innerHeight - r.height - 44 : y * innerHeight + 40;
    tip.style.transform = `translate(${px}px,${py}px)`;
  }
  function place(words) {
    const [x, y] = POINTS[index]; moveDot(x, y); dot.classList.remove("collect");
    placeTip(words || (index >= POINTS.length - 2 ? "Almost there. Tap Space." : "Look at the dot, then tap Space."), x, y);
  }
  function measure(e) {
    // Measured from this trusted click: no fullscreen/browser-chrome offset guess.
    locked = windowNow();
    return {viewport: {left: e.screenX - e.clientX, top: e.screenY - e.clientY, width: innerWidth, height: innerHeight},
      screen: {left: screen.availLeft, top: screen.availTop, width: screen.availWidth, height: screen.availHeight,
        screen_width: screen.width, screen_height: screen.height, screen_left: screen.availLeft, screen_top: screen.availTop, dpr: devicePixelRatio}};
  }
  function act(action, e) {
    if (!e.isTrusted || !active && action !== "retry" && action !== "cursor") return;
    if (action === "calibrate" && stream) {
      hideFlow(); phase = "calibrate"; index = 0; main.style.display = "none"; setFocus(true); dot.style.display = "block";
      emit("calibration_start", measure(e)); place();
    } else if (action === "check" && stream) {
      hideFlow(); phase = "waiting"; emit("check_start", measure(e));
    } else if (action === "practise" && stream) {
      hideFlow(); phase = "waiting"; emit("practice_start", measure(e));
    } else if (action === "done") {
      if (phase === "practice") emit("practice_end");
      handoff();
    } else if (action === "home") {
      finished = true; home();
    } else if (action === "cursor") {
      emit("use_cursor"); hideFlow(); phase = "closing"; shutdown();
      showCard({title: "Back to the cursor", say: ["Hermes will use your pointer. The camera is off."], actions: []});
    } else if (action === "retry") {
      restart();
    }
  }
  function handoff() {
    hideFlow(); phase = "handoff"; locked = null; rehearsal = make("p", "Try it here: hold Space. This is only a rehearsal.");
    rehearsal.id = "rehearse";
    const steps = make("ul", "", "steps");
    for (const s of ["Move the pointer once in the page.", "Hold Space.", "Wait for Listening.", "Ask about what you’re looking at.", "Let go."]) steps.append(make("li", s));
    showCard({title: "Now ask in Chrome", say: ["Switch back to your Chrome window. Here’s how asking works."], extra: [steps, rehearsal],
      lines: [], actions: [["home", "Done"], CURSOR]});
  }
  function startCheckRun() {
    phase = "check"; main.style.display = "none"; setFocus(true); tip.style.display = "none"; dot.style.display = "block"; dot.classList.remove("collect");
    checkIndex = 0; runTrial();
  }
  function runTrial() {
    const [x, y] = check.points[checkIndex]; moveDot(x, y); checkObserving = false;
    checkTimer = setTimeout(() => {
      checkObserving = true;
      checkTimer = setTimeout(() => {
        checkObserving = false; emit("check_trial", {index: checkIndex}); checkIndex++;
        if (checkIndex < check.points.length) runTrial();
      }, check.observe_ms);
    }, check.settle_ms);
  }
  function setPracticeWords(text) { if (text !== barWords) { barWords = text; barText.textContent = text; } }
  function practiceFrame() {
    if (phase !== "practice") return;
    if (performance.now() - seenAt > LOST_AFTER_MS) {
      region.style.opacity = "0";
      setPracticeWords(lostWhy === "offscreen" ? OFF_SCREEN : NO_FACE);
    } else setPracticeWords(ESTIMATE);
  }
  addEventListener("keydown", e => {
    if (!e.isTrusted) return;
    if (e.code === "Escape" && ["calibrate", "checkIntro", "check", "practice", "waiting"].includes(phase)) {
      emit("calibration_cancel"); notice = "Cancelled. " + (calibrated ? "Your saved calibration has not changed." : "Nothing was saved."); home(); return;
    }
    if (e.code !== "Space") return;
    if (phase === "calibrate") {
      e.preventDefault();
      if (e.repeat || collecting || awaiting || index < 0) return;
      collecting = true; until = performance.now() + 1100; dot.classList.add("collect");
      placeTip("Keep looking", ...POINTS[index]);
    } else if (phase === "checkIntro") {
      e.preventDefault(); if (!e.repeat) startCheckRun();
    } else if (phase === "handoff") {
      e.preventDefault(); if (e.repeat || holdStart) return;
      holdStart = performance.now();
      holdTimer = setTimeout(() => { rehearsal.textContent = "Listening. Only a rehearsal: nothing is being recorded."; rehearsal.classList.add("on"); }, TAP_HOLD_MS);
    }
  }, true);
  addEventListener("keyup", e => {
    if (!e.isTrusted || e.code !== "Space" || phase !== "handoff" || !holdStart) return;
    e.preventDefault(); clearTimeout(holdTimer);
    const held = performance.now() - holdStart; holdStart = 0; rehearsal.classList.remove("on");
    rehearsal.textContent = held >= TAP_HOLD_MS ? "That was only a rehearsal. Nothing was recorded or answered. In Chrome, the same hold asks a real question."
      : "That was a tap. Hold Space until you see Listening.";
  }, true);
  function shutdown() {
    active = false; clearInterval(timer); clearInterval(practiceTick); stream?.getTracks().forEach(t => t.stop()); try { model?.close(); } catch {}
    model = null; stream = null; video.srcObject = null; preview.srcObject = null;
  }
  addEventListener("pagehide", () => { shutdown(); hideFlow(); }, {once: true});
  globalThis.__HERMES_WEBCAM__ = {
    stop() { shutdown(); hideFlow(); },
    pointAccepted() { awaiting = false; index++; if (index < POINTS.length) place(); },
    pointRetry() { awaiting = false; collecting = false; place("We lost your eyes there. Look at the dot and tap Space again."); },
    calibrationFailed(text) { hideFlow(); phase = "result";
      showCard({title: "That didn’t work", say: [text], lines: [calibrated ? "Your earlier calibration has not changed." : ""], actions: [["calibrate", "Try again"], CURSOR]}); },
    checkReady(value) {
      hideFlow(); check = value; phase = "checkIntro"; dot.style.display = "none";
      showCard({title: "One short check", say: ["A dot will move by itself. Follow it with your eyes. No need to press anything while it moves."],
        lines: ["Nothing will show where we think you’re looking, so you can’t chase it.", "Tap Space to start. Esc cancels."], actions: [CURSOR]});
    },
    checkResult(result) {
      hideFlow(); phase = "result"; locked = null; calibrated = result.calibrated;
      showCard({title: result.title, say: result.body.slice(0, 1), lines: result.body.slice(1), actions: [...result.actions, CURSOR]});
    },
    practiceReady() {
      hideFlow(); phase = "practice"; main.style.display = "none"; seenAt = performance.now(); lostWhy = "face"; barWords = ""; setFocus(true);
      practice.style.display = "grid"; bar.style.display = "flex";
      bar.replaceChildren(barText, ...[...buttons([["done", "Finish"], ["check", "Check again"], ["calibrate", "Recalibrate"], CURSOR]).children]);
      setPracticeWords(ESTIMATE);
    },
    practiceGaze(value) {
      if (phase !== "practice") return;
      if (value.lost) { lostWhy = value.lost; return; }
      seenAt = performance.now();
      const x = (Math.floor(value.x * REGION_COLS - 1e-9) + .5) / REGION_COLS, y = (Math.floor(value.y * REGION_ROWS - 1e-9) + .5) / REGION_ROWS;
      region.style.transform = `translate(${x * innerWidth}px,${y * innerHeight}px)`; region.style.opacity = "1";
    },
    notice(text) { notice = text; home(); },
    cameraFailed(raw) { fatal(raw, "The camera stopped sending pictures. Another app may have taken it."); },
    status() { return {active, phase, index, collecting, checkIndex, face: faceVisible(), videoTime: video.currentTime, hidden: document.hidden,
      frames, frame_ms: frames ? frameMs / frames : null, feature_ms: frames ? featureMs / frames : null,
      sample_hz: frames > 1 ? (frames - 1) * 1000 / (lastFrame - firstFrame) : null}; }
  };
  function tick() {
    if (!active || video.readyState < 2 || video.currentTime === lastVideoTime) return;
    lastVideoTime = video.currentTime;
    if (locked && ["calibrate", "checkIntro", "check", "practice"].includes(phase) &&
        (document.hidden || locked.some((v, i) => v !== windowNow()[i]))) {
      emit("calibration_cancel");
      notice = "The window changed, so that stopped. " + (calibrated ? "Your saved calibration has not changed." : "Nothing was saved.");
      home(); return;
    }
    const now = performance.now(), t = (performance.timeOrigin + now) / 1000;
    try {
      const lm = model.detectForVideo(video, now).faceLandmarks[0];
      const featureStart = performance.now();
      const f = globalThis.__hermesGazeAppearance(video, lm, globalThis.__hermesGazeFeatures(lm), true);
      const done = performance.now();
      frameMs += done - now; featureMs += done - featureStart;
      if (!frames) firstFrame = now;
      frames++; lastFrame = now;
      if (f) faceAt = now;
      updateFace();
      emit("sample", {t, features: f, calibration: collecting ? index : -1, check: checkObserving ? checkIndex : -1, hidden: document.hidden});
      if (collecting && now >= until) {
        collecting = false; awaiting = true; emit("calibration_point", {index});
        if (index === POINTS.length - 1) { placeTip("Almost there", ...POINTS[index]); dot.style.display = "none"; }
      }
    } catch (e) { emit("error", {error: String(e)}); fatal(String(e), "The eye tracker hit a problem and stopped."); }
  }
  async function openCamera() {
    if (!model) {
      const {FaceLandmarker} = await import(opts.module);
      // Python installs the checksum-verified SIMD loader into this isolated context.
      const files = {wasmBinaryPath: opts.wasm + "/vision_wasm_internal.wasm"};
      model = await FaceLandmarker.createFromOptions(files, {baseOptions: {modelAssetPath: opts.model, delegate: "CPU"},
        runningMode: "VIDEO", numFaces: 1, minFaceDetectionConfidence: .5, minFacePresenceConfidence: .5});
    }
    stream = await navigator.mediaDevices.getUserMedia({video: {width: 640, height: 480}, audio: false});
    video.srcObject = stream; await video.play();
    active = true; lastVideoTime = -1;
    timer = setInterval(tick, 100); // Timers, not requestAnimationFrame: this owned process disables background throttling.
    clearInterval(practiceTick); practiceTick = setInterval(practiceFrame, 150);
    emit("ready"); home();
  }
  async function restart() {
    phase = "start"; showCard({title: "Starting the camera", actions: [CURSOR]});
    emit("retry_camera");
    try { await openCamera(); } catch (e) { emit("error", {error: String(e)}); fatal(String(e), plainCameraError(e)); }
  }
  showCard({title: "Starting the camera", actions: [CURSOR]});
  try { await openCamera(); } catch (e) { emit("error", {error: String(e)}); fatal(String(e), plainCameraError(e)); }
})
