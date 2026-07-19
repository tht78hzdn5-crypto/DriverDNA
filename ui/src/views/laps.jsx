import React from "react";
import { get } from "../api.js";
import { lapTime } from "../format.js";
import { Loading, useFetch } from "../app.jsx";

// Laps (UI-SPEC view 7): the data-quality conscience — every flag surfaced.
export default function Laps({ slug }) {
  const laps = useFetch(() => get(`/api/laps?cohort=${slug}`), [slug]);
  if (!laps.data) return <Loading error={laps.error} />;

  return (
    <div className="grid">
      <section className="panel">
        <h1>Laps</h1>
        <div className="sub"><a href={`#/cohort/${slug}`}>← cohort</a> · red marks are data quality, never driving</div>
      </section>
      <section className="panel">
        <div className="scroll-x">
          <table>
            <thead><tr><th>lap</th><th>role</th><th>session</th><th className="right">time</th>
              <th>quality flags</th><th className="right">raw retained</th></tr></thead>
            <tbody>
              {laps.data.map((lap) => (
                <tr key={lap.lap_pk}>
                  <td className="num">{lap.lap_id || `#${lap.lap_pk}`}</td>
                  <td className="dim">{lap.role}</td>
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
