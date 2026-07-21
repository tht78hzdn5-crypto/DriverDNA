# DriverDNA — Project Brief

Updated 2026-07-20 · branch `claude/plan-review-philosophy-hl3cdg`. Orientation
document for anyone (human or AI) picking the project up. **Verified counts and
the current milestone table live in `docs/STATUS.md`** (dated, reproducible) —
this brief is the durable "what/why/how" and the decision log.

Document set: `docs/ARCHITECTURE_VISION.md` (the constitution — the *why*),
`docs/SPEC.md` (the engine — the *how*, with the amendment log), `CLAUDE.md`
(build rules), `docs/UI-SPEC.md` (the interface), `docs/COACHING.md` (M7 design),
`docs/STATUS.md` (dated status). This brief.

State in one line: engine **M0a–M5 done**; UI **U0–U2 done** (+ render-parity
gate); **M6 (Driver Model) is next to build**, **M7 (Coaching Intelligence)
design is ADOPTED** (not yet built); waiting on laps and two API keys, not on
code.

## What it is

A personal racing-telemetry instrument for one driver (iRacing via Garage61
CSV exports). **It measures the driver, not the lap** — the persistent Driver
Model is the product (constitution, `docs/ARCHITECTURE_VISION.md`). It parses
laps, finds corners, measures technique deterministically, attributes time lost
per corner phase, and — as the Driver Model (M6) lands — accumulates that
evidence into per-fundamental **Score + Confidence + Evidence Count** beliefs
that sharpen as laps pile up. An AI layer (one-shot coaching plan + interactive
chat, and eventually the M7 coaching ontology) explains and prioritizes the
deterministic results; it never invents or computes a number, **including
scores**. Python 3.11+, numpy/scipy, pydantic, typer, SQLite, anthropic SDK;
FastAPI + a built React SPA for the local cockpit. Localhost only — no hosted
anything.

## Philosophy (binding on every change)

1. Coach the driver, not the lap — transferable technique, priced in seconds.
2. The deterministic engine is the only source of numbers; AI explains,
   labels anything beyond the measurements as hypothesis.
3. "Insufficient data" over guessing, always; every claim carries N, spread,
   source tag, evidence IDs.
4. Three sources — `vs-principle`, `vs-self`, `vs-reference` — stay separately
   inspectable; any composite score is deterministic, versioned, and
   confidence-qualified (A14 / ARCHITECTURE_VISION.md), never opaque or
   AI-generated.
5. Reference laps are context ("gap"), never "recoverable time", and never
   enter self history.
6. Longitudinal by design: persistence is the point.
7. Driver sovereignty: annotations, priorities, thresholds — explicit,
   confirmed, versioned, reversible; suppression never deletes a measurement.
8. Personal instrument, not a product.
9. Designed to be distrusted: determinism, evidence IDs, trust gates.

## How it works (pipeline)

```
CSV export (18 channels, 60 Hz, one lap/file, filename = lap ID only)
  → parser: typed numpy TelemetryLap + structured quality flags
    (only permitted repair: pedal clipping to [0,1], counted + flagged)
  → segmenter: corner spans from brake/steering activity (gear-0 excluded),
    nine landmarks per corner, multi-apex complexes kept as one corner
  → identity: per (car, track) corner map — built ONCE from apex GPS
    clusters, frozen, then MATCHED (IDs C01.. never drift/renumber);
    new corners admitted only after N distinct laps, always surfaced
  → classification: slow/medium/fast from median min-speed, with hysteresis;
    class changes are reported events
  → metrics: 18 deterministic per-corner/lap values (METRIC_DEFS carries
    unit + plain-language description) + 5 principle detectors (canon
    checks with rationale; flag form, never priced in seconds)
  → persistence: SQLite — one compressed npz blob per lap (windowed,
    newest-100/cohort) + permanent compact rows for everything queryable;
    role isolation enforced at the query surface (self vs reference)
  → attribution: phase times measured over CANONICAL frozen windows
    (median landmark positions — never a lap's own landmarks), stored
    compactly at import; robust baselines (median±k·MAD outlier screening,
    median-of-top-3 primary, single best labeled)
  → findings: vs-self (tercile opportunity × session-sign repeatability),
    vs-principle (trigger-rate floor), vs-reference (gap-labeled);
    confidence gates (≥10 phase samples, ≥2 sessions, ≥2 tracks for
    rollups) suppress WITH stated reasons
  → report payload: one deterministic versioned dict — the JSON report IS
    this payload; Markdown + self-contained HTML (inline CSS/SVG) render
    from it; driver rollup gates cross-track aggregation (car+class only)
  → coach: provider-abstracted one-shot plan; local validation rejects
    unknown/suppressed finding IDs, unknown evidence, missing hypothesis
    confidence, any number-with-unit absent from the payload
  → chat: deterministic bundle + read-only tools returning live DB values;
    annotations record driver intent; config changes STAGE only —
    /confirm applies through ConfigStore (validated, TOML + history,
    revertible); every response mechanically validated (unknown IDs,
    unsupported numbers → one regeneration, then a surfaced error);
    transcripts persisted with bundle version, evidence, effects
```

## Repository map

```
docs/SPEC.md                      authoritative spec (amended, self-contained)
docs/{schema,corners,metrics,attribution}-report.md   generated artifacts
src/driverdna/
  cli.py          import · corners · metrics · attribution · report · coach ·
                  chat · history · schema-report · version
  config.py       every threshold, typed + documented; ConfigStore write path
  db.py           schema/migrations, blob storage, retention, isolation
  pipeline.py     import orchestration (parse→…→store, windows, reclassify)
  ingest/         contract lock, parser, cohort loader
  corners/        segmenter, identity (build→freeze→match), classify, report
  metrics/        technique metrics, detectors, report
  attribution/    engine (windows/baselines), ranker (findings), report
  report/         payload (the contract), builder (md/json/html)
  coach/          provider (Claude, env-only key), payload, validate, grounding
  chat/           tools (read-only surface), session (grounded loop)
  ui/api.py       FastAPI: pass-through reads + audited writes (no logic here)
ui/               React (Vite) SPA source + tokens.json; built into ui/static
docs/             SPEC, ARCHITECTURE_VISION (constitution), UI-SPEC, COACHING,
                  PROJECT-BRIEF, STATUS, generated reports
tests/            315 tests (17 files); fixtures = 12 real laps + synthetic
                  factories + a Chromium render-parity crawler
```
Exact counts are in `docs/STATUS.md` and reproducible from the repo; treat that
doc, not this one, as the number of record.

## Guarantees currently verified by tests

- Schema lock + absence tests on both real fixtures (exact dirty-data counts).
- Corner IDs stable under jitter/missing/extra corners, GPS-degraded
  fallback, primary-apex flips in chicanes.
- Determinism: two independent imports → byte-identical md/json/html reports.
- Stint-only variation → zero shown findings.
- Reference import: self history/tables/classes byte-identical; gap sections
  only.
- Eviction can never touch summaries or trends.
- Coach/chat grounding: unknown IDs and invented numbers reject (mocked
  provider); unconfirmed config proposals change nothing; confirmed ones are
  written, audited, and reversible.

## What's needed next (in order of value)

1. **M6 — the Driver Model.** Deterministic, versioned per-fundamental scoring
   (Score + Confidence + Evidence Count + trend) over the rows M1–M5 already
   persist. Additive, no key needed; the declared next build. Governed by the
   constitution; scoped in `docs/SPEC.md` (Milestone 6).
2. **M7 — Coaching Intelligence (design ADOPTED 2026-07-20, `docs/COACHING.md`;
   not yet built).** A grounded coaching ontology so the AI *selects and
   phrases* within a fixed, evidence-triggered vocabulary; a confidence value
   never launders an unmeasured inference (no-signal fundamentals get a
   self-check, never a score). Sequenced after M6; a detector-level subset is
   groundable on today's engine.
3. **`sync`: built and live-verified (2026-07-20).** Self-lap ingest from
   the Garage61 API — `Garage61Client` + `sync_driver` + `driverdna sync` —
   ends the manual-upload loop for self laps. A real run against the
   owner's account pulled 25 laps across 25 cohorts with real session/run/
   date metadata; a second and third run were fully idempotent (0 new,
   25 total unchanged); every synced lap was `role='self'`, confirming
   M0b's reference-lap finding live. Reference laps stay manual-import
   regardless (M0b: other-drivers' lap fetch returns `403 forbidden_lap`).
4. **`ANTHROPIC_API_KEY`** → first live coach/chat runs (all logic is
   mock-tested; live runs will shake out prompt/formatting realities).
5. **The owner's independent Spa lap set** → the blind acceptance test. Note:
   session labelling for manual imports is now carried in the fixture manifest;
   a general `import --session` flag (or file-timestamp clustering) is still
   wanted so any manually-imported history is rankable without a manifest.
6. **U4** on the UI track (packaging + shared tokens; U3 chat view done
   2026-07-20), and a deliberate, versioned map/window `rebuild` command
   once tens of laps exist (freezing early trades optimality for
   comparability, by design).
7. More laps, of anything — gates clear at ≥10 phase samples + ≥2 sessions.

## Scaling

- **As a personal instrument (its stated purpose): nothing needed.** SQLite +
  numpy handle years of one driver's data with orders of magnitude to spare
  (a lap ≈ 6k rows; raw blobs are windowed anyway; compact rows are tiny).
  Import cost ~1–2 s/lap, report generation sub-second.
- **If it ever became multi-user** (explicitly out of v1 scope): the compact
  relational schema ports to a server DB (Postgres) largely as-is; blob
  storage moves to object storage; ingest becomes a queued job; the
  deterministic payload becomes an API response; per-user cohort keys add a
  tenant column. The philosophy constraints (no blending, gates, evidence
  IDs) are architecture-independent and must survive any port.
- **The real scaling axis is trust**: keep the determinism byte-diff, the
  trust-gate tests, and the amendment discipline in SPEC.md as the suite any
  refactor must pass.

## The UI (U0–U3 built; U4 remains)

Governed by `docs/UI-SPEC.md`. Built and verified: **U0** the FastAPI layer
(`src/driverdna/ui/api.py`) — pass-through reads (payload endpoints return the
*byte-identical* report JSON) and writes that only wrap the audited engine paths;
**U1** the React SPA (driver home, cohort view with a track outline drawn from
the driver's own GPS, corner drill, finding detail, laps) on the timing-screen
tokens in `ui/tokens.json`, served by `driverdna ui`; **U1 gate 1** a
Playwright/Chromium **render-parity crawler** that asserts every fractional
figure on screen traces to a payload number (136 checked, kept green forever);
**U2** annotations and a config panel through the audited propose/confirm/revert
paths. Node is a build-time dependency only; the built SPA ships in the package.

**U3: the chat view, done (2026-07-20).** `ChatSession.ask_stream` — a
generator yielding `thinking` → `consulting_tool`* → `validating` →
`response`|`error` — is now the single implementation; `ask()` (used by the
CLI and every existing chat test) is a thin wrapper draining it to its last
event, so nothing duplicates the grounding logic. Three new endpoints
(`POST /api/chat/sessions`, `.../messages` via raw SSE framing, `.../confirm/
{n}`) and `ui/src/views/chat.jsx` consume it: text never streams
token-by-token (the validated reply arrives whole), a visible "consulted:
..." tool audit line follows each reply, and a staged config proposal
renders as the same amber-ruled card U2 established, confirmed through
`ChatSession.confirm`. Verified in a real Chromium browser against a
scripted mock provider (session record has screenshots of the full flow:
empty state → tool-call audit → staged proposal → confirmed and cleared;
plus the clean "ANTHROPIC_API_KEY is not set" error card a real user without
a key will actually see). A cross-thread sqlite3 bug surfaced during this
work — a chat session's DB connection outlives the request that opens it,
and FastAPI dispatches sync endpoints to a thread pool — fixed with
`Database.open(..., check_same_thread=False)` for that one long-lived
connection; every other caller keeps the stricter default.

Remaining: **U4** packaging + migrating the static report templates onto
`ui/tokens.json` for one shared look. A DriverModel view follows M6.

The binding rule throughout: the UI renders what the engine computed and never
computes a measurement (mechanically enforced). What does NOT belong in a UI:
re-ranking that ignores gates, editing measurements, or any number computed
client-side. Scores are welcome — but they come from the engine's deterministic
model (M6), carry confidence + evidence count, and are rendered, never computed.

## Decision log (append-only)

Durable record of forks and their resolutions (per the Decision-discipline rule
in `CLAUDE.md`). Newest first.

- **2026-07-21 — Dated manual import built, closing the gap the data-pack
  investigation surfaced.** With `sync` capped at ~1 saved lap per driver
  per cohort (the same-day data-pack findings above), M6 trend's real
  test case needs the driver's own exported history, not the API.
  `driverdna import` gained `--date YYYY-MM-DD|<ISO8601>`, applied to every
  file in a flag-driven import, plus a per-manifest-entry `date` field that
  overrides the flag for that entry — so a mixed-date directory imports in
  one pass. Both paths write `lap_date` through the same field `sync`
  already populates; the trend algorithm itself needed no changes. A
  malformed date is rejected loudly (exit 2, nothing imported) rather than
  silently accepted, since trend sorts laps on this string — a bad value
  would corrupt chronological ordering invisibly otherwise. The committed
  `tests/fixtures/manifest.toml` stays deliberately undated (comment-only
  change documenting the field) so `docs/driver-model-report.md` and other
  fixture-derived regression anchors stay byte-identical. Verified against
  real telemetry, not just synthetic tests: dating the real 11-lap Spa
  fixture cohort by session (via a scratch copy, not the committed
  manifest) produced an actual `declining` trend on `consistency` from
  `driverdna model`, byte-identical across two runs.
- **2026-07-21 — Team data packs deprioritized as a reference-lap path
  (not closed).** Follow-up to the same-day data-packs finding below.
  Probed `GET /teams/{id}/datapacks[groups]` against both of the owner's
  teams (`DriverDNA`, solo; `Blue Flags & Dads`, has another driver): both
  return an identical `401 Missing app scope (not approved):
  team_datapacks_read` — an application-level gate checked before any
  team- or content-specific authorization, so whether either team has a
  published data pack is unknown and unknowable via this API until the
  scope is approved for the app. Owner's real-world read, kept labeled
  separately from anything API-confirmed: data packs in practice are used
  for sharing car **setups**, not lap telemetry, even though the
  documented schema supports a `lap.csv` content item alongside
  `ghost.bin`/`replay.bin`/`setup.sto`. Decision: don't spend the
  approval-friction (self-service vs a Garage61-side request — itself
  unconfirmed) chasing an expected-empty result. Deprioritized, not
  ruled out — if a populated lap data pack is ever confirmed to exist,
  this is still the more architecturally sound path than another `/laps`
  attempt. Decision-of-record #2 stays as-is: manual `import`.
- **2026-07-21 — Garage61's official developer docs obtained and
  cross-referenced; the 403 finding explained, a second reference-lap path
  surfaced, unrelated to any code change.** The live developer portal
  (`garage61.net/developer/*`) is a JS-rendered SPA this session's fetch
  tooling can't reach; the owner supplied the actual pages (Getting
  started, Authentication, Permissions, Endpoints, Webhooks) as PDFs.
  Two things change the M0b record, both in `docs/garage61-api.md`, no
  code touched: (1) the `403 forbidden_lap` finding is now *explained*,
  not just observed — the `driving_data` permission's documented default
  scope is "the authenticated user and their teammates," and the 403'd
  driver in the original probe wasn't a teammate; consistent, not
  contradictory, with `/laps` listings themselves showing dozens of
  non-teammate drivers (the docs distinguish search/listing approval from
  per-lap access — different gates). (2) A structurally distinct,
  completely unexplored mechanism exists for legitimate lap sharing:
  **team data packs** (`/teams/{team}/datapacks/*`, including a
  `lap.csv` export), gated by `team_datapacks_read`/`_write` — permissions
  this token doesn't have. Unlike `/laps` (a per-lap visibility check that
  correctly 403s strangers), data packs are Garage61's own explicit
  content-*sharing* subsystem — the more plausible path for a reference-lap
  feature, if one is ever built. Decision-of-record #2 is **not reopened**
  — manual `import` stays correct for v1 — but SPEC.md now points at data
  packs as the next thing to probe, not another `/laps` attempt with a
  different plan tier. Also recorded for later, not used by anything now:
  the `/analyses` endpoint (a different permission than `driving_data`,
  untested whether its lap coverage differs from `/laps`'s one-per-
  driver-per-cohort shape); OAuth2 (relevant only if A17's deferred
  productization ever happens); and a push-based webhook/live-timing
  subsystem (a different ingestion model than `sync`'s polling, would need
  a public receiver — out of keeping with philosophy #8's local-only v1
  design). Standing caveat now on record: Garage61 states "there is no API
  stability yet" — `sync` is built against a contract that may change.
- **2026-07-20 — M6 trend built; its (previously unspecified) definition
  and three sub-forks resolved.** No doc had ever prescribed *how* trend is
  computed — only that the field is always present and reads "unavailable"
  until dated laps exist. Now that `sync` populates `lap_date`, trend is
  defined as: **the direction of a fundamental's own score between an
  earlier and a recent bucket of the driver's dated laps.** Dated self-laps
  are ordered by `(lap_date, lap_pk)`, split by count at the midpoint, and
  the same scoring function runs on each half via an additive lap-pk
  evidence filter threaded through the M2/M3 query surface
  (`self_metric_table`/`self_detector_table`/`phase_history`/
  `cumulative_loss` gain an optional `lap_pks` param, default None =
  unchanged for every existing caller). Sub-forks, picked deliberately not
  silently:
  (1) *Reuse the full composite score per bucket* (not a bespoke trend
  metric): simplest, and "did my score move" is the honest meaning. Cost:
  the opportunity component's baseline recomputes per bucket → era-relative;
  flagged, not hidden (adherence/consistency are baseline-free and carry the
  signal). (2) *Bucket by lap count, not by calendar midpoint*: equal-N
  halves are more comparable and dodge date-tie ambiguity; determinism from
  the `(lap_date, lap_pk)` total order. (3) *No `scoring_model_version`
  bump* — stays `dm-v1`. Reasoning: dm-v1 always specified `trend` as a
  required output reading "unavailable" pending dates (ARCHITECTURE_VISION
  condition 5); populating it now *fulfils* that contract rather than
  changing it, and score/confidence are byte-identical for every evidence
  set (dated evidence never existed under the old path, so no persisted
  belief is invalidated). A conscious call, revisitable — recorded here so
  it's a decision, not an oversight. Known limitation surfaced by the first
  live run (25-lap synced history, 1 lap/cohort): when dated laps are thin
  per cohort, the two buckets hold different cars/tracks, so a direction
  partly reflects cohort mix — the same era-windowing question A17 deferred,
  sharpening as dated laps accumulate per cohort. Trend *computation* logic
  is the deliverable; a longitudinal *history-over-time* view (storing
  belief snapshots per date) remains a separate future item.
- **2026-07-20 — Product intent recorded: philosophy #8 refined (A17),
  deferred but real.** Owner intent, on the record so post-M6 conversations
  start from a recorded position instead of re-deriving it: DriverDNA may
  eventually go to market — plausibly to veteran drivers with large
  existing lap histories. Nothing changes in the build order; v1 remains a
  personal instrument and nothing is built for multi-user now. Philosophy
  #8 ("Personal instrument, not a product") is refined A14-style, not
  contradicted: **personal instrument first; product potential is
  acknowledged and deferred until the instrument is proven on its owner
  (post-M6, post-blind-test). Any productization keeps the gates,
  no-blending, and evidence-ID constraints unchanged** — those are
  architecture-independent trust properties, not v1 conveniences. Recorded
  as SPEC.md amendment A17; mirrored in UI-SPEC's out-of-scope list, now
  split into permanent exclusions vs. v1-only deferrals (a split flagged
  earlier and pending until this entry).

  *Veteran cold-start (recorded now so it isn't rediscovered later).* A
  marketed DriverDNA meets drivers with ~10,000-lap histories, which
  strains three current design constants: (1) **frozen-from-first-laps
  corner maps and canonical windows** — a bulk historical import freezes
  identity/windows on the oldest data; the planned versioned `rebuild-map`
  command becomes a hard requirement for that user, not a nice-to-have.
  (2) **The vs-self baseline across skill eras** — a veteran's 2019 laps
  and 2026 laps are not one population; tercile opportunity computed
  against a career-spanning history may need era-windowing. Open
  analytical question — noted, deliberately not solved here. (3)
  **Bulk-import ergonomics** — ~1–2 s/lap means hours for a big history;
  acceptable for v1, but one-time-import UX would matter in a product.
  No build work on any of this now.

  *Blob-retention question, answered from the code rather than assumed
  (2026-07-20).* After import, all downstream measurement math reads
  compact rows only — M3 attribution reads stored `phase_times`, and M6
  belief recomputation (`compute_all_beliefs`) reads only compact helpers
  (`self_metric_table`, `self_detector_table`, corner maps/windows,
  session/lap counts). **A scoring-version bump therefore never needs raw
  blobs**, and raising `retention.raw_laps_per_cohort` (newest-100) is
  pointless for that purpose. The one measurement path that re-reads raw
  blobs is corner-admission window backfill
  (`pipeline._freeze_windows_for_admitted`): phase times for a newly
  admitted corner are recomputed from whatever blobs retention still
  holds, and evicted laps are skipped. A future `rebuild-map` has the same
  shape — new canonical windows require re-interpolating t(distance) from
  raw arrays, so **a rebuild can only re-measure laps whose blobs
  survive retention**. That is the one real reason blob retention might be
  raised, and it matters precisely in the veteran/bulk-import scenario
  above. (Also noted while verifying: `coach.include_raw_traces` is
  defined in config but consumed nowhere — raw traces never enter AI
  payloads today; the flag is documentation of intent, not a live path.)
- **2026-07-20 — U3 (chat view) built ahead of the blind acceptance test;
  the U0-U2 exception extended to cover it too.** STATUS.md had recorded an
  explicit owner amendment: U0-U2 could build ahead of the Spa blind test
  "for momentum," but U3-U4 were to "keep the original gate (revisit when
  reached)." The blind test remains blocked — even after today's live
  `sync` run, the account has only one lap each in two different Spa track
  configurations, not the required ≥2 sessions of the *same* cohort. U3 was
  nonetheless built this session (surfaced as a fork mid-build, not
  silently pushed through): CLAUDE.md's own "U3 next on the U-track" status
  line and this build session's momentum argued for proceeding: SSE
  progress, tool-call audit, and the staged/confirm flow are UI-only
  plumbing over `ChatSession` (M5, already fully spec'd and mock-tested)
  and the render-parity crawler's numeric-grounding guarantee, not a new
  measurement claim the blind test is meant to validate — the same
  reasoning the original U0-U2 exception rests on. Owner confirmed:
  extend the exception to U3 (and, by the same reasoning, U4 remains
  ungated too — it's packaging, not new measurement). The blind test
  stays the trust gate for the *engine's findings*, not for shipping a UI
  over findings the engine already produces and validates independently.
- **2026-07-20 — `sync` built on M0b's observed behavior; three forks
  resolved.** (1) *No date-range filtering*: M0b found the real query-param
  names for date-range filtering unconfirmed (tried names silently no-op'd
  rather than erroring); rather than guess, `sync` re-lists a cohort's full
  lap metadata every run (cheap — JSON only) and relies on the existing
  source_file/content_hash dedup to skip CSV re-fetch (expensive) for laps
  already imported. Consistent with the standing "never assume API
  behavior" rule — this is the rule applied to a new call site, not a new
  decision. (2) *Missing/incomplete laps skipped before fetch*: the API's
  lap metadata carries `missing`/`incomplete` booleans a bare CSV can't;
  `sync` treats either as un-fetchable and records why, rather than
  attempting to parse a lap that can't represent a complete single lap. (3)
  *Real session/run/date metadata adopted for the sync path only*: the API
  supplies `event`+`session` (session grouping) and `run` (stint index) —
  both hand-reconstructed on the manual-import path per SPEC.md's source
  contract (no run/stint CSV channel exists). `sync` uses the real values
  directly; `import` is unaffected and keeps reconstructing. `startTime`
  becomes `lap_date`, satisfying M6's trend precondition — trend
  *computation* is intentionally left alone (`model/scoring.py`'s `_trend`
  stays hardcoded "unavailable"; that logic is a separate, self-contained
  addition per its own docstring, not a side effect of sync landing). None
  of the three touch the nine philosophy points or the out-of-scope list —
  they're implementation choices within M0b's already-adopted fallback
  (reference laps stay manual `import`), not new philosophy forks.
- **2026-07-20 — M0b (Garage61 API probe) run and resolved; the reference-lap
  fetch question answered.** With a real `GARAGE61_TOKEN`, `/laps` proved not
  owner-scoped by default (a plain track/car query returns laps from many
  drivers), but `/laps/{id}` and `/laps/{id}/csv` for a lap this token doesn't
  own return `403 forbidden_lap`; own-account laps return `200` with a CSV
  whose header/columns/units match the M0a-locked manual-download contract
  exactly. Resolution, exactly as SPEC.md's Milestone 0b already anticipated
  as the fallback: **reference laps stay on the manual `import` path,
  `role=reference`; `sync` will not be able to pull other-drivers' laps with
  this token/plan.** This refines decision-of-record #2 (reference laps in
  scope, fed by `sync` or `import`) — the "fed by sync" half is now known
  unavailable for the reference role specifically; self-lap `sync` is
  unaffected. Not a nine-philosophy-point or out-of-scope-list change: #2 is a
  decision of record, not a philosophy point, and the spec's own text already
  named this exact contingency before probing — this entry confirms which
  branch of that contingency is real, it doesn't introduce a new one. Also
  discovered: the `Garage_61_<LAPID>.csv` filename code is a different ID
  space from the API's lap `id` (a ULID) — no fixture lap id resolves via the
  API, so the parity check verified CSV structure/units against a freshly
  API-fetched own-account lap instead of a byte-exact fixture match. Full
  observed evidence: `docs/garage61-api.md`. Network note: this session
  reached `garage61.net` successfully — an earlier snapshot's belief that
  network policy blocked it (see `docs/STATUS.md`, corrected in the same
  edit as this entry) no longer holds, at least for this session.
- **2026-07-20 — COACHING.md flipped to adopted; two load-bearing rules added.**
  (1) *Conviction where measured, silence/self-check where not*: a confidence
  value never launders an unmeasured inference — "Vision, 30% confident" is
  forbidden; no-signal fundamentals never emit a score or confidence at any
  level, full stop. On measured ground the coach commits with no hedging,
  fixing "too hedged to be useful" without loosening grounding. (2)
  *Self-checks* replace scores for no-signal fundamentals — a driver-runnable
  in-car exercise, labeled a coaching hypothesis, in the schema slot where a
  score would otherwise go. Checked against the philosophy in the same edit:
  consistent with #2 (a self-check is interpretation, not a computed number)
  and #3 (it's what "insufficient data" *does* here, not a dead end); does not
  contradict `ARCHITECTURE_VISION.md`'s "— · 0% · no telemetry signal" score
  convention (M6's score table and M7's coaching layer enforce the same rule
  at two different layers — a fixed "0%" flag is not a graduated confidence
  value). Also formalized **gap-band eligibility** (coarse, absolute,
  versioned loss/trigger-rate bands controlling loud/quiet/silent delivery
  tone, looser-gated than the full M3/M6 statistical finding gates so there's
  usually something real to say even at a handful of laps — flagged as a
  formalization of prior intent, correct if it diverges) and fixed a defect in
  the seed set the new rules exist to catch: the original `be_patient`
  conflated a measurable-but-weak fundamental (commitment) with a truly
  unmeasurable one (vision/eye-line) under one id and description; split into
  `trust_the_proxy` (proxy, tentative) and `look_further` (no_signal,
  self-check, nine principles now). Record: `docs/COACHING.md`.
- **2026-07-20 — Trend and evidence_count made required M6 outputs (constitution
  condition 5).** Every Driver Model belief carries `trend` and
  `evidence_count` as first-class fields, always — never dropped for
  convenience when data is thin; they hold an explicit "unavailable" value
  instead of being omitted from the schema. This is the longitudinal guarantee
  the mission promises and it doesn't get to quietly disappear under
  implementation pressure. Recorded in `ARCHITECTURE_VISION.md` (Scoring
  Contract, condition 5) and mirrored in SPEC.md's M6 section; not a new
  lettered SPEC amendment (A-series is reserved for changes to SPEC.md's own
  engine content or the nine philosophy points — this clarifies an M6 output
  contract rather than refining either).
- **2026-07-19 — Coaching Intelligence adopted as M7 (design stage).** A grounded
  coaching ontology (`technique → driving principle → coaching principle`) where
  the AI selects/phrases within a fixed, evidence-triggered vocabulary. Checked
  against the philosophy: consistent with #2 and the out-of-scope list; no
  contradiction. Spec `docs/COACHING.md`; awaiting owner reaction before build.
- **2026-07-19 — Scores adopted; philosophy #4 refined (A14).** Owner chose
  *deterministic, versioned, reproducible* scores that always ship **Score +
  Confidence + Evidence Count** and decompose to their sources; AI explains and
  prioritizes, never computes. Reason: scores are the product's headline value;
  AI's role is to articulate, not invent. **Refines philosophy #4** ("no overall
  score" → "no *opaque* blended score"); recorded in `ARCHITECTURE_VISION.md`
  and SPEC A14. Constitution `docs/ARCHITECTURE_VISION.md` adopted the same day.
- **2026-07-19 — Content-dedup + contract widenings (A12–A13).** Real laps forced
  three fixes: 0-or-1-wrap laps are valid (+ partial-lap guard); steering can
  exceed 2π at hairpins; `PositionType` is an enum not a constant; and a
  re-downloaded lap is rejected by content fingerprint, never double-counted.
- **2026-07-18/19 — UI adopted (UI-SPEC); U0/U1/U2 built ahead of the blind
  test** for momentum (owner call); U3–U4 keep the original gate.
- **2026-07-18 — Filename contract corrected (A11).** Garage61 filenames carry a
  lap ID only; identities/lap-times moved to `tests/fixtures/manifest.toml`.
- **2026-07-18 — Ten review findings (F1–F10) folded in before building**;
  Python chosen (owner had no preference). Constitution philosophy confirmed.
