"""Multi-granularity table & container data extractor + lightweight SVG chart generator."""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple


def extract_structured_data(
    table_payload: Dict[str, Any],
    fmt: str = "csv",
) -> str:
    """Convert extracted DOM table headers + rows into clean CSV, JSON, or Markdown."""
    headers: List[str] = [str(h) for h in (table_payload.get("headers") or [])]
    rows: List[List[Any]] = [list(r) for r in (table_payload.get("rows") or [])]

    if fmt == "json":
        if headers:
            records = [dict(zip(headers, r)) for r in rows]
        else:
            records = rows
        return json.dumps(records, indent=2, ensure_ascii=False)

    if fmt == "markdown":
        lines: List[str] = []
        if headers:
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for r in rows:
            lines.append("| " + " | ".join(str(cell) for cell in r) + " |")
        return "\n".join(lines)

    buf = io.StringIO()
    writer = csv.writer(buf)
    if headers:
        writer.writerow(headers)
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()


def _parse_numeric(val: Any) -> float:
    s = str(val or "").strip().replace(",", "").replace("$", "").replace("%", "")
    if s.lower().endswith("x"):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return 0.0


def render_svg_scatter(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    x_col: Optional[str] = None,
    y_col: Optional[str] = None,
    label_col: str = "Campaign",
) -> str:
    """Render a compact, self-contained SVG scatter plot for the Chrome HUD overlay.
    Axis columns default to the 2nd and last headers; labels always name the columns
    actually plotted — no fabricated axis names on arbitrary tables."""
    h_lower = [h.lower() for h in headers]
    ix = h_lower.index(x_col.lower()) if x_col and x_col.lower() in h_lower else min(1, max(len(headers) - 2, 0))
    iy = h_lower.index(y_col.lower()) if y_col and y_col.lower() in h_lower else max(len(headers) - 1, 0)
    il = h_lower.index(label_col.lower()) if label_col.lower() in h_lower else 0
    x_label = headers[ix] if ix < len(headers) else "x"
    y_label = headers[iy] if iy < len(headers) else "y"

    pts: List[Tuple[str, float, float]] = []
    for r in rows:
        if max(ix, iy, il) < len(r):
            pts.append((str(r[il]), _parse_numeric(r[ix]), _parse_numeric(r[iy])))

    if not pts:
        return ""

    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 0.5)

    w, h = 420, 150
    pad_l, pad_r, pad_t, pad_b = 44, 24, 22, 28
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b

    circles: List[str] = []
    for label, xv, yv in pts:
        cx = pad_l + ((xv - min_x) / span_x) * plot_w
        cy = pad_t + plot_h - ((yv - min_y) / span_y) * plot_h
        safe_lbl = html.escape(label[:16])
        circles.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5.5" fill="#38bdf8" stroke="#09090b" stroke-width="1.5"/>'
            f'<text x="{cx + 8:.1f}" y="{cy + 3:.1f}" fill="#e4e4e7" font-size="10" font-family="monospace">{safe_lbl}</text>'
        )

    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" xmlns="http://www.w3.org/2000/svg" '
        f'style="background:#09090b;border:1px solid #27272a;border-radius:6px;margin-top:6px;">'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" stroke="#3f3f46" stroke-width="1"/>'
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" stroke="#3f3f46" stroke-width="1"/>'
        f'<text x="{pad_l + plot_w / 2:.1f}" y="{h - 6}" fill="#a1a1aa" font-size="10" text-anchor="middle" font-family="sans-serif">{html.escape(str(x_label))}</text>'
        f'<text x="12" y="{pad_t + plot_h / 2:.1f}" fill="#a1a1aa" font-size="10" text-anchor="middle" font-family="sans-serif" transform="rotate(-90 12 {pad_t + plot_h / 2:.1f})">{html.escape(str(y_label))}</text>'
        + "".join(circles)
        + "</svg>"
    )
