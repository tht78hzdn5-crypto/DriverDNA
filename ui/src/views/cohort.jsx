import React from "react";
import { get } from "../api.js";
import { fmt, lapTime } from "../format.js";
import { Loading, useFetch } from "../app.jsx";
import { LossBars, SourceSections } from "./shared.jsx";

// Cohort view (UI-SPEC view 2). The signature element: the track outline
// drawn from the driver's own retained GPS trace, corner markers at the
// frozen apex positions, warmth = attributed loss (from the payload — the
// SPA only maps values to pixels).
function TrackMap({ trace, corners, perCornerLoss, slug }) {
  const lats = trace.lat, lons = trace.lon;
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const midLat = ((minLat + maxLat) / 2) * (Math.PI / 180);
  const sx = (lon) => (lon - minLon) * Math.cos(midLat);
  const spanX = sx(maxLon) || 1;
  const spanY = (maxLat - minLat) || 1;
  const scale = 92 / Math.max(spanX, spanY);
  const px = (lon) => 4 + sx(lon) * scale;
  const py = (lat) => 4 + (maxLat - lat) * scale;
  const height = 8 + spanY * scale;

  const losses = corners.map((c) => perCornerLoss[c.corner_id] ?? null);
  const known = losses.filter((v) => v !== null);
  const cut = known.length ? [...known].sort((a, b) => b - a)[Math.floor(known.length / 3)] : Infinity;

  const points = lats.map((lat, i) => `${px(lons[i]).toFixed(2)},${py(lat).toFixed(2)}`).join(" ");
  return (
    <svg className="trackmap" viewBox={`0 0 100 ${height.toFixed(1)}`} role="img"
         aria-label="track outline from your GPS trace">
      <polyline className="outline" points={points} />
      {corners.map((c, i) => (
        <g key={c.corner_id}>
          <a href={`#/corner/${slug}/${c.corner_id}`}>
            <circle
              className={`marker ${losses[i] !== null && losses[i] >= cut ? "hot" : ""}`}
              cx={px(c.lon)} cy={py(c.lat)} r="2.1"
            />
            <text x={px(c.lon) + 2.8} y={py(c.lat) + 1}>{c.corner_id}</text>
          </a>
        </g>
      ))}
    </svg>
  );
}

export default function Cohort({ slug }) {
  const payload = useFetch(() => get(`/api/cohorts/${slug}/payload`), [slug]);
  const corners = useFetch(() => get(`/api/cohorts/${slug}/corners`), [slug]);
  const trace = useFetch(() => get(`/api/cohorts/${slug}/track-trace`).catch(() => null), [slug]);
  if (!payload.data || !corners.data) return <Loading error={payload.error || corners.error} />;

  const p = payload.data;
  const c = p.cohort;
  const perCornerLoss = p.cumulative_loss.per_corner_total || {};
  const shownCount = p.findings.filter((f) => f.shown && !f.annotation).length;
  const suppressedCount = p.findings.filter((f) => !f.shown).length;

  return (
    <div className="grid">
      <section className="panel">
        <h1>{c.car} @ {c.track}</h1>
        <div className="chips">
          <span className="chip num">{c.n_laps} laps</span>
          <span className="chip num">{c.n_sessions} session{c.n_sessions === 1 ? "" : "s"}</span>
          <span className="chip num">{shownCount} findings shown</span>
          <span className="chip num">{suppressedCount} suppressed, reasons stated</span>
        </div>
      </section>

      {trace.data && (
        <section className="panel">
          <p className="eyebrow">Your line — lap {trace.data.lap_id} · markers at frozen apexes · amber = highest attributed loss</p>
          <TrackMap trace={trace.data} corners={corners.data} perCornerLoss={perCornerLoss} slug={slug} />
        </section>
      )}

      <section className="panel">
        <p className="eyebrow">Typical loss vs robust baseline (s/lap)</p>
        {Object.keys(p.cumulative_loss.by_phase).length > 0 ? (
          <>
            <LossBars entries={Object.entries(p.cumulative_loss.by_phase).sort()} />
            <div style={{ height: "0.6rem" }} />
            <LossBars entries={Object.entries(p.cumulative_loss.by_class).sort()} />
          </>
        ) : (
          <div className="dim">No attributable phases yet.</div>
        )}
      </section>

      <section className="panel">
        <p className="eyebrow">Findings — three sources, never blended</p>
        <SourceSections findings={p.findings} slug={slug} />
      </section>

      {p.incidents && p.incidents.n > 0 && (
        <section className="panel">
          <p className="eyebrow">Incidents — spins, offs, near-stops · single events, not traits</p>
          {p.incidents.events.map((e) => (
            <div key={e.incident_id}
                 className={`finding ${e.classification === "unclassified" ? "suppressed" : ""}`}>
              <div className="head">
                <span className="desc">
                  {e.corner_id ? <a href={`#/corner/${slug}/${e.corner_id}`}>{e.corner_id}</a> : "—"}
                  {" · "}{e.classification.replace(/_/g, " ")}
                </span>
                <span className="val">{e.confidence}</span>
              </div>
              <div className="meta">
                {e.kinds} · min <span className="num">{fmt(e.min_speed_kmh, 0)}</span> km/h ·
                peak yaw <span className="num">{fmt(e.peak_yaw_rate)}</span> rad/s · {e.lap_id}
              </div>
              <div className="reason">{e.rationale}</div>
            </div>
          ))}
          <div className="sub">{p.incidents.note}</div>
        </section>
      )}

      <section className="panel">
        <p className="eyebrow">Corners</p>
        <div className="scroll-x">
          <table>
            <thead><tr><th>corner</th><th>class</th><th className="right">apex % lap</th><th className="right">loss s/lap</th></tr></thead>
            <tbody>
              {p.corner_map.map((corner) => (
                <tr key={corner.corner_id}>
                  <td><a href={`#/corner/${slug}/${corner.corner_id}`}>{corner.corner_id}</a></td>
                  <td className="dim">{corner.class || "unclassified"}</td>
                  <td className="right num">{fmt(corner.apex_pct, 1)}</td>
                  <td className="right num">
                    {perCornerLoss[corner.corner_id] === undefined ? "—" : fmt(perCornerLoss[corner.corner_id])}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">Lap board</p>
        <div className="scroll-x">
          <table>
            <tbody>
              {c.lap_durations_s.map((duration, i) => (
                <tr key={i}>
                  <td className="dim num">{i + 1}</td>
                  <td className={`num ${c.lap_delta_s[i] === 0 ? "lap-best" : ""}`}>{lapTime(duration)}</td>
                  <td className="dim num right">{c.lap_delta_s[i] === 0 ? "best" : `+${fmt(c.lap_delta_s[i])}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="sub">Not measured, never inferred: {p.unavailable_fundamentals[0]}; full list in the report.</div>
      </section>
    </div>
  );
}
