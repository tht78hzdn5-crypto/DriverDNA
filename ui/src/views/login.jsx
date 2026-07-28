import React, { useState } from "react";
import { send } from "../api.js";

// The sign-in gate (docs/DEPLOY-SPEC.md track H1). Rendered *instead of* the
// cockpit shell when the server says a session is required and this browser
// does not have one — so no view ever fetches, fails, and shows ten error
// panels where a login belongs.
//
// Deliberately spare, and deliberately renders no measurement: there is no
// `.num` element here, because the render-parity crawler's guarantee is that
// every on-screen number traces to the payload, and a login screen has no
// payload to trace to.
//
// The credentials are posted once and exchanged for an HttpOnly cookie. They
// are never stored in JS — no localStorage, no sessionStorage, no module
// state — so nothing on the page can read the session back out afterwards.
export default function Login({ onAuthenticated, googleEnabled }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (!email || !password || busy) return;
    setBusy(true);
    setError(null);
    try {
      await send("POST", "/api/auth/login", { email, password });
      setPassword("");
      onAuthenticated();
    } catch (e2) {
      setError(String(e2.message || e2));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="panel login-panel">
        <div className="brand" style={{ marginBottom: "0.9rem" }}>
          <svg className="mark" width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <polyline points="2,2 9,6 16,10 9,14 2,16" fill="none"
                      stroke="var(--accent)" strokeWidth="1.6" strokeLinejoin="round" />
            <polyline points="16,2 9,6 2,10 9,14 16,16" fill="none"
                      stroke="var(--dim)" strokeWidth="1.6" strokeLinejoin="round" />
          </svg>
          <span className="word">Driver<b>DNA</b></span>
        </div>
        <h1>Sign in</h1>
        <div className="sub">Sign in to your cockpit.</div>
        <form onSubmit={submit}>
          <label className="upload-field">
            <span className="upload-label">Email</span>
            <input
              className="in" style={{ width: "100%" }} type="email"
              name="email" autoComplete="username" autoFocus
              value={email} onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label className="upload-field" style={{ marginTop: "0.6rem" }}>
            <span className="upload-label">Password</span>
            <input
              className="in" style={{ width: "100%" }} type="password"
              name="password" autoComplete="current-password"
              value={password} onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="btn-primary" type="submit"
                  disabled={busy || !email || !password} style={{ marginTop: "0.8rem" }}>
            {busy ? "Checking…" : "Enter"}
          </button>
        </form>
        {googleEnabled && (
          <a className="btn" href="/api/auth/google/login" style={{ marginTop: "0.6rem", display: "block", textAlign: "center" }}>
            Sign in with Google
          </a>
        )}
        {error && <div className="error" style={{ marginTop: "0.8rem" }}>{error}</div>}
      </section>
    </div>
  );
}
