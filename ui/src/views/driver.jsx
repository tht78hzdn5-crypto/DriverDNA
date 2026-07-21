import React from "react";
import { get } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";
import { LossBars } from "./shared.jsx";

// Driver home (UI-SPEC view 1): the rollup, and the gates panel as a
// primary state — direction, not apology.
export default function DriverHome() {
  const driver = useFetch(() => get("/api/driver"), []);
  const cohorts = useFetch(() => get("/api/cohorts"), []);
  if (!driver.data || !cohorts.data) return <Loading error={driver.error || cohorts.error} />;

  const rollups = driver.data.cross_track_rollups;
  const shown = rollups.filter((r) => r.shown);
  return (
    <div className="grid">
      <section className="panel">
        <h1>Driver</h1>
        <div className="sub">
          Cross-track rollups aggregate within one car and one corner class
          only, at two or more tracks. {driver.data.note}.
        </div>
      </section>

      <section className="panel">
        <p className="eyebrow">Cohorts</p>
        <div className="cardlist">
          {cohorts.data.map((c) => (
            <a key={c.slug} className="card" href={`#/cohort/${c.slug}`}>
              <div>{c.car} @ {c.track}</div>
              <div className="dim" style={{ fontSize: "0.74rem" }}>{c.driver}</div>
            </a>
          ))}
        </div>
      </section>

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
    </div>
  );
}
