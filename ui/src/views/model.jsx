import React from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";

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

export default function DriverModel() {
  const driver = useFetch(() => get("/api/driver"), []);
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
        {measured.map((id) => <Meter key={id} id={id} b={beliefs[id]} />)}
      </section>

      {noSignal.length > 0 && (
        <section className="panel">
          <p className="eyebrow">No signal yet — stated, never scored</p>
          {noSignal.map((id) => <Meter key={id} id={id} b={beliefs[id]} />)}
        </section>
      )}
    </div>
  );
}
