// SPEC.md A62: magnitudeText renders the new gate_statistic kind as a
// bare formatted value — the principle's words carry the unit, so no
// unit suffix is attached. Existing kinds are pinned unchanged.
import { describe, expect, it } from "vitest";
import { magnitudeText } from "./shared.jsx";

describe("magnitudeText", () => {
  it("renders seconds with the s suffix", () => {
    expect(magnitudeText("seconds_lost", 1.852)).toBe("1.852 s");
  });

  it("renders dispersion with the typical suffix", () => {
    expect(magnitudeText("normalized_dispersion", 1.852)).toBe("1.85× typical");
  });

  it("renders a gate statistic bare, with no unit suffix", () => {
    expect(magnitudeText("gate_statistic", 0.5)).toBe("0.500");
  });

  it("returns null for unknown kinds", () => {
    expect(magnitudeText("nope", 1)).toBeNull();
  });
});
