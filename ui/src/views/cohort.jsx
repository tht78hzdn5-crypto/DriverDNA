import { useState } from "react";
import { get, send } from "../api.js";
import { fmt, lapTime } from "../format.js";
import { ContextStrip, Loading, useFetch } from "../app.jsx";
import {
  CoachingHeadline, CoachingSelfChecks, FundamentalSections, IncidentCard,
  IncidentMechanismCounts, LossBars, Methodology, SourceLegend,
  fundamentalLabels,
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

// Reference laps (v2, extended R2/R3 — SPEC.md A39): context made visible
// AND managed. Isolation stated once; the "who" named; the envelope stated
// (n/median/best, not just a pooled number, G2); a bad import can be
// excluded without deleting it (G4) — reversible, audited, same shape as
// the finding-annotations pattern. Zero references (ever imported) is a
// designed direction state, not a blank; zero ACTIVE references (all
// excluded) is a different, honestly stated state, not the same empty one.
function ReferenceLaps({ refs, onChanged }) {
  const [busy, setBusy] = useState(null); // lap_pk currently in flight
  const [error, setError] = useState(null);

  async function toggle(lap) {
    setBusy(lap.lap_pk);
    setError(null);
    try {
      if (lap.excluded) {
        await send("DELETE", `/api/laps/${lap.lap_pk}/exclude`);
      } else {
        await send("POST", `/api/laps/${lap.lap_pk}/exclude`);
      }
      onChanged();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel">
      <p className="eyebrow">Reference laps</p>
      <div className="guarantee">Context only — never enters your history, trends, or scores.</div>
      {refs.contributors.length === 0 ? (
        <div className="empty">
          <div className="ref-empty">No reference laps yet — add a faster driver's lap for gap context.</div>
          <a className="btn-primary" href="#/upload">Import a reference lap</a>
        </div>
      ) : (
        <>
          {refs.envelope ? (
            <div className="sub num" style={{ marginTop: 0 }}>
              envelope: n={refs.envelope.n} · median {lapTime(refs.envelope.median_s)} ·
              {" "}best {lapTime(refs.envelope.best_s)}
            </div>
          ) : (
            <div className="reason">
              {refs.n_excluded} reference lap{refs.n_excluded === 1 ? "" : "s"} on record, all
              currently excluded — no envelope until one is re-included.
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", marginTop: "0.5rem" }}>
            {refs.contributors.map((l) => (
              <div key={l.lap_pk} className="ref-line" style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginTop: 0 }}>
                <span className={l.excluded ? "dim" : ""}>
                  {l.driver && <b>{l.driver}</b>}{" "}
                  <span className="num">{lapTime(l.duration_s)}</span>
                  {l.excluded && <span className="chip" style={{ marginLeft: "0.4rem" }}>excluded</span>}
                </span>
                <button
                  className="btn small" disabled={busy === l.lap_pk}
                  onClick={() => toggle(l)}
                  title={l.excluded ? "Re-include in the envelope" : "Exclude from the envelope"}
                >
                  {busy === l.lap_pk ? "…" : l.excluded ? "Include" : "Exclude"}
                </button>
              </div>
            ))}
          </div>
          {error && <div className="error" style={{ marginTop: "0.5rem" }}>{error}</div>}
        </>
      )}
    </section>
  );
}

// Rebuild map (U6): rewrites frozen geometry, so it sits behind its own
// explicit confirm (decision 5) — same non-default-action discipline as the
// config panel's staged card, one click to stage the intent, a distinct
// second click (`btn confirm`) to actually act.
function RebuildMapReport({ phase, result, error, onConfirm, onCancel, busy }) {
  if (phase === "idle") return null;
  return (
    <>
      {phase === "confirm" && (
        <section className="panel staged grid-span">
          <p className="eyebrow">Rebuild map — confirm to proceed</p>
          <div className="sub" style={{ marginTop: 0 }}>
            Re-derives every corner's centroid and canonical window from this
            cohort's full lap set. Corner IDs never change — evidence stays valid.
          </div>
          <div className="actions">
            <button className="btn confirm" disabled={busy} onClick={onConfirm}>
              {busy ? "Rebuilding…" : "Confirm rebuild"}
            </button>
            <button className="btn" disabled={busy} onClick={onCancel}>Cancel</button>
          </div>
        </section>
      )}

      {error && <div className="error grid-span">{error}</div>}

      {phase === "done" && result && (
        <section className="panel grid-span">
          <p className="eyebrow">Rebuild report — {result.car} @ {result.track}</p>
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>corner</th><th className="right">shift</th><th>window</th>
                  <th className="right">re-measured</th><th className="right">cleared</th>
                </tr>
              </thead>
              <tbody>
                {result.corners.map((c) => (
                  <tr key={c.corner_id}>
                    <td>{c.corner_id}</td>
                    <td className="right num">
                      {c.centroid_shift_m === null ? "GPS-degraded" : `${fmt(c.centroid_shift_m, 1)} m`}
                    </td>
                    <td className="dim">{c.window_changed ? "shifted" : "unchanged"}</td>
                    <td className="right num">{c.laps_remeasured}</td>
                    <td className="right num">{c.laps_cleared.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.admitted.length > 0 && (
            <div className="sub">admitted new corners: {result.admitted.join(", ")}</div>
          )}
          {result.class_changes.length > 0 && (
            <div className="reason">
              {result.class_changes.map((c) => `${c.corner_id}: ${c.old} → ${c.new}`).join("; ")}
              {" "}— surfaced, never silent
            </div>
          )}
          {result.total_cleared > 0 && (
            <div className="reason" style={{ marginTop: "0.4rem" }}>
              {result.total_cleared} phase-time record(s) cleared — their raw blobs were
              evicted past retention and can't be re-measured against the new windows.
              Lap identity, metrics, and detectors are unchanged.
            </div>
          )}
        </section>
      )}
    </>
  );
}

export default function Cohort({ slug }) {
  const [reload, setReload] = useState(0);
  const payload = useFetch(() => get(`/api/cohorts/${slug}/payload`), [slug, reload]);
  const corners = useFetch(() => get(`/api/cohorts/${slug}/corners`), [slug, reload]);
  const trace = useFetch(() => get(`/api/cohorts/${slug}/track-trace`).catch(() => null), [slug]);

  const [rebuild, setRebuild] = useState({ phase: "idle", result: null, error: null, busy: false });

  async function confirmRebuild() {
    setRebuild((s) => ({ ...s, busy: true, error: null }));
    try {
      const result = await send("POST", `/api/cohorts/${slug}/rebuild-map`);
      setRebuild({ phase: "done", result, error: null, busy: false });
      setReload((n) => n + 1); // corner geometry/classes/loss may have moved
    } catch (e) {
      setRebuild((s) => ({ ...s, busy: false, error: String(e.message || e) }));
    }
  }

  if (!payload.data || !corners.data) return <Loading error={payload.error || corners.error} />;

  const p = payload.data;
  const c = p.cohort;
  const perCornerLoss = p.cumulative_loss.per_corner_total || {};
  const shownCount = p.findings.filter((f) => f.shown && !f.annotation).length;
  const suppressedCount = p.findings.filter((f) => !f.shown).length;
  const labels = fundamentalLabels(p.driver_model);

  return (
    <div className="grid grid-wide">
      <section className="panel grid-span">
        <h1>{c.car} @ {c.track}</h1>
        <ContextStrip slug={slug} here="cohort">
          <button
            className="btn small" disabled={rebuild.busy}
            onClick={() => setRebuild((s) => ({ ...s, phase: "confirm" }))}
          >
            Rebuild map
          </button>
        </ContextStrip>
      </section>

      <RebuildMapReport
        phase={rebuild.phase} result={rebuild.result} error={rebuild.error} busy={rebuild.busy}
        onConfirm={confirmRebuild}
        onCancel={() => setRebuild({ phase: "idle", result: null, error: null, busy: false })}
      />

      <div className="tiles grid-span">
        <div className="tile"><div className="v num">{c.n_laps}</div><div className="k">Laps</div></div>
        <div className="tile">
          <div className="v num">{c.n_sessions || "—"}</div>
          <div className="k">Sessions</div>
          {c.n_sessions === 0 && <div className="s">manual import — no session data</div>}
        </div>
        <div className="tile"><div className="v num">{shownCount}</div><div className="k">Findings shown</div></div>
        <div className="tile"><div className="v num">{suppressedCount}</div><div className="k">Suppressed</div>
          <div className="s">reasons stated</div></div>
        <div className="tile"><div className="v num">{p.references.n}</div><div className="k">Reference laps</div>
          <div className="s">
            context only{p.references.n_excluded > 0 ? ` · ${p.references.n_excluded} excluded` : ""}
          </div>
        </div>
      </div>

      {trace.data && (
        <section className="panel">
          <p className="eyebrow">Your racing line · amber marks highest attributed loss</p>
          <TrackMap trace={trace.data} corners={corners.data} perCornerLoss={perCornerLoss} slug={slug} />
        </section>
      )}

      <section className="panel">
        <p className="eyebrow">Work on this next</p>
        <CoachingHeadline
          headline={p.coaching.headline} headline_reason={p.coaching.headline_reason}
          silent_count={p.coaching.silent_count} slug={slug}
        />
      </section>

      <section className="panel grid-span">
        <p className="eyebrow">Typical loss vs robust baseline (s/lap)</p>
        <Methodology id="loss.cumulative" />
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

      {/* A46: one feedback section, organised by racing fundamental. The
          coaching expression and the findings that triggered it sit
          together instead of restating each other in two voices. */}
      <section className="panel grid-span">
        <p className="eyebrow">By fundamental</p>
        <SourceLegend />
        <FundamentalSections
          findings={p.findings} slug={slug} labels={labels}
          coaching={p.coaching}
        />
      </section>

      {p.coaching.self_checks.length > 0 && (
        <section className="panel grid-span">
          <p className="eyebrow">No signal — run these yourself</p>
          <CoachingSelfChecks items={p.coaching.self_checks} labels={labels} />
        </section>
      )}

      <div className="grid-span">
        <ReferenceLaps refs={p.references} onChanged={() => setReload((n) => n + 1)} />
      </div>

      {p.incidents && p.incidents.n > 0 && (
        <section className="panel grid-span">
          <p className="eyebrow">Incidents — single events, not traits</p>
          <IncidentMechanismCounts events={p.incidents.events} />
          {p.incidents.events.map((e) => (
            <IncidentCard key={e.incident_id} event={e} slug={slug} />
          ))}
        </section>
      )}

      <section className="panel grid-span">
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

      <section className="panel grid-span">
        <p className="eyebrow">Lap board</p>
        {c.lap_durations_s.map((duration, i) => {
          const hasIncident = p.incidents && c.lap_ids &&
            p.incidents.events.some((e) => e.lap_id === c.lap_ids[i]);
          return (
            <div key={i} className="lap-row">
              <span className="lap-idx num">{i + 1}</span>
              <span className={`lap-time num ${c.lap_delta_s[i] === 0 ? "lap-best" : ""}`}>{lapTime(duration)}</span>
              {hasIncident && <span className="chip incident">incident</span>}
              <span className="lap-delta num">{c.lap_delta_s[i] === 0 ? "best" : `+${fmt(c.lap_delta_s[i])}`}</span>
            </div>
          );
        })}
      </section>
    </div>
  );
}
