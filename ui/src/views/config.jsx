import { useEffect, useState } from "react";
import { get, send } from "../api.js";
import { Loading, useFetch } from "../app.jsx";

// AI provider keys (SPEC.md A37, "BYOK"): write-only in one direction — the
// key is sent once over HTTPS and never read back; GET returns only a
// fingerprint. A type="password" input, never a plain text field, and the
// key is never logged to the browser console or held in component state
// past the one PUT call. Deliberately NOT a clickable <a href> to Google's/
// Anthropic's own key pages: trust gate 5's offline test forbids any
// "https://" string in the built bundle at all (test_ui_static.py), a
// stricter and more mechanical guarantee than "the SPA makes no live
// request" — plain, unlinked attribution text respects that fully; the
// driver can type the address themselves in a separate tab.
const AI_PROVIDERS = [
  { id: "gemini", label: "Gemini", hint: "ai.google.dev/gemini-api/docs/api-key" },
  { id: "claude", label: "Claude", hint: "console.anthropic.com/settings/keys" },
];

function AiKeyRow({ providerId, label, hint }) {
  const [status, setStatus] = useState(null); // {configured, fingerprint?, set_at?}
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const refresh = () =>
    get(`/api/settings/ai-key?provider=${providerId}`).then(setStatus).catch((e) => setError(String(e.message || e)));

  useEffect(() => { refresh(); }, [providerId]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await send("PUT", "/api/settings/ai-key", { provider: providerId, key: draft });
      setDraft("");
      await refresh();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await send("DELETE", `/api/settings/ai-key?provider=${providerId}`);
      await refresh();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cfg">
      <div className="cfg-head">
        <span className="cfg-name">{label}</span>
        {status?.configured ? (
          // A fingerprint is a display hint, not a measurement -- no .num.
          <span className="cfg-val">{status.fingerprint}</span>
        ) : (
          <span className="dim cfg-val">not set — server key used, if any</span>
        )}
      </div>
      <div className="cfg-edit">
        <input
          className="in" type="password" style={{ width: "auto", flex: 1 }}
          aria-label={`${label} API key`}
          placeholder="paste your own key"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button className="btn small" disabled={busy || !draft.trim()} onClick={save}>Set</button>
        {status?.configured && (
          <button className="btn small" disabled={busy} onClick={remove}>Remove</button>
        )}
      </div>
      <div className="cfg-doc">
        Used only for your own coach/chat calls; never for anyone else's.{" "}
        Get a free key at {hint}.
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

function AiKeysPanel() {
  return (
    <section className="panel">
      <p className="eyebrow">Your own AI keys — bring-your-own-key</p>
      <div className="guarantee">
        Stored encrypted, tied to your account only. Never echoed back, never
        logged. Falls back to the server's own key (if configured) when unset.
      </div>
      {AI_PROVIDERS.map((p) => (
        <AiKeyRow key={p.id} providerId={p.id} label={p.label} hint={p.hint} />
      ))}
    </section>
  );
}

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

      <AiKeysPanel />

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
                  {/* .num means "a traceable measurement, tabular mono" —
                      only a real number qualifies. A string config value
                      (e.g. a model name) is data, not a measurement, and
                      must not wear the class the render-parity crawler
                      uses to find figures that must trace to the payload:
                      "gemini-3.5-flash" contains a decimal-shaped
                      substring and would otherwise false-positive as an
                      invented number. */}
                  <span className={typeof value === "number" ? "num cfg-val" : "cfg-val"}>
                    {String(value)}
                  </span>
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
