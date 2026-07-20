import React, { useEffect, useState } from "react";
import DriverHome from "./views/driver.jsx";
import Cohort from "./views/cohort.jsx";
import CornerDrill from "./views/corner.jsx";
import FindingDetail from "./views/finding.jsx";
import Laps from "./views/laps.jsx";
import Config from "./views/config.jsx";
import Chat from "./views/chat.jsx";

// Tiny hash router: #/ · #/cohort/:slug · #/corner/:slug/:cid ·
// #/finding/:slug/:fid · #/laps/:slug · #/chat[/:slug]
function parseHash() {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  return { view: parts[0] || "home", args: parts.slice(1).map(decodeURIComponent) };
}

export default function App() {
  const [route, setRoute] = useState(parseHash());
  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const { view, args } = route;
  return (
    <>
      <header className="topbar">
        <a href="#/" className="brand">DriverDNA</a>
        <nav>
          {args[0] && view !== "home" && view !== "config" && (
            <>
              {view !== "cohort" && <a href={`#/cohort/${args[0]}`}>cohort</a>}
              {view !== "laps" && <a href={`#/laps/${args[0]}`}>laps</a>}
              {view !== "chat" && <a href={`#/chat/${args[0]}`}>chat</a>}
            </>
          )}
          <a href="#/">driver</a>
          {view !== "chat" && <a href="#/chat">chat</a>}
          <a href="#/config">config</a>
        </nav>
      </header>
      {view === "home" && <DriverHome />}
      {view === "cohort" && <Cohort slug={args[0]} />}
      {view === "corner" && <CornerDrill slug={args[0]} cornerId={args[1]} />}
      {view === "finding" && <FindingDetail slug={args[0]} findingId={args[1]} />}
      {view === "laps" && <Laps slug={args[0]} />}
      {view === "config" && <Config />}
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

export function Loading({ error }) {
  return error
    ? <div className="error">{error}</div>
    : <div className="dim" style={{ fontSize: "0.8rem" }}>loading…</div>;
}
