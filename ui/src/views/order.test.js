// The pyramid order is a contract: every surface reads this one array, so
// a reorder here silently reorders the cohort feedback, the corner drill,
// and #/model together. Pin the order and the membership.
import { describe, expect, it } from "vitest";
import { FUNDAMENTAL_ORDER } from "./order.js";

describe("FUNDAMENTAL_ORDER", () => {
  it("lists the seven fundamentals, foundations first", () => {
    expect(FUNDAMENTAL_ORDER).toEqual([
      "braking",
      "rotation",
      "corner_exit",
      "commitment",
      "consistency",
      "vehicle_management",
      "vision",
    ]);
  });

  it("has no duplicates", () => {
    expect(new Set(FUNDAMENTAL_ORDER).size).toBe(FUNDAMENTAL_ORDER.length);
  });
});
