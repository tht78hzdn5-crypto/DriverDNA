import { useState } from "react";
import { send } from "../api.js";

export default function Login({ onAuthenticated, googleEnabled, garage61Enabled }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    const authErr = params.get("auth_error");
    if (authErr) {
      window.history.replaceState({}, "", window.location.pathname + window.location.hash);
      return `Google sign-in failed: ${authErr}`;
    }
    return null;
  });

  const isRegister = mode === "register";

  async function submit(e) {
    e.preventDefault();
    if (!email || !password || busy) return;
    setBusy(true);
    setError(null);
    try {
      const endpoint = isRegister ? "/api/auth/register" : "/api/auth/login";
      await send("POST", endpoint, { email, password });
      setPassword("");
      onAuthenticated();
    } catch (e2) {
      setError(String(e2.message || e2));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  function toggleMode() {
    setMode(isRegister ? "login" : "register");
    setError(null);
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
        <h1>{isRegister ? "Create account" : "Sign in"}</h1>
        <div className="sub">{isRegister ? "Set up your cockpit." : "Sign in to your cockpit."}</div>
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
              name="password" autoComplete={isRegister ? "new-password" : "current-password"}
              value={password} onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {isRegister && password.length > 0 && password.length < 8 && (
            <div className="sub" style={{ marginTop: "0.3rem", color: "var(--warn, #e8a735)" }}>
              At least 8 characters
            </div>
          )}
          <button className="btn-primary" type="submit"
                  disabled={busy || !email || !password || (isRegister && password.length < 8)}
                  style={{ marginTop: "0.8rem" }}>
            {busy ? (isRegister ? "Creating…" : "Checking…") : (isRegister ? "Create account" : "Enter")}
          </button>
        </form>
        {googleEnabled && (
          <a className="btn" href="/api/auth/google/login" style={{ marginTop: "0.6rem", display: "block", textAlign: "center" }}>
            {isRegister ? "Sign up with Google" : "Sign in with Google"}
          </a>
        )}
        {garage61Enabled && (
          <a className="btn" href="/api/auth/garage61/login" style={{ marginTop: "0.6rem", display: "block", textAlign: "center" }}>
            Sign in with Garage61
          </a>
        )}
        {error && <div className="error" style={{ marginTop: "0.8rem" }}>{error}</div>}
        <div style={{ marginTop: "1rem", textAlign: "center" }}>
          <button type="button" onClick={toggleMode}
                  style={{ background: "none", border: "none", color: "var(--accent)", cursor: "pointer", fontSize: "0.85rem", padding: 0 }}>
            {isRegister ? "Already have an account? Sign in" : "Create an account"}
          </button>
        </div>
      </section>
    </div>
  );
}
