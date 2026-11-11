// Loaded by CDP only, in the tracker window's isolated world. No website runs here.
(async function (opts) {
  "use strict";
  let flow = 0, setup = opts.setup || "";
  const emit = (type, data = {}) => __lookIntent(JSON.stringify({type, nonce: opts.nonce, setup, flow, ...data}));
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; };
  const style = make("style");
  // Material values are the companion's glass plate (browser/overlay.js) and type (browser/panel.js).
  style.textContent = `
    :root { color-scheme:light dark; --ground:#efeff2; --label:#202124; --secondary:#62636a; --tertiary:#797a80;
      --accent:#0066d6; --tint:rgba(0,102,214,.10); --hover:rgba(35,36,40,.13); --line:rgba(35,36,40,.13);
      --fill:rgba(250,250,252,.82); --blur:blur(34px) saturate(1.6); --sheen:rgba(255,255,255,.8);
      --shadow:0 0 0 .5px rgba(0,0,0,.13),0 12px 36px rgba(0,0,0,.12),0 3px 8px rgba(0,0,0,.04),inset 0 1px 0 rgba(255,255,255,.8);
      --quiet:var(--shadow); --dot:#202124; }
    @media (prefers-color-scheme:dark) { :root { --ground:#1b1b1e; --label:#f2f2f5; --secondary:#b5b5be; --tertiary:#96969e;
      --accent:#6aaeff; --tint:rgba(78,161,255,.17); --hover:rgba(255,255,255,.17); --line:rgba(255,255,255,.17);
      --fill:rgba(44,44,48,.86); --sheen:rgba(255,255,255,.1);
      --shadow:0 0 0 .5px rgba(255,255,255,.17),0 12px 36px rgba(0,0,0,.36),inset 0 1px 0 rgba(255,255,255,.1); } }
    /* Measurement is a bright neutral field in either appearance. */
    body.focus { --ground:#efeff2; --label:#202124; --secondary:#62636a; --line:rgba(35,36,40,.13);
      --fill:rgba(250,250,252,.82); --dot:#202124; --accent:#0066d6;
      --shadow:0 0 0 .5px rgba(0,0,0,.13),0 12px 36px rgba(0,0,0,.12),inset 0 1px 0 rgba(255,255,255,.8); }
    * { box-sizing:border-box; }
    html,body { height:100%; margin:0; }
    body { background:var(--ground); color:var(--label); overflow:hidden; -webkit-font-smoothing:antialiased; letter-spacing:-.006em; cursor:default;
      font:15px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif; transition:background-color .6s ease; }
    [hidden] { display:none!important; }
    .glass { background:var(--fill); -webkit-backdrop-filter:var(--blur); backdrop-filter:var(--blur); box-shadow:var(--shadow); }
    h1 { font-size:32px; line-height:1.14; letter-spacing:-.035em; font-weight:600; margin:9px 0 12px; text-align:center; }
    main.result h1 { font-size:36px; }
    .rail { position:fixed; top:24px; left:30%; transform:translateX(-50%); display:flex; gap:14px; align-items:baseline; color:var(--secondary); font-size:13px; }
    .rail strong { color:var(--label); font-weight:500; }
    #cancel { position:fixed; top:16px; left:70%; transform:translateX(-50%); font-size:13px; }
    main { position:fixed; inset:52px 24px 36px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:0; }
    .arrive { animation:arrive .42s cubic-bezier(.2,.8,.2,1) both; }
    @keyframes arrive { from { opacity:0; transform:translateY(8px) scale(.985); } }
    #feed { position:fixed; left:0; top:0; width:2px; height:2px; opacity:0; pointer-events:none; }
    .face { position:relative; width:230px; height:230px; border-radius:50%; padding:8px; flex:none; margin-bottom:22px; }
    .face .picture { position:relative; width:100%; height:100%; border-radius:50%; overflow:hidden; background:var(--ground); box-shadow:inset 0 0 0 .5px var(--line),inset 0 1px 3px rgba(0,0,0,.08); }
    .face video { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; transform:scaleX(-1); display:block; }
    .face.off video,.face.off .guide,.face.off .you { display:none; }
    .face.waking { animation:breathe 2s ease-in-out infinite; }
    @keyframes breathe { 50% { opacity:.62; } }
    .guide,.you { position:absolute; border-radius:50%; pointer-events:none; transform:translate(-50%,-50%); }
    .guide { left:50%; top:48%; width:62%; height:62%; border:1.5px dashed rgba(255,255,255,.75); filter:drop-shadow(0 0 1.5px rgba(0,0,0,.5)); transition:opacity .3s ease; }
    .you { left:50%; top:48%; width:62%; height:62%; opacity:0; border:2px solid #fff; filter:drop-shadow(0 0 2px rgba(0,0,0,.45));
      transition:left .22s ease,top .22s ease,width .22s ease,height .22s ease,opacity .25s ease; }
    .face.placed .guide { opacity:0; }
    .note { max-width:390px; margin:0; font-size:15px; line-height:1.5; color:var(--secondary); text-align:center; }
    .note.kept { color:var(--secondary); font-size:13px; margin-top:14px; }
    .row { display:inline-flex; flex-wrap:wrap; justify-content:center; align-items:center; gap:3px; padding:5px; border-radius:28px; margin-top:24px; max-width:calc(100vw - 32px); }
    button { all:unset; box-sizing:border-box; cursor:pointer; white-space:nowrap; padding:11px 19px; border-radius:22px; font-size:14px; font-weight:400; color:var(--secondary); transition:background-color .16s ease,opacity .16s ease; }
    button:hover { background-color:var(--hover); }
    button.primary { background-color:var(--tint); color:var(--accent); font-weight:600; }
    button.primary:hover { filter:brightness(1.05); }
    button:active { opacity:.72; }
    button:disabled { opacity:.42; filter:none; background-color:transparent; }
    button.primary:disabled { background-color:var(--hover); color:var(--secondary); }
    button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
    .key { display:inline-block; padding:0 12px; height:25px; line-height:24px; border-radius:7px; font-size:12.5px; font-weight:500; color:var(--label); background:linear-gradient(180deg,var(--sheen),transparent 60%),var(--fill);
      box-shadow:0 0 0 .5px var(--line),0 1.5px 0 var(--line),0 3px 8px rgba(0,0,0,.08),inset 0 .5px 0 var(--sheen); vertical-align:baseline; transition:transform .1s ease,box-shadow .1s ease; }
    #dot { --size:clamp(44px,11vw,108px); position:fixed; left:0; top:0; width:0; height:0; display:none; }
    #dot .disc,#dot .pt { position:absolute; border-radius:50%; }
    #dot .disc { left:calc(var(--size) / -2); top:calc(var(--size) / -2); width:var(--size); height:var(--size); box-shadow:var(--quiet); transition:transform .42s cubic-bezier(.2,.9,.3,1); }
    #dot .pt { left:-5px; top:-5px; width:10px; height:10px; background:var(--dot); transition:transform .3s ease; }
    #dot.collect .disc { transform:scale(.29); transition:transform var(--ms,1.1s) cubic-bezier(.45,0,.55,1); }
    #dot.collect .pt { transform:scale(2.4); transition:transform var(--ms,1.1s) cubic-bezier(.45,0,.55,1); }
    #cue { position:fixed; left:0; top:0; display:none; width:270px; max-width:calc(100vw - 32px); text-align:center; font-size:13px; color:var(--secondary); line-height:1.5; }
    #practice { position:fixed; inset:38px 36px 285px; display:none; grid-template-columns:1fr 1.1fr; gap:38px; align-items:center; max-width:930px; margin:auto; }
    body.practising #practice { display:grid; }
    .article h2 { font-size:29px; letter-spacing:-.035em; line-height:1.12; margin:0 0 17px; }
    .article p { max-width:380px; font-size:15px; line-height:1.7; color:var(--secondary); }
    .topic { display:grid; place-items:center; height:220px; border-radius:34px; background:var(--fill); box-shadow:inset 0 0 0 .5px var(--line); }
    .topic.selected { outline:2px solid var(--line); outline-offset:9px; }
    .planet { width:138px; height:138px; border-radius:50%; background:linear-gradient(140deg,#ddc6a0,#a8977f); position:relative; }
    .planet::after { content:""; position:absolute; width:290px; height:72px; border:18px solid #c5bcb0; border-radius:50%; top:30px; left:-76px; transform:rotate(-24deg); }
    #example { position:fixed; right:8%; top:48px; width:310px; padding:23px; border-radius:23px; }
    #example h2 { font-size:19px; margin:0 0 9px; }
    #example p { line-height:1.6; font-size:14px; }
    .quiet { color:var(--secondary); font-size:12px; }
    .practice-status { min-height:44px; padding:9px 21px; border-radius:28px; font-size:16px; }
    .practice-status.live { color:var(--accent); }
    #bar { position:fixed; left:50%; bottom:24px; transform:translateX(-50%); display:none; flex-direction:column; align-items:center; gap:12px; max-width:calc(100vw - 32px); }
    @media (max-width:850px) { .face { width:184px; height:184px; } h1 { font-size:28px; } main.result h1 { font-size:30px; } #practice { inset:30px 28px 280px; gap:22px; } .article h2 { font-size:25px; } }
    @media (max-width:520px) { #practice { inset:20px 24px 315px; flex-direction:column; justify-content:center; gap:15px; } body.practising #practice { display:flex; } .topic { width:280px; height:170px; } .article h2 { font-size:24px; } .article p { font-size:13px; } .rail { font-size:12px; gap:8px; } #example { right:6%; max-width:88%; } }
    @media (max-height:560px) { #practice { inset:20px 32px 220px; } .topic { height:140px; } .planet { transform:scale(.7); } .article p { font-size:13px; } #bar { bottom:12px; gap:4px; } #bar h1 { font-size:23px; margin:4px; } #bar .row { margin-top:10px; } }
    @media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation:none!important; transition:none!important; } }
    @media (prefers-reduced-transparency: reduce) { :root,body.focus { --fill:rgb(250,250,252); --sheen:transparent; --blur:none; }
      .glass { -webkit-backdrop-filter:none; backdrop-filter:none; } }
    @media (prefers-reduced-transparency: reduce) and (prefers-color-scheme: dark) { :root { --fill:rgb(44,44,47); }
      body.focus { --fill:rgb(250,250,252); } }`;
  document.head.append(style);
  document.title = "Look";
  const rail = make("div", "", "rail"), stageName = make("strong"), count = make("span"); count.id = "progress"; count.setAttribute("role", "status"); rail.append(stageName, count);
  const cancel = make("button", "Cancel"); cancel.id = "cancel"; cancel.dataset.action = "cancel"; cancel.addEventListener("click", e => act("cancel", e));
  const main = make("main");
  // The detection video never leaves the DOM: removing a media element pauses it.
  const video = make("video"); video.autoplay = true; video.muted = true; video.playsInline = true; video.id = "feed";
  const preview = make("video"); preview.autoplay = true; preview.muted = true; preview.playsInline = true;
  const face = make("div", "", "face glass"), picture = make("div", "", "picture");
  const guide = make("div", "", "guide"), you = make("div", "", "you");
  picture.append(preview, guide, you); face.append(picture);
  const dot = make("div"); dot.id = "dot";
  const disc = make("div", "", "disc glass"); dot.append(disc, make("div", "", "pt"));
  const cue = make("div"); cue.id = "cue";
  const practice = make("article"); practice.id = "practice";
  const article = make("div", "", "article");
  article.append(make("h2", "Saturn’s rings"), make("p", "Saturn’s rings stretch far beyond the planet. From a distance they look solid, but they’re made of countless separate pieces."));
  const planet = make("div", "", "topic");
  planet.setAttribute("role", "img"); planet.setAttribute("aria-label", "Illustration of Saturn and its rings");
  planet.append(make("div", "", "planet")); practice.append(article, planet);
  const example = make("section", "", "glass"); example.id = "example"; example.hidden = true;
  example.setAttribute("aria-label", "Example answer");
  example.append(make("h2", "Saturn’s rings"), make("p", "Saturn’s rings are mostly ice, with some rock and dust. Billions of pieces orbit the planet."), make("p", "Example answer", "quiet"));
  const bar = make("div"); bar.id = "bar"; bar.setAttribute("aria-live", "polite");
  document.body.append(video, main, practice, example, dot, cue, bar, rail, cancel);
  cue.setAttribute("role", "status"); dot.setAttribute("aria-describedby", "cue");
  rail.hidden = cancel.hidden = true;

  const POINTS = [.1, .5, .9].flatMap(y => [.1, .5, .9].map(x => [x, y]));
  const NO_EYES = "Couldn’t see your eyes.", MOVED = "Window moved";
  const CURSOR = ["cursor", "Use cursor"];
  // Display only: a coarse cell, so the area never reads as a precise pointer.
  const REGION_COLS = 8, REGION_ROWS = 6, LOST_AFTER_MS = 700, TAP_HOLD_MS = 130, READY_MS = 650;
  // Face cue, in fractions of the round picture. Fixed by eye; it is a hint, not a gate.
  const GUIDE = {x: .5, y: .48, size: .62}, FIT = {x: .075, y: .085, size: .14}, HEAD_SPAN = 1.65;

  let model, stream, timer, active = true, index = -1, collecting = false, until = 0, lastVideoTime = -1, awaiting = false;
  let frames = 0, firstFrame = 0, lastFrame = 0, frameMs = 0, featureMs = 0;
  let phase = "start", locked = null, calibrated = !!opts.calibrated, notice = opts.calibration_notice || "", faceAt = 0;
  let check = null, checkIndex = -1, checkObserving = false, checkTimer = 0;
  let seenAt = 0, practiceTick = 0, practiceFace = false;
  let holdStart = 0, holdTimer = 0, readyTimer = 0, practiceStep = "idle";
  let retryPoint = false, listening = false, rehearsed = false, spaceDown = false;
  const faceNote = make("p", "", "note");

  const windowNow = () => [screenX, screenY, innerWidth, innerHeight, devicePixelRatio];
  const faceVisible = () => performance.now() - faceAt < 800;
  function setFocus(on) { document.body.classList.toggle("focus", on); document.body.classList.toggle("calibrating", on); }

  function buttons(list) {
    const row = make("div", "", "row glass");
    list.forEach(([action, label, disabled], i) => {
      const b = make("button", label, i === 0 && !["cursor", "done"].includes(action) ? "primary" : "");
      b.dataset.action = action; b.disabled = !!disabled; b.addEventListener("click", e => act(action, e)); row.append(b);
    });
    return row;
  }
  // Every full page: optional round picture, only the words that can't be drawn, one capsule of actions.
  function page({camera = "", waking = false, status = "", notes = [], kept = "", extra = [], actions = []}) {
    const parts = [];
    if (camera) {
      const live = camera === "live" && stream;
      face.classList.toggle("off", !live); face.classList.toggle("waking", waking); face.classList.remove("placed");
      if (live) { preview.srcObject = stream; preview.play().catch(() => {}); }
      parts.push(face);
    }
    if (status) parts.push(make("h1", status));
    parts.push(...extra);
    for (const line of notes) if (line) parts.push(make("p", line, "note"));
    if (kept) parts.push(make("p", kept, "note kept"));
    if (actions.length) parts.push(buttons(actions));
    main.replaceChildren(...parts); main.className = ["result", "error", "moved"].includes(phase) ? "result" : ""; main.style.display = "";
    for (const part of parts) { part.classList.remove("arrive"); void part.offsetWidth; part.classList.add("arrive"); }
    updateFace();
  }
  function updateFace() {
    const visible = faceVisible();
    for (const b of document.querySelectorAll('[data-action="calibrate"],[data-action="check"],[data-action="start-check"]')) b.disabled = !visible;
    if (!visible) { you.style.opacity = "0"; face.classList.remove("placed"); }
    if (phase === "home") faceNote.textContent = !visible ? "Bring your face into view." : notice;
    if (phase === "boundary") faceNote.textContent = visible ? "" : "Bring your face into view.";
    if (["calibrate", "checkIntro", "check"].includes(phase)) {
      if (!visible && !awaiting && (collecting || checkObserving || phase === "check")) {
        collecting = awaiting = checkObserving = false; clearTimeout(checkTimer); dot.classList.remove("collect");
        if (phase === "check") phase = "checkIntro";
        emit("observation_cancel");
      }
      const p = phase === "calibrate" ? POINTS[index] : check?.points[checkIndex];
      if (p) showCue(...p);
    }
  }
  // Runs here only, on landmarks already in this window. Nothing about it crosses the binding.
  function followFace(lm) {
    const a = (video.videoWidth || 640) / (video.videoHeight || 480);
    const across = p => (1 - p.x) * a - (a - 1) / 2;   // Mirrored, then cropped to the round picture.
    const x = (across(lm[234]) + across(lm[454])) / 2, y = (lm[10].y + lm[152].y) / 2, size = Math.abs(lm[454].x - lm[234].x) * a * HEAD_SPAN;
    const placed = Math.abs(x - GUIDE.x) < FIT.x && Math.abs(y - GUIDE.y) < FIT.y && Math.abs(size - GUIDE.size) < FIT.size;
    const ring = placed ? GUIDE : {x, y, size};
    you.style.left = `${ring.x * 100}%`; you.style.top = `${ring.y * 100}%`; you.style.width = you.style.height = `${ring.size * 100}%`;
    you.style.opacity = "1"; face.classList.toggle("placed", placed);
  }
  function home() {
    phase = "home"; locked = null; hideFlow();
    faceNote.className = "note";
    const outdated = notice === "Eye tracker updated. Start a new calibration." || notice === "The eye tracker has changed.";
    notice = outdated ? "The eye tracker has changed." : notice;
    page({camera: "live", status: calibrated ? "Saved calibration" : outdated ? "Recalibration needed" : "Set up eye tracking",
      extra: [faceNote], actions: calibrated ? [["check", "Check"], ["calibrate", "Calibrate again"], CURSOR] : [["calibrate", "Start calibration"], CURSOR]});
  }
  function hideFlow() {
    index = -1; collecting = false; awaiting = false; checkObserving = false; checkIndex = -1; clearTimeout(checkTimer); check = null;
    clearTimeout(holdTimer); clearTimeout(readyTimer); holdStart = 0; listening = false; example.hidden = true;
    rail.hidden = cancel.hidden = true;
    dot.style.display = "none"; cue.style.display = "none"; practice.style.display = "none"; bar.style.display = "none";
    dot.classList.remove("collect"); setFocus(false); document.body.classList.remove("practising");
  }
  function fatal(label) {
    flow++; emit("calibration_cancel");
    active = false; clearInterval(timer); stream?.getTracks().forEach(t => t.stop()); stream = null; video.srcObject = null; preview.srcObject = null;
    hideFlow(); phase = "error";
    page({status: label, notes: label === "Camera stopped" ? ["Check the camera connection."] : [], kept: calibrated ? "Saved calibration unchanged." : "", actions: [["retry", "Try again"], CURSOR]});
  }
  function cameraLabel(e) {
    const name = e && e.name;
    if (name === "NotAllowedError") return "Camera blocked";
    if (name === "NotFoundError") return "No camera";
    if (name === "NotReadableError") return "Camera in use";
    return "Camera stopped";
  }
  function moveDot(x, y) { dot.style.transform = `translate(${x * innerWidth}px,${y * innerHeight}px)`; }
  function showCue(x, y) {
    cue.textContent = !faceVisible() ? "Bring your face into view." : retryPoint ? "Couldn’t see your eyes. Tap Space" :
      collecting || phase === "check" || awaiting ? "Keep looking" : "Tap Space";
    cue.style.display = "block";
    const size = Math.max(10, Math.min(76, Math.floor(2 * (innerHeight * .1 - 42))));
    dot.style.setProperty("--size", `${size}px`);
    const r = cue.getBoundingClientRect();
    const px = Math.min(innerWidth - r.width - 16, Math.max(16, x * innerWidth - r.width / 2));
    const py = y * innerHeight + size / 2 + 7;
    cue.style.transform = `translate(${px}px,${py}px)`;
  }
  function progress(training) {
    rail.hidden = cancel.hidden = false;
    stageName.textContent = training ? "Calibration" : "Accuracy check";
    count.textContent = `${(training ? index : checkIndex) + 1} of ${training ? 9 : 10}`;
  }
  function place() {
    const [x, y] = POINTS[index]; moveDot(x, y); dot.classList.remove("collect", "shake");
    progress(true); showCue(x, y);
  }
  function measure(e) {
    // Measured from this trusted click: no fullscreen/browser-chrome offset guess.
    locked = windowNow();
    return {viewport: {left: e.screenX - e.clientX, top: e.screenY - e.clientY, width: innerWidth, height: innerHeight},
      screen: {left: screen.availLeft, top: screen.availTop, width: screen.availWidth, height: screen.availHeight,
        screen_width: screen.width, screen_height: screen.height, screen_left: screen.availLeft, screen_top: screen.availTop, dpr: devicePixelRatio}};
  }
  function act(action, e) {
    if (!e.isTrusted || !active && !["retry", "cursor", "setup"].includes(action)) return;
    if (["calibrate", "check", "start-check"].includes(action) && !faceVisible()) return;
    if (action === "calibrate" && stream) {
      flow++; hideFlow(); phase = "calibrate"; index = 0; retryPoint = false; main.style.display = "none"; setFocus(true); dot.style.display = "block";
      emit("calibration_start", measure(e)); place(); e.target.blur();
    } else if (action === "start-check" && phase === "boundary") {
      phase = "waiting"; main.replaceChildren(); emit("check_begin"); e.target.blur();
    } else if (action === "check" && stream) {
      flow++; hideFlow(); phase = "waiting"; emit("check_start", measure(e)); e.target.blur();
    } else if (action === "practise" && stream) {
      flow++; hideFlow(); phase = "waiting"; emit("practice_start", measure(e));
    } else if (action === "done" || action === "return" || action === "start-page") {
      if (phase === "returning") return;
      flow++; hideFlow(); locked = null; phase = "returning";
      page({status: "Returning to browsing…"}); emit("return_browsing", {start_page: action === "start-page"});
    } else if (action === "again" && phase === "practice") {
      practiceStep = "idle"; renderPractice();
    } else if (action === "cancel" || action === "home") {
      flow++; emit("calibration_cancel"); home();
    } else if (action === "cursor") {
      flow++; emit("use_cursor"); hideFlow(); phase = "cursor"; shutdown();
      page({status: "Eye tracking off", actions: [["setup", "Set up eye tracking"]]});
    } else if (action === "retry" || action === "setup") restart();
  }
  function renderPractice() {
    const step = practiceStep, answered = step === "answer", retry = ["tap", "early", "cancelled", "interrupted"].includes(step);
    const title = step === "waiting" ? "Wait for Listening…" : step === "listening" ? "Listening" : answered ? "" : retry ? "Try the hold again" : "Ask about Saturn";
    practiceFace = faceVisible();
    const help = !practiceFace && !answered ? "Bring your face into view." : step === "waiting" ? "Keep holding Space." : step === "listening" ? "Say “What are these rings made of?”" :
      step === "tap" ? "Hold Space a little longer." : step === "early" ? "Wait for “Listening” before speaking." :
      step === "cancelled" ? "Practice cancelled. Hold Space to try again." : step === "interrupted" ? "Practice interrupted. Hold Space to try again." :
      answered ? "" : "Look at the rings, then hold Space.";
    example.hidden = !answered;
    practice.setAttribute("aria-hidden", String(answered));
    const parts = [];
    if (title) { const heading = make(["waiting", "listening"].includes(step) ? "div" : "h1", title, ["waiting", "listening"].includes(step) ? `practice-status glass${step === "listening" ? " live" : ""}` : ""); heading.id = "say"; parts.push(heading); }
    if (help) parts.push(make("p", help, "note"));
    if (step === "listening") parts.push(make("p", "Then release Space.", "note"));
    parts.push(buttons(answered ? [["return", "Return to browsing"], ["again", "Try again"]] : [["done", "Skip practice"]]),
      make("p", "This is practice. Your microphone is off.", "quiet"));
    bar.replaceChildren(...parts);
  }
  function interruptPractice(step) {
    if (phase !== "practice" || !holdStart) return;
    clearTimeout(holdTimer); clearTimeout(readyTimer); holdStart = 0; listening = false;
    practiceStep = step; renderPractice();
  }
  function showCheckDot() {
    phase = "checkIntro"; retryPoint = false; awaiting = false;
    const [x, y] = check.points[checkIndex]; moveDot(x, y);
    dot.classList.remove("collect", "travel"); dot.style.display = "block";
    progress(false); showCue(x, y);
  }
  function startCheckRun() {
    phase = "check"; showCue(...check.points[checkIndex]); dot.style.setProperty("--ms", `${check.settle_ms + check.observe_ms}ms`); dot.classList.add("collect");
    const owner = flow;
    checkTimer = setTimeout(() => {
      if (flow !== owner || phase !== "check") return;
      checkObserving = true;
      checkTimer = setTimeout(() => {
        if (flow !== owner || phase !== "check") return;
        checkObserving = false; awaiting = true; emit("check_trial", {index: checkIndex});
      }, check.observe_ms);
    }, check.settle_ms);
  }
  function practiceFrame() {
    if (phase !== "practice") return;
    if (performance.now() - seenAt > LOST_AFTER_MS) planet.classList.remove("selected");
    if (!faceVisible()) interruptPractice("interrupted");
    if (practiceFace !== faceVisible()) renderPractice();
  }
  addEventListener("keydown", e => {
    if (!e.isTrusted) return;
    if (e.code === "Escape" && phase === "practice") { e.preventDefault(); interruptPractice("cancelled"); return; }
    if (e.code === "Escape" && ["calibrate", "boundary", "checkIntro", "check", "waiting"].includes(phase)) {
      e.preventDefault(); flow++; emit("calibration_cancel"); home(); return;
    }
    if (e.code !== "Space") return;
    const fresh = !spaceDown && !e.repeat; spaceDown = true;
    if (["calibrate", "checkIntro", "check"].includes(phase)) {
      if (e.target.closest("button")) return;
      e.preventDefault();
      if (!fresh || !faceVisible() || collecting || awaiting) return;
      if (phase === "checkIntro") { startCheckRun(); return; }
      if (phase !== "calibrate" || index < 0) return;
      collecting = true; retryPoint = false; until = performance.now() + 1100; dot.style.setProperty("--ms", "1100ms"); dot.classList.remove("shake"); dot.classList.add("collect"); showCue(...POINTS[index]);
    } else if (phase === "boundary") {
      // Only an explicit trusted control activation starts the held-out check.
      if (!e.target.closest("button")) e.preventDefault();
    } else if (phase === "practice" && !e.target.closest("button")) {
      e.preventDefault(); if (!fresh || practiceStep === "answer" || holdStart || !faceVisible()) return;
      holdStart = performance.now(); const owner = flow;
      holdTimer = setTimeout(() => {
        if (flow !== owner || phase !== "practice" || !holdStart) return;
        practiceStep = "waiting"; renderPractice();
        readyTimer = setTimeout(() => {
          if (flow !== owner || phase !== "practice" || !holdStart) return;
          listening = true; practiceStep = "listening"; renderPractice();
        }, READY_MS);
      }, TAP_HOLD_MS);
    }
  }, true);
  addEventListener("keyup", e => {
    if (!e.isTrusted || e.code !== "Space") return;
    spaceDown = false;
    if (phase !== "practice" || !holdStart) return;
    e.preventDefault(); clearTimeout(holdTimer); clearTimeout(readyTimer);
    const elapsed = performance.now() - holdStart; holdStart = 0;
    practiceStep = listening ? "answer" : elapsed < TAP_HOLD_MS ? "tap" : "early";
    if (listening && !rehearsed) { rehearsed = true; emit("practice_complete"); }
    listening = false; renderPractice();
  }, true);
  addEventListener("blur", () => { spaceDown = false; interruptPractice("interrupted"); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) interruptPractice("interrupted"); });
  function shutdown() {
    flow++;
    active = false; clearInterval(timer); clearInterval(practiceTick); stream?.getTracks().forEach(t => t.stop()); try { model?.close(); } catch {}
    model = null; stream = null; video.srcObject = null; preview.srcObject = null;
  }
  addEventListener("pagehide", () => { shutdown(); hideFlow(); }, {once: true});
  globalThis.__HERMES_WEBCAM__ = {
    stop() { shutdown(); hideFlow(); },
    beginSetup(value) {
      setup = value; flow++; emit("calibration_cancel");
      if (active && stream) home();
      else if (phase !== "error") restart();
    },
    returnResult(result) {
      if (phase !== "returning") return;
      phase = result.ok ? "tracking" : "return-error";
      if (result.ok) page({status: "Eye tracking", notes: ["Keep this window open for eye tracking."], actions: [["return", "Return to browsing"], ["calibrate", "Calibrate again"], CURSOR]});
      else page({status: result.missing ? "That page is no longer available" : "Couldn’t bring your page forward",
        notes: ["Your calibration is saved. Eye tracking stays on.", result.error || ""],
        actions: [["return", "Try again"], ["start-page", "Open start page"], CURSOR]});
    },
    pointAccepted() { if (phase !== "calibrate" || !awaiting) return; awaiting = false; dot.classList.remove("collect"); index++; if (index < POINTS.length) place(); },
    pointRetry() {
      if (phase !== "calibrate") return;
      awaiting = false; collecting = false; retryPoint = true;
      dot.classList.remove("collect"); showCue(...POINTS[index]);
    },
    calibrationFailed() { hideFlow(); phase = "result";
      page({status: "Couldn’t calibrate", notes: ["Try even lighting and a steady position."], kept: calibrated ? "Saved calibration unchanged." : "", actions: [["calibrate", "Calibrate again"], CURSOR]}); },
    checkBoundary(value) {
      if (phase !== "calibrate") return;
      hideFlow(); check = value; phase = "boundary";
      page({status: "Ready to check", actions: [["start-check", "Start accuracy check"], ["cancel", "Cancel"]]});
      faceNote.className = "note kept"; main.append(faceNote);
      document.activeElement?.blur();
    },
    checkReady(value) {
      if (phase !== "waiting") return;
      hideFlow(); check = value; checkIndex = 0; main.style.display = "none"; setFocus(true); showCheckDot();
    },
    checkAccepted() { if (phase !== "check" || !awaiting) return; checkIndex++; showCheckDot(); },
    checkResult(result) {
      hideFlow(); phase = "result"; locked = null; calibrated = result.calibrated;
      if (calibrated) notice = "";
      page({status: result.note, notes: [result.detail], kept: result.kept ? "Saved calibration unchanged." : "", actions: result.outcome === "good" ? result.actions : [...result.actions, CURSOR]});
    },
    practiceReady() {
      hideFlow(); phase = "practice"; practiceStep = "idle"; main.style.display = "none"; seenAt = performance.now(); document.body.classList.add("practising");
      practice.style.display = "";
      bar.style.display = "flex"; renderPractice(); document.activeElement?.blur();
    },
    practiceGaze(value) {
      if (phase !== "practice") return;
      planet.classList.remove("selected");
      if (value.lost) return;
      seenAt = performance.now();
      const x = (Math.floor(value.x * REGION_COLS - 1e-9) + .5) / REGION_COLS, y = (Math.floor(value.y * REGION_ROWS - 1e-9) + .5) / REGION_ROWS;
      const r = planet.getBoundingClientRect();
      if (x * innerWidth >= r.left && x * innerWidth <= r.right && y * innerHeight >= r.top && y * innerHeight <= r.bottom) planet.classList.add("selected");
    },
    notice(text) { notice = text; home(); },
    cameraFailed() { fatal("Camera stopped"); },
    status() { return {active, phase, flow, setup, index, collecting, checkIndex, practiceStep, face: faceVisible(), videoTime: video.currentTime, hidden: document.hidden,
      frames, frame_ms: frames ? frameMs / frames : null, feature_ms: frames ? featureMs / frames : null,
      sample_hz: frames > 1 ? (frames - 1) * 1000 / (lastFrame - firstFrame) : null}; }
  };
  function tick() {
    if (!active) return;
    if (stream && stream.getVideoTracks().every(track => track.readyState === "ended")) {
      emit("error", {error: "Camera video track stopped"}); fatal("Camera stopped"); return;
    }
    if (locked && ["calibrate", "boundary", "waiting", "checkIntro", "check", "practice"].includes(phase) &&
        ((document.hidden && phase !== "practice") || locked.some((v, i) => v !== windowNow()[i]))) {
      flow++; emit("calibration_cancel"); hideFlow(); locked = null; phase = "moved";
      page({status: MOVED, notes: ["Keep this window on one screen."], kept: calibrated ? "Saved calibration unchanged." : "", actions: [["home", "Restart setup"], CURSOR]}); return;
    }
    updateFace();
    if (video.readyState < 2 || video.currentTime === lastVideoTime) return;
    lastVideoTime = video.currentTime;
    const now = performance.now(), t = (performance.timeOrigin + now) / 1000;
    try {
      const lm = model.detectForVideo(video, now).faceLandmarks[0];
      const featureStart = performance.now();
      const f = globalThis.__lookAppearance(video, lm, globalThis.__lookFeatures(lm), true);
      const done = performance.now();
      frameMs += done - now; featureMs += done - featureStart;
      if (!lm) faceAt = 0;
      if (!frames) firstFrame = now;
      frames++; lastFrame = now;
      if (f) { faceAt = now; if (phase === "home") followFace(lm); }
      updateFace();
      emit("sample", {t, features: f, calibration: collecting ? index : -1, check: checkObserving ? checkIndex : -1, hidden: document.hidden});
      if (collecting && now >= until) { collecting = false; awaiting = true; emit("calibration_point", {index}); }
    } catch (e) { emit("error", {error: String(e)}); fatal("Camera stopped"); }
  }
  async function openCamera() {
    const owner = flow;
    if (!model) {
      const {FaceLandmarker} = await import(opts.module);
      if (owner !== flow) return;
      // Python installs the checksum-verified SIMD loader into this isolated context.
      const files = {wasmBinaryPath: opts.wasm + "/vision_wasm_internal.wasm"};
      const loaded = await FaceLandmarker.createFromOptions(files, {baseOptions: {modelAssetPath: opts.model, delegate: "CPU"},
        runningMode: "VIDEO", numFaces: 1, minFaceDetectionConfidence: .5, minFacePresenceConfidence: .5});
      if (owner !== flow) { loaded.close(); return; }
      model = loaded;
    }
    if (owner !== flow) return;
    emit("opening_camera");
    const acquired = await navigator.mediaDevices.getUserMedia({video: {width: 640, height: 480}, audio: false});
    if (owner !== flow) { acquired.getTracks().forEach(t => t.stop()); return; }
    stream = acquired;
    video.srcObject = stream; await video.play();
    if (owner !== flow) return;
    active = true; lastVideoTime = -1;
    timer = setInterval(tick, 100); // Timers, not requestAnimationFrame: this owned process disables background throttling.
    clearInterval(practiceTick); practiceTick = setInterval(practiceFrame, 150);
    emit("ready"); home();
  }
  function failedToOpen(e) { emit("error", {error: String(e)}); fatal(cameraLabel(e)); }
  async function restart() {
    flow++; hideFlow(); locked = null; phase = "start"; page({camera: "empty", waking: true, actions: [CURSOR]});
    emit("retry_camera");
    const owner = flow;
    try { await openCamera(); } catch (e) { if (owner === flow) failedToOpen(e); }
  }
  page({camera: "empty", waking: true, actions: [CURSOR]});
  const owner = flow;
  try { await openCamera(); } catch (e) { if (owner === flow) failedToOpen(e); }
})
