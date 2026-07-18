# Telemetry fixtures

This directory must contain the two real Garage61 exports the source contract
was verified against (docs/SPEC.md, "Source contract"):

1. **Ford Mustang @ Laguna Seca** — lap time 1:37.268
2. **Toyota GR86 @ Spa-Francorchamps** — lap time 2:51.250

Keep the filenames exactly as downloaded from Garage61 — the parser reads
driver/car/track/lap-time/lap-id metadata from the filename (best-effort).

These fixtures are the regression anchor for the entire pipeline: the M0a
schema-lock tests assert the exact header order, 60 Hz timing, single
LapDistPct wrap, unit ranges, and the known dirty-data counts on these files.
M0a cannot run until they are present.

Synthetic traces (landmark shapes, double-apex cases, detector edge cases)
are added alongside from M1 onward, in `tests/fixtures/synthetic/`.
