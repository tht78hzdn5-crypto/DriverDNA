import React, { useEffect, useRef, useState } from "react";
import { get, send, streamChat } from "../api.js";
import { Loading, useFetch } from "../app.jsx";

// Chat (UI-SPEC view 5, U3). Text never streams token-by-token — the SSE
// progress states (thinking -> consulting_tool* -> validating, decision 4)
// show what's happening, then the mechanically-validated reply arrives
// whole in one "response" event, or "error" replaces it as a distinct card,
// never retracted partial text. Evidence IDs in a reply link into the
// finding view (obs:<n> and cp.* tokens have no dedicated view yet, so they
// render as plain evidence text rather than a link to nowhere).
const ID_TOKEN =
  /(obs:\d+|(?:vs-self|vs-principle|vs-reference):[A-Za-z0-9_:.-]+|cp\.[A-Za-z_]+\.[A-Za-z_]+)/;

function linkifyEvidence(text, slug) {
  return text.split(ID_TOKEN).map((part, i) => {
    if (i % 2 === 0) return part || null;
    if (/^(vs-self|vs-principle|vs-reference):/.test(part)) {
      return (
        <a key={i} className="num" href={`#/finding/${slug}/${encodeURIComponent(part)}`}>
          {part}
        </a>
      );
    }
    return <code key={i} className="num">{part}</code>;
  });
}

const PROGRESS_LABEL = { thinking: "thinking…", validating: "validating…" };

function auditLabel(call) {
  const arg = call.args?.corner_id || call.args?.key || call.args?.finding_id;
  return arg ? `${call.tool} (${arg})` : call.tool;
}

export default function Chat({ slug }) {
  const cohorts = useFetch(() => get("/api/cohorts"), []);
  const [sessionId, setSessionId] = useState(null);
  const [turns, setTurns] = useState([]);
  const [staged, setStaged] = useState([]);
  const [progress, setProgress] = useState(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    setSessionId(null);
    setTurns([]);
    setStaged([]);
    setError(null);
    if (!slug) return;
    let alive = true;
    send("POST", "/api/chat/sessions", { cohort: slug })
      .then((r) => alive && setSessionId(r.session_id))
      .catch((e) => alive && setError(String(e.message || e)));
    return () => { alive = false; };
  }, [slug]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [turns, progress]);

  async function submit(e) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy || !sessionId) return;
    setDraft("");
    setError(null);
    setBusy(true);
    setTurns((t) => [...t, { role: "driver", text }]);
    let consulted = [];
    setProgress("thinking");
    try {
      await streamChat(sessionId, text, (event) => {
        if (event.type === "thinking") {
          setProgress("thinking");
        } else if (event.type === "consulting_tool") {
          consulted = [...consulted, event];
          setProgress(`consulting: ${auditLabel(event)}`);
        } else if (event.type === "validating") {
          setProgress("validating");
        } else if (event.type === "response") {
          setTurns((t) => [...t, {
            role: "assistant", text: event.text, consulted,
          }]);
          setStaged(event.staged || []);
        } else if (event.type === "error") {
          setTurns((t) => [...t, { role: "error", text: event.error }]);
        }
      });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setProgress(null);
      setBusy(false);
    }
  }

  async function confirmStaged(index) {
    setBusy(true);
    setError(null);
    try {
      await send("POST", `/api/chat/sessions/${sessionId}/confirm/${index}`);
      setStaged((s) => s.filter((_, i) => i !== index - 1));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (!cohorts.data) return <Loading error={cohorts.error} />;

  if (!slug) {
    return (
      <div className="grid">
        <section className="panel">
          <h1>Chat</h1>
          <div className="sub">Pick a cohort to start a grounded session.</div>
        </section>
        <section className="panel">
          <div className="cardlist">
            {cohorts.data.map((c) => (
              <a key={c.slug} className="card" href={`#/chat/${c.slug}`}>
                <div>{c.car} @ {c.track}</div>
              </a>
            ))}
          </div>
        </section>
      </div>
    );
  }

  const cohort = cohorts.data.find((c) => c.slug === slug);

  return (
    <div className="grid">
      <section className="panel">
        <p className="eyebrow">Chat</p>
        <h1>{cohort ? `${cohort.car} @ ${cohort.track}` : slug}</h1>
        <div className="sub">
          Grounded in your deterministic findings — every claim cites evidence
          or is labeled a hypothesis. "Insufficient data" is a valid answer.
        </div>
      </section>

      {error && <div className="error">{error}</div>}

      <section className="panel chat-log">
        {turns.length === 0 && !progress && (
          <div className="dim" style={{ fontSize: "0.82rem" }}>
            Ask about a finding, challenge an interpretation, or ask what to
            focus on next.
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={`chat-turn ${t.role}`}>
            {t.role === "error" ? (
              <div className="error">{t.text}</div>
            ) : (
              <>
                <div className="chat-bubble">
                  {t.role === "assistant" ? linkifyEvidence(t.text, slug) : t.text}
                </div>
                {t.consulted && t.consulted.length > 0 && (
                  <div className="chat-audit dim">
                    consulted: {t.consulted.map(auditLabel).join(", ")}
                  </div>
                )}
              </>
            )}
          </div>
        ))}
        {progress && (
          <div className="chat-turn assistant">
            <div className="chat-bubble dim chat-progress">
              {PROGRESS_LABEL[progress] || progress}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </section>

      {staged.length > 0 && (
        <section className="panel staged">
          <p className="eyebrow">Staged changes — confirm to apply</p>
          {staged.map((p, i) => (
            <div key={i} className="staged-row chat-staged-row">
              <span className="num">{p.key}</span>
              <span className="num">
                <span className="dim">{String(p.old_value)}</span>
                {" → "}
                <b>{String(p.new_value)}</b>
              </span>
              <button
                className="btn confirm small"
                disabled={busy || !sessionId}
                onClick={() => confirmStaged(i + 1)}
              >
                Confirm change #{i + 1}
              </button>
            </div>
          ))}
        </section>
      )}

      <form className="panel chat-input" onSubmit={submit}>
        <input
          className="in"
          aria-label="message"
          placeholder={sessionId ? "Ask about your data…" : "starting session…"}
          value={draft}
          disabled={!sessionId || busy}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button className="btn" type="submit" disabled={!sessionId || busy || !draft.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
