import React from "react";
import { get } from "../api.js";
import { fmt, lapTime } from "../format.js";
import { ContextStrip, Loading, useFetch } from "../app.jsx";
import {
  CoachingHeadline, CoachingSecondary, CoachingSelfChecks, LossBars, SourceSections,
} from "./shared.jsx";

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

// Reference laps (v2): context made visible. Isolation stated once; the "who"
// named. Zero references is a designed direction state, not a blank.
function ReferenceLaps({ refLaps }) {
  return (
    <section className="panel">
      <p className="eyebrow">Reference laps</p>
      <div className="guarantee">Context only — never enters your history, trends, or scores.</div>
      {refLaps.length === 0 ? (
        <div className="empty">
          <div className="ref-empty">No reference laps yet — add a faster driver's lap for gap context.</div>
          <a className="btn-primary" href="#/upload">Import a reference lap</a>
        </div>
      ) : (
        <div className="ref-line">
          {refLaps.map((l, i) => (
            <span key={l.lap_pk}>
              {i > 0 && " · "}
              <b>{l.driver}</b> <span className="num">{lapTime(l.duration_s)}</span>
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

export default function Cohort({ slug }) {
  const payload = useFetch(() => get(`/api/cohorts/${slug}/payload`), [slug]);
  const corners = useFetch(() => get(`/api/cohorts/${slug}/corners`), [slug]);
  const trace = useFetch(() => get(`/api/cohorts/${slug}/track-trace`).catch(() => null), [slug]);
  const laps = useFetch(() => get(`/api/laps?cohort=${slug}`).catch(() => []), [slug]);
  if (!payload.data || !corners.data) return <Loading error={payload.error || corners.error} />;

  const p = payload.data;
  const c = p.cohort;
  const perCornerLoss = p.cumulative_loss.per_corner_total || {};
  const shownCount = p.findings.filter((f) => f.shown && !f.annotation).length;
  const suppressedCount = p.findings.filter((f) => !f.shown).length;
  const refLaps = (laps.data || []).filter((l) => l.role === "reference");

  return (
    <div className="grid">
      <section className="panel">
        <h1>{c.car} @ {c.track}</h1>
        <ContextStrip slug={slug} here="cohort" />
      </section>

      <div className="tiles">
        <div className="tile"><div className="v num">{c.n_laps}</div><div className="k">Laps</div></div>
        <div className="tile"><div className="v num">{c.n_sessions}</div><div className="k">Sessions</div></div>
        <div className="tile"><div className="v num">{shownCount}</div><div className="k">Findings shown</div></div>
        <div className="tile"><div className="v num">{suppressedCount}</div><div className="k">Suppressed</div>
          <div className="s">reasons stated</div></div>
        <div className="tile"><div className="v num">{refLaps.length}</div><div className="k">Reference laps</div>
          <div className="s">context only</div></div>
      </div>

      {trace.data && (
        <section className="panel">
          <p className="eyebrow">Your racing line · amber marks highest attributed loss</p>
          <TrackMap trace={trace.data} corners={corners.data} perCornerLoss={perCornerLoss} slug={slug} />
        </section>
      )}

      <section className="panel">
        <p className="eyebrow">Coaching — what to work on next</p>
        <CoachingHeadline
          headline={p.coaching.headline} headline_reason={p.coaching.headline_reason}
          silent_count={p.coaching.silent_count} slug={slug}
        />
        {(p.coaching.secondary.length > 0 || p.coaching.self_checks.length > 0) && (
          <>
            <div style={{ height: "0.3rem" }} />
            <CoachingSecondary
              items={p.coaching.secondary} slug={slug}
              headlinePrincipleId={p.coaching.headline?.coaching_principle_id}
            />
            <CoachingSelfChecks items={p.coaching.self_checks} />
          </>
        )}
      </section>

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

      <ReferenceLaps refLaps={refLaps} />

      {p.incidents && p.incidents.n > 0 && (
        <section className="panel">
          <p className="eyebrow">Incidents — single events, not traits</p>
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
      </section>
    </div>
  );
}
