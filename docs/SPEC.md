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
8. **Personal instrument, not a product.** Local CLI, SQLite, static reports. No
   server. Simplicity and auditability outrank generality.
9. **Designed to be distrusted.** Determinism tests, evidence IDs on every claim,
   trust gates. The architecture assumes verification before belief.

## Decisions of record

1. Ingestion: `sync` via the Garage61 developer API is the primary path; directory
   import of manually downloaded CSVs is a retained fallback using the identical
   parser.
2. Reference laps are in scope. Lap role is `self` or `reference`. Reference laps
   feed per-corner reference envelopes and gap analysis only — never the driver's
   technique history, trends, or consistency statistics.
3. Every finding carries a source tag: `vs-principle` (canonical technique checks —
   catches uniform weaknesses), `vs-self` (faster-vs-slower × stability), or
   `vs-reference` (gap to faster drivers). Reported separately; never blended into
   one score.
4. Persistence is required (SQLite). A stateless directory analyzer contradicts the
   product's purpose.
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

- `Garage61Client`: token auth (`GARAGE61_TOKEN`, env only), list own laps with
  car/track/date filters, fetch lap CSV, incremental sync state in DB.
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
- SQLite: raw lap samples stored as one compressed blob per lap (laps are always
  loaded whole; nothing queries individual samples by SQL); compact relational rows
  for everything queryable — lap metadata, quality flags, corner landmarks, metric
  values, findings, evidence refs, report outcomes, reference envelopes, sync
  state, coaching outputs, chat transcripts, and config history. Eviction of a
  lap's raw blob is a single-row delete that never touches summaries. Migrations
  under test.

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
  db.py                        # SQLite schema, migrations, blob lap storage, eviction
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
  is surfaced in the report, never silent.
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
- **Known v1 limitation, flagged not silently accepted (2026-07-20).** The
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
  require). **Trend needs real lap dates** — a dependency on sync metadata or a
  user-supplied date on import (flagged; degrades to "trend unavailable"). Per
  `ARCHITECTURE_VISION.md`'s Scoring Contract condition 5: `trend` and
  `evidence_count` are **required fields on every belief row, always** — when
  ungated data isn't available they hold an explicit "unavailable" value, they
  are never dropped from the schema for convenience.
- **AI role (unchanged contract).** Coach/chat gain the beliefs in their
  payload/bundle and may *explain* a score and *recommend the highest-impact
  practice priority*; they never produce or adjust a score (enforced by the
  existing numeric-grounding validator — a belief is just another payload
  number). Every score is presented with its confidence, evidence count, and a
  plain "this is a model estimate; here's how to sharpen it."
- **Artifact:** `driverdna model` — the per-fundamental score / confidence /
  evidence table, deterministic. A DriverModel UI view follows on the U-track.

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
- **Known v1 limitation, flagged not silently accepted.** `same_lap_twice`
  (the one principle with no phase to band on — consistency is cross-cutting)
  pools coefficient of variation across every measured metric on a corner,
  unweighted, mixing metrics of very different scale/type (percentages, rates,
  small integer counts). A low-mean count metric can produce an outsized CV
  that dominates the average — the same underlying issue as M6's cross-cohort
  `consistency` caveat, one level down (per-corner instead of per-driver). See
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
   with no hints. Top findings must independently include high-speed-corner entry
   commitment and elevated entry-phase inconsistency (known ground truth: Sector 1,
   ±1.2 s spread vs ±0.4–0.7 s elsewhere). Failure blocks trusting any novel
   finding. Caveat, recorded honestly: the expected answer is written in this spec,
   which the builder reads — so this is a smoke test against gross failure, not
   independent proof.
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

Hosted sync, **AI-generated or unconfidenced scores** (deterministic
confidence-qualified scores are in scope via M6), slip/vision inference,
automatic AI refresh, non-Garage61 sources. Cross-car claims remain computed
but unreported until sample size justifies them. The local UI layer is
specified separately in **docs/UI-SPEC.md** (owner-adopted 2026-07-19); the
Driver Model (M6) is governed by **docs/ARCHITECTURE_VISION.md**. This spec
remains authoritative for the engine, and every surface renders what the engine
computed — it never computes a measurement.

## Setup and build order

- Environment: `GARAGE61_TOKEN`, `ANTHROPIC_API_KEY` (env only; never persisted,
  printed, or logged). Python 3.11+.
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
