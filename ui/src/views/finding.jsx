import React from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";

// Finding detail (UI-SPEC view 4): the evidence view. Annotate actions are
// U2 — this view states what they will do, and shows any existing
// annotation with the measurement intact.
export default function FindingDetail({ slug, findingId }) {
  const payload = useFetch(() => get(`/api/cohorts/${slug}/payload`), [slug]);
  if (!payload.data) return <Loading error={payload.error} />;

  const finding = payload.data.findings.find((f) => f.finding_id === findingId);
  if (!finding) return <div className="error">Unknown finding: {findingId}</div>;

  const d = finding.details || {};
  return (
    <div className="grid">
      <section className="panel">
        <p className="eyebrow"><span className="src-tag">{finding.source}</span>finding</p>
        <h1>{finding.description}</h1>
        <div className="sub">
          <a href={`#/corner/${slug}/${finding.corner_id}`}>{finding.corner_id}</a>
          {finding.phase && <> · {finding.phase} phase</>} · {finding.kind}
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">Evidence</p>
        <div className="scroll-x">
          <table>
            <tbody>
              <tr><td className="dim">measured value</td>
                  <td className="num">{finding.seconds === null ? "not priced in seconds (form check)" : `${fmt(finding.seconds)} s`}</td></tr>
              <tr><td className="dim">sample size N</td><td className="num">{finding.n}</td></tr>
              <tr><td className="dim">spread</td>
                  <td className="num">{finding.spread === null ? "—" : fmt(finding.spread)}</td></tr>
              {"opportunity_s" in d && d.opportunity_s !== null && (
                <tr><td className="dim">opportunity (slower vs faster laps)</td>
                    <td className="num">{fmt(d.opportunity_s)} s</td></tr>
              )}
              {"repeatability" in d && d.repeatability !== null && (
                <tr><td className="dim">repeatability (session sign-consistency)</td>
                    <td className="num">{fmt(d.repeatability, 2)}</td></tr>
              )}
              {"trigger_rate" in d && (
                <tr><td className="dim">trigger rate</td>
                    <td className="num">{fmt(d.trigger_rate, 2)}</td></tr>
              )}
              {"n_sessions" in d && (
                <tr><td className="dim">sessions</td><td className="num">{d.n_sessions}</td></tr>
              )}
              <tr><td className="dim">status</td>
                  <td>{finding.shown ? "shown" : <span className="reason">{finding.gate_reason}</span>}</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">Evidence records ({finding.evidence_ids.length})</p>
        <div className="dim num" style={{ fontSize: "0.76rem", lineHeight: 1.8 }}>
          {finding.evidence_ids.join(" · ")}
        </div>
        <div className="sub">
          Each obs:&lt;n&gt; is a stored corner observation — a specific corner on a
          specific lap. Nothing on this page exists without them.
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">Your annotation</p>
        {finding.annotation ? (
          <div>
            <span className="chip">{finding.annotation.status}</span>
            {finding.annotation.note && <span className="dim"> — {finding.annotation.note}</span>}
            <div className="sub">Suppressed from priority framing; the measurement above is kept.</div>
          </div>
        ) : (
          <div className="dim" style={{ fontSize: "0.82rem" }}>
            None. Marking a finding acknowledged or intentional (arrives with U2,
            or via chat today) removes it from priority framing without deleting
            the measurement.
          </div>
        )}
      </section>
    </div>
  );
}
