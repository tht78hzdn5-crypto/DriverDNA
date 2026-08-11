import { get } from "../api.js";
import { Loading, useFetch } from "../app.jsx";

// Garage (UI-SPEC view 8, v2): the cohort index as its own destination, over
// the existing /api/cohorts — no new endpoint, no computed number. Driver
// home no longer doubles as this list.
export default function Garage() {
  const cohorts = useFetch(() => get("/api/cohorts").catch(() => []), []);
  if (!cohorts.data) return <Loading error={cohorts.error} />;

  return (
    <div className="grid">
      <section className="panel">
        <h1>Garage</h1>
      </section>
      <section className="panel">
        {cohorts.data.length === 0 ? (
          <div className="empty">
            <div className="checker" aria-hidden="true" />
            <p>Nothing in the garage yet — bring your first laps in.</p>
            <a className="btn-primary" href="#/upload">Import laps</a>
          </div>
        ) : (
          <>
            <div className="cardlist">
              {cohorts.data.map((c) => (
                <a key={c.slug} className="card" href={`#/cohort/${c.slug}`}>
                  <div className="cohort-name">{c.car} @ {c.track}</div>
                  <div className="dim" style={{ fontSize: "0.74rem", marginTop: "0.2rem" }}>
                    {c.driver}
                    <span className="num" style={{ marginLeft: "0.5em" }}>
                      {c.n_laps} lap{c.n_laps === 1 ? "" : "s"}
                    </span>
                    {c.n_reference_laps > 0 && (
                      <span className="num" style={{ marginLeft: "0.3em" }}>
                        · {c.n_reference_laps} ref
                      </span>
                    )}
                    {c.last_synced_at ? (
                      <span style={{ marginLeft: "0.5em" }}>
                        · synced {new Date(c.last_synced_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                      </span>
                    ) : (
                      <span style={{ marginLeft: "0.5em" }}>· imported</span>
                    )}
                  </div>
                </a>
              ))}
            </div>
            <div className="actions">
              <a className="btn" href="#/upload">Import laps</a>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
