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
