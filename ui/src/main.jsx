import React from "react";
import { createRoot } from "react-dom/client";
import tokens from "../tokens.json";
import App from "./app.jsx";
import "./app.css";

// Self-hosted (UI-SPEC decision 8: "all assets, incl. fonts, bundled at
// build time; no CDN"). Only the weights app.css actually sets: 400
// (default), 500 (.th), 600 (h1/h2/.brand) for Sans; 400 for Mono. Latin
// subset only — every string in this UI is English/numeric, and the
// unsubsetted import ships ~46 cyrillic/greek/vietnamese/etc. font files
// nothing here ever renders.
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";

// tokens.json is the single visual source of truth (UI-SPEC): inject every
// token as a CSS custom property so the stylesheet derives from it.
const root = document.documentElement;
for (const [name, value] of Object.entries(tokens.color)) {
  root.style.setProperty(`--${name}`, value);
}
root.style.setProperty("--mono", tokens.font.mono);
root.style.setProperty("--sans", tokens.font.sans);

createRoot(document.getElementById("root")).render(<App />);
