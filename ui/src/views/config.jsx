import React, { useState } from "react";
import { get, send } from "../api.js";
import { Loading, useFetch } from "../app.jsx";

// Config panel (UI-SPEC view 6): every threshold with its documentation,
// edited through propose → confirm → apply (ConfigStore), with config_history
// as the audit view and revert. Confirm is a distinct, explicit action; a
// staged proposal renders as an amber-ruled card until confirmed or discarded.
export default function Config() {
  const [reload, setReload] = useState(0);
  const [staged, setStaged] = useState(null); // {key, old_value, new_value, description}
  const [drafts, setDrafts] = useState({}); // key -> input string
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const config = useFetch(() => get("/api/config"), [reload]);
  const history = useFetch(() => get("/api/config/history"), [reload]);
  if (!config.data || !history.data) return <Loading error={config.error || history.error} />;

  const refresh = () => setReload((n) => n + 1);

  function coerce(key, raw) {
    const current = config.data[key].value;
    if (typeof current === "boolean") return raw === "true" || raw === true;
    if (typeof current === "number") {
      const n = Number(raw);
      return Number.isNaN(n) ? raw : n;
    }
    return raw;
  }

  async function propose(key) {
    setError(null);
    setBusy(true);
    try {
      const new_value = coerce(key, drafts[key]);
      const p = await send("POST", "/api/config/propose", { key, new_value });
      setStaged({ ...p, description: p.description || config.data[key].description });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    try {
      await send("POST", "/api/config/apply", { proposal: staged });
      setStaged(null);
      setDrafts({});
      refresh();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function revert(changePk) {
    setBusy(true);
    setError(null);
    try {
      await send("POST", `/api/config/revert/${changePk}`);
      refresh();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  const sections = {};
  for (const key of Object.keys(config.data)) {
    const [section] = key.split(".");
    (sections[section] ||= []).push(key);
  }

  return (
    <div className="grid">
      <section className="panel">
        <h1>Configuration</h1>
        <div className="sub">Every threshold with its default. Changes are versioned and reversible.</div>
      </section>

      {staged && (
        <section className="panel staged">
          <p className="eyebrow">Staged change — confirm to apply</p>
          <div className="staged-row">
            <span className="num">{staged.key}</span>
            <span className="num">
              <span className="dim">{String(staged.old_value)}</span>
              {" → "}
              <b>{String(staged.new_value)}</b>
            </span>
          </div>
          {staged.description && <div className="sub">{staged.description}</div>}
          <div className="actions">
            <button className="btn confirm" disabled={busy} onClick={confirm}>
              Confirm change
            </button>
            <button className="btn" disabled={busy} onClick={() => setStaged(null)}>
              Discard
            </button>
          </div>
        </section>
      )}

      {error && <div className="error">{error}</div>}

      {Object.keys(sections).sort().map((section) => (
        <section className="panel" key={section}>
          <p className="eyebrow">{section}</p>
          {sections[section].map((key) => {
            const { value, description } = config.data[key];
            const field = key.slice(section.length + 1);
            return (
              <div className="cfg" key={key}>
                <div className="cfg-head">
                  <span className="cfg-name">{field}</span>
                  <span className="num cfg-val">{String(value)}</span>
                </div>
                {description && <div className="cfg-doc">{description}</div>}
                <div className="cfg-edit">
                  <input
                    className="in"
                    aria-label={`new value for ${key}`}
                    value={drafts[key] ?? ""}
                    placeholder={String(value)}
                    onChange={(e) => setDrafts({ ...drafts, [key]: e.target.value })}
                  />
                  <button
                    className="btn"
                    disabled={busy || (drafts[key] ?? "") === ""}
                    onClick={() => propose(key)}
                  >
                    Propose
                  </button>
                </div>
              </div>
            );
          })}
        </section>
      ))}

      <section className="panel">
        <p className="eyebrow">Change history — auditable, reversible</p>
        {history.data.length === 0 ? (
          <div className="dim" style={{ fontSize: "0.82rem" }}>No changes yet.</div>
        ) : (
          <div className="scroll-x">
            <table>
              <thead><tr><th>#</th><th>key</th><th>change</th><th>by</th><th></th></tr></thead>
              <tbody>
                {history.data.map((h) => (
                  <tr key={h.change_pk}>
                    <td className="num dim">{h.change_pk}</td>
                    <td className="num">{h.key}</td>
                    <td className="num">
                      <span className="dim">{h.old_value}</span> → {h.new_value}
                    </td>
                    <td className="dim">{h.source}</td>
                    <td>
                      <button className="btn small" disabled={busy} onClick={() => revert(h.change_pk)}>
                        revert
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
