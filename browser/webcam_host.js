// Loaded by CDP only, in the tracker window's isolated world. No website runs here.
(async function (opts) {
  "use strict";
  const emit = (type, data = {}) => __hermesGazeIntent(JSON.stringify({type, nonce: opts.nonce, ...data}));
  const make = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; };
  const style = make("style");
  // Material values are the companion's glass plate (browser/overlay.js) and type (browser/panel.js).
  style.textContent = `
    :root { color-scheme:light dark; --ground:#efeff2; --label:rgba(0,0,0,.86); --secondary:rgba(60,60,67,.72); --tertiary:rgba(60,60,67,.5);
      --accent:#0066d6; --tint:rgba(0,102,214,.11); --bars:#0a6fe0; --hover:rgba(0,0,0,.055); --line:rgba(0,0,0,.09);
      --fill:rgba(250,250,252,.8); --blur:blur(34px) saturate(1.9); --sheen:rgba(255,255,255,.42);
      --shadow:0 0 0 .5px rgba(0,0,0,.13),0 12px 36px rgba(0,0,0,.17),0 3px 8px rgba(0,0,0,.07),inset 0 .5px 0 rgba(255,255,255,.75);
      --quiet:0 0 0 .5px rgba(0,0,0,.11),0 5px 16px rgba(0,0,0,.07),inset 0 .5px 0 rgba(255,255,255,.75);
      --dot:#111316; --tube:rgba(250,250,252,.92); --tube-edge:rgba(0,0,0,.26); --trace:rgba(17,19,22,.36); --hollow:rgba(60,60,67,.55);
      --region:rgba(0,0,0,.05); --region-edge:rgba(0,0,0,.16); }
    @media (prefers-color-scheme: dark) { :root { --ground:#1b1b1e; --label:rgba(255,255,255,.92); --secondary:rgba(235,235,245,.68); --tertiary:rgba(235,235,245,.42);
      --accent:#4ea1ff; --tint:rgba(78,161,255,.17); --bars:#5facff; --hover:rgba(255,255,255,.08); --line:rgba(255,255,255,.11);
      --fill:rgba(40,40,44,.76); --blur:blur(34px) saturate(1.7); --sheen:rgba(255,255,255,.07);
      --shadow:0 0 0 .5px rgba(255,255,255,.15),0 14px 44px rgba(0,0,0,.55),0 3px 8px rgba(0,0,0,.3),inset 0 .5px 0 rgba(255,255,255,.1);
      --quiet:0 0 0 .5px rgba(255,255,255,.13),0 5px 16px rgba(0,0,0,.3),inset 0 .5px 0 rgba(255,255,255,.1);
      --dot:#fff; --tube:rgba(64,64,70,.92); --tube-edge:rgba(255,255,255,.3); --trace:rgba(255,255,255,.4); --hollow:rgba(235,235,245,.4);
      --region:rgba(255,255,255,.07); --region-edge:rgba(255,255,255,.24); }
      /* The screen is the light on the face: the dots and check always use the bright field. */
      body.focus { --ground:#dfdfe3; --label:rgba(0,0,0,.86); --secondary:rgba(60,60,67,.72); --line:rgba(0,0,0,.09);
        --fill:rgba(250,250,252,.8); --blur:blur(34px) saturate(1.9); --sheen:rgba(255,255,255,.42); --dot:#111316;
        --quiet:0 0 0 .5px rgba(0,0,0,.11),0 5px 16px rgba(0,0,0,.07),inset 0 .5px 0 rgba(255,255,255,.75); } }
    * { box-sizing:border-box; }
    html,body { height:100%; margin:0; }
    body { background:var(--ground); color:var(--label); overflow:hidden; -webkit-font-smoothing:antialiased; letter-spacing:-.006em; cursor:default;
      font:15px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif; transition:background-color .6s ease; }
    .glass { background:linear-gradient(180deg,var(--sheen),transparent 46%),var(--fill); -webkit-backdrop-filter:var(--blur); backdrop-filter:var(--blur); box-shadow:var(--shadow); }
    #beta { position:fixed; left:28px; top:24px; margin:0; font-size:13px; color:var(--tertiary); }
    body.focus #beta,body.practising #beta { display:none; }
    main { position:fixed; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:14px; padding:24px; }
    main.at-map { justify-content:flex-end; padding-bottom:34px; pointer-events:none; }
    main.at-map > * { pointer-events:auto; }
    .arrive { animation:arrive .42s cubic-bezier(.2,.8,.2,1) both; }
    @keyframes arrive { from { opacity:0; transform:translateY(8px) scale(.985); } }
    #feed { position:fixed; left:0; top:0; width:2px; height:2px; opacity:0; pointer-events:none; }
    .face { position:relative; width:min(336px,46vh); height:min(336px,46vh); border-radius:50%; padding:9px; flex:none; margin-bottom:6px; }
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
    .note { margin:0; font-size:13px; color:var(--secondary); text-align:center; }
    .note.notice { color:var(--label); font-weight:500; }
    .note.kept { color:var(--tertiary); margin-top:-8px; }
    .detail { margin:0; max-width:420px; font-size:12px; color:var(--tertiary); text-align:center; overflow-wrap:anywhere; }
    .row { display:inline-flex; align-items:center; gap:3px; padding:5px; border-radius:26px; margin-top:6px; max-width:calc(100vw - 32px); }
    button { all:unset; box-sizing:border-box; white-space:nowrap; height:38px; line-height:38px; padding:0 18px; border-radius:19px; font-size:14px; font-weight:400; color:var(--secondary); transition:background-color .16s ease,opacity .16s ease; }
    button:hover { background-color:var(--hover); }
    button.primary { background-color:var(--tint); color:var(--accent); font-weight:600; }
    button.primary:hover { filter:brightness(1.05); }
    button:active { opacity:.72; }
    button:disabled { opacity:.42; filter:none; background-color:transparent; }
    button.primary:disabled { background-color:var(--hover); color:var(--secondary); }
    button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
    .key { display:inline-block; padding:0 12px; height:25px; line-height:24px; border-radius:7px; font-size:12.5px; font-weight:500; color:var(--label); background:linear-gradient(180deg,var(--sheen),transparent 60%),var(--fill);
      box-shadow:0 0 0 .5px var(--line),0 1.5px 0 var(--line),0 3px 8px rgba(0,0,0,.08),inset 0 .5px 0 var(--sheen); vertical-align:baseline; transition:transform .1s ease,box-shadow .1s ease; }
    .key.down { transform:translateY(1.5px); box-shadow:0 0 0 .5px var(--line),inset 0 .5px 0 var(--sheen); }
    #dot { position:fixed; left:0; top:0; width:0; height:0; display:none; transition:transform .55s cubic-bezier(.3,.7,.2,1); }
    #dot .disc,#dot .pt { position:absolute; border-radius:50%; }
    #dot .disc { left:-56px; top:-56px; width:112px; height:112px; box-shadow:var(--quiet); transition:transform .42s cubic-bezier(.2,.9,.3,1); }
    #dot .pt { left:-5.5px; top:-5.5px; width:11px; height:11px; background:var(--dot); transition:transform .3s ease; }
    #dot.collect .disc { transform:scale(.27); transition:transform var(--ms,1.1s) cubic-bezier(.45,0,.55,1); }
    #dot.collect .pt { transform:scale(1.9); transition:transform var(--ms,1.1s) cubic-bezier(.45,0,.55,1); }
    #dot.travel .disc { transform:scale(.38); }
    #dot.shake { animation:shake .34s ease; }
    @keyframes shake { 25% { margin-left:-7px; } 60% { margin-left:6px; } 85% { margin-left:-2px; } }
    .echo { position:fixed; left:0; top:0; width:30px; height:30px; margin:-15px 0 0 -15px; border-radius:50%; pointer-events:none; box-shadow:0 0 0 1px var(--dot); opacity:0; animation:echo .5s ease-out forwards; }
    @keyframes echo { from { opacity:.34; scale:1; } to { opacity:0; scale:2.7; } }
    #cue { position:fixed; left:0; top:0; display:none; align-items:center; gap:7px; font-size:13px; color:var(--secondary); white-space:nowrap; transition:opacity .2s ease; }
    #map,#marks { position:fixed; inset:0; pointer-events:none; }
    #marks { width:100%; height:100%; overflow:visible; }
    .place { position:absolute; width:92px; height:92px; margin:-46px 0 0 -46px; border-radius:50%; animation:settle .5s cubic-bezier(.2,.9,.3,1) both; }
    @keyframes settle { from { opacity:0; transform:scale(.72); } }
    .pop { transform-box:fill-box; transform-origin:center; animation:pop .4s cubic-bezier(.2,.9,.3,1) both; }
    @keyframes pop { from { opacity:0; transform:scale(.3); } }
    .draw { animation:draw .55s ease-out both; }
    @keyframes draw { from { stroke-dashoffset:1; } to { stroke-dashoffset:0; } }
    #practice { position:fixed; inset:0; display:none; padding:24px 24px 88px; grid:1fr 1fr / 1fr 1fr 1fr; gap:14px; }
    .topic { display:grid; place-items:center; border-radius:22px; box-shadow:var(--quiet); background:var(--fill); font:500 24px/1.2 -apple-system,BlinkMacSystemFont,"SF Pro Display",system-ui,sans-serif; letter-spacing:-.018em; }
    #region { position:fixed; left:0; top:0; width:42vmin; height:42vmin; margin:-21vmin 0 0 -21vmin; border-radius:50%; pointer-events:none; opacity:0;
      background:var(--region); box-shadow:0 0 0 .5px var(--region-edge),0 6px 22px rgba(0,0,0,.09),inset 0 .5px 0 var(--sheen); transition:transform .3s cubic-bezier(.3,.7,.3,1),opacity .35s ease; }
    #bar { position:fixed; left:50%; bottom:22px; transform:translateX(-50%); display:none; align-items:center; gap:3px; max-width:calc(100vw - 32px); padding:5px 5px 5px 20px; border-radius:26px; }
    #bar .words { display:inline-flex; align-items:center; gap:6px; white-space:nowrap; margin-right:14px; font-size:13px; color:var(--secondary); }
    #lesson { display:flex; flex-direction:column; align-items:center; gap:14px; margin-bottom:10px; }
    #say { display:flex; align-items:center; gap:12px; font:500 22px/1.2 -apple-system,BlinkMacSystemFont,"SF Pro Display",system-ui,sans-serif; letter-spacing:-.018em; }
    #say .key { height:44px; line-height:43px; padding:0 34px; border-radius:11px; font-size:17px; }
    #capsule { display:flex; align-items:center; gap:10px; height:36px; padding:0 16px 0 14px; border-radius:18px; font-size:12.5px; font-weight:500; color:var(--label); opacity:0; transform:translateY(5px); transition:opacity .2s ease,transform .2s ease; }
    #capsule.on { opacity:1; transform:none; }
    #capsule .bars { display:flex; align-items:center; gap:2.4px; height:18px; }
    #capsule .bars i { width:2.6px; height:16px; border-radius:1.3px; background:var(--bars); transform:scaleY(.22); }
    #capsule.on .bars i { animation:level 1.05s ease-in-out infinite; }
    #capsule.on .bars i:nth-child(2n) { animation-delay:-.32s; }
    #capsule.on .bars i:nth-child(3n) { animation-delay:-.61s; }
    @keyframes level { 50% { transform:scaleY(.86); } }
    #rehearse { min-height:18px; }
    @media (max-width:760px) { #bar { flex-wrap:wrap; border-radius:22px; } #bar .words { white-space:normal; } }
    @media (prefers-reduced-motion: reduce) { .arrive,.place,.pop,.draw,.face.waking,#dot.shake,#capsule.on .bars i { animation:none; } .echo { display:none; }
      body,#dot,#dot .disc,#dot .pt,#dot.collect .disc,#dot.collect .pt,#region,.you { transition:none; } #capsule.on .bars i { transform:scaleY(.6); } }
    @media (prefers-reduced-transparency: reduce) { :root,body.focus { --fill:rgb(250,250,252); --sheen:transparent; --blur:none; }
      .glass { -webkit-backdrop-filter:none; backdrop-filter:none; } }
    @media (prefers-reduced-transparency: reduce) and (prefers-color-scheme: dark) { :root { --fill:rgb(44,44,47); }
      body.focus { --fill:rgb(250,250,252); } }`;
  document.head.append(style);
  document.title = "Hermes Gaze";
  const beta = make("p", "Eye tracking beta"); beta.id = "beta";
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
  const map = make("div"); map.id = "map";
  const marks = document.createElementNS("http://www.w3.org/2000/svg", "svg"); marks.id = "marks";
  const practice = make("div"); practice.id = "practice";
  for (const topic of ["Saturn’s rings", "Coral reefs", "Sourdough", "The Silk Road", "Honeybees", "Northern lights"]) practice.append(make("div", topic, "topic glass"));
  const region = make("div"); region.id = "region";
  const bar = make("div", "", "glass"); bar.id = "bar";
  const barText = make("span", "", "words");
  const capsule = make("div", "", "glass"); capsule.id = "capsule";
  const bars = make("span", "", "bars"); for (let i = 0; i < 9; i++) bars.append(make("i"));
  capsule.append(bars, make("span", "Listening"));
  const lessonKey = make("span", "Space", "key");
  const say = make("div"); say.id = "say"; say.append(make("span", "Hold"), lessonKey, make("span", "in Chrome to ask"));
  const lesson = make("div"); lesson.id = "lesson"; lesson.append(capsule, say);
  const rehearse = make("p", "", "note"); rehearse.id = "rehearse";
  document.body.append(video, beta, main, map, marks, practice, region, dot, cue, bar);

  const POINTS = [.1, .5, .9].flatMap(y => [.1, .5, .9].map(x => [x, y]));
  const NO_EYES = "Couldn’t see your eyes", OFF_SCREEN = "Off screen", MOVED = "Window moved";
  const STAYS = "Stays in this window", STAYS_AND_OPEN = "Stays in this window. Leave open to keep tracking.";
  const CURSOR = ["cursor", "Use cursor"];
  // Display only: a coarse cell, so the area never reads as a precise pointer.
  const REGION_COLS = 8, REGION_ROWS = 6, LOST_AFTER_MS = 700, TAP_HOLD_MS = 220;
  const CHECK_CUE_DELAY_MS = 3500;
  // Face cue, in fractions of the round picture. Fixed by eye; it is a hint, not a gate.
  const GUIDE = {x: .5, y: .48, size: .62}, FIT = {x: .075, y: .085, size: .14}, HEAD_SPAN = 1.65;

  let model, stream, timer, active = true, index = -1, collecting = false, until = 0, lastVideoTime = -1, awaiting = false;
  let frames = 0, firstFrame = 0, lastFrame = 0, frameMs = 0, featureMs = 0;
  let phase = "start", locked = null, calibrated = !!opts.calibrated, notice = opts.calibration_notice || "", faceAt = 0;
  let check = null, checkIndex = -1, checkObserving = false, checkTimer = 0, cueTimer = 0;
  let seenAt = 0, lostWhy = "", barWords = "", practiceTick = 0;
  let holdStart = 0, holdTimer = 0, afterDots = false, shownMap = null;

  const windowNow = () => [screenX, screenY, innerWidth, innerHeight, devicePixelRatio];
  const faceVisible = () => performance.now() - faceAt < 800;
  function setFocus(on) { document.body.classList.toggle("focus", on); document.body.classList.toggle("calibrating", on); }

  function buttons(list) {
    const row = make("div", "", "row glass");
    list.forEach(([action, label, disabled], i) => {
      const b = make("button", label, i === 0 && action !== "cursor" ? "primary" : "");
      b.dataset.action = action; b.disabled = !!disabled; b.addEventListener("click", e => act(action, e)); row.append(b);
    });
    return row;
  }
  // Every full page: optional round picture, only the words that can't be drawn, one capsule of actions.
  function page({camera = "", waking = false, status = "", notes = [], kept = "", detail = "", extra = [], actions = [], atMap = false}) {
    const parts = [];
    if (camera) {
      const live = camera === "live" && stream;
      face.classList.toggle("off", !live); face.classList.toggle("waking", waking); face.classList.remove("placed");
      if (live) { preview.srcObject = stream; preview.play().catch(() => {}); }
      parts.push(face);
    }
    parts.push(...extra);
    if (status) parts.push(make("p", status, "note notice"));
    for (const line of notes) if (line) parts.push(make("p", line, "note"));
    if (kept) parts.push(make("p", kept, "note kept"));
    if (detail) parts.push(make("p", detail, "detail"));
    if (actions.length) parts.push(buttons(actions));
    main.replaceChildren(...parts); main.className = atMap ? "at-map" : ""; main.style.display = "";
    for (const part of parts) { part.classList.remove("arrive"); void part.offsetWidth; part.classList.add("arrive"); }
    updateFace();
  }
  function updateFace() {
    if (!stream) return;
    const begin = main.querySelector('[data-action="calibrate"]');
    if (begin && phase === "home" && !calibrated) begin.disabled = !faceVisible();
    if (!faceVisible()) { you.style.opacity = "0"; face.classList.remove("placed"); }
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
    if (calibrated) page({camera: "live", status: notice, notes: [STAYS_AND_OPEN], actions: [["check", "Check my gaze"], ["calibrate", "Recalibrate"], CURSOR]});
    else page({camera: "live", status: notice, notes: [STAYS], actions: [["calibrate", "Begin", !faceVisible()], CURSOR]});
    notice = "";
  }
  function hideFlow() {
    index = -1; collecting = false; awaiting = false; checkObserving = false; checkIndex = -1; clearTimeout(checkTimer); clearTimeout(cueTimer); check = null;
    dot.style.display = "none"; cue.style.display = "none"; practice.style.display = "none"; bar.style.display = "none"; region.style.opacity = "0";
    dot.classList.remove("collect", "travel", "shake"); setFocus(false); document.body.classList.remove("practising"); drawMap(null);
  }
  function fatal(raw, label, showRaw) {
    active = false; clearInterval(timer); stream?.getTracks().forEach(t => t.stop()); stream = null; video.srcObject = null; preview.srcObject = null;
    hideFlow(); phase = "error";
    page({camera: "empty", status: label, detail: showRaw ? raw : "", actions: [["retry", "Try again"], CURSOR]});
  }
  function cameraLabel(e) {
    const name = e && e.name;
    if (name === "NotAllowedError") return ["Camera blocked", false];
    if (name === "NotFoundError") return ["No camera", false];
    if (name === "NotReadableError") return ["Camera in use", false];
    return ["Camera stopped", true];
  }
  function moveDot(x, y) { dot.style.transform = `translate(${x * innerWidth}px,${y * innerHeight}px)`; }
  function showCue(x, y, line) {
    const key = make("span", "Space", "key");
    cue.replaceChildren(...(line ? [make("span", line), make("span", "·")] : []), make("span", "Tap"), key);
    cue.style.display = "flex";
    const r = cue.getBoundingClientRect();
    const px = Math.min(innerWidth - r.width - 16, Math.max(16, x * innerWidth - r.width / 2));
    const py = y > .7 ? y * innerHeight - r.height - 74 : y * innerHeight + 72;
    cue.style.transform = `translate(${px}px,${py}px)`;
  }
  function place() {
    const [x, y] = POINTS[index]; moveDot(x, y); dot.classList.remove("collect", "shake");
    if (index === 0) showCue(x, y);
  }
  function release() {
    const [x, y] = POINTS[index];
    const echo = make("div", "", "echo"); echo.style.transform = `translate(${x * innerWidth}px,${y * innerHeight}px)`;
    echo.addEventListener("animationend", () => echo.remove()); document.body.append(echo);
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
      hideFlow(); phase = "calibrate"; index = 0; afterDots = true; main.style.display = "none"; setFocus(true); dot.style.display = "block";
      emit("calibration_start", measure(e)); place();
    } else if (action === "check" && stream) {
      hideFlow(); phase = "waiting"; afterDots = false; emit("check_start", measure(e));
    } else if (action === "practise" && stream) {
      hideFlow(); phase = "waiting"; emit("practice_start", measure(e));
    } else if (action === "done") {
      if (phase === "practice") emit("practice_end");
      handoff();
    } else if (action === "home") {
      home();
    } else if (action === "cursor") {
      emit("use_cursor"); hideFlow(); phase = "closing"; shutdown();
      page({camera: "empty", status: "Camera off"});
    } else if (action === "retry") {
      restart();
    }
  }
  function handoff() {
    hideFlow(); phase = "handoff"; locked = null;
    rehearse.textContent = ""; lessonKey.classList.remove("down"); capsule.classList.remove("on");
    page({extra: [lesson, rehearse], notes: ["Move the pointer once on each page"], actions: [["home", "Done"], CURSOR]});
  }
  function waitForCheck() {
    // The same dot and the same tap as the nine dots; words only if nothing happens.
    phase = "checkIntro"; main.style.display = "none"; setFocus(true); checkIndex = -1;
    const [x, y] = check.points[0]; moveDot(x, y); dot.classList.remove("collect", "travel"); dot.style.display = "block";
    clearTimeout(cueTimer);
    cueTimer = setTimeout(() => { if (phase === "checkIntro") showCue(x, y); }, afterDots ? CHECK_CUE_DELAY_MS : 0);
  }
  function startCheckRun() {
    clearTimeout(cueTimer); cue.style.display = "none";
    phase = "check"; dot.classList.add("travel");
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
  // The result is the map: closed glass where both landings were inside, open where one wasn't.
  function drawMap(places) {
    shownMap = places; map.replaceChildren(); marks.replaceChildren();
    if (!places) return;
    const R = 46, W = innerWidth, H = innerHeight, NS = marks.namespaceURI;
    const svg = (tag, attrs, parent = marks) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); parent.append(n); return n; };
    const line = (parent, x1, y1, x2, y2, attrs) => svg("line", {x1, y1, x2, y2, pathLength: 1, "stroke-dasharray": 1, class: "draw", ...attrs}, parent);
    places.forEach((p, i) => {
      const cx = p.x * W, cy = p.y * H, misses = p.trials.filter(t => !t.hit), landed = misses.find(t => "x" in t);
      const hits = p.trials.filter(t => t.hit), delay = i * .07;
      if (!misses.length) {
        const plate = make("div", "", "place glass"); plate.style.left = `${cx}px`; plate.style.top = `${cy}px`; plate.style.animationDelay = `${delay}s`; map.append(plate);
      } else if (!landed && !hits.length) {
        svg("circle", {cx, cy, r: R, fill: "none", stroke: "var(--hollow)", "stroke-width": 2.25, "stroke-linecap": "round", "stroke-dasharray": "0.1 7", class: "pop", style: `animation-delay:${delay}s`});
      } else {
        const toward = landed ? Math.atan2(landed.y * H - cy, landed.x * W - cx) : -Math.PI / 2;
        const a0 = toward + .62, a1 = toward + Math.PI * 2 - .62;
        const d = `M${cx + R * Math.cos(a0)} ${cy + R * Math.sin(a0)}A${R} ${R} 0 1 1 ${cx + R * Math.cos(a1)} ${cy + R * Math.sin(a1)}`;
        const tube = svg("g", {class: "pop", style: `animation-delay:${delay}s;filter:drop-shadow(0 4px 9px rgba(0,0,0,.2))`});
        svg("path", {d, fill: "none", stroke: "var(--tube-edge)", "stroke-width": 11, "stroke-linecap": "round"}, tube);
        svg("path", {d, fill: "none", stroke: "var(--tube)", "stroke-width": 10, "stroke-linecap": "round"}, tube);
      }
      p.trials.forEach((t, j) => {
        const at = delay + .18 + j * .07;
        if (t.hit) svg("circle", {cx: cx + t.dx * R * .62, cy: cy + t.dy * R * .62, r: 5.5, fill: "var(--dot)", class: "pop", style: `animation-delay:${at}s`});
        else if ("x" in t) {
          const x = t.x * W, y = t.y * H;
          line(marks, cx, cy, x, y, {stroke: "var(--trace)", "stroke-width": 1, style: `animation-delay:${at}s`});
          svg("circle", {cx: x, cy: y, r: 5.5, fill: "var(--dot)", class: "pop", style: `animation-delay:${at + .25}s`});
        }
      });
    });
  }
  addEventListener("resize", () => { if (phase === "result" && shownMap) drawMap(shownMap); });
  function setPracticeWords(kind) {
    if (kind === barWords) return;
    barWords = kind;
    if (kind === "hold") barText.replaceChildren(make("span", "Hold"), make("span", "Space", "key"), make("span", "in Chrome to ask"));
    else barText.textContent = kind;
  }
  function practiceFrame() {
    if (phase !== "practice") return;
    if (performance.now() - seenAt > LOST_AFTER_MS) {
      region.style.opacity = "0";
      setPracticeWords(lostWhy === "offscreen" ? OFF_SCREEN : NO_EYES);
    } else setPracticeWords("hold");
  }
  addEventListener("keydown", e => {
    if (!e.isTrusted) return;
    if (e.code === "Escape" && ["calibrate", "checkIntro", "check", "practice", "waiting"].includes(phase)) {
      emit("calibration_cancel"); home(); return;
    }
    if (e.code !== "Space") return;
    if (phase === "calibrate") {
      e.preventDefault();
      if (e.repeat || collecting || awaiting || index < 0) return;
      collecting = true; until = performance.now() + 1100; dot.classList.remove("shake"); dot.classList.add("collect"); cue.style.display = "none";
    } else if (phase === "checkIntro") {
      e.preventDefault(); if (!e.repeat) startCheckRun();
    } else if (phase === "handoff") {
      e.preventDefault(); if (e.repeat || holdStart) return;
      holdStart = performance.now(); lessonKey.classList.add("down");
      holdTimer = setTimeout(() => { capsule.classList.add("on"); rehearse.textContent = "Only a rehearsal"; }, TAP_HOLD_MS);
    }
  }, true);
  addEventListener("keyup", e => {
    if (!e.isTrusted || e.code !== "Space" || phase !== "handoff" || !holdStart) return;
    e.preventDefault(); clearTimeout(holdTimer);
    const held = performance.now() - holdStart; holdStart = 0; lessonKey.classList.remove("down"); capsule.classList.remove("on");
    rehearse.textContent = held >= TAP_HOLD_MS ? "In Chrome, this asks" : "Hold longer";
  }, true);
  function shutdown() {
    active = false; clearInterval(timer); clearInterval(practiceTick); stream?.getTracks().forEach(t => t.stop()); try { model?.close(); } catch {}
    model = null; stream = null; video.srcObject = null; preview.srcObject = null;
  }
  addEventListener("pagehide", () => { shutdown(); hideFlow(); }, {once: true});
  globalThis.__HERMES_WEBCAM__ = {
    stop() { shutdown(); hideFlow(); },
    pointAccepted() { awaiting = false; release(); dot.classList.remove("collect"); index++; if (index < POINTS.length) place(); },
    pointRetry() {
      awaiting = false; collecting = false;
      dot.classList.remove("collect", "shake"); void dot.offsetWidth; dot.classList.add("shake");
      showCue(...POINTS[index], NO_EYES);
    },
    calibrationFailed() { hideFlow(); phase = "result";
      page({camera: "live", status: "Adjust light or position", kept: calibrated ? "Earlier setup kept" : "", actions: [["calibrate", "Try again"], CURSOR]}); },
    checkReady(value) { hideFlow(); check = value; waitForCheck(); },
    checkResult(result) {
      hideFlow(); phase = "result"; locked = null; calibrated = result.calibrated;
      drawMap(result.map);
      page({atMap: true, status: result.note, kept: result.kept ? "Earlier setup kept" : "", actions: [...result.actions, CURSOR]});
    },
    practiceReady() {
      hideFlow(); phase = "practice"; main.style.display = "none"; seenAt = performance.now(); lostWhy = "face"; barWords = ""; document.body.classList.add("practising");
      practice.style.display = "grid"; bar.style.display = "flex";
      bar.replaceChildren(barText, ...[...buttons([["done", "Done"], ["calibrate", "Recalibrate"], CURSOR]).children]);
      setPracticeWords("hold");
    },
    practiceGaze(value) {
      if (phase !== "practice") return;
      if (value.lost) { lostWhy = value.lost; return; }
      seenAt = performance.now();
      const x = (Math.floor(value.x * REGION_COLS - 1e-9) + .5) / REGION_COLS, y = (Math.floor(value.y * REGION_ROWS - 1e-9) + .5) / REGION_ROWS;
      region.style.transform = `translate(${x * innerWidth}px,${y * innerHeight}px)`; region.style.opacity = "1";
    },
    notice(text) { notice = text; home(); },
    cameraFailed(raw) { fatal(raw, "Camera stopped", false); },
    status() { return {active, phase, index, collecting, checkIndex, face: faceVisible(), videoTime: video.currentTime, hidden: document.hidden,
      frames, frame_ms: frames ? frameMs / frames : null, feature_ms: frames ? featureMs / frames : null,
      sample_hz: frames > 1 ? (frames - 1) * 1000 / (lastFrame - firstFrame) : null}; }
  };
  function tick() {
    if (!active || video.readyState < 2 || video.currentTime === lastVideoTime) return;
    lastVideoTime = video.currentTime;
    if (locked && ["calibrate", "checkIntro", "check", "practice"].includes(phase) &&
        (document.hidden || locked.some((v, i) => v !== windowNow()[i]))) {
      emit("calibration_cancel"); notice = MOVED; home(); return;
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
      if (f) { faceAt = now; if (phase === "home") followFace(lm); }
      updateFace();
      emit("sample", {t, features: f, calibration: collecting ? index : -1, check: checkObserving ? checkIndex : -1, hidden: document.hidden});
      if (collecting && now >= until) { collecting = false; awaiting = true; emit("calibration_point", {index}); }
    } catch (e) { emit("error", {error: String(e)}); fatal(String(e), "Camera stopped", true); }
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
  function failedToOpen(e) { emit("error", {error: String(e)}); const [label, showRaw] = cameraLabel(e); fatal(String(e), label, showRaw); }
  async function restart() {
    phase = "start"; page({camera: "empty", waking: true, actions: [CURSOR]});
    emit("retry_camera");
    try { await openCamera(); } catch (e) { failedToOpen(e); }
  }
  page({camera: "empty", waking: true, actions: [CURSOR]});
  try { await openCamera(); } catch (e) { failedToOpen(e); }
})
