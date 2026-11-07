// Explicit recording mode in the owned tracker process, never a website.
(async function (opts) {
  "use strict";
  const emit = (type, data = {}) => __hermesGazeIntent(JSON.stringify({type, nonce: opts.nonce, ...data}));
  const make = (tag, text) => { const n = document.createElement(tag); n.textContent = text || ""; return n; };
  const style = make("style", "body{margin:0;background:#17191c;color:#f5f5f7;font:20px system-ui;text-align:center}main{padding:32px}video{width:320px;transform:scaleX(-1)}button{font:inherit;padding:12px;margin:12px}#dot{position:fixed;width:22px;height:22px;border-radius:50%;background:#a9d7ff;transform:translate(-50%,-50%);display:none}#instruction{position:fixed;bottom:12px;width:100%;pointer-events:none}body.recording main{display:none}");
  document.head.append(style); document.title = "Hermes Gaze — private recording";
  const main = make("main"), video = make("video"), start = make("button", "Start recording"), stop = make("button", "Stop camera"),
    status = make("p", "Starting camera…"), instruction = make("p"), dot = make("div");
  video.autoplay = true; video.muted = true; video.playsInline = true;
  instruction.id = "instruction"; dot.id = "dot";
  main.append(make("h1", "Private gaze recording"), video,
    make("p", opts.instruction), make("p", "Camera video and target positions stay on this computer. No audio. Esc saves and stops early."),
    start, stop, status); document.body.append(main, dot, instruction);
  let stream, recorder, started = false, ended = false, geometry, windowState, videoStart = 0, startTime = 0, chain = Promise.resolve(), frames = 0;
  const duration = opts.duration;
  const grid = n => Array.from({length: n * n}, (_, i) => [.1 + .8 * (i % n) / (n - 1), .1 + .8 * Math.floor(i / n) / (n - 1)]);
  function target(t) {
    if (t < duration * .25) {
      const span = duration * .25 / 9, i = Math.min(8, Math.floor(t / span));
      return {xy: grid(3)[i], phase: "calibration", settling: t % span < Math.min(.6, span * .3)};
    }
    if (t < duration * .60) {
      const local = t - duration * .25, span = duration * .35 / 16;
      return {xy: grid(4)[Math.min(15, Math.floor(local / span))], phase: "fixed", settling: local % span < Math.min(.6, span * .3)};
    }
    if (t < duration * .82) {
      const p = (t - duration * .60) / (duration * .22);
      return {xy: [.5 + .38 * Math.sin(p * Math.PI * 4), .5 + .35 * Math.sin(p * Math.PI * 2)], phase: "moving", settling: false};
    }
    const p = (t - duration * .82) / (duration * .18) * 6, line = Math.min(5, Math.floor(p));
    return {xy: [.1 + .8 * (p % 1), .15 + line * .14], phase: "reading", settling: p % 1 < .08};
  }
  function finish(reason = "complete") {
    if (ended) return;
    ended = true;
    if (recorder?.state === "recording") recorder.stop();
    else emit("stopped");
    stream?.getTracks().forEach(t => t.stop());
    dot.style.display = "none"; document.body.classList.remove("recording");
    status.textContent = "Saving locally. You can close this window when recording finishes.";
    opts.reason = reason;
  }
  function draw() {
    if (!started || ended) return;
    if (windowState.some((v, i) => v !== [screenX, screenY, innerWidth, innerHeight, devicePixelRatio][i])) { finish("window changed"); return; }
    const t = (performance.now() - startTime) / 1000;
    if (t >= duration) { finish(); return; }
    const p = target(t);
    dot.style.left = `${p.xy[0] * 100}%`; dot.style.top = `${p.xy[1] * 100}%`;
    instruction.textContent = `${opts.instruction} · ${p.phase === "reading" ? "Follow the dot as if reading" : "Keep looking at the dot"} · ${Math.ceil(duration - t)} seconds · Esc saves and stops`;
    requestAnimationFrame(draw);
  }
  function capture(_, metadata) {
    if (!started || ended) return;
    const t = metadata.mediaTime - videoStart;
    const p = target(Math.max(0, t));
    emit("record_frame", {t: Math.max(0, t), target: [geometry.left + p.xy[0] * geometry.width, geometry.top + p.xy[1] * geometry.height],
      phase: p.phase, settling: p.settling, media_time: metadata.mediaTime, presented_frame: metadata.presentedFrames});
    frames++;
    video.requestVideoFrameCallback(capture);
  }
  start.addEventListener("click", e => {
    if (!e.isTrusted || started || ended || !stream) return;
    started = true;
    geometry = {left: e.screenX - e.clientX, top: e.screenY - e.clientY, width: innerWidth, height: innerHeight,
      screen_width: screen.width, screen_height: screen.height, screen_left: screen.availLeft, screen_top: screen.availTop, dpr: devicePixelRatio};
    // Evaluation coordinates are viewport-local. Save the actual desktop origin separately.
    emit("record_start", {screen: {...geometry, left: 0, top: 0}, viewport_origin: [geometry.left, geometry.top], epoch: Date.now() / 1000});
    geometry.left = 0; geometry.top = 0;
    windowState = [screenX, screenY, innerWidth, innerHeight, devicePixelRatio];
    recorder = new MediaRecorder(stream, {mimeType: "video/webm;codecs=vp8", videoBitsPerSecond: 2500000});
    recorder.ondataavailable = e => {
      chain = chain.then(async () => {
        const bytes = new Uint8Array(await e.data.arrayBuffer());
        for (let offset = 0; offset < bytes.length; offset += 49152) {
          const part = bytes.subarray(offset, offset + 49152);
          emit("record_chunk", {data: btoa(String.fromCharCode(...part))});
        }
      }).catch(() => finish("video encoding failed"));
    };
    recorder.onerror = () => finish("video encoding failed");
    recorder.onstop = () => { chain.then(() => emit("record_end", {reason: opts.reason || "complete", frames})); };
    recorder.onstart = () => {
      videoStart = video.currentTime; startTime = performance.now();
      document.body.classList.add("recording"); dot.style.display = "block";
      draw(); video.requestVideoFrameCallback(capture);
    };
    recorder.start(500);
  });
  stop.addEventListener("click", e => { if (e.isTrusted) finish("stopped by user"); });
  addEventListener("keydown", e => { if (e.isTrusted && e.code === "Escape") finish("stopped by user"); });
  addEventListener("visibilitychange", () => { if (document.hidden) finish("window hidden"); });
  addEventListener("pagehide", () => finish("window closed"), {once: true});
  globalThis.__HERMES_WEBCAM__ = {stop: () => finish("tracker stopped"), status: () => ({started, ended, frames})};
  try {
    stream = await navigator.mediaDevices.getUserMedia({video: {width: 640, height: 480, frameRate: 15}, audio: false});
    video.srcObject = stream; await video.play();
    status.textContent = "Ready. Maximize this window before starting. Keep this window visible.";
    emit("ready");
  } catch (_) { emit("error", {error: "Recording camera could not start"}); }
})
