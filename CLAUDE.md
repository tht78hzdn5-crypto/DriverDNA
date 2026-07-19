# DriverDNA — build rules

Personal racing-telemetry instrument for one driver. The constitution (the *why*)
is **docs/ARCHITECTURE_VISION.md**: DriverDNA measures the driver, not the lap —
the persistent Driver Model is the product. The engine spec (the *how*) is
**docs/SPEC.md** — read both before changing anything. The philosophy (nine
principles, owner-confirmed, refined by A14) is binding; when in doubt, the
constitution wins over convenience.

## Non-negotiables

- The deterministic engine is the only source of numbers, **including scores**.
  AI (coach/chat) explains scores and prioritizes practice; it never produces or
  adjusts a number.
- Sources stay separately inspectable. Composite **scores are allowed but only
  deterministic, versioned, and confidence-qualified** — Score + Confidence +
  Evidence Count, always decomposable to the sources; never opaque, never
  AI-generated (A14 / ARCHITECTURE_VISION.md).
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
one-shot coach) → M5 (interactive chat) → M6 (Driver Model — deterministic,
versioned scoring; the constitution's center of gravity, additive over M1–M5).

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
- **M2: done** — 18 deterministic metrics + 5 principle detectors; SQLite
  persistence (blob laps, compact rows, migrations), newest-N retention that
  can never touch summaries, reference-role isolation enforced at the query
  surface, candidate admission surfaced; `driverdna import` pipeline;
  `docs/metrics-report.md` generated (`driverdna metrics`). Note: "reference
  import perturbs gap sections only" re-verifies fully at M3 when gap
  sections exist; at M2 the tested guarantee is reference never enters self
  history/classes.
- **M3: done** — canonical per-corner phase windows frozen with the map
  (never per-lap landmarks); outlier-screened robust baselines
  (median-of-top-3, single best labeled); phase times stored compactly at
  import (survive blob eviction); vs-self tercile ranker with within-session
  repeatability; vs-principle pattern findings; vs-reference gaps; cumulative
  loss by phase/class; confidence gates that suppress with stated reasons;
  `docs/attribution-report.md` generated (`driverdna attribution`). Trust
  gates verified in tests: stint-only variation → zero shown findings;
  reference import perturbs gap sections only.
- **M4: done** — deterministic report payload (the JSON report IS the
  payload); Markdown + self-contained HTML (inline CSS/SVG, no external
  refs, tested); driver rollup with gated cross-track aggregation; one-shot
  coach: provider interface (Claude impl, env-only key, lazy SDK import),
  versioned payload + focus history, strict local validation (unknown or
  suppressed finding IDs, unknown evidence IDs, missing hypothesis
  confidence, and numbers-with-units absent from the payload all reject),
  accepted outputs persisted. `driverdna report / coach / history`.
- **M5: done** — grounded chat: deterministic context bundle; read-only tool
  surface returning live DB values; annotations (acknowledged/intentional)
  that suppress priority framing while keeping the measurement;
  propose_config_change stages only — applying requires the driver's
  explicit `/confirm` through ConfigStore (versioned, reversible, audited);
  mechanical grounding enforcement (unknown-ID rejection, numeric claims
  validated against bundle + tool results, one regeneration then a surfaced
  error); transcripts persisted with bundle version, evidence, effects.
  ConfigStore write path complete (propose/apply/revert + config_history).
- **UI: U0 (API) + U1 (read views + render-parity crawler) + U2 (annotations
  and config panel through audited paths) done. U3 (chat view) next on the
  U-track.**
- **Constitution adopted (2026-07-19)**: `docs/ARCHITECTURE_VISION.md` — the
  Driver Model is the product; scores are deterministic/versioned/
  confidence-qualified (A14). **M6 (Driver Model) scoped and is the declared
  next engine milestone.**
- **Determinism verified mechanically**: two independent imports produce
  byte-identical Markdown/JSON/HTML reports.
- **M0b: blocked** — waiting on `GARAGE61_TOKEN`. `sync` remains unbuilt by
  design until the API probe documents real behavior.
- Coach/chat live runs blocked on `ANTHROPIC_API_KEY`; all provider tests are
  mocked regardless.
- Spa blind acceptance test blocked on the owner's GR86/Spa lap set (≥ 2 sessions).

Update this section as milestones complete.

## UI layer (docs/UI-SPEC.md)

- The UI spec (owner-adopted) governs the FastAPI + React SPA served by
  `driverdna ui`. Binding rule: the UI renders what the engine computed and
  never computes a measurement — every on-screen number must exist in the
  JSON payload or a DB read endpoint (render-parity test, kept green).
- Milestone order U0 (API) → U1 (read views) → U2 (writes) → U3 (chat) →
  U4 (packaging/tokens); per the UI spec, the build starts only after the
  engine's blind acceptance test has run (owner may amend this gate).
- Node is a build-time dependency only; the built SPA ships in the package
  static dir; API tests never require node. Localhost only; fully offline.

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
