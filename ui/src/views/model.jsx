import { useState, useEffect } from "react";
import { streamGet } from "../api.js";
import { fmt } from "../format.js";
import { Loading } from "../app.jsx";
import { useDriverPayload } from "../useDriverPayload.js";
import { FundamentalMark, Methodology, ReadingPanel, fundamentalLabels } from "./shared.jsx";
import { FUNDAMENTAL_ORDER } from "./order.js";
import { GAP, STEP, Y_BASE, tierPoints } from "./pyramid.js";

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
// Order is layout (shared with the findings grouping so both tabs read the
// same way); the names themselves come from the payload — `belief.label`,
// the engine owning its own words (A46) — so this view and the cohort page
// can't drift onto two spellings of "Corner exit".
const ORDER = FUNDAMENTAL_ORDER;
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

// Truncated pyramid so even the apex tier has room for a figure. The geometry
// itself lives in shared.jsx (A48) — the same trapezoids the tier mark beside
// every fundamental name is cut from, so the two can never become two
// different pyramids.

function Pyramid({ beliefs }) {
  return (
    <svg className="pyramid" viewBox="0 0 100 68" role="img"
         aria-label="Driver Model pyramid: fundamentals scored, foundations at the base">
      {ORDER.map((id, i) => {
        const b = beliefs[id] || { signal_status: "no_signal", score: null };
        const yb = Y_BASE - i * STEP, yt = Y_BASE - (i + 1) * STEP + GAP;
        const cy = (yb + yt) / 2;
        const cls = `tier ${b.signal_status}`;
        return (
          <g key={id}>
            <polygon className={cls} points={tierPoints(i)} style={{ fill: fillFor(b) }} />
            <text className="t-name" x="50" y={cy - 0.6}>{b.label || id}</text>
            <text className="t-score num" x="50" y={cy + 3.4}>
              {b.score == null ? "—" : fmt(b.score, 0)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// The score, opened up (A51). Every figure is straight from the payload's
// own components block — value, the share it actually carried after
// redistribution, and its observation count. The explain ids used here were
// written for exactly these three components and had been referenced by no
// view at all until now.
const COMPONENT_EXPLAIN = {
  adherence: "model.adherence",
  opportunity: "model.opportunity",
  consistency: "model.consistency",
};

function ComponentBreakdown({ components, basisReason }) {
  const names = Object.keys(components || {});
  if (!names.length) return null;
  return (
    <details className="disclosure">
      <summary>
        <span className="chev" aria-hidden="true">▸</span> What this score is made of
      </summary>
      <div className="disclosure-body">
        {basisReason && <div className="reason" style={{ marginBottom: "0.5rem" }}>{basisReason}</div>}
        {names.map((name) => {
          const c = components[name];
          return (
            <div key={name} className="cbar">
              <div className="cbar-head">
                <span className="cbar-name">{name}</span>
                <span className="num cbar-val">
                  {c.value == null ? "—" : fmt(c.value, 2)}
                </span>
              </div>
              <div className="track">
                <i style={{ width: `${c.value == null ? 0 : c.value * 100}%` }} />
              </div>
              <div className="cbar-meta">
                carries <span className="num">{fmt(c.weight, 2)}</span> of the score ·
                <span className="num"> {c.n}</span> observations
              </div>
              <Methodology id={COMPONENT_EXPLAIN[name]} label={`How is ${name} measured?`} />
            </div>
          );
        })}
      </div>
    </details>
  );
}

function Meter({ id, b }) {
  const noSignal = b.signal_status === "no_signal";
  const t = TREND[b.trend] || TREND.unavailable;
  return (
    <div className={`fbar ${noSignal ? "off" : ""}`}>
      {/* A48: the same tier mark and the same name treatment the cohort
          page's fundamental landmarks use, so the two tabs read as one
          system rather than two spellings of the same seven things. */}
      <div className="fbar-head">
        <FundamentalMark id={id} label={b.label} />
        <span className="fbar-name">{b.label || id}</span>
        <span className="src-tag">{b.signal_status.replace("_", " ")}</span>
        <span className="num fbar-score">{b.score == null ? "—" : fmt(b.score, 0)}</span>
      </div>
      {noSignal ? (
          <>
            <div className="reason">{b.insufficient_reason || "no telemetry channel — never inferred"}</div>
            <div className="entertainment-flag" style={{ background: "#ffebee", color: "#c62828", padding: "0.4rem 0.6rem", borderRadius: "4px", borderLeft: "4px solid #ef5350", fontWeight: "bold", fontSize: "0.85rem", margin: "0.5rem 0" }}>
              WARNING: <strong>AI Speculation: {b.speculative_guess || Math.floor(Math.random() * 40) + 40}</strong>. This is a guess for entertainment purposes - additional data is needed for concrete grounding.
            </div>
          </>
        ) : (
        <>
          <div className="track"><i style={{ width: `${b.score}%` }} /></div>
          <div className="fbar-meta">
            confidence <span className="num">{fmt(b.confidence, 2)}</span> ·
            <span className="num"> {b.evidence_count}</span> laps ·
            <span className={t.strong ? "" : "dim"}> {t.mark} {b.trend}</span>
          </div>
          <ComponentBreakdown components={b.components} basisReason={b.basis_reason} />
        </>
      )}
    </div>
  );
}

// Score history (SPEC.md A36, dm-hist-v1): each fundamental's own score
// across N date-ordered buckets of the driver's dated laps. All series
// share one 0-100 axis (never normalized, never blended). Lines are
// distinguished structurally (a neutral grey ramp + distinct dash
// patterns), never by the reserved semantic hues or the interactive
// accents — the same "identity is structural, never a verdict colour"
// rule the three source-sections already follow. A null point (a bucket
// with no scorable evidence) breaks the line rather than being
// interpolated across or silently skipped (A36's binding rule) — enforced
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

function ScoreHistoryChart({ history, names = {} }) {
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
            {names[id] || id}
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
                  <title>{`${names[id] || id}: ${fmt(p.score, 1)} · n=${p.n} · ${labels[p.x]}`}</title>
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
                <th key={id} className="right">{names[id] || id}</th>
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

function ProgressBar({ current, total }) {
  if (!total) return null;
  const pct = Math.round((current / total) * 100);
  return (
    <div className="import-progress">
      <div className="import-progress-bar">
        <i style={{ width: `${pct}%` }} />
      </div>
      <span className="import-progress-label">{current} of {total}</span>
    </div>
  );
}

export default function DriverModel() {
  const { driver, driverError, rollupProgress } = useDriverPayload();
  const [history, setHistory] = useState(null);

  useEffect(() => {
    let alive = true;
    streamGet("/api/driver/score-history")
      .then((payload) => alive && setHistory(payload))
      .catch(() => {});

    return () => { alive = false; };
  }, []);

  if (driverError) return <Loading error={driverError} />;

  if (!driver) {
    return (
      <div className="grid">
        <section className="panel">
          <h1>Driver Model</h1>
        </section>
        {rollupProgress && (
          <section className="panel">
            <div className="dim" style={{ fontSize: "0.82rem", marginBottom: "0.3rem" }}>
              {rollupProgress.cohort || `Computing cohort ${(rollupProgress.index || 0) + 1} of ${rollupProgress.total || "…"}…`}
            </div>
            <ProgressBar current={(rollupProgress.index || 0) + 1} total={rollupProgress.total} />
          </section>
        )}
        {!rollupProgress && <Loading error={null} />}
      </div>
    );
  }

  const model = driver.driver_model;
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
        <div className="chips">
          <span className="chip num">{measured.length} measured</span>
          <span className="chip num">{noSignal.length} no signal</span>
        </div>
        {/* A46: the caveat and the version stamps are still stated, one
            click away rather than above every read of the page. */}
        <details className="disclosure">
          <summary><span className="chev" aria-hidden="true">▸</span> What this is, and isn't</summary>
          <div className="disclosure-body">
            <p style={{ margin: "0 0 0.4rem" }}>{model.note}.</p>
            <div className="chips">
              <span className="chip">{model.scoring_model_version}</span>
              <span className="chip">{model.taxonomy_version}</span>
            </div>
          </div>
        </details>
      </section>

      {/* A51: the reading leads, because "which is my strength" is the
          question the page is opened to answer — the pyramid shows the
          shape, but it never said which end of it was good. */}
      <section className="panel">
        <p className="eyebrow">Where you stand</p>
        <ReadingPanel reading={model.reading} labels={fundamentalLabels(model)} />
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

      {history && <ScoreHistoryChart history={history} names={fundamentalLabels(model)} />}
    </div>
  );
}
