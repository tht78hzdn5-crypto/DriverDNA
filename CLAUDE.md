# DriverDNA — build rules

Racing-telemetry instrument, **multi-user since A32** (2026-07-28 — philosophy
#8 reversed by owner decision; audited and reconciled by A53, 2026-08-18). The
binding build rules for every agent — non-negotiables, decision discipline, build order, commands,
testing rules, and the multi-agent working agreement — live in `AGENTS.md` and
are imported here rather than restated:

@AGENTS.md

They are a separate file because they have to be portable: Gemini CLI and
Antigravity also work on this repository, and Antigravity silently refuses a
rules file over 12,000 characters, which this file exceeds. One copy, no drift —
`tests/test_agent_contract.py` enforces both halves of that.

What follows is Claude-Code-facing and specific to this repository's history:
where the build actually stands, and the UI layer's own rules. `docs/STATUS.md`
is the cross-agent dated snapshot; where the two disagree, STATUS.md wins.

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
- **"Done" means merged (2026-08-03, owner instruction; AGENTS.md's
  Branches-and-merging section is the binding copy).** A remote/CCR session
  can be harness-assigned a feature branch instead of `main` directly — that
  assignment governs where commits land mid-session, it does not change what
  counts as finished. Prompted by a real case: a session did solid, tested
  work (SPEC.md A33/A34 below) entirely on such a branch and reported it as
  "done" while it sat unmerged. Going forward: every session ends by merging
  its branch to `main`, or by saying plainly, in the chat, why not (a design
  doc awaiting the owner's go, like R4 below, is a legitimate "why not" — an
  untested change is not). Do not just report green tests and a push as
  finished; state the merge outcome explicitly.
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
- **UI design language v2 ("pit wall"): U5 built (2026-07-22)** —
  owner-directed redesign, spec in UI-SPEC.md §"Design language v2", now
  live in the SPA. Palette and colour grammar untouched; a condensed Plex
  display face carries structure labels only (self-hosted 600/700, offline
  intact), one top-right chamfer is the geometric tell, a three-tier button
  system replaced text-link actions ("an action is a button, navigation is a
  link"), a constant six-tab shell (Driver · Model · Garage · Chat · Import ·
  Config) with a per-view context strip replaced the shape-shifting nav, a
  new Garage view (view 8) is the cohort index over the existing
  `/api/cohorts`, and driver home is now the rollup + pit-board stat tiles.
  Reference-lap visibility folded in (R1): tile + panel, guarantee line,
  "ref n=K" on gap findings, a "References" line over one read-field
  addition (`driver` on `/api/laps`), N=0 direction state. Copy trimmed per
  the owner's "very wordy" note (binding "Copy density" rule in UI-SPEC.md).
  `_TOKENS` byte-match green; five trust gates green; built SPA reships
  in-package. `#/garage` added to the offline route list only (no
  measurement to parity-crawl, like `#/upload`); no reference lap seeded
  into the shared fixture (parity-clean by construction). Mockup:
  docs/ui-redesign-mockup.html.
- **UI design language v2: U6 "cockpit actions" built (2026-07-26)** — the
  write-side half, unblocked once U5's gates passed. `POST /api/sync` wraps
  `sync_driver`, constructing `Garage61Client()` straight from
  `GARAGE61_TOKEN` (never from the request); `POST /api/cohorts/{slug}/
  rebuild-map` resolves the slug and wraps `rebuild_cohort_map` (the A22
  in-place refreeze), 404ing on an unknown slug or a resolvable cohort with
  no frozen map. Both are pure wrappers (no business logic in `api.py`),
  proven byte-identical to the CLI: `tests/test_cockpit_api.py` syncs a
  mocked `Garage61Client` (canned lap listing + CSV bytes, never live/a real
  token) through the endpoint and `driverdna sync` to independent fresh DBs
  and diffs the lap/observation/sync-state rows; a real fixture cohort is
  copied to two DBs, rebuilt via the endpoint and `driverdna rebuild-map`,
  and the `corners`/`corner_windows`/`phase_times` rows diffed; a dedicated
  test proves an unset `GARAGE61_TOKEN` returns HTTP 400 and never opens the
  DB. UI: a `btn-primary` **Sync** on driver home (missing-token state is a
  `.reason` guidance line, never an input field — the secret never transits
  the browser) and a `btn small` **Rebuild map** in the cohort context strip
  behind a client-side confirm/cancel gate, rendering the rebuild report
  (per-corner shift/window/re-measured/cleared, admitted, class changes, the
  cleared-stale-phase notice) and refetching the payload afterward. Four
  implementation-time decisions flagged in UI-SPEC.md's U6 section (details
  left open by its seven conditions, not changes to them): both endpoints
  require a pre-existing DB like every write endpoint but `/api/laps/upload`;
  the missing-token error is HTTP 400 specifically; `/api/sync` returns a
  bare `list[CohortSync]` rather than an upload-style `{results, evicted}`
  wrapper; Sync lives on driver home only, not duplicated onto Garage. Five
  trust gates green, no route-list changes needed; suite 518 → 530 (12 new
  tests, `test_cockpit_api.py` + `test_cockpit_ui.py`).
- **Single-driver auth built (2026-07-27, SPEC.md A31)** — `docs/DEPLOY-SPEC.md`
  track H1, adopted 2026-07-26 and never built while the Cloud Run deploy
  shipped anyway, so the live service had every `/api` route open behind
  nothing but `--no-allow-unauthenticated`. `DRIVERDNA_ACCESS_TOKEN` (env-only,
  same non-negotiable as every other secret) exchanges at `POST
  /api/auth/login` for a signed, expiring, HttpOnly/SameSite cookie
  (`hmac.compare_digest`; signing key derived from the passphrase, so rotation
  *is* revocation; stateless, so it survives Cloud Run's N instances). One
  app-level FastAPI dependency guards every route — so a future endpoint is
  guarded by default, and DEPLOY-SPEC's done-criterion test enumerates
  `app.routes` to keep it that way. `driverdna ui` now refuses a non-loopback
  bind with no passphrase (`_is_loopback` fails closed); write-path hardening
  landed with it (per-file upload cap + CSV type check, `/api/chat/*` rate
  limit, `no-store` on every API response). SPA: a sign-in gate rendered
  instead of the shell, and any 401 anywhere returns to it — no `credentials`
  or header changes were needed, since every call is same-origin.
  **Stdlib only, by constraint not preference:** a browser-side identity
  provider (Auth0/Clerk/Firebase/Supabase Auth) is mechanically excluded by
  `test_ui_static.py` (bundle contains no `https://` — fails in CI, no browser)
  and `test_offline.py`; a server-side OIDC flow *would* pass both and was
  rejected on cost/benefit, recorded rather than left implied. No third-party
  origin at either level, so **no trust gate was amended**. Auth is off when no
  passphrase is configured — the local instrument is unchanged and every
  pre-existing test passed unmodified. 725 passed / 0 failed (from 644/1: the
  `AGENTS.md` size-budget failure on `main` was pre-existing and is fixed).
  ⚠️ `Dockerfile` binds `0.0.0.0`, so **Cloud Run needs the secret set before
  this merges** or the service will not start; exposure itself is unchanged.
- **`driverdna census` built (2026-08-02, SPEC.md A33)** — the corpus answers
  "do I need more lap data?" itself, instead of an agent hand-reading a payload
  and re-deriving the confidence formula. `census.py` reports have-vs-need for
  every gate (the four confidence floors, `min_evidence_for_score`, trend's
  dated-lap buckets, `min_phase_samples`/`min_sessions`/`min_tracks_for_rollup`,
  reference-lap presence) and ranks what to add next. Applies **no gate of its
  own**: thresholds are read from config and every suppression reason is the
  exact string the engine emitted, read back off `build_cohort_payload`'s
  findings and `build_driver_payload`'s rollups — paraphrasing was rejected
  because a census that explains a suppression in its own words can drift from
  the real gate and call a corpus ready when it is not (two tests pin the
  strings against the payload, not against literals). Where a gain is not
  computable it prints `—`: closing a corpus-level term (sessions/tracks/cars)
  moves it by an amount identical for every fundamental and is stated as a
  number, but how much a lap raises `evidence_count` depends on which corners
  it produces, so census refuses to project it. One refactor enabled it —
  `_confidence`'s four ratios are now exposed as `confidence_terms()`, with
  `_confidence` their mean plus the unchanged proxy cap; **number-neutral and
  proven so**, all six committed `docs/*-report.md` regenerate byte-identical
  and `test_scoring.py` passes unmodified. First real-fixture run: confidence
  ceiling 60.2%, **15 of 177 findings shown**, 75 of them blocked by the
  single-lap Mustang cohort. Deliberately no UI surface; the corner-map
  admission gate is not reported (no read-only pending-candidate query exists).
  Suite 726 → 744.
- **Reference-lap isolation restored at the corner map (2026-08-03, SPEC.md
  A34)** — the owner supplied a reference lap plus six of their own Mustang GT4
  laps at Spa, so the **vs-reference path ran on real data for the first time**
  (30 gap findings, 6.54 s of a real 10.73 s lap-time gap; all still suppressed
  at 5–6 phase samples < 10, so ~4–5 more GT4/Spa laps is the concrete ask).
  Running it exposed that reference laps were defining the driver's own
  geometry. The measurement layer's `role='self'` filters were never the whole
  guarantee: the **corner map** is the coordinate system those measurements are
  taken in, and three paths wrote reference geometry into it — **founding** (the
  first lap in a cohort builds the map, and nothing checked its role: one
  reference CSV into an empty store produced an 11-corner map), **admission**
  (`admit_pending_candidates` counted reference laps toward
  `min_laps_for_admission` and fed their apexes to the new centroid), and
  **rebuild** (A22's refreeze read `corner_apex_positions` /
  `observation_positions`, neither of which even joined `laps` — so an audit for
  an unfiltered `JOIN laps` missed them). Measured on the real GT4 cohort:
  **11 of 14 corners moved** (largest 46.94 m), **11 of 14 windows differed**,
  **154 of the owner's 191 phase times changed** by up to **1.57 s**; on the
  GR86 fixture cohort the admission path alone moved `consistency` 34.31 →
  32.26. Fixed by refusing a reference lap as its cohort's first (before the
  lap row is written; itemized exit 2 / HTTP 422, and on a cold start the
  upload refuses before the store is created), and by making admission and both
  refreeze queries self-only. **Isolation is not exclusion** — reference
  observations are still linked and measured, they just never vote on where a
  corner is. **No committed number moved**: 7/7 `docs/*-report.md`
  byte-identical, because both fixture manifests hold zero reference laps —
  which is also the blast radius. The existing M3 guard
  (`test_reference_import_perturbs_gap_sections_only`) passes honestly and
  always did: its synthetic reference lap matches existing corners, so the
  admission path never runs and it never rebuilds — the guarantee was pinned
  one layer above where it broke. Flagged: a cohort founded by a reference lap
  *before* this fix keeps its stranger-built map (the refusal guards new
  imports, not existing rows); `rebuild-map` is the recovery path. Suite
  744 → 761.
- **Bug log adopted (2026-08-09, owner instruction)** — `docs/BUG-LOG.md` is
  the defect register: one entry per real bug, open or fixed, recording what
  broke, root cause, blast radius, and **how it was caught or how it was
  missed**. Seeded from the repo's own history (20 entries; 3 open —
  the two 2026-08-08 VM blockers, plus BUG-020: nothing mechanically checks
  that committed artifacts match regenerated output, which is why A42/A43
  left three of them stale for days). Deliberately exempt from AGENTS.md's
  "no other status docs" rule — it is a register, not a snapshot, and it
  cross-references SPEC amendments rather than restating them. Filing is now
  binding (AGENTS.md, Decision discipline). Paired standing rule, added to
  the shared non-negotiables block so every agent gets it: **never assume a
  failure is synthetic** — a failing test, error, or wrong number is real
  until proven otherwise, and unexplained red is an open bug, not noise.
- **Feedback reads by racing fundamental (2026-08-09, SPEC.md A46)** —
  owner-directed readability pass on "the feedback section and language".
  The real cause was structural, not just wordiness: the cohort page ran two
  feedback layers in two voices — M7's coaching already spoke racing, while
  the findings section below restated the same triggers in engine voice,
  grouped by `vs-self`/`vs-principle`/`vs-reference` (how the engine *knows*,
  not how you drive), with detector slugs (`coast-window`,
  `one-steering-input`) read as English and `"Gap is context, not recoverable
  time."` stamped on every reference row — 30 times on the owner's real
  GT4/Spa cohort. Now: `taxonomy.phase_fundamental()` (measured claimant
  wins, so proxy `commitment` never adopts a measured finding — the
  precondition is test-pinned), `DETECTOR_LABELS`, and `Finding.fundamental`
  let cohort page, corner drill, Markdown and HTML all group by braking /
  rotation / corner exit from **one** engine authority. Each row keeps its
  source tag, so SPEC decision 3 holds and nothing is blended; UI-SPEC
  decisions 6 and 7 are amended explicitly, not silently. Supporting data (N,
  spread, gap band, the whole suppressed pile with every gate reason
  verbatim) moved behind the existing disclosure arrow. Deliberately **no**
  per-fundamental seconds total: `cumulative_loss` is per phase and `entry`
  maps to two fundamentals, so the renderer summing it would be the UI
  computing a measurement. One correctness fix rode along: `vs-principle`
  descriptions printed the *first triggering lap's* rationale as if it
  characterised the corner — now in `details["rationale"]`, labelled as one
  lap. `PAYLOAD_VERSION` 6→7 (additive strings only; `coach-v3`/`chat-v3`
  untouched). **Number-neutral, proven against a clean-`main` regeneration:**
  the only value that moved is `payload_version`. ⚠️ Flagged: three committed
  artifacts (`docs/coaching-report.md`, `driver.*`,
  `gr86-spa-francorchamps.*`) were **already stale on `main`** from A42's
  `coach-onto-v2` and A43's census — regenerated here, so most of their diff
  is that catching up, not A46. Suite 908 → 924.
- **Fundamentals read as landmarks; the feedback section reads as coaching
  (2026-08-10, SPEC.md A48)** — owner-directed follow-on to A46, which put the
  right structure on the page and left the rendering behind it (`.fgroup-name`
  was 0.92rem against 0.86rem finding rows, on a `--line` rule with almost no
  contrast, and the racing sentence sat *below* the header). Chosen from a
  mockup, not from prose: four treatments built against the real GR86/Spa
  fixture — every sentence and figure real engine output —
  (`docs/ui-fundamentals-mockup.html`), owner picked **"lens rule"**. One rule
  runs the height of a group, brightest where the fundamental is named and
  fading down it, with a **tier mark** (the Driver Model pyramid in miniature,
  this fundamental's tier lit) sitting on it; the same treatment carries onto
  `#/model`'s meters, and `ui/src/views/pyramid.js` holds the tier geometry
  once so the full-size pyramid and the 22px mark cannot become two shapes.
  Each fundamental now opens with its top-ranked principle in full —
  expression, driving principle **and the drill**, which had rendered on the
  single headline card only, so eight of the nine seed principles carried a
  practice step the driver could never see; the measurements collapse into one
  disclosure per group, and the headline's fundamental carries a `priority`
  chip (which retires `CoachingSecondary`'s "Same as the headline above"
  branch). **The owner's "hide the vs-self/vs-principle/vs-reference stuff" is
  implemented as collapse, never delete** — every row stays in the DOM with its
  source tag and the parity crawler reads inside closed `<details>`, so
  AGENTS.md's evidence guarantee and UI-SPEC decision 6's binding half are
  untouched; deleting the tags would contradict the constraint the same request
  opened with and needs its own owner decision. Also rejected, and recorded:
  the Driver Model score on a cohort group header (it is driver-level, pooled
  across every cohort). The static report gained a section it had been
  dropping — a fundamental the engine can coach but has no shown finding for
  (`consistency`: a major signal at sixteen corners). Number-neutral:
  `PAYLOAD_VERSION` stays 7, both JSONs and all eight `docs/*-report.md`
  byte-identical, the cohort `.md`'s numeric multiset identical, the two HTML
  reports' reader-visible numerals identical with every delta inside `<style>`.
  Suite 963 → 971, 16 Postgres skips, 0 browser skips.
- **Sync bounded by cohort, newest first; pit-lane laps counted before they
  are judged (2026-08-11, SPEC.md A49)** — owner-directed. An account holds a
  cohort per (car, track) ever driven (~25 for the owner), and sync listed
  every one on every run while `discover_cohorts` sorted *alphabetically* — the
  one order carrying no information about which combos are live.
  `config.sync.max_cohorts` (default 10, `0` disables) caps the run, and
  discovery now orders newest-driven first off `/me/statistics`' `day`, a field
  that was already in the response and being thrown away. **The trade is
  recorded, not implied:** `sync_driver` deliberately keeps no automatic
  watermark (`after` filters on when a lap was *driven*, not synced), and a
  cohort cap reintroduces exactly that one axis up — so only the cohort axis is
  capped (within a synced cohort the full listing is still re-read) and every
  skipped cohort is reported **by name with its last-driven date**, never as a
  count. That is deliberate: `day`'s format is documented nowhere and is
  compared as a string (right for `YYYY-MM-DD` and ISO-8601, wrong for an epoch
  int), so a wrong ordering has to be visible on the first run; a dateless row
  sorts oldest, and if no cohort has a date the cap is refused outright and the
  full sync runs. **Pit-lane laps are counted, not dropped:** formation laps
  never arrive (the API's `lapTypes` default is normal laps only), so what
  remains is a normal lap that began in the pits, flagged `pitlane` — also
  undocumented, and its two readings imply opposite behaviour, so
  `skip_pitlane_laps` ships **off** with `CohortSync.laps_pitlane` surfaced in
  CLI, SSE and SPA. Number-neutral by construction; all 14 committed artifacts
  byte-identical. **BUG-022 fixed (2026-08-14, A50):** a towed lap's *trace*
  duration was used as if it were a lap time — `payload.py` measured
  `lap_delta_s` against `min(duration_s)` with no completeness check, so a lap
  ending in a virtual tow became the cohort's "fastest" (measured: 68.50 s vs a
  real 171.25 s lap, which then rendered at +102.75 s). Fixed by reading the
  existing `INCOMPLETE_LAP` quality flag: `build_cohort_payload` now computes
  `lap_delta_s` from complete laps only and exposes a parallel `lap_incomplete`
  boolean array (`PAYLOAD_VERSION` 7→8); incomplete laps get `null` deltas, an
  "incomplete" chip in the SPA lap board, and are filtered from the line chart
  and the reference envelope. The per-corner layer was already correct by
  construction (the segmenter finds 4 corners instead of 14 on a 40% trace).
  Owner-stated intent, now binding: incomplete laps are **wanted** (a tow is
  the incident record, A19), so the fix keeps them and stops mis-reading one
  column. Three more
  defects found on the way: `main` was red from PR #21 (BUG-023, fixed);
  `ruff check .` red from fifteen dead root scratch scripts — one-shot
  `db.py` rewriters left over from the identity/Postgres work, deleted
  owner-directed, so the `lint` gate is green rather than permanently red
  (BUG-024, fixed); and **all 26 browser tests had been
  silently skipping** (image ships Chromium 1194, Playwright resolves 1234),
  which had hidden a broken `/api/cohorts` assertion on this branch for two
  commits (BUG-025, fixed — 26 browser tests now run and pass).
  Suite 971 → 993 passed / 16 skipped (Postgres-absent only) / 0 failed, with
  the 26 browser tests running again for the first time in this environment.
- **BUG-018 closed-undiagnosed; BUG-027 fixed; persistent journald
  (2026-08-15)** — BUG-018 (Oracle VM 1033 outage, 2026-08-08) cannot be
  diagnosed: journald defaulted to volatile storage and every crash log was
  lost on reboot; the service recovered on `Restart=always`. Both real bugs
  found during the same triage are now fixed (BUG-026 heartbeat, BUG-027
  auth-expired). BUG-027: `Garage61AuthError` (HTTP 401 from an expired OAuth
  token) was caught by a generic `except Exception`, surfacing a raw traceback.
  Now caught specifically at both sync surfaces — the SSE worker emits a
  structured `auth_expired` error event, the SPA renders a reconnect link, the
  CLI exits 2. `deploy/journald-driverdna.conf` (`Storage=persistent`,
  `SystemMaxUse=200M`) + runbook Part G make future outages diagnosable.
  Suite 993 → 997 passed / 16 skipped / 0 failed.
- **Reference laps: surveyed + planned, nothing new built (2026-07-22)** —
  `docs/REFERENCE-LAPS.md` is the source of truth: the machinery exists and
  is tested (role column, query-surface isolation, shared (car,track)
  corner maps, `reference_envelope`/`vs_reference_findings` through
  payload/report/UI; manual `import --role reference` only, per M0b/A16)
  but has never fired — the DB holds zero reference laps since `sync`
  structurally can't fetch them. Doc: owner-runnable recipe, six gaps,
  design-stage R-track (R0 feed-and-pin gate → R1 visibility → R2
  identity/depth → R3 curation), open decisions flagged. R1 (see &
  understand) is folded into U5 per UI-SPEC.md "Reference-lap visibility":
  N=0 direction state + button, isolation guarantee line, reference stat
  tile, "ref n=K" on gap findings, "References" line over one read-field
  addition (`driver` on `/api/laps`). Awaiting owner reaction.

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
- **Deployment store returns to SQLite on an Oracle VM; Supabase/Cloud Run
  retired (2026-08-05, SPEC.md A40, owner-directed)** — the hosted Supabase
  project went over its egress limit. This *refines, not repeals* A23: SQLite
  was kept first-class precisely for this fallback, and the Postgres backend
  stays a supported, tested second backend and the reversible path. Migration
  is `driverdna store-copy` (Postgres → SQLite, checksum-verified, PK-
  preserving) for the compact rows plus the new `driverdna backfill-blobs
  --from <csv-dir>` for historical raw traces (a plain re-import is a no-op —
  copied rows already dedup by content hash — so backfill matches each CSV to
  a lap by content fingerprint and writes only the missing `<lap_pk>.npz`,
  never touching a lap row). Blobs were never in Supabase and were ephemeral on
  Cloud Run; on the VM they land on the durable block volume. Number-neutral,
  no model-version bump. Network shape: a public URL via Cloudflare Tunnel +
  Access (owner's choice, DEPLOY-SPEC H2's public-URL option), app auth still
  on. Code + docs + `docs/DEPLOY-RUNBOOK.md` + systemd unit land now;
  `.github/workflows/deploy.yml` (Cloud Run) is retired; VM provisioning, the
  cutover, and deleting the Supabase project are owner-executed runbook steps.
- **Real root cause of the Cloud Run sign-in bounce + the auth-layer changes
  A40's VM target needs (2026-08-05, SPEC.md A41)** — a parallel session
  (`docs/VM-MIGRATION.md`, branch `claude/driverdna-access-link-m6uv7f`,
  commit `cd9296f`, referenced not duplicated) found the sign-in bounce four
  prior sessions tried to fix by editing auth code was actually two unset
  deploy secrets: `--db ""` silently opened SQLite's evaporating private temp
  database. Fixed regardless of platform: `resolve_store("")` now raises
  instead of silently opening it; the ephemeral session-secret fallback is
  retired (owner-confirmed) and the interlock fails closed instead — a
  restart no longer silently signs everyone out; `/health` now reports
  `store`/`auth` (enum/bool, never secrets). New for the VM+reverse-proxy
  topology: `driverdna ui --behind-proxy` closes the most severe finding — a
  proxy in front of a *loopback*-bound instance defeated the interlock
  silently (bind looked safe, auth was actually off). It applies the
  fail-closed interlock regardless of bind address, explicitly wires
  `uvicorn`'s proxy-header trust to `127.0.0.1` only (verified: uvicorn
  0.52.1 already defaulted to exactly this — now an intentional, tested
  contract instead of an implicit library default), and switches `_is_https`
  to the now-reliable `request.url.scheme`. `deploy/driverdna.service` now
  passes it. One source-analysis finding (rate-limiting/`_client_key`) was
  re-verified empirically and found already-correct given uvicorn's real
  defaults — narrowed with a real `ProxyHeadersMiddleware` integration test
  rather than taken on faith either way. Suite 885 → 899 passed, 16 skipped
  (same Postgres-absent set), 0 failed.
- **UI v3 "cockpit feel" + U7 mobile + incidents-for-newcomers + Gemini
  provider + BYOK: built (2026-08-02, `docs/UI-V3-PLAN.md`, SPEC.md
  A35/A36/A37/A38)** — owner-directed. Chrome-accent tokens + micro-motion;
  the engine-sourced `.disclosure` "methodology arrow" pattern
  (`explain.py`/`GET /api/explain`); a wide-viewport two-column layout; the
  score-history chart (`dm-hist-v1`, generalizes M6 trend's 2-bucket
  machinery to N, no new kind of number); the mobile responsive pass + PWA
  shell; incident cards with plain-language mechanisms/drills behind one
  disclosure click, unclassified incidents still honestly causeless; chat's
  M5-era incidents boundary lifted, additively (a classified incident
  becomes citable, an unclassified one stays structurally uncitable);
  `GeminiCoachProvider`/`GeminiChatProvider` (default provider, built and
  mock-tested against the real installed SDK's actual objects, **then
  live-verified (A38)**: a real, owner-supplied `GEMINI_API_KEY`, used
  once and rotated immediately after, surfaced two real defects —
  `coach.max_tokens`'s 4000 default silently starved the thinking-model
  provider (raised to 16000), and `coach`'s system prompt had two
  ambiguities Gemini hit reliably (`PROMPT_VERSION` coach-v2→coach-v3,
  wording only). Fixed both without touching the validator; 2/2 live
  `driverdna coach` runs and one live chat turn then passed grounding
  cleanly); per-user encrypted API keys (BYOK) with a `#/config` panel.
  Full detail, and the real bugs the trust gates and the live run caught,
  all fixed properly: `docs/STATUS.md`'s 2026-08-02 snapshot.

- **Lap-analysis protocol: built (2026-07-29)** — `docs/LAP-ANALYSIS-PROTOCOL.md`,
  owner-directed: put cheap high-volume agents (Flash, via Antigravity or
  Gemini CLI) on the grunt work of *reading traces* for things no metric
  catches, with the reading checked mechanically before anyone believes it.
  The reader gets no authority: observations only, never code, never a number
  the engine uses. `driverdna lap-digest` cuts a lap into readable per-corner
  slices and **measures nothing** — row and column selection only, asserted
  cell-for-cell — because it is the shared evidence base for two independent
  readers and a derived-column bug would corrupt both identically.
  `driverdna verify-observations` rejects any numeral not quoted from the
  digest, importing `coach.grounding`'s tolerance rather than defining a
  second one (`matches_number` is that function, newly public, unchanged).
  Reliability is measured per batch via known-outcome laps riding along
  unmarked. Flagged: on a thin corpus the engine is *supposed* to be quiet
  (gates at 10 phase samples / 2 sessions / 3 laps), so "engine silent" scores
  as ungated there, never as a gap; and the reviewer must be blinded when the
  batch is *designed*, not just when it is read (B01's reviewer already knew
  which two laps carried incidents — excluded from its agreement count).
  B01 sealed: answer key pre-registered, 19/19 reviewer observations grounded,
  committed before any agent ran. First finding, not in the answer key: brake
  re-application after the corner's brake release, 8 of 11 laps at C01,
  concentrated at five corners and absent at ten, counted by no metric —
  while `throttle_modulation_count` counts the exact throttle analogue.
  Separately, `gear` reaches the analysis chain once, at `segmenter.py:193`,
  where gear-0 spans are excluded from corner detection rather than measured.
  Neither acted on: a finding is not an amendment.
- **Reference laps R2 (identity/depth) + R3 (curation): built (2026-08-03,
  SPEC.md A39)** — `docs/REFERENCE-LAPS.md`'s R-track continues past R1.
  Six open decisions were asked via `AskUserQuestion` and owner-confirmed
  before any code: no `--ref-label` column (the existing `driver` column is
  sufficient identity); one aggregated envelope, not split per contributor;
  the corner drill overlays reference n/median/best as three extra columns
  on the self phase-times row (never a separate section or side-by-side);
  curation is an exclusion flag through the audited-annotations pattern
  (`reference_exclusions` table, migration 015 — reversible, upserts in
  place, never deletes the lap or its measurements); the toggle lives in
  the cohort view's References panel and as CLI commands
  (`exclude-reference`/`include-reference`); the cascade is immediate (no
  cache — `build_cohort_payload` already reads live DB state on every
  fetch). Exclusion is enforced exactly once, at `db.phase_history`'s query
  surface (role='reference') — the same discipline A34 established for
  role isolation itself — so `attribution/ranker.py`'s
  `vs_reference_findings` needed **zero code changes** to honour it,
  proven by a test that excludes a lap, reruns the unmodified ranker
  function, and diffs the findings list back to byte-identical on
  re-inclusion. Payload gained a `references` section (`{n, n_excluded,
  envelope, contributors}`, `PAYLOAD_VERSION` 4→5); API gained
  `GET .../corners/{id}/reference-phases` and
  `POST`/`DELETE /api/laps/{lap_pk}/exclude` (mirrors the annotate
  endpoints exactly). One real gap found and closed along the way: `POST
  /api/laps/upload` hardcoded `driver="owner"` for every upload regardless
  of role, which would have made decision 1 only half true on the browser
  ingestion path — fixed with one optional form field, self-upload default
  unchanged. Verified against real fixture telemetry (a second
  `spa-blind-2026-07/` lap imported as a genuine reference lap, not
  content-deduped against the self import) and a real Playwright session
  (envelope/identity render, the Exclude/Include toggle updates the page
  live with no reload, the corner drill's overlay columns show real
  values) — not yet against the owner's own production store, which
  presently holds zero reference laps. R4 (reference-geometry adoption)
  remains untouched, its own separate owner-go still pending. Suite
  850 → 879 passed, 0 failed (+29 tests). Full record: `docs/SPEC.md` A39,
  `docs/STATUS.md`'s 2026-08-03 snapshot.

- **Multi-tenancy audited and the docs reconciled (2026-08-18, SPEC.md A53)** —
  A32 said multi-user was built and merged; every later doc said the opposite,
  and this status log itself never mentioned A32 again after 2026-07-28.
  `docs/ACCOUNTS-SPEC.md:37-56` had predicted exactly that and required the
  reconciling edits *in the same change as A32*; they never happened. Audited
  read-only against `main` at `e196c2d`. **A32 is live, not dead code** — the
  deploy runbook makes `/api/auth/register` the documented way the owner creates
  their account — and partitioning is genuinely thorough (76 `owner_user_pk`
  sites in `db.py`, `corner_maps UNIQUE(car, track, owner_user_pk)`). But four
  specified things were never built, all now open: **`finding_annotations` was
  never partitioned** (BUG-031 — finding IDs carry no tenant term, so two users
  on one car/track collide exactly, and one driver's annotation suppresses
  another's finding and leaks its note into their chat bundle); **config is
  instance-wide with a cross-tenant revert** (BUG-032); **`/api/sync` falls back
  to the owner's `GARAGE61_TOKEN`**, so a beta user who never connected Garage61
  imports the owner's laps (BUG-033); and **`tests/test_tenancy.py`, the gate
  ACCOUNTS-SPEC named for this work, does not exist** — the only cross-user
  isolation tests in 74 files are two covering AI keys. The blob store is shared
  but not currently leaky (`lap_pk` is globally unique and every API path
  resolves through an owner-filtered query first); its primitives are unguarded
  though, which is the A34 shape. Suite unchanged and green: **975 passed, 42
  skipped, 0 failed** (SQLite; 26 browser skips are a gap, 16 Postgres-absent).
  **Docs-only change — no code touched, no committed artifact moved.** Owner
  decisions adopted in A53: registration closes to first-user-only behind the
  Cloudflare Access allowlist, and config becomes **fully per-user**, which
  refines a non-negotiable and therefore ships only with a config fingerprint
  stored beside every measurement. Five more decisions the same day:
  reference-derived numbers pin to the reference lap rather than the importing
  user, through a canonical config keyed to `content_hash` — a deliberate
  carve-out from per-user config, since vs-reference findings cannot be both
  comparable across cockpits and per-driver; `sync.max_cohorts` 10 → 40 with retention
  unchanged and tiers rejected; pre-A32 rows reassigned to the live account;
  finding IDs keep their shape; database snapshots move off the VM. Full
  record: `docs/SPEC.md` A53,
  `docs/BUG-LOG.md` BUG-031..032, `docs/STATUS.md`'s 2026-08-18 snapshot.

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

## Editing the coaching and feedback layer

The owner expects to keep iterating on how coaching and feedback *appear*
(2026-08-09). This section is the map and the tripwires, so a presentation
change stays a presentation change. `docs/UI-SPEC.md` (decisions 2, 6, 7,
"Copy density") and `docs/SPEC.md` (decisions 3, 8; A46) remain binding; this
is the practical layer under them.

### Where the words live — edit the engine, never the SPA

Every driver-facing string has exactly one home, and none of them is a JSX
file. This is not style: `model.jsx` used to keep its own fundamental-label
map, which is a drift waiting to happen, and A46 deleted it.

| To change… | Edit | Notes |
|---|---|---|
| the racing voice — "shrink the coast", the *why*, the drill | `coaching/ontology.py` | versioned (`ONTOLOGY_VERSION`); a principle is data, not code |
| a finding's measurement sentence | `attribution/ranker.py` (+ `PHASE_LABELS`) | changes committed artifacts — see below |
| a detector's driver-facing name | `metrics/detectors.py` `DETECTOR_LABELS` | **never rename the slug** |
| "how is this measured" disclosure text | `explain.py` `METHODOLOGY` | id must exist before a view names it |
| a fundamental's display name | `model/taxonomy.py` `Fundamental.label` | travels via `belief.label` |
| a gate's stated reason | `attribution/ranker.py` `_gate` | exempt from copy trimming |
| how a fundamental's group *looks* — the landmark header, the lens rule, the tier mark | `ui/src/views/shared.jsx` (`FundamentalSections`, `FundamentalMark`) + `ui/src/app.css`; geometry in `ui/src/views/pyramid.js` | mirrored in `report/builder.py` (`_coaching_lede_md`/`_html`) — change both |
| which principle ledes a fundamental | `coaching/engine.py`'s ranking; the renderers only read `headline` then `secondary` | implemented once per surface, pinned on both against the payload's own `coaching.headline` |

**Slugs are identity, labels are language.** `coast-window`,
`one-steering-input`, `cp.*` ids and `finding_id`s are load-bearing — evidence
IDs, config keys, ontology gates, annotations, stored rows and the grounding
validator all key off them. Improve wording by adding or editing a *label*.
Renaming a slug silently orphans stored annotations.

### The traps, in the order you'll hit them

1. **Do not put an aggregate on a group header.** A per-fundamental seconds
   total is the single most tempting addition here and it is forbidden:
   `cumulative_loss` is per *phase*, and `entry` maps to two fundamentals
   (`braking` measured, `commitment` proxy), so summing it in the renderer
   both double-counts and violates "the UI never computes a measurement".
   Counts of rendered items are fine (the `shownCount` precedent). If a
   per-fundamental total is genuinely wanted, the **engine** must compute it,
   with its own decision about the double-count.
2. **Grouping is presentation; the source tag is not.** SPEC decision 3
   requires every finding to carry its source tag, and the three sources are
   never combined into one figure. Regroup freely; never drop the `.src-tag`
   chip, and never colour it semantically (colour-grammar rule 2).
3. **Render-parity scans inside closed disclosures.** The crawler reads
   `textContent` of every `.num` element, and `textContent` includes collapsed
   `<details>`. So a number that isn't in the payload must not sit in a `.num`
   element *anywhere*, open or not. This is why the vs-principle rationale —
   which quotes one lap's figure — renders as prose.
4. **Suppression may be collapsed, never dropped** — and since A48 the *shown*
   findings collapse too, under their fundamental's coaching lede. Same rule
   governs both: every suppressed finding stays listed with its `gate_reason`
   **verbatim**, every shown finding stays in the DOM with its own `.src-tag`,
   and nothing is removed to make the page quieter. UI-SPEC's copy-density rule
   explicitly exempts measurement copy and gate reasons ("accuracy over brevity
   there"). Trim chrome around them, never them. If a future request is
   "get rid of the source tags", that is an AGENTS.md non-negotiable and needs
   an explicit owner re-decision, not a renderer change.
5. **A confidence value never launders an unmeasured inference.** A
   `no_signal` principle gets a self-check and no score, magnitude, band or
   confidence at any level — the grounding validator rejects it mechanically,
   so a well-meant "confidence" chip on a self-check is a test failure, not a
   design choice.
6. **Don't let the two layers re-diverge.** A46 exists because coaching (the
   racing voice) and findings (the measurement) were restating each other in
   two registers. Before adding a sentence, check whether
   `coaching/ontology.py` already says it.
7. **Rules of hooks apply.** `useMethodologyText` is a hook; calling it in a
   `.map()` is a violation even when the list is a module constant. See
   `SourceLegend`'s four fixed calls.
8. **Name an `explain.py` id before a view references it.** Both
   `<Methodology id="…">` and `useMethodologyText("…")` are cross-checked by
   `test_explain.py` (the hook form only since BUG-021 — see below).
   Template-literal ids can't be checked statically and are covered
   dynamically instead.

### If you change a `Finding.description` or any engine string

It flows into committed artifacts, so the change is never local — and since
2026-08-09 this is **enforced**, not remembered:
`tests/test_artifact_freshness.py` regenerates all fourteen and byte-compares,
so forgetting step 1 turns the suite red with the exact command to fix it.

1. Regenerate all of them — `driverdna metrics|attribution|coaching|incidents|
   model|census` (+ `corners` and `schema-report`, which read the fixtures
   directly) and `driverdna report --out-dir .`. Delete any
   `mustang-laguna-seca.*` the report command writes; only the GR86 and driver
   artifacts are committed. Run `corners` **from the repo root with its
   default `--fixtures-dir`** — it prints that path into its own header, so
   passing an absolute one produces a different file.
2. **Prove number-neutrality against clean `main`, not against the committed
   files.** The freshness test tells you *that* an artifact moved; it cannot
   tell you whether it should have. Committed artifacts were stale for days
   before that test existed (BUG-020), so for a presentation change,
   regenerate on a clean checkout too and diff the *numeric multisets* of both
   JSON payloads. A pure presentation change moves nothing except a deliberate
   `PAYLOAD_VERSION` bump.
3. Additive payload fields bump `PAYLOAD_VERSION`. `coach-v3`/`chat-v3`
   version *prompts* — leave them unless prompt text actually changes.
   Strings never enter the grounding `number_pool`; numbers do.
4. If the freshness test goes red for a reason you did not intend, that is a
   real regression — find it before regenerating. Never regenerate to make it
   green without knowing which number moved and why.

### Verifying a change here

Tests alone are not sufficient and the repo's rules say so. The full recipe:
`python3 -m pytest` (report what skipped and why — Postgres skips are
expected, browser skips are a gap); rebuild the SPA (`cd ui && npm run build`)
so the in-package bundle ships it; then **actually load the page** — group
headers render, disclosures open, `#/model` reads payload labels, and 0 px
horizontal overflow at 390×844. `test_render_parity.py`, `test_offline.py` and
the four other browser-gated files must pass with Chromium present.

## Commands and testing rules

See `AGENTS.md` — imported at the top of this file.
