// One feature order for the live tracker and frame-exact offline evaluation.
globalThis.__hermesGazeFeatures = function (lm) {
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
};

// Version-ordered appearance: first-eye 16×8 row-major standardized grayscale,
// second eye likewise, then the original eight iris/head values (saved-file layout).
// leftOnly is the live model's 128 values + that eye's two iris coordinates.
globalThis.__hermesGazeAppearance = (() => {
  let patch, ctx;
  return function (image, lm, features, leftOnly = false) {
    if (!features || !lm || lm.length !== 478) return null;
    if (!patch) {
      patch = document.createElement("canvas"); patch.width = 16; patch.height = 8;
      ctx = patch.getContext("2d", {willReadFrequently: true});
    }
    const width = image.naturalWidth || image.videoWidth, height = image.naturalHeight || image.videoHeight;
    if (!(width > 0 && height > 0) || !ctx) return null;
    const values = [];
    for (const [a, b] of (leftOnly ? [[33, 133]] : [[33, 133], [362, 263]])) {
      const ax = lm[a].x * width, ay = lm[a].y * height;
      const bx = lm[b].x * width, by = lm[b].y * height;
      const dx = bx - ax, dy = by - ay, length = Math.hypot(dx, dy);
      if (!Number.isFinite(length) || length < 2) return null;
      const scale = 16 / (1.5 * length), cos = dx / length, sin = dy / length;
      const cx = (ax + bx) / 2, cy = (ay + by) / 2;
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, 16, 8);
      ctx.setTransform(scale * cos, -scale * sin, scale * sin, scale * cos,
        8 - scale * (cos * cx + sin * cy), 4 - scale * (-sin * cx + cos * cy));
      ctx.drawImage(image, 0, 0);
      const rgba = ctx.getImageData(0, 0, 16, 8).data, gray = [];
      for (let i = 0; i < rgba.length; i += 4) gray.push((.299 * rgba[i] + .587 * rgba[i + 1] + .114 * rgba[i + 2]) / 255);
      const mean = gray.reduce((a, b) => a + b, 0) / gray.length;
      const std = Math.max(.02, Math.sqrt(gray.reduce((a, b) => a + (b - mean) ** 2, 0) / gray.length));
      values.push(...gray.map(v => (v - mean) / std));
    }
    const out = values.concat(leftOnly ? features.slice(0, 2) : features);
    return out.every(Number.isFinite) ? out : null;
  };
})();
