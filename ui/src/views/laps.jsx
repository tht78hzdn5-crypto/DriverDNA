import React from "react";
import { get } from "../api.js";
import { lapTime } from "../format.js";
import { ContextStrip, Loading, useFetch } from "../app.jsx";

// Laps (UI-SPEC view 7): the data-quality conscience — every flag surfaced.
export default function Laps({ slug }) {
  const laps = useFetch(() => get(`/api/laps?cohort=${slug}`), [slug]);
  if (!laps.data) return <Loading error={laps.error} />;

  return (
    <div className="grid">
      <section className="panel">
        <h1>Laps</h1>
        <ContextStrip slug={slug} here="laps" />
        <div className="sub" style={{ marginTop: "0.5rem" }}>Red marks data quality, never driving.</div>
      </section>
      <section className="panel">
        <div className="scroll-x">
          <table>
            <thead><tr><th>lap</th><th>role</th><th>session</th><th className="right">time</th>
              <th>quality flags</th><th>incidents</th><th className="right">raw retained</th></tr></thead>
            <tbody>
              {laps.data.map((lap) => (
                <tr key={lap.lap_pk}>
                  <td className="num">{lap.lap_id || `#${lap.lap_pk}`}</td>
                  <td>{lap.role === "reference"
                    ? <span className="src-tag">reference</span>
                    : <span className="dim">self</span>}</td>
                  <td className="dim num">{lap.session_key || "—"}</td>
                  <td className="right num">{lapTime(lap.duration_s)}</td>
                  <td>
                    {lap.quality_flags.length === 0 && <span className="dim">clean</span>}
                    {lap.quality_flags.map((flag) => (
                      <span key={flag.code} className="chip" style={{ marginRight: "0.3rem" }}>
                        <span className="flag">■</span> {flag.code}
                      </span>
                    ))}
                  </td>
                  <td>
                    {lap.incidents > 0
                      ? <a href={`#/cohort/${slug}`} className="chip" title="detailed on the cohort page">
                          {lap.incidents} incident{lap.incidents === 1 ? "" : "s"}
                        </a>
                      : <span className="dim">—</span>}
                  </td>
                  <td className="right dim">{lap.raw_retained ? "yes" : "evicted (summaries kept)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
