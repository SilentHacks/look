// Owned offline document: no getUserMedia, no microphone, no network server.
(async function (opts) {
  "use strict";
  const {FaceLandmarker} = await import(opts.module);
  const factory = globalThis.ModuleFactory;
  let model;
  async function reset() {
    model?.close();
    globalThis.ModuleFactory = factory; // Tasks Vision consumes/deletes the installed loader on creation.
    model = await FaceLandmarker.createFromOptions({wasmBinaryPath: opts.wasm + "/vision_wasm_internal.wasm"}, {
      baseOptions: {modelAssetPath: opts.model, delegate: "CPU"}, runningMode: "VIDEO", numFaces: 1,
      minFaceDetectionConfidence: .5, minFacePresenceConfidence: .5,
      outputFaceBlendshapes: true
    });
  }
  await reset();
  function tuningFeatures(lm, width, height) {
    if (!lm || lm.length !== 478) return {};
    const sub = (a, b) => a.map((v, i) => v - b[i]);
    const dot = (a, b) => a.reduce((v, x, i) => v + x * b[i], 0);
    const unit = a => a.map(v => v / Math.hypot(...a));
    const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
    // MediaPipe z is in x units; undo image aspect ratio before head-local projection.
    const xyz = lm.map(p => [p.x, p.y * height / width, p.z]);
    const hx = unit(sub(xyz[263], xyz[33]));
    const hz = unit(cross(hx, sub(xyz[152], xyz[10])));
    const hy = unit(cross(hz, hx));
    const iris = [], openness = [];
    for (const [a,b,c,u,d] of [[33,133,468,159,145],[362,263,473,386,374]]) {
      const size = Math.hypot(...sub(xyz[b], xyz[a]));
      const delta = sub(xyz[c], xyz[a].map((v,i) => (v + xyz[b][i]) / 2));
      iris.push(dot(delta,hx)/size, dot(delta,hy)/size);
      openness.push(Math.hypot(...sub(xyz[u],xyz[d]))/size);
    }
    const head = [lm[1].x, lm[1].y, Math.hypot(...sub(xyz[263],xyz[33])),
      Math.atan2(hx[1],hx[0]), Math.atan2(hx[2],hx[0]), Math.atan2(hy[2],hy[1])];
    return {pose_features: iris.concat(head), openness};
  }
  function eyeAppearance(image, lm) {
    if (!lm) return null;
    // Personal pixel ridge, not a pretrained gaze CNN. No image leaves this owned offline document.
    const patch = document.createElement("canvas"); patch.width = 16; patch.height = 8;
    const ctx = patch.getContext("2d", {willReadFrequently: true}), values = [];
    for (const [a,b] of [[33,133],[362,263]]) {
      const ax = lm[a].x * image.naturalWidth, ay = lm[a].y * image.naturalHeight;
      const bx = lm[b].x * image.naturalWidth, by = lm[b].y * image.naturalHeight;
      const dx = bx-ax, dy = by-ay, length = Math.hypot(dx,dy);
      if (length < 2) return null;
      const scale = 16/(1.5*length), cos = dx/length, sin = dy/length;
      const cx = (ax+bx)/2, cy = (ay+by)/2;
      ctx.setTransform(1,0,0,1,0,0); ctx.clearRect(0,0,16,8);
      ctx.setTransform(scale*cos,-scale*sin,scale*sin,scale*cos,
        8-scale*(cos*cx+sin*cy),4-scale*(-sin*cx+cos*cy));
      ctx.drawImage(image,0,0);
      const rgba = ctx.getImageData(0,0,16,8).data, gray = [];
      for (let i=0;i<rgba.length;i+=4) gray.push((.299*rgba[i]+.587*rgba[i+1]+.114*rgba[i+2])/255);
      const mean = gray.reduce((a,b)=>a+b,0)/gray.length;
      const std = Math.max(.02,Math.sqrt(gray.reduce((a,b)=>a+(b-mean)**2,0)/gray.length));
      values.push(...gray.map(v=>(v-mean)/std));
    }
    return values;
  }
  globalThis.__HERMES_EVAL__ = {
    async extract(src, timestamp, discontinuous) {
      if (discontinuous) await reset(); // Independent stills must not inherit a previous face track.
      const image = new Image(); image.src = src; await image.decode();
      const start = performance.now();
      const result = model.detectForVideo(image, timestamp);
      const features = globalThis.__hermesGazeFeatures(result.faceLandmarks[0]);
      const inference_ms = performance.now() - start;
      const extra = tuningFeatures(result.faceLandmarks[0], image.naturalWidth, image.naturalHeight);
      const blinks = result.faceBlendshapes[0]?.categories.filter(c => c.categoryName.startsWith("eyeBlink")) || [];
      const patchStart = performance.now();
      const patch = features ? eyeAppearance(image, result.faceLandmarks[0]) : null;
      return {features, inference_ms, ...extra, blink: Math.max(0, ...blinks.map(c => c.score)),
        appearance: patch ? patch.concat(features) : null,
        appearance_inference_ms: inference_ms + performance.now() - patchStart};
    }
  };
  globalThis.__HERMES_WEBCAM__ = {stop() { model?.close(); }};
  document.title = "Hermes Gaze — offline evaluation (no camera)";
  document.body.textContent = "Offline frame evaluation. No camera or microphone is open.";
  __hermesGazeIntent(JSON.stringify({type: "ready", nonce: opts.nonce}));
})
