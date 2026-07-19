import React from "react";
import { createRoot } from "react-dom/client";
import tokens from "../tokens.json";
import App from "./app.jsx";
import "./app.css";

// tokens.json is the single visual source of truth (UI-SPEC): inject every
// token as a CSS custom property so the stylesheet derives from it.
const root = document.documentElement;
for (const [name, value] of Object.entries(tokens.color)) {
  root.style.setProperty(`--${name}`, value);
}
root.style.setProperty("--mono", tokens.font.mono);
root.style.setProperty("--sans", tokens.font.sans);

createRoot(document.getElementById("root")).render(<App />);
