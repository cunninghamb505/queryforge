"""Builds fancy, self-contained reports from a query result DataFrame.

The HTML report inlines all CSS and renders any chart as inline SVG, so the downloaded file is a
single portable document that works offline and prints cleanly to PDF from a browser. No external
JS/CSS/fonts are referenced.
"""

from __future__ import annotations

import html
import io
import json
from datetime import datetime

import pandas as pd

# Chart series palette; index 0 is replaced by the user's chosen accent at render time.
_PALETTE = ["#8b5cf6", "#22d3ee", "#f472b6", "#a3e635", "#fbbf24", "#818cf8", "#fb7185"]


# --- summary ---------------------------------------------------------------

def numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def summarize(df: pd.DataFrame, elapsed_ms: float | None) -> dict:
    num_cols = numeric_columns(df)
    return {
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "numeric_cols": len(num_cols),
        "null_cells": int(df.isna().sum().sum()),
        "elapsed_ms": elapsed_ms,
    }


def _fmt_num(v: float) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f) and abs(f) < 1e15:
        return f"{int(f):,}"
    return f"{f:,.4g}"


# --- SVG chart -------------------------------------------------------------

def svg_chart(
    labels: list[str],
    series: list[dict],
    *,
    chart_type: str = "bar",
    accent: str = "#8b5cf6",
    width: int = 780,
    height: int = 360,
    max_points: int = 40,
) -> str | None:
    """Renders a grouped-bar / line / area chart as an inline SVG string.

    labels: x-axis category labels. series: [{"name": str, "values": list[float]}, ...].
    Returns None if there's nothing chartable.
    """
    if not labels or not series:
        return None

    truncated = len(labels) > max_points
    labels = [str(x) for x in labels[:max_points]]
    clean_series = []
    for s in series:
        vals = []
        for v in s["values"][:max_points]:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                vals.append(0.0)
        clean_series.append({"name": str(s["name"]), "values": vals})
    if not clean_series:
        return None

    palette = [accent] + [c for c in _PALETTE if c.lower() != accent.lower()]

    pad_l, pad_r, pad_t, pad_b = 60, 20, 44, 74
    x0, x1 = pad_l, width - pad_r
    y0, y1 = pad_t, height - pad_b

    all_vals = [v for s in clean_series for v in s["values"]] or [0.0]
    vmax = max(all_vals)
    vmin = min(0.0, min(all_vals))
    if vmax == vmin:
        vmax = vmin + 1

    def vy(v: float) -> float:
        return y1 - (v - vmin) / (vmax - vmin) * (y1 - y0)

    n = len(labels)
    slot = (x1 - x0) / max(n, 1)

    parts: list[str] = []
    parts.append(
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif" '
        f'width="100%" style="max-width:{width}px">'
    )
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="none"/>')

    # horizontal gridlines + y labels
    for i in range(5):
        gv = vmin + (vmax - vmin) * i / 4
        gy = vy(gv)
        parts.append(
            f'<line x1="{x0}" y1="{gy:.1f}" x2="{x1}" y2="{gy:.1f}" '
            f'stroke="#e5e7eb" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x0 - 8}" y="{gy + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#6b7280">{html.escape(_fmt_num(gv))}</text>'
        )

    # zero baseline (if within range)
    if vmin < 0 < vmax:
        zy = vy(0)
        parts.append(f'<line x1="{x0}" y1="{zy:.1f}" x2="{x1}" y2="{zy:.1f}" stroke="#9ca3af" stroke-width="1.2"/>')

    # x labels
    step = max(1, n // 20)
    for i, lab in enumerate(labels):
        if i % step != 0:
            continue
        cx = x0 + slot * i + slot / 2
        text = html.escape(lab if len(lab) <= 14 else lab[:13] + "…")
        parts.append(
            f'<text x="{cx:.1f}" y="{y1 + 16:.1f}" text-anchor="end" font-size="11" '
            f'fill="#6b7280" transform="rotate(-35 {cx:.1f} {y1 + 16:.1f})">{text}</text>'
        )

    ns = len(clean_series)
    if chart_type == "bar":
        group_w = slot * 0.72
        bar_w = group_w / ns
        for si, s in enumerate(clean_series):
            color = palette[si % len(palette)]
            for i, v in enumerate(s["values"]):
                bx = x0 + slot * i + (slot - group_w) / 2 + bar_w * si
                by = vy(max(v, 0)) if v >= 0 else vy(0)
                bh = abs(vy(v) - vy(0))
                parts.append(
                    f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
                    f'rx="2" fill="{color}"><title>{html.escape(s["name"])}: {html.escape(_fmt_num(v))}</title></rect>'
                )
    else:  # line / area
        for si, s in enumerate(clean_series):
            color = palette[si % len(palette)]
            pts = [(x0 + slot * i + slot / 2, vy(v)) for i, v in enumerate(s["values"])]
            pts_str = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
            if chart_type == "area":
                base = vy(max(vmin, 0))
                area = f"{pts[0][0]:.1f},{base:.1f} " + pts_str + f" {pts[-1][0]:.1f},{base:.1f}"
                parts.append(f'<polygon points="{area}" fill="{color}" fill-opacity="0.18"/>')
            parts.append(
                f'<polyline points="{pts_str}" fill="none" stroke="{color}" '
                f'stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>'
            )
            for px, py in pts:
                parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.6" fill="{color}"/>')

    # legend
    lx = x0
    ly = 22
    for si, s in enumerate(clean_series):
        color = palette[si % len(palette)]
        parts.append(f'<rect x="{lx}" y="{ly - 9}" width="11" height="11" rx="2" fill="{color}"/>')
        name = html.escape(s["name"])
        parts.append(f'<text x="{lx + 16}" y="{ly}" font-size="12" fill="#374151">{name}</text>')
        lx += 20 + 8 * len(s["name"]) + 24

    parts.append("</svg>")
    if truncated:
        parts.append(
            f'<div style="font-size:12px;color:#6b7280;margin-top:6px">'
            f'Showing first {max_points} of {len(series[0]["values"])} points.</div>'
        )
    return "".join(parts)


# --- HTML report -----------------------------------------------------------

def build_html_report(
    df: pd.DataFrame,
    *,
    title: str,
    subtitle: str = "",
    notes: str = "",
    sql: str = "",
    connection_label: str = "",
    summary: dict | None = None,
    accent: str = "#8b5cf6",
    include_sql: bool = True,
    include_summary: bool = True,
    include_chart: bool = False,
    include_table: bool = True,
    table_row_limit: int = 500,
    chart_svg: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    generated_at = generated_at or datetime.now()
    esc = html.escape
    accent_soft = accent + "22"  # ~13% alpha via hex

    blocks: list[str] = []

    if include_summary and summary:
        cards = [
            ("Rows", _fmt_num(summary["rows"])),
            ("Columns", _fmt_num(summary["cols"])),
            ("Numeric columns", _fmt_num(summary["numeric_cols"])),
            ("Null cells", _fmt_num(summary["null_cells"])),
        ]
        if summary.get("elapsed_ms") is not None:
            cards.append(("Query time", f'{summary["elapsed_ms"]:.0f} ms'))
        card_html = "".join(
            f'<div class="card"><div class="card-val">{esc(v)}</div>'
            f'<div class="card-lbl">{esc(k)}</div></div>'
            for k, v in cards
        )
        blocks.append(f'<section><h2>Summary</h2><div class="cards">{card_html}</div></section>')

    if include_chart and chart_svg:
        blocks.append(f'<section><h2>Chart</h2><div class="chart">{chart_svg}</div></section>')

    if notes.strip():
        note_html = "<br>".join(esc(line) for line in notes.splitlines())
        blocks.append(f'<section><h2>Notes</h2><p class="notes">{note_html}</p></section>')

    if include_sql and sql.strip():
        blocks.append(f'<section><h2>Query</h2><pre class="sql">{esc(sql.strip())}</pre></section>')

    if include_table:
        shown = df.head(table_row_limit)
        table_html = shown.to_html(index=False, border=0, classes="data", na_rep="", escape=True)
        note = ""
        if len(df) > table_row_limit:
            note = f'<div class="tbl-note">Showing first {table_row_limit:,} of {len(df):,} rows.</div>'
        blocks.append(f'<section><h2>Data</h2>{note}<div class="tbl-wrap">{table_html}</div></section>')

    subtitle_html = f'<div class="subtitle">{esc(subtitle)}</div>' if subtitle.strip() else ""
    meta_bits = [f"Generated {generated_at:%Y-%m-%d %H:%M}"]
    if connection_label:
        meta_bits.append(esc(connection_label))
    meta_html = " · ".join(meta_bits)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
  :root {{ --accent: {accent}; --accent-soft: {accent_soft}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #f3f4f6; color: #111827;
         font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
  .page {{ max-width: 960px; margin: 0 auto; padding: 32px 24px 64px; }}
  header {{ background: linear-gradient(120deg, var(--accent), #0ea5e9);
            color: #fff; border-radius: 16px; padding: 28px 32px; margin-bottom: 28px;
            box-shadow: 0 12px 30px -12px var(--accent); }}
  header h1 {{ margin: 0; font-size: 28px; letter-spacing: -0.02em; }}
  .subtitle {{ margin-top: 6px; font-size: 15px; opacity: 0.92; }}
  .meta {{ margin-top: 14px; font-size: 12.5px; opacity: 0.85; }}
  section {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 14px;
             padding: 20px 24px; margin-bottom: 20px; }}
  h2 {{ margin: 0 0 14px; font-size: 15px; text-transform: uppercase;
        letter-spacing: 0.06em; color: #6b7280; }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 14px; }}
  .card {{ flex: 1 1 120px; background: var(--accent-soft); border: 1px solid #e5e7eb;
           border-radius: 12px; padding: 16px; }}
  .card-val {{ font-size: 24px; font-weight: 700; color: #111827; }}
  .card-lbl {{ font-size: 12px; color: #6b7280; margin-top: 4px; }}
  .chart {{ overflow-x: auto; }}
  .notes {{ margin: 0; line-height: 1.6; color: #374151; }}
  pre.sql {{ margin: 0; background: #0f172a; color: #e2e8f0; padding: 16px;
             border-radius: 10px; overflow-x: auto; font-size: 13px; line-height: 1.5; }}
  .tbl-wrap {{ overflow-x: auto; }}
  .tbl-note, .tbl-wrap + .tbl-note {{ font-size: 12px; color: #6b7280; margin-bottom: 10px; }}
  table.data {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  table.data th {{ background: var(--accent); color: #fff; text-align: left;
                   padding: 9px 12px; position: sticky; top: 0; white-space: nowrap; }}
  table.data td {{ padding: 8px 12px; border-bottom: 1px solid #eef2f7; }}
  table.data tr:nth-child(even) td {{ background: #f9fafb; }}
  footer {{ text-align: center; color: #9ca3af; font-size: 12px; margin-top: 8px; }}
  @media print {{ body {{ background: #fff; }} section {{ break-inside: avoid; }} }}
</style>
</head>
<body>
  <div class="page">
    <header>
      <h1>{esc(title)}</h1>
      {subtitle_html}
      <div class="meta">{meta_html}</div>
    </header>
    {"".join(blocks)}
    <footer>Generated by SQL Optimizer</footer>
  </div>
</body>
</html>"""


# --- byte exporters --------------------------------------------------------

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_json_bytes(df: pd.DataFrame) -> bytes:
    return json.dumps(
        json.loads(df.to_json(orient="records", date_format="iso")), indent=2
    ).encode("utf-8")


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Results")
    return buf.getvalue()
