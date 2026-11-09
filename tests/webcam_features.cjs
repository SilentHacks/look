// Synthetic pixels only. No browser, device, saved footage or biometric fixtures.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.join(__dirname, "..", "browser");
const width = 640, height = 480;
let flat = false, interval;
const pixel = (x, y) => x < 0 || y < 0 || x >= width || y >= height ? [0, 0, 0] :
  (flat ? [80, 80, 80] : [(Math.floor(x) * 7 + Math.floor(y) * 3) % 256,
    (Math.floor(x) * 2 + Math.floor(y) * 11) % 256, (Math.floor(x) + Math.floor(y) * 5) % 256]);
const elements = [];
function element(tag) {
  const node = {tag, style: {}, classList: {add() {}, remove() {}, toggle() {}}, dataset: {}, append() {}, replaceChildren() {}, querySelector: () => null, addEventListener() {}, setAttribute() {},
    videoWidth: width, videoHeight: height, currentTime: 0, readyState: 2, async play() {}};
  if (tag === "canvas") {
    const ctx = {
      setTransform(...m) { this.m = m; }, clearRect() {}, drawImage() {},
      getImageData() {
        const [a, b, c, d, e, f] = this.m, det = a * d - b * c, data = [];
        for (let y = 0; y < 8; y++) for (let x = 0; x < 16; x++) {
          const u = x + .5 - e, v = y + .5 - f;
          data.push(...pixel((d * u - c * v) / det, (-b * u + a * v) / det), 255);
        }
        return {data};
      }
    };
    node.getContext = () => ctx;
  }
  elements.push(node);
  return node;
}
globalThis.document = {createElement: element, createElementNS: (_ns, tag) => element(tag), head: element("head"), body: element("body"), hidden: false, querySelectorAll: () => [], addEventListener() {}};
globalThis.Image = class { constructor() { this.naturalWidth = width; this.naturalHeight = height; } async decode() {} };
globalThis.addEventListener = () => {};
Object.defineProperty(globalThis, "navigator", {value: {mediaDevices: {
  async getUserMedia(options) { assert.equal(options.audio, false); return {getTracks: () => [{stop() {}}], getVideoTracks: () => [{readyState: "live"}]}; }
}}, configurable: true});
globalThis.setInterval = callback => { if (callback.name === "tick") interval = callback; return 1; };
globalThis.clearInterval = () => {};
const messages = [];
globalThis.__hermesGazeIntent = text => messages.push(JSON.parse(text));
const lm = Array.from({length: 478}, () => ({x: .5, y: .5, z: 0}));
for (const [a, b, iris, up, down, cx] of [[33, 133, 468, 159, 145, .35], [362, 263, 473, 386, 374, .65]]) {
  lm[a] = {x: cx - .06, y: .4, z: 0}; lm[b] = {x: cx + .06, y: .42, z: 0};
  lm[iris] = {x: cx + .01, y: .415, z: 0};
  lm[up] = {x: cx, y: .39, z: 0}; lm[down] = {x: cx, y: .43, z: 0};
}
lm[10].y = .2; lm[152].y = .8;
globalThis.syntheticLandmarks = lm;
// Independent raster oracle for the pre-port offline 16×8, 1.5-eye-width patch.
function legacyAppearance(features) {
  const values = [];
  for (const [a, b] of [[33, 133], [362, 263]]) {
    const ax = lm[a].x * width, ay = lm[a].y * height, bx = lm[b].x * width, by = lm[b].y * height;
    const dx = bx - ax, dy = by - ay, length = Math.hypot(dx, dy), scale = 16 / (1.5 * length);
    const cos = dx / length, sin = dy / length, gray = [];
    for (let y = 0; y < 8; y++) for (let x = 0; x < 16; x++) {
      const u = (x + .5 - 8) / scale, v = (y + .5 - 4) / scale;
      const [r, g, b] = pixel((ax + bx) / 2 + cos * u - sin * v, (ay + by) / 2 + sin * u + cos * v);
      gray.push((.299 * r + .587 * g + .114 * b) / 255);
    }
    const mean = gray.reduce((a, b) => a + b, 0) / 128;
    const std = Math.max(.02, Math.sqrt(gray.reduce((a, b) => a + (b - mean) ** 2, 0) / 128));
    values.push(...gray.map(v => (v - mean) / std));
  }
  return values.concat(features);
}
(async () => {
  (0, eval)(fs.readFileSync(path.join(root, "webcam_features.js"), "utf8"));
  const module = "data:text/javascript," + encodeURIComponent(`export class FaceLandmarker {
    static async createFromOptions() { return new FaceLandmarker(); }
    detectForVideo() { return {faceLandmarks: [globalThis.syntheticLandmarks], faceBlendshapes: []}; }
    close() {}
  }`);
  await (0, eval)(fs.readFileSync(path.join(root, "gaze_eval.js"), "utf8"))({module, wasm: "unused", nonce: "test"});
  const offline = globalThis.__HERMES_EVAL__;
  await (0, eval)(fs.readFileSync(path.join(root, "webcam_host.js"), "utf8"))({module, wasm: "unused", nonce: "test",
    calibration_notice: "Please recalibrate."});
  const video = elements.find(e => e.tag === "video");
  for (flat of [false, true]) {
    const saved = await offline.extract("synthetic", 100, false);
    const expected = legacyAppearance(saved.features);
    assert.equal(saved.appearance.length, 264);
    expected.forEach((value, i) => assert(Math.abs(saved.appearance[i] - value) < 1e-12));
    video.currentTime += .1;
    interval();
    const sample = messages.at(-1);
    assert.equal(sample.type, "sample");
    assert.deepEqual(sample.features, saved.appearance.slice(0, 128).concat(saved.appearance.slice(-8, -6)));
  }
  assert.equal(globalThis.__HERMES_WEBCAM__.status().frames, 2);
  assert(globalThis.__HERMES_WEBCAM__.status().sample_hz > 0);
  lm[159] = lm[145]; // Same blink gate in both paths; never fill a missing face.
  assert.equal((await offline.extract("synthetic", 200, false)).appearance, null);
  video.currentTime += .1; interval();
  assert.equal(messages.at(-1).features, null);
  globalThis.__HERMES_WEBCAM__.stop();
  // Stop while model initialization is pending must not request even a fake camera.
  let releaseModel, closed = false, cameraCalls = 0;
  globalThis.pendingModel = new Promise(resolve => { releaseModel = resolve; });
  navigator.mediaDevices.getUserMedia = async () => { cameraCalls++; throw Error("Late camera request"); };
  const pendingModule = "data:text/javascript," + encodeURIComponent(`export class FaceLandmarker {
    static async createFromOptions() { return await globalThis.pendingModel; }
  }`);
  const pending = (0, eval)(fs.readFileSync(path.join(root, "webcam_host.js"), "utf8"))({
    module: pendingModule, wasm: "unused", nonce: "test"});
  await new Promise(resolve => setImmediate(resolve));
  globalThis.__HERMES_WEBCAM__.stop();
  releaseModel({close() { closed = true; }});
  await pending;
  assert.equal(cameraCalls, 0);
  assert.equal(closed, true);
  console.log("Shared extraction: legacy layout, live/offline equivalence, flat patch and blink rejection OK");
})().catch(error => { console.error(error); process.exitCode = 1; });
