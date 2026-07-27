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
- Secrets (`GARAGE61_TOKEN`, `ANTHROPIC_API_KEY`, `DRIVERDNA_DATABASE_URL`) are
  env-only: never persisted, printed, or logged. The database URL carries a
  password, so it is redacted before any connection error reaches a message, a
  log, or an HTTP body — and there is deliberately no bare `DATABASE_URL`
  fallback.
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
  Flagged, not silently accepted at the time: `consistency`'s CV pooling —
  fixed 2026-07-21, `dm-v2`, see below; the original "cross-cohort" diagnosis
  was itself wrong, see SPEC.md's M6 section.
- **M6 trend: built (2026-07-20)** — `trend` is the direction of a
  fundamental's own score between an earlier and a recent bucket of the
  driver's dated laps. Same scoring function per bucket via an additive lap-pk
  evidence filter; deterministic (ordered by lap_date, lap_pk); banded by
  `config.model.trend_delta_points`. Did not itself change `dm-v1`'s
  score/confidence for any evidence set (the field was always specified;
  the version has since moved to `dm-v2` for an unrelated reason, see
  below). Two flagged limitations (era-relative opportunity baseline;
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
  Originally built because the Garage61 API was believed to cap `/laps` at
  ~1 saved lap per driver per cohort — **that premise was wrong (A28,
  2026-07-27): it was `group`'s default, not a cap.** Still the only path
  for pre-API history and laps Garage61 never held, so it is not retired. Verified end-to-end
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
  the existing source_file/content_hash dedup. Date-range filtering landed
  with A28 (`--after`/`--max-age-days`) once the real param names were known.
- **`/laps` is not a personal-best endpoint (2026-07-27, SPEC.md A28)** — it
  was `group`'s default all along (`driver` = PB per driver; `group=none` =
  all laps). M0b's census was accurate but its conclusion ("the endpoint's
  shape … not something more API calls can pull around") was an inference
  presented as a fact, and it silently shaped three later decisions. `sync`
  now sends `group=none`, `drivers=me`, `unclean=true` (A19: an off is
  measured, not filtered), plus optional `after`/`age`. The authoritative
  parameter list came from `https://garage61.net/api/openapi/v1.json` — the
  JSON the "unreachable" JS developer portal fetches for itself, its URL a
  plain string in the SPA bundle. **Standing lesson: when a docs site won't
  render, read its client before declaring the documentation unavailable;
  and a negative capability claim needs a source, not a probe inference.**
  Spec-sourced, **not live-verified** (no token in that session): the
  client-side self-filter is kept unconditionally rather than trusting
  `drivers=me`, and each lap's `canViewTelemetry` is honoured per lap
  (`seeTelemetry` is documented Pro-only; the owner is on free, so whether
  non-PB CSVs are fetchable at all is still open).
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
- **Incident subsystem: built (2026-07-21, SPEC.md A19)** — a spin/off/
  near-stop is measured, not filtered ("measure the driver, not the lap").
  New `incidents/` package: deterministic lap-level detection (near-stop,
  off-track via `PositionType`, steering-reversal-with-yaw-spike snap) +
  mechanism characterization (trail-brake/lift-off/power-on oversteer,
  understeer-off, external, or `unclassified` when ambiguous), classified
  from the *causal* onset (first yaw divergence). N=1 events, never traits;
  reference laps never scanned; `incidents` table (migration 005); payload
  section; `driverdna incidents` artifact; cohort/laps UI. The 11 committed
  `spa-blind-2026-07/` laps are the real ground truth (`9XVJTW` spin →
  trail_brake_oversteer, `9PH9M2` dead-stop → detected).
- **Coaching over incidents: built (2026-07-21, SPEC.md A20)** — the deferred
  Layer 3. `incidents/coaching.py` fixes a deterministic, 1:1
  classification -> `coaching_principle_id` map (existing nine seed
  principles, none new); the coach's `incident_explanations` output is
  mechanically rejected unless it cites exactly that verdict — the AI
  explains, it never picks or overrides. `unclassified`/`external` incidents
  get no principle and cannot be explained. Built for the `coach`
  structured-output path; chat's live Q&A doesn't consume incidents yet
  (explicit boundary, tested both sides).
- **Coaching + Driver Model surfaced in the UI (2026-07-21)** — the M7
  coaching layer (headline/secondary/self-checks) was computed since M7 but
  never rendered; now a cohort-page section, grouped by principle so one
  notable at many corners is said once. Driver Model tab redesigned as a
  pyramid (foundations at the base; deliberately not a radar chart — its
  area would read as a blended score, forbidden by philosophy #6).
- **Upload-laps built (2026-07-21)** — `POST /api/laps/upload` (multipart,
  thin wrapper over `import_lap_file`, DB-effect parity with the CLI
  verified directly) + `#/upload` view close the last CLI-only gap in
  UI-SPEC view 7. The one write endpoint allowed to create the DB fresh —
  a true cold start, zero-to-cockpit through the browser alone, including a
  fix so the pre-any-lap empty state reads as direction, not a raw 404.
- **Git workflow (2026-07-21, owner instruction): commits go straight to
  `main`.** The branch + PR flow used earlier this session is retired.
- **Car/track auto-detect from filename (2026-07-21)** — Garage61's newer
  export filename shape (`Garage_61__<driver>__<car>__<track>__<laptime>__
  <id>.csv`) embeds car/track directly; `parse_garage61_filename`
  (`ingest/parser.py`) is additive to the locked M0a contract, only widening
  `lap_id` extraction. Both `driverdna import` (no `--car`/`--track`) and
  `#/upload` (blank fields) auto-detect per file, itemizing — never
  partially importing — any file that can't resolve either way. Verified
  against the owner's real Mustang GT4 / Summit Point laps, CLI and browser
  both. One flagged, unverified observation in `docs/garage61-api.md`: the
  new filename's trailing ID structurally matches the API's own ULID shape,
  unlike the old short code — untested against a live call.
- **Second export filename shape + working one-field override (2026-07-26,
  SPEC.md A24)** — Garage61 renamed its browser downloads again, to
  `Garage 61 - <driver> - <car> - <track> - <laptime> - <id>.csv` (` - `
  delimited, literal spaces in fields). That broke import on both surfaces:
  auto-detect returned nothing, so `#/upload` 422'd before the DB was
  touched. Both newer shapes now go through **one splitter** parameterized by
  prefix/delimiter/underscore-decoding — chosen because car/track are cohort
  keys and per-shape regexes absorb a surplus delimiter at different points,
  which is exactly how one cohort would silently become two (tested
  directly). A delimiter *inside* a field is refused, not guessed
  (philosophy: insufficient data over guessing); a re-download's ` (1)` is
  stripped before splitting so it never enters `lap_id`. Separately,
  `--car`/`--track` (and the `#/upload` boxes) are now **independently**
  optional: a given field applies to every file, a blank one keeps
  auto-detecting, so a future rename never strands the driver. Errors name
  the missing field per file. Verified end-to-end on the owner's real
  filename, CLI and browser.
- **`rebuild-map` refuses instead of destroying unmeasurable phase times
  (2026-07-26, SPEC.md A26)** — after A23 put blobs on local disk, an
  unreadable trace meant either "evicted here" (gone for good) or "imported on
  another machine" (intact there), and `rebuild_cohort_map` treated both as
  eviction: `delete_phase_times` plus a report blaming retention. Eviction now
  writes a tombstone (`<lap_pk>.evicted`) in the **blob store** — not a DB
  column, because eviction is per-machine while the store may be shared. A
  pre-flight raises `RawTracesUnavailable` before touching anything when a
  trace is missing without a tombstone; `--allow-missing-traces` overrides.
  Refusing beats clearing (destroys recoverable data) and beats skipping
  (would mix new-window and retired-window phase times, the exact thing A22
  prevents). First rebuild after upgrading may refuse on pre-existing
  evictions — deliberate, and safer than backfilling.
- **Cohort-label drift detected, never merged (2026-07-26, SPEC.md A27)** —
  `sync` labels a track `"Name (Variant)"` from the API; manual import uses
  the filename's bare name. Doing both splits one cohort in two, silently
  halving the evidence behind every baseline, trend and consistency number.
  `cohorts.find_label_drift` flags case/punctuation drift and
  variant-present-on-one-side-only, surfaced by `history` and at the end of
  `import` (where the fix still costs one re-import). Two *different* variants
  are deliberately not flagged — "track variants are distinct cohorts" is the
  spec's own rule, and a noisy warning would get ignored. Reported only: the
  right label isn't derivable from the strings, and cohort keys are
  load-bearing for evidence IDs.
- **Re-download suffix, corrected against real evidence (2026-07-26, SPEC.md
  A25)** — A24 stripped a browser re-download's `(1)` suffix assuming a
  leading space (`" (1)"`), never actually observed. The owner's own next
  re-download on Windows produced `...(1).csv` with **no space**, and the
  parser rejected it — the same "could not resolve car/track" error A24 was
  meant to close. Fixed by making the space optional; both spellings parse
  now, only the no-space one is confirmed against a real file. Recorded
  because it's the same mistake A24 itself warned against: an unverified
  guess presented as if observed.
- **`consistency` scoring fixed: per-unit CV normalization, `dm-v2`
  (2026-07-21, SPEC.md A21)** — the M6 "Known v1 limitation" note's own
  diagnosis (cross-cohort raw-magnitude pooling) was investigated before
  fixing and found wrong: each CV was already per-cohort. The real
  mechanism was cross-metric-*type* — a "% lap" metric's naturally tiny CV
  (~0.007) vs. a "count" metric's naturally huge one (~0.99) — dominating a
  flat average regardless of actual consistency. Fixed with a documented
  per-unit reference scale (`config.model.consistency_unit_reference_cv`, 9
  units from real telemetry) and two-level pooling (mean within unit, then
  across units — a flat mean and a median were both tried and rejected
  against real data and the existing trend tests). Real-fixture effect:
  `consistency` 5.1 → 34.3; `commitment` (inflated the *other* way by the
  same bug) 96.5 → 56.1. Found and fixed one incidental bug along the way:
  `ConfigStore`'s hand-rolled TOML writer had no dict-value support (fell
  back to Python `repr()`, invalid TOML) — never hit before this was the
  first dict-valued config field. Full record: PROJECT-BRIEF.md's decision
  log.
- **`rebuild-map`: in-place corner-map/window refreeze (2026-07-21, SPEC.md
  A22)** — `driverdna rebuild-map --car --track` re-derives every corner's
  centroid + canonical windows from the cohort's full accumulated lap set
  (not just the laps that first froze the map) and re-measures phase times.
  **In place, not versioned**: corner IDs / `corner_pk` never change, so
  evidence IDs stay valid — reasoning for in-place over a new `map_pk` in
  SPEC.md A22 (a versioned map would need a query-layer-wide `map_pk` filter
  to avoid cross-version double-counting; not worth it at this scale, and
  every other frozen value here is single-current). A lap whose raw blob was
  evicted past retention can't be honestly re-measured → its stale phase
  times are cleared and reported, never left silent (philosophy #7). New
  geometry still enters through the existing admission path; deterministic +
  idempotent (verified against the two real Spa/GR86 cohorts). Reuses
  `_freeze_windows_for_admitted`'s exact mechanism, generalized to every
  corner. Closes the A17-deferred refreeze gap.

- **Store moved to hosted Postgres (2026-07-26, SPEC.md A23)** — the primary
  store may now be a private, single-tenant Supabase Postgres; **SQLite stays a
  first-class, fully tested backend** (and the offline/rollback path). One set
  of SQL, translated per dialect by `sql.py`; `db.py` gained a connection proxy
  so the ~28 external `db.conn.execute` sites are untouched. Raw lap blobs
  moved out of the database onto **local disk** (`blobs.py`) — measured at ~95%
  of the bytes — so the hosted store holds only compact rows. Two
  silent-corruption risks are mechanically guarded: `REAL`→`DOUBLE PRECISION`
  (Postgres `REAL` is float4 and would have truncated every metric) and every
  text column `COLLATE "C"` (Supabase's en_US.UTF-8 collation would have
  reordered every report). Tables live in a `driverdna` schema with RLS and
  zero policies, because Supabase auto-exposes `public` over PostgREST.
  `driverdna store-copy` migrates in either direction preserving primary keys
  (evidence IDs *are* those numbers) with a per-table checksum proof;
  `driverdna migrate-blobs` completes the blob move for an older database.
  Equivalence is tested, not claimed: the same corpus in either backend
  produces byte-identical artifacts. Four latent bugs were found and fixed on
  the way — see A23 and PROJECT-BRIEF.md's decision log.

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
- The owner runs the CLI from a local Windows shell. Any command block given to
  them must be PowerShell-ready: full paths (not relative to some assumed cwd),
  and no bash-only syntax (`&&` chaining, `$(...)`, POSIX env-var syntax).
  `;` chains commands in PowerShell; `$env:NAME` reads/sets an env var.

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
