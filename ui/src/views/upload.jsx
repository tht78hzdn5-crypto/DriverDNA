import React, { useState } from "react";
import { get, uploadLaps } from "../api.js";

// Upload (UI-SPEC view 7: "Laps — Import/session listing"). A thin form over
// POST /api/laps/upload, which is itself a thin wrapper over the same
// import_lap_file the CLI calls per file (decision 3) — this view computes
// nothing, it only collects the same inputs `driverdna import` takes as
// flags and shows back exactly what the endpoint reports. Also the one true
// cold-start path: no DB needs to exist yet.
export default function Upload() {
  const [files, setFiles] = useState([]);
  const [car, setCar] = useState("");
  const [track, setTrack] = useState("");
  const [role, setRole] = useState("self");
  const [date, setDate] = useState("");
  const [session, setSession] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null); // {results, evicted}
  const [landedCohort, setLandedCohort] = useState(null); // {slug, car, track}

  async function submit(e) {
    e.preventDefault();
    if (!files.length || !car.trim() || !track.trim()) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const form = new FormData();
      for (const f of files) form.append("files", f);
      form.append("car", car.trim());
      form.append("track", track.trim());
      form.append("role", role);
      if (date.trim()) form.append("date", date.trim());
      if (session.trim()) form.append("session", session.trim());
      const r = await uploadLaps(form);
      setResult(r);
      // The slug is server-truth, never computed here (UI-SPEC decision 2) —
      // re-fetch and match by car/track to link into the cohort that landed.
      const cohorts = await get("/api/cohorts");
      const landed = cohorts.find((c) => c.car === car.trim() && c.track === track.trim());
      setLandedCohort(landed || null);
    } catch (e2) {
      setError(String(e2.message || e2));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid">
      <section className="panel">
        <h1>Import laps</h1>
        <div className="sub">
          Upload Garage61 CSV exports directly — the same import path as{" "}
          <code>driverdna import</code>, run from the browser. Nothing is computed
          here; every result below is the engine's own report of what it did.
        </div>
      </section>

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
                <span className="upload-label">Car *</span>
                <input className="in" style={{ width: "100%" }} value={car}
                       onChange={(e) => setCar(e.target.value)} placeholder="GR86" required />
              </label>
              <label className="upload-field">
                <span className="upload-label">Track *</span>
                <input className="in" style={{ width: "100%" }} value={track}
                       onChange={(e) => setTrack(e.target.value)} placeholder="Spa-Francorchamps" required />
              </label>
            </div>
            <div className="upload-row">
              <label className="upload-field">
                <span className="upload-label">Role</span>
                <select className="in" style={{ width: "100%" }} value={role}
                        onChange={(e) => setRole(e.target.value)}>
                  <option value="self">self (your driving)</option>
                  <option value="reference">reference (never enters your history/trends)</option>
                </select>
              </label>
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
            <div className="sub" style={{ marginTop: 0 }}>
              Date enables trend for these laps later, same as <code>--date</code>. Session
              groups laps for within-session repeatability, same as a manifest's <code>session</code>.
            </div>
            <div className="actions">
              <button className="btn confirm" type="submit"
                      disabled={busy || !files.length || !car.trim() || !track.trim()}>
                {busy ? "Importing…" : "Import"}
              </button>
            </div>
          </div>
        </form>
        {error && <div className="error" style={{ marginTop: "0.6rem" }}>{error}</div>}
      </section>

      {result && (
        <section className="panel">
          <p className="eyebrow">Import result</p>
          {result.results.map((r) => (
            <div key={r.filename} className={`finding ${r.status !== "imported" ? "suppressed" : ""}`}>
              <div className="head">
                <span className="desc">{r.filename}</span>
                <span className="val">{r.status}</span>
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
          {result.evicted > 0 && (
            <div className="sub">
              retention: {result.evicted} raw lap blob(s) evicted (summaries kept, never findings)
            </div>
          )}
          {landedCohort && (
            <div className="actions">
              <a className="btn confirm" href={`#/cohort/${landedCohort.slug}`}>
                View {landedCohort.car} @ {landedCohort.track} →
              </a>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
