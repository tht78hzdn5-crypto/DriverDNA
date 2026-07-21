import React from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";

// Driver Model (M6) — the constitution's centre of gravity, made visible.
// Render-only: every number here comes straight from the payload's
// driver_model section. A no_signal fundamental shows no score/confidence at
// any level (the A14 rule); the model is a driver-level belief, pooled across
// every cohort, never a per-lap measurement.

const TREND = {
  improving: { mark: "▲", cls: "ok" },
  declining: { mark: "▼", cls: "bad" },
  stable: { mark: "▬", cls: "dim" },
  unavailable: { mark: "·", cls: "dim" },
};

function pretty(id) {
  return id.replace(/_/g, " ");
}

function Belief({ id, b }) {
  const noSignal = b.signal_status === "no_signal";
  const trend = TREND[b.trend] || TREND.unavailable;
  return (
    <div className={`finding ${noSignal ? "suppressed" : ""}`}>
      <div className="head">
        <span className="desc">
          {pretty(id)}
          <span className="src-tag" style={{ marginLeft: "0.5rem" }}>{b.signal_status}</span>
        </span>
        {/* A no_signal fundamental renders NO score/confidence — ever. */}
        {!noSignal && <span className="val num">{fmt(b.score, 1)}</span>}
      </div>
      {noSignal ? (
        <div className="reason">{b.insufficient_reason || "no signal yet — insufficient data"}</div>
      ) : (
        <div className="meta">
          confidence <span className="num">{fmt(b.confidence, 2)}</span> ·
          evidence <span className="num">{b.evidence_count}</span> laps ·
          trend <span className={trend.cls}>{trend.mark} {b.trend}</span>
        </div>
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
      <div className="grid">
        <section className="panel">
          <h1>Driver Model</h1>
          <div className="dim">No model yet — import laps first.</div>
        </section>
      </div>
    );
  }

  const beliefs = Object.entries(model.beliefs);
  const measured = beliefs.filter(([, b]) => b.signal_status !== "no_signal");
  const noSignal = beliefs.filter(([, b]) => b.signal_status === "no_signal");

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

      <section className="panel">
        <p className="eyebrow">Fundamentals — score · confidence · evidence · trend</p>
        {measured.length === 0 && (
          <div className="dim">Nothing measured yet — every fundamental is below signal.</div>
        )}
        {measured.map(([id, b]) => <Belief key={id} id={id} b={b} />)}
      </section>

      {noSignal.length > 0 && (
        <section className="panel">
          <p className="eyebrow">No signal yet — stated, never scored</p>
          {noSignal.map(([id, b]) => <Belief key={id} id={id} b={b} />)}
        </section>
      )}
    </div>
  );
}
