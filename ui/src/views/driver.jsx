import { useState } from "react";
import { get, send } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";
import { LossBars, Methodology } from "./shared.jsx";

// Driver home (UI-SPEC view 1, v2): the rollup and its gates panel. The
// cohort list moved to the Garage tab; home is purely the driver-wide view.
// A cold start (no DB yet — the only realistic failure on this local tool)
// routes to the same "import to get started" direction, not a raw CLI error.
const NO_DB = "no DB at"; // matches api.py's open_db() 404 detail exactly
const NO_TOKEN = "GARAGE61_TOKEN"; // matches Garage61Client's own RuntimeError text

// Sync (U6): a wrapper over sync_driver, nothing computed here — every
// figure below is the endpoint's own response, replayed verbatim. The
// missing-token state is guidance, never an input field (decision: secrets
// stay env-only, never transit the browser).
function SyncPanel({ onSynced }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // list[CohortSync] verbatim
  const [error, setError] = useState(null);
  const noToken = (error || "").includes(NO_TOKEN);

  async function runSync() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await send("POST", "/api/sync");
      setResult(r);
      onSynced();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <p className="eyebrow">Sync</p>
      <div className="actions" style={{ marginTop: 0 }}>
        <button className="btn-primary" disabled={busy} onClick={runSync}>
          {busy ? "Syncing…" : "Sync"}
        </button>
        <a className="btn" href="#/garage">Open garage</a>
        <a className="btn" href="#/model">Driver model</a>
      </div>

      {noToken && <div className="reason" style={{ marginTop: "0.6rem" }}>Set GARAGE61_TOKEN to sync.</div>}
      {error && !noToken && <div className="error" style={{ marginTop: "0.6rem" }}>{error}</div>}

      {result && (
        result.length === 0 ? (
          <div className="dim" style={{ fontSize: "0.82rem", marginTop: "0.6rem" }}>
            No cohorts found — nothing driven yet, or the filter matched none.
          </div>
        ) : (
          <div style={{ marginTop: "0.6rem" }}>
            {result.map((s) => (
              <div key={`${s.car}::${s.track}`} className="finding">
                <div className="head">
                  <span className="desc">{s.car} @ {s.track}</span>
                  <span className="val num">{s.laps_new} new</span>
                </div>
                <div className="meta num">
                  {s.laps_seen} seen
                  {s.laps_skipped.length > 0 && <> · {s.laps_skipped.length} skipped</>}
                </div>
                {s.laps_skipped.map((sk) => (
                  <div key={sk.lap_id} className="reason">skipped {sk.lap_id}: {sk.reason}</div>
                ))}
                {s.results.filter((r) => r.admitted.length > 0 || r.class_changes.length > 0).map((r) => (
                  <div key={r.lap_pk} className="reason">
                    {r.admitted.length > 0 && <>admitted to map: {r.admitted.join(", ")} </>}
                    {r.class_changes.map((c) => `${c.corner_id}: ${c.old} → ${c.new}`).join("; ")}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )
      )}
    </section>
  );
}

function CensusPanel({ census }) {
  if (!census) return null;
  const { n_self_laps, n_reference_laps, confidence_ceiling_pct, next_steps, cohorts } = census;
  return (
    <section className="panel">
      <p className="eyebrow">Corpus readiness</p>
      <div className="sub" style={{ marginTop: 0, marginBottom: "0.6rem" }}>
        <span className="num">{n_self_laps}</span> self lap{n_self_laps === 1 ? "" : "s"} across{" "}
        <span>{cohorts.length}</span> cohort{cohorts.length === 1 ? "" : "s"}
        {n_reference_laps > 0 && <> · <span className="num">{n_reference_laps}</span> reference</>}
      </div>
      <div className="sub" style={{ marginBottom: "0.8rem" }}>
        Current confidence ceiling: <span className="num">{confidence_ceiling_pct.toFixed(1)}%</span>
      </div>
      {next_steps.length > 0 && (
        <>
          <p className="eyebrow" style={{ marginBottom: "0.3rem" }}>What to add next</p>
          {next_steps.map((step, i) => (
            <div key={i} className="finding" style={{ marginBottom: "0.3rem" }}>
              <div className="head">
                <span className="desc">{step.action}</span>
                <span className="val num">
                  {step.delta_points != null ? `+${step.delta_points.toFixed(2)} pts` : "—"}
                </span>
              </div>
              <div className="reason">{step.detail}</div>
            </div>
          ))}
        </>
      )}
    </section>
  );
}

export default function DriverHome() {
  const [reload, setReload] = useState(0);
  const driver = useFetch(() => get("/api/driver"), [reload]);
  const cohorts = useFetch(() => get("/api/cohorts"), [reload]);
  const coldStart = (driver.error || "").includes(NO_DB) || (cohorts.error || "").includes(NO_DB);
  if (!coldStart && (driver.error || cohorts.error)) {
    return <Loading error={driver.error || cohorts.error} />;
  }
  if (!coldStart && (!driver.data || !cohorts.data)) return <Loading error={null} />;

  if (coldStart || (cohorts.data && cohorts.data.length === 0)) {
    return (
      <div className="grid">
        <section className="panel">
          <h1>Driver</h1>
        </section>
        <section className="panel empty">
          <div className="checker" aria-hidden="true" />
          <p>No laps yet — this instrument has nothing to measure until real laps exist.</p>
          <a className="btn-primary" href="#/upload">Import laps</a>
        </section>
      </div>
    );
  }

  const rollups = driver.data.cross_track_rollups;
  const shown = rollups.filter((r) => r.shown);
  const gated = rollups.filter((r) => !r.shown);

  return (
    <div className="grid grid-wide">
      <section className="panel grid-span">
        <h1>Driver</h1>
      </section>

      <div className="tiles grid-span">
        <div className="tile"><div className="v num">{cohorts.data.length}</div><div className="k">Cohorts</div></div>
        <div className="tile"><div className="v num">{shown.length}</div><div className="k">Rollups shown</div></div>
        <div className="tile"><div className="v num">{gated.length}</div><div className="k">Gated</div>
          {gated.length > 0 && <div className="s">reasons below</div>}</div>
      </div>

      <section className="panel">
        <p className="eyebrow">Cross-track loss by car and class (s/lap)</p>
        <div className="sub" style={{ marginTop: 0, marginBottom: "0.6rem" }}>
          Aggregated within one car and one class, at two or more tracks.
        </div>
        <Methodology id="gate.confidence" label="Why are some rollups gated?" />
        {shown.length > 0
          ? <LossBars entries={shown.map((r) => [`${r.car} · ${r.class}`, r.loss_s])} />
          : <div className="dim" style={{ fontSize: "0.82rem" }}>Nothing clears the gate yet.</div>}
        {gated.map((r) => (
          <div key={`${r.car}-${r.class}`} className="finding suppressed">
            <div className="head">
              <span className="desc">{r.car} · {r.class}</span>
              <span className="val num">{fmt(r.loss_s)} s</span>
            </div>
            <div className="reason">{r.gate_reason} — {r.n_tracks} track{r.n_tracks === 1 ? "" : "s"}</div>
          </div>
        ))}
      </section>

      <CensusPanel census={driver.data.census} />

      <SyncPanel onSynced={() => setReload((n) => n + 1)} />
    </div>
  );
}
