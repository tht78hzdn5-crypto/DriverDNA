// The Driver Model pyramid's geometry — one definition, two sizes (A48).
//
// #/model draws it full size with a score on every tier; the cohort page and
// the corner drill draw it at 22px beside a fundamental's name with that
// fundamental's tier lit. Those are the same shape by construction rather
// than by two people keeping two sets of numbers in agreement, which is the
// drift this file exists to prevent.
//
// Layout only. A tier's position is fixed regardless of score — foundations
// at the base, higher-order skills toward the peak — so neither drawing ever
// implies a ranking, and neither carries a colour with meaning.

import { FUNDAMENTAL_ORDER } from "./order.js";

// Truncated pyramid so even the apex tier has room for a figure. Geometry in
// SVG user units against a 0 0 100 68 viewBox; tier 0 is the base (widest).
export const Y_BASE = 65, Y_TOP = 3;
const TIERS = FUNDAMENTAL_ORDER.length;
export const STEP = (Y_BASE - Y_TOP) / TIERS, GAP = 1.1;

export const edgeX = (y, side) => {
  const t = (Y_BASE - y) / (Y_BASE - Y_TOP); // 0 base → 1 peak
  const [baseL, baseR, apexL, apexR] = [4, 96, 39, 61];
  return side < 0 ? baseL + t * (apexL - baseL) : baseR + t * (apexR - baseR);
};

const points = (pairs) =>
  pairs.map((p) => p.map((n) => n.toFixed(2)).join(",")).join(" ");

// One tier's trapezoid, by index into FUNDAMENTAL_ORDER.
export function tierPoints(i) {
  const yb = Y_BASE - i * STEP, yt = Y_BASE - (i + 1) * STEP + GAP;
  return points([
    [edgeX(yb, -1), yb], [edgeX(yb, 1), yb],
    [edgeX(yt, 1), yt], [edgeX(yt, -1), yt],
  ]);
}

// The whole pyramid's outline — what makes the 22px mark still read as a
// pyramid when an individual tier is under two pixels tall.
export const SILHOUETTE = points([
  [edgeX(Y_BASE, -1), Y_BASE], [edgeX(Y_BASE, 1), Y_BASE],
  [edgeX(Y_TOP, 1), Y_TOP], [edgeX(Y_TOP, -1), Y_TOP],
]);
