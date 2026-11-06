// SPEC.md A62: magnitudeText renders the new gate_statistic kind as a
// bare formatted value — the principle's words carry the unit, so no
// unit suffix is attached. Existing kinds are pinned unchanged.
import { describe, expect, it } from "vitest";
import { lapIdShort, magnitudeText } from "./shared.jsx";

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

// BUG-053: an incident event's lap_id is null whenever the incident lap's
// laps.lap_id was never stored (44 laps on the owner corpus, e.g. the
// Charlotte Mustang cohort's 7 null-lap_id events). IncidentCard rendered
// event.lap_id.slice(0, 6) unguarded, so the whole cohort page blanked with
// a TypeError. The label falls back to the lap_pk the payload always
// carries (the same fallback the engine's own incidents report uses), and
// only a missing lap_pk as well reads as "—".
describe("lapIdShort", () => {
  it("renders the first six characters of a present lap_id", () => {
    expect(lapIdShort("01M5WSW28FPD7NFY2FAYECHBXV", 303)).toBe("01M5WS…");
  });

  it("falls back to the lap_pk when lap_id is null", () => {
    expect(lapIdShort(null, 303)).toBe("#303");
  });

  it("falls back to the lap_pk when lap_id is undefined", () => {
    expect(lapIdShort(undefined, 303)).toBe("#303");
  });

  it("reads as an em dash only when both lap_id and lap_pk are missing", () => {
    expect(lapIdShort(null, null)).toBe("—");
    expect(lapIdShort(undefined, undefined)).toBe("—");
  });
});
