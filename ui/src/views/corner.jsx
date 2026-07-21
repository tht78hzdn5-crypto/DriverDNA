import React, { useState } from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";

// Corner drill (UI-SPEC view 3): phase baselines with their labels intact
// (robust primary, single-best labeled), metric summaries, and a live
// distribution from the same read path the chat tools use.
export default function CornerDrill({ slug, cornerId }) {
  const payload = useFetch(() => get(`/api/cohorts/${slug}/payload`), [slug]);
  const [metric, setMetric] = useState("min_speed_kmh");
  const dist = useFetch(
    () => get(`/api/metrics/${cornerId}/${metric}/distribution?cohort=${slug}`).catch((e) => ({ error: String(e.message) })),
    [slug, cornerId, metric],
  );
  if (!payload.data) return <Loading error={payload.error} />;

  const p = payload.data;
  const corner = p.corner_map.find((c) => c.corner_id === cornerId);
  const baselines = p.phase_baselines[cornerId] || {};
  const metrics = p.metrics[cornerId] || {};
  const findings = p.findings.filter((f) => f.corner_id === cornerId);

  return (
    <div className="grid">
      <section className="panel">
        <h1>{cornerId} <span className="dim">· {corner?.class || "unclassified"} · apex {fmt(corner?.apex_pct, 1)}% lap</span></h1>
        <div className="sub"><a href={`#/cohort/${slug}`}>← cohort</a></div>
      </section>

      <section className="panel">
        <p className="eyebrow">Phase times over the frozen canonical windows (s)</p>
        <div className="scroll-x">
          <table>
            <thead><tr><th>phase</th><th className="right">n</th><th className="right">median</th>
              <th className="right">robust best</th><th className="right">single best*</th>
              <th className="right">spread</th><th className="right">outliers screened</th></tr></thead>
            <tbody>
              {["entry", "mid", "exit"].map((phase) => {
                const b = baselines[phase];
                if (!b) return (
                  <tr key={phase}><td className="dim">{phase}</td>
                    <td colSpan="6" className="dim">not defined for this corner (stated, not hidden)</td></tr>
                );
                return (
                  <tr key={phase}>
                    <td>{phase}</td>
                    <td className="right num">{b.n}</td>
                    <td className="right num">{fmt(b.median_s)}</td>
                    <td className="right num">{fmt(b.robust_best_s)}</td>
                    <td className="right num lap-best">{fmt(b.single_best_s)}</td>
                    <td className="right num">{fmt(b.spread_s)}</td>
                    <td className="right num">{b.n_outliers}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="sub">* one execution — context, never the yardstick.</div>
      </section>

      <section className="panel">
        <p className="eyebrow">Metric distribution — live from the DB (self laps only)</p>
        <select value={metric} onChange={(e) => setMetric(e.target.value)}
                style={{ background: "var(--raised)", color: "var(--text)",
                         border: "1px solid var(--line)", padding: "0.3rem" }}>
          {Object.keys(p.metric_definitions).map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        {dist.data && !dist.data.error ? (
          <div style={{ marginTop: "0.6rem" }}>
            <div className="num">
              n={dist.data.n} · median {fmt(dist.data.median)} {dist.data.unit} · spread {fmt(dist.data.spread)}
            </div>
            <div className="dim num" style={{ fontSize: "0.78rem", marginTop: "0.3rem" }}>
              per lap: {dist.data.values.map((v) => fmt(v, 2)).join(" · ")}
            </div>
            <div className="sub">{p.metric_definitions[metric]?.description}</div>
          </div>
        ) : (
          <div className="reason" style={{ marginTop: "0.6rem" }}>{dist.data?.error || "loading…"}</div>
        )}
      </section>

      <section className="panel">
        <p className="eyebrow">Findings at this corner</p>
        {findings.map((f) => (
          <div key={f.finding_id} className={`finding ${f.shown && !f.annotation ? "" : "suppressed"}`}>
            <div className="head">
              <span className="desc">
                <span className="src-tag">{f.source}</span>
                <a href={`#/finding/${slug}/${encodeURIComponent(f.finding_id)}`}>{f.description}</a>
              </span>
              <span className="val num">{f.seconds === null ? "" : `${fmt(f.seconds)} s`}</span>
            </div>
            {!f.shown && <div className="reason">{f.gate_reason}</div>}
          </div>
        ))}
      </section>
    </div>
  );
}
