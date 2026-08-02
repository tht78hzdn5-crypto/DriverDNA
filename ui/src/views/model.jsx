import React, { useState } from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";
import { Methodology } from "./shared.jsx";

// Driver Model (M6) — the constitution's centre of gravity, made visible.
// Render-only: every number here is straight from the payload's driver_model
// section. Honesty guardrails, enforced in the view: a no_signal fundamental
// shows no score or confidence at any level (the A14 rule); score magnitude
// uses a neutral sequential ramp, never the reserved semantic colors — the
// instrument does not editorialize about driving with alarm colour (UI-SPEC
// colour grammar). The pyramid's height is a fixed layout (how a corner is
// built up, foundations to peak), never a ranking, and no tier is a blended
// "overall".

// Foundations (the physical arc of a corner) at the base; higher-order,
// harder-to-measure skills toward the peak. Fixed order — stable regardless
// of score, so the shape never implies a leaderboard.
const ORDER = [
  "braking", "rotation", "corner_exit",
  "commitment", "consistency", "vehicle_management", "vision",
];
const LABEL = {
  braking: "Braking", rotation: "Rotation", corner_exit: "Corner exit",
  commitment: "Commitment", consistency: "Consistency",
  vehicle_management: "Vehicle mgmt", vision: "Vision",
};
const TREND = {
  improving: { mark: "▲", strong: true },
  declining: { mark: "▼", strong: true },
  stable: { mark: "▬", strong: false },
  unavailable: { mark: "·", strong: false },
};

// Neutral single-hue magnitude ramp (NOT the interactive accent, NOT a
// semantic hue): higher score = more opaque. Score is the number on the tier;
// opacity is only the at-a-glance gradient.
const DATA = "70, 100, 140"; // muted steel-grey, rgb
const fillFor = (b) =>
  b.score == null ? "transparent" : `rgba(${DATA}, ${0.18 + 0.8 * (b.score / 100)})`;

// Truncated pyramid so even the apex tier has room for a figure. Geometry in
// SVG user units; tier 0 is the base (widest), tier 6 the peak.
const Y_BASE = 65, Y_TOP = 3, TIERS = ORDER.length;
const STEP = (Y_BASE - Y_TOP) / TIERS, GAP = 1.1;
const edgeX = (y, side) => {
  const t = (Y_BASE - y) / (Y_BASE - Y_TOP); // 0 base → 1 peak
  const [baseL, baseR, apexL, apexR] = [4, 96, 39, 61];
  return side < 0 ? baseL + t * (apexL - baseL) : baseR + t * (apexR - baseR);
};

function Pyramid({ beliefs }) {
  return (
    <svg className="pyramid" viewBox="0 0 100 68" role="img"
         aria-label="Driver Model pyramid: fundamentals scored, foundations at the base">
      {ORDER.map((id, i) => {
        const b = beliefs[id] || { signal_status: "no_signal", score: null };
        const yb = Y_BASE - i * STEP, yt = Y_BASE - (i + 1) * STEP + GAP;
        const cy = (yb + yt) / 2;
        const pts = [
          [edgeX(yb, -1), yb], [edgeX(yb, 1), yb],
          [edgeX(yt, 1), yt], [edgeX(yt, -1), yt],
        ].map((p) => p.map((n) => n.toFixed(2)).join(",")).join(" ");
        const cls = `tier ${b.signal_status}`;
        return (
          <g key={id}>
            <polygon className={cls} points={pts} style={{ fill: fillFor(b) }} />
            <text className="t-name" x="50" y={cy - 0.6}>{LABEL[id]}</text>
            <text className="t-score num" x="50" y={cy + 3.4}>
              {b.score == null ? "—" : fmt(b.score, 0)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Meter({ id, b }) {
  const noSignal = b.signal_status === "no_signal";
  const t = TREND[b.trend] || TREND.unavailable;
  return (
    <div className={`fbar ${noSignal ? "off" : ""}`}>
      <div className="fbar-head">
        <span className="fbar-name">{LABEL[id] || id}</span>
        <span className="src-tag">{b.signal_status.replace("_", " ")}</span>
        <span className="num fbar-score">{b.score == null ? "—" : fmt(b.score, 0)}</span>
      </div>
      {noSignal ? (
        <div className="reason">{b.insufficient_reason || "no telemetry channel — never inferred"}</div>
      ) : (
        <>
          <div className="track"><i style={{ width: `${b.score}%` }} /></div>
          <div className="fbar-meta">
            confidence <span className="num">{fmt(b.confidence, 2)}</span> ·
            <span className="num"> {b.evidence_count}</span> laps ·
            <span className={t.strong ? "" : "dim"}> {t.mark} {b.trend}</span>
          </div>
        </>
      )}
    </div>
  );
}

// Score history (SPEC.md A34, dm-hist-v1): each fundamental's own score
// across N date-ordered buckets of the driver's dated laps. All series
// share one 0-100 axis (never normalized, never blended). Lines are
// distinguished structurally (a neutral grey ramp + distinct dash
// patterns), never by the reserved semantic hues or the interactive
// accents — the same "identity is structural, never a verdict colour"
// rule the three source-sections already follow. A null point (a bucket
// with no scorable evidence) breaks the line rather than being
// interpolated across or silently skipped (A34's binding rule) — enforced
// here by splitting each series into contiguous runs of non-null points
// and drawing one <polyline> per run.
const HISTORY_STYLE = {
  braking: { stroke: "#C7CCD4", dash: "" },
  rotation: { stroke: "#A9B0BC", dash: "6,3" },
  corner_exit: { stroke: "#8C93A0", dash: "2,2" },
  commitment: { stroke: "#767E8E", dash: "8,2,2,2" },
  consistency: { stroke: "#5E6678", dash: "10,4" },
  vehicle_management: { stroke: "#464E60", dash: "4,4,1,4" },
  vision: { stroke: "#2E3548", dash: "1,3" },
};

function _runs(points) {
  // Contiguous runs of non-null scores, as [{x, y}] index/value pairs;
  // consecutive runs are gaps a line is never drawn across.
  const out = [];
  let current = [];
  for (const p of points) {
    if (p.score === null) {
      if (current.length) out.push(current);
      current = [];
    } else {
      current.push(p);
    }
  }
  if (current.length) out.push(current);
  return out;
}

function ScoreHistoryChart({ history }) {
  const seriesKeys = Object.keys(history.series);
  const [selected, setSelected] = useState(() => new Set(seriesKeys));

  if (history.x_axis.kind === "unavailable") {
    return (
      <section className="panel">
        <p className="eyebrow">Score history — over time</p>
        <Methodology id="model.history" label="How is score history calculated?" />
        <div className="empty">
          <div className="checker" aria-hidden="true" />
          <p>Not enough dated laps yet to bucket a history — keep syncing.</p>
        </div>
      </section>
    );
  }

  const labels = history.x_axis.labels;
  const n = labels.length;
  const W = 100, H = 46, padL = 6, padR = 2, padT = 4, padB = 8;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const px = (i) => padL + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const py = (score) => padT + plotH * (1 - score / 100);

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  return (
    <section className="panel">
      <p className="eyebrow">Score history — over time</p>
      <Methodology id="model.history" label="How is score history calculated?" />
      <div className="chips history-legend">
        {seriesKeys.map((id) => (
          <button
            key={id}
            type="button"
            className={`chip toggle ${selected.has(id) ? "on" : ""}`}
            style={selected.has(id) ? { borderColor: HISTORY_STYLE[id]?.stroke, color: "var(--text)" } : undefined}
            onClick={() => toggle(id)}
            aria-pressed={selected.has(id)}
          >
            {LABEL[id] || id}
          </button>
        ))}
      </div>

      <svg className="history-chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Driver Model fundamental scores over time, one line per selected fundamental">
        {[0, 50, 100].map((tick) => (
          <g key={tick}>
            <line x1={padL} x2={W - padR} y1={py(tick)} y2={py(tick)} className="history-grid" />
            <text x={padL - 1} y={py(tick) + 1} className="history-axis" textAnchor="end">{tick}</text>
          </g>
        ))}
        {seriesKeys.filter((id) => selected.has(id)).map((id) => {
          const style = HISTORY_STYLE[id] || HISTORY_STYLE.braking;
          const points = history.series[id].points;
          return (
            <g key={id}>
              {_runs(points).map((run, ri) => (
                <polyline
                  key={ri}
                  className="history-line"
                  style={{ stroke: style.stroke, strokeDasharray: style.dash || "none" }}
                  points={run.map((p) => `${px(p.x).toFixed(2)},${py(p.score).toFixed(2)}`).join(" ")}
                />
              ))}
              {points.filter((p) => p.score !== null).map((p) => (
                <circle key={p.x} cx={px(p.x)} cy={py(p.score)} r="0.9" style={{ fill: style.stroke }}>
                  <title>{`${LABEL[id] || id}: ${fmt(p.score, 1)} · n=${p.n} · ${labels[p.x]}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>

      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th>bucket</th>
              {seriesKeys.filter((id) => selected.has(id)).map((id) => (
                <th key={id} className="right">{LABEL[id] || id}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((label, i) => (
              <tr key={i}>
                <td className="dim">{label} <span className="num dim">n={history.x_axis.bucket_lap_counts[i]}</span></td>
                {seriesKeys.filter((id) => selected.has(id)).map((id) => {
                  const p = history.series[id].points[i];
                  return (
                    <td key={id} className="right num" title={p.reason || undefined}>
                      {p.score === null ? "—" : fmt(p.score, 1)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="sub">Same 0-100 axis for every fundamental — nothing normalized, nothing blended.</div>
    </section>
  );
}

export default function DriverModel() {
  const driver = useFetch(() => get("/api/driver"), []);
  const history = useFetch(() => get("/api/driver/score-history"), []);
  if (!driver.data) return <Loading error={driver.error} />;
  const model = driver.data.driver_model;
  if (!model) {
    return (
      <div className="grid"><section className="panel">
        <h1>Driver Model</h1>
        <div className="dim">No model yet — import laps first (or run <code>driverdna demo</code>).</div>
      </section></div>
    );
  }

  const beliefs = model.beliefs;
  const measured = ORDER.filter((id) => beliefs[id] && beliefs[id].signal_status !== "no_signal");
  const noSignal = ORDER.filter((id) => beliefs[id] && beliefs[id].signal_status === "no_signal");

  return (
    <div className="grid">
      <section className="panel">
        <h1>Driver Model</h1>
        <div className="sub">{model.note}.</div>
        <div className="chips">
          <span className="chip">{model.scoring_model_version}</span>
          <span className="chip">{model.taxonomy_version}</span>
          <span className="chip num">{measured.length} measured</span>
          <span className="chip num">{noSignal.length} no signal</span>
        </div>
      </section>

      <section className="panel pyramid-panel">
        <p className="eyebrow">The pyramid — foundations at the base, higher-order skills toward the peak</p>
        <Pyramid beliefs={beliefs} />
        <div className="sub">Height is layout, not a ranking — nothing is blended into an overall.</div>
      </section>

      <section className="panel">
        <p className="eyebrow">Fundamentals — score · confidence · evidence · trend</p>
        <Methodology id="model.confidence" label="How is confidence calculated?" />
        <Methodology id="model.trend" label="How is trend calculated?" />
        {measured.map((id) => <Meter key={id} id={id} b={beliefs[id]} />)}
      </section>

      {noSignal.length > 0 && (
        <section className="panel">
          <p className="eyebrow">No signal yet — stated, never scored</p>
          {noSignal.map((id) => <Meter key={id} id={id} b={beliefs[id]} />)}
        </section>
      )}

      {history.data && <ScoreHistoryChart history={history.data} />}
    </div>
  );
}
