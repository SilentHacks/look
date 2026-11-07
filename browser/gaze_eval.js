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
      minFaceDetectionConfidence: .5, minFacePresenceConfidence: .5
    });
  }
  await reset();
  globalThis.__HERMES_EVAL__ = {
    async extract(src, timestamp, discontinuous) {
      if (discontinuous) await reset(); // Independent stills must not inherit a previous face track.
      const image = new Image(); image.src = src; await image.decode();
      const start = performance.now();
      const features = globalThis.__hermesGazeFeatures(model.detectForVideo(image, timestamp).faceLandmarks[0]);
      return {features, inference_ms: performance.now() - start};
    }
  };
  globalThis.__HERMES_WEBCAM__ = {stop() { model?.close(); }};
  document.title = "Hermes Gaze — offline evaluation (no camera)";
  document.body.textContent = "Offline frame evaluation. No camera or microphone is open.";
  __hermesGazeIntent(JSON.stringify({type: "ready", nonce: opts.nonce}));
})
