# DriverDNA — build rules

Personal racing-telemetry instrument for one driver. The authoritative
specification is **docs/SPEC.md** — read it before changing anything. Its
Philosophy section (nine principles, owner-confirmed) is binding on every design
decision; when in doubt, the philosophy wins over convenience.

## Non-negotiables

- The deterministic engine is the only source of numbers. AI (coach/chat) explains
  and prioritizes; it never invents a measurement.
- Sources are never blended: `vs-principle` / `vs-self` / `vs-reference` stay
  separate. No overall score.
- "Insufficient data" over guessing, always. Every finding carries N, spread,
  source tag, and evidence IDs.
- Reference laps never enter self history, trends, or consistency statistics.
- Secrets (`GARAGE61_TOKEN`, `ANTHROPIC_API_KEY`) are env-only: never persisted,
  printed, or logged.
- Every threshold lives in config with a documented default; all parameter changes
  flow through ConfigStore, versioned and reversible.
- Nothing is silently repaired at ingest except pedal clipping to [0,1], which is
  quality-flagged with counts.

## Build order (strict)

M0a (contract lock) → M1 (parse/segment/identify/classify) → M2
(metrics/detectors/persistence) → M3 (attribution/ranking) → M4 (reports +
one-shot coach) → M5 (interactive chat).

M0b (Garage61 API probe) floats: it requires `GARAGE61_TOKEN` and gates only the
`sync` feature — but no code may assume API behavior before M0b documents it.

Do not begin a milestone until the prior milestone's done-criteria (in the spec)
pass. Every milestone ends with tests green AND its inspectable artifact generated
from the real fixtures and reviewed.

## Current status

- **M-setup: done** (scaffold, amended spec, tooling).
- **M0a: done** — schema-lock + absence tests green on both fixtures;
  `docs/schema-report.md` generated (`driverdna schema-report`).
- **M1: done** — parser with quality flags; segmentation with nine landmarks
  (multi-apex handled); frozen corner map with build→freeze→match identity;
  speed-band classes with hysteresis; `docs/corners-report.md` generated
  (`driverdna corners`).
- **M2: in progress.**
- **M0b: blocked** — waiting on `GARAGE61_TOKEN`.
- Coach/chat live runs blocked on `ANTHROPIC_API_KEY`; all provider tests are
  mocked regardless.
- Spa blind acceptance test blocked on the owner's GR86/Spa lap set (≥ 2 sessions).

Update this section as milestones complete.

## Commands

- Install: `python3 -m pip install -e ".[dev]"`
- Test: `python3 -m pytest`
- CLI: `driverdna --help`

## Testing rules

- Provider (coach/chat) tests use the mocked provider only; tests never call live
  APIs and never require secrets.
- Determinism is tested mechanically: run the pipeline twice, byte-diff the
  normalized JSON (sorted keys, fixed float precision, no wall-clock timestamps).
- The fixture CSVs in `tests/fixtures/` are the regression anchor for the source
  contract; synthetic traces cover landmark shapes, double-apex handling, and
  detector edge cases.
- API capabilities are documented from observed behavior (docs/garage61-api.md),
  never assumed.
