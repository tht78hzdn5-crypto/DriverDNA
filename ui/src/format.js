// Presentation formatting only — mirrors the engine's own report formatting
// (m:ss.mmm, 3-decimal seconds). No new values are derived here.
export function lapTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds - m * 60;
  return `${m}:${s.toFixed(3).padStart(6, "0")}`;
}

export function fmt(value, digits = 3) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(digits);
}
