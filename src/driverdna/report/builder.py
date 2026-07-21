"""ReportBuilder: Markdown + JSON + self-contained static HTML (M4).

All three render from the same deterministic payload (report/payload.py) —
the JSON report IS the payload. HTML is one self-contained file per cohort
plus a rolling driver.html: inline CSS, inline hand-rolled SVG charts
(cumulative loss by phase, loss by class, lap trend). No server, no external
assets, no build step, no timestamps.

Styling (U4, 2026-07-21): mirrors `ui/tokens.json`, the SPA's single visual
source of truth (UI-SPEC.md, "Design language and tokens" — "consumed by
both [surfaces]"). `_TOKENS` below is that mirror, made explicit because a
static HTML file has no JS runtime to import the JSON at render time (the
SPA's `main.jsx` does the equivalent by injecting each color as a CSS custom
property); `tests/test_report.py` asserts `_TOKENS` matches `ui/tokens.json`
byte-for-byte so the two surfaces can't silently drift. Declared as CSS
custom properties in one `:root` block so both the stylesheet and the
inline SVG (`fill="var(--dim)"` etc. — a standard SVG presentation-attribute
capability) reference the same names. Fonts name IBM Plex first, same as
the SPA, but the files themselves are not bundled into reports (SPA-only,
owner decision 2026-07-21) — an unavailable named font just falls through
to the next stack entry, so this stays fully offline and self-contained.
"""

from __future__ import annotations

import html
from typing import Any

# Mirrors ui/tokens.json exactly — kept in sync by test_report.py.
_TOKENS = {
    "base": "#101318", "panel": "#171B22", "raised": "#1F242D", "line": "#2A303A",
    "text": "#E8EAED", "dim": "#8C93A0", "best": "#B48CFF", "ok": "#3ECF8E",
    "warn": "#E8A13C", "bad": "#E5484D", "accent": "#6EA8D8",
    "mono": "'IBM Plex Mono', ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, monospace",
    "sans": "'IBM Plex Sans', -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
}

# The SPA's own default chart-bar fill (app.css `.lossrow .bar i`) — one
# non-semantic data color, not itself a design token, kept identical here
# so bar/line charts read the same on both surfaces (UI-SPEC: "share one
# appearance"). The single largest bar highlights in `--warn`, mirroring
# `.lossrow.max .bar i` — direction, not alarm (color grammar rule 1).
_DATA_COLOR = "#46566B"

_CSS = ("""
:root {{
  --base: {base}; --panel: {panel}; --raised: {raised}; --line: {line};
  --text: {text}; --dim: {dim}; --best: {best}; --ok: {ok};
  --warn: {warn}; --bad: {bad}; --accent: {accent};
  --mono: {mono}; --sans: {sans};
}}
body {{
  font-family: var(--sans); max-width: 60rem; margin: 2rem auto; padding: 0 1rem;
  background: var(--base); color: var(--text); line-height: 1.45;
}}
h1, h2, h3 {{ line-height: 1.2; }}
a {{ color: var(--accent); }}
table {{ border-collapse: collapse; margin: 0.75rem 0; font-size: 0.9rem;
         width: 100%; font-variant-numeric: tabular-nums; }}
th, td {{ border-top: 1px solid var(--line); padding: 0.4rem 0.55rem; text-align: left; }}
th {{ border-top: 0; color: var(--dim); font-weight: 500; font-size: 0.72rem;
      letter-spacing: 0.08em; text-transform: uppercase; }}
.suppressed {{ color: var(--dim); }}
.tag {{ font-size: 0.68rem; letter-spacing: 0.08em; text-transform: uppercase;
        color: var(--dim); border: 1px solid var(--line); border-radius: 2px;
        padding: 0.05rem 0.4rem; margin-right: 0.4rem; background: var(--raised); }}
svg {{ max-width: 100%; height: auto; }}
svg text {{ fill: var(--dim); font-family: var(--mono); }}
.caveat {{ background: var(--raised); border-left: 3px solid var(--warn);
           padding: 0.5rem 0.8rem; margin: 0.5rem 0; color: var(--text); }}
""".strip()).format(**_TOKENS)


def _bar_chart(title: str, data: list[tuple[str, float]], unit: str = "s") -> str:
    if not data:
        return ""
    width, bar_h, gap, label_w = 640, 26, 8, 130
    peak = max(abs(v) for _, v in data) or 1.0
    max_abs = max(abs(v) for _, v in data)
    rows = []
    for i, (label, value) in enumerate(data):
        y = i * (bar_h + gap)
        w = max(1.0, abs(value) / peak * (width - label_w - 90))
        fill = "var(--warn)" if abs(value) == max_abs else _DATA_COLOR
        rows.append(
            f'<text x="{label_w - 8}" y="{y + bar_h * 0.7:.0f}" '
            f'text-anchor="end" font-size="12">{html.escape(label)}</text>'
            f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_h}" '
            f'fill="{fill}"/>'
            f'<text x="{label_w + w + 6:.1f}" y="{y + bar_h * 0.7:.0f}" '
            f'font-size="12">{value:.3f} {unit}</text>'
        )
    height = len(data) * (bar_h + gap)
    return (
        f"<h3>{html.escape(title)}</h3>"
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{html.escape(title)}">' + "".join(rows) + "</svg>"
    )


def _line_chart(title: str, values: list[float], unit: str = "s") -> str:
    if len(values) < 2:
        return ""
    width, height, pad = 640, 200, 40
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pts = []
    for i, v in enumerate(values):
        x = pad + i * (width - 2 * pad) / (len(values) - 1)
        y = height - pad - (v - lo) / span * (height - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return (
        f"<h3>{html.escape(title)}</h3>"
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{html.escape(title)}">'
        f'<polyline fill="none" stroke="{_DATA_COLOR}" stroke-width="2" '
        f'points="{" ".join(pts)}"/>'
        f'<text x="{pad}" y="{height - 8}" font-size="11">first lap</text>'
        f'<text x="{width - pad}" y="{height - 8}" text-anchor="end" '
        f'font-size="11">latest lap</text>'
        f'<text x="8" y="{pad}" font-size="11">{hi:.2f} {unit}</text>'
        f'<text x="8" y="{height - pad}" font-size="11">{lo:.2f} {unit}</text>'
        "</svg>"
    )


def _findings_rows_md(findings: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| source | finding | s | n | spread | status | evidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in findings:
        status = "shown" if f["shown"] else f"suppressed — {f['gate_reason']}"
        seconds = "—" if f["seconds"] is None else f"{f['seconds']:.3f}"
        spread = "—" if f["spread"] is None else f"{f['spread']:.3f}"
        evidence = f"{len(f['evidence_ids'])} refs"
        lines.append(
            f"| {f['source']} | {f['description']} | {seconds} | {f['n']} "
            f"| {spread} | {status} | {evidence} |"
        )
    return lines


def render_cohort_markdown(payload: dict[str, Any]) -> str:
    c = payload["cohort"]
    lines = [
        f"# DriverDNA report — {c['driver']} / {c['car']} @ {c['track']}",
        "",
        f"Laps: {c['n_laps']} · sessions: {c['n_sessions']} · payload v"
        f"{payload['payload_version']}. Sources are never blended; findings "
        "carry N, spread, source tag, and evidence IDs.",
        "",
        "## Findings",
        "",
    ]
    shown = [f for f in payload["findings"] if f["shown"] and not f.get("annotation")]
    annotated = [f for f in payload["findings"] if f["shown"] and f.get("annotation")]
    suppressed = [f for f in payload["findings"] if not f["shown"]]
    if shown:
        lines += _findings_rows_md(shown)
    else:
        lines.append(
            "No findings pass the confidence gates yet — insufficient data "
            "is the honest state, not a failure. Import more laps."
        )
    if annotated:
        lines += ["", "### Acknowledged / intentional (by you — measurement kept)", ""]
        for f in annotated:
            a = f["annotation"]
            note = f" — {a['note']}" if a.get("note") else ""
            lines.append(f"- {f['description']} ({a['status']}{note})")
    lines += ["", f"Suppressed findings: {len(suppressed)} (each with its "
              "stated reason — see the JSON report for the full list).", ""]

    loss = payload["cumulative_loss"]
    if loss["by_phase"]:
        lines += ["## Cumulative typical loss (s/lap vs robust baseline)", ""]
        lines += ["| by phase | s |", "|---|---|"] + [
            f"| {k} | {v:.3f} |" for k, v in sorted(loss["by_phase"].items())
        ] + [""]
        lines += ["| by class | s |", "|---|---|"] + [
            f"| {k} | {v:.3f} |" for k, v in sorted(loss["by_class"].items())
        ] + [""]

    lines += ["## Corner map", "", "| corner | class | apex (% lap) |", "|---|---|---|"]
    for corner in payload["corner_map"]:
        lines.append(
            f"| {corner['corner_id']} | {corner['class'] or 'unclassified'} "
            f"| {corner['apex_pct']:.1f} |"
        )
    lines += [
        "",
        "## Data quality",
        "",
        f"Flag counts: {payload['quality']['flag_counts'] or 'none'} · laps "
        f"with flags: {payload['quality']['n_laps_flagged']}/{c['n_laps']}",
        "",
        "## Not measured (never inferred)",
        "",
    ]
    lines += [f"- {u}" for u in payload["unavailable_fundamentals"]]
    lines += ["", "## Caveats", ""]
    lines += [f"- {v}" for v in payload["caveats"]]
    return "\n".join(lines) + "\n"


def render_cohort_html(payload: dict[str, Any]) -> str:
    c = payload["cohort"]
    shown = [f for f in payload["findings"] if f["shown"]]
    suppressed = [f for f in payload["findings"] if not f["shown"]]
    loss = payload["cumulative_loss"]

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>DriverDNA — {html.escape(c['car'])} @ {html.escape(c['track'])}</title>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>DriverDNA — {html.escape(c['driver'])} / "
        f"{html.escape(c['car'])} @ {html.escape(c['track'])}</h1>",
        f"<p>Laps: {c['n_laps']} · sessions: {c['n_sessions']} · payload "
        f"v{payload['payload_version']}. Sources are never blended.</p>",
        "<h2>Findings</h2>",
    ]
    if shown:
        parts.append("<table><tr><th>source</th><th>finding</th><th>s</th>"
                     "<th>n</th><th>spread</th><th>evidence</th></tr>")
        for f in shown:
            seconds = "—" if f["seconds"] is None else f"{f['seconds']:.3f}"
            spread = "—" if f["spread"] is None else f"{f['spread']:.3f}"
            parts.append(
                f"<tr><td><span class='tag'>{f['source']}</span></td>"
                f"<td>{html.escape(f['description'])}</td><td>{seconds}</td>"
                f"<td>{f['n']}</td><td>{spread}</td>"
                f"<td>{len(f['evidence_ids'])} refs</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append(
            "<p class='caveat'>No findings pass the confidence gates yet — "
            "insufficient data is the honest state. Import more laps.</p>"
        )
    parts.append(
        f"<p class='suppressed'>Suppressed findings: {len(suppressed)} "
        "(reasons stated in the JSON report).</p>"
    )

    if loss["by_phase"]:
        parts.append(_bar_chart(
            "Cumulative typical loss by phase (s/lap)",
            sorted(loss["by_phase"].items()),
        ))
        parts.append(_bar_chart(
            "Cumulative typical loss by corner class (s/lap)",
            sorted(loss["by_class"].items()),
        ))
    parts.append(_line_chart(
        "Lap time trend (imported order)", c["lap_durations_s"]
    ))

    parts.append("<h2>Corner map</h2><table><tr><th>corner</th><th>class</th>"
                 "<th>apex (% lap)</th></tr>")
    for corner in payload["corner_map"]:
        parts.append(
            f"<tr><td>{corner['corner_id']}</td>"
            f"<td>{corner['class'] or 'unclassified'}</td>"
            f"<td>{corner['apex_pct']:.1f}</td></tr>"
        )
    parts.append("</table>")

    parts.append("<h2>Not measured (never inferred)</h2><ul>")
    parts += [f"<li>{html.escape(u)}</li>" for u in payload["unavailable_fundamentals"]]
    parts.append("</ul><h2>Caveats</h2>")
    parts += [f"<div class='caveat'>{html.escape(v)}</div>" for v in payload["caveats"]]
    parts.append("</body></html>")
    return "".join(parts)


def render_driver_markdown(payload: dict[str, Any]) -> str:
    lines = ["# DriverDNA — driver rollup", ""]
    for c in payload["cohorts"]:
        lines.append(
            f"- {c['driver']} / {c['car']} @ {c['track']}: {c['n_laps']} laps, "
            f"{c['n_sessions']} sessions"
        )
    lines += ["", "## Cross-track rollups (within car, within class)", "",
              "| car | class | loss s/lap | tracks | status |", "|---|---|---|---|---|"]
    for r in payload["cross_track_rollups"]:
        status = "shown" if r["shown"] else f"suppressed — {r['gate_reason']}"
        lines.append(
            f"| {r['car']} | {r['class']} | {r['loss_s']:.3f} | {r['n_tracks']} "
            f"| {status} |"
        )
    lines += ["", f"_{payload['note']}._", ""]
    return "\n".join(lines)


def render_driver_html(payload: dict[str, Any]) -> str:
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>DriverDNA — driver rollup</title>",
        f"<style>{_CSS}</style></head><body><h1>DriverDNA — driver rollup</h1><ul>",
    ]
    for c in payload["cohorts"]:
        parts.append(
            f"<li>{html.escape(c['driver'])} / {html.escape(c['car'])} @ "
            f"{html.escape(c['track'])}: {c['n_laps']} laps</li>"
        )
    parts.append("</ul><h2>Cross-track rollups (within car, within class)</h2>")
    shown = [(f"{r['car']} · {r['class']}", r["loss_s"])
             for r in payload["cross_track_rollups"] if r["shown"]]
    if shown:
        parts.append(_bar_chart("Loss by car and class (s/lap)", shown))
    parts.append("<table><tr><th>car</th><th>class</th><th>loss s/lap</th>"
                 "<th>tracks</th><th>status</th></tr>")
    for r in payload["cross_track_rollups"]:
        status = "shown" if r["shown"] else html.escape(f"suppressed — {r['gate_reason']}")
        parts.append(
            f"<tr><td>{html.escape(r['car'])}</td><td>{r['class']}</td>"
            f"<td>{r['loss_s']:.3f}</td><td>{r['n_tracks']}</td><td>{status}</td></tr>"
        )
    parts.append(f"</table><p><em>{html.escape(payload['note'])}</em></p></body></html>")
    return "".join(parts)
