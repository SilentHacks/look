// Loaded by CDP only, in the tracker window's isolated world. No website runs here.
(async function (opts) {
  "use strict";
  const emit = (type, data = {}) => __hermesGazeIntent(JSON.stringify({type, nonce: opts.nonce, ...data}));
  const make = (tag, text) => { const n = document.createElement(tag); if (text) n.textContent = text; return n; };
  const style = make("style");
  style.textContent = "body{margin:0;background:#17191c;color:#f5f5f7;font:18px system-ui;text-align:center}main{padding:36px}video{width:320px;transform:scaleX(-1)}button{font:inherit;padding:12px 24px;margin:12px}#dot{position:fixed;width:24px;height:24px;border-radius:50%;background:#a9d7ff;transform:translate(-50%,-50%);display:none}body.calibrating main{display:none}#guide{position:fixed;bottom:18px;width:100%;pointer-events:none}body:not(.calibrating) #guide{display:none}";
  document.head.append(style);
  document.title = "Hermes Gaze — webcam";
  const main = make("main"), title = make("h1", "Webcam gaze"), status = make("p", "Starting camera…");
  const video = make("video"); video.autoplay = true; video.muted = true; video.playsInline = true;
  const begin = make("button", "Calibrate nine points"), stop = make("button", "Stop camera");
  const help = make("p", "Calibration stays on this computer. No images leave this window.");
  main.append(title, video, status, begin, stop, help); document.body.append(main);
  const dot = make("div"); dot.id = "dot";
  const guide = make("p"); guide.id = "guide"; document.body.append(dot, guide);
  const points = [.1, .5, .9].flatMap(y => [.1, .5, .9].map(x => [x, y]));
  let model, stream, timer, active = true, index = -1, collecting = false, until = 0, lastVideoTime = -1;
  let calibrationWindow = null;
  const show = text => { status.textContent = text; };
  function place() {
    const p = points[index]; dot.style.left = `${p[0] * 100}%`; dot.style.top = `${p[1] * 100}%`;
    guide.textContent = `Look at the dot, then press Space (${index + 1} of 9). Esc cancels.`;
  }
  function finishUI() {
    index = -1; collecting = false; dot.style.display = "none"; document.body.classList.remove("calibrating");
  }
  begin.addEventListener("click", e => {
    if (!e.isTrusted || !active || !stream) return;
    // Measured from this trusted click: no fullscreen/browser-chrome offset guess.
    const viewport = {left: e.screenX - e.clientX, top: e.screenY - e.clientY, width: innerWidth, height: innerHeight};
    calibrationWindow = [screenX, screenY, innerWidth, innerHeight, devicePixelRatio];
    index = 0; collecting = false; document.body.classList.add("calibrating"); dot.style.display = "block";
    emit("calibration_start", {viewport, screen: {left: screen.availLeft, top: screen.availTop,
      width: screen.availWidth, height: screen.availHeight, screen_width: screen.width, screen_height: screen.height,
      screen_left: screen.availLeft, screen_top: screen.availTop, dpr: devicePixelRatio}});
    place();
  });
  addEventListener("keydown", e => {
    if (!e.isTrusted || index < 0) return;
    if (e.code === "Escape") { emit("calibration_cancel"); finishUI(); return; }
    if (e.code !== "Space" || e.repeat || collecting) return;
    e.preventDefault(); collecting = true; until = performance.now() + 1100;
    guide.textContent = "Keep looking…";
  });
  function features(lm) {
    if (!lm || lm.length !== 478) return null;
    const out = [];
    for (const [a, b, iris, up, down] of [[33, 133, 468, 159, 145], [362, 263, 473, 386, 374]]) {
      const dx = lm[b].x - lm[a].x, dy = lm[b].y - lm[a].y, length = Math.hypot(dx, dy);
      if (length < .01 || Math.hypot(lm[up].x - lm[down].x, lm[up].y - lm[down].y) / length < .10) return null;
      const x = lm[iris].x - (lm[a].x + lm[b].x) / 2, y = lm[iris].y - (lm[a].y + lm[b].y) / 2;
      out.push((x * dx + y * dy) / (length * length), (y * dx - x * dy) / (length * length));
    }
    out.push(lm[1].x, lm[1].y, Math.hypot(lm[33].x - lm[263].x, lm[33].y - lm[263].y),
      Math.atan2(lm[263].y - lm[33].y, lm[263].x - lm[33].x));
    return out.every(Number.isFinite) ? out : null;
  }
  function shutdown() {
    active = false; clearInterval(timer); stream?.getTracks().forEach(t => t.stop()); model?.close();
    stream = null; finishUI(); show("Camera stopped. Switch to cursor with /gaze mode hover.");
  }
  stop.addEventListener("click", e => { if (e.isTrusted) { shutdown(); emit("stopped"); } });
  addEventListener("pagehide", shutdown, {once: true});
  globalThis.__HERMES_WEBCAM__ = {
    show, stop: shutdown,
    calibrationResult(text) { finishUI(); show(text); },
    status() { return {active, index, collecting, videoTime: video.currentTime, hidden: document.hidden}; }
  };
  try {
    const {FaceLandmarker} = await import(opts.module);
    // Python installs the checksum-verified SIMD loader into this isolated context.
    const files = {wasmBinaryPath: opts.wasm + "/vision_wasm_internal.wasm"};
    model = await FaceLandmarker.createFromOptions(files, {baseOptions: {modelAssetPath: opts.model, delegate: "CPU"},
      runningMode: "VIDEO", numFaces: 1, minFaceDetectionConfidence: .5, minFacePresenceConfidence: .5});
    stream = await navigator.mediaDevices.getUserMedia({video: {width: 640, height: 480}, audio: false});
    video.srcObject = stream; await video.play();
    show(opts.calibrated ? "Tracking. You can return to Chrome." : "Calibrate before asking with your eyes.");
    emit("ready");
    timer = setInterval(() => {
      if (!active || video.readyState < 2 || video.currentTime === lastVideoTime) return;
      lastVideoTime = video.currentTime;
      if (index >= 0 && calibrationWindow.some((v, i) => v !== [screenX, screenY, innerWidth, innerHeight, devicePixelRatio][i])) {
        emit("calibration_cancel"); finishUI(); show("Window changed. Start calibration again.");
      }
      const now = performance.now(), t = (performance.timeOrigin + now) / 1000;
      try {
        const f = features(model.detectForVideo(video, now).faceLandmarks[0]);
        emit("sample", {t, features: f, calibration: collecting ? index : -1, hidden: document.hidden});
        if (collecting && now >= until) {
          collecting = false; emit("calibration_point", {index}); index++;
          if (index === points.length) { index = -1; dot.style.display = "none"; guide.textContent = "Saving calibration…"; }
          else place();
        }
      } catch (e) { emit("error", {error: String(e)}); shutdown(); }
    }, 100); // Timers, not requestAnimationFrame: this owned process disables background throttling.
  } catch (e) { emit("error", {error: String(e)}); shutdown(); }
})
