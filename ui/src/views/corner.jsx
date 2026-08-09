import { useState } from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { ContextStrip, Loading, useFetch } from "../app.jsx";
import { FundamentalSections, Methodology, fundamentalLabels } from "./shared.jsx";

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
  // R2 (SPEC.md A39): the reference phase-time envelope, overlaid on the
  // self baselines below rather than a separate section -- same table, its
  // own columns, so a gap is never blended into the self numbers it's
  // measured against.
  const refPhases = useFetch(
    () => get(`/api/cohorts/${slug}/corners/${cornerId}/reference-phases`),
    [slug, cornerId],
  );
  if (!payload.data) return <Loading error={payload.error} />;

  const p = payload.data;
  const corner = p.corner_map.find((c) => c.corner_id === cornerId);
  const baselines = p.phase_baselines[cornerId] || {};
  const findings = p.findings.filter((f) => f.corner_id === cornerId);

  return (
    <div className="grid">
      <section className="panel">
        <h1>{cornerId} <span className="dim">· {corner?.class || "unclassified"} · apex {fmt(corner?.apex_pct, 1)}% lap</span></h1>
        <ContextStrip slug={slug} here="" />
      </section>

      <section className="panel">
        <p className="eyebrow">Phase times over the frozen canonical windows (s)</p>
        <Methodology id="baseline.robust" label="How are these baselines calculated?" />
        <div className="scroll-x">
          <table>
            <thead><tr><th>phase</th><th className="right">n</th><th className="right">median</th>
              <th className="right">robust best</th><th className="right">single best*</th>
              <th className="right">spread</th><th className="right">outliers screened</th>
              <th className="right">ref n</th><th className="right">ref median</th><th className="right">ref best</th>
            </tr></thead>
            <tbody>
              {["entry", "mid", "exit"].map((phase) => {
                const b = baselines[phase];
                const ref = refPhases.data ? refPhases.data[phase] : null;
                if (!b) return (
                  <tr key={phase}><td className="dim">{phase}</td>
                    <td colSpan="9" className="dim">not defined for this corner (stated, not hidden)</td></tr>
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
                    <td className="right num dim">{ref ? ref.n : "—"}</td>
                    <td className="right num dim">{ref ? fmt(ref.median_s) : "—"}</td>
                    <td className="right num dim">{ref ? fmt(ref.best_s) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="sub">
          * one execution — context, never the yardstick. ref n/median/best: the
          reference-lap envelope for this phase — gap context, never blended
          with your own numbers above.
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">Metric distribution — self laps only</p>
        <select className="in" style={{ width: "auto" }} value={metric}
                onChange={(e) => setMetric(e.target.value)}>
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

      {/* A46: the same fundamental grouping the cohort page uses, so one
          corner's braking and rotation findings read apart rather than as
          one undifferentiated list. */}
      <section className="panel">
        <p className="eyebrow">Findings at this corner</p>
        <FundamentalSections
          findings={findings} slug={slug}
          labels={fundamentalLabels(p.driver_model)}
        />
      </section>
    </div>
  );
}
