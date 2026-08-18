# DriverDNA v1 — Build Specification

Amended 2026-07-18 after owner review; supersedes the uploaded draft and all prior
plans. This document is self-contained and authoritative for the engine (the
*how*); **docs/ARCHITECTURE_VISION.md** is the constitution (the *why*) and, per
amendment A14, governs the scoring contract. Amendments relative to the reviewed
draft are listed at the end ("Amendment log"). Throughout, "the tool" and
"DriverDNA" refer to this application.

## Product intent

Optimize the driver, not the lap. Translate raw Garage61 telemetry into
track/car-transferable racing fundamentals, denominated in cumulative seconds lost
per technique, sharpening as data accumulates. Evidence discipline throughout: the
tool must be honest and useful at 40 laps, and must say "insufficient data" rather
than guess. Personal instrument, not a product. No opaque blended scores.

The deterministic engine is the source of truth. The AI layer — both the generated
coaching plan and the interactive chat — explains, prioritizes, and helps the
driver act on the deterministic findings; it never invents measurements. A grounded
conversation that helps the driver understand and refine the tool's interpretations
is a core v1 capability, not an add-on. The same evidence discipline that governs
reports governs the chat: answer from the findings, label anything beyond them as a
hypothesis, and never manufacture a number.

## Philosophy (confirmed by owner)

These nine principles are binding on every design decision below.

1. **Coach the driver, not the lap.** Track-specific findings are raw material; the
   deliverable is transferable technique, priced in cumulative seconds.
2. **Measurement and interpretation strictly separated.** The deterministic engine
   produces every number; the AI explains and prioritizes but never creates one.
   Anything beyond the measurements is labeled a hypothesis.
3. **Honesty beats helpfulness.** "Insufficient data" is a first-class answer.
   Every claim carries sample size and spread. Three trustworthy findings beat ten
   plausible ones.
4. **Provenance stays inspectable; scores are deterministic.** `vs-principle`,
   `vs-self`, and `vs-reference` mean different things and always remain
   separately inspectable. Composite scores (the Driver Model, M6) are
   permitted and are a core output, but only as **deterministic, versioned,
   confidence-qualified** figures that decompose to those sources — never an
   opaque blended number, and never AI-generated. See A14 and
   docs/ARCHITECTURE_VISION.md.
5. **The driver's own data is the primary signal.** Reference laps give context
   ("gap"), never promises ("recoverable time").
6. **The tool compounds.** Value is longitudinal; persistence is core, not optional.
7. **The driver stays sovereign.** Findings can be challenged, annotated,
   reprioritized; thresholds retuned — every change explicit, confirmed, versioned,
   reversible. Suppressing a finding never deletes the measurement.
8. **Personal instrument, not a product.** Local CLI, static reports.
   Simplicity and auditability outrank generality. (Refined by **A23**,
   2026-07-26: the primary store may be a private, single-tenant hosted
   Postgres; SQLite remains a first-class, tested backend and the offline
   path. Still one driver's instrument — no multi-tenancy, and no API for
   anyone but the one driver. Refined by **A31**, 2026-07-27: the original
   "no auth layer, ... owner's own localhost UI" clause is retired — the app
   is served over a hostname and now carries single-driver authentication.
   "No multi-tenancy" is reaffirmed, not softened: no user table, no
   registration, no second identity. Refined by A17,
   2026-07-20: personal instrument *first* — product potential is acknowledged
   and deferred until the instrument is proven on its owner, post-M6 and
   post-blind-test; any productization keeps the gates, no-blending, and
   evidence-ID constraints unchanged. Full record in PROJECT-BRIEF.md's
   decision log, including the veteran cold-start implications.)
9. **Designed to be distrusted.** Determinism tests, evidence IDs on every claim,
   trust gates. The architecture assumes verification before belief.

## Decisions of record

1. Ingestion: `sync` via the Garage61 developer API is the primary path; directory
   import of manually downloaded CSVs is a retained fallback using the identical
   parser.
2. Reference laps are in scope. Lap role is `self` or `reference`. Reference laps
   feed per-corner reference envelopes and gap analysis only — never the driver's
   technique history, trends, or consistency statistics. Clarified 2026-07-20
   (M0b observed behavior, `docs/garage61-api.md`): with the probed token/plan,
   `sync` cannot fetch a lap it doesn't own via `/laps` (`403 forbidden_lap`),
   even though such laps appear in unscoped `/laps` listings — so reference laps
   arrive via the manual `import` path only, tagged `role=reference`, exactly as
   this milestone's fallback already specified. `sync` for the driver's own laps
   is unaffected. Not reopened, but noted (2026-07-21, official Garage61 docs
   cross-referenced): the 403 is explained by `driving_data`'s documented
   default scope (self + teammates only), and a structurally different,
   entirely unexplored mechanism exists for legitimate sharing — team **data
   packs** (`docs/garage61-api.md`, "team data packs") — gated by permissions
   this token doesn't have. If reference-lap `sync` is ever revisited, that's
   the path to probe, not another `/laps` attempt.
3. Every finding carries a source tag: `vs-principle` (canonical technique checks —
   catches uniform weaknesses), `vs-self` (faster-vs-slower × stability), or
   `vs-reference` (gap to faster drivers). Reported separately; never blended into
   one score.
4. Persistence is required. A stateless directory analyzer contradicts the
   product's purpose. The store is SQLite or a private hosted Postgres (A23);
   raw lap blobs are always local-disk.
5. Corner classification by minimum-corner-speed band enables all cross-track
   aggregation. Nothing aggregates across tracks except within a class, within a
   car.
6. Cross-car technique claims are computed and stored but not reported in v1;
   per-car reporting only, until sample size justifies more. (Clarified 2026-07-20:
   this restricts the *finding* layer — a comparative claim like "your throttle
   technique is better in car A than car B." It does not block M6's Driver Model,
   which pools a driver's evidence across cohorts into one belief per fundamental
   ("how good is this driver at braking, overall") — a generalization about the
   driver, not a car-vs-car comparison. Breadth still gates confidence exactly as
   this decision intends: a belief resting on one car reads with the confidence
   that implies, never asserted as if it generalized further than the evidence
   does.)
7. AI coaching is on-demand only (`coach` for a generated plan, `chat` for
   interactive follow-up), provider-abstracted, Claude implementation. No automatic
   refresh (silent spend).
8. Reference-based deltas are labeled "gap to reference," not "recoverable time."
   vs-self and vs-principle findings are the primary practice signals.
9. Interactive coaching chat is grounded strictly in the deterministic findings and
   their evidence. It may explain, reprioritize, or challenge an interpretation,
   and may propose config changes — but it cannot fabricate metrics, and any change
   it makes to the tool's parameters requires explicit driver confirmation and is
   written to config, not silently applied.
10. Implementation stack: Python (3.11+), numpy/scipy for signal math, pydantic for
    typed models and config, typer for the CLI, stdlib sqlite3, anthropic SDK for
    the coach/chat provider. HTML reports from string templates; no web framework.

## Source contract (verified against both supplied exports)

Confirmed from the Mustang/Laguna (1:37.268) and GR86/Spa (2:51.250) telemetry
CSVs. M0a re-asserts these on the fixtures; any divergence in a future export fails
loudly.

Exact header, in order: `Speed, LapDistPct, Lat, Lon, Brake, Throttle, RPM,
SteeringWheelAngle, Gear, Clutch, ABSActive, DRSActive, LatAccel, LongAccel,
VertAccel, Yaw, YawRate, PositionType`.

- **60 Hz, no time column.** `elapsed_time_s = sample_index / 60`. Verified exact:
  rows÷60 matched the known lap time to 1.3 ms (Mustang) and 0.0 ms (Spa).
  50 Hz is ruled out.
- **One lap per file.** `LapDistPct` runs 0→1 across a single lap; it wraps at
  the start/finish line **0 or 1 times** depending on where the file boundary
  falls (a line-to-line sample never wraps; one starting just past the line
  wraps once — see amendment A12). Two or more wraps means a multi-lap file
  (`unexpected_wrap_count`); coverage well short of a full lap means a partial
  lap (`incomplete_lap`). Both are quality-flagged, not silently used.
- **Units:** Speed m/s (peaks ~208 / ~198 km/h; ×3.6 for km/h).
  `SteeringWheelAngle` radians → convert to degrees. Accelerations m/s². `YawRate`
  rad/s.
- **`ABSActive` / `DRSActive`:** string booleans `true`/`false` — parse explicitly,
  do not rely on truthiness. DRS is all-false in both fixtures.
- **`Lat` / `Lon` are real GPS** (Laguna ≈ 36.58, −121.76; Spa ≈ 50.44, 5.97). Use
  as the **primary corner-identity key**, `LapDistPct` as fallback — GPS anchoring
  matches corners across laps more robustly than distance-percent alone. (Simulator
  GPS is clean and consistent — no real-world noise — so clustering is low-risk.)
- **Filename is `Garage_61_<LAPID>.csv` and nothing more** (verified on the real
  downloads — an earlier draft wrongly claimed driver/car/track/lap-time were
  embedded). Parse the lap ID best-effort, never fail on absence. Cohort metadata
  (driver / car / track / configuration) comes from API metadata on the `sync`
  path and from user-supplied flags or a manifest on the `import` path. The
  fixtures' verified identities live in `tests/fixtures/manifest.toml`.

Absent — confirmed not present, design accordingly:

- **No fuel, no weather, no lap-validity/off-track, no run/stint-index channel.**
  This is a hard constraint. Stint-position control cannot use fuel; it must derive
  run grouping from sync/session metadata (one file = one lap, so runs are
  reconstructed at ingest, not read from a column). On the manual-import path, runs
  are reconstructed from file timestamps and user-supplied session metadata
  (filenames carry no timestamps); where reconstruction is impossible,
  stint-dependent findings degrade gracefully with a stated caveat rather than
  silently proceeding. Lap validity has no channel —
  outlier flagging only, with a stated caveat.
- **`Clutch` is pinned at 1.0** in both fixtures — treat as uninformative; build
  nothing on it unless a future file shows variation.

Dirty-data facts the parser must handle (not cosmetic — the principle detectors sit
directly downstream):

- **Pedals exceed [0,1] and go slightly negative.** Throttle >1 (3 samples each
  file) and <0 (10–14 samples); Spa has **143 negative `Brake` samples** and one
  `Brake` >1. Clip to [0,1] and raise a `clipped_pedal` quality flag with counts.
  Un-clipped values will corrupt brake-release-slope and throttle-monotonicity
  detection.
- **`Gear == 0`** appears (53 Mustang / 155 Spa samples), i.e. neutral/standing-
  start stretches. The segmenter ignores gear-0 spans rather than treating them as
  corner data.
- **`PositionType`** is a small integer enum (3 in most laps; a later Spa lap also
  shows 4 — see A13). Store it, don't depend on it.

## Architecture

- `Garage61Client`: token auth (`GARAGE61_TOKEN`, env only), list own laps
  filtered by car/track, fetch lap CSV, sync state in DB. Built 2026-07-20
  from M0b's observed behavior only: `/laps` is unscoped and requires
  `tracks`, so listing is client-side self-filtered on `driver.id`; date
  filtering is deliberately NOT implemented — M0b found the real query-param
  names for it unconfirmed, and this project never builds on an assumed
  param name. `sync` therefore re-lists a cohort's full lap metadata each
  run (cheap) and only fetches a CSV (the expensive part) for genuinely new
  laps, detected via the same source_file/content_hash dedup `import` uses.
- `Garage61Parser` → typed `TelemetryLap` (normalized channels, elapsed time, lap
  position, metadata, quality flags). `SessionLoader` → cohorts
  (driver/car/track-configuration) and reconstructed sessions/runs.
- `CornerSegmenter` → per-lap corner spans with phase landmarks. `CornerMap`
  (identity) → build→freeze→match GPS-anchored corner identities with persistent
  IDs. `CornerClassifier` → speed-band class per corner identity, with hysteresis.
- `TechniqueAnalyzer` (deterministic metrics) + `PrincipleDetectors` (canon checks)
  → evidence-bearing `DeterministicFinding`s.
- `AttributionEngine` → time-at-distance deltas over canonical per-corner phase
  windows, technique-tagged, confidence-gated.
- `ReportBuilder` → Markdown, JSON, and self-contained static HTML.
- `CoachProvider` interface with Claude implementation (`ANTHROPIC_API_KEY`, env
  only, never persisted or logged). Serves both the one-shot `coach` plan and the
  interactive `chat`.
- `CoachChat`: grounded conversation over the current findings and evidence. Builds
  the context bundle, enforces the grounding contract on responses, exposes
  read-only lookups and confirmation-gated config edits, and persists conversation
  turns for continuity.
- `ConfigStore`: typed TOML config with a documented default for every threshold;
  the single write path for parameter changes (whether from the CLI or a confirmed
  chat proposal), each change versioned and reversible.
- Storage: raw lap samples stored as one compressed npz blob per lap **on
  local disk** (laps are always loaded whole; nothing queries individual
  samples by SQL — see A23 for why they do not go to the hosted store);
  compact relational rows in SQLite or Postgres
  for everything queryable — lap metadata, quality flags, corner landmarks, metric
  values, findings, evidence refs, report outcomes, reference envelopes, sync
  state, coaching outputs, chat transcripts, and config history. Eviction of a
  lap's raw blob is a single-row delete that never touches summaries. Migrations
  under test. Stated, not assumed (2026-07-20, verified from code): after
  import, all downstream measurement math reads compact rows only — M3 reads
  stored phase times, M6 recomputes beliefs from compact rows — so a
  scoring-version bump never needs raw blobs and never justifies raising
  retention. The one measurement path that re-reads blobs is corner-admission
  window backfill (and a future map/window `rebuild` would share its shape):
  it re-measures only laps whose blobs survive retention, skipping evicted
  ones. That is the sole reason `retention.raw_laps_per_cohort` might ever be
  raised (see A17's veteran cold-start record).

Repository layout:

```
pyproject.toml
CLAUDE.md                      # build rules, milestone order, pointers here
docs/SPEC.md                   # this document
docs/schema-report.md          # generated by M0a
docs/garage61-api.md           # generated by M0b
src/driverdna/
  cli.py                       # sync · import · report · coach · chat · history · corners · metrics
  config.py                    # ConfigStore
  db.py                        # schema, migrations, dialect shim (SQLite/Postgres)
  sql.py                       # SQL + DDL translation between the two dialects
  store.py                     # store resolution; DSN redaction (env-only secret)
  blobs.py                     # local-disk raw lap blob store, retention
  migrate.py                   # store-copy: key-preserving copy + checksum proof
  garage61/client.py
  ingest/parser.py             # CSV → TelemetryLap
  ingest/loader.py             # cohorts, session/run reconstruction
  corners/segmenter.py         # detection + per-lap landmarks
  corners/identity.py          # build→freeze→match corner map
  corners/classify.py          # speed bands with hysteresis
  metrics/technique.py
  metrics/detectors.py
  attribution/engine.py        # canonical windows, robust baselines
  attribution/ranker.py        # vs-self ranker, gates, cumulative tables
  report/builder.py
  coach/                       # provider, payload, validation
  chat/                        # session, tool surface, grounding validator
tests/
  fixtures/                    # the 2 real CSVs + synthetic traces
```

## Milestone 0a — Lock the contract (requires: fixture CSVs)

The schema is already verified (see source contract); M0a turns it into regression
locks.

- Copy the two telemetry CSVs into `tests/fixtures/`.
- Schema-lock test: load both fixtures and assert the exact header order; 60 Hz
  reconstruction to < 5 ms of the manifest lap time; single `LapDistPct` wrap; m/s
  speed range sanity; radian→degree steering; string-boolean ABS/DRS parsing; GPS
  present and plausible; and the dirty-data counts (throttle >1 / <0, Spa's 143
  negative brakes and one >1 brake, gear-0 spans). Emit `docs/schema-report.md`
  from the run. Any future export that diverges fails here, consciously.
- Encode "absent" as tests too: assert no fuel/weather/validity/stint column
  exists, so a later silent addition is caught rather than assumed.

Done when `docs/schema-report.md` exists and schema-lock and absence tests are
green. Gates M1.

## Milestone 0b — Probe the API (requires: GARAGE61_TOKEN; gates only `sync`)

Resolves the one genuine unknown. Floats independently of M1–M3; must complete
before any code is built on assumed API behavior.

- With a real `GARAGE61_TOKEN`, verify auth, lap listing and filters, single-lap
  CSV fetch, pagination, and rate limits — and critically, whether **laps shared by
  other drivers** are fetchable with this token (the reference-lap feature depends
  on it).
- **Parity check:** fetch via the API a lap that also exists as a manual download
  and diff the two files. The fixtures are manual downloads; if the API path serves
  a different format, that must be discovered here, not in production parsing.
- Emit `docs/garage61-api.md` with observed evidence. If other-driver fetch is
  unavailable, reference laps degrade to manual-download import tagged `reference`;
  document the real capability, don't assume it.

Done when the doc exists and API capabilities are enumerated from observed
behavior.

**M0b: done (2026-07-20).** Probed live against `https://garage61.net/api/v1`
with a real token; observed evidence in `docs/garage61-api.md`. Auth, own-lap
listing (track/car-scoped, `driver.id` self-filter), pagination, and single-lap
CSV fetch all work, and the API CSV format matches the M0a-locked manual-export
contract exactly (header, column order, units, dirty-data character). The one
genuine unknown is resolved: other-drivers' laps are visible in listings but
`403 forbidden_lap` on detail/CSV — reference laps stay on the `import` path
(see decision-of-record #2's 2026-07-20 clarification above). Also discovered:
the manual-download filename's `LAPID` is not the API's lap `id` (different ID
schemes), so `sync` must never try to resolve one from the other.

**`sync` built (2026-07-20)**, directly on M0b's findings: `Garage61Client`
(`src/driverdna/garage61/client.py`, stdlib `urllib` only — no new
dependency) + `sync_driver`/`discover_cohorts`
(`src/driverdna/garage61/sync.py`) + `driverdna sync` CLI. Cohort discovery
via `/me/statistics` (no unscoped lap listing exists); every listed lap is
filtered client-side to `driver.id == /me`'s id before fetch, so a
reference/other-driver lap can never reach the import pipeline through this
path by construction, not just by convention. The API's own lap metadata
gave two upgrades the manual-import path can't: `event`+`session` become a
real `session_key` (no more best-effort reconstruction) and `run` becomes a
real `run_index` (a genuine stint index, where CSV-only import still has no
run/stint channel at all — SPEC.md's source contract). `startTime` becomes
`lap_date`, meeting M6's trend precondition (trend computation itself is
built — see the "Trend" section under Milestone 6 below for the full
mechanism; this paragraph only concerns what `sync` supplies it with).
Laps the API itself flags
`missing` or `incomplete` are skipped before fetch, surfaced by reason,
never silently dropped. Idempotent via the same source_file/content_hash
dedup `import` already uses (`source_file="garage61-api:<api lap id>"`).

## Milestone 1 — Parse, segment, identify, classify

- Parser per contract: time reconstruction, typed channel arrays, radians→degrees,
  string-boolean ABS/DRS, filename metadata best-effort, structured quality flags
  (missing channels, malformed values, inferred units, incomplete wrap, metadata
  failure, `clipped_pedal` with counts). All parseable laps admitted with flags;
  nothing silently repaired except pedal clipping to [0,1], which is flagged.
- Signal conditioning: clip pedals to [0,1] (flagged); exclude gear-0 spans from
  corner detection; light configurable smoothing before any derivative-based
  detection.
- Corner segmentation from sustained braking and/or steering activity; merge short
  gaps; landmarks per corner: entry, brake start, peak brake, brake release,
  turn-in, minimum-speed apex, throttle pickup, full throttle, exit. All thresholds
  in injected config with documented defaults.
- Multi-apex complexes (e.g., Spa Bus Stop) are a known-hard case: handle a double
  apex either as one complex with two apex landmarks or as two corners — but
  identically on every lap. Add synthetic fixtures for both shapes; cross-lap
  consistency outranks the representation choice.
- Corner identity — build→freeze→match: per cohort, build the corner map by
  clustering the GPS position (`Lat`/`Lon`) of each corner's minimum-speed point
  across laps (`LapDistPct` center as fallback when GPS is degraded), assign
  persistent corner IDs, then **freeze the map**. Subsequent laps are matched to
  the frozen map (nearest corner within a configurable radius), never re-clustered
  — IDs must not drift as data accumulates. A genuinely new corner is admitted only
  when unmatched consistently across a configured number of laps; every map change
  is surfaced in the report, never silent. The one deliberate way to re-derive a
  frozen map's centroids + canonical windows from the accumulated full lap set is
  the explicit, in-place `driverdna rebuild-map` command (A22) — IDs still never
  change, so it sharpens the map without drifting identity or breaking evidence IDs.
- Cohort key includes track **configuration** (from Garage61 metadata) — track
  variants are distinct cohorts.
- Classification: class assigned per corner identity from the median minimum corner
  speed across laps (not per lap). Default bands, configurable: slow < 90 km/h,
  medium 90–150, fast > 150 (channel is m/s; convert). **Hysteresis:** once
  assigned, a class changes only when the median moves a configured margin past the
  band edge, and the change is reported as an event. Store raw min speed so bands
  can be re-derived.
- Inspectable artifact: `driverdna corners` — a debug report of corners found per
  track, landmark table per lap, and ID assignment across laps.

Done when fixtures produce stable corner sets, IDs, and classes across all laps and
synthetic landmark tests pass.

## Milestone 2 — Metrics, principle detectors, persistence

- Deterministic metrics per corner/lap: braking (brake-point distance, initial
  application rate, peak, release duration and shape, trail overlap with steering,
  repeatability); rotation (turn-in point, steering smoothness and correction
  count, yaw response, minimum speed, repeatability); exit (throttle-pickup
  distance, modulation, full-throttle distance, exit acceleration); vehicle
  management (ABS activation rate; acceleration proxies only); consistency
  (lap-to-lap variance of every metric).
- Principle detectors, each `vs-principle`, threshold-configurable, with a
  plain-language rationale in output:
  1. Brake release should taper through turn-in — flag release completed more than
     a configured distance/time before turn-in.
  2. Throttle–brake overlap ≈ 0 — flag overlap beyond a noise floor.
  3. One steering input entry→apex — flag corrections (derivative sign reversals
     above a magnitude floor) beyond N.
  4. Throttle monotonic after pickup — flag lifts/stabs between pickup and full
     throttle.
  5. Coast window between brake release and throttle pickup — flag beyond
     threshold.
- Explicitly unavailable, never inferred: tire slip/utilization, vision. State the
  missing signal.
- Persistence per the architecture section: blob-per-lap raw storage; newest 100
  raw laps per driver/car/track cohort; permanent compact summaries for everything
  else; transactional eviction that preserves summaries and trend contributions;
  role isolation (`reference` laps never enter self trends).
- Inspectable artifact: `driverdna metrics` — per-corner/per-lap metric dump for
  eyeball verification against the traces.

Done when metrics are deterministic on fixtures, detector unit tests pass on
synthetic traces, eviction preserves trends, and a reference-lap import perturbs
gap sections only.

## Milestone 3 — Attribution and ranking

- Time-at-distance: per lap, interpolate t(LapDistPct).
- **Canonical phase windows:** per corner, phase boundaries are frozen from the
  cross-lap median landmark positions, expressed as track-distance points: entry =
  brake start→turn-in; mid = turn-in→apex; exit = apex→full throttle (or corner
  exit if earlier). Every lap is measured over these identical windows, so a phase
  delta is a true time difference over the same stretch of track. Per-lap landmarks
  feed the technique metrics; they are never the measurement windows. (Rationale:
  landmarks move lap to lap — that movement is the driving signal; measuring
  between per-lap landmarks would compare different track spans and produce
  plausible-looking nonsense.)
- **Robust baselines:** statistical outliers are screened before baseline
  selection; the primary baseline is the median of the driver's top-3 executions of
  that corner phase in-cohort (configurable; the single best is still displayed,
  labeled as such). Secondary: a composite best across phases, labeled theoretical.
  vs reference envelope (median and best) when present, labeled as gap. One
  invalid lap must never silently become the yardstick — there is no lap-validity
  channel to catch it otherwise.
- Technique tagging: each phase delta is associated with that phase's technique
  metrics.
- **vs-self ranker (defined here, fully):** within a cohort, laps are split into
  faster/slower terciles by lap time; opportunity = median phase-time difference
  between terciles for the corner/phase; repeatability = fraction of sessions in
  which the difference keeps the same sign; rank by opportunity × repeatability,
  always reporting both factors, inputs, sample counts, and confidence.
- Cumulative tables: total seconds lost by technique tag, by corner class, per
  cohort and per car (cross-track within car and class only).
- Controls: stint-position control uses lap index within a run. There is no fuel
  channel (confirmed absent), so runs are reconstructed at ingest from
  session/sync grouping and lap timestamps, not read from a column; lap-within-run
  index is therefore a proxy and is labeled as one. Lap validity has no channel —
  statistical outlier flagging with an explicit quality caveat, never silent
  exclusion.
- Confidence gates (configurable defaults): a finding is shown only with ≥ 10
  corner-phase samples and ≥ 2 sessions; cross-track rollups require ≥ 2 tracks.
  Every finding carries N, spread, source tag, and evidence IDs.
- Inspectable artifact: draft attribution tables in plain Markdown, generated from
  the fixtures.

Done when attribution tables are deterministic, gates are enforced, and the
acceptance tests below pass.

## Milestone 4 — Reports and one-shot coaching

- Markdown + JSON: cohorts, quality flags, measurements, rank inputs,
  cumulative-loss tables, evidence, unavailable fundamentals, data-quality caveats,
  and a driver rollup. JSON is normalized for determinism: sorted keys, fixed float
  precision, no wall-clock timestamps in the payload body.
- HTML: one self-contained file per report plus a rolling `driver.html`. Inline
  CSS, inline SVG charts (cumulative time lost by technique; per-class breakdown;
  session trend). No server, no external assets, no build step, static only.
- Coaching plan (`coach`): one-shot generation via the provider interface.
  Versioned structured payload: cohort metadata, deterministic findings, evidence
  IDs, historical trends, prior focus history; raw traces only behind a config
  flag, default off. Strict structured output: `measured_priorities` (referencing
  supplied evidence IDs only), `coaching_plan`, `hypotheses` (labeled, with
  confidence and evidence IDs). Local validation rejects unknown evidence IDs,
  unsupported metric claims, malformed rankings, or hypotheses presented as
  measurements. Persist accepted outputs with model/config/payload versions.

Done when mocked-provider contract tests pass for `coach`, validation rejections
are tested, and reports render fully offline.

## Milestone 5 — Interactive coaching chat (`chat`)

A grounded conversation the driver uses to understand, clarify, or adjust the
tool's feedback. The deterministic findings are the ground truth; the chat helps
the driver interpret and act on them, and refine how the tool computes them — it
never becomes a free-form racing chatbot detached from the data. Sequenced last
because it is the largest single component and reuses M4's payload and validation
machinery; reports and one-shot coaching are usable while it is built.

- **Context bundle** (per session, versioned like the coach payload): the current
  cohort's findings with evidence IDs, cumulative-loss tables, quality flags and
  confidence gates, unavailable-fundamentals list, prior focus history, and the
  most recent coaching plan. Raw traces only behind the same default-off flag. The
  bundle is assembled deterministically so a given question is answered against a
  known, inspectable state.
- **Grounding contract, enforced mechanically** on every response — not just
  requested in the prompt:
  - The model returns structured citations (evidence IDs) alongside prose; claims
    about the driver's technique route through the read-only tool surface. A
    response citing an evidence ID absent from the bundle is rejected.
  - A numeric-claim validator extracts numbers-with-units from the prose and checks
    each against values present in the bundle or returned by tools this turn
    (within tolerance); an unmatched number rejects the response.
  - A rejected response is regenerated once, then surfaced as an error rather than
    shown.
  - Anything beyond the measured findings is labeled a hypothesis with its basis —
    identical discipline to the report's `hypotheses` section. The chat may reason
    about *why* a pattern might occur (a coaching interpretation) as long as it is
    marked as interpretation, not measurement.
  - "Insufficient data" is a valid and expected answer. If the driver asks about
    something below its confidence gate or absent from telemetry (e.g. tire slip),
    the chat says so plainly rather than obliging.
  - General racing knowledge (the canonical principles behind the detectors) may be
    used to *explain* a finding, but must not be presented as a measurement of this
    driver.
  - Honest caveat: mechanical enforcement of natural language is approximate; the
    test suite defines exactly which violations are guaranteed caught, and that set
    is the contract.
- **What the driver can do in chat:**
  1. *Understand* — "why is Sector 1 flagged?", "what does trail-brake overlap mean
     here?" Answered from evidence and the principle rationale.
  2. *Clarify / challenge an interpretation* — "that corner is flat in this car,
     ignore it", "I lift there on purpose." The chat can mark a finding as
     acknowledged/intentional (a per-finding annotation stored in the DB), which
     suppresses it from future priority framing without deleting the underlying
     measurement.
  3. *Reprioritize* — "I want to focus on braking this month." Adjusts the emphasis
     of the *presentation*, not the measurements.
  4. *Adjust the tool's parameters* — "your one-correction rule is too strict for a
     bumpy track like this." The chat may **propose** a config change (e.g.
     steering-correction magnitude floor), show the current vs proposed value and
     what it would re-flag, and apply it **only on explicit confirmation**, via
     `ConfigStore`, versioned and reversible. It cannot silently retune detectors.
- **Read-only tool surface** exposed to the model (function-calling): look up a
  finding by ID, fetch a metric's distribution for a corner, list corners in a
  class, show current config value. These return real DB values — the mechanism by
  which the chat stays honest instead of recalling numbers from context. No tool
  writes except the confirmation-gated `propose_config_change`, which stages rather
  than commits.
- **Boundaries** ("within reason"): the chat answers about *this driver's* data,
  the tool's methods, and the racing principles behind them. It declines off-topic
  requests, does not generate car setups (out of scope, no setup data), and does
  not invent lap times or corner-level numbers it cannot retrieve. On disagreement
  about a measurement, it explains how the number was derived and offers the
  annotate/retune paths above rather than simply conceding or insisting.
- Persist transcripts with the bundle version, evidence IDs cited, any annotations
  created, and any config changes applied — the chat's effects are auditable, same
  standard as the reports.

Done when: mocked-provider contract tests pass for `chat`; the grounding contract
is enforced by tests (a response citing an unknown evidence ID or an unretrievable
metric is rejected; an out-of-gate question yields "insufficient data"); annotation
suppression and confirmation-gated config changes are tested end to end.

## Milestone 6 — Driver Model (deterministic scoring)

The center of gravity the constitution (docs/ARCHITECTURE_VISION.md) names: a
persistent, versioned belief store about the *driver*, fed by everything M1–M5
already persist. Additive — it reads the permanent compact rows across all of a
driver's cohorts; nothing in M0–M5 is rewritten. Pooling evidence across a
driver's cohorts is the intentional generalization this milestone exists for —
distinct from decision-of-record #6's restriction on car-vs-car comparative
findings; see the clarification there.

- **Taxonomy (versioned data).** A static `observable → technique → fundamental`
  map — the pyramid, made explicit. Every metric maps to exactly one place.
  Fundamentals with no observable (eye-line) and no proxy are marked
  unmeasurable; ones with a weak proxy (commitment ← entry-speed retention) are
  marked low-signal.
- **Scoring model (`dm-v1`, versioned).** A deterministic function from a
  driver's accumulated evidence per fundamental to **(score 0–100, confidence
  0–1, evidence_count, trend)**. Score is an explicit weighted aggregation of
  principle-adherence rate, normalized vs-self opportunity, and consistency;
  weights live in `ConfigStore` (documented, versioned, reversible). Confidence
  is a deterministic function of evidence volume *and breadth* (events,
  sessions, tracks, cars, spread) — pinned near zero where a fundamental is
  unmeasurable. No AI produces any of these numbers.
- **Reproducibility.** Belief recomputation is a pure function of the evidence
  set + `scoring_model_version` (order-independent, or explicitly ordered by lap
  timestamp) — the same evidence and version always yield the same beliefs. A
  version bump leaves past beliefs recomputable.
- **Persistence.** A `driver_beliefs` table stores per (driver, fundamental) the
  current score/confidence/evidence_count/trend + model version + timestamp.
  Implementation note (2026-07-20): belief computation is a pure read+compute
  (`compute_all_beliefs`) that runs live wherever a payload is built (report,
  coach, chat, the `/api/driver` and `/api/cohorts/{slug}/payload` endpoints) —
  so numbers shown are always current, never stale, without depending on the
  DB row being fresh. The `driver_beliefs` table is written explicitly (by
  `driverdna model`, or a future API refresh action), not on every lap
  import — recomputing after each import was considered and deliberately
  deferred (it would add cost to every import for a value already computed
  live on read); this can be revisited if a persisted history-over-time view
  is wanted later.
- **v1 limitation resolved: per-unit CV normalization, dm-v2 (2026-07-21,
  A21).** The v1 note below (as originally written) diagnosed this as
  cross-*cohort* raw-magnitude pooling with no per-cohort normalization.
  Investigation before fixing it (per this project's practice of verifying a
  documented mechanism against real code and real data before changing
  anything) found that diagnosis **did not match reality**: each CV was
  already computed from one cohort's own value array —
  `_consistency_component` never pooled raw magnitude across cohorts. A real
  two-cohort test (GR86/Spa + a second, real car/track) showed the *same*
  metric's CV was actually comparable across cars. The actual mechanism was
  cross-*metric-type*: a "% lap" landmark-position metric has a naturally
  tiny CV (~0.007) while a small-integer "count" metric (e.g. steering
  corrections) has a naturally huge one (~0.99), for equally repeatable
  driving — pooling raw CVs with a flat mean let whichever metrics were
  high-CV *by unit* dominate the signal regardless of the driver's actual
  consistency. Fixed: each raw CV is now divided by its own unit's typical
  scale (`config.model.consistency_unit_reference_cv`, 9 units keyed to
  metrics/technique.py's `METRIC_DEFS`, values are observed medians from
  real committed multi-car/multi-track telemetry) before pooling, and pooled
  in two levels — mean within each unit, then mean across units — so a unit
  with many contributing corners/metrics can't dominate by sample count
  either. A flat mean and a median (at either pooling level) were both tried
  and rejected against real data and the existing trend tests; see
  `model/scoring.py`'s `_consistency_component` docstring for why. Real
  formula change for the same evidence, so `SCORING_MODEL_VERSION` bumps
  `dm-v1` → `dm-v2` per the Scoring Contract (condition 2). Real-fixture
  effect (`docs/driver-model-report.md`, GR86/Spa + Mustang/Laguna):
  `consistency` 5.1 → 34.3, and `commitment` (previously inflated by the
  same bug in the opposite direction — its only consistency metric is a
  "% lap" type, trivially "consistent" against the old flat ceiling) 96.5 →
  56.1, both now correctly recalibrated rather than sitting at either
  extreme. Full record: PROJECT-BRIEF.md's decision log. **Not resolved by
  this change**: the separate, structurally similar M7 coaching-layer note
  below (`same_lap_twice` / `CoachingConfig.consistency_cv_floor`) — a
  different code path, still open.
  <br><br>
  *Original v1 note (2026-07-20), preserved for the record:* the
  `consistency` fundamental's coefficient of variation pools each metric's
  *raw* magnitude across every one of a driver's cohorts (car × track), with
  no per-cohort normalization first. Two cars with very different natural
  scales for the same metric (e.g. corner speed) will inflate the pooled CV
  beyond what either car alone would show — the score can read lower than a
  single-car view would justify. Confidence is unaffected (it counts evidence
  breadth honestly) but the score itself carries this caveat until a future
  version normalizes per-cohort before pooling. Observed on the real fixtures
  (GR86/Spa + Mustang/Laguna): `consistency` scored notably lower than
  `braking`/`rotation`/`corner_exit`, which are single-phase and less exposed
  to this effect.
- **Gated longitudinal outputs.** Archetype (a deterministic pattern over the
  fundamentals) and any universal-pace-gain estimate stay "insufficient data"
  until enough breadth exists (≥ 2 tracks / ≥ 2 cars, as the existing gates
  require). Per `ARCHITECTURE_VISION.md`'s Scoring Contract condition 5:
  `trend` and `evidence_count` are **required fields on every belief row,
  always** — when the data isn't available they hold an explicit "unavailable"
  value, never dropped from the schema for convenience.
- **Trend (built 2026-07-20; dated manual import built 2026-07-21).** A
  fundamental's `trend` is the direction of its own score between an
  *earlier* and a *recent* bucket of the driver's dated laps. Dated self-laps
  (`lap_date` set — `sync` populates it from the API's `startTime`; manual
  `import` can set it too, via `--date` or a manifest entry's own `date`
  field, since the Garage61 API caps `/laps` at ~1 saved lap per driver per
  cohort — `docs/garage61-api.md` — so a real per-cohort trend needs the
  driver's own exported history) are ordered by `(lap_date, lap_pk)` and
  split by count at the midpoint into two halves; the **same** scoring
  function runs on each (via a lap-pk evidence filter, additive to the M2/M3
  query surface), and the recent-minus-earlier delta is banded against
  `config.model.trend_delta_points` (default 5 points) →
  `improving` / `stable` / `declining`. It reads `unavailable` when there are
  fewer than `2 × trend_min_laps_per_bucket` dated laps (default 4/bucket) or a
  bucket has no scorable evidence for the fundamental — so on undated fixtures
  it stays `unavailable`, by honest gap not omission. Deterministic (explicit
  lap-timestamp order, per the
  Reproducibility contract). Completing this field changes no score/confidence
  for any evidence set, so `scoring_model_version` stays `dm-v1` (the field was
  always specified; dated evidence never existed under the old always-
  "unavailable" path — decision recorded in PROJECT-BRIEF.md). *Two flagged v1
  limitations, in the era-windowing territory A17 deferred:* (1) the
  opportunity component's baseline is recomputed per bucket, so it is
  era-relative (adherence/consistency carry the signal cleanly); (2) buckets
  pool across cohorts, so when dated laps are thin-per-cohort the two halves
  can hold different cars/tracks and a direction partly reflects cohort mix,
  not skill-over-time alone — sharpens as dated laps accumulate per cohort.
  First live exercise (owner's 25-lap synced history): braking and rotation
  read `improving`, corner_exit/commitment `stable`, consistency/vehicle_
  management honestly `unavailable` (1 lap/cohort can't fill a bucket's
  per-corner CV).
- **AI role (unchanged contract).** Coach/chat gain the beliefs in their
  payload/bundle and may *explain* a score and *recommend the highest-impact
  practice priority*; they never produce or adjust a score (enforced by the
  existing numeric-grounding validator — a belief is just another payload
  number). Every score is presented with its confidence, evidence count, and a
  plain "this is a model estimate; here's how to sharpen it."
- **Artifact:** `driverdna model` — the per-fundamental score / confidence /
  evidence table, deterministic. The DriverModel UI view (`#/model`) was
  built 2026-07-21 (render-only over this section; PROJECT-BRIEF.md log).

Done when: the scoring model is deterministic and versioned (two runs →
identical beliefs); every score carries confidence + evidence count;
unmeasurable fundamentals read as "no signal / 0%", not fabricated; gated
outputs suppress with reasons until breadth exists; the AI surface explains but
never emits a score (tested against the mocked provider).

## Milestone 7 — Coaching Intelligence (built 2026-07-20)

Full design in `docs/COACHING.md` (design adopted, then built, same day); this
is the milestone-tracking summary. Additive over M1–M6; reads detector trigger
rates (M2), `cumulative_loss` and vs-self findings (M3), and per-corner metric
values (M2) — nothing upstream is rewritten.

- **Ontology (versioned data, `coach-onto-v1`).** Nine seed `CoachingPrinciple`s
  (`src/driverdna/coaching/ontology.py`), each mapped to exactly one M6
  taxonomy technique/fundamental so `signal_status` is never asserted
  independently of M6's own tri-state rule. Gates are declarative data
  (`DetectorGate` / `MetricCVGate` / `FindingGate` / `AlwaysEligible`), not
  bespoke per-principle functions — adding a coaching concept stays a data
  change, per the design's own intent.
- **Eligibility + ranking + gap bands (deterministic engine, no AI).**
  `coaching/engine.py`'s `eligible_principles()` is a pure function of DB state
  + config; `select_coaching()` groups the result into headline (the single
  largest seconds-banded notable/major item) / secondary (moderate, and
  notable/major not chosen as headline) / silent_count / self_checks
  (`no_signal`, always present, never headline-eligible). Gap-band and CV-band
  thresholds are versioned in `ConfigStore` (`CoachingConfig`).
  Two ambiguities in the original design doc, resolved and flagged rather than
  picked silently (see `coaching/engine.py`'s module docstring for the full
  reasoning): (1) headline requires notable/major, not moderate — the more
  specific, more repeated rule wins over a looser phrase elsewhere in the same
  doc; (2) gap band (volume) and `signal_status` (conviction) are independent —
  a `proxy` principle can still win the headline slot on magnitude but must
  stay phrased tentatively regardless of band.
- **AI role (unchanged contract, extended schema).** Coach/chat payload gains a
  `coaching` section (headline/secondary/self_checks, each with evidence IDs);
  the AI selects and phrases only, never invents or promotes an ineligible
  principle. The grounding validator is extended (`coach/validate.py`,
  `chat/session.py`): a `coaching_principle_id` outside the eligible set is a
  mechanical rejection, identical machinery to an unknown evidence ID; a
  `no_signal` principle carrying any confidence/percentage language is a
  separate mechanical rejection (`docs/COACHING.md`: "a confidence value never
  launders an unmeasured inference"). Coach's structured schema bumped
  `coach-v1` → `coach-v2` (adds `coaching_priorities`); chat's bundle bumped
  `chat-v1` → `chat-v2` (same rule, prose-scoped). `PAYLOAD_VERSION` 2 → 3.
- **Known v1 limitation, flagged not silently accepted. Still open (A21,
  2026-07-21, only fixed M6's sibling issue — see below).** `same_lap_twice`
  (the one principle with no phase to band on — consistency is cross-cutting)
  pools coefficient of variation across every measured metric on a corner,
  unweighted, mixing metrics of very different scale/type (percentages, rates,
  small integer counts). A low-mean count metric can produce an outsized CV
  that dominates the average — the same underlying mechanism as M6's
  `consistency` fundamental had (cross-*metric-type*, not cross-cohort as
  first documented), one level down (per-corner instead of per-driver). M6's
  own case was fixed by per-unit CV normalization (A21, Milestone 6 section
  above); this coaching-layer case uses a different code path
  (`coaching/engine.py`, `CoachingConfig.consistency_cv_floor`) and was
  deliberately left unfixed here — a same-shaped fix could likely reuse
  `model.consistency_unit_reference_cv`, but that's a call for whenever this
  principle's own scoring is revisited, not bundled into A21's scope. See
  `CoachingConfig.consistency_cv_floor`'s docstring.
- **Artifact:** `driverdna coaching` — per-cohort headline/secondary/silent/
  self-checks with triggers and gap bands shown, deterministic ("why this
  advice, and why this loud"). A coaching UI view follows on the U-track.

Done when: eligibility, ranking, and gap-band assignment are deterministic and
versioned (tested); a mocked-provider coach/chat response invoking an
ineligible or invented principle is rejected, not shown (tested); a response
putting a confidence value on a `no_signal` principle is rejected, not shown
(tested); "nothing clears notable" yields insufficient-data coaching for the
headline slot, not a manufactured priority (tested); every surfaced piece of
advice cites a principle that cites evidence, or for `no_signal` is clearly
labeled a self-check (tested); no `no_signal` principle ever renders with a
score or confidence, at any level, in any test.

## Acceptance — trust gates

1. Spa blind test: run on the owner's GR86/Spa laps (≥ 2 sessions; to be supplied)
   with no hints. **Run 2026-07-21 on 11 independent laps across 6 sessions
   (none in `tests/fixtures/`) — see A18.** The originally-stated ground truth
   below never held on any dataset and is retracted; the engine's own
   incident-screened output is the current ground truth, restated here so a
   future re-run has something concrete to compare against:
   entry-and-mid-phase loss concentrated at the two slow corners (La
   Source C01 mid ≈0.82 s, Bus Stop C15 exit/entry, both repeatable across
   sessions), fast corners (Eau Rouge/Raidillon, Blanchimont) essentially
   loss-free (≈0.09 s aggregate). Class-level loss: slow ≈1.33 s > medium
   ≈0.96 s > fast ≈0.09 s per lap — the *inverse* of the original
   high-speed-entry prediction. Failure blocks trusting any novel finding.
   Caveat, recorded honestly: the expected answer is written in this spec,
   which the builder reads — so this is a smoke test against gross failure, not
   independent proof; A18 also documents why the *original* ground truth was
   never independently verified either, which is what the blind run caught.
2. Determinism: identical inputs → identical JSON (normalized: sorted keys, fixed
   float precision, no wall-clock timestamps).
3. Reference isolation: importing a reference lap changes gap analyses only; self
   history byte-identical.
4. Stint control: a synthetic set where only stint position varies yields zero
   technique findings.
5. Chat grounding: with a mocked provider, a chat response that cites an evidence
   ID absent from the bundle, or asserts a metric not retrievable from the DB, is
   rejected — not shown. An out-of-gate or no-telemetry question ("how's my tire
   slip?") returns "insufficient data / not measured," never a fabricated answer. A
   confirmed config proposal writes through `ConfigStore` and is reversible; an
   unconfirmed one changes nothing.
6. Full regression suite: schema handling on both fixtures (header order, 60 Hz,
   single wrap, pedal clipping, gear-0, GPS), malformed/missing inputs, synthetic
   landmark traces (including steering-only corners and brake-release gaps), cohort
   partitioning, retention/eviction, serialization.

## CLI and configuration

`driverdna sync` (incremental API pull) · `driverdna import <dir>` ·
`driverdna corners` (M1 debug: corner map + landmarks) · `driverdna metrics`
(M2 debug: metric dump) · `driverdna report [--cohort]` · `driverdna coach`
(one-shot plan) · `driverdna chat [--cohort]` (interactive grounded session) ·
`driverdna history`.

One config file (TOML) for thresholds, speed bands, confidence gates, retention,
smoothing; typed defaults; every threshold documented where it is defined; all
parameter changes (CLI or confirmed chat proposal) flow through `ConfigStore`,
versioned and reversible.

## Out of scope for v1

**Multi-user** hosted sync (tenant keys, queued ingest, shared deployment) —
single-user hosted storage is now in scope, see A23, which removed the
original blanket "hosted sync" item; **AI-generated or unconfidenced scores**
(deterministic confidence-qualified scores are in scope via M6), slip/vision
inference, automatic AI refresh, non-Garage61 sources. Cross-car claims remain computed
but unreported until sample size justifies them. The local UI layer is
specified separately in **docs/UI-SPEC.md** (owner-adopted 2026-07-19); the
Driver Model (M6) is governed by **docs/ARCHITECTURE_VISION.md**. This spec
remains authoritative for the engine, and every surface renders what the engine
computed — it never computes a measurement.

## Setup and build order

- Environment: `GARAGE61_TOKEN`, `ANTHROPIC_API_KEY`, and (when using the
  hosted store) `DRIVERDNA_DATABASE_URL` — all env only; never persisted,
  printed, or logged, and the database URL is redacted before any connection
  error is surfaced. `DRIVERDNA_BLOB_ROOT` optionally relocates raw lap blobs,
  which are local-disk only and never sent to the hosted store. Python 3.11+.
  The Postgres backend needs the `pg` extra (`pip install -e '.[pg]'`); a
  SQLite-only install requires no database driver.
- Fixtures: the two telemetry CSVs belong in `tests/fixtures/` (owner-supplied);
  M0a cannot run without them.
- Build order is strict within the dependency chain: **M0a → M1 → M2 → M3 → M4 →
  M5 → M6 → M7**; do not begin a milestone until the prior milestone's
  done-criteria pass. M6 (Driver Model) reads M1–M5's persisted rows and is
  additive. M7 (Coaching Intelligence — grounded coaching ontology over the
  Driver Model) is specified in **docs/COACHING.md**; design **adopted
  (2026-07-20)**, **built (2026-07-20)** — see "Milestone 7" below.
  **M0b floats**: it requires `GARAGE61_TOKEN`, gates only the `sync` feature, and
  must complete before any code assumes API behavior. The Spa blind test (gate 1)
  runs when the owner's Spa lap set is supplied; it is the final trust gate, not a
  build blocker.
- Every milestone ends with its tests green **and** its inspectable artifact
  generated from the real fixtures and reviewed by eye. The first human-readable
  output must not wait until reports exist — segmentation and identity bugs must be
  visible at the milestone that creates them.

## Amendment log (relative to the reviewed draft, 2026-07-18)

Accepted at owner plan review; rationale recorded in the review:

- **A1** Attribution measures phase deltas over canonical per-corner windows frozen
  from cross-lap median landmarks — never between per-lap landmarks (correctness).
- **A2** Baselines are robust: outlier screening + median-of-top-3 default; single
  best displayed but labeled; composite labeled theoretical.
- **A3** Corner identity is build→freeze→match with an explicit admission rule and
  surfaced map changes — never perpetual re-clustering. Cohort keys include track
  configuration.
- **A4** Classification gains hysteresis; class changes are reported events.
- **A5** M0 split into M0a (contract lock, fixtures only; gates M1) and M0b (API
  probe, token required; gates only sync) + API-vs-manual parity diff added.
- **A6** Chat moved to its own milestone (M5) after reports + one-shot coach (M4).
  Same v1 scope, safer sequencing.
- **A7** Chat grounding enforcement made mechanical: structured citations,
  numeric-claim validator, unknown-ID rejection, one regeneration then error, with
  the test suite as the contract.
- **A8** Every milestone emits an inspectable artifact (`corners`, `metrics`, draft
  attribution tables) so algorithmic bugs surface at the milestone that creates
  them.
- **A9** The vs-self ranker is fully defined in this document (terciles, opportunity,
  repeatability) instead of referencing a prior plan.
- **A10** Raw lap samples stored as one compressed blob per lap; relational rows
  only for queryable compact data.
- Stack decision recorded (decision 10); session/run reconstruction rule for the
  manual-import path defined; determinism normalization specified; Spa blind-test
  caveat recorded.
- **A11** (2026-07-18, fixtures in hand): filename contract corrected — real
  downloads are `Garage_61_<LAPID>.csv`, lap ID only. Lap-time anchoring moved to
  `tests/fixtures/manifest.toml`; import-path cohort metadata is user-supplied;
  fixture identities verified from data (GPS + duration).
- **A12** (2026-07-19, more laps supplied): the "single wrap" rule was too narrow.
  A single complete lap wraps **0 or 1 times** — a file sampled exactly
  start/finish-line to line runs 0.000→1.000 monotonically and never wraps. The
  real invariants are *single lap* (≤1 wrap; 2+ → `unexpected_wrap_count`) and
  *complete* (unwrapped coverage ≳ 0.97; less → `incomplete_lap`). Both new
  guards are quality-flagged, nothing silently repaired. Also widened: steering
  is radians but can exceed 2π at slow hairpins (road-car wheel past a full
  turn), so the "is radians" bound is ~2 turns, not < 2π.
- **A13** (2026-07-19): `PositionType` is not constant — a later Spa lap shows 4
  alongside the usual 3. It remains store-don't-depend; the lock is now a small
  integer enum, not a fixed value. Separately, import now rejects **content
  duplicates** (a lap re-downloaded under a different filename fingerprints
  identically and is skipped, never double-counted) — surfaced, not silent.
- **A14** (2026-07-19, owner decision): scores are adopted as a core output.
  Philosophy #4's "no overall score" is refined to "no *opaque* blended score":
  the Driver Model (M6) produces **deterministic, versioned, reproducible**
  scores that always ship **Score + Confidence + Evidence Count** and decompose
  to the separated sources. No score is AI-generated; AI explains scores and
  recommends practice priorities only. The scoring model may evolve through
  research but stays versioned and reproducible. Governing document:
  **docs/ARCHITECTURE_VISION.md** (the project constitution / the *why*), which
  this spec now serves as the *how*.
- **A15** (2026-07-20, owner decision): M7 (Coaching Intelligence) built per
  `docs/COACHING.md`. Philosophy #2 (measurement/interpretation strictly
  separated) is refined the same way A14 refined #4: coaching *language* is a
  constrained selection from a versioned, evidence-triggered ontology, never
  free LLM prose — the AI phrases within the ontology, it does not decide
  *whether* a coaching concept applies. Two ambiguities in the adopted design
  doc were resolved during implementation rather than picked silently (full
  reasoning in `coaching/engine.py`'s module docstring): headline eligibility
  requires the notable/major gap band, not moderate; gap band and
  `signal_status` are independent axes (volume vs. conviction). See "Milestone
  7" above for the full build summary, including the flagged v1 CV-pooling
  limitation in `same_lap_twice`.
- **A16** (2026-07-20, M0b run with a real `GARAGE61_TOKEN`): the reference-lap
  fetch question is resolved from observed behavior, not assumption — other
  drivers' laps are visible in `/laps` listings but return `403 forbidden_lap`
  on detail/CSV fetch; own-account laps and the API's CSV format (byte-for-byte
  contract match) work fully. Reference laps therefore use the manual `import`
  path only (decision-of-record #2, clarified above); `sync` for self laps is
  unblocked. Full evidence: `docs/garage61-api.md`.
- **A17** (2026-07-20, owner decision): philosophy #8 refined — personal
  instrument *first*; product potential (plausibly veteran drivers with large
  lap histories) is acknowledged and **deferred until the instrument is proven
  on its owner** (post-M6, post-blind-test). Nothing in the build order
  changes; nothing is built for multi-user now. Any future productization
  keeps the gates, no-blending, and evidence-ID constraints unchanged.
  UI-SPEC's out-of-scope list is split accordingly (permanent exclusions vs
  v1-only deferrals). Full record — including the veteran cold-start strains
  (map/window refreeze via `rebuild-map`, vs-self era-windowing, bulk-import
  ergonomics) and the verified answer to the blob-retention question — in
  PROJECT-BRIEF.md's decision log.
- **A18** (2026-07-21, Spa blind test finally run): 11 independent GR86/Spa
  laps supplied across 6 sessions, imported to an isolated scratch DB (never
  `tests/fixtures/`). Two findings, both real:
  (1) The gate itself works — no crash, all three sources decomposable,
  thin corners correctly suppressed with stated reasons.
  (2) The *predicted* answer (high-speed-corner entry commitment, Sector-1
  ±1.2 s entry spread) never held — not on the new data, and, re-checked, not
  on the original `tests/fixtures/` corpus either (max per-corner entry
  spread ≈0.15 s in both). The figure in gate 1 was never engine-corroborated;
  it read as a coarse, unverified belief about the driving, written into the
  acceptance criteria before the criteria could check it. That is exactly the
  failure mode a blind test exists to catch, and it caught it.
  Separately, investigating *why* the top two engine-reported findings looked
  large (C01 mid 2.06 s, C15 exit 1.95 s) surfaced a real engine bug: one spin
  (La Source, 5 km/h) and one 15 s dead stop (Bus Stop) landed in the slow
  tercile of `vs_self_findings`'s opportunity split, which — unlike
  `baseline()` — applied no outlier screening. Fixed: the same median±k·MAD
  fence `baseline()` already used is now applied to the opportunity/
  repeatability computation too (`attribution/engine.py`'s `outlier_mask`,
  `attribution/ranker.py`); `docs/attribution-report.md` regenerated (two
  fixture findings, C03 exit and C02 mid, were themselves partly
  outlier-inflated and are now correctly suppressed); a regression test
  (`test_vs_self_opportunity_ignores_one_incident_lap`) plants an isolated
  incident and asserts it's screened. Re-run post-fix produced gate 1's
  restated ground truth above. Full narrative, including the incident
  forensics (speed-trace confirmation of both incidents), in
  PROJECT-BRIEF.md's decision log.
- **A19** (2026-07-21, incident subsystem — a new deterministic finding
  family): every other telemetry tool discards a spin/off as noise; per
  philosophy #1 ("measure the driver, not the lap") DriverDNA measures it —
  an incident is the richest driver signal on a lap. New `incidents/`
  subsystem: a lap-level scan (`detector.py`) finds incident windows
  (near-stop, off-track via `PositionType` — corroborating only, per A13 —
  and a steering-reversal-with-yaw-spike snap), and `classify.py` names the
  mechanism (trail-brake / lift-off / power-on oversteer, understeer-off,
  external kerb/bump) from the telemetry at the *causal* onset — the first
  yaw divergence, where the input that caused it still lives, not the
  peak-yaw moment by which the driver is already catching it. This refines
  three philosophy points, named here per the decision-discipline rule:
  #2 (sources separately inspectable — an incident record decomposes to the
  exact samples and channel values), #3 (insufficient-data-over-guessing —
  an ambiguous signature returns `unclassified`, never a guessed cause;
  confidence is high/medium/low, never a percentage that would launder an
  inference, echoing A15's binding rule one level down), and #7 (nothing
  hidden — today's A18 fix *screens* incidents from pace stats, so the
  constitution requires they still be *surfaced*: they are, richly).
  An incident is characterised as a single event (N=1: "this lap did X"),
  never generalised into a trait — a repeated pattern needs N and goes
  through the normal finding gates. Persisted in a new `incidents` table
  (migration 005), scanned for self laps only (reference laps never enter),
  surfaced in the payload (`incidents` section, PAYLOAD_VERSION 3→4), the
  `driverdna incidents` artifact, and the cohort/laps UI. Deliberately kept
  OUT of the coach/chat bundles: the AI may *explain* a classification only
  once the grounded citation path exists (incident evidence IDs in the
  citable universe) — that is "Coaching over incidents" (Layer 3), a
  separate later pass, not built here. Two thresholds (near-stop absolute
  floor; the on-track `PositionType` value) are track/sim assumptions with
  documented defaults, retunable through ConfigStore. Validated on the
  committed real ground-truth laps (A18's `9XVJTW` spin →
  trail_brake_oversteer/high; `9PH9M2` dead-stop → detected; every clean lap
  silent). Full record in PROJECT-BRIEF.md's decision log.
- **A20** (2026-07-21, coaching over incidents — Layer 3, closing A19's
  explicit deferral): the AI may now *explain* an incident's classification,
  never produce or choose it — refining non-negotiable #1 ("AI... never
  produces or adjusts a number") one level further: here the AI never
  produces or adjusts a *diagnosis* either. The link from an incident's
  classification to the one coaching principle eligible to explain it
  (`incidents/coaching.py`'s fixed mapping — `trail_brake_oversteer` →
  `cp.brake_release.finish_the_front`; `lift_off_oversteer`/
  `power_on_oversteer` → `cp.throttle_pickup.roll_it_on`;
  `understeer_off` → `cp.turn_in.one_commitment`, from the existing nine
  seed principles) is deterministic and 1:1, computed once in the payload,
  identical for every consumer. The coach's `incident_explanations` output
  is mechanically rejected if its `coaching_principle_id` differs from that
  verdict even slightly — the AI has zero choice, only prose — and rejected
  outright for `unclassified`/`external` incidents (refines #3,
  insufficient-data-over-guessing: the engine didn't name a cause, so
  neither may the AI, mechanically enforced the same way an unknown
  evidence ID is). Built for the coach's structured-output path only; chat's
  live Q&A does not consume incidents yet (a later pass — the boundary is
  explicit and tested on both sides). Full record in PROJECT-BRIEF.md's
  decision log.
- **A21** (2026-07-21, `consistency` per-unit CV normalization, `dm-v2`):
  the M6 "Known v1 limitation" note's original diagnosis (cross-cohort raw-
  magnitude pooling) was investigated before being fixed and found not to
  match the code or real data — the actual mechanism was cross-*metric-type*
  pooling (a "% lap" metric's naturally tiny CV vs. a "count" metric's
  naturally huge one). `_consistency_component` now normalizes each metric's
  CV against a documented per-unit reference before pooling in two levels
  (mean within unit, then mean across units); see the corrected Milestone 6
  note above for the full mechanism and real-fixture before/after. Refines
  non-negotiable #4 (composite scores must be "deterministic, versioned,
  and confidence-qualified... always decomposable to the sources") one
  level further: decomposability includes the pooling formula itself being
  honest about *what* it's normalizing against, not just citing evidence
  IDs — an inaccurate documented mechanism is its own kind of opacity, even
  when the score is technically decomposable to real numbers. `dm-v1` →
  `dm-v2` per the Scoring Contract (ARCHITECTURE_VISION.md condition 2 —
  a real formula change for the same evidence). New config default:
  `model.consistency_unit_reference_cv` (9 units); `model.consistency_
  cv_ceiling`'s default changed 0.5 → 2.0 (same role, now expressed in
  multiples of a metric's own unit reference rather than raw CV). Full
  record, including the two rejected pooling designs (flat mean, median),
  in PROJECT-BRIEF.md's decision log.
- **A22** (2026-07-21, `rebuild-map` — versioned-in-name, in-place-in-fact
  corner-map/window refreeze): corner maps and canonical phase windows
  freeze from a cohort's first laps (M1 build→freeze→match) and never
  re-derive as more data accumulates — a gap deferred since A17 ("no build
  work now"; it only bites at veteran-scale histories). `driverdna
  rebuild-map --car --track` re-derives every corner's centroid + canonical
  windows from the cohort's FULL current observation set and re-measures
  phase times. Two design forks, both owner-decided deliberately (not
  assumed) after the mechanism was fully read out:
  1. **In-place, not a new `map_pk`.** `corner_pk` / `corner_id` never
     change, so every evidence ID (`obs:{obs_pk}`, and the corner it resolves
     through) stays valid; existing observations keep their corner
     assignment and each corner's centroid is recomputed FROM those
     assignments, so the two stay consistent with no re-matching. This
     reuses the exact mechanism `_freeze_windows_for_admitted` already
     applies to a newly-admitted corner, generalized to every corner.
     Rejected: a versioned map (new `map_pk` per rebuild) would force
     dropping `corner_maps`' `UNIQUE(car, track)`, a current-map concept, and
     an `AND c.map_pk = <current>` filter on every query joining `corners`
     (else cross-version double-counting) — a large query-layer change for a
     history-of-past-maps feature not needed at this scale; every other
     frozen value in the codebase is single-current, so in-place is
     consistent, not an exception. Refines philosophy #6 (longitudinal/
     versioned) pragmatically: the *scoring* model and taxonomy carry real
     version strings because past beliefs must stay recomputable; a corner
     map is geometry that only ever sharpens toward the true track, so a
     single current map that improves in place is the honest model, and
     evidence-ID stability is the property actually worth protecting.
  2. **An evicted raw blob → clear the stale phase times + report, never
     leave them.** A lap whose blob was evicted past retention can't have its
     phase times honestly re-interpolated against the new windows; leaving
     the old numbers would present a measurement against a retired window
     definition — silent repair, forbidden (philosophy #7 / the "nothing
     silently repaired" rule). `rebuild-map` DELETEs those `phase_times` rows
     and lists every affected `(lap_pk, corner_id)`; the lap's
     `corner_observations` row, metrics, detector results, and evidence ID
     all stay intact — only the phase-time attribution figure goes, exactly
     like any other "insufficient data" gap. At today's data volume
     (retention default 100/cohort) this doesn't fire, but the behavior is
     defined and tested (a shrunk retention forces an eviction) rather than
     discovered later. Genuinely new geometry still enters through the
     existing audited admission path; classes re-derive after,
     hysteresis-sticky, self-only. Deterministic and idempotent (a second
     rebuild of the same data is a no-op — verified by test). Full record in
     PROJECT-BRIEF.md's decision log.

- **A23** (2026-07-26, owner-directed): **the primary store moves from a local
  SQLite file to a hosted Supabase Postgres.** SQLite remains a first-class,
  fully-tested second backend. Raw lap blobs do **not** move — they stay on
  local disk beside the machine that imported them.

  **What this refines, named explicitly (CLAUDE.md decision discipline):**

  1. **Philosophy #8** — "Personal instrument, not a product. Local CLI,
     **SQLite**, static reports. **No server**." Refined a second time, after
     A17. What changes is only *where the queryable rows live*. What survives,
     unchanged: this is still **one driver's instrument** — no multi-tenancy,
     no auth layer, no tenant column, no shared deployment, and no API for
     anyone but the owner's own localhost UI. The deterministic engine remains
     the only source of numbers; gates, no-blending and evidence IDs are
     untouched. The store is private and single-tenant, which is why this is
     **not** the A17 productization step: nothing in A17's deferral changes.
     SQLite staying tested is what keeps "local CLI" true rather than
     nostalgic — `--db driverdna.db` works forever, and `git clone && pytest`
     still needs no server and no secrets.
  2. **The v1 out-of-scope list** — "**Hosted sync**" was its first item and is
     hereby removed *for the single-user case only*. Multi-user hosted sync
     (tenant keys, queued ingest, shared deployment) stays out of scope, and
     PROJECT-BRIEF.md's "Scaling" section is corrected to say so.
  3. **Philosophy #6** ("The tool compounds; persistence is core") — refined
     honestly in both directions. The record gains off-machine durability and
     reach from more than one machine; it *loses* the guaranteed availability
     of a local file, because a free-tier project pauses after 7 days idle and
     has no point-in-time recovery. The mitigations are part of the amendment,
     not an afterthought: SQLite stays a supported backend, and
     `driverdna store-copy --from <url> --to <path>` is the backup path, with
     the round trip covered by a test.
  4. **Philosophy #9** ("Designed to be distrusted") is *satisfied*, not
     refined: backend equivalence is a test, not a claim. The same fixture
     corpus imported into either backend produces byte-identical metrics,
     attribution, incidents, coaching and driver-model artifacts.

  **Two silent-corruption risks were identified up front and are now
  mechanically guarded**, because both produce wrong numbers rather than
  errors:

  - SQLite's `REAL` is an 8-byte double; Postgres's `REAL` is 4-byte float4.
    A literal DDL copy would have quietly rounded every metric, phase time,
    GPS coordinate and score to ~7 significant digits. All 20 columns map to
    `DOUBLE PRECISION`; a test fails on any float4 column in the schema.
  - Postgres orders text by the database collation. On a Supabase cluster
    (`en_US.UTF-8`) `MX-5` sorts after `MX5` and `gr86` before `GR86` — the
    reverse of SQLite's bytewise order, verified directly against ICU. Every
    report iterates cohorts `ORDER BY driver, car, track`, so this would have
    reordered whole report sections and broken the determinism guarantee.
    Every text column is `COLLATE "C"`; a test fails if one is ever added
    without it.

  **Security is part of the decision, not an implementation detail.** Supabase
  exposes the `public` schema over PostgREST automatically, and the anon key
  granting that access ships in every project — so tables left there would
  publish the driver's telemetry and chat transcripts to an unauthenticated
  endpoint. Tables are created in a `driverdna` schema (not exposed by
  default) **and** carry row-level security with zero policies, which denies
  every role but the owner. Verified behaviourally: a role standing in for
  `anon`, holding an explicit `SELECT` grant on every table, reads zero rows.

  **`DRIVERDNA_DATABASE_URL`** joins `GARAGE61_TOKEN` and `ANTHROPIC_API_KEY`
  as env-only — never persisted, printed, or logged; redacted before any
  connection error reaches a message, a log or an HTTP body. There is
  deliberately no bare `DATABASE_URL` fallback: a generic one left in the
  shell by an unrelated project could silently repoint the instrument at the
  wrong history, which for a longitudinal tool is the worst failure available.

  **Found while doing this, and fixed** (all pre-existing, all invisible on
  SQLite): `corner_positions` had no `ORDER BY` while its dict order decided
  which corner an incident was labelled with; the vs-self tercile split had no
  tie-break while slicing fast/slow groups out of that order; `AND 0` relied
  on SQLite's int-as-boolean coercion on the M6 trend path; and
  `store_incidents` passed numpy int64 sample indices to sqlite3 unadapted, so
  `span_start`/`span_end`/`onset` were stored as BLOBs in INTEGER columns —
  sorting after every integer, and rejected outright by a typed store.
  `store-copy` repairs those rows and *reports* the count; a silent repair
  would itself violate the "nothing silently repaired" rule.

- **A24** (2026-07-26, driver-reported bug): **a second newer Garage61 export
  filename shape, and an independently-optional `--car`/`--track`.**

  Import failed on both surfaces for a lap the owner downloaded from the
  browser:
  `Garage 61 - Benjamin Richards - Ford Mustang GT4 - Summit Point Raceway - 01.27.017 - 01KY31T54KGGQ351PDAGJDTZJM.csv`.
  `parse_garage61_filename` accepted only the 2026-07-21 double-underscore
  shape, so auto-detect returned `None` and `#/upload` raised its 422 before
  the store was opened. Diagnosed first, not guessed: this was initially
  suspected to be fallout from A23's Postgres/blob move, and it was not —
  the rejection happens in a filename-only loop, which an existing test
  already pins (`not db_path.exists()` after rejection).

  **One splitter, parameterized per shape — not one regex per shape.** This is
  the load-bearing choice. `car`/`track` are *cohort keys*, so the same lap
  spelled either way must produce byte-identical strings or the driver's laps
  silently split into two cohorts and every trend, baseline and consistency
  statistic quietly reads from half the evidence. Per-shape lazy regexes
  absorb a surplus delimiter at a different group per shape, which is exactly
  how that divergence would arise; an explicit five-field split has no
  backtracking to diverge. Parity is a test, not a claim
  (`test_both_filename_shapes_give_byte_identical_car_track`, and end-to-end
  in `test_both_filename_shapes_land_in_one_cohort`).

  **A delimiter inside a field is refused, not split on a guess — this
  reaffirms non-negotiable #3 ("insufficient data" over guessing).** With a
  surplus delimiter, car-vs-track is genuinely ambiguous: `Ben - GR86 - Spa -
  Francorchamps` could be car `GR86` / track `Spa - Francorchamps` or car
  `GR86 - Spa` / track `Francorchamps`. Two resolutions were considered and
  rejected — extras-to-track (mirrors the old lazy-regex behavior; a driver
  display name containing ` - ` then yields a wrong cohort with no error) and
  extras-to-driver (a config-suffixed track like `Watkins Glen - Boot` yields
  a wrong cohort with no error). Both put a *wrong value* in the cohort key,
  where it is invisible. Refusal is loud, itemized, and the driver types the
  field instead. Note this also drops one pre-existing behavior: a
  6+-field underscore name used to parse with a garbage `track`; it now
  refuses. That was never a real Garage61 output.

  A browser re-download's ` (1)` suffix is stripped before splitting, so it
  can never enter `lap_id`; the copy then lands as a content-hash duplicate
  at import, which is the honest report — it is the same telemetry under a
  new name. Safari's `-1` form is deliberately not handled: it was not
  observed, and inventing it would guess past the evidence.

  **`--car`/`--track` (and the `#/upload` boxes) become independently
  optional.** Previously `explicit = bool(car and track)` meant a
  single supplied field was silently discarded and the driver was then told
  "car/track not given" while looking at the car they had just typed — so the
  documented manual escape hatch did not actually exist. Now a given field
  applies to every file and a blank one keeps auto-detecting per file, which
  is what makes the hatch real: when Garage61 renames its exports again,
  filling only the box the filename no longer states is enough to keep
  importing. Unresolvable files remain a loud, itemized, nothing-imported
  rejection, now naming *which* field each file is missing. The CLI's
  per-file note reports only what actually came from the filename, so a value
  the driver typed is never echoed back to them as "auto-detected".

  All of this is additive to the locked M0a contract: only filename-derived
  `car`/`track`/`lap_id` widen; no channel, metric, score or artifact changes,
  and the committed fixture reports are byte-identical.

  **Flagged, not fixed here (owner-directed, separate work): blob roots can
  collide between two hosted projects.** `default_blob_root`
  (`blobs.py:131-150`) keys a URL's blob directory on the DSN's last path
  segment, which for *every* Supabase project is literally `postgres`. Two
  projects therefore share `~/.driverdna/blobs/postgres/`, and since `lap_pk`
  restarts per database, lap 1 of one would overwrite and then be served for
  lap 1 of the other — silently returning the wrong telemetry rather than
  erroring. This contradicts `blobs.py`'s own "per-database by construction"
  claim. Harmless with a single project; the workaround today is to set
  `DRIVERDNA_BLOB_ROOT` per project. A real fix keys the root on a hash of
  the full DSN and migrates existing blobs.

- **A25** (2026-07-26, owner-reported): **A24's re-download suffix handling
  was itself an unverified guess, and the guess was wrong.** A24 recorded
  "a browser re-download's ` (1)` suffix is stripped before splitting" as if
  observed; it was not — no re-download had actually happened yet, only a
  space-separated form was assumed by analogy to common desktop conventions.
  The owner's own next re-download, on their own Windows machine, produced
  `...PDABVEREMJ(1).csv` — **no space** before the parenthesis — and
  `parse_garage61_filename` returned `None` for it, reproducing the exact
  "could not resolve car/track" rejection A24 was supposed to have closed.

  `_RE_DOWNLOAD_SUFFIX_RE` widened from `r" \(\d+\)$"` to `r" ?\(\d+\)$"` —
  the leading space is now optional, so both spellings strip cleanly before
  the five-field split. Nothing else about A24's design changes: the suffix
  is still stripped before splitting (never enters `lap_id`), and a
  re-downloaded copy still lands as a content-hash duplicate at import.

  The corrected instinct A24 already stated, misapplied to itself: "store,
  don't depend on the shape persisting... inventing it would be guessing
  past the evidence." A24's own re-download handling was exactly that kind
  of invention, just not caught before it shipped, because no test used real
  observed evidence for that one line — every suffix test at the time used
  the same assumed, unconfirmed spelling. Both spellings are now tested
  explicitly, one labeled as the real observed case
  (`test_new_filename_format_handles_re_download_suffix_without_space`,
  `test_hyphen_filename_shape_handles_re_download_suffix_without_space`) and
  one as the still-unconfirmed original guess, kept only because it costs
  nothing to also accept.

- **A26** (2026-07-26): **`rebuild-map` refuses rather than destroying phase
  times it cannot honestly re-measure.** A23 moved raw blobs onto local disk,
  which created a second, materially different reason `load_lap_arrays`
  returns `None`. `rebuild_cohort_map` did not distinguish them: any
  unreadable trace meant `delete_phase_times`, reported as "blobs were
  evicted past retention".

  Those two causes are not equivalent. **Evicted here** means the raw trace
  is gone for good — nothing, anywhere, can re-measure that lap, so clearing
  its stale phase times is the honest act A22 specified. **Absent here** means
  the lap was imported on another machine and its trace is intact there;
  clearing is then an unrecoverable local loss of a measurement that machine
  can still reproduce, *and* the reported reason is false. `blobs.py`'s own
  docstring asserted every caller "degrades honestly" on a missing blob and
  listed "the pipeline skips re-measurement" — for this caller it did not
  skip, it deleted.

  **Eviction now leaves a tombstone** (`<lap_pk>.evicted`) in the blob store,
  written by `enforce_retention` beside the blob it removes. The tombstone
  lives in the blob store, not the database, because eviction is a
  *per-machine* event while the database may be shared between machines — a
  column would say "evicted" to a machine that had simply never held the
  blob. Rejected alternative: infer the distinction from
  `config.retention.raw_laps_per_cohort` (is this lap within the newest N?).
  That breaks whenever retention is lowered and later raised, and it infers a
  fact the system can simply record.

  `rebuild_cohort_map` now runs a **pre-flight before mutating anything** and
  raises `RawTracesUnavailable` when any observed lap's trace is missing
  without a tombstone. Refusing beats the alternatives: clearing destroys
  recoverable data, and skipping-without-clearing would leave the cohort with
  some phase times measured against new windows and some against retired ones
  — the silent mixing A22 exists to prevent. `--allow-missing-traces` proceeds
  deliberately, and the cleared-reason wording now follows which case applied.

  Refines philosophy #7 (nothing silently repaired) in the direction it
  already pointed: a destructive step must know *why* the data it is
  destroying is missing, not merely that it is.

  **Note for existing installs**: laps evicted before this amendment have no
  tombstone, so the first `rebuild-map` after upgrading may refuse and name
  them. That is the safe direction — a false refusal costs one flag, a false
  "evicted" costs the measurements. Deliberately not backfilled: on a shared
  store the backfill would have to run from some machine, and every lap absent
  *there* would be marked evicted *everywhere*.

- **A27** (2026-07-26): **cohort-label drift is detected and reported, never
  merged.** `car`/`track` are cohort keys, and every longitudinal number —
  baselines, the vs-self ranker, M6 trend, consistency — is computed per
  cohort. Two labels for one real cohort therefore halve the evidence behind
  every one of them while raising nothing.

  The exposure is structural, not hypothetical. `sync` builds its track label
  from the API's `name` + `variant` (`garage61/sync.py:_track_label` →
  "Summit Point Raceway (Shenandoah)"); a manual import takes the export
  filename's label, which carries no variant. Doing both — at the time, the
  documented workflow, since `/laps` was believed to return only one lap per
  cohort (A24, M0b; **that premise was wrong — see A28**) — splits the
  cohort. A28 removes the *need* to mix the two paths but not the ability to,
  so this detector remains load-bearing.

  `cohorts.find_label_drift` flags two signatures: labels differing only by
  case/punctuation, and labels differing by one naming a parenthesised
  variant where the other names none. Surfaced by `driverdna history` and, more
  usefully, at the end of `driverdna import` — the moment a divergent label is
  actually created, when the fix still costs one re-import.

  **Two different variants are deliberately not flagged**: "track variants are
  distinct cohorts" is this spec's own rule, so `(Main)` vs `(Shenandoah)` is
  correct behavior. A warning that fired on legitimate cohorts would train the
  driver to ignore the one that matters, so the false-negative direction was
  chosen over the false-positive one, and both directions are tested.

  **Reported, never repaired.** Which label is right — or whether two are
  genuinely different configurations — is not derivable from the strings, and
  a cohort key is load-bearing for evidence IDs, so an automatic merge would
  risk exactly the quiet corruption this project refuses. The remedy is a
  re-import under the intended label, chosen by the driver. This is
  "insufficient data over guessing" applied to metadata rather than
  measurements.

- **A28** (2026-07-27): **`/laps` was never a personal-best endpoint — M0b
  measured a default, not a shape.** The `group` parameter defaults to
  `driver` ("Personal best laps per driver"); `group=none` returns all laps.
  Sync now sends `group=none`, and the per-cohort lap ceiling that shaped
  three prior decisions is gone.

  **How the error happened, because that matters more than the fix.** M0b
  probed the live API carefully and found the right *fact*: every driver in
  two independently-checked cohorts (30 and 66 drivers) had exactly one lap,
  no exceptions. It then ruled out the plan-cap hypothesis, correctly, and
  concluded the remaining explanation was the endpoint's fixed shape. That
  step was the mistake: "universal across accounts" rules out an
  account-specific cause, not a *parameter default*, which is equally
  universal and equally invisible to a probe that never varies it. The census
  was sound; the inference from it was not. The doc then hardened the guess
  into "not something a different plan or more API calls can pull around" —
  a claim about what cannot exist, drawn from evidence that only showed what
  a default does.

  The reachable ground truth was the OpenAPI document at
  `https://garage61.net/api/openapi/v1.json`. M0b recorded the endpoint
  reference as unreachable ("a JS-rendered SPA not reachable by this
  session's fetch tooling") and stopped there; the SPA in fact fetches that
  JSON, and the URL is a plain string in its bundle. **Standing lesson: when
  a documentation site is unreadable, the site's own data source usually is
  not** — read the client before concluding the docs are unavailable. A
  Garage61 engineer (Alex) supplied the `group=none` pointer by email, which
  is what prompted the re-check; the spec then confirmed it and much more.

  **What the spec settles that M0b listed as unconfirmed:** `limit`'s ceiling
  and default are both 1000; the real date filters are `after` (RFC3339) and
  `age` (days, or negative for seasons) — not the `start`/`end` M0b guessed
  and watched silently no-op; `drivers`/`teams`/`extraDrivers` scope the
  search server-side, with `drivers=me` for own laps; `lapTypes` already
  defaults to normal (full) laps, which is what M0a's single-lap contract
  needs; `cars` accepts negative IDs for car *categories*.

  **Decisions this reverses or narrows.** The "dated manual import" path
  (2026-07-21) exists *because* per-cohort trend was thought unreachable via
  the API. It stays — it is the only path for pre-API history and for laps
  Garage61 never held — but it is no longer the only way to get a real
  per-cohort trend. A27's cohort-label drift detector stays for the same
  reason: mixing paths is now avoidable, not impossible.

  **Unclean laps are requested (`unclean=true`), not filtered.** A19 made a
  spin or an off a measurement rather than a disqualification; accepting the
  API's clean-only default would have quietly undone that on the sync path,
  leaving the incident subsystem structurally unable to see the laps it was
  built for. Laps whose telemetry is genuinely unusable (`missing`,
  `incomplete`) are still dropped — but locally, on the lap's own flags,
  after seeing it. `--clean-only` opts out. Owner-confirmed 2026-07-27.

  **Two guards, because this amendment is spec-sourced and not live-verified
  (no `GARAGE61_TOKEN` in the session that wrote it).** This is the A24/A25
  lesson applied pre-emptively rather than after a correction:

  1. `drivers=me` is an optimisation, never a trust boundary. The
     client-side `driver.id == /me` filter is kept unconditionally, because
     reference-lap isolation is a non-negotiable and this API silently
     ignores query names it does not recognise — a rename would degrade
     "scope to me" into "all drivers" with no error. `LapListing.foreign_rows`
     counts other-driver rows that came back anyway, so whether the
     server-side scope applied is *reported from the response*, not assumed.
  2. Telemetry access is checked per lap, not hoped for. `seeTelemetry` is
     documented as requiring a Pro plan and the owner's account is free, so
     whether non-PB laps expose CSV at all is genuinely unknown. Each lap
     carries `canViewTelemetry`; sync skips an explicit `false` and reports
     the count, instead of spending a call to collect a 403. An *absent*
     field is not read as denial — that would silently drop importable laps.

  **No automatic sync watermark.** `after` filters on when a lap was
  *driven*, not when it was synced, so deriving it from
  `garage61_sync_state.last_synced_at` would permanently skip any lap driven
  before the last sync but uploaded after it. Re-listing a cohort in full is
  cheap (an already-synced lap never costs a CSV fetch); silently missing a
  lap is not. `--after`/`--max-age-days` stay driver-supplied, and `--after`
  is validated and normalised to RFC3339 locally, since a value this API
  cannot parse would become an unbounded backfill rather than an error.

- **A29** (2026-07-27, owner-directed): **the build rules become portable, and
  CI becomes a real gate, because more than one agent now works on this
  repository.** The owner uses Gemini CLI and Google Antigravity during Claude
  Code usage-limit windows, with unrestricted scope.

  **Refines philosophy #8** ("personal instrument, not a product — simplicity
  and auditability outrank generality"), named here per the decision-discipline
  rule. A multi-agent working agreement is process surface #8 would normally
  argue against. It earns its place on *auditability*: the risk being managed
  is a second model violating an invariant while writing plausible-looking
  code, and the answer chosen is the same one #9 ("designed to be distrusted")
  already prescribes — mechanical enforcement, not more prose. Still one
  driver's instrument, one owner, one repository; no collaboration workflow
  beyond what a single owner switching tools requires.

  **`AGENTS.md` is the single source of the build rules** (non-negotiables,
  decision discipline, build order, commands, testing rules, working
  agreement). It exists as a separate file for a concrete reason: Antigravity
  silently refuses a rules file over 12,000 characters and `CLAUDE.md` was
  25,908. `CLAUDE.md` now imports it via `@AGENTS.md` and keeps only its
  "Current status" changelog and UI-layer notes; `.gemini/settings.json` sets
  `context.fileName` so Gemini CLI loads it; `.agents/rules/driverdna.md`
  mirrors the non-negotiables for Antigravity, whose docs do not promise that a
  root `AGENTS.md` is read at all.

  **The one duplication is pinned, not trusted.** That mirrored block is
  delimited by `shared:non-negotiables` markers and asserted byte-identical by
  `tests/test_agent_contract.py` — the same reasoning as the `ui/tokens.json` ↔
  `report/builder.py` `_TOKENS` parity test. The same file also fails if
  `AGENTS.md` outgrows the 12,000-character cap, if `.gemini/settings.json`
  stops naming `AGENTS.md`, or if `CLAUDE.md` restates the rules instead of
  importing them. Both failure modes were induced deliberately and observed to
  fail before the file was accepted.

  **`.github/workflows/tests.yml` runs the suite on every push and on pull
  requests to `main`**, across Python 3.11 and 3.12, with a Postgres service
  container wired to `DRIVERDNA_TEST_DATABASE_URL` so the dual-backend tests
  execute rather than skip. Until now there was no test CI at all: every
  invariant in this project is enforced by pytest and nothing else — no linter,
  no formatter, no type checker — and nothing ran it on push.

  **Resolved (2026-08-03):** A separate `browser-tests` job now installs
  Chromium via Playwright, builds the SPA, and runs the six Chromium-gated test
  files (`test_render_parity`, `test_offline`, `test_upload_ui`, `test_auth_ui`,
  `test_cockpit_ui`, `test_score_history_ui`). Non-blocking
  (`continue-on-error: true`): a failure is visible but does not block merges,
  so the main gate stays green-by-default. A follow-up "Confirm browser tests
  actually ran" step fails the job if the skip guard still triggers despite the
  install — silent coverage loss was the original gap, and this closes it.

  **Branch discipline:** Claude Code continues to commit directly to `main`
  (the 2026-07-21 owner instruction stands); Gemini CLI and Antigravity work on
  `gemini/*` and `antigravity/*` branches and merge only on green CI. Known
  asymmetry, recorded rather than worked around: CI gates merges, so a direct
  push to `main` can still break it and a branch cut afterwards inherits the
  breakage — push-triggered CI makes that visible within a minute rather than
  preventing it.

  **Also fixed here:** `.github/workflows/gemini-assistant.yml` had never
  worked. It pinned `google-github-actions/run-gemini-cli@v1`, and no `v1` tag
  exists — the action is pre-1.0 (latest `v0.1.22`). Its only run, the owner's
  issue #4, failed in six seconds with `Unable to resolve action ... unable to
  find version 'v1'`, which is why nothing ever replied. Repinned to the exact
  version (not the `v0` major, which still accepts breaking changes) and gated
  on `github.event.sender.login == github.repository_owner`, since the job
  holds `contents: write`.

- **A30** (2026-07-27): **free-plan non-PB laps 404 on CSV fetch — observed
  live, `sync` now handles gracefully.** A real `sync` with `group=none`
  (A28) listed ~928 laps across 9 cohorts. A substantial share of non-PB
  laps return 404 on `/laps/{id}/csv` despite appearing in the listing
  without `canViewTelemetry: false`. This is distinct from the Pro-only
  `seeTelemetry` gate: Garage61 does not store telemetry for every lap on a
  free plan. `sync.py` now catches `Garage61NotFoundError` (404) and
  `Garage61ForbiddenError` (403) on CSV fetch, records them separately in
  `CohortSync` (`laps_csv_not_found`, `laps_csv_forbidden`), and continues
  importing remaining laps. Auth errors (401) and server errors (500) still
  abort immediately — the guard catches only per-lap fetch failures.

  Resolves the open question flagged in A28's capabilities summary ("whether
  a free plan can fetch CSV for non-PB laps at all"). Documented in
  `docs/garage61-api.md`, which is updated with the live observation.

- **A31** (2026-07-27): **single-driver auth is built — philosophy #8's "no
  auth layer" clause is retired, and its "one driver" clause is not.**

  **Principle refined, named here as the decision discipline requires:**
  philosophy #8, *"Personal instrument, not a product."* Its A23 refinement
  still reads "no multi-tenancy, **no auth layer**, no API for anyone but the
  owner's own localhost UI." Two of those three are now false in different
  ways, and the difference is the whole point:

  - *"No auth layer"* is **retired**. It was true when the only listener was
    `127.0.0.1`. The Cloud Run deployment made it false-by-omission rather
    than false-by-decision — the app was reachable over a hostname with no
    application-level authentication whatsoever, held up only by Cloud Run's
    `--no-allow-unauthenticated` IAM flag. A lock is now what makes "one
    driver's instrument" true off-loopback, so the clause is refined rather
    than merely deleted.
  - *"No multi-tenancy"* is **untouched and reaffirmed**. There is no user
    table, no registration, no tenant column, no second identity, and no
    password reset. `laps.driver` remains a data label unrelated to who is
    signed in. This amendment is explicitly **not** precedent for multi-user,
    exactly as A23 said of itself.

  **What was built** (docs/DEPLOY-SPEC.md track H1, designed and adopted
  2026-07-26, unimplemented until now): `DRIVERDNA_ACCESS_TOKEN` — env-only,
  same non-negotiable as every other secret — exchanged at
  `POST /api/auth/login` for a signed, expiring, HttpOnly/SameSite=Lax
  cookie; `hmac.compare_digest`; one app-level FastAPI dependency guarding
  every route; `POST /api/auth/logout`, `GET /api/auth/status`; a
  fail-closed `--host` interlock refusing a non-loopback bind with no
  passphrase configured; write-path hardening (per-file upload cap, CSV type
  check, `/api/chat/*` rate limit, `no-store` on every API response).

  **Stdlib only, and that is a design constraint rather than a preference.**
  An identity provider (Auth0, Clerk, Firebase, Supabase Auth) is
  mechanically excluded from the browser by two existing tests, not by
  taste: `tests/test_ui_static.py` asserts the built bundle contains no
  `https://` (it fails in CI, with no browser), and `tests/test_offline.py`
  aborts every non-same-origin browser request. A server-side OIDC flow
  could satisfy both, and was rejected on cost/benefit: for one driver it
  buys MFA in exchange for a vendor, a dependency, a redirect URI pinned to
  a hostname, and a user model this very amendment forbids. Because the
  chosen scheme adds no third-party origin at either the browser or the
  process level, **UI-SPEC trust gates 5a and 5b are untouched** — no gate
  wording is weakened by this change.

  **No numbers move.** Nothing here touches a metric, a score, a threshold
  default, or a model version. Two new config sections (`auth`, `api`) hold
  session and serving policy only; the passphrase is never among them.

  **Auth is off when no passphrase is configured**, which is what keeps the
  local loopback instrument identical to before and let every pre-existing
  test pass unmodified — the mechanical proof that this is additive.

  Full record: PROJECT-BRIEF.md's decision log, dated. Deployment
  consequence flagged there and in DEPLOY-SPEC: `Dockerfile` binds
  `0.0.0.0`, so the Cloud Run service now requires `DRIVERDNA_ACCESS_TOKEN`
  in its environment or it will refuse to start — the interlock working as
  designed, and a sequencing hazard if merged before the secret is set.

- **A32** (2026-07-28): **Multi-tenancy and Productization.**
  **Principle refined:** philosophy #8 ("no multi-tenancy", overriding A31).
  The owner has explicitly directed the system to support multi-user accounts
  and SaaS productization, dropping the strict "one driver's instrument" rule.
  
  **What was built:** A new `users` table, row-level `owner_user_pk`
  partitioning on all data structures, a password reset SMTP flow, and a
  Google OAuth flow. UI-SPEC trust gate 5b is amended to permit outbound
  network calls for SMTP (`smtp.sendgrid.net`) and Google OAuth endpoints.
  Trust gate 5a remains untouched, ensuring telemetry blobs are only fetched
  from trusted domains. Data remains fully isolated per user, and deterministic
  measurements remain strictly independent per account.

  > **Corrected by A53 (2026-08-18) — read that before relying on this entry.**
  > Two things above are not accurate as written. (1) "Principle *refined*"
  > should read **reversed by owner decision**, per ACCOUNTS-SPEC:37-41.
  > (2) "Data remains fully isolated per user" was not true when written and is
  > not true now: `finding_annotations` was never partitioned, config is
  > instance-wide, and `/api/sync` can serve one user the owner's laps. A53
  > carries the audit, with file:line evidence, and the beta direction adopted
  > in response.

- **A33** (2026-08-02): **`driverdna census` — the corpus answers "do I need
  more laps?" itself.** Asked whether more lap data would help validate the
  engine, answering it meant hand-reading `reports_hosted/driver.json` and
  re-deriving the confidence formula by hand. That is a question the store can
  answer, so it now does.

  **No principle is refined and no number moves.** Census applies no gate of
  its own: every threshold is read from `DriverDNAConfig`, and every
  suppression reason is the *exact string the engine emitted*, read back off
  `build_cohort_payload`'s findings and `build_driver_payload`'s rollups.
  Paraphrasing them was rejected deliberately — a census that explains a
  suppression in its own words can drift from the real gate and report a
  corpus as ready when it is not. Two tests pin the quoted strings against the
  payload rather than against literals.

  **The one refactor**, `model/scoring.py`: `_confidence` computed its four
  ratios inline, and census needs them individually. `confidence_terms()` now
  returns `(label, have, floor)` per term and `_confidence` is the mean of
  their ratios plus the unchanged proxy cap. Number-neutral, and proven so
  rather than asserted: `tests/test_scoring.py` passes unmodified, a test
  asserts `_confidence` equals the mean of the exposed terms, and all six
  committed `docs/*-report.md` artifacts regenerate **byte-identical** from
  the real fixtures.

  **Where it refuses to guess.** Closing a corpus-level term
  (sessions/tracks/cars) moves that term by an amount identical for every
  fundamental, so census states the gain as a number. How much a new lap
  raises `evidence_count` depends on which corners and metrics that lap
  actually produces, so census states the shortfall and prints `—` instead of
  projecting — philosophy #2 ("insufficient data over guessing") applied to
  census's own output. It also distinguishes suppressions that more laps
  *will* clear (sample/track counts) from those they will not ("no effect",
  "below pattern floor"), so the report cannot be read as "more laps fixes
  everything".

  **First real-fixture run** (`docs/census-report.md`, 12 laps / 2 cohorts):
  confidence ceiling 60.2%, and **15 of 177 findings shown** — 75 of them
  blocked by `insufficient data: 1 phase samples < 10`, which is the
  single-lap Mustang/Laguna Seca cohort. The dominant blocker is a cohort with
  one lap in it, not the engine.

  **Known cost, accepted:** census calls `build_cohort_payload` per cohort to
  quote real suppression reasons, so it recomputes what `report` computes —
  the price of quoting the engine instead of paraphrasing it, and the same
  full-recomputation shape `metrics`/`model`/`coaching` already have. Not yet
  measured on a corpus of hundreds of laps; if it becomes slow there, that is
  a real observation to record rather than something to pre-optimize.

  **Deliberately out of scope:** no UI surface (UI-SPEC.md is not amended);
  the data/render split in `census.py` makes a later payload section cheap.
  The corner-map admission gate (`identity.min_laps_for_admission`) is not
  reported — there is no read-only pending-candidate query, and adding one was
  scope the question did not ask for.

- **A34** (2026-08-03): **Reference laps never define the driver's own
  geometry.** The non-negotiable is "reference laps never enter self history,
  trends, or consistency statistics", and the *measurement* layer has honoured
  it since M2 — every history/metric/detector/class query filters
  `role='self'`. The **corner map** did not, and the corner map is the
  coordinate system those measurements are taken in: a corner's centroid
  decides which observations belong to it, and its frozen phase windows decide
  where every entry/mid/exit time is measured. Three paths wrote reference
  geometry into it:

  1. **Founding.** The first lap in a cohort *builds* the map
     (`pipeline.import_parsed_lap`). Nothing checked its role, so a reference
     lap imported into an empty cohort founded the whole thing — verified live:
     one reference CSV into an empty store produced 11 corners and 11 canonical
     phase windows, every one of them somebody else's line.
  2. **Admission.** `db.admit_pending_candidates` admits a cluster seen on
     `min_laps_for_admission` distinct laps and takes the new centroid as the
     median of the cluster's apexes. Both counted reference observations, so a
     corner the driver had driven twice and a stranger once entered the map —
     at a position the stranger's apex helped set.
  3. **Rebuild.** A22's in-place refreeze re-derives every centroid
     (`db.corner_apex_positions`) and every window
     (`db.observation_positions`) from the corner's full observation set. Both
     queries were role-agnostic; neither even joined `laps`, so an audit
     looking for an unfiltered `JOIN laps` missed them.

  **Measured consequence**, on the owner's real 6-lap Mustang GT4 @ Spa cohort
  with one reference lap (10.73 s faster, same car, same track). Rebuilding a
  clean copy and a with-reference copy and diffing: **11 of 14 corners moved**
  (largest 46.94 m at C08), **11 of 14 phase windows differed**, and **154 of
  the owner's own 191 phase times changed** — up to **1.57 s**, C08 moving that
  much of a lap from `mid` into `exit`. Driver Model scores followed
  (`corner_exit` 67.5 → 67.4, `rotation` 61.6 → 61.1). On the older GR86/Spa
  fixture cohort the admission path alone moved `consistency` 34.31 → 32.26.

  **Why the existing test missed it.**
  `test_reference_import_perturbs_gap_sections_only` (M3, trust gate 3) is
  exactly the right test and passes honestly — its synthetic reference lap
  matches corners that already exist, so the admission path never runs and the
  test never rebuilds. The guarantee was pinned one layer above where it broke.

  **Fix.** `import_parsed_lap` raises `ReferenceCannotFoundMap` *before* the
  lap row is written when a reference lap would be its cohort's first;
  `admit_pending_candidates` counts distinct laps and takes its centroid over
  self observations only; `corner_apex_positions` and `observation_positions`
  filter `role='self'`. **Isolation is not exclusion**: reference observations
  are still clustered, still linked to the corner they belong to, and still
  measured — that is what a gap is made of. They just never vote on where a
  corner is. Both import surfaces refuse up front and itemized, nothing
  partially imported (`driverdna import` exits 2; `POST /api/laps/upload`
  returns 422, and on a cold start refuses before the store is created so a
  rejected upload leaves no database behind).

  **No principle is refined** — this restores a non-negotiable that was already
  written down, one level below where it had been enforced. **No committed
  number moves**: all seven `docs/*-report.md` artifacts regenerate
  byte-identical, because both committed fixture manifests contain zero
  reference laps. That is also the blast radius: no committed corner map was
  ever influenced, and the owner's live store has never held a reference lap.
  After the fix, the same real GT4 experiment gives corner centroids, phase
  windows, all 191 self phase times and the Driver Model **identical** with and
  without the reference lap, while the reference lap keeps its 31 phase times
  and its 30 vs-reference gap findings.

  **Flagged, not silently accepted:** a cohort founded by a reference lap
  *before* this fix keeps its stranger-built map — the refusal is a guard on
  new imports, not a repair. Such a cohort cannot be detected from the rows
  alone (the map records no founding role), so nothing is auto-repaired;
  `rebuild-map` now re-derives that cohort's geometry self-only, which is the
  recovery path. No such cohort is known to exist.

- **A35** (2026-07-29, owner-directed): **Design language v3 ("cockpit
  feel").** A presentation amendment to UI-SPEC's "Design language v2"
  section, which currently declares all eleven token colours and the motion
  rule untouched — v3 changes four things there and nothing else, and none
  of them touch a measurement:

  1. **Palette** — new **chrome-only** accent tokens may be added to
     `ui/tokens.json`. The three colour-grammar rules stand verbatim:
     semantic colours (purple/green/amber/red) keep their exclusive
     meanings, red still never means driver pace, source identity stays
     structural. A new accent may never encode a measurement — legal on the
     wordmark, active-tab underline, hover/press states, disclosure
     chevrons, empty-state ribbons; illegal on any figure, bar, chart
     series, tile value, or finding row.
  2. **Motion** — v2's "≤150 ms, functional only" extends to
     interactive-feedback micro-motion ≤180 ms (press, hover, disclosure
     open/close, tab underline). Still no data-entrance animation, no chart
     animation, `prefers-reduced-motion` still fully honored.
  3. **Copy** — two new, tightly bounded registers: a **methodology
     register** (explanatory prose, allowed only inside a collapsed
     disclosure) and a **newcomer register** (one short empathetic line,
     incidents only, inside the disclosure, never attached to a number).
     v2's "labels not paragraphs" rule continues to bind the default render.
  4. **Progressive disclosure is not suppression.** Binding: the headline
     number, its `n`, and any `gate_reason` stay visible uncollapsed — only
     derivation detail and methodology may collapse, behind a visible,
     keyboard-reachable, labelled control. UI-SPEC decision 7 (suppression
     is visible, with its reason and progress) is unchanged.

  Full record: `docs/UI-V3-PLAN.md`, `docs/PROJECT-BRIEF.md` decision log.

- **A36** (2026-07-29): **Score history (`dm-hist-v1`).** A new
  deterministic engine output: each Driver Model fundamental's own score
  over N contiguous date-ordered buckets of the driver's dated laps, from
  the same `_bucket_score` machinery `trend` (M6) already uses. **Produces
  no new kind of number** — no formula changes, no weight moves, so
  `dm-v2`'s scoring model version is *not* bumped; only a new
  `series_version` (`dm-hist-v1`) is introduced for the series shape
  itself. Carries verbatim the two limitations `_trend` already documents
  (era-relative opportunity baseline; cross-cohort bucket composition when
  dated laps are thin-per-cohort) — a chart makes them more visible, not
  less true. Binding: a bucket with no scorable evidence is a null with a
  stated reason and renders as a gap, never interpolated, and no line is
  drawn across it. Full record: `docs/UI-V3-PLAN.md`.

- **A37** (2026-07-29, owner-directed): **Per-user AI keys (BYOK).**
  Investigated first: the owner's original ask — "users logged into their
  own Google accounts use their own Gemini usage" — is not available to
  third-party apps. Google AI Pro/Ultra are chat subscriptions with no API
  access; Gemini API quota and billing always follow the Cloud project
  behind the key, never the signed-in user; and Google states that
  piggybacking Gemini CLI's OAuth to reach its backend services is a terms
  violation and grounds for account suspension, naming an AI Studio or
  Vertex API key as the supported third-party path. The owner's resolution:
  a user may supply their own free AI Studio key, used only for that
  account's coach/chat calls, falling back to a server-wide
  `GEMINI_API_KEY` when unset.

  **This reverses two written rules, and says so rather than eliding it:**
  - `AGENTS.md`'s non-negotiable *"secrets are env-only: never persisted,
    printed, or logged"* is **refined**: a *user-supplied provider key* may
    now be persisted, encrypted at rest, scoped to one account. Every
    server-side secret (`GARAGE61_TOKEN`, `ANTHROPIC_API_KEY`,
    `GEMINI_API_KEY`, `DRIVERDNA_DATABASE_URL`, `DRIVERDNA_SESSION_SECRET`)
    stays env-only, unchanged, never printed, never logged, never returned
    by any endpoint.
  - UI-SPEC U6 condition 4 *"secrets never transit the browser"* is
    **narrowed**: that rule was written about `GARAGE61_TOKEN` — a
    server-side credential the UI must never ask for — and it stands for
    every server-side secret. A user's own provider key is by definition
    supplied by that user and can only arrive through their browser, over
    HTTPS, once, write-only; it is never sent back by any read endpoint.

  Full record: `docs/UI-V3-PLAN.md`, `docs/PROJECT-BRIEF.md` decision log.

- **A38** (2026-08-02): **Track C3 live Gemini acceptance run — two real
  defects found and fixed, never by loosening the validator.** Run against
  the real fixture cohort (`GR86:Spa-Francorchamps`, 11 laps) with a live
  `GEMINI_API_KEY` supplied by the owner for this run only (rotated
  immediately after, per the owner's own instruction — never persisted,
  never committed).
  1. **`coach.max_tokens` default (4000) was silently broken for the
     default provider.** `gemini-3.5-flash` is a thinking model whose
     internal reasoning tokens are drawn from the same budget as
     `max_output_tokens`; a real coach/chat payload exhausted 4000 tokens
     on thinking alone, returning `finish_reason=MAX_TOKENS` with **empty**
     response text — which the grounding validator correctly rejected as
     "not valid JSON," but for the wrong underlying reason (a token-budget
     bug presenting as a grounding failure). Fixed: default raised to
     16000 (`config.py`), harmless for Claude, which simply uses less of
     the budget than it's given.
  2. **`coach`'s `SYSTEM_PROMPT` had two real compliance ambiguities**,
     invisible against Claude but hit reliably by Gemini across 5/5 raw
     attempts: (a) the no_signal principle's "never attach a confidence
     value, at any level" instruction was general enough that Gemini
     applied it to ordinary `hypotheses[]` entries too, emitting
     `confidence: null` where the schema requires low/medium/high; (b)
     nothing told the model that an `incident_explanations[]` entry must
     cite its own `incident_id` inside its own `evidence_ids` — an
     unusual, easy-to-miss convention. Both are now stated explicitly and
     scoped precisely in the prompt (`coach/provider.py`); `PROMPT_VERSION`
     bumped `coach-v2` → `coach-v3` (no schema change, no validator change
     — wording only, so no schema-version bump). **The validator itself was
     never touched** — same absolute rule as everywhere else in this repo;
     fixing the model's inputs is always in bounds, fixing the gate to
     tolerate a wrong answer never is.
  Result after both fixes: **2/2** live `driverdna coach` runs against
  Gemini passed the strict validator unmodified on the first attempt
  (before the fixes: 0/5). One live grounded chat turn through
  `GeminiChatProvider` (the primary interactive surface, which already had
  chat's regenerate-once loop and needed no prompt change) also passed,
  citing real `obs:<n>` evidence. Full detail: `docs/STATUS.md`'s
  2026-08-02 snapshot.

- **A39** (2026-08-03): **Reference laps R2 (identity/depth) + R3
  (curation) — built.** `docs/REFERENCE-LAPS.md`'s R-track picks up where R1
  (visibility) left off: the pool is now inspectable (who's in it, how
  many, what envelope they add up to) and manageable (a bad import can be
  retired without deleting it). Six open decisions, all owner-confirmed
  before any code was written (not picked silently):
  1. **No `ref_label` column.** The existing `laps.driver` column (already
     populated at import, and settable per lap via `--driver`/manifest
     `driver` on the CLI path) is sufficient identity — no schema change.
  2. **One aggregated envelope, not split per contributor.** Matches the
     design doc's own stated default: findings don't multiply, a mixed-skill
     reference pool honestly reads as a wider envelope.
  3. **Corner drill: overlay, not a separate section or side-by-side.**
     Reference n/median/best ride as three extra columns on the *same*
     phase-times table row, never blended into the self numbers they sit
     beside (source separability, SPEC.md decision 3, preserved by column
     separation rather than by physical separation).
  4. **Curation: Option A** — an exclusion flag through the audited-
     annotations pattern (reversible, upserts in place, never deletes the
     lap or its measurements), not Option B (no mechanism).
  5. **Toggle location: cohort view + CLI**, both wrapping one DB-layer
     write path.
  6. **Cascade: immediate.** No caching layer exists for payloads —
     `build_cohort_payload` already reads current DB state on every call, so
     excluding a lap is visible on the very next fetch with no rebuild step.

  **What got built, mapped to those decisions:**
  - **Schema** (`db.py`, migration 015): `reference_exclusions` table
    (`owner_user_pk`, `lap_pk`, `note`, `created_at`, `UNIQUE(owner_user_pk,
    lap_pk)`) — the audited-annotations pattern (`finding_annotations`,
    migration 001) applied to a lap instead of a finding. `owner_user_pk`
    follows `user_api_keys`' (014) shape rather than `finding_annotations`'
    own (001, predates Data Partitioning): every table created after
    migration 009 scopes itself per account directly.
  - **Exclusion enforced once, at the query surface.** `db.phase_history`
    filters out any `reference_exclusions` row when `role='reference'` — the
    exact discipline role isolation itself already uses (A34: "enforced at
    the query surface, not in callers"). Consequence: `attribution/
    ranker.py`'s `vs_reference_findings` and the new corner-drill endpoint
    needed **zero code changes** to honour curation — both already read
    through `phase_history`. A dedicated test
    (`test_vs_reference_envelope_recomputes_without_an_excluded_lap`) proves
    this by excluding a lap and re-running the unmodified ranker function
    directly, then proves reversibility by re-including it and diffing the
    findings list back to byte-identical.
  - **Payload** (`report/payload.py`): a new `references` section on
    `build_cohort_payload` (`PAYLOAD_VERSION` 4→5) —
    `{n, n_excluded, envelope, contributors}`. `envelope` reuses
    `attribution.engine.reference_envelope` (already built for per-corner
    phase times) over whole-*lap* `duration_s` instead — no new statistic,
    same function, a different input array. Excluded laps stay in
    `contributors`, flagged, never dropped — curation marks, it never
    hides, same contract as an annotated finding.
  - **API** (`ui/api.py`): `GET /api/cohorts/{slug}/corners/{corner_id}/
    reference-phases` (mirrors the existing metric-distribution endpoint,
    per-phase `{n, median_s, best_s}` via `phase_history` +
    `reference_envelope`); `POST`/`DELETE /api/laps/{lap_pk}/exclude`
    (mirrors `/api/findings/{id}/annotate` exactly — 404 on an unknown or
    non-reference lap_pk, 404 on un-excluding a lap that isn't excluded,
    same "reversible, never silent" discipline as `clear_annotation`).
  - **CLI** (`cli.py`): `exclude-reference LAP_PK [--note]` /
    `include-reference LAP_PK`, thin wrappers over the same DB methods the
    API uses, `typer.Exit(2)` on the same validation failures.
  - **UI** (`cohort.jsx`, `corner.jsx`): the References panel now states the
    envelope, lists each contributor (driver + lap time), and gives each an
    Exclude/Include button (same `act()`-then-reload idiom `finding.jsx`'s
    annotate buttons already use); an all-excluded pool gets its own honest
    state ("N on record, all currently excluded — no envelope until one is
    re-included"), distinct from the true empty state. The corner drill's
    phase-times table gained the three overlay columns.

  **A gap found and closed while wiring identity through, not part of the
  original ask:** `POST /api/laps/upload` hardcoded `driver="owner"` for
  every uploaded lap, self or reference — decision 1 ("the driver column is
  sufficient identity") would have been only half true, since the browser
  upload path (`#/upload`, one of the two documented reference-lap
  ingestion routes per `docs/REFERENCE-LAPS.md`) could never actually *set*
  a distinguishing name. Fixed with one optional `driver` form field
  (defaults to `"owner"` when blank, so every existing self-upload behaves
  identically) and one conditional input in `upload.jsx`, shown only when
  role is reference — self uploads in this single-driver instrument have no
  use for it. `driverdna import --driver`/manifest `driver` already covered
  the CLI path; this closes the same gap on the other documented ingestion
  surface.

  **Verification.** New file `tests/test_reference_curation.py` (DB methods,
  payload section, ranker-integration, CLI — 19 tests); new API/upload tests
  appended to `tests/test_api.py` and `tests/test_upload_api.py` (7 tests);
  a dedicated Playwright suite, `tests/test_reference_curation_ui.py` (3
  tests, its own isolated DB — never the shared `tests/fixtures/` render-
  parity DB, which stays at zero reference laps by design): the cohort page
  renders the envelope and contributor identity from a real imported
  reference lap, the Exclude/Include buttons update the page live with no
  reload, and the corner drill's overlay columns render real values for a
  corner the one reference lap actually measured. `tests/test_blobs.py`'s
  `_v5_database_with_inline_blobs` helper (which manually rewinds specific
  tables to simulate an old database) needed one line added — drop
  `reference_exclusions` alongside the other post-006 tables it already
  drops — the same maintenance every migration since 008 has required
  there, not a workaround.

  **No committed number moved**: nothing here touches self history, trends,
  classes, consistency, incidents, or the Driver Model, and both committed
  fixture manifests still hold zero reference laps. Suite 850 → 879 passed
  (0 failed), +29 tests, run before and after.

  **Not done, flagged rather than assumed:** the owner's real synced corpus
  presently holds zero reference laps (`docs/STATUS.md`), so this is
  verified against real fixture telemetry and a real Playwright browser, not
  yet against the owner's own production store — the same "built but never
  fired" gap R0 named for the original feature, one layer up. R4 (deliberate
  reference-geometry adoption) remains untouched and still awaits its own
  separate owner go, unaffected by any of this.

- **A40** (2026-08-05, owner-directed): **the deployment's primary store
  returns to SQLite on an Oracle VM; Supabase Postgres + Cloud Run are
  decommissioned.** Trigger: the hosted Supabase project went over its egress
  limit. This is the sanctioned **re-decision reversing A23**'s store move —
  recorded here rather than done silently, because "never silently reverse a
  decision" is a standing non-negotiable (`AGENTS.md`).

  **This is a return to the originally intended architecture, not a new
  departure.** `docs/DEPLOY-SPEC.md` decision 1 (2026-07-26) already chose an
  Oracle Cloud Always Free VM with SQLite; Cloud Run + Supabase was a later
  divergence that A23's own H1-as-built note flagged as "never recorded in an
  amendment." The v1 out-of-scope list's "Postgres or any DB migration"
  exclusion (DEPLOY-SPEC.md) is *satisfied* by this, not broken by it.

  **A23 is refined, not repealed. The Postgres backend stays.** SQLite was kept
  a first-class, fully-tested backend by A23 precisely so this fallback would
  cost nothing, and the Postgres dialect layer (`sql.py`), pool, and
  Supabase-hardening remain in the tree and under test as the supported second
  backend and the reversible path — `--db postgresql://…` still works. What
  changes is only *which backend the live deployment runs on*. Everything A23
  established holds: single-tenant, the deterministic engine as the only source
  of numbers, and backend equivalence proven by a test (the same corpus yields
  byte-identical artifacts on either backend — the guarantee that makes this
  migration safe).

  **Migration mechanics (all pre-existing except one small addition):**
  - `driverdna store-copy --from <supabase-url> --to <sqlite-path>` carries
    every compact row with primary keys preserved (evidence IDs *are* those
    numbers) and a per-table checksum proof; it refuses a non-empty target and
    exits non-zero on any mismatch ("do NOT cut over"). Copying *into* SQLite
    needs no sequence resync. This moves the irreplaceable rows — `driver_
    beliefs` history, chat/coach transcripts, `finding_annotations`,
    `config_history` — that are not reconstructible from CSV.
  - **Raw lap blobs are not in store-copy's scope and never were in Supabase.**
    A23 kept them on local disk beside the importing machine; on Cloud Run's
    ephemeral filesystem that meant they did not durably exist at all (the
    cached `track_outline_json`, A-era, is the standing workaround). On the VM
    they land on the durable block volume, so every *future* imported/synced
    lap gets a durable trace automatically.
  - **`driverdna backfill-blobs --from <csv-dir>` is this amendment's one code
    addition** — the recovery path for *historical* raw traces, since a plain
    re-import is a no-op (the copied rows already dedup by content hash, so
    `store_lap` returns "duplicate" and writes no blob). It matches each CSV to
    a lap by that lap's own content fingerprint and writes only the missing
    `<lap_pk>.npz`, never creating, deleting, or renumbering a lap row, so
    evidence IDs stay valid. Idempotent. Restoring blobs re-enables the only
    capabilities that need them (`rebuild-map` re-measurement, `lap-digest`,
    raw track-trace); every report, the Driver Model, trends, chat/coach and
    findings run on the compact rows and were never at risk.

  **Number-neutral. No engine value changes and no model-version bump:**
  `backfill-blobs` writes bytes that reproduce the exact arrays the source
  imported (a test asserts array-equality against the source store), and
  reading them changes no measurement. New surface only: `pipeline.backfill_
  blobs`, `Database.laps_needing_raw()`, the `backfill-blobs` CLI command, and
  a TDD test file (`tests/test_backfill_blobs.py`).

  **Network shape: a public URL (owner's choice), per DEPLOY-SPEC H2's
  public-URL option** — Cloudflare Tunnel + Access (outbound-only, edge
  identity), chosen over Tailscale. H1's app-level auth stays on; edge identity
  is the outer wall, not a reason to trust an unauthenticated request. The
  existing Google-OAuth env (`DRIVERDNA_SESSION_SECRET`, `GOOGLE_CLIENT_ID/
  SECRET`) and provider/sync secrets move to the VM's `0600` systemd
  EnvironmentFile; the OAuth redirect URI must be repointed to the new host.

  **What lands now vs. what the owner executes:** the code, the amendment,
  `docs/DEPLOY-RUNBOOK.md`, the systemd unit + backup timer, the `cloudflared`
  notes, and the retirement of `.github/workflows/deploy.yml` land in this
  change. VM provisioning, the `store-copy` cutover, `backfill-blobs`, and
  deleting the Supabase project (which ends egress billing) are owner-executed
  runbook steps, kept off the automated path deliberately — a destructive
  cutover is not something a push to `main` should trigger. `docs/DEPLOY-SPEC.md`
  H2/H3 are un-staled to describe this real target; `docs/STATUS.md` carries
  the dated snapshot.

- **A41** (2026-08-05): **the Cloud Run sign-in bounce's real root cause, and
  the auth-layer changes A40's VM target needs.** A parallel session
  (`docs/VM-MIGRATION.md`, branch `claude/driverdna-access-link-m6uv7f`,
  commit `cd9296f`) investigated the sign-in bounce four prior sessions had
  tried to fix by changing auth code, and found the auth logic was never the
  problem. Referenced here per CLAUDE.md decision discipline rather than
  duplicated; that document is the full record, this entry is what was acted
  on from it and how, on this branch (`claude/database-egress-limit-csvslz`).

  **Root cause (not fixed here — moot once A40's Cloud Run retirement lands,
  recorded for the historical record and because it explains why four
  sessions of auth-code changes could not have worked):** two repository
  secrets (`DRIVERDNA_SESSION_SECRET`, `DRIVERDNA_DATABASE_URL`) were never
  set, so the deploy shipped `--db ""`. `sqlite3.connect("")` opens SQLite's
  private, connection-scoped temp database — deleted the instant the
  connection closes — so every request got a fresh, empty store: sign-in
  wrote the user to one temp DB, the very next request opened a different one
  and found nobody, and the SPA bounced back to login. A second, independent
  fault (the ephemeral per-process session secret, see below) would have kept
  breaking sign-in even after the first was fixed.

  **Fixed, applies regardless of backend or platform:**
  1. `resolve_store("")` now raises rather than silently returning `""` —
     an empty explicit `--db` is a caller bug (most often a shell
     interpolating an unset env var into a quoted argument), not "no --db
     given," and must not fall through to `$DRIVERDNA_DATABASE_URL` either
     (`store.py`; `cli._store` converts the raise to a clean `typer.Exit(2)`,
     the one choke point all 22 CLI call sites already share).
  2. **The ephemeral session-secret fallback is retired; the interlock now
     fails closed (owner-confirmed 2026-08-05).** A non-loopback bind (or,
     new in this amendment, a loopback bind with `--behind-proxy` declared)
     with no `DRIVERDNA_SESSION_SECRET`/`DRIVERDNA_ACCESS_TOKEN` configured
     now refuses to start with a named error, rather than generating a
     process-local secret that silently rotates — and signs everyone out
     with nothing in the logs to explain why — on every restart. This is a
     **re-decision** of behaviour A31 shipped (CLAUDE.md's "never silently
     reverse a decision" rule): `tests/test_auth_cli.py`'s three
     ephemeral-secret tests are rewritten to pin refusal instead, per that
     file's own updated header.
  3. **`/health` now reports `store` (`sqlite`/`postgres`) and `auth`
     (bool)** — owner-confirmed 2026-08-05 to be public. Enum and boolean
     only, never the DSN or any secret; `_is_pg` and `session_secret` are
     both already known at `create_app`-build time, so this adds no DB
     access (the existing "does not open a DB" guarantee is a named test,
     kept green). This is the fact that would have made the Cloud Run bounce
     a five-second diagnosis instead of four sessions of auth-code changes.

  **New, for the VM+reverse-proxy topology A40 actually deploys (the most
  severe finding, and the reason this landed alongside A40 rather than
  after):** the fail-closed interlock keys off *bind address*, so a reverse
  proxy in front of a **loopback**-bound instance defeats it silently — the
  bind looks safe, `authenticated()` returns `True` unconditionally with no
  secret configured, and the whole internet reaches the cockpit through the
  proxy with no login at all. `driverdna ui --behind-proxy`
  (`$DRIVERDNA_BEHIND_PROXY`) closes this:
  - Applies the fail-closed secret requirement regardless of bind address.
  - Explicitly wires `uvicorn.run(..., proxy_headers=True,
    forwarded_allow_ips="127.0.0.1")` — the proxy's own address, never a
    wildcard — turning what was an *implicit* uvicorn default (verified
    directly: uvicorn 0.52.1 already defaults to exactly this) into an
    intentional, tested contract, and explicitly passing
    `proxy_headers=False` otherwise rather than depending on a library
    default for a security-relevant trust boundary.
  - `_is_https` (`ui/api.py`) trusts the now-reliably-resolved
    `request.url.scheme` under `--behind-proxy`, instead of re-reading
    `X-Forwarded-Proto` itself — a read with no trust boundary at the app
    layer. Off (the Cloud-Run-shaped default), behaviour is byte-for-byte
    unchanged: the existing manual header read, needed because Cloud Run's
    front end is never `127.0.0.1`.
  - `_client_key` needed **zero code changes** — it already reads the
    ASGI-level `scope["client"]`, which `ProxyHeadersMiddleware` rewrites
    beneath it. Locked in by an integration test wrapping the real
    middleware exactly as the CLI configures it and proving a login lockout
    from one forwarded client does not lock out a different one arriving
    through the same proxy peer — not merely asserted, since the source
    analysis's static read of this exact function reached the wrong
    conclusion once uvicorn's actual runtime defaults were checked (below).
  - A loud, once-per-app warning (not a request-time refusal — a refusal
    here would be a confusing failure mode) fires when a request carries
    `X-Forwarded-*` while no secret is configured and `--behind-proxy` was
    never set: the forgotten-flag case this whole amendment exists to catch.
  - `deploy/driverdna.service` (this branch) now passes `--behind-proxy`;
    without it the unit would still refuse to start unauthenticated (item 2
    above still holds), but login throttling and rate limiting would
    silently collapse to one shared bucket keyed on the tunnel's loopback
    connection instead of the real caller.

  **One finding in the source analysis re-verified and narrowed, not taken on
  faith:** its §3.2 read `_client_key`/rate-limiting as broken behind any
  reverse proxy. Empirically checking uvicorn 0.52.1's actual defaults
  (`Config.proxy_headers=True`, `forwarded_allow_ips` resolving to
  `'127.0.0.1'`, confirmed by driving `ProxyHeadersMiddleware` directly)
  showed `scope["client"]` already rewrites correctly today for a
  loopback-connecting proxy, with no code change — the static analysis
  couldn't see the installed library's runtime defaults, only the source.
  The interlock finding (§3.1) and the `_is_https` finding (§3.3) were both
  independently code-verified and are exactly as described. This is itself
  an instance of the source document's own stated lesson — assert the thing
  you believe, don't infer it — applied one level up, to that document's own
  claim.

  **Deliberately not acted on, left for the owner (VM-MIGRATION.md §5, still
  open):** the mechanism choice in §3.1 was already made (option (a),
  explicit flag, as built); §3.8's session-per-device semantics (a second
  sign-in currently ends the first session on the password path but not on
  Google's callback-for-an-existing-user path — a real inconsistency, not
  addressed here, no default is obviously correct); §4.1's instruction to
  audit what Supabase actually holds before trusting it as the authoritative
  copy — an operational check against the live project, not something
  decidable from a session with no access to it.

  **Verification.** New/rewritten tests: `tests/test_dialect.py` (3, the
  empty-`--db` refusal, library- and CLI-level), `tests/test_auth_cli.py`
  (rewrites 2 ephemeral-secret tests to pin refusal, adds 4 for
  `--behind-proxy`), `tests/test_api.py` (2, `/health`'s new fields, proving
  the DSN/secret never appear), `tests/test_auth_api.py` (6: scheme trust
  under `--behind-proxy`, the once-only warning under four conditions, and
  the real-middleware `_client_key` integration test). Suite 885 → 899
  passed, 16 skipped (same Postgres-absent set), 0 failed; every
  ephemeral-secret/health-shape change is a deliberate rewrite of what the
  test pins, not a weakening — each rewritten assertion is narrower or
  stricter than what it replaced, never removed outright.

- **A42** (2026-08-06): **`same_lap_twice` per-unit CV normalization
  (coach-onto-v2).** The `cp.repeatability.same_lap_twice` coaching
  principle's MetricCVGate pooled every measured metric's raw CV with a flat
  mean. This is the coaching-layer analogue of the identical bug dm-v1 had
  (A21): five '% lap' metrics with a natural CV of ~0.007 each would dominate
  a flat mean alongside one 'count' metric with a natural CV of ~0.99, even
  when the driver is genuinely and measurably inconsistent on that count
  metric. The concrete effect: with five perfectly-consistent '% lap' metrics
  and one 'count' metric at typical scale, the flat mean gives ≈ 0.99/6 ≈
  0.165 (barely above the 0.15 eligibility floor, moderate band) while the
  per-unit normalized result gives (0.0 + 1.0) / 2 = 0.5 — a 3× difference
  and a different gap band. The flagged note in M7's milestone description
  ("same underlying issue as M6's cross-cohort consistency caveat, one level
  down") is the same structural diagnosis as A21, now resolved by the same
  pattern: divide each metric's raw CV by its own unit's typical scale
  (`config.model.consistency_unit_reference_cv`, the same reference dict dm-v2
  already uses) then pool two levels — mean within each unit, mean across
  units — so no unit dominates by metric count. `trust_the_proxy`'s single-
  metric gate (`brake_point_dist_pct`, one unit) is unchanged. `ONTOLOGY_
  VERSION` bumped `coach-onto-v1` → `coach-onto-v2`. No model-level Driver
  Model version bump — `same_lap_twice` is a coaching gate, not a Driver
  Model scoring component. `consistency_cv_floor` and the `cv_band_*`
  thresholds now operate in normalized-CV space (multiples of typical scale
  for that unit); their default values are unchanged and remain reasonable in
  that space (0.15 = 15% above typical variability). **Verification:**
  `test_same_lap_twice_per_unit_normalized_not_flat_mean` in
  `tests/test_coaching_engine.py` tests the new function directly with
  controlled metric values. Suite 899 → 900 passed, 16 skipped, 0 failed.

- **A43** (2026-08-06): **`census` surfaced in the driver payload and Driver
  home UI.** A33's `driverdna census` artifact answered "do I need more lap
  data?" at the CLI only; A43 adds a `census` key to `build_driver_payload`
  (`PAYLOAD_VERSION` 5 → 6) and renders a "Corpus readiness" panel on the
  Driver home tab showing the confidence ceiling, self-lap count, and the
  next-steps table ranked by confidence gain. No new measurement, no new
  configuration — census reads the exact thresholds and suppression strings the
  engine already emits. The `_include_census=False` sentinel in
  `build_driver_payload` breaks the recursion that would otherwise arise because
  `census._suppression_section` calls `build_driver_payload` to quote rollup
  gate reasons verbatim (the anti-drift guarantee A33 established). Three new
  tests in `test_census.py`: census key present in driver payload, census key
  None when no laps, next_steps shape. Suite 900 → 903 passed, 16 skipped, 0
  failed.

- **A44** (2026-08-06): **390×844 mobile viewport render-parity and trust-gate-5
  tests (DEPLOY-SPEC Track M done-criteria).** Two DEPLOY-SPEC U5 done-criteria
  were verified manually but had no automated test:
  (1) every fractional `.num` figure traces to a payload number at 390×844
  viewport — same parity invariant as the desktop `test_render_parity.py` test
  but with `browser.new_page(viewport={"width": 390, "height": 844})`; and
  (2) no horizontal body overflow (`document.documentElement.scrollWidth >
  window.innerWidth`) on any crawled route at that width.
  `test_render_parity.py` gains `test_mobile_viewport_parity_and_no_horizontal_
  overflow` covering all seven SPA routes.
  `test_offline.py` gains `test_mobile_viewport_non_localhost_blocked` — the
  same non-same-origin block invariant (trust gate 5) at 390×844 width, so
  mobile layout changes can't silently re-introduce an external request.
  Both tests skip automatically when Playwright/Chromium or the built SPA is
  absent (same `pytestmark` as all other browser tests). No new measurement, no
  engine change, no PAYLOAD_VERSION bump. Suite 903 → 903 passed (browser tests
  are non-blocking CI; skip count unchanged in the non-browser suite), 16
  skipped, 0 failed.

- **A45** (2026-08-06): **Two standing bug fixes — blob-root collision and
  Google OAuth session-per-device inconsistency (SPEC.md A24 / VM-MIGRATION.md
  §5).**

  *Blob-root collision (A24):* `default_blob_root` keyed a Postgres DSN's blob
  directory off the last URL path segment (e.g. `"postgres"` for every Supabase
  project), so two separate Supabase projects shared `~/.driverdna/blobs/postgres/`
  and would overwrite each other's lap blobs. Fixed: the root is now keyed on the
  first 16 hex characters of `SHA-256(DSN without query string)`, making it
  unique per full DSN while still stable on repeated calls. `DRIVERDNA_BLOB_ROOT`
  still overrides unconditionally. Existing remote-store users whose blobs landed
  under the old name-based directory must rename the directory or set the env var
  to point at it; `driverdna store-copy` is the migration path. The fix was
  lower urgency once Supabase was retired but the bug survives in the Postgres
  backend. `test_blobs.py`: replaced `test_remote_url_keys_off_database_name`
  with three tests (`test_remote_url_root_lives_under_home_driverdna`,
  `test_remote_url_distinct_dsns_produce_distinct_roots`,
  `test_remote_url_same_dsn_is_stable`) that pin the new guarantees.

  *Google OAuth session-per-device (A41 / VM-MIGRATION.md §5):* A second
  Google sign-in for an existing user did not bump `session_epoch`, so the
  prior session remained valid — inconsistent with the password login path,
  which always bumps the epoch on sign-in. Fixed in `google_callback`: generate
  a fresh `session_epoch = datetime.utcnow().isoformat()` before the DB
  transaction, then `UPDATE users SET session_epoch=? WHERE user_pk=?` for
  existing users (new-user INSERT already set a fresh epoch from the same value).
  `test_auth_api.py` gains `test_google_callback_invalidates_prior_session_for_
  existing_user`: password-logs in, captures the old cookie, triggers the
  mocked OAuth callback for the same email, and asserts the old cookie now
  returns 401. Suite 903 → 905 passed, 16 skipped, 0 failed.

- **A46** (2026-08-09): **Feedback reads by racing fundamental, not by
  measurement source** (owner-directed: "cleaner, easier to read, less
  superfluous text, more racing fundamental focused than data focused —
  understanding that the data feeds the coaching").

  *The structural cause, not just wordiness.* The cohort page carried two
  feedback layers saying the same thing in two voices: M7's coaching layer
  already spoke racing ("Let the fronts finish their work before you ask them
  to steer"), while the findings section directly below restated the same
  triggers in engine voice, grouped by `vs-self`/`vs-principle`/
  `vs-reference` — how the engine *knows* a thing, not how a driver drives.
  Nothing on screen carried a fundamental, though `model/taxonomy.py` has held
  that mapping since M6 and the Driver Model tab is built on it.

  *Engine changes.* `taxonomy.phase_fundamental()` inverts `Fundamental.phases`
  (entry→braking, mid→rotation, exit→corner_exit) with an explicit rule — the
  MEASURED claimant wins, so `commitment` (proxy, also `phases=("entry",)`)
  never adopts a directly-measured finding; `test_taxonomy.py` pins the
  precondition that exactly one measured fundamental claims each phase, so a
  later taxonomy edit cannot make this ambiguous silently. `Fundamental` gains
  a required `label`. `metrics/detectors.py` gains `DETECTOR_LABELS`, the
  driver-facing phrase per detector (slugs remain the stable IDs everywhere
  else), cross-checked against the real dispatcher. `Finding` gains
  `fundamental`, resolved from `detector_fundamentals` / `phase_fundamental`
  so every renderer groups by one authority instead of its own lookup table.

  *A correctness fix, not only a rewording.* `vs_principle_findings` built its
  description as `f"{corner}: {detector} on {t}/{n} laps. {rationale}"` where
  `rationale = rows[0]["rationale"]` — the **first triggering lap's** value.
  "3.63 s with neither pedal" was therefore one lap's figure printed as though
  it characterised the corner. The description is now a summary
  (`C01: coasting mid-corner on 6 of 11 laps`) and the rationale moves to
  `details["rationale"]`, rendered behind the evidence disclosure labelled as
  the single observation it is. The driving principle that sentence was
  carrying already lives in `coaching/ontology.py`, its proper home.
  `vs-reference` drops the per-row "Gap is context, not recoverable time."
  (30 repetitions on the owner's real GT4/Spa cohort) — the phrase is stated
  once by the section legend and `explain.py`'s `source.vs-reference`; the
  fixed vocabulary "gap to reference" is unchanged (decision 8).

  *Rendering.* `FundamentalSections` replaces `SourceSections` on the cohort
  page and the corner drill, in the Driver Model pyramid's fixed order; the
  coaching expression for a fundamental and the findings that triggered it now
  sit in one group instead of restating each other. N, spread, reference
  depth, gap band and the detector rationale move behind the existing
  `.disclosure` arrow; the suppressed pile collapses to one disclosure per
  group carrying every gate reason verbatim. `belief.label` travels through
  the payload, retiring the hardcoded label map in `model.jsx`.
  `PAYLOAD_VERSION` 6→7 (additive: `finding.fundamental`, `belief.label`);
  `coach-v3`/`chat-v3` untouched — those version prompts, and no prompt text
  changed. Every addition is a string, so the numeric-grounding pool is
  unaffected.

  *Number-neutral, proven.* Regenerating every artifact against clean `main`
  and against this branch and diffing the numeric multisets: the only value
  that moved in `gr86-spa-francorchamps.json` and `driver.json` is
  `payload_version` 6→7. `docs/attribution-report.md`, `metrics-report.md`,
  `corners-report.md`, `incidents-report.md`, `driver-model-report.md` and
  `census-report.md` regenerate byte-identical.

  *Pre-existing staleness found and fixed in passing, flagged so it is not
  read as this change's doing:* `docs/coaching-report.md`, `driver.*` and
  `gr86-spa-francorchamps.*` were stale on `main` — A42 (`coach-onto-v2`,
  per-unit CV normalization) and A43 (census in the driver payload) changed
  their numbers without regenerating them. Verified by regenerating on a clean
  checkout: clean-`main` output differs from the committed files in exactly
  the same way, and matches this branch's output number-for-number. They are
  regenerated here; most of the diff in those three files is A42/A43 catching
  up, not A46.

  Suite 908 → 924 passed, 16 skipped (Postgres only), 0 failed.

- **A47** (2026-08-09): **CI quality gates: lint, secret scanning, mypy
  ratchet, and branch protection (owner-directed) — plus two live CI bugs
  found and fixed while scoping the work.** `main` had no merge gate at all
  (unprotected, and `tests.yml` triggers on `push`, so CI could only report
  after the fact) and no linter/formatter/type checker, a position stated
  four times in the repo (`tests.yml`'s own header comment,
  `docs/PROJECT-BRIEF.md`, `docs/STATUS.md`, and this file's own prior text)
  as a deliberate design choice. Re-decided per AGENTS.md's Decision
  discipline, not silently reversed.

  *Two real CI defects found before any new tooling landed:*
  (1) **All 19–22 Playwright-driven tests had been silently skipping in
  every CI run for an unknown stretch of history.** Playwright's installer
  moved Chrome for Testing to a `chrome-linux64/` layout; the seven
  browser-test modules' hand-copied `_find_chrome()` still globbed the old
  `chrome-linux/` path. The `browser-tests` job's own guard step caught this
  correctly (`grep` the skip reason, `exit 1`) — but the job was
  `continue-on-error: true`, so the run still reported green regardless.
  `tests/test_reference_curation_ui.py` ran in *no* environment at all:
  Chromium-gated so it skipped in the main `pytest` job, and absent from the
  browser job's hand-maintained six-file list. Fixed: `tests/browser.py`'s
  `chromium_executable()` asks Playwright for its own browser path instead
  of guessing the on-disk layout (verified this actually matters — this
  session's sandbox had a real, reproducible version mismatch between a
  freshly `pip install`ed Playwright and its pre-baked browser revision);
  `pytest.mark.browser` (registered, `--strict-markers`) replaces the
  hardcoded file list, so a new browser test module is picked up
  automatically; `continue-on-error: true` is removed — the job blocks for
  real now. Verified in a live GitHub Actions run, not just locally (the
  bug was invisible locally the whole time it was broken in CI): the
  `browser-tests` job went from `19 skipped in 1.69s` to
  `22 passed, 902 deselected ... in 119.16s`.
  (2) **The TDD guardrail (A-series predecessor, 2026-07-27) had never once
  correctly suppressed.** It compared changed files against `^driverdna/`,
  which stopped existing when the package moved to src-layout
  (`src/driverdna/`) in `f286908` — so `src_changes` was always `0`, and the
  "agent may be cheating" warning fired on every normal push touching
  `tests/`, including ordinary Red→Green→Refactor commits. Fixed to
  `^src/driverdna/`; verified live that it now stays quiet on a commit
  touching both `tests/` and `src/driverdna/`, and still (correctly) warns
  on a tests-only commit.

  *What was adopted:*
  - **`ruff check`** (pyflakes + bugbear only, `[tool.ruff]` in
    `pyproject.toml`) as a required `lint` job. No formatter, no
    line-length rule — see "What was explicitly not adopted" below. 47
    pre-existing findings cleared before the gate landed, most notably 13
    `zip()`-without-`strict=` sites reviewed individually rather than
    blanket-flagged: 3 deliberately-ragged pairwise-adjacent patterns
    (`zip(xs, xs[1:])`) got `strict=False`; the other 10 (all same-length
    by construction — `corner_map.match_lap`'s one-id-per-span contract,
    `outlier_mask`'s one-bool-per-input contract, digest-row-vs-header
    parity) got `strict=True`, so a future length mismatch raises instead
    of silently truncating. None of the 10 `strict=True` conversions broke
    the suite, so none were latent bugs — but the check is now live for
    the next one.
  - **ESLint** (`ui/eslint.config.js`, flat config) for the 17-file SPA,
    which had zero JS tooling. Pyflakes-equivalent rules plus only the two
    long-established React hook rules (`rules-of-hooks`,
    `exhaustive-deps`) — `eslint-plugin-react-hooks` 7's full "recommended"
    set pulls in ~14 additional React-Compiler-readiness rules
    (`set-state-in-effect`, `purity`, `immutability`, ...) that are
    opinionated architectural guidance, not the "this is a bug" class this
    gate is scoped to. 24 problems baseline against the full set, 22
    against the narrowed one; cleared to 0 errors (13 dead `import React`
    statements — React 18's automatic JSX runtime makes them unused, and
    none referenced `React.` namespaced — plus two genuinely dead
    variables). 5 warnings (stale-dependency risk in two effects, two
    fast-refresh notes) left as non-blocking, matching upstream default
    severity: fixing the `exhaustive-deps` warnings would mean guessing
    whether the narrowed dependency lists are deliberate (avoiding a
    re-fetch loop) without a way to verify the runtime intent.
  - **gitleaks 8.30.1**, pinned binary + SHA256 checksum (independently
    downloaded and hashed in this session, not copied from a summary,
    verified to match the published `gitleaks_8.30.1_checksums.txt`
    exactly) — downloaded directly rather than via `gitleaks-action`,
    matching this repo's existing convention of pinning
    `run-gemini-cli` by exact version in `gemini-assistant.yml`, so
    there's no additional third-party Action supply chain to trust.
    `.gitleaks.toml` extends the built-in ruleset and allowlists
    `tests/fixtures/` and `src/driverdna/ui/static/` — not because either
    tripped a false positive (a full-history scan with the default
    ruleset found none: 116 commits, ~45.6 MB) but because both could
    plausibly trip an entropy rule as they grow, and neither is source
    this scan covers. Mechanises the AGENTS.md non-negotiable that
    `GARAGE61_TOKEN`/`ANTHROPIC_API_KEY`/`GEMINI_API_KEY`/
    `DRIVERDNA_DATABASE_URL` are env-only and never persisted — previously
    enforced by review alone.
  - **mypy**, advisory, scoped to `src/driverdna` (93.6% already
    return-annotated). 59 findings, spot-checked across every distinct
    error class and none were real bugs (dynamic `_pool`/`_pool_raw`
    attributes on a `Database` instance built via `object.__new__`
    bypassing `__init__`; an exception-named `for e in ids:` loop variable
    mypy's scope check flags on principle, unrelated to the actual
    `except ... as e:` earlier in the same function; Optional-narrowing
    and `**kwargs`-unpacking noise on loosely-typed dicts). Pinned to
    `ci/mypy-baseline.txt` as a **ratchet**, not `continue-on-error: true`
    — that flag is exactly what hid defect (1) above, so repeating it here
    immediately after fixing it there would be self-defeating. The job can
    fail for real and stay visibly red; it simply isn't in the
    required-checks list, so it can't block a merge. Fails only when the
    count exceeds the pinned baseline, never demands the existing 59 be
    fixed.
  - **Branch protection on `main`** (owner-executed via GitHub's UI — no
    tool in this session can write repo rulesets): require the PR + status
    checks (`pytest (3.11)`, `pytest (3.12)`, `lint`, `browser-tests`,
    `secrets` — not `mypy`), owner on the bypass list for direct hotfix
    pushes. Lands last, after every other check is proven green in a real
    run.

  *What was explicitly not adopted:* `ruff format` / black. Would touch
  ~6,100 lines across 106 of 138 files — and only ~2% of that diff is
  actual line length, the rest is trailing-comma-expansion churn — against
  a repository three different agent tools push directly to.
  `tests/test_ordering_determinism.py::test_no_unaliased_derived_tables`
  asserts on literal SQL source text via `inspect.getsource` with a
  40-character alias-lookahead window; a reflow tool restructuring a query
  string would produce a false failure there. Prettier for the SPA was
  similarly skipped for the same reason (no formatter, matching the
  Python-side decision) — ESLint's scope is deliberately correctness-only
  on both sides of the stack.

  Landed as five separate commits (repair existing CI → ruff → eslint →
  gitleaks → mypy), each with the full suite green and, for the two CI
  fixes, verified in a real GitHub Actions run before the next commit —
  the plan for this work exists specifically because a prior local-only
  pass proved nothing about CI once already. Suite 905 → 909 passed (the
  gitleaks pin-format test), 16 skipped, 0 failed throughout; no engine
  number moved.

  **Not resolved (2026-08-09): branch protection is blocked, not merely
  pending.** The owner's account hit a GitHub plan restriction attempting
  the Rulesets UI this amendment assumed was a formality — private-repo
  Rulesets require a paid plan tier this account does not have. Classic
  branch protection (`Settings → Branches`, the older, separate feature)
  is untried and may or may not be gated the same way; not yet confirmed
  either direction. Until one of them works, **there is no
  platform-enforced block on a direct push to `main`** — every required
  check still runs and still reports red/green on every push and PR, the
  enforcement layer is just absent. AGENTS.md's Branches-and-merging
  section is corrected accordingly: the PR-only rule is now stated as
  binding by convention, not backed by a ruleset, and is written more
  emphatically for exactly that reason — an agent reading it should treat
  it as absolute regardless of whether GitHub would actually stop a
  violation.

- **A48** (2026-08-10): **Fundamentals read as landmarks, and the feedback
  section reads as coaching** (owner-directed: the fundamental names should
  "feel like section landmarks, not just list headers … like a coach has seven
  fundamentals they look at everything through as a lens"; then, on seeing the
  mockup, "hide the 'vs reference/principle' and 'vs self' stuff and instead
  show more targeted coaching feedback in that section").

  *What was actually wrong.* A46 put the right structure on the page and left
  the rendering behind it. `.fgroup-name` was 0.92rem — barely larger than the
  0.86rem finding rows it headed — on a `--line` left rule with almost no
  contrast against `--panel`; and the fundamental's racing sentence sat *below*
  the header inside `CoachingSecondary`, so the first thing read under
  "Rotation" was an engine-voice measurement row, not the coach's takeaway.
  Two of A46's own goals were therefore only half-delivered.

  *Chosen from a mockup, not from prose.* Four header treatments were built
  against the real GR86/Spa fixture — every sentence, corner and figure real
  engine output, not placeholders — and the owner picked "lens rule":
  `docs/ui-fundamentals-mockup.html` (the `docs/ui-redesign-mockup.html`
  precedent). One rule runs the height of the group, brightest where the
  fundamental is named and fading down it, with the tier mark sitting on it.

  *The tier mark.* A 22px inline SVG: the Driver Model pyramid in miniature
  with this fundamental's tier lit, beside every fundamental name on the cohort
  page, the corner drill and `#/model`. `ui/src/views/pyramid.js` now holds the
  tier geometry once and `model.jsx`'s full-size `Pyramid` cuts its tiers from
  the same `tierPoints()`, so the two drawings cannot become two pyramids;
  `ui/src/views/order.js` holds `FUNDAMENTAL_ORDER`. It encodes position in the
  fixed seven and nothing else — no score, no semantic colour, so it can never
  read as a verdict (colour grammar rule 2 untouched).

  *Coaching leads; measurement is one click under it.* Each fundamental opens
  with its top-ranked principle said in full — expression, driving principle,
  **and the drill**, which until now rendered on the single headline card only,
  so eight of the nine seed principles carried a written practice step the
  driver could never see. The findings collapse into one `<details>` per group
  ("The 7 findings behind this"). The headline's fundamental is marked with a
  `priority` chip and the headline is prepended to its own fundamental's
  ranked list, which is what retires `CoachingSecondary`'s "Same as the
  headline above, also at:" branch: the headline principle now always *is* its
  fundamental's lede, so there is nothing left to cross-refer to.

  *What was asked for and deliberately not done, stated rather than quietly
  ignored.* "Hide the vs-self / vs-principle / vs-reference stuff" is
  implemented as **collapse, never delete**. Every finding row is still in the
  DOM, still carries its own `.src-tag`, and the render-parity crawler reads
  inside closed `<details>` — so the guarantee AGENTS.md calls non-negotiable
  ("every finding carries N, spread, source tag, and evidence IDs") and
  UI-SPEC decision 6's binding half are untouched, while the section reads the
  way the owner asked. Deleting the tags would have contradicted the
  constraint the same request opened with ("Source tag stays on every finding
  row") and is not a change any renderer should make on its own; it would need
  its own owner decision. Also rejected: putting the Driver Model score on the
  cohort group header. That score is driver-level, pooled across every cohort;
  on a per-cohort page it would be a number that is not about the cohort being
  read.

  *A fundamental with coaching but no shown finding now gets its section in
  the static report too.* On the real fixture that is `consistency` — a major
  signal at sixteen corners with nothing clearing the finding gates. The SPA
  has always rendered that group; the report dropped it, which meant the report
  was silently hiding the loudest thing the engine had to say about this
  driver. A fundamental with findings but no eligible principle (`braking`
  here) invents no sentence and keeps its rows in the clear.

  *Group headers stop carrying a bare count.* Decision 6 permits a count of
  rendered items; it never required one. With the measurements collapsed the
  figure had nothing next to it to say what it counted, and every count is now
  stated in words where it does the work ("The 7 findings behind this", "33 not
  shown yet — evidence gates", "Nothing clears the gates here yet").

  *Number-neutral, proven.* No payload field was added, so `PAYLOAD_VERSION`
  stays 7 and `coach-v3`/`chat-v3` are untouched. `gr86-spa-francorchamps.json`,
  `driver.json` and `driver.md` regenerate byte-identical; all eight
  `docs/*-report.md` regenerate byte-identical;
  `gr86-spa-francorchamps.md`'s numeric multiset is identical across the
  change (129 numerals) and only prose was added; the two HTML reports' *reader
  visible* numerals are identical (533 and 27) with every numeric delta inside
  the `<style>` block, which is the new CSS lengths. The lede ordering rule is
  implemented once per surface (`shared.jsx`, `report/builder.py`) and pinned
  on both against the payload's own `coaching.headline` rather than against a
  restatement of the rule, so the two cannot start leding with different
  principles.

  Suite 963 → 971 passed, 16 skipped (Postgres-absent only; Chromium present,
  every browser-gated file ran), 0 failed. +8 tests: four browser
  (`tests/test_feedback_hierarchy_ui.py` — sentence-before-measurement in DOM
  order, the `priority` chip on exactly the headline's fundamental and said
  once, findings collapsed-not-dropped with every row still tagged, the tier
  mark on both surfaces) and four report (`tests/test_report.py` — Markdown and
  HTML lede each fundamental with its coaching expression, a coached-but-
  ungated fundamental still gets its section, each expression said once per
  section).

- **A49** (2026-08-11): **Sync is bounded by cohort, newest first; pit-lane laps
  are counted before they are judged** (owner-directed: "is there a limit to how
  many cohorts can be loaded and synced? I'd want the g61 sync to pull from the
  latest and go on down sequentially to that #", then "have it ignore laps that
  don't start at the finish line or laps that are just starting formation laps.
  propose a max # and a way to communicate that # to users").

  *The problem.* An account accumulates a cohort per (car, track) ever driven —
  the owner's has ~25 — and `sync_driver` listed every one of them on every run.
  Most will never gain another lap. `discover_cohorts` sorted alphabetically,
  which is the one order that carries no information about which combos are
  live.

  *What changed.* `config.sync.max_cohorts` (default **10**, `0` disables) caps
  how many cohorts one sync pulls, and `discover_cohorts` now returns them
  newest-driven first. `/me/statistics` is per (day, car, track, sessionType),
  so a cohort's `last_driven` is the newest `day` across its rows — the field
  was already in the response and was being discarded. Ten covers 2–4 active
  combos a season plus a couple carried over; the cap is a prefix of a
  recency-ordered list, so a cohort re-enters the window the moment it is driven
  again.

  *The trade this makes, stated rather than implied.* `sync_driver`'s docstring
  explains why there is deliberately **no** automatic watermark off
  `last_synced_at`: `after` filters on when a lap was *driven*, not when it was
  synced, so a lap uploaded after the last sync but driven before it would be
  silently skipped forever. A cohort cap reintroduces exactly that failure mode
  one axis up — a lap uploaded late to a cohort outside the window is not seen
  until that cohort is driven again. This is a narrowing of a documented
  guarantee, which is why it is an amendment and not a default. Two things bound
  it: only the *cohort* axis is capped (within a synced cohort the full listing
  is still re-read, so the original reasoning holds unchanged there), and every
  skipped cohort is reported **by name with its last-driven date**, in the CLI
  and in the SPA, never as a bare count.

  *Why named and not counted.* The ordering rests on `day`, whose format is
  documented nowhere — `docs/garage61-api.md` lists the field and never shows a
  value. It is compared as a string, correct for `YYYY-MM-DD` and for any
  ISO-8601 timestamp, wrong for an epoch integer. Naming the shed cohorts makes
  a wrong ordering visible on the first run instead of silently dropping the
  wrong fifteen. Two further guards: a row with no usable `day` sorts oldest
  rather than raising, and if *no* cohort carries a date the cap is refused
  outright and the full sync runs — a slow correct sync beats a fast arbitrary
  one ("insufficient data over guessing").

  *Pit-lane laps: measured, not assumed.* The owner asked for laps that don't
  start at the finish line, and formation laps, to be ignored. Formation laps
  are already excluded server-side: the API's `lapTypes` default returns normal
  full laps only, so out/in laps (types 3 and 4) never arrive. What remains is a
  *normal*-typed lap that nonetheless began in the pit lane, which the listing
  marks with a `pitlane` boolean — also undocumented beyond a field-name
  mention. Under the reading "started in the pit lane" skipping is right; under
  "touched the pit lane at all" it would discard laps whose driving is fine. So
  `config.sync.skip_pitlane_laps` ships **defaulting off**, and sync counts
  these laps (`CohortSync.laps_pitlane`, surfaced in the CLI, the SSE
  `complete` event and the SPA) without dropping any. The default flips when a
  real sync settles the question; the counter is what will settle it. This keeps
  the change number-neutral: no lap that was imported before is skipped now.

  *A real bug found while doing this, and deliberately not fixed here.* Filed as
  **BUG-022**. It was first written up as "`ingest/parser.py:328` raises
  `INCOMPLETE_LAP`, nothing reads it, so partial laps are measured as if
  complete on every ingest path" — and that consequence was **inferred from the
  unread flag rather than checked**. The owner then supplied the missing product
  intent — an incomplete lap is *wanted*, because a lap that ends in a virtual
  tow is the incident record ("measure the driver, not the lap", A19) — which
  forced the check. The check disproves the original scope and finds a narrower
  real defect. Both are recorded in BUG-022; the correction is the point.

  Measured on `Garage_61_HKWPXX.csv` truncated to 40%: the per-corner layer is
  **correct by construction** — the segmenter finds 4 corners instead of 14, so
  an incomplete lap contributes fewer *valid* observations, never fabricated
  ones, and phase times, metrics, the Driver Model and trend are all unaffected.
  What is actually broken is whole-lap `duration_s` (`n_samples /
  SAMPLE_RATE_HZ`, i.e. trace length) being used as though it were a lap time:
  `report/payload.py:183-186` measures `lap_delta_s` against `min(duration_s)`
  with no completeness filter, so the truncated lap's 68.50 s becomes the
  cohort's "fastest" and a genuine 171.25 s lap renders at **+102.75 s**.
  `references_section` (`payload.py:149`) has the same exposure for a towed
  reference lap. Dormant on the committed fixtures, which are all complete —
  and it activates exactly as incident capture starts working.

  The fix must therefore *keep* these laps and stop mis-reading one column, not
  gate measurement on `INCOMPLETE_LAP` as the first filing proposed — that would
  have deleted the evidence the incidents subsystem exists to collect. Left for
  its own change because it moves real numbers in `lap_delta_s` and the
  reference envelope. Separately, A49's `laps_pitlane` counter still answers
  what `pitlane` means: whether it coincides with low coverage.

  *Not changed.* No model version bump: this is ingest scope, not a scoring
  parameter, and with the pit-lane skip off by default no existing measurement
  moves. No committed artifact moves either — the fixtures are imported, not
  synced, so `test_artifact_freshness.py` stays green untouched. `sync_driver`'s
  return type stays `list[CohortSync]`; the run-level cap counts ride the
  existing `discovering` progress event (repeated on the SSE `complete` event so
  the SPA need not hold progress state), which is how the CLI and the UI both
  get them without a signature change across ~20 call sites.

  *Also fixed on the way, unrelated to this change.* `main` was red: PR #21
  added `garage61_linked` to `GET /api/auth/status` without updating the
  assertion in `tests/test_auth_api.py` (**BUG-023**). And `ruff check .` — a
  declared CI merge gate — reported 25 findings in fifteen dead root-level
  scratch scripts that nothing imports: one-shot rewriters that opened
  `src/driverdna/db.py`, applied string replacements and wrote it back, left
  over from the identity/`users` phase work and the Postgres move (A23). Raised
  as an owner decision rather than folded in silently, then deleted on the
  owner's instruction (**BUG-024**) — their output has been in `db.py` for
  months, so they were both dead and misleading. Auto-fixing the unused imports
  was rejected: it would have left dead code lint-clean and still dead.
  `ruff check .` now passes repo-wide, so `lint` is a real signal instead of a
  permanently red one — which matters, because BUG-023 was a genuine regression
  sitting in the same run and was nearly written off as environmental.

- **A50** (2026-08-14): **BUG-022 fixed: incomplete laps excluded from lap-time
  comparison.** `INCOMPLETE_LAP`-flagged laps no longer enter the `lap_delta_s`
  comparison or the reference envelope: `lap_delta_s` is computed from
  `min(duration_s)` of complete laps only, an incomplete lap's entry is `null`,
  and a new `lap_incomplete` boolean array (parallel to `lap_ids`) lets every
  consumer distinguish them. Reference `reference_envelope` also filters
  incomplete reference laps (the `incomplete` field now travels with the
  contributor dict from `reference_laps_for_cohort`). The HTML chart excludes
  incomplete laps so a 68 s trace doesn't distort the Y scale. SPA shows an
  "incomplete" chip and "—" delta. Per-corner measurement is unchanged —
  incomplete laps still contribute their valid corners, as A19/A49 require.
  `PAYLOAD_VERSION` 7→8: additive field, `lap_delta_s` entries may be `null`.
  Number-neutral on committed fixtures (all complete laps). Stale Cloud Run
  references in `api.py` comments cleaned up (A40 retired it). BUG-026 (SSE
  heartbeat) separately fixed and merged.

- **A53** (2026-08-18): **A32 reconciled against reality; closed-beta direction
  adopted.** A32 (2026-07-28) recorded multi-tenancy as built and merged, and the
  repository then spent three weeks contradicting it: `docs/DEPLOY-SPEC.md` still
  said "no user table, no registration, no tenant column", `AGENTS.md` and
  `CLAUDE.md` still opened "personal instrument for one driver", and the dated
  status log never named A32 again. `docs/ACCOUNTS-SPEC.md` (lines 37-56)
  predicted this exact failure and required those documents to change **in the
  same edit as A32**. They did not. This amendment closes that gap and states
  what an audit of the running code actually found.

  **A32's own wording is corrected, not rewritten.** A32 says "**Principle
  refined:** philosophy #8". ACCOUNTS-SPEC:37-41 required the word **reversed** —
  "the amendment must say *reversed by owner decision*, not 'refined'" — because
  a reversal recorded as a refinement makes the amendment log understate its own
  history. Read A32 as: **philosophy #8 was reversed by owner decision on
  2026-07-28, overriding A31.** A32's text stands; this is the correction of
  record.

  **What the audit found (2026-08-18, read-only, against `main` at `e196c2d`).**
  A32 is **live and load-bearing**, not dead code: `docs/DEPLOY-RUNBOOK.md`
  Part D step 5 makes `/api/auth/register` the documented way the owner creates
  their account on the VM. Partitioning is real and thorough — migration 008
  creates `users`, 009 adds `owner_user_pk` and rewrites the unique keys,
  including `corner_maps UNIQUE(car, track, owner_user_pk)` (`db.py:320`), the
  crux ACCOUNTS-SPEC:60-71 identified. Laps, corner maps, corners, observations,
  incidents, driver beliefs, coach outputs, sync state, chat transcripts,
  reference exclusions and BYOK keys are all filtered at the read surface.

  **Four things were specified and never built**, each now an open defect:
  1. **`finding_annotations` was never partitioned** (BUG-031). Migration 009
     skipped it though ACCOUNTS-SPEC:143-148 listed it. `db.py:1830` selects with
     no owner filter, `db.py:1838` deletes by `finding_id` alone, and the upsert
     conflicts on `finding_id` only. Finding IDs carry no tenant term
     (`attribution/ranker.py:70`), so two users on the same car/track collide
     exactly. One driver's annotation suppresses another's finding, and their
     free-text note enters the other's chat bundle (`chat/session.py:311`). This
     is ACCOUNTS-SPEC hazard 4 — "must *prove* uniqueness, not assume it" —
     assumed.
  2. **Config is instance-wide with a cross-tenant revert** (BUG-032).
     `ConfigStore` holds one TOML path; `config_history` carries `owner_user_pk`,
     so the audit trail looks per-user while the effect is global.
     `config.py:834` reverts by `change_pk` with no owner filter, reachable from
     `ui/api.py:1716`.
  3. **`/api/sync` falls back to the owner's Garage61 token** (BUG-033).
     `ui/api.py:1824` falls through to `Garage61Client()`, which reads the
     process `GARAGE61_TOKEN` that `deploy/driverdna.service` sets — so a beta
     user who clicks Sync without connecting their own account imports **the
     owner's laps**. `/api/garage61/status` compounds it by reporting
     `connected: true` to everyone whenever the env var is set.
  4. **`tests/test_tenancy.py` does not exist.** ACCOUNTS-SPEC:150-157 named it
     as the *gate* for Phase 2 — two users, overlapping car/track, every read
     endpoint enumerated. The only cross-user isolation tests in 74 test files
     are two in `tests/test_byok_api.py`, covering AI keys. Nothing was deleted
     when A40 moved off Cloud Run; the suite is green (975 passed, 42 skipped)
     and has simply never tested this.

  **Not a hole, but pinned one layer too high.** The blob store is shared, not
  per-user (`blobs.py:114-125`, keyed `<lap_pk>.npz`, rooted per *database*). No
  leak is reachable today because `lap_pk` is globally unique and every API path
  resolves the lap through an owner-filtered query first — but `load_lap_arrays`
  and `has_raw` take a bare `lap_pk` and never check ownership, while the legacy
  fallback beside them does. That is the A34 shape, and A34 is the reason it is
  written down here rather than left to be rediscovered.

  **Also found:** Google OAuth links accounts by email with no `email_verified`
  check and no `google_sub` column (ACCOUNTS-SPEC:88-91 specified one); login
  does not normalize email while register does, permanently locking out anyone
  who registers with a capital letter (BUG-034); `sync_driver` is called with
  `driver="owner"` hardcoded (`ui/api.py:1854`, the BUG-012 defect class); the
  CLI is permanently `user_pk=1`; and the migration-seeded `owner@example.com`
  at `user_pk=1` has a `'placeholder'` hash no password can match, while
  migration 009 backfilled **every pre-A32 row to it** — so all data predating
  A32 belongs to an account nobody can log into (BUG-035).

  **Direction adopted (owner decision, 2026-08-18).** A small invite-only closed
  beta, mixed newcomers and experienced iRacers, with a commercial multi-user
  product as the eventual path:
  - **Registration closes to first-user-only**, with the Cloudflare Access email
    allowlist as the invite mechanism (`deploy/cloudflared/README.md:37-39`) —
    the rule ACCOUNTS-SPEC:105-109 specified and never got. Defence in depth: a
    shared Access session can no longer mint accounts.
  - **Config becomes fully per-user — every threshold, not an allowlist.** This
    **refines philosophy #1 and the AGENTS.md non-negotiable** that "every
    threshold lives in config with a documented default", and it is named here
    rather than slipped in: with per-user measurement thresholds, two accounts
    can produce differently-computed numbers under the same
    `scoring_model_version`. **Mandatory mitigation, not optional:** every stored
    measurement records a fingerprint of the user's effective
    `config_snapshot()` alongside its model version, so a number stays
    reproducible and decomposable exactly as A14 requires. Without that
    fingerprint this change would make "deterministic, versioned,
    confidence-qualified" unverifiable, and must not ship.

  - **Reference-derived numbers pin to the reference lap, not to the importing
    user.** With per-user thresholds, two accounts holding the same coach's lap
    would otherwise disagree about it — there would stop being *the* gap to that
    lap. The cheaper options were offered and **rejected**: letting the importing
    user's config win (self-consistent per cockpit, but not comparable) and
    computing vs-reference findings under instance defaults. Recorded because
    this is the most expensive of the three and was chosen deliberately.

    **The referent is the canonical reference config** (owner decision, same
    day). A reference lap has no account — `laps.driver` is the name on the lap,
    `owner_user_pk` is the importing account — so "the reference's config"
    needed one, and the alternative was rejected on the merits: freezing the
    config at import is simpler and deterministic, but two accounts importing
    the same lap under different configs would still disagree, which is the
    comparability this decision exists to buy. So **reference measurement
    resolves through one instance-level config keyed to the lap's identity**
    (`content_hash` is the existing global handle, already unique per lap
    content and already the dedup key), and every account computes the same gap.

    Stated plainly so it is not discovered later: this is deliberately a
    **carve-out from "config is fully per-user"**. Vs-self findings use the
    driver's own thresholds; vs-reference findings do not, and cannot, if the
    same lap is to mean the same thing in two cockpits. It is the rejected
    "instance defaults" option scoped to reference measurement alone, adopted
    knowingly rather than by drift. Consequences to carry into the build:
    a driver who retunes a measurement threshold sees vs-self findings move and
    vs-reference findings hold still, which the UI must not present as
    inconsistency; and the config fingerprint stored beside a vs-reference
    measurement is the **canonical** one, not the user's, or the audit trail
    would name a config that did not produce the number.

  - **`sync.max_cohorts` default 10 → 40.** A veteran's cohorts past the cap
    never arrive: A49 orders newest-driven-first and names what it skipped, so it
    degrades honestly, but an older cohort does not sync unless it is driven
    again. **Not a model version bump:** `SyncConfig` is ingest scope, and says
    so — "nothing here changes how a lap is scored", only which laps are offered
    to the pipeline. `retention.raw_laps_per_cohort` **stays 100**: it is a
    ceiling, not a reservation, so lowering it saves nothing for the light
    accounts it was proposed for and only ever bites users past 100 laps in one
    cohort. **Audience tiers were considered and rejected** — the two knobs have
    opposite audiences, and one default change does what a tier system would.

  - **Pre-A32 rows are reassigned to the live account** (BUG-035), not stranded.
    Owner's instruction, with the collision rule stated: where a unique
    constraint collides — `corner_maps UNIQUE(car, track, owner_user_pk)` is the
    real case — **the live account's row wins and `user_pk=1`'s is discarded.**
    No merge heuristic; the owner explicitly does not want that data preserved
    at the cost of complexity.

  - **Finding IDs keep their shape** (BUG-031). Partitioning the table closes the
    defect completely; changing `_finding_id` would orphan every stored citation
    in annotations, `evidence_cited` and coach outputs for no additional
    security, and their determinism is a feature. A test asserting **no table is
    keyed on a bare `finding_id`** is the cheap guard against the next table
    repeating this.

  - **Database snapshots move off the VM**; blob loss is accepted as recoverable.
    `deploy/driverdna-backup.service` writes its seven snapshots to the same
    block volume as the database, which defends against corruption but not
    against losing the volume — and the database holds the rows that service's
    own comment calls irreplaceable. Blobs are deliberately *not* backed up:
    `backfill-blobs` reconstructs them from source CSVs, Garage61 still holds
    synced laps, the derived phase times survive in the database independently,
    and retention already evicts blobs by design. To be stated in the runbook so
    it reads as a decision rather than an omission.

  **Nothing in this amendment changes a measurement.** It is documentation plus
  recorded decisions; no committed artifact moves. The `max_cohorts` default
  change above is adopted here and applied in the build pass, not in this
  docs-only commit.
