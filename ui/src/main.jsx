import React from "react";
import { createRoot } from "react-dom/client";
import tokens from "../tokens.json";
import App from "./app.jsx";
import "./app.css";

// Self-hosted (UI-SPEC decision 8: "all assets, incl. fonts, bundled at
// build time; no CDN"). Only the weights app.css actually sets. Latin
// subset only — every string in this UI is English/numeric.
//   Sans: 400 (default), 500 (.th/meters), 600 (titles/brand)
//   Mono: 400 (every figure)
//   Sans Condensed (v2 display face): 600/700 — structure labels only
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-sans-condensed/latin-600.css";
import "@fontsource/ibm-plex-sans-condensed/latin-700.css";

// tokens.json is the single visual source of truth (UI-SPEC): inject every
// token — colour, font, and now shape (v2) — as a CSS custom property so the
// stylesheet derives from it. Generalized from colour-only: one loop over
// every group, `--<key>` for each value.
const root = document.documentElement;
for (const group of Object.values(tokens)) {
  for (const [name, value] of Object.entries(group)) {
    root.style.setProperty(`--${name}`, value);
  }
}

// index.html's static <meta name="theme-color"> is read by the browser
// before any JS runs, so it's hardcoded there and can't be sourced from
// tokens.json at parse time (a real, documented duplication, checked
// mechanically by tests/test_ui_static.py). This re-asserts the same
// value from the single source of truth as defense in depth, so a future
// token change is at least caught here even if the static HTML drifts.
const themeColorMeta = document.querySelector('meta[name="theme-color"]');
if (themeColorMeta) themeColorMeta.setAttribute("content", tokens.color.base);

// U7 mobile/PWA (DEPLOY-SPEC Track M item 4, docs/UI-V3-PLAN.md Track A5):
// registers the runtime-caching service worker (ui/public/sw.js). Same-
// origin only, and only over a secure context — `serviceWorker` is simply
// undefined on plain HTTP, so this is a no-op on the local `driverdna ui`
// loopback path, exactly matching the existing offline/local behavior.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

createRoot(document.getElementById("root")).render(<App />);
