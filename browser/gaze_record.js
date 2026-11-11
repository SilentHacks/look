// Explicit dataset mode in the owned tracker process, never a website.
(function () {
  "use strict";
  const grid = (n, edge) => Array.from({length: n * n}, (_, i) => [edge + (1 - edge * 2) * (i % n) / (n - 1), edge + (1 - edge * 2) * Math.floor(i / n) / (n - 1)]);
  function shuffle(points, seed) {
    let state = seed || 1;
    for (let i = points.length - 1; i > 0; i--) {
      state ^= state << 13; state ^= state >>> 17; state ^= state << 5;
      const j = (state >>> 0) % (i + 1); [points[i], points[j]] = [points[j], points[i]];
    }
    return points;
  }
  function protocol(block, seed) {
    const schedule = [];
    const fixed = (points, phase) => points.forEach(xy => schedule.push({xy, phase, span: 1.2}));
    const validation = shuffle(grid(3, .12), seed);
    if (block !== "no-recalibration") fixed(shuffle(grid(5, .04), seed), "calibration");
    fixed(validation, "validation-start");
    fixed(shuffle(grid(4, 1 / 8), seed), "fixed");
    schedule.push({phase: "moving", span: 15}, {phase: "reading", span: 16.8});
    fixed(validation, "validation-end");
    return schedule;
  }
  const scheduleLength = schedule => schedule.reduce((sum, step) => sum + step.span, 0);
  function target(schedule, t, duration = scheduleLength(schedule)) {
    let local = t * scheduleLength(schedule) / duration;
    for (const step of schedule) {
      if (local >= step.span) { local -= step.span; continue; }
      const p = local / step.span;
      if (step.phase === "moving") return {xy: [.5 + .42 * Math.sin(p * Math.PI * 4), .5 + .4 * Math.sin(p * Math.PI * 2)], phase: step.phase, settling: false};
      if (step.phase === "reading") {
        const line = Math.min(3, Math.floor(local / 4.2));
        const elapsed = local - line * 4.2;
        return {xy: [.08 + .84 * Math.max(0, (elapsed - .8) / 3.4), .12 + line * .25], phase: step.phase, settling: elapsed < .8};
      }
      return {xy: step.xy, phase: step.phase, settling: local < .35};
    }
    return {xy: [.5, .5], phase: "validation-end", settling: true};
  }
  // The same pure schedule/target functions run in Node without a DOM or devices.
  if (typeof module !== "undefined") module.exports = {protocol, scheduleLength, target};
  return async function (opts) {
  const blockDuration = block => opts.duration ?? scheduleLength(protocol(block, 1));
  const emit = (type, data = {}) => __lookIntent(JSON.stringify({type, nonce: opts.nonce, ...data}));
  const make = (tag, text) => { const n = document.createElement(tag); n.textContent = text || ""; return n; };
  document.head.append(make("style", "body{margin:0;background:#17191c;color:#f5f5f7;font:18px system-ui;text-align:center}main{max-width:850px;margin:auto;padding:24px}video{width:240px;transform:scaleX(-1)}button,input,textarea{font:inherit;padding:8px;margin:6px}label{display:block}input,textarea{width:340px}button{cursor:pointer}#dot{position:fixed;width:20px;height:20px;border-radius:50%;background:#a9d7ff;transform:translate(-50%,-50%);display:none}#instruction{position:fixed;bottom:0;width:100%;pointer-events:none;font-size:14px}body.recording main{display:none}button:focus-visible{outline:3px solid #a9d7ff}"));
  document.title = "Look private dataset recorder";
  const main = make("main"), dot = make("div"), instruction = make("p"), video = make("video");
  dot.id = "dot"; instruction.id = "instruction";
  video.autoplay = true; video.muted = true; video.playsInline = true;
  document.body.append(main, dot, instruction);
  let stream, recorder, index = 0, active = false, saving = false, geometry, windowState, startTime,
    chain = Promise.resolve(), frames = 0, seed, schedule = [], shown, reason, pending = false, frameCallback, duration;
  const fields = {};
  function button(id, text, fn) {
    const b = make("button", text); b.id = id;
    b.addEventListener("click", e => { if (e.isTrusted) fn(e); }); main.append(b); return b;
  }
  function close() {
    stream?.getTracks().forEach(t => t.stop()); emit("protocol_end");
  }
  function finish(why = "complete") {
    if (!active) return;
    active = false; saving = true; reason = why;
    video.cancelVideoFrameCallback(frameCallback);
    recorder.stop(); dot.style.display = "none"; document.body.classList.remove("recording");
    instruction.textContent = ""; main.replaceChildren(make("h1", "Saving locally…"));
  }
  function draw() {
    if (!active) return;
    if (windowState.some((v, i) => v !== [screenX, screenY, innerWidth, innerHeight, devicePixelRatio][i])) { finish("window changed"); return; }
    const t = (performance.now() - startTime) / 1000;
    if (t >= duration) { finish(); return; }
    shown = target(schedule, t, duration);
    dot.style.left = `${shown.xy[0] * 100}%`; dot.style.top = `${shown.xy[1] * 100}%`;
    instruction.textContent = `${shown.phase} · Follow the dot with your eyes · ${Math.ceil(duration - t)} seconds · Esc saves and stops early`;
    requestAnimationFrame(draw);
  }
  function capture(_, metadata) {
    if (!active) return;
    const t = (metadata.presentationTime - startTime) / 1000;
    // Label the target actually drawn, not a future target recomputed across a transition.
    if (t >= 0 && shown) emit("record_frame", {t, target: [shown.xy[0] * geometry.width, shown.xy[1] * geometry.height],
      phase: shown.phase, settling: shown.settling, media_time: metadata.mediaTime, presented_frame: metadata.presentedFrames});
    frames++; frameCallback = video.requestVideoFrameCallback(capture);
  }
  async function begin() {
    if (!pending) return;
    // Reattaching the preview on a break screen pauses the HTML video element.
    try { await video.play(); }
    catch (_) { emit("error", {error: "Camera preview could not resume"}); return; }
    frames = 0; chain = Promise.resolve(); reason = undefined;
    recorder = new MediaRecorder(stream, {mimeType: "video/webm;codecs=vp8", videoBitsPerSecond: 1500000});
    recorder.ondataavailable = e => {
      chain = chain.then(async () => {
        const bytes = new Uint8Array(await e.data.arrayBuffer());
        for (let offset = 0; offset < bytes.length; offset += 49152) {
          emit("record_chunk", {data: btoa(String.fromCharCode(...bytes.subarray(offset, offset + 49152)))});
        }
      }).catch(() => { emit("error", {error: "Video encoding failed; session remains unfinished"}); });
    };
    recorder.onerror = () => finish("video encoding failed");
    recorder.onstop = () => { chain.then(() => emit("record_end", {reason, frames})); };
    recorder.onstart = () => {
      // No old frame may advance Python's watermark before this session's clock exists.
      startTime = performance.now(); active = true; pending = false;
      document.body.classList.add("recording"); dot.style.display = "block";
      draw(); frameCallback = video.requestVideoFrameCallback(capture);
    };
    recorder.start(500);
  }
  function prepare(message = "Take a break. Restore baseline settings except for the next named change.") {
    if (index >= opts.blocks.length) { close(); return; }
    const block = opts.blocks[index];
    duration = blockDuration(block.name);
    main.replaceChildren(make("h1", `${index ? "Next block" : "Ready"}: ${block.name}`),
      make("p", `${opts.person} · ${opts.glasses} · ${opts.device}`), make("p", message),
      make("p", block.instruction), make("p", `${duration.toFixed(1)} seconds. Maximize this window before starting and keep it visible. Follow the dot naturally.`), video);
    for (const [key, value] of Object.entries(block.details)) {
      const label = make("label", key.replaceAll("_", " "));
      fields[key] = make("input"); fields[key].id = key; fields[key].value = value; fields[key].maxLength = 200;
      label.append(fields[key]); main.append(label);
    }
    if (opts.physical?.distance_mm) {
      const distance = make("label", "Measured eye-to-display distance (mm, update for this session)");
      fields.distance_mm = make("input"); fields.distance_mm.type = "number"; fields.distance_mm.min = "1";
      fields.distance_mm.value = opts.physical.distance_mm; distance.append(fields.distance_mm); main.append(distance);
    }
    const label = make("label", "Session note (no real names or contact details)");
    fields.note = make("textarea"); fields.note.id = "note"; fields.note.value = opts.note; fields.note.maxLength = 1000;
    label.append(fields.note); main.append(label);
    button("start", "Start session", e => {
      if (active || saving || pending || !stream) return;
      const details = Object.fromEntries(Object.keys(block.details).map(k => [k, fields[k].value.trim()]));
      if (Object.values(details).some(v => !v)) { instruction.textContent = "Describe each condition field before starting."; return; }
      const distance_mm = opts.physical?.distance_mm ? Number(fields.distance_mm.value) : null;
      if (distance_mm !== null && (!Number.isFinite(distance_mm) || distance_mm <= 0)) {
        instruction.textContent = "Enter a positive measured distance."; return;
      }
      seed = crypto.getRandomValues(new Uint32Array(1))[0];
      schedule = protocol(block.name, seed); pending = true;
      geometry = {left: 0, top: 0, width: innerWidth, height: innerHeight, screen_width: screen.width,
        screen_height: screen.height, screen_left: screen.availLeft, screen_top: screen.availTop, dpr: devicePixelRatio};
      windowState = [screenX, screenY, innerWidth, innerHeight, devicePixelRatio];
      emit("record_start", {screen: geometry, viewport_origin: [e.screenX - e.clientX, e.screenY - e.clientY],
        epoch: Date.now() / 1000, block: block.name, details, note: fields.note.value, distance_mm, seed});
    });
    button("exit", "Stop and resume later", close);
  }
  async function enableCamera() {
    main.replaceChildren(make("p", "Starting camera only…"));
    try {
      stream = await navigator.mediaDevices.getUserMedia({video: {width: 640, height: 480, frameRate: 15}, audio: false});
      video.srcObject = stream; await video.play(); prepare("Check your camera preview for anything private in the background.");
    } catch (_) { emit("error", {error: "Recording camera could not start"}); }
  }
  function intro() {
    main.replaceChildren(make("h1", "Private gaze dataset"), make("p", `${opts.person} · ${opts.glasses} · ${opts.device}`),
      make("p", `Selected blocks: ${opts.blocks.map(b => b.name).join(", ")}. About ${Math.ceil(opts.blocks.reduce((sum, b) => sum + blockDuration(b.name), 0) / 60)} minutes plus breaks. Stop between blocks and rerun the same command to resume.`));
    button("camera", "Enable camera", enableCamera); button("exit", "Not now", close);
  }
  globalThis.__HERMES_WEBCAM__ = {
    stop: () => { if (active) finish("tracker stopped"); stream?.getTracks().forEach(t => t.stop()); },
    begin,
    reject: message => { pending = false; instruction.textContent = message; },
    saved: () => {
      saving = false;
      if (reason === "complete") index++;
      prepare(reason === "complete" ? "Session saved. Rest your eyes, then adjust only the next named condition." : "Partial session saved. It won’t count as complete. Rest, then retry this block or stop and resume later.");
    },
    status: () => ({started: active, saving, pending, index, frames, phase: shown?.phase})
  };
  addEventListener("keydown", e => { if (e.isTrusted && e.code === "Escape" && active) finish("stopped by user"); });
  addEventListener("visibilitychange", () => { if (document.hidden && active) finish("window hidden"); });
  addEventListener("pagehide", () => { if (active) finish("window closed"); stream?.getTracks().forEach(t => t.stop()); }, {once: true});
  if (opts.consent_required) {
    main.append(make("h1", "Record a local gaze dataset?"),
      make("p", "This saves video of your face and background, gaze-target positions, an anonymous ID and your condition notes. It does not record audio or connect to Hermes. Everything stays on this computer unless you export it. Share exports only with someone you trust for local gaze research. You can decline or stop at any time."),
      make("p", `Use an anonymous ID, not your real name. To delete your sessions and consent, remove ${opts.delete_path}. Also remove any exports, extracted frames or features, scores and backups. Deleting files does not guarantee they cannot be recovered.`));
    button("consent", "I agree, continue", () => { emit("record_consent", {accepted: true}); intro(); });
    button("decline", "No thanks", close);
  } else intro();
  emit("ready");
  };
})()
