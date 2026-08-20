import { useState } from "react";
import { get, streamSync } from "../api.js";
import { fmt } from "../format.js";
import { Loading, useFetch } from "../app.jsx";
import { useDriverPayload, invalidateDriverCache } from "../useDriverPayload.js";
import { LossBars, Methodology, ReadingPanel, fundamentalLabels } from "./shared.jsx";

// Driver home (UI-SPEC view 1, v2): the rollup and its gates panel. The
// cohort list moved to the Garage tab; home is purely the driver-wide view.
// A cold start (no DB yet — the only realistic failure on this local tool)
// routes to the same "import to get started" direction, not a raw CLI error.
const NO_DB = "no DB at"; // matches api.py's open_db() 404 detail exactly
const NO_TOKEN = "GARAGE61_TOKEN"; // matches Garage61Client's own RuntimeError text
const AUTH_EXPIRED = "sign-in expired"; // matches api.py's Garage61AuthError detail

function ProgressBar({ current, total }) {
  if (!total) return null;
  const pct = Math.round((current / total) * 100);
  return (
    <div className="import-progress">
      <div className="import-progress-bar">
        <i style={{ width: `${pct}%` }} />
      </div>
      <span className="import-progress-label">{current} of {total}</span>
    </div>
  );
}

function SyncPanel({ onSynced }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [syncProgress, setSyncProgress] = useState(null);
  const noToken = (error || "").includes(NO_TOKEN);
  const authExpired = (error || "").includes(AUTH_EXPIRED);

  async function runSync() {
    setBusy(true);
    setError(null);
    setResult(null);
    setSyncProgress({ message: "Discovering cohorts…", current: 0, total: 0 });
    try {
      let finalResult = null;
      await streamSync(null, (event) => {
        if (event.type === "discovering") {
          setSyncProgress((prev) => ({
            ...prev,
            message: `Found ${event.cohorts} cohort${event.cohorts === 1 ? "" : "s"}…`,
            total: event.cohorts,
          }));
        } else if (event.type === "cohort_start") {
          setSyncProgress((prev) => ({
            ...prev,
            message: `Syncing ${event.car} @ ${event.track}…`,
            current: event.index,
            total: event.total,
          }));
        } else if (event.type === "cohort_done") {
          setSyncProgress((prev) => ({
            ...prev,
            current: event.index + 1,
            total: event.total,
          }));
        } else if (event.type === "complete") {
          finalResult = event;
        } else if (event.type === "error") {
          throw new Error(event.detail);
        }
      });
      if (finalResult) {
        setResult(finalResult);
        onSynced();
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
      setSyncProgress(null);
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

      {syncProgress && (
        <div style={{ marginTop: "0.6rem" }}>
          <div className="dim" style={{ fontSize: "0.82rem", marginBottom: "0.3rem" }}>
            {syncProgress.message}
          </div>
          <ProgressBar current={syncProgress.current} total={syncProgress.total} />
        </div>
      )}

      {noToken && <div className="reason" style={{ marginTop: "0.6rem" }}>Set GARAGE61_TOKEN to sync.</div>}
      {authExpired && <div className="reason" style={{ marginTop: "0.6rem" }}>Garage61 sign-in expired. <a href="#/import">Reconnect</a></div>}
      {error && !noToken && !authExpired && <div className="error" style={{ marginTop: "0.6rem" }}>{error}</div>}

      {result && result.cohorts_skipped?.length > 0 && (
        <div className="reason" style={{ marginTop: "0.6rem" }}>
          {result.cohorts_skipped.length} older cohort
          {result.cohorts_skipped.length === 1 ? "" : "s"} not synced (limit{" "}
          {result.max_cohorts}). <a href="#/config">Change in Config</a>
          <details className="disclosure">
            <summary><span className="chev" aria-hidden="true">▸</span> Which ones</summary>
            <div className="disclosure-body">
              {result.cohorts_skipped.map((c) => (
                <div key={`${c.car}::${c.track}`}>
                  {c.car} @ {c.track}
                  {c.last_driven ? ` — last driven ${c.last_driven}` : ""}
                </div>
              ))}
            </div>
          </details>
        </div>
      )}

      {result && (
        result.results.length === 0 ? (
          <div className="dim" style={{ fontSize: "0.82rem", marginTop: "0.6rem" }}>
            No cohorts found — nothing driven yet, or the filter matched none.
          </div>
        ) : (
          <div style={{ marginTop: "0.6rem" }}>
            {result.results.map((s) => (
              <div key={`${s.car}::${s.track}`} className="finding">
                <div className="head">
                  <span className="desc">{s.car} @ {s.track}</span>
                  <span className="val num">{s.laps_new} new</span>
                </div>
                <div className="meta num">
                  {s.laps_seen} seen
                  {s.laps_skipped.length > 0 && <> · {s.laps_skipped.length} skipped</>}
                  {s.laps_pitlane > 0 && <> · {s.laps_pitlane} pit-lane start</>}
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

// A51: the panel that closes driver home's biggest gap. This page used to
// carry no coaching content at all — tiles, a loss chart, corpus readiness
// and a Sync button — because coaching was computed per (car, track) and had
// no driver-level form. Everything here is a straight render of
// payload.driver_model.reading and payload.coaching_rollup; the SPA composes
// no sentence and computes no figure of its own.
function WhereYouStandPanel({ driver }) {
  const reading = driver?.driver_model?.reading;
  const rollup = driver?.coaching_rollup;
  if (!reading && !rollup) return null;

  const labels = fundamentalLabels(driver.driver_model);
  const patterns = (rollup?.patterns || []).filter((p) => p.shown);
  const strengths = (rollup?.strengths || []).filter((s) => s.shown);
  const lede = patterns[0];
  const win = strengths[0];

  return (
    <section className="panel grid-span">
      <p className="eyebrow">Where you stand</p>
      <ReadingPanel reading={reading} labels={labels} />

      {win && (
        <div className="fgroup-lede" style={{ marginTop: "1rem" }}>
          <div className="coach-say">{win.strength_expression}</div>
          <div className="coach-tags">
            <span className="chip">{labels[win.fundamental] || win.fundamental.replace(/_/g, " ")}</span>
            <span className="chip num">
              {win.n_tracks} tracks · {win.n_instances} corners
            </span>
          </div>
        </div>
      )}

      {lede ? (
        <>
          <p className="eyebrow" style={{ marginTop: "1.2rem", marginBottom: "0.3rem" }}>
            Work on this everywhere
          </p>
          <div className="fgroup-lede">
            <div className="coach-say">{lede.coaching_expression}</div>
            <div className="coach-why">{lede.driving_principle}</div>
            {lede.drill && <div className="coach-drill"><b>Try this:</b> {lede.drill}</div>}
            <div className="coach-tags">
              <span className="chip">{labels[lede.fundamental] || lede.fundamental.replace(/_/g, " ")}</span>
              <span className="chip num">
                {lede.n_tracks} tracks · {lede.n_instances} corners
              </span>
            </div>
            <Methodology id="coaching.cross_track" label="Why does more than one track matter?" />
          </div>
        </>
      ) : (
        rollup && (
          <div className="dim" style={{ fontSize: "0.82rem", marginTop: "1rem" }}>
            No pattern yet appears at {rollup.min_tracks} or more tracks — drive
            somewhere else and the habits you carry with you separate from the
            corners you have not learned.
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

function RollupProgress({ progress }) {
  if (!progress) return null;
  return (
    <section className="panel">
      <div className="dim" style={{ fontSize: "0.82rem", marginBottom: "0.3rem" }}>
        Computing rollup — {progress.cohort || "starting…"}
      </div>
      <ProgressBar current={progress.index + 1} total={progress.total} />
    </section>
  );
}

export default function DriverHome() {
  const [reload, setReload] = useState(0);
  const summary = useFetch(() => get("/api/driver/summary"), [reload]);
  const cohorts = useFetch(() => get("/api/cohorts"), [reload]);

  const { driver, driverError, rollupProgress } = useDriverPayload();

  const coldStart = (summary.error || "").includes(NO_DB) || (cohorts.error || "").includes(NO_DB)
    || (driverError || "").includes(NO_DB);

  if (!coldStart && summary.error && !driverError) {
    return <Loading error={summary.error} />;
  }

  const hasSummary = !!summary.data;

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

  const rollups = driver ? driver.cross_track_rollups : [];
  const shown = rollups.filter((r) => r.shown);
  const gated = rollups.filter((r) => !r.shown);

  return (
    <div className="grid grid-wide">
      <section className="panel grid-span">
        <h1>Driver</h1>
      </section>

      <div className="tiles grid-span">
        <div className="tile">
          <div className="v num">{hasSummary ? summary.data.n_cohorts : "…"}</div>
          <div className="k">Cohorts</div>
        </div>
        <div className="tile">
          <div className="v num">{hasSummary ? summary.data.n_self_laps : "…"}</div>
          <div className="k">Laps</div>
        </div>
        {driver ? (
          <>
            <div className="tile"><div className="v num">{shown.length}</div><div className="k">Rollups shown</div></div>
            <div className="tile"><div className="v num">{gated.length}</div><div className="k">Gated</div>
              {gated.length > 0 && <div className="s">reasons below</div>}</div>
          </>
        ) : (
          <div className="tile"><div className="v dim">…</div><div className="k">Rollups</div></div>
        )}
      </div>

      {driver && <WhereYouStandPanel driver={driver} />}

      {!driver && !driverError && <RollupProgress progress={rollupProgress} />}
      {driverError && !coldStart && <section className="panel"><div className="error">{driverError}</div></section>}

      {driver && (
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
      )}

      {driver && <CensusPanel census={driver.census} />}

      <SyncPanel onSynced={() => { invalidateDriverCache(); setReload((n) => n + 1); }} />
    </div>
  );
}
