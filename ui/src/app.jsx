import React, { useEffect, useState } from "react";
import DriverHome from "./views/driver.jsx";
import Garage from "./views/garage.jsx";
import Cohort from "./views/cohort.jsx";
import CornerDrill from "./views/corner.jsx";
import FindingDetail from "./views/finding.jsx";
import Laps from "./views/laps.jsx";
import Config from "./views/config.jsx";
import Chat from "./views/chat.jsx";
import DriverModel from "./views/model.jsx";
import Upload from "./views/upload.jsx";
import Login from "./views/login.jsx";
import { get, send } from "./api.js";

// Tiny hash router: #/ · #/garage · #/cohort/:slug · #/corner/:slug/:cid ·
// #/finding/:slug/:fid · #/laps/:slug · #/model · #/chat[/:slug] · #/upload
function parseHash() {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  return { view: parts[0] || "home", args: parts.slice(1).map(decodeURIComponent) };
}

// v2 shell: a constant six-tab bar that never changes shape with context.
// Entity views (cohort/corner/finding/laps) live "in the garage", so Garage
// stays lit for them; their own scoped nav is a context strip in the view.
const TABS = [
  { id: "home", label: "Driver", href: "#/" },
  { id: "model", label: "Model", href: "#/model" },
  { id: "garage", label: "Garage", href: "#/garage" },
  { id: "chat", label: "Chat", href: "#/chat" },
  { id: "upload", label: "Import", href: "#/upload" },
  { id: "config", label: "Config", href: "#/config" },
];
const TAB_FOR = { cohort: "garage", corner: "garage", finding: "garage", laps: "garage" };

export default function App() {
  const [route, setRoute] = useState(parseHash());
  // null while unknown; then {required, authenticated} straight from the
  // server. Asked once before anything renders, so a locked cockpit shows a
  // sign-in rather than every panel failing its own fetch in turn.
  const [session, setSession] = useState(null);
  // U7 mobile/PWA (DEPLOY-SPEC Track M item 4): the service worker's
  // binding rule is "cache the shell, never the numbers" — it never
  // serves /api/* from cache, so going offline means every data fetch
  // simply fails. This banner states that plainly instead of letting the
  // driver stare at whatever numbers happened to be on screen already,
  // wondering if they're current. It never shows the last numbers seen.
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine
  );
  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const checkSession = () =>
    get("/api/auth/status")
      .then(setSession)
      // If even the status probe fails, the server is unreachable rather than
      // locked — fall through to the shell so the view's own error shows.
      .catch(() => setSession({ required: false, authenticated: true }));

  useEffect(() => {
    checkSession();
    // Any 401 anywhere (an expired cookie mid-session, a rotated passphrase)
    // returns the whole shell to the gate instead of stranding one panel.
    const onLost = () =>
      setSession((s) => ({ ...s, required: true, authenticated: false }));
    window.addEventListener("driverdna:unauthenticated", onLost);
    return () => window.removeEventListener("driverdna:unauthenticated", onLost);
  }, []);

  async function signOut() {
    await send("POST", "/api/auth/logout").catch(() => {});
    setSession({ required: true, authenticated: false });
  }

  const { view, args } = route;
  const activeTab = TAB_FOR[view] || view;

  if (session === null) return <Loading />;
  if (session.required && !session.authenticated) {
    return <Login onAuthenticated={checkSession} googleEnabled={session.google_enabled} garage61Enabled={session.garage61_enabled} />;
  }

  return (
    <>
      {!online && (
        <div className="offline-banner" role="status">
          Not connected — no current data.
        </div>
      )}
      <header className="topbar">
        <a href="#/" className="brand" aria-label="DriverDNA home">
          {/* Helix half-twist that reads equally as two racing lines through a
              chicane — drawn once, no image assets. */}
          <svg className="mark" width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <polyline points="2,2 9,6 16,10 9,14 2,16" fill="none"
                      stroke="var(--accent)" strokeWidth="1.6" strokeLinejoin="round" />
            <polyline points="16,2 9,6 2,10 9,14 16,16" fill="none"
                      stroke="var(--dim)" strokeWidth="1.6" strokeLinejoin="round" />
          </svg>
          <span className="word">Driver<b>DNA</b></span>
        </a>
        <nav>
          {TABS.map((t) => (
            <a key={t.id} href={t.href}
               className={`tab ${activeTab === t.id ? "active" : ""}`}>
              {t.label}
            </a>
          ))}
          {/* Only when there is a session to end — the local loopback
              instrument has no sign-in and needs no sign-out. */}
          {session.required && (
            <button className="btn small" onClick={signOut}>Sign out</button>
          )}
        </nav>
      </header>
      {view === "home" && <DriverHome />}
      {view === "garage" && <Garage />}
      {view === "cohort" && <Cohort slug={args[0]} />}
      {view === "corner" && <CornerDrill slug={args[0]} cornerId={args[1]} />}
      {view === "finding" && <FindingDetail slug={args[0]} findingId={args[1]} />}
      {view === "laps" && <Laps slug={args[0]} />}
      {view === "config" && <Config />}
      {view === "model" && <DriverModel />}
      {view === "upload" && <Upload />}
      {view === "chat" && <Chat slug={args[0]} />}
    </>
  );
}

export function useFetch(makeRequest, deps) {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    let alive = true;
    setState({ data: null, error: null });
    makeRequest()
      .then((data) => alive && setState({ data, error: null }))
      .catch((error) => alive && setState({ data: null, error: String(error.message || error) }));
    return () => { alive = false; };
  }, deps);
  return state;
}

// Cohort-scoped nav, rendered under a view's title (never in the global tabs).
export function ContextStrip({ slug, here, children }) {
  const links = [
    { id: "cohort", label: "Overview", href: `#/cohort/${slug}` },
    { id: "laps", label: "Laps", href: `#/laps/${slug}` },
    { id: "chat", label: "Chat", href: `#/chat/${slug}` },
  ];
  return (
    <div className="context">
      {links.map((l) => (
        l.id === here
          ? <span key={l.id} className="crumb"><b>{l.label}</b></span>
          : <a key={l.id} href={l.href}>{l.label}</a>
      ))}
      {children && <><span className="spacer" />{children}</>}
    </div>
  );
}

export function Loading({ error }) {
  return error
    ? <div className="error">{error}</div>
    : <div className="dim" style={{ fontSize: "0.8rem" }}>loading…</div>;
}
