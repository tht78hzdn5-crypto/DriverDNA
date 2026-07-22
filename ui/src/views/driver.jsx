import React from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";
import { LossBars } from "./shared.jsx";

// Driver home (UI-SPEC view 1, v2): the rollup and its gates panel. The
// cohort list moved to the Garage tab; home is purely the driver-wide view.
// A cold start (no DB yet — the only realistic failure on this local tool)
// routes to the same "import to get started" direction, not a raw CLI error.
const NO_DB = "no DB at"; // matches api.py's open_db() 404 detail exactly

export default function DriverHome() {
  const driver = useFetch(() => get("/api/driver"), []);
  const cohorts = useFetch(() => get("/api/cohorts"), []);
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
    <div className="grid">
      <section className="panel">
        <h1>Driver</h1>
      </section>

      <div className="tiles">
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

      <section className="panel">
        <div className="actions" style={{ marginTop: 0 }}>
          <a className="btn" href="#/garage">Open garage</a>
          <a className="btn" href="#/model">Driver model</a>
        </div>
      </section>
    </div>
  );
}
