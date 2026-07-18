# DriverDNA

A personal racing-telemetry instrument. It ingests Garage61 lap exports (iRacing),
segments corners, measures technique deterministically, attributes time lost per
corner phase, and reports transferable findings denominated in cumulative seconds —
sharpening as laps accumulate. An AI coaching layer (one-shot plan + grounded chat)
explains and prioritizes the deterministic findings; it never invents a measurement.

Optimize the driver, not the lap.

- **Authoritative spec:** [`docs/SPEC.md`](docs/SPEC.md) — product intent, philosophy,
  verified source contract, milestones, and acceptance gates.
- **Build rules for agents:** [`CLAUDE.md`](CLAUDE.md).
- **Status:** scaffold complete (M-setup). M0a (contract lock) is next and requires
  the two fixture telemetry CSVs in `tests/fixtures/`.

Personal instrument, not a product: local CLI, SQLite, static self-contained reports.
No server, no blended scores, no guessing — "insufficient data" is a valid answer.
