import { useState } from "react";
import { get, streamUpload, streamSync } from "../api.js";

// Upload (UI-SPEC view 7: "Laps — Import/session listing"). A thin form over
// POST /api/laps/upload, which is itself a thin wrapper over the same
// import_lap_file the CLI calls per file (decision 3) — this view computes
// nothing, it only collects the same inputs `driverdna import` takes as
// flags and shows back exactly what the endpoint reports. Also the one true
// cold-start path: no DB needs to exist yet.
export default function Upload({ garage61Enabled, garage61Linked }) {
  const [files, setFiles] = useState([]);
  const [car, setCar] = useState("");
  const [track, setTrack] = useState("");
  const [role, setRole] = useState("self");
  const [date, setDate] = useState("");
  const [session, setSession] = useState("");
  const [driver, setDriver] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null); // {results, evicted}
  const [landedCohorts, setLandedCohorts] = useState([]); // [{slug, car, track}]
  const [progress, setProgress] = useState(null); // {current, total, results}

  const [syncBusy, setSyncBusy] = useState(false);
  const [syncError, setSyncError] = useState(null);
  const [syncResult, setSyncResult] = useState(null); // list[CohortSync]
  const [syncProgress, setSyncProgress] = useState(null); // {message, current, total, results}

  async function submit(e) {
    e.preventDefault();
    if (!files.length) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setLandedCohorts([]);
    setProgress({ current: 0, total: files.length, results: [] });
    try {
      const form = new FormData();
      for (const f of files) form.append("files", f);
      // Both blank => the server auto-detects per file from the newer
      // Garage61 filename shape; either given overrides for every file.
      if (car.trim()) form.append("car", car.trim());
      if (track.trim()) form.append("track", track.trim());
      form.append("role", role);
      if (date.trim()) form.append("date", date.trim());
      if (session.trim()) form.append("session", session.trim());
      if (role === "reference" && driver.trim()) form.append("driver", driver.trim());

      let finalResult = null;
      await streamUpload(form, (event) => {
        if (event.type === "progress") {
          setProgress((prev) => ({
            current: event.index + 1,
            total: event.total,
            results: [...(prev?.results || []), event.result],
          }));
        } else if (event.type === "complete") {
          finalResult = event;
        }
      });

      if (finalResult) {
        setResult({ results: finalResult.results, evicted: finalResult.evicted });
        const cohorts = await get("/api/cohorts");
        const wanted = new Set(finalResult.results.map((x) => `${x.car}::${x.track}`));
        setLandedCohorts(cohorts.filter((c) => wanted.has(`${c.car}::${c.track}`)));
      }
    } catch (e2) {
      setError(String(e2.message || e2));
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function runSync() {
    setSyncBusy(true);
    setSyncError(null);
    setSyncResult(null);
    setSyncProgress({ message: "Discovering cohorts…", current: 0, total: 0, results: [] });
    try {
      const payload = {};
      if (car.trim()) payload.car = car.trim();
      if (track.trim()) payload.track = track.trim();

      let finalResult = null;
      await streamSync(Object.keys(payload).length ? payload : null, (event) => {
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
            results: [...(prev?.results || []), event],
          }));
        } else if (event.type === "complete") {
          finalResult = event;
        } else if (event.type === "error") {
          throw new Error(event.detail);
        }
      });

      if (finalResult) {
        setSyncResult(finalResult.results);
      }
    } catch (e) {
      setSyncError(String(e.message || e));
    } finally {
      setSyncBusy(false);
      setSyncProgress(null);
    }
  }

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

  return (
    <div className="grid">
      <section className="panel">
        <h1>Import laps</h1>
        <div className="sub">Garage61 CSV exports — the same import as the CLI, from the browser.</div>
      </section>

      {(garage61Enabled || garage61Linked) && (
        <section className="panel">
          <p className="eyebrow">Garage61 Sync</p>
          {!garage61Linked ? (
            <>
              <div className="sub">Link your Garage61 account to automatically sync your latest laps.</div>
              <div className="actions" style={{ marginTop: "0.6rem" }}>
                <a className="btn confirm" href="/api/auth/garage61/login">Link Garage61 Account</a>
              </div>
            </>
          ) : (
            <>
              <div className="sub">Sync the latest laps directly from your connected Garage61 account.</div>
              <div className="actions" style={{ marginTop: "0.6rem" }}>
                <button className="btn confirm" disabled={syncBusy} onClick={runSync}>
                  {syncBusy ? "Syncing…" : "Sync from Garage61"}
                </button>
              </div>
              {syncProgress && (
                <div style={{ marginTop: "0.6rem" }}>
                  <div className="dim" style={{ fontSize: "0.82rem", marginBottom: "0.3rem" }}>
                    {syncProgress.message}
                  </div>
                  <ProgressBar current={syncProgress.current} total={syncProgress.total} />
                </div>
              )}
              {syncError && (syncError.includes("sign-in expired")
                ? <div className="reason" style={{ marginTop: "0.6rem" }}>Garage61 sign-in expired. <a className="btn small" href="/api/auth/garage61/login">Reconnect</a></div>
                : <div className="error" style={{ marginTop: "0.6rem" }}>{syncError}</div>
              )}
              {syncResult && (
                syncResult.length === 0 ? (
                  <div className="dim" style={{ fontSize: "0.82rem", marginTop: "0.6rem" }}>
                    No new laps found.
                  </div>
                ) : (
                  <div style={{ marginTop: "0.6rem" }}>
                    {syncResult.map((s) => (
                      <div key={`${s.car}::${s.track}`} className="finding">
                        <div className="head">
                          <span className="desc">{s.car} @ {s.track}</span>
                          <span className="val num">{s.laps_new} new</span>
                        </div>
                        <div className="meta num">
                          {s.laps_new} new / {s.laps_seen} seen
                        </div>
                      </div>
                    ))}
                  </div>
                )
              )}
            </>
          )}
        </section>
      )}

      <section className="panel">
        <form onSubmit={submit}>
          <div className="cfg-edit" style={{ flexDirection: "column", alignItems: "stretch", gap: "0.6rem" }}>
            <label className="upload-field">
              <span className="upload-label">CSV files</span>
              <input
                type="file" accept=".csv" multiple required
                onChange={(e) => setFiles([...e.target.files])}
              />
              {files.length > 0 && (
                <span className="dim" style={{ fontSize: "0.78rem" }}>
                  {files.length} file{files.length === 1 ? "" : "s"} selected
                </span>
              )}
            </label>
            <div className="upload-row">
              <label className="upload-field">
                <span className="upload-label">Car (optional)</span>
                <input className="in" style={{ width: "100%" }} value={car} name="car"
                       onChange={(e) => setCar(e.target.value)} placeholder="auto-detect from filename" />
              </label>
              <label className="upload-field">
                <span className="upload-label">Track (optional)</span>
                <input className="in" style={{ width: "100%" }} value={track} name="track"
                       onChange={(e) => setTrack(e.target.value)} placeholder="auto-detect from filename" />
              </label>
            </div>
            <div className="sub" style={{ marginTop: 0 }}>
              Leave both blank to auto-detect each file's car and track from its
              Garage61 export filename, so one upload can span cohorts. Fill
              either box on its own to apply that value to every file while the
              other keeps auto-detecting.
            </div>
            <div className="upload-row">
              <label className="upload-field">
                <span className="upload-label">Role</span>
                <select className="in" style={{ width: "100%" }} value={role}
                        onChange={(e) => setRole(e.target.value)}>
                  <option value="self">self (your driving)</option>
                  <option value="reference">reference (gap context)</option>
                </select>
              </label>
              {role === "reference" && (
                <label className="upload-field">
                  <span className="upload-label">Driver (optional)</span>
                  <input className="in" style={{ width: "100%" }} value={driver}
                         onChange={(e) => setDriver(e.target.value)} placeholder="e.g. teammate JD" />
                </label>
              )}
              <label className="upload-field">
                <span className="upload-label">Session (optional)</span>
                <input className="in" style={{ width: "100%" }} value={session}
                       onChange={(e) => setSession(e.target.value)} placeholder="e.g. race-1" />
              </label>
              <label className="upload-field">
                <span className="upload-label">Date (optional)</span>
                <input className="in" style={{ width: "100%" }} type="date" value={date}
                       onChange={(e) => setDate(e.target.value)} />
              </label>
            </div>
            <div className="guarantee">
              Reference laps are context only — they never enter your history, trends, or scores.
            </div>
            <div className="sub" style={{ marginTop: 0 }}>
              Date enables trend; session groups laps for repeatability.
            </div>
            <div className="actions">
              <button className="btn confirm" type="submit" disabled={busy || !files.length}>
                {progress
                  ? `Importing ${progress.current} of ${progress.total}…`
                  : "Import"}
              </button>
            </div>
            {progress && (
              <ProgressBar current={progress.current} total={progress.total} />
            )}
          </div>
        </form>
        {error && <div className="error" style={{ marginTop: "0.6rem" }}>{error}</div>}
      </section>

      {(progress?.results?.length > 0 || result) && (
        <section className="panel">
          <p className="eyebrow">Import result</p>
          {(progress?.results || result?.results || []).map((r) => (
            <div key={r.filename} className={`finding ${r.status !== "imported" ? "suppressed" : ""}`}>
              <div className="head">
                <span className="desc">{r.filename}</span>
                <span className="val">{r.status}</span>
              </div>
              <div className="meta">
                {r.car} @ {r.track}
                {r.auto_detected && <span className="src-tag" style={{ marginLeft: "0.4rem" }}>auto-detected</span>}
              </div>
              {r.status === "imported" && (
                <div className="meta num">
                  lap {r.lap_pk} · corners {r.corners_matched}/{r.corners_total} matched
                  {r.admitted.length > 0 && <> · admitted to map: {r.admitted.join(", ")}</>}
                </div>
              )}
              {r.status === "duplicate" && (
                <div className="reason">identical telemetry already imported — not double-counted</div>
              )}
              {r.status === "exists" && (
                <div className="reason">already imported (same source file) — skipped</div>
              )}
              {r.class_changes.length > 0 && (
                <div className="reason">
                  {r.class_changes.map((c) => `${c.corner_id}: ${c.old} → ${c.new}`).join("; ")}
                  {" "}— surfaced, never silent
                </div>
              )}
            </div>
          ))}
          {result?.evicted > 0 && (
            <div className="sub">
              retention: {result.evicted} raw lap blob(s) evicted (summaries kept, never findings)
            </div>
          )}
          {landedCohorts.length > 0 && (
            <div className="actions">
              {landedCohorts.map((c) => (
                <a key={c.slug} className="btn confirm" href={`#/cohort/${c.slug}`}>
                  View {c.car} @ {c.track} →
                </a>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
