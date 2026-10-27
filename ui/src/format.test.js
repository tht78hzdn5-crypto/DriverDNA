// Unit tests for the presentation formatters. Pure functions, no DOM.
import { describe, expect, it } from "vitest";
import { fmt, lapTime } from "./format.js";

describe("lapTime", () => {
  it("formats minutes, seconds, and milliseconds", () => {
    expect(lapTime(90.45)).toBe("1:30.450");
    expect(lapTime(61.5)).toBe("1:01.500");
  });

  it("formats a sub-minute lap", () => {
    expect(lapTime(0)).toBe("0:00.000");
    expect(lapTime(9.999)).toBe("0:09.999");
  });
});

describe("fmt", () => {
  it("renders null and undefined as an em dash", () => {
    expect(fmt(null)).toBe("—");
    expect(fmt(undefined)).toBe("—");
  });

  it("rounds to three digits by default", () => {
    expect(fmt(1.23456)).toBe("1.235");
  });

  it("honours an explicit digit count", () => {
    expect(fmt(1.26, 1)).toBe("1.3");
  });
});
