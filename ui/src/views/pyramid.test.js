// Pyramid geometry: one definition, two sizes. These pin the shape so a
// refactor of the constants cannot silently distort either drawing.
import { describe, expect, it } from "vitest";
import {
  GAP,
  SILHOUETTE,
  STEP,
  Y_BASE,
  Y_TOP,
  edgeX,
  tierPoints,
} from "./pyramid.js";

describe("edgeX", () => {
  it("spans the full width at the base", () => {
    expect(edgeX(Y_BASE, -1)).toBe(4);
    expect(edgeX(Y_BASE, 1)).toBe(96);
  });

  it("narrows to the apex width at the top", () => {
    expect(edgeX(Y_TOP, -1)).toBe(39);
    expect(edgeX(Y_TOP, 1)).toBe(61);
  });

  it("interpolates linearly between base and top", () => {
    const mid = (Y_BASE + Y_TOP) / 2;
    expect(edgeX(mid, -1)).toBe((4 + 39) / 2);
    expect(edgeX(mid, 1)).toBe((96 + 61) / 2);
  });
});

describe("tierPoints", () => {
  it("returns four 2-decimal points for the base tier", () => {
    const points = tierPoints(0).split(" ");
    expect(points).toHaveLength(4);
    for (const point of points) {
      expect(point).toMatch(/^-?\d+\.\d{2},-?\d+\.\d{2}$/);
    }
  });

  it("stacks tiers upward without overlap: each tier's top clears the next gap", () => {
    // Tier i's top edge sits GAP above tier i+1's base edge.
    expect(Y_BASE - STEP + GAP).toBeLessThan(Y_BASE);
  });
});

describe("SILHOUETTE", () => {
  it("is a closed four-point outline of the whole pyramid", () => {
    expect(SILHOUETTE.split(" ")).toHaveLength(4);
    expect(SILHOUETTE).toContain("4.00,65.00");
    expect(SILHOUETTE).toContain("61.00,3.00");
  });
});

describe("constants", () => {
  it("divides the height evenly across seven tiers", () => {
    expect(STEP).toBe((Y_BASE - Y_TOP) / 7);
    expect(GAP).toBe(1.1);
  });
});
