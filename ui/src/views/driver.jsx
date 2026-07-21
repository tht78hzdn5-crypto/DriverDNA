import React from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";
import { LossBars } from "./shared.jsx";

// Driver home (UI-SPEC view 1): the rollup, and the gates panel as a
// primary state — direction, not apology.
// The only realistic reason /api/cohorts (or /api/driver) fails on this
// single-user local tool is that the DB file doesn't exist yet — a true
// cold start, before any lap has ever been imported. Route that specific
// case to the same friendly "import to get started" direction the
// zero-cohorts state already gives, rather than a raw CLI-flavored error
// string ("no DB at ... run driverdna import first") a browser-only user
// has no way to act on.
const NO_DB = "no DB at"; // matches api.py's open_db() 404 detail exactly

export default function DriverHome() {
  const driver = useFetch(() => get("/api/driver"), []);
  const cohorts = useFetch(() => get("/api/cohorts"), []);
  const coldStart = (driver.error || "").includes(NO_DB) || (cohorts.error || "").includes(NO_DB);
  if (!coldStart && (driver.error || cohorts.error)) {
    return <Loading error={driver.error || cohorts.error} />;
  }
  if (!coldStart && (!driver.data || !cohorts.data)) return <Loading error={null} />;

  const rollups = coldStart ? [] : driver.data.cross_track_rollups;
  const shown = rollups.filter((r) => r.shown);
  const cohortList = coldStart ? [] : cohorts.data;
  return (
    <div className="grid">
      <section className="panel">
        <h1>Driver</h1>
        {!coldStart && (
          <div className="sub">
            Cross-track rollups aggregate within one car and one corner class
            only, at two or more tracks. {driver.data.note}.
          </div>
        )}
      </section>

      <section className="panel">
        <p className="eyebrow">Cohorts</p>
        {cohortList.length === 0 ? (
          <div>
            <div className="dim" style={{ fontSize: "0.85rem", marginBottom: "0.6rem" }}>
              Nothing imported yet — this instrument has nothing to measure until
              real laps exist. Direction, not apology: import to get started.
            </div>
            <a className="btn confirm" href="#/upload">Import laps →</a>
          </div>
        ) : (
          <>
            <div className="cardlist">
              {cohortList.map((c) => (
                <a key={c.slug} className="card" href={`#/cohort/${c.slug}`}>
                  <div>{c.car} @ {c.track}</div>
                  <div className="dim" style={{ fontSize: "0.74rem" }}>{c.driver}</div>
                </a>
              ))}
            </div>
            <div className="sub" style={{ marginTop: "0.6rem" }}>
              <a href="#/upload">+ Import more laps</a>
            </div>
          </>
        )}
      </section>

      {!coldStart && (
        <section className="panel">
          <p className="eyebrow">Cross-track loss by car and class (s/lap)</p>
          {shown.length > 0 && (
            <LossBars entries={shown.map((r) => [`${r.car} · ${r.class}`, r.loss_s])} />
          )}
          {rollups.filter((r) => !r.shown).map((r) => (
            <div key={`${r.car}-${r.class}`} className="finding suppressed">
              <div className="head">
                <span className="desc">{r.car} · {r.class}</span>
                <span className="val num">{fmt(r.loss_s)} s</span>
              </div>
              <div className="reason">{r.gate_reason} — progress: {r.n_tracks} track{r.n_tracks === 1 ? "" : "s"}</div>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
