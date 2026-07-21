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

## Decision discipline (standing rule)

When a decision is made — especially one Claude Code surfaced as a fork (scoring
approach, M7 adoption, a threshold default) — the pick **and its reason** are
recorded in the durable docs at decision time, never left only in chat:

- The resolution goes in `docs/SPEC.md` (amendment log) and/or
  `docs/PROJECT-BRIEF.md` (Decision log), dated.
- If the decision touches the **nine philosophy points** or the **out-of-scope
  list**, the record must *name the principle or item it refines and why*, in
  the same edit — flagged at decision time, not left to be caught later. A14
  (scores refine philosophy #4) is the model.
- `docs/STATUS.md` is the single dated snapshot; verified counts (tests, laps,
  sessions, findings, commits) live there so they can be checked over time.

## Build order (strict)

M0a (contract lock) → M1 (parse/segment/identify/classify) → M2
(metrics/detectors/persistence) → M3 (attribution/ranking) → M4 (reports +
one-shot coach) → M5 (interactive chat) → M6 (Driver Model — deterministic,
versioned scoring; the constitution's center of gravity, additive over M1–M5)
→ M7 (Coaching Intelligence — grounded coaching ontology; docs/COACHING.md,
design stage).

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
  and config panel through audited paths) + U3 (chat view) + U4
  (packaging/tokens) done — the full UI-SPEC.md milestone track is built.**
  U4 (2026-07-21): static HTML reports migrated onto `ui/tokens.json`'s dark
  theme (`report/builder.py`'s `_TOKENS` mirrors it; a test asserts they
  match byte-for-byte); IBM Plex self-hosted in the SPA (latin subset only,
  8 files/176KB — SPA only, reports keep the system-font fallback); a real
  Playwright test for trust gate 5 (route-level blocking of all
  non-localhost requests across every route, not just a static grep).
  U3: `ChatSession.ask_stream`
  (generator; `ask()` is a thin wrapper over it) drives three new endpoints
  (`POST /api/chat/sessions`, `.../messages` via SSE, `.../confirm/{n}`) and
  `ui/src/views/chat.jsx`. SSE progress (thinking → consulting_tool* →
  validating), tool-call audit, and staged/confirm all browser-verified
  against a mocked provider; text never streams, a rejected reply is a
  distinct error card. Fixed a real cross-thread sqlite3 bug found while
  testing (`Database.open(..., check_same_thread=False)` for the one
  long-lived chat-session connection).
- **Constitution adopted (2026-07-19)**: `docs/ARCHITECTURE_VISION.md` — the
  Driver Model is the product; scores are deterministic/versioned/
  confidence-qualified (A14).
- **M6 (Driver Model): built (2026-07-20)** — taxonomy (7 fundamentals, 17
  techniques, measured/proxy/no_signal), `driver_beliefs` store, the `dm-v1`
  scoring model (adherence/opportunity/consistency, weight-redistributed,
  proxy-capped confidence), `driverdna model` artifact, and beliefs wired
  into the report/coach/chat payload (`driver_model` section — cited through
  the existing numeric-grounding validator, no new validator code).
  Flagged, not silently accepted: `consistency`'s CV pools raw metric scale
  across a driver's different cars/tracks with no per-cohort normalization —
  see SPEC.md's M6 section, "Known v1 limitation."
- **M6 trend: built (2026-07-20)** — `trend` is the direction of a
  fundamental's own score between an earlier and a recent bucket of the
  driver's dated laps. Same scoring function per bucket via an additive lap-pk
  evidence filter; deterministic (ordered by lap_date, lap_pk); banded by
  `config.model.trend_delta_points`. `scoring_model_version` stays `dm-v1`
  (score/confidence unchanged for every evidence set; the field was always
  specified). Two flagged limitations (era-relative opportunity baseline;
  cross-cohort bucket composition when dated laps are thin-per-cohort) — see
  SPEC.md M6 "Trend". First live run on the owner's 25-lap synced history:
  braking/rotation `improving`, corner_exit/commitment `stable`,
  consistency/vehicle_management honestly `unavailable`.
- **Dated manual import: built (2026-07-21)** — `driverdna import --date
  YYYY-MM-DD|<ISO8601>` sets `lap_date` on every imported file the same way
  `sync` does from the API's `startTime`; a manifest entry's own `date`
  field overrides the flag for that entry, so a mixed-date directory can be
  imported in one pass. Malformed dates are rejected loudly (exit 2, nothing
  imported) — never silently accepted, since trend sorts on this string.
  Exists because the Garage61 API caps `/laps` at ~1 saved lap per driver
  per cohort (`docs/garage61-api.md`), so a real per-cohort trend needs the
  driver's own exported history, not `sync` alone. Verified end-to-end
  against the real fixture CSVs (not just synthetic tests): dating the
  11-lap Spa cohort by session produced a real `declining` trend on
  `consistency` from `driverdna model`, byte-identical across two runs; the
  committed fixture manifest itself stays undated (comment-only change) so
  `docs/driver-model-report.md` is untouched.
- **Coaching Intelligence (M7): design adopted, then built (2026-07-20)**:
  `docs/COACHING.md` — grounded coaching ontology (technique → driving
  principle → coaching principle), nine seed `CoachingPrinciple`s
  (`coaching/ontology.py`), a deterministic eligibility/ranking/gap-band
  engine (`coaching/engine.py`) reading M2/M3 rows through M6's own taxonomy,
  `driverdna coaching` artifact, and a `coaching` payload section wired into
  report/coach/chat (coach schema `coach-v1`→`coach-v2`, chat bundle
  `chat-v1`→`chat-v2`, `PAYLOAD_VERSION` 2→3). Binding rule enforced
  mechanically now, not just documented: a confidence value never launders an
  unmeasured inference — a `no_signal` principle carrying any
  confidence/percentage language is rejected by the grounding validator, same
  machinery as an unknown evidence ID; no-signal principles get a
  driver-runnable self-check, never a score or confidence at any level. Two
  design-doc ambiguities resolved and flagged during implementation, not
  picked silently — see SPEC.md's "Milestone 7" / A15. Flagged, not silently
  accepted: `same_lap_twice`'s pooled per-corner CV mixes metrics of very
  different scale with no normalization — same underlying issue as M6's
  cross-cohort `consistency` caveat, one level down.
  Constitution condition 5 (2026-07-19): `trend` and `evidence_count` are
  required M6 outputs, always present (never dropped for convenience).
- **Determinism verified mechanically**: two independent imports produce
  byte-identical Markdown/JSON/HTML reports.
- **M0b: done (2026-07-20)** — probed the live API with a real
  `GARAGE61_TOKEN`; `docs/garage61-api.md` generated from observed evidence.
  Auth, own-lap listing/pagination, and CSV fetch work and match the M0a
  contract exactly. The one genuine unknown is resolved: other-drivers'
  laps are visible in listings but return `403 forbidden_lap` on
  detail/CSV — reference laps stay on the manual `import` path
  (SPEC.md decision-of-record #2, clarified).
- **`sync` built and live-verified (2026-07-20)** — a real run against the
  owner's account pulled 25 laps/25 cohorts with real metadata; two reruns
  were fully idempotent (0 new); reference isolation held live
  (every synced lap `role='self'`). `Garage61Client` (stdlib `urllib`, no new
  dependency) + `sync_driver` + `driverdna sync`. Cohort discovery via
  `/me/statistics`; every lap is self-filtered on `driver.id` before fetch,
  so reference laps structurally cannot enter through this path. Real API
  metadata upgrades `session_key` and `run_index` beyond what manual CSV
  import can derive, and populates `lap_date` (M6 trend's precondition;
  trend computation itself remains a separate follow-up). Idempotent via
  the existing source_file/content_hash dedup. Date-range filtering is
  deliberately not implemented — M0b found the real param names unconfirmed.
- Coach/chat live runs blocked on `ANTHROPIC_API_KEY`; all provider tests are
  mocked regardless.
- **Spa blind acceptance test: run (2026-07-21, SPEC.md A18)** on 11
  independent GR86/Spa laps, 6 sessions. Caught two real things: the spec's
  original ground truth (Sector-1 high-speed entry, ±1.2 s) was never
  engine-corroborated on any dataset and is retracted; a genuine ranker bug
  (unscreened incident laps could inflate vs-self opportunity) was found and
  fixed (`attribution/ranker.py` now reuses `baseline()`'s outlier fence).
  Gate 1 in SPEC.md restates the engine's actual, incident-robust findings
  as the new ground truth. Full narrative: PROJECT-BRIEF.md decision log.

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
