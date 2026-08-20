# DriverDNA - Status & Decision Log

**Snapshot date: 2026-08-20 (BUG-038 fixed: Driver payload N² query explosion & frontend caching resolved).**

- **What prompted it:** User reported the Driver home screen freezing on "27 of 27 — computing driver model" and eventual "load failed" on multi-cohort accounts (BUG-038). Fixed the N² payload query explosion (~500K queries) and rewrote frontend driver caching via `useDriverPayload` with proper ref-counting and abort logic.
- **A32 is live, not dead code.** `docs/DEPLOY-RUNBOOK.md` Part D step 5 makes
  `POST /api/auth/register` the documented way the owner creates their account
  on the VM, and registration ships in the built SPA bundle. Partitioning is
  genuinely thorough — 76 `owner_user_pk` sites in `db.py`, and `corner_maps
  UNIQUE(car, track, owner_user_pk)` (`db.py:320`), the crux
  `docs/ACCOUNTS-SPEC.md:60-71` identified.
- **Six defects filed** (`docs/BUG-LOG.md` BUG-031..033, all open):
  `finding_annotations` never partitioned and finding IDs carrying no tenant
  term, so two accounts on one car/track collide exactly (BUG-031); config
  instance-wide with a cross-tenant revert (BUG-032); `/api/sync` falling back
  to the owner's `GARAGE61_TOKEN`, so a beta user who never connected Garage61
  imports the owner's laps (BUG-033); login not normalizing email while
  register does, a permanent lockout (BUG-034); all pre-A32 rows owned by a
  seeded account with a `'placeholder'` hash no password can match (BUG-035);
  and the tenancy test gate ACCOUNTS-SPEC specified never being written
  (BUG-036). BUG-037/035 backfill the two `e196c2d` security fixes that merged
  without entries.
- **Not a hole, but pinned too high:** the blob store is shared rather than
  per-user (`blobs.py:114-125`). No leak is reachable — `lap_pk` is globally
  unique and every API path resolves the lap through an owner-filtered query
  first — but `load_lap_arrays` and `has_raw` take a bare `lap_pk` and never
  check ownership, while the legacy fallback beside them does. The A34 shape.
- **Owner decisions adopted (A53):** registration closes to first-user-only,
  with the Cloudflare Access email allowlist as the invite mechanism; and
  config becomes **fully per-user, every threshold**. The second refines a
  non-negotiable, so it ships only with a fingerprint of the user's effective
  `config_snapshot()` stored beside every measurement — without that,
  "deterministic, versioned, confidence-qualified" stops being verifiable.
  Five further decisions taken the same day: **reference-derived numbers pin to
  the reference lap, not the importing user** (the most expensive of three
  options, chosen deliberately), resolved through a **canonical config keyed
  to the lap's `content_hash`** — a knowing carve-out from "config is fully
  per-user", since vs-reference findings cannot be comparable across cockpits
  and per-driver at once;
  **`sync.max_cohorts` 10 → 40** with `raw_laps_per_cohort` staying 100 and
  audience tiers rejected (the two knobs have opposite audiences, and retention
  is a ceiling rather than a reservation); **pre-A32 rows reassigned** to the
  live account, live row wins on collision; **finding IDs keep their shape**,
  with a guard test instead; and **database snapshots move off the VM** while
  blob loss is accepted as recoverable.
- **Capacity, estimated** (867 KB blob + 32-52 KB rows per lap, measured
  2026-07-27; ~153 GB usable after the 47 GB boot volume): roughly **25
  veteran accounts** (40 cohorts at the 100-lap retention cap, ~5.2 GB each
  with backups) or **~1,100 newbie accounts** (~0.12 GB each). Disk is not the
  binding constraint at beta scale — `MAX_CHAT_SESSIONS = 8` is instance-wide
  (`ui/api.py:149`), the service runs one uvicorn worker by construction, and
  SQLite is single-writer. Size the beta on concurrent activity, not disk.
- **Verified counts:** `python3 -m pytest -rs -m "not browser"` → **1057 passed,
  19 skipped, 26 deselected, 0 failed** (SQLite backend, Python 3.14, clean dev
  venv, 313 s). The 19 skips are **16 Postgres-absent** and **3 optional Gemini
  SDK-absent**. The 26 deselected are browser tests. `tests/test_agent_contract.py`
  green (9 passed).

---

**Snapshot date: 2026-08-16 (A52 — CV bands recalibrated, any band can
headline; BUG-029 and BUG-030 fixed). A51 merged as PR #30.**

- **What prompted it:** the two items A51 deferred. They turned out to share a
  root cause, plus a second instance of it nobody had noticed.
- **BUG-029 — A42 changed the unit and left every threshold behind.** A42
  moved `same_lap_twice`'s gate from a **raw** CV to a **per-unit normalized**
  one, rewrote the config descriptions to say so, and never converted the
  numbers. `git log -L` shows `d588921` editing `cv_band_major`'s description
  from "coefficient-of-variation floor" to "normalized-CV floor" while
  `default=0.50` on the line above went untouched. On the normalized scale
  `1.0` is exactly unit-typical, so an average driver banded **major** at twice
  the threshold: all 16 fixture corners banded major and the band carried no
  information. Second instance in the same commit: `consistency_cv_floor=0.15`,
  described as "15% above typical", actually meant 85% *better* than typical —
  the eligibility gate filtered nothing.
- **Recalibrated to the scale's own anchors**, not fitted to the corpus:
  floor/moderate `1.15` (the floor's own stated intent), notable `1.50`
  (midway typical→ceiling), major `2.00` (**equal to**
  `consistency_cv_ceiling`, so coaching and dm-v2 agree on "as bad as it
  gets"). `commitment_cv_floor` stays `0.15` — single metric, raw-CV path,
  always correct.
- **BUG-030 — the weakest fundamental could never be coached.**
  `headline_eligible` required seconds-banding, so `same_lap_twice` was
  excluded from the headline pool permanently. The Driver Model named
  `consistency` the driver's weakness (34.3, 16 corners) while coaching was
  structurally incapable of saying so. Now band-only, ranked by a private
  unit-free `_severity` (magnitude ÷ its own kind's major floor). Ranking on
  raw magnitude would have compared 0.591 s against CV 2.724 and taken the CV
  every time — bigger number, not worse problem. `_severity` is test-pinned
  never to reach the payload.
- **Effect on the real corpus:** secondary 26 → 20; bands 16/16-major →
  15 moderate / 3 notable / 2 major; `repeatability` 16 major → 9 moderate plus
  the one genuine C02 outlier; strengths 7 → 8 principles, because the six
  corners that fell below the floor were the driver's *most repeatable* and now
  read as strengths. `same_lap_twice` enters the headline pool and ranks third
  on severity (1.36 vs 1.69) — eligible at last, correctly just short.
- **One artifact change that is not a band effect:** the fixture headline moved
  `cp.turn_in.one_commitment` → `cp.coasting.always_working`. They are exactly
  tied (same corner C14, same 0.5906, same band, same severity — both band on
  that corner's `mid` loss); the old `max()` kept declaration order, the new
  sort breaks ties on `principle_id`. Both deterministic; incidental tiebreak
  → explicit one.
- **Versions:** `ONTOLOGY_VERSION` → `coach-onto-v4`. `PAYLOAD_VERSION`
  unchanged at 9, `SCORING_MODEL_VERSION` unchanged at `dm-v2` — and dm-v2
  **structurally cannot** move, since it reads `config.model.*` while these are
  `config.coaching.*`. Verified by a test asserting `scoring.py` contains no
  `config.coaching` reference, and empirically:
  `docs/driver-model-report.md` and `docs/census-report.md` regenerate
  byte-identical.
- **One brittle test of my own, fixed:** A51's
  `test_ontology_version_bumped_for_the_new_field` pinned the literal
  `"coach-onto-v3"`, so it failed on the very next bump. It now pins the
  guarantee (`!= "coach-onto-v2"`) rather than a version string.
- **Verified counts:** `python3 -m pytest` → **1062 passed, 16 skipped, 0
  failed** (SQLite backend, 8m00s). All 16 skips are Postgres-absent; zero
  browser skips. `ruff check .`: clean.

---

**Snapshot date: 2026-08-16 (A51 — strengths, score decomposition, and
driver-level coaching; BUG-028 filed).**

- **What prompted it:** an audit of the build against its own stated goal —
  "make it obvious what your strengths and weaknesses are, in coaching
  language". Scored 0/10 on strengths (the word occurred **zero** times in
  `src/` and `ui/src/`; all nine principles error-framed), 4/10 on weaknesses
  (scores rendered with no ordering, no anchor, no decomposition), 7/10 on
  what-to-work-on (excellent per cohort, nonexistent driver-wide).
- **Score decomposition (A14 gap closed):** `Belief` now carries the three
  components it was computing and discarding, each with value, `n`, and the
  share it carried after redistribution.
- **`basis_reason`:** explains a narrow basis and distinguishes **structural**
  from **pending**. A fundamental owning no detectors can never gain adherence;
  saying "not yet" would be a lie. This is what makes `vehicle_management`'s
  bare `0.0` honest — it now reads "scored on one component; only 1 of its 4
  techniques carries a telemetry signal".
- **`model/reading.py` (`read-v1`):** names a strongest and weakest.
  **Rank-only** (these scores are calibrated against no driver population, so
  an absolute band would be asserted, not earned) and **measured-only** (a
  proxy at 0.0 would otherwise become "your greatest weakness", headlining the
  least-supported number in the system). Gated on `reading_min_scored` (3) and
  `reading_min_separation` (10.0), each stating its reason.
- **Coaching strengths:** `strength_expression` on all eight measured/proxy
  principles + `eligible_strengths`. **A `negligible` band is not a strength** —
  a candidate exists only where a gate *cleared*, so `negligible` means the
  fault is present but cheap; the signal is the inverse pass, which produced no
  record before. Strengths require the full `thin_evidence_floor_n`, stricter
  than a candidate's flag.
- **`coaching/rollup.py`:** driver-level coaching. *A principle firing at more
  than one track is the driver, not the track.* Reuses
  `gates.min_tracks_for_rollup`; single-track patterns are suppressed **with
  reason**, never dropped; no magnitude is ever combined across cohorts.
- **On the real corpus:** strongest braking 80.5, weakest consistency 34.3
  (46.2 points apart), and coasting confirmed as a genuine cross-track habit
  (2 tracks, 9 corners) with its drill on driver home.
- **Versions:** `PAYLOAD_VERSION` 8→9, `ONTOLOGY_VERSION` →`coach-onto-v3`,
  `READING_VERSION` `read-v1` new. `SCORING_MODEL_VERSION` **unchanged**
  (`dm-v2`) — no score moved.
- **Number-neutrality proven, not asserted:** both payloads regenerated on a
  clean `main` worktree and diffed as numeric multisets — **zero numbers lost**
  in any of the three payloads; `payload_version` is the only value that moved
  anywhere.
- **BUG-028 filed:** six `explain.py` texts written and referenced by no view
  (`test_explain.py` checks JSX→engine only). The three component texts are now
  live; the other three remain open deliberately.
- **Environment fix (not a repo change):** the 26 browser tests had been
  skipping here on BUG-025's mismatch (image ships Chromium 1194, this
  Playwright resolves 1234) plus an unbuilt SPA. Bridged the path and built the
  SPA; the render-parity crawler is running again, which this change needed.
- **Deferred, with reasons stated in A51:** CV band saturation
  (`cv_band_major` 0.5 vs observed 0.849–2.724 → all 16 repeatability items
  band "major") and headline eligibility (`consistency` can never headline).
  Both move engine numbers.
- **Verified counts:** `python3 -m pytest` → **1035 passed, 16 skipped, 0
  failed** (SQLite backend, 8m39s). All 16 skips are Postgres-absent; **zero
  browser skips** — the 26 browser tests ran. `ruff check .`: clean.
  `npm run lint`: 0 errors, 6 pre-existing warnings. `npm run build`: clean.

---

**Snapshot date: 2026-08-15 (BUG-018 closed-undiagnosed, BUG-027 fixed,
persistent journald for future crash diagnosis).**

- **BUG-018 closed-undiagnosed:** the Oracle VM 1033 outage from 2026-08-08
  remains undiagnosable — journald's volatile storage lost every crash log on
  reboot. The service recovered on its own (`Restart=always`). Both real bugs
  found in the same triage (BUG-026, BUG-027) are now fixed. Reopening
  requires reproduction or fresh journal evidence.
- **BUG-027 fixed:** `Garage61AuthError` (HTTP 401 from an expired OAuth token)
  was caught by a generic `except Exception`, surfacing a raw traceback to the
  driver. Now caught specifically at both sync surfaces: the SSE worker in
  `api.py` emits `{"type": "error", "detail": "… sign-in expired …",
  "auth_expired": true}`; the SPA's `SyncPanel` (driver home) and `#/import`
  detect the substring and render a reconnect link to the OAuth flow; the CLI
  prints the message and exits 2.
- **Persistent journald:** `deploy/journald-driverdna.conf` drop-in
  (`Storage=persistent`, `SystemMaxUse=200M`) ensures crash logs survive
  reboots. Install documented in `docs/DEPLOY-RUNBOOK.md` Part G.
- **Verified counts:** `python3 -m pytest` → **997 passed, 16 skipped, 0
  failed** (SQLite backend). The 16 skips are Postgres-absent only. `ruff
  check .`: clean. `npm run lint`: 0 errors. `npm run build`: clean.

---

**Snapshot date: 2026-08-14 (BUG-022 fixed, BUG-026 fixed, stale Cloud Run
comments removed — SPEC.md A50).**

- **BUG-022 fixed:** `INCOMPLETE_LAP`-flagged laps excluded from the lap-time
  comparison. `lap_delta_s` computed from complete laps only; incomplete entries
  are `null`. New `lap_incomplete` boolean array in the cohort payload. Reference
  envelope also filters incomplete reference laps. `PAYLOAD_VERSION` 7→8.
  Number-neutral on committed fixtures (all complete).
- **BUG-026 fixed:** SSE streams (sync, rebuild-map, report) used bare `q.get()`
  with no timeout. During silent compute phases (driver model, census — up to
  minutes), nothing was emitted and Cloudflare's ~100s idle timeout killed the
  connection. `_drain_sse` helper with `q.get(timeout=heartbeat)` + `: keepalive`
  SSE comments. New `api.sse_heartbeat_seconds` config key (default 15s).
- **Stale Cloud Run references** in `api.py` comments cleaned up (Cloud Run was
  retired at A40).
- **Verified counts:** `python3 -m pytest` → **994 passed, 16 skipped, 0
  failed** (SQLite backend). The 16 skips are Postgres-absent only. `ruff
  check .`: clean. `npm run lint`: 0 errors. `npm run build`: clean.
  `test_artifact_freshness.py`: 16 passed; only `payload_version` changed.

---

**Snapshot date: 2026-08-11 (sync bounded by cohort, newest first; pit-lane
laps counted before they are judged — SPEC.md A49).**

- **`config.sync.max_cohorts` (default 10, `0` disables)** caps how many
  cohorts one `driverdna sync` pulls, and `discover_cohorts` now orders them
  **newest-driven first** off `/me/statistics`' `day` field, which was present
  in the response and being discarded. The owner's account holds ~25 cohorts,
  most of them finished one-offs.
- **The trade is recorded, not implied.** `sync_driver` deliberately keeps no
  automatic watermark, because `after` filters on when a lap was *driven*, not
  synced. A cohort cap reintroduces that failure mode one axis up: a lap
  uploaded late to a cohort outside the window waits until that cohort is
  driven again. Bounded two ways — only the cohort axis is capped (within a
  synced cohort the full listing is still re-read), and every skipped cohort is
  reported **by name with its last-driven date**, in the CLI and the SPA.
- **Ordering rests on an unverified field, so it is made visible rather than
  trusted.** `day`'s format is documented nowhere; it is compared as a string
  (right for `YYYY-MM-DD` and ISO-8601, wrong for an epoch int). A row with no
  usable date sorts oldest, and if *no* cohort carries a date the cap is
  refused outright and the full sync runs.
- **Pit-lane laps are counted, not yet dropped.** Formation laps never arrive
  (the API's `lapTypes` default returns normal laps only). What remains is a
  normal lap that began in the pit lane, flagged `pitlane` — a field whose
  meaning is also undocumented, and whose two readings imply opposite
  behaviour. `config.sync.skip_pitlane_laps` therefore ships **off**, with
  `CohortSync.laps_pitlane` surfaced in the CLI, the SSE `complete` event and
  the SPA. Number-neutral by construction: no lap imported before is skipped
  now.
- **A real bug found and deliberately left open (BUG-022)** — and its own
  first filing corrected the same day. Originally written up as "`INCOMPLETE_LAP`
  is flagged and never read, so partial laps are measured as if complete"; the
  owner then said incomplete laps are **wanted** (a lap ending in a virtual tow
  *is* the incident record, A19), which forced the unchecked inference to be
  measured. It is wrong: the segmenter finds 4 corners instead of 14 on a
  40%-truncated lap, so the per-corner layer is correct by construction and
  phase times, metrics, Driver Model and trend are unaffected. The real defect
  is narrower — whole-lap `duration_s` (trace length) used as a lap time in
  `payload.py:183-186` and `:149`, so a towed 68.50 s lap becomes the cohort's
  "fastest" and a genuine 171.25 s lap renders at +102.75 s. Dormant on the
  fixtures; activates as incident capture starts working.
- **Three defects found on the way**, all filed: `main` was red from PR #21
  adding `garage61_linked` without updating its assertion (BUG-023, fixed);
  `ruff check .` is red from fifteen dead root-level scratch scripts (BUG-024,
  left open — deleting tracked files is an owner decision); and **all 26
  browser tests had been silently skipping** because the image ships Chromium
  build 1194 while Playwright resolves 1234, which had been hiding a broken
  `/api/cohorts` assertion on this branch for two commits (BUG-025, fixed).
- **Verified counts:** `python3 -m pytest` → **993 passed, 16 skipped, 0
  failed** (6m43s, SQLite backend). The 16 skips are Postgres-absent only
  (`DRIVERDNA_TEST_DATABASE_URL` unset); **0 browser skips** — the 26
  browser-gated tests ran, for the first time in this environment, after
  BUG-025. Before that fix the same suite read *964 passed, 42 skipped*, the
  extra 26 being browser tests skipping silently. `pytest -m browser` → 26
  passed. **`ruff check .` now passes repo-wide** — the fifteen dead root-level
  scratch scripts behind BUG-024 were deleted (owner-directed), so the `lint`
  gate is green for the first time rather than permanently red. `npm run lint`:
  0 errors, 6 pre-existing warnings. `tests/test_artifact_freshness.py`: 16 passed, and no committed
  artifact file shows as modified — the change is ingest scope and the fixtures
  are imported, not synced.

---

**Snapshot date: 2026-08-10 (fundamentals as landmarks; the feedback section
reads as coaching — SPEC.md A48).**

- **Owner-directed presentation pass, chosen from a mockup rather than from
  prose.** Four header treatments were built against the real GR86/Spa fixture
  — every sentence, corner and figure real engine output — and the owner picked
  "lens rule": `docs/ui-fundamentals-mockup.html`. One rule runs the height of
  a fundamental's group, brightest where it is named and fading down it, with a
  **tier mark** (the Driver Model pyramid in miniature, this fundamental's tier
  lit) sitting on it. The same treatment carries onto `#/model`'s meters, so
  the two tabs read as one system; `ui/src/views/pyramid.js` holds the tier
  geometry once, so the full-size pyramid and the 22px mark cannot become two
  shapes.
- **The section now leads with coaching.** Each fundamental opens with its
  top-ranked principle in full — expression, driving principle, **and the
  drill**, which until now rendered on the single headline card only, so eight
  of the nine seed principles carried a written practice step the driver could
  never see. The measurements collapse into one disclosure per group. The
  fundamental owning the page headline carries a `priority` chip, which retires
  `CoachingSecondary`'s "Same as the headline above" branch entirely.
- **"Hide the vs-self/vs-principle/vs-reference stuff" is implemented as
  collapse, never delete** — stated plainly rather than quietly widened or
  quietly ignored. Every row stays in the DOM with its own source tag, and the
  render-parity crawler reads inside closed `<details>`, so AGENTS.md's
  "every finding carries N, spread, source tag, and evidence IDs" and UI-SPEC
  decision 6's binding half are untouched. Deleting the tags would contradict
  the constraint the same request opened with and would need its own owner
  decision.
- **The static report gained a section it had been dropping.** A fundamental
  the engine can coach but has no shown finding for — `consistency` on the real
  fixture, a major signal at sixteen corners — now gets its heading and lede in
  Markdown and HTML. The SPA always rendered it; the report was silently hiding
  the loudest thing the engine had to say about this driver.

### Verified counts (2026-08-10, A48)

| What | Result | Command |
| --- | --- | --- |
| Tests, before this change | **963 passed, 16 skipped, 0 failed** | `python3 -m pytest -q -rs` |
| Tests, after | **971 passed, 16 skipped, 0 failed** | `python3 -m pytest -q -rs` |
| New tests | **+8** — 4 browser (`test_feedback_hierarchy_ui.py`: sentence before measurement in DOM order; `priority` chip on exactly the headline's fundamental and said once; findings collapsed-not-dropped with every row still tagged; the tier mark on both surfaces) and 4 report (`test_report.py`: Markdown and HTML lede each fundamental with its coaching expression; a coached-but-ungated fundamental still gets its section; each expression said once per section) | — |
| Skips | **16, all Postgres-absent.** No browser skips — Chromium installed via `python -m playwright install chromium`, all seven browser-gated files ran | `pytest -rs` skip lines |
| ruff / eslint | **clean** / **0 errors, 6 warnings** (7 before this change — one fewer, from splitting the shared constants out of `shared.jsx`) | `ruff check .`; `npm run lint` in `ui/` |
| Backend under test | SQLite (no Postgres, no secrets, no live server) | — |
| Browser verification | Real Chromium against the fixture DB at 1180px and 390×844: group headers read as landmarks, the coaching lede sits above the first finding row, the `priority` chip lands on Rotation, the collapsed measurements open, `#/model` shows the tier mark per fundamental, 0 px horizontal overflow, no JS errors | Playwright drive script + `test_render_parity.py` |
| Number neutrality | `PAYLOAD_VERSION` unchanged at 7. `gr86-spa-francorchamps.json`, `driver.json`, `driver.md` and all eight `docs/*-report.md` regenerate **byte-identical**; `gr86-spa-francorchamps.md`'s numeric multiset is identical (129 numerals), prose only; the two HTML reports' **reader-visible** numerals are identical (533 and 27), every numeric delta inside `<style>` | numeric-multiset diff vs `HEAD` |

One process note worth keeping: the first regeneration pass wrote
`docs/model-report.md` instead of the committed `docs/driver-model-report.md`,
and `test_artifact_freshness.py`'s coverage guard caught the stray file
immediately. That guard is a week old and has now paid for itself twice.

---

**Snapshot date: 2026-08-09 (CI quality gates: lint, secrets, mypy ratchet,
branch protection — SPEC.md A47).**

- **The "no linter, no formatter, no type checker" position is retired**,
  re-decided per AGENTS.md's Decision discipline rather than silently
  reversed. `main` had no merge gate at all (unprotected, and `tests.yml`
  triggers on `push`, so CI only ever reported after the fact). Full
  record: `docs/SPEC.md` A47, `docs/PROJECT-BRIEF.md`'s decision log.
- **Two real, previously-invisible CI defects found and fixed first,
  before any new tooling landed** — more consequential than the gates
  themselves: (1) all 19–22 Playwright browser tests had been silently
  skipping in every CI run (Playwright's installer moved to a
  `chrome-linux64/` layout; the tests' Chromium-discovery glob still
  expected the old path; the job's own guard caught this and failed, but
  `continue-on-error: true` swallowed it) — fixed and **verified in a real
  GitHub Actions run**, not just locally, since the bug was invisible
  locally the entire time it was broken in CI:
  `19 skipped in 1.69s` → `22 passed, 902 deselected ... in 119.16s`.
  (2) the TDD guardrail (2026-07-27) had compared against a `driverdna/`
  path that stopped existing at the src-layout migration, so it had never
  once correctly suppressed since it was written — fixed to
  `src/driverdna/`, verified live that it now stays quiet on a mixed
  tests+source commit and still warns on a tests-only one.
- **Adopted:** `ruff check` (pyflakes + bugbear, no formatter — required,
  `lint` job) with 47 pre-existing findings cleared, including 13 `zip()`
  calls reviewed individually for `strict=True` vs `strict=False` rather
  than blanket-flagged; ESLint on the 17-file SPA (same correctness-only
  scope, zero JS tooling existed before this), 22 problems cleared to 0
  errors; gitleaks 8.30.1 pinned by exact binary + independently-verified
  SHA256 checksum (not `gitleaks-action`), `.gitleaks.toml` allowlisting
  `tests/fixtures/` and `src/driverdna/ui/static/`; mypy as an advisory
  **ratchet** against `ci/mypy-baseline.txt` (59 findings, spot-checked
  and none were real bugs) — deliberately *not*
  `continue-on-error: true`, since that flag is exactly what hid defect
  (1) above.
- **Branch protection on `main` is the one owner-executed step** — no tool
  in this session can write repo rulesets. Required checks:
  `pytest (3.11)`, `pytest (3.12)`, `lint`, `browser-tests`, `secrets` —
  deliberately not `mypy`. Owner stays on the bypass list for direct
  hotfix pushes. **Correction, same day: attempted and blocked.** The
  owner's GitHub account hit a paid-plan restriction on private-repo
  Rulesets — this was assumed to be a formality and was not. Classic
  branch protection (the older, separate `Settings → Branches` feature)
  is untried. Until one works, **main has no platform-enforced gate**:
  every check above still runs and reports red/green, nothing stops a
  direct push. AGENTS.md's Branches-and-merging section now states the
  PR-only rule as binding by convention rather than implying a ruleset
  backs it.

### Verified counts (2026-08-09, A47 CI quality gates)

| What | Result | Command |
| --- | --- | --- |
| Tests, before this change | **908 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after | **909 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests | **+1** `test_gitleaks_version_is_pinned_and_checksummed` in `test_agent_contract.py` | — |
| ruff | **clean** | `python3 -m ruff check .` |
| eslint | **clean** (5 non-blocking warnings) | `npm run lint` (in `ui/`) |
| mypy | **59 findings**, at the pinned `ci/mypy-baseline.txt` ceiling, advisory only | `python3 -m mypy src/driverdna` |
| Backend under test | SQLite locally (no Postgres, no secrets, no live server); Postgres service container in CI | — |

Every CI-repair claim above was checked against a real GitHub Actions run on
this branch, not just local output — this whole effort exists because a
local pass had previously proven nothing about what CI actually does.

---

**Snapshot date: 2026-08-09 (A46 — feedback reads by racing fundamental).**

### Verified counts (2026-08-09, A46)

| What | Result | Command |
| --- | --- | --- |
| Tests, before this change | **908 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after | **924 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests | **+16** — 5 `test_taxonomy.py` (`phase_fundamental` total/unambiguous/measured-over-proxy), 2 `test_metrics.py` (`DETECTOR_LABELS` covers exactly the real detectors, and reads as language not slugs), 5 `test_attribution.py` (every finding carries a real fundamental; phase/detector land where expected; no slug leaks into a description; vs-principle keeps its rationale behind the summary; vs-reference drops the per-row boilerplate), 4 `test_report.py` (Markdown/HTML group by fundamental, source tag survives, boilerplate said once) | — |
| Skips | same 16, all Postgres-absent — no browser skips: Chromium present, all six browser-gated files ran | `pytest -rs` skip lines |
| Backend under test | SQLite (no Postgres, no secrets, no live server) | — |
| Browser verification | Real Chromium against the fixture DB: fundamental headers render on `#/cohort` and `#/corner`, suppressed/evidence disclosures open, `#/model` shows payload labels, 0 px horizontal overflow at 390×844 | `playwright` drive script + `test_render_parity.py` |
| Number neutrality | Only `payload_version` 6→7 moved, across `gr86-spa-francorchamps.json` + `driver.json`, versus clean-`main` regeneration | numeric-multiset diff |

**SPEC.md A46 — feedback grouped by racing fundamental.** Owner-directed
readability pass. Findings now group by braking / rotation / corner exit
rather than by `vs-self` / `vs-principle` / `vs-reference`; each row keeps
its own source tag, so nothing is blended (UI-SPEC decisions 6 and 7 amended
explicitly, not silently). Detector slugs (`coast-window`,
`one-steering-input`, …) stop appearing as driver-facing English via a new
`DETECTOR_LABELS` map; `taxonomy.phase_fundamental()` files phase-shaped
findings under the measured fundamental; supporting data (N, spread, gap
band, gate reasons, the whole suppressed pile) moves behind the existing
disclosure arrow. One real correctness fix rode along: `vs-principle`
descriptions were printing the *first triggering lap's* rationale as though
it characterised the corner — it now sits in `details["rationale"]`, labelled
as one lap.

⚠️ **Pre-existing artifact staleness fixed in passing, not caused here:**
`docs/coaching-report.md`, `driver.*` and `gr86-spa-francorchamps.*` were
stale on `main` (A42's `coach-onto-v2` CV renormalization and A43's census
section changed their numbers without regeneration). Confirmed by
regenerating on a clean checkout and diffing: clean-`main` output differs
from the committed files identically, and matches this branch
number-for-number. Most of the diff in those three files is A42/A43 catching
up.

**BUG-020 fixed — artifact freshness is now enforced.**
`tests/test_artifact_freshness.py` regenerates all fourteen committed
artifacts from `tests/fixtures/` into a temp dir and byte-compares (~8 s, one
shared import, no secrets or browser). A failure names the first differing
line and quotes the regeneration command. It also fails if a new
`docs/*-report.md` is committed without being added to its table, and a
guard-the-guard test mutates one digit of a real artifact to prove rejection.
Proven end-to-end before commit by changing a real engine string and
confirming it named exactly the three affected artifacts.

Strict byte-compare was **verified safe before adoption**, not assumed: all
fourteen regenerate byte-identical under both CI matrix versions (3.11 and
3.12) and across two numpy majors. Found while building it: `driverdna
corners` prints its `--fixtures-dir` into its own header, so
`docs/corners-report.md` only reproduces from the repo root with the default
flag — the test pins that invocation and the wart is recorded rather than
silently worked around. Suite 944 → 960.

**Coaching/feedback edit guide + BUG-021.** `CLAUDE.md` gained "Editing the
coaching and feedback layer" — where each driver-facing string lives (none in
the SPA), the eight tripwires, the regenerate-and-prove-number-neutrality
recipe, and the verification checklist — because the owner expects to keep
iterating on this surface. One non-negotiable mirrored into both rule files:
driver-facing words live in the engine; slugs are stable identities and are
never renamed for readability.

Writing that guide surfaced **BUG-021** (fixed): `test_explain.py`'s
methodology-id guard matched only `<Methodology id="...">`, not
`useMethodologyText("...")`, so eleven hook-referenced ids — including the
four A46 added — could be typo'd and render as nothing with the suite green.
Guard widened, plus two new tests covering the template-literal `incident.*`
ids that cannot be checked statically. Found by verifying a claim before
writing it down, not by a failure. Suite 942 → 944.

**Bug log adopted (owner instruction, same session).** `docs/BUG-LOG.md` is
now the defect register — 20 entries seeded from the repo's own history, 3
open. Filing is binding (AGENTS.md, Decision discipline), and a paired
standing rule went into the shared non-negotiables block: **never assume a
failure is synthetic.** The open entries are the two 2026-08-08 VM blockers
(now BUG-018 / BUG-019, unchanged in substance) and BUG-020 — nothing
mechanically checks that committed artifacts match regenerated output, the
gap that let A42/A43 leave three of them stale.

---

**Snapshot date: 2026-08-08 (Antigravity deployment handoff — OCI VM live, two blockers open).**

- **Oracle Cloud VM deployed:** DriverDNA running on Ampere A1 ARM64 (`147.5.99.21`). Dedicated `driverdna` service user, venv, and three systemd units (`driverdna`, `driverdna-sync.timer`, `driverdna-backup.timer`).
- **Cloudflare Tunnel + Access:** `cloudflared` routes `driver-dna.com` → port 8710; Cloudflare Access gate uses Google SSO. Internal app-level Google OAuth wired via `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `/etc/driverdna/env`.
- **SSH keypair rotated:** Private key was exposed in chat; `vm_key` replaced, `authorized_keys` locked to the new key.
- **Blocker 1 — service unreachable (Cloudflare 1033):** Service was restarted after `pip install .[dev]` ran against the live venv. Still returning 1033. Needs `journalctl -u driverdna -n 100 --no-pager` to diagnose.
- **Blocker 2 — ARM64 test failures:** `pytest` on the VM produced multiple `F` markers at ~15%, ~31%, ~38% of the suite. Tracebacks not captured. On x86 the suite is 924 passed / 0 failed. Needs `python3 -m pytest --tb=short 2>&1 | tee pytest-arm64.txt` on the VM to get the actual errors.
- **Next step agreed:** Garage61 OAuth ("Login with Garage61 and sync your laps"), callback URI `https://driver-dna.com/api/auth/garage61/callback`. Needs a design decision before building — no SPEC.md amendment exists yet.

---

**Snapshot date: 2026-08-06 (A45 blob-root collision fix + Google OAuth session invalidation fix).**

### Verified counts (2026-08-06, A45 two standing bug fixes)

| What | Result | Command |
| --- | --- | --- |
| Tests, before this change | **903 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after | **905 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests | **+2** `test_remote_url_distinct_dsns_produce_distinct_roots` + `test_remote_url_same_dsn_is_stable` (replacing narrower test) in `test_blobs.py`; `test_google_callback_invalidates_prior_session_for_existing_user` in `test_auth_api.py` | — |
| Skips | same 16, all Postgres-absent | `pytest -rs` skip lines |
| Backend under test | SQLite (no Postgres, no secrets, no live server) | — |

**SPEC.md A45 — Blob-root collision + Google OAuth session-per-device fixes:**
`default_blob_root` now keys Postgres DSN blob dirs on `SHA-256(DSN)[:16]`
instead of the last URL path segment, so two projects whose path ends in
`/postgres` no longer share a blob root. `google_callback` now bumps
`session_epoch` for existing users, matching the password login path and
ending the prior session on a second device sign-in.

---

**Snapshot date: 2026-08-06 (A44 390×844 mobile viewport render-parity + trust-gate-5 tests).**

### Verified counts (2026-08-06, A44 mobile viewport browser tests)

| What | Result | Command |
| --- | --- | --- |
| Tests, before this change | **903 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after (non-browser suite) | **903 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests (browser-gated) | **+2** `test_mobile_viewport_parity_and_no_horizontal_overflow` in `test_render_parity.py`; `test_mobile_viewport_non_localhost_blocked` in `test_offline.py` | — |
| Skips | same 16, all Postgres-absent (browser tests skip without Playwright/Chromium) | `pytest -rs` skip lines |
| Backend under test | SQLite (no Postgres, no secrets, no live server) | — |

**SPEC.md A44 — 390×844 mobile viewport render-parity and trust-gate-5 tests (DEPLOY-SPEC Track M done-criteria):**
Two DEPLOY-SPEC U5 done-criteria (no horizontal overflow at mobile viewport; same parity invariant
as desktop; trust gate 5 at mobile width) were verified manually but had no automated test.
`test_render_parity.py` gains `test_mobile_viewport_parity_and_no_horizontal_overflow` — parity
and overflow checks at 390×844. `test_offline.py` gains `test_mobile_viewport_non_localhost_blocked`
— same non-same-origin block gate at 390×844. Both auto-skip without Playwright/Chromium/built SPA.
No engine change, no payload version bump.

---

**Snapshot date: 2026-08-06 (A43 census surfaced in driver payload + Driver home UI).**

### Verified counts (2026-08-06, A43 census in driver payload)

| What | Result | Command |
| --- | --- | --- |
| Tests, before this change | **900 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after | **903 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests | **+3** `test_census_in_driver_payload`, `test_census_payload_none_when_no_laps`, `test_census_payload_next_steps_have_correct_shape` in `test_census.py` | — |
| Skips | same 16, all Postgres-absent | `pytest -rs` skip lines |
| Backend under test | SQLite (no Postgres, no secrets, no live server) | — |

**SPEC.md A43 — `census` in driver payload + Driver home panel:**
`build_driver_payload` now includes a `census` key (`PAYLOAD_VERSION` 5 → 6). The Driver
home tab gains a "Corpus readiness" panel showing the confidence ceiling percentage, self-lap
count, and the next-steps table ranked by confidence gain. A `_include_census=False` sentinel
on `build_driver_payload` breaks the recursion that would otherwise arise because
`census._suppression_section` calls back into `build_driver_payload` to quote rollup gate
reasons verbatim. No new measurement, no new configuration.

---

**Snapshot date: 2026-08-06 (A42 `same_lap_twice` per-unit CV normalization in
coaching engine — `coach-onto-v2`).**

---

**Snapshot date: 2026-08-05 (real root cause of the Cloud Run sign-in bounce,
plus the auth-layer changes SPEC.md A40's VM target needs — SPEC.md A41).**
A parallel session (`docs/VM-MIGRATION.md`, branch
`claude/driverdna-access-link-m6uv7f`, commit `cd9296f` — not merged, not
duplicated onto this branch, referenced by commit per decision discipline)
investigated the sign-in bounce four prior sessions had tried to fix by
editing auth code. None of that could have worked: two repository secrets
(`DRIVERDNA_SESSION_SECRET`, `DRIVERDNA_DATABASE_URL`) were never set, so the
Cloud Run deploy ran `--db ""`, which `sqlite3.connect("")` turns into a
private, connection-scoped temp database deleted the instant each request's
connection closes — every request got a fresh, empty store. Moot for the
running service once A40's Cloud Run retirement completes, but recorded
because the underlying code defects are real regardless of platform, and
because it explains why the auth logic itself was never at fault.

Fixed, all platform-independent:
- **`resolve_store("")` now raises** instead of silently opening the
  evaporating temp store — the reproduction actually hung a real `uvicorn.run`
  server before the fix landed, confirming the bug's severity directly rather
  than by inference.
- **The ephemeral session-secret fallback is retired (owner-confirmed
  2026-08-05); the interlock now fails closed.** A restart no longer silently
  rotates the signing key and signs everyone out with nothing in the logs to
  explain why. A documented re-decision of A31's shipped behavior, per "never
  silently reverse a decision" — `tests/test_auth_cli.py`'s three
  ephemeral-secret tests are rewritten to pin refusal, not deleted.
- **`/health` now reports `store` (sqlite/postgres) and `auth` (bool)**
  (owner-confirmed public) — enum/bool only, DSN and secrets never appear,
  the existing no-DB-access guarantee unchanged. The single fact that would
  have made the original bounce a five-second diagnosis.

New, for the VM+reverse-proxy topology A40 actually deploys — the most severe
finding: the fail-closed interlock keys off *bind address*, so a proxy in
front of a **loopback**-bound instance defeats it silently (bind looks safe,
auth is actually off, the whole internet reaches the cockpit through the
proxy). `driverdna ui --behind-proxy` (`$DRIVERDNA_BEHIND_PROXY`) applies the
interlock regardless of bind address, explicitly wires
`uvicorn.run(proxy_headers=True, forwarded_allow_ips="127.0.0.1")` (turning
what was an *implicit*, verified-empirically-already-correct uvicorn 0.52.1
default into an intentional tested contract), switches `_is_https` to trust
the now-reliable `request.url.scheme` instead of re-reading the header
itself, and logs a loud once-per-app warning if forwarded headers arrive
anyway with no secret configured and the flag forgotten.
`deploy/driverdna.service` now passes `--behind-proxy`.

**One source-analysis finding re-verified and narrowed, not taken on faith:**
its rate-limiting/`_client_key` claim assumed uvicorn wasn't already trusting
a loopback-connecting proxy by default. Directly instantiating
`ProxyHeadersMiddleware` with uvicorn 0.52.1's actual resolved defaults showed
`scope["client"]` already rewrites correctly for that topology, no code
change needed — confirmed with a real integration test wrapping the app in
the exact middleware configuration the CLI now passes to `uvicorn.run`,
rather than left as an assumption either way. The interlock and `_is_https`
findings were both independently code-verified and are exactly as described.

Not acted on, left open for the owner (VM-MIGRATION.md §5): the session-per-
device inconsistency between the password and Google-callback login paths;
auditing what the live Supabase project actually holds before trusting it as
authoritative (no access to it from this session).

### Verified counts (2026-08-06, A42 coaching CV-pooling fix)

| What | Result | Command |
| --- | --- | --- |
| Tests, before this change | **899 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after | **900 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests | **+1** `test_same_lap_twice_per_unit_normalized_not_flat_mean` in `test_coaching_engine.py` | — |
| Skips | same 16, all Postgres-absent | `pytest -rs` skip lines |
| Backend under test | SQLite (no Postgres, no secrets, no live server) | — |

**SPEC.md A42 — `same_lap_twice` per-unit CV normalization in coaching engine
(`coach-onto-v2`):**
The coaching engine's `same_lap_twice` principle (`cp.repeatability.same_lap_twice`)
pooled all measured metrics' CVs with a flat mean — the same structural bug A21 fixed
in M6's consistency scoring. Five "% lap" metrics with naturally tiny CVs (~0.007) would
dilute one "count" metric's genuinely high CV (~0.99) in a flat mean, making a
demonstrably inconsistent corner appear negligible to the gate. Fixed by porting A21's
per-unit normalized two-level pooling to the coaching layer: each metric's raw CV is
divided by its unit's typical scale (`config.model.consistency_unit_reference_cv`),
then pooled as mean-within-unit then mean-across-units. The `trust_the_proxy` principle's
single-metric gate is unchanged. `ONTOLOGY_VERSION` bumped `coach-onto-v1 → coach-onto-v2`.
New test pins that the per-unit result diverges materially from the flat mean on a
5-"% lap" + 1-"count" mix — the exact scenario that breaks the flat mean.

---

### Verified counts (2026-08-05, A41 auth-layer changes)

| What | Result | Command |
| --- | --- | --- |
| Tests, before this change | **885 passed, 16 skipped, 0 failed** | `.venv/bin/python -m pytest` |
| Tests, after | **899 passed, 16 skipped, 0 failed** | `.venv/bin/python -m pytest -rs` |
| New/rewritten tests | **+14** across `test_dialect.py`, `test_auth_cli.py`, `test_api.py`, `test_auth_api.py` | — |
| Skips | same 16, all Postgres-absent | `pytest -rs` skip lines |
| Backend under test | SQLite (venv `git clone` install; no Postgres, no secrets, no live server) | — |

---

**Snapshot date: 2026-08-05 (migrate off Supabase → SQLite on an Oracle VM,
owner-directed, SPEC.md A40).** The hosted Supabase project went over its
egress limit, so the deployment's primary store returns to SQLite on an Oracle
Always Free VM — the architecture DEPLOY-SPEC decision 1 originally chose.
This **refines A23, it does not repeal it**: SQLite was kept a first-class,
fully-tested backend precisely for this fallback, and the Postgres dialect
layer stays in the tree as the supported second backend and reversible path.
Backend equivalence (same corpus → byte-identical artifacts on either backend)
is the tested guarantee that makes the cutover safe.

What landed in this change (code + docs; the cutover itself is owner-executed):
- **`driverdna backfill-blobs --from <csv-dir>`** — the one code addition. Raw
  lap blobs were never in Supabase and were ephemeral on Cloud Run, and a
  plain re-import can't restore them (copied rows already dedup by content
  hash, so `store_lap` returns "duplicate" and writes no blob). Backfill
  matches each CSV to a lap by that lap's content fingerprint and writes only
  the missing `<lap_pk>.npz`, never creating/deleting/renumbering a lap row —
  so evidence IDs stay valid. New surface: `pipeline.backfill_blobs`,
  `Database.laps_needing_raw()`, the CLI command. **Number-neutral, no
  model-version bump** — a test asserts the restored arrays are array-equal to
  the source store's, and reading them changes no measurement.
- **Docs / decision discipline:** SPEC.md **A40** (the re-decision, recorded
  rather than done silently per the standing non-negotiable); DEPLOY-SPEC H2/H3
  un-staled with an A40 banner (platform corrected; **network shape = public
  URL via Cloudflare Tunnel + Access**, owner's choice over Tailscale); this
  snapshot; CLAUDE.md "Current status" bullet.
- **Deploy artifacts:** `docs/DEPLOY-RUNBOOK.md` (empty tenancy → installed
  PWA → cutover → decommission); `deploy/driverdna.service` (loopback bind,
  single uvicorn process by construction, H3 hardening, `0600` EnvironmentFile);
  `deploy/driverdna-backup.{service,timer}` (`sqlite3 .backup`, daily);
  `deploy/cloudflared/` (tunnel config + Access notes). `.github/workflows/
  deploy.yml` (Cloud Run) **removed**; `Dockerfile` de-`pg`'d and marked the
  optional/local SQLite container, not the deployment of record.

Migration mechanics for the owner (runbook has exact commands): `driverdna
store-copy --from <supabase> --to driverdna.db` (PK-preserving, per-table
checksum, refuses a non-empty target) carries the irreplaceable rows
(`driver_beliefs` history, chat/coach transcripts, `finding_annotations`,
`config_history`); then `backfill-blobs` for historical raw traces; then the
systemd + Cloudflare bring-up. Deleting the Supabase project (which ends the
egress billing) is the final owner-executed step, kept off the automated path
deliberately.

### Verified counts (2026-08-05, Supabase → SQLite/VM migration prep)

| What | Result | Command |
| --- | --- | --- |
| Tests, before any change (baseline) | **879 passed, 16 skipped, 0 failed** | `.venv/bin/python -m pytest` |
| Tests, after | **885 passed, 16 skipped, 0 failed** | `.venv/bin/python -m pytest -rs` |
| New tests | **+6** (`tests/test_backfill_blobs.py`) | — |
| Skips | all 16 are Postgres-absent (`DRIVERDNA_TEST_DATABASE_URL` unset); no browser tests present in this run | `pytest -rs` skip lines |
| Backend under test | SQLite (a venv `git clone` install; no Postgres, no secrets) | — |

Not done, flagged rather than claimed: this is **migration prep verified
against the local suite and fixtures**, not the live cutover. VM provisioning,
the `store-copy` off the real Supabase, `backfill-blobs` against the owner's
real CSVs, and the Cloudflare/OAuth bring-up are the owner's runbook steps and
have not been run from here (no Oracle tenancy, Supabase URL, or owner CSVs in
this session). "Done means merged" applies to this code+docs change; the
deployment itself completes when the owner works the runbook.

---

**Snapshot date: 2026-08-04 (mobile UI improvement pass, owner-directed).**
Extended U7's mobile CSS beyond its original single-breakpoint pass
(`ui/src/app.css`, `ui/src/views/cohort.jsx`). Verified in a real browser,
not just reviewed as CSS: `driverdna demo` + Playwright at 390×844 (the
project's own reference viewport) and 320×700 (iPhone SE, the narrowest
common width) across Driver home, Driver Model, Garage, Cohort, Chat, and
Laps. **Zero horizontal body overflow at either width, on every route
checked** (`document.body.scrollWidth > window.innerWidth` false
throughout) — the trust-gate-5 property UI-V3-PLAN.md flagged as
"specified but not yet built" as an automated 390×844 parity pass; this
session's check was manual/one-off, not a committed test, so that gap
still stands.

What changed, and why (DEPLOY-SPEC D3's "mobile = read + chat subset"
still governs which views got real phone treatment vs. stayed merely
legible):
- **Cohort view's lap board** (`ui/src/views/cohort.jsx`): was a
  `.scroll-x`-wrapped table, the most-viewed table in the app and the
  worst fit for sideways scrolling on a phone. Now stacked rows
  (`.lap-row`) — verified legible at both widths, incident chips and
  best-lap highlighting intact.
- **Chat input**: `position: sticky; bottom: 0` below the 48rem
  breakpoint (verified via computed style: `sticky` on a 390px viewport,
  `static` on desktop — the media query is real, not just present in
  source), so it no longer scrolls away during a long conversation;
  `env(safe-area-inset-bottom)` respected. Chat log's fixed `max-height`
  is dropped on mobile so the page scrolls naturally instead of
  double-scrolling.
- **Tab bar**: confirmed horizontally scrollable, not clipped — at
  320px only 5 of 6 tabs fit in view, but `nav`'s own scrollWidth
  (365px) exceeds its clientWidth (304px) and every tab, including
  Config, is reachable by the existing scroll-snap. No hamburger, per
  the standing "hiding where you are is the wrong trade" rule.
- **Laps view's data-quality table** deliberately left as-is: confirmed
  it already follows the intended pattern — the `.scroll-x` container
  scrolls internally (table 500px in a 353px box) while the page body
  never does. This is the desktop-shaped-but-legible tier D3 allows for
  a secondary table; not converted to stacked rows.
- Stat tiles, Driver Model meters, coaching cards, findings, config rows,
  staged-change rows, and the upload form all gained `flex-wrap`/stacking
  at 48rem so long labels and values don't collide. New ~26rem (415px)
  breakpoint for small-phone refinement (2-column tiles, smaller
  headings/tabs/chips).

Full suite green throughout (**850 passed, 16 skipped**, same skip set as
the 2026-08-03 baseline — all Postgres-absent). `test_ui_static.py`,
`test_render_parity.py`, and `test_cockpit_ui.py` run directly and green.
SPA rebuilt and reshipped (`npm run build`); confirmed the new mobile CSS
(the 26rem breakpoint, `.lap-row`, sticky `.chat-input`) is present in the
built, minified bundle, not just the source. Committed and pushed to
`claude/mobile-ui-improvements-m51my0` (not yet merged to `main` or opened
as a PR — awaiting the owner's go, per "done means merged" this is the
stated why-not, not a silent gap).

**Not done, flagged rather than silently skipped:** the 390×844
render-parity pass UI-V3-PLAN.md's Track A done-criteria calls for was
not added as a committed automated test — this session's browser
verification was manual (screenshots + one-off Playwright scripts in the
scratch dir, not `tests/`). Corner drill-down, finding evidence, config,
and upload views were left in their "reachable and legible, not
optimized" tier per D3 — not audited beyond confirming the existing
44px-tap-target and flex-wrap rules already apply to them generically.

**Snapshot date: 2026-08-03 (reference laps R2/R3).**
`docs/REFERENCE-LAPS.md`'s R2 (identity/depth) and R3 (curation)
are built (SPEC.md A39) — six open decisions, all asked via `AskUserQuestion`
and owner-confirmed before any code: no `--ref-label` column (the existing
`driver` column is sufficient identity); one aggregated envelope, not split
per contributor; the corner drill overlays reference n/median/best as extra
columns on the self phase-times row; curation is an exclusion flag through
the audited-annotations pattern (reversible, never deletes); the toggle lives
in the cohort view's References panel and as CLI commands; the cascade is
immediate (payloads read live DB state on every fetch, no rebuild step).
Exclusion is enforced once, at `db.phase_history`'s query surface
(role='reference') — the same place role isolation itself is enforced
(A34) — so `attribution/ranker.py` needed no changes at all to honour it.
One real gap found and closed along the way, not part of the original ask:
`POST /api/laps/upload` hardcoded `driver="owner"` for every upload
regardless of role, which would have made decision 1 only half true on the
browser ingestion path; fixed with one optional form field, default
unchanged for self uploads. Verified against real fixture telemetry (the
`spa-blind-2026-07/` GR86/Spa laps, imported as a genuine second, reference-
role lap) and a real Playwright browser session (cohort page envelope +
identity, the Exclude/Include toggle updating live with no reload, the
corner drill's overlay columns) — not yet against the owner's own production
store, which presently holds zero reference laps (see the run below). R4
(reference-geometry adoption) is untouched. Suite 850 → 879 passed (0
failed), +29 tests. Full record: `docs/SPEC.md` A39.

### Verified counts (2026-08-03, reference laps R2/R3)

| Count | Value | How to reproduce |
|---|---|---|
| Tests, before any change (baseline) | **850 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after | **879 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests this session | **29** — 19 in `tests/test_reference_curation.py` (DB/payload/ranker/CLI), 7 appended to `tests/test_api.py` and `tests/test_upload_api.py` (endpoints, upload driver field), 3 in `tests/test_reference_curation_ui.py` (Playwright) | `python3 -m pytest tests/test_reference_curation.py tests/test_reference_curation_ui.py` |
| Existing tests modified | **1 line**, `tests/test_blobs.py`'s `_v5_database_with_inline_blobs` helper now also drops `reference_exclusions` when simulating an old database — the same maintenance every migration since 008 has required there | `git diff tests/test_blobs.py` |
| `vs_reference_findings` / `attribution/ranker.py` changes | **0** — exclusion enforced once in `db.phase_history`, proven by a test that excludes a lap, re-runs the unmodified ranker function, and diffs the findings list | `python3 -m pytest tests/test_reference_curation.py -k vs_reference_envelope` |
| Playwright: cohort page + corner drill against a real reference lap | **3/3 passed** — envelope/identity render, Exclude/Include updates live with no reload, corner-drill overlay columns show real values | `python3 -m pytest tests/test_reference_curation_ui.py` |
| Committed `docs/*-report.md` | untouched — this session never ran a report command against the committed fixtures | — |
| Skips | 16, all Postgres-absent (Chromium was present and exercised — the two browser trust gates plus the new Playwright suite all ran green) | — |

**Snapshot date: 2026-08-03 (later still, Chromium CI).** Action item closed:
CI now runs the browser trust gates instead of silently skipping them.
`.github/workflows/tests.yml` gained a `browser-tests` job — installs Chromium
via Playwright, builds the SPA (`npm ci && npm run build`), and runs the six
Chromium-gated test files (`test_render_parity`, `test_offline`,
`test_upload_ui`, `test_auth_ui`, `test_cockpit_ui`, `test_score_history_ui`).
Non-blocking (`continue-on-error: true`), matching `docs/SPEC.md`'s stated
next step: the main `pytest` job stays the merge gate, this job's red/green is
now a visible, honest signal instead of an invisible skip. A guard step (same
pattern as the existing Postgres-backend guard) fails the job outright if the
skip reason still fires despite the Chromium install, so the job can't go
green by silently skipping again.

Verified before merging (`claude/chromium-ci-setup-3ru4mz` → `main`,
fast-forward, no other pushes landed on `main` in between):

| Count | Value | How to reproduce |
|---|---|---|
| Full suite, this container (Chromium + built SPA both present) | **850 passed, 16 skipped, 0 failed** | `python3 -m pytest -rs` |
| Skips | 16, all Postgres-absent (no local Postgres in this container) — **zero Chromium/SPA-absent skips**, confirming the browser tests actually ran | — |
| The six Chromium-gated files, run directly | **17 passed** | `python3 -m pytest tests/test_render_parity.py tests/test_offline.py tests/test_upload_ui.py tests/test_auth_ui.py tests/test_cockpit_ui.py tests/test_score_history_ui.py` |
| `test_agent_contract.py` (incl. the AGENTS.md 11,000-char size budget) | **8/8 passed** — AGENTS.md is 9,025 chars after the edit | `python3 -m pytest tests/test_agent_contract.py` |

Docs/workflow-only change (`tests.yml`, `AGENTS.md`, `docs/SPEC.md`); no
`driverdna/` source touched, so this baseline is a completeness check, not a
regression risk. `AGENTS.md`'s "What CI does and does not cover" section and
`docs/SPEC.md`'s A16 note both updated to describe the new job rather than the
old skip. **Not yet independently confirmed**: this session verified Chromium
install + browser tests locally (this environment ships Chromium
pre-installed) but did not watch a live GitHub Actions run of the new
`browser-tests` job — the `actions/setup-node` + `playwright install
--with-deps` steps are standard but unexercised in the real Actions
environment until the next push triggers them.

**Snapshot date: 2026-08-03 (later still).** Closed the loop this doc itself
posed: "re-running `sync` is the cheapest available evidence... requires no
driving." Owner supplied `GARAGE61_TOKEN` for a one-off run against a scratch
DB in this session (never persisted, never committed — no DB has ever been in
this repo per `.gitignore`). Two attempts failed instantly with `Connection
reset by peer` before any request reached the API; a bare `curl`/`urllib` call
through the same path succeeded seconds later, so this was a transport-layer
flake in how the CLI's console-script binary opened its first connection, not
a bad token. Running the same logic in-process got to 318 laps before one
further reset, then a resumable retry-with-backoff loop finished cleanly.

**Real yield: 992 self laps, 31 cohorts, 0 reference laps, every lap dated.**
Confidence terms are now saturated on every corpus-breadth gate (evidence
985/50, sessions 212/6, tracks 19/3, cars 10/2 — all "met"); census's own
"what to add next" table has nothing left on it but a reference lap. Findings
shown jumped from 15/177 (fixture data) to **564/3149** on the real corpus.

This also resolved the open question about this session's manually-uploaded
Mustang GT4 laps: merging them into the synced data showed **all 10 are
content-hash duplicates of laps already synced** — the real Spa GT4 cohort is
26 laps / 6 sessions (36 findings now shown), not the 10-lap / 0-session
cohort this session had been testing the A34 fix against. No actual A27
label-drift split existed here; it was moot because it was the same
underlying laps under `sync`'s API-sourced label the whole time.

**One mistake, caught before it landed:** `driverdna model` run without
`--out` from the repo root defaulted to writing the tracked
`docs/driver-model-report.md` — meant to be regenerated from the committed
fixtures only — with real-account output. Caught via `git status` before
any commit; reverted with `git checkout --`. Every real-data query after that
point went through the payload API directly or into the session scratchpad,
never a bare CLI default path. Worth restating for the next agent: **any CLI
command that writes a report defaults into `docs/`** — always pass an
explicit `--out` when running one against anything other than the committed
fixtures.

**Not done:** the sync ran against an ephemeral scratch DB, not a real
production store — nothing here is the owner's actual running instrument
until they choose to point `driverdna` at a persisted DB and sync there
themselves (or ask for that explicitly). R4 (`docs/REFERENCE-LAPS.md`,
reference-geometry adoption) remains drafted and unbuilt, awaiting the
owner's explicit go given its flagged tension with AGENTS.md's reference-
isolation non-negotiable.

**Snapshot date: 2026-08-03 (later).** Owner supplied 4 more real Mustang GT4
laps at Spa (one landed as a content-hash duplicate of an already-imported
lap, correctly caught), taking the self cohort from 6 to **10 laps**. Rerun
against a scratch DB with the A34 fix live: at 10 laps, `min_phase_samples=10`
finally clears for **43 of 150 findings** — the first time volume alone has
cleared that gate on this cohort. All 43 are still hidden, now behind a
*different* wall: `insufficient data: 0 session(s) < 2`. Manually-imported
laps carry no `session_key` (only `sync` populates it from the API), so a
cohort built entirely by upload can satisfy every sample-count gate and still
show nothing. Not a bug — the gate is doing its job — but a concrete, specific
answer to "what's blocking me now": sync this car/track instead of
uploading it, or the sample-count win is wasted.

Also asked, reasonably: isn't a reference lap the gold standard, so why can't
it define the map? Answered and recorded as **R4** in
`docs/REFERENCE-LAPS.md` (design stage, **not built**, owner's explicit go
required before any code): a reference lap is the right target to aim at, but
the corner map is the ruler measurements are taken through, and A34 exists
precisely so the ruler stays the driver's own. R4 drafts a legitimate,
opt-in, versioned, reversible path to deliberately adopt a reference's
geometry — explicitly flagged as being in tension with AGENTS.md's
"reference laps never enter self history" non-negotiable, since the
on-screen effect (self phase times changing from reference data) is the same
shape as the bug just fixed, even though the mechanism is closer to
`ConfigStore`'s driver-initiated propose/confirm/revert. See
`docs/PROJECT-BRIEF.md`'s 2026-08-03 decision-log entry.

`docs/REFERENCE-LAPS.md` also corrected: R0's "reference-first-in-empty-cohort
... untested" note was true when written and is false now — A34 both tested
and refused it. R0 and R1 marked done in that doc for the first time.

**Snapshot date: 2026-08-03.** Reference-lap isolation restored at the corner
map (SPEC.md A34), on `claude/engine-validation-lap-data-388xct`. The owner
supplied a reference lap and then six of their own Mustang GT4 laps at Spa, so
the vs-reference path ran on real data for the first time in the project's
history — and running it exposed that reference laps were defining the driver's
own geometry through three paths the measurement-layer `role='self'` filters
never covered: founding a cohort's corner map, counting toward corner
admission, and feeding A22's `rebuild-map` refreeze.

Measured on the owner's real 6-lap GT4/Spa cohort by rebuilding a clean copy
and a with-reference copy and diffing:

| Before the fix (one reference lap present) | After |
| --- | --- |
| **11 of 14 corners moved**, largest 46.94 m (C08) | 0 moved (0.000000 m) |
| **11 of 14 phase windows differed** | identical |
| **154 of the owner's 191 phase times changed**, up to **1.57 s** | identical |
| Driver Model `corner_exit` 67.5 → 67.4, `rotation` 61.6 → 61.1 | identical |
| A reference CSV alone founded an 11-corner map in an empty store | refused, exit 2 / HTTP 422, nothing written |
| Reference lap's own 31 phase times, 30 vs-reference gaps | unchanged — isolation is not exclusion |

On the older GR86/Spa fixture cohort the admission path alone moved
`consistency` 34.31 → 32.26. **Blast radius: none committed.** Both fixture
manifests hold zero reference laps, so no committed corner map was ever
influenced and all seven `docs/*-report.md` regenerate byte-identical.

The existing guard (`test_reference_import_perturbs_gap_sections_only`, M3
trust gate 3) passes honestly and always did — its synthetic reference lap
matches corners that already exist, so the admission path never runs and it
never rebuilds. The guarantee was pinned one layer above where it broke.

### What the six new GT4 laps say about the original question

The cohort now holds 6 self laps + 1 reference lap and produces **30
vs-reference gap findings totalling 6.54 s** against a real 10.73 s lap-time
gap — all of them still suppressed by `insufficient data: 5–6 phase samples <
10`. So the concrete answer to "which laps do I need": **about 4–5 more Mustang
GT4 laps at Spa** turns those 30 computed gaps into shown ones. Census also
surfaced a distinct gap worth recording: manually-imported laps carry no
`session_key`, so this cohort reports **sessions 0/6** and a full quarter of
Driver Model confidence is unreachable through the import path alone (`sync`
populates it from the API; manual import does not).

### Verified counts (2026-08-03)

| Count | Value | How to reproduce |
|---|---|---|
| Tests, before any change (baseline) | **744 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after | **761 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests this session | **17** — 13 in `tests/test_reference_isolation.py`, 2 in `test_import_cli.py`, 2 in `test_upload_api.py` | `python3 -m pytest tests/test_reference_isolation.py` |
| Existing tests modified | **2**, setup only (`test_reference_lap_is_never_scanned_into_incidents`, `test_reference_role_is_isolated_like_the_cli_path`) — each imported a reference lap into an empty cohort as a convenience; a self lap now precedes it. Assertions unchanged. | `git diff tests/test_incidents.py tests/test_upload_api.py` |
| Committed `docs/*-report.md` regenerated from real fixtures | **7/7 byte-identical** — the proof the fix moved no committed number | `driverdna import tests/fixtures --db <tmp>` then each report command, diffed |
| Real GT4 cohort, rebuilt with vs. without the reference lap | corners, windows, all 191 self phase times and the Driver Model **identical** | two DB copies, `driverdna rebuild-map` on each, rows diffed |
| Skips | 16, all Postgres-absent or Chromium-absent | — |

The 16 skips mean the two UI-SPEC browser trust gates did not run here, as in
CI. Green above is not evidence they hold.

**Snapshot date: 2026-08-02.** `driverdna census` built (SPEC.md A33), on
`claude/engine-validation-lap-data-388xct`. The owner asked whether more lap
data would help validate the engine; the corpus now answers that itself
instead of an agent hand-reading a payload. Census reports have-vs-need for
every gate and ranks what to add next, applying no gate of its own — thresholds
come from config, suppression reasons are quoted verbatim off the engine's
payload, and a gain it cannot compute prints `—` rather than a guess.

One refactor made it possible: `_confidence` computed its four ratios inline,
so `confidence_terms()` now exposes them and `_confidence` is their mean plus
the unchanged proxy cap. Proven number-neutral rather than asserted — see the
counts below.

What the first real-fixture run says about the actual question:

| Finding | Value |
| --- | --- |
| Confidence ceiling, measured fundamental (12 laps, 2 cohorts) | **60.2%** |
| Findings shown | **15 of 177 computed** |
| Dominant blocker | **`insufficient data: 1 phase samples < 10`, 75 findings** — the single-lap Mustang/Laguna Seca cohort |
| Saturated terms (more buys nothing) | none yet at 12 laps; `sessions` saturates at 6 and is already there on the live 11-lap instrument |
| Reference laps ever imported | **0** — the vs-reference path has still never run on real data |
| Dated laps | **0 of 8** needed, so `trend` is unavailable on every fundamental |

Separately established while answering the question, and worth acting on: the
live/hosted instrument (`reports_hosted/driver.json`) runs on **11 laps, 1 car,
1 track**, while a real `group=none` sync listed **~928 laps across 9 cohorts**
(A30) whose importable yield was never recorded. Re-running `sync` is the
cheapest available evidence by a wide margin and requires no driving.

### Verified counts (2026-08-02)

| Count | Value | How to reproduce |
|---|---|---|
| Tests, before any change (baseline) | **726 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| Tests, after | **744 passed, 16 skipped, 0 failed** | `python3 -m pytest` |
| New tests this session | **18** in `tests/test_census.py` | `python3 -m pytest tests/test_census.py` |
| Committed `docs/*-report.md` regenerated from real fixtures | **6/6 byte-identical** — the proof the `confidence_terms` extraction moved no number | `driverdna import tests/fixtures --db <tmp>` then each report command, diffed |
| `docs/census-report.md` across two separate processes | **byte-identical** | `driverdna census --db <tmp> --out a.md` twice, diffed |
| Skips | 16, all Postgres-absent or Chromium-absent | — |

The 16 skips mean the two UI-SPEC browser trust gates did not run here, as in
CI. Green above is not evidence they hold.

**Snapshot date: 2026-07-29.** Lap-analysis protocol built and its first
calibration batch sealed (`docs/LAP-ANALYSIS-PROTOCOL.md`). Two new commands:
`driverdna lap-digest` cuts a lap into readable per-corner slices and measures
nothing (row/column selection only, asserted cell-for-cell), and `driverdna
verify-observations` checks a reading's numbers against the digest bytes,
reusing `coach.grounding`'s tolerance rather than defining a second one. Wired
into both non-Claude hosts (`GEMINI.md`, `.agents/rules/driverdna.md`) plus one
line in `AGENTS.md`, which now sits at 10,857 chars against the 11,000 test
budget — 143 to spare, so the next edit there needs the count checked.

Batch B01 (the 11 `spa-blind-2026-07/` laps, 198 slices) has its answer key
pre-registered, the reviewer's own observations written, grounded 19/19, and
committed as the seal — all before any reading agent ran. **Awaiting the owner
to run Flash and to supply the 10 Mustang laps for B02.** One finding already,
not in the answer key and not yet acted on: brake re-application after the
corner's brake release, on 8 of 11 laps at C01, concentrated at five corners
and absent at ten, counted by no metric — while `throttle_modulation_count`
counts the exact throttle analogue. Also unmeasured: `gear` reaches the
analysis chain in exactly one place, `segmenter.py:193`, where gear-0 spans are
*excluded* from corner detection rather than measured.

| Count | Value | How to reproduce |
|---|---|---|
| Tests | 726 passed / 16 skipped at session start; +29 added | `python3 -m pytest` |
| Blind-batch slices | 198 (11 laps x 18 corners) | `driverdna lap-digest --db <db> --out-dir <dir>` |
| Reviewer observations, B01 | 19 grounded / 0 rejected | `driverdna verify-observations --obs docs/lap-analysis/b01/claude-observations.jsonl --digest-dir <blind>` |
| `AGENTS.md` size | 10,857 chars (budget 11,000) | `python3 -c "print(len(open('AGENTS.md',encoding='utf-8').read()))"` |

The 16 skips are all Postgres-gated. Note that in this container Chromium *is*
present, so `test_render_parity.py` and `test_offline.py` ran rather than
skipping as they do in CI.

**Snapshot date: 2026-08-02 (updated).** `docs/UI-V3-PLAN.md` built end to
end, **including Track C3** — see the update at the end of this entry.
All three tracks landed in this session, each committed separately with
its own tests, on `claude/ui-incidents-gemini-coach-93l5h7`.

- **Track A (UI v3 "cockpit feel" + U7 mobile) — built.** A1-A6 all done:
  a chrome-only accent token (`#3FC7DE`, chosen over a documented magenta
  alternative, owner's call still open — see the v3 mockup) plus
  interactive micro-motion; the `.disclosure` "methodology arrow" pattern
  (`src/driverdna/explain.py`'s `METHODOLOGY` dict, one `GET /api/explain`
  pass-through, reused by both A3 and Track B); a wide-viewport two-column
  layout with zero DOM reordering; the score-history chart (`dm-hist-v1`,
  SPEC.md A36) — see its own entry below; the mobile responsive pass +
  PWA shell (manifest, service worker, an offline banner); and
  `docs/ui-redesign-mockup-v3.html`, assembled from real Playwright
  screenshots of the built SPA rather than hand-drawn placeholders.
- **SPEC.md A36 — score history (`dm-hist-v1`) — built.**
  `model/history.py` generalizes M6 trend's own 2-bucket `_bucket_score`
  machinery to N buckets (`config.model.history_buckets`, default 6),
  producing no new kind of number (SCORING_MODEL_VERSION untouched). The one
  dangerous edit the plan flagged — bucketed scoring was entirely uncached
  before this — is fixed by giving `_CohortCache` a `lap_pks` scope it
  checks before ever reusing a row, with a dedicated test proving a cache
  built for one bucket can't silently answer another's query (the failure
  mode that would draw a plausible-looking flat line). A second, subtler
  correctness detail: `_trend`'s own 2-way split always gives the *recent*
  bucket the remainder lap on an odd count, so the new N-way bucketer had
  to match that convention or `history_buckets=2` would silently diverge
  from `_trend` on the owner's real 25-lap (odd) history — caught and
  tested before it shipped, not after.
- **Track B (incidents for newcomers) — built.** B1-B4: `IncidentCard`
  (visible: what happened, corner, N=1 line; behind one disclosure click:
  an empathy line, the mechanism in plain language, a real drill, and the
  engine's full raw-evidence rationale) and `IncidentMechanismCounts`
  (counting, not computing). B3 lifts the M5-era boundary that kept
  incidents out of chat's grounding entirely — additive only: a classified
  incident becomes citable, an unclassified one stays structurally
  uncitable (absent from `ChatSession._known_ids`, not merely
  rule-forbidden), `CHAT_PROMPT_VERSION` chat-v2 -> chat-v3. B4 regenerated
  `docs/incidents-report.md` and diffed byte-identical (payload additions
  don't touch that generator).
- **DEPLOY-SPEC Track P (Gemini provider) — built, mock-tested, AND now
  live-verified (Track C3, SPEC.md A38).** `GeminiCoachProvider` /
  `GeminiChatProvider` built against the real installed `google-genai` SDK,
  verified by direct introspection (not memory or possibly-stale fetched
  docs) — a newer `client.interactions.create` surface also exists in the
  current SDK and was deliberately not used, since this doc's own design
  assumes the classic `generate_content` shape. `coach.provider` now
  defaults to `"gemini"` (`gemini-3.5-flash`, pinned from
  `ai.google.dev/gemini-api/docs/pricing`, verified 2026-08-02). Tool-schema
  translation, message translation (including the tool-result round trip
  that recovers a function name Anthropic's own block doesn't carry), and
  429 backoff are all tested against real SDK response objects with only
  the network call mocked.
  **Track C3, completed 2026-08-02**: the owner supplied a real
  `GEMINI_API_KEY` for one session (rotated immediately after — never
  persisted, never committed, used only as a transient env var). The live
  run surfaced two real defects, both fixed in the code (never in the
  validator — see SPEC.md A38 for full detail):
  1. `coach.max_tokens` default (4000) silently starved `gemini-3.5-flash`
     — a thinking model whose reasoning tokens share the output budget —
     producing an empty response (`finish_reason=MAX_TOKENS`) that the
     validator correctly rejected as "not valid JSON" for the wrong
     underlying reason. Raised to 16000; harmless for Claude.
  2. `coach`'s `SYSTEM_PROMPT` had two real ambiguities that Gemini hit on
     5/5 raw attempts (Claude apparently never triggered either): the
     no_signal "never attach confidence" rule read as applying to ordinary
     `hypotheses[]` too, and nothing said an `incident_explanations[]`
     entry must cite its own `incident_id` in its own `evidence_ids`. Both
     clarified; `PROMPT_VERSION` `coach-v2` → `coach-v3` (wording only, no
     schema/validator change).
  **Result: 2/2** live `driverdna coach` runs against the real fixture
  cohort (`GR86:Spa-Francorchamps`) passed the strict validator unmodified
  on the first attempt after both fixes (0/5 before). One live grounded
  chat turn through `GeminiChatProvider` — the primary interactive
  surface, unaffected by the prompt issue since it already had chat's
  regenerate-once loop — also passed on the first attempt, citing real
  `obs:<n>` evidence and real `cp.*` coaching principle IDs. The acceptance
  gate DEPLOY-SPEC named is now met, not just designed.
- **SPEC.md A37 (per-user AI keys, BYOK) — built.** AES-256-GCM
  (`cryptography`, newly explicit in the `ui` extra), key-encryption key
  derived from `DRIVERDNA_SESSION_SECRET` via `hashlib.scrypt` with its own
  domain-separation salt (distinct from `ui/auth.py`'s session-signing
  derivation off the same secret). `PUT/GET/DELETE /api/settings/ai-key`;
  GET returns only a fingerprint, never the key. Two real bugs the render-
  parity and offline trust gates caught during this build, both fixed
  properly rather than routed around: (1) the config panel's generic value
  renderer tagged every value `.num` regardless of type, and the new
  `gemini-3.5-flash` string contains a decimal-shaped substring the
  crawler correctly flagged as an uncited number — fixed by only tagging
  actual numbers; (2) an initial "get a free key" link put a literal
  `https://` URL into the built bundle, which trust gate 5's stricter-than-
  requests bundle-content check forbids — fixed by making it plain,
  unlinked attribution text instead of walking back the guarantee.
- **Two environment-level things fixed while building, worth recording
  since they'd otherwise resurface for the next agent**: the container's
  system `cryptography` package was missing `cffi`, which crashed (a Rust
  panic, not a catchable ImportError) on first import of `google-genai` —
  fixed by installing `cffi`; and `python3 -m driverdna.cli <args>` silently
  does nothing (no `__main__` guard in `cli.py`) — use the installed
  `driverdna` console script or `python3 -m driverdna` instead.
- **Track C3 (above) is now done.** `docs/UI-V3-PLAN.md` is built and
  tested end to end, with no remaining flagged gaps.

**Snapshot date: 2026-07-29.** Plan adopted, nothing built:
**`docs/UI-V3-PLAN.md`** — owner-directed UI v3 ("fun factor" + the mobile
pass, merged because they touch the same CSS), incidents rewritten for
newcomers, and the coach moved to Gemini with per-user bring-your-own-key.
It schedules two already-adopted DEPLOY-SPEC designs (Track P: Gemini
provider; Track M: mobile/PWA, renamed U7 to stop colliding with UI-SPEC's
own U5) and adds three amendments to write before any code: **A35** design
language v3, **A36** score history `dm-hist-v1`, **A37** per-user AI keys.

One investigated finding worth recording here, because it reverses the
premise of the original request: **"sign in with Google, use your own Gemini
quota" is not available to third-party apps.** Google AI Pro/Ultra are chat
subscriptions with no API access; Gemini API quota and billing always follow
the Cloud project behind the key, never the signed-in user; and Google states
that piggybacking Gemini CLI's OAuth to reach its backend services is a terms
violation and grounds for account suspension, naming an AI Studio or Vertex
API key as the supported path. The owner's decision (2026-07-29) is therefore
bring-your-own-key with a server-side `GEMINI_API_KEY` fallback.

**Snapshot date: 2026-07-28.** Multi-tenant accounts merged (SPEC.md A32):
Google OAuth, SMTP password resets (via SendGrid), and `owner_user_pk`
partitioning across every table (`laps`, `incidents`, `driver_beliefs`, etc.),
superseding the single-driver passphrase auth built the day before (A31). Row-
level security and per-tenant data isolation are tested extensively; every
deterministic grounding test stays strictly scoped per tenant. Landed via PR
#11 alongside three real bugs found while fixing this branch's CI (below) —
none were in the original CI failure report, which only got as far as the
first.

**Snapshot date: 2026-07-28.** Investigated three owner-reported problems
(Cloud Run 500s + slow loading, "cloud actions flow did not run" emails,
CI red on `antigravity/multi-user-accounts`) on `claude/driverdna-issues-analysis-gsuysa`.

- **The "did not run" emails were a real, currently-red test, not a cosmetic
  guardrail step as first assumed.** `deploy.yml` has no dependency on
  `tests.yml` and deploys unconditionally on every push to `main` — that part
  of the original read was right. But `tests.yml` itself was genuinely
  failing on `main`: `test_agent_contract.py::test_agents_md_fits_antigravity_rule_limit`,
  because `AGENTS.md` grew to 11405 chars in the TDD-guardrails merge, over
  its 11000-char budget. Confirmed against the actual failed-job logs
  (runs 30297184257, 30295013798), not inferred. Fixed by trimming prose
  (no content removed, 10883 chars) and re-syncing the byte-for-byte mirror
  in `.agents/rules/driverdna.md`, which had drifted on the one changed line.
- **Issue 1 (500s / slow `/api/driver`) fixed**, building on
  `claude/db-performance-review-28d3et` (a prior session's unmerged work:
  migration 007 indexes, `build_driver_payload` skipping per-cohort
  findings/coaching/incidents for the rollup, `compute_all_beliefs` cached
  per cohort). Added on top: `GET /health` (no DB access, for Cloud Run's
  liveness probe) and a global exception handler (structured JSON 500 +
  logged traceback, instead of an unlogged bare crash). Replaced that
  session's single-shared-Postgres-connection optimization with a real
  `psycopg_pool.ConnectionPool` (`open_postgres_pool`, `Database.from_pool`):
  the shared connection was a genuine thread-safety hazard, not just a missed
  optimization — FastAPI dispatches sync routes to a thread pool, and psycopg
  connections are not safe for concurrent use from multiple threads. Verified
  with a real local Postgres (dedicated unit tests proving concurrent
  checkouts get distinct connections, plus an API-level test asserting
  `app.state.pool` is a real `ConnectionPool`). Full suite green on both
  backends (`python3 -m pytest` with `DRIVERDNA_TEST_DATABASE_URL` set).
- **Issue 3 (auth branch CI) fixed on `antigravity/multi-user-accounts`
  itself**, not `main` — three real, distinct bugs, not just the one CI
  reported:
  1. `AUTOINCREMENT` (SQLite-only) left dangling after `sql.py`'s regex
     already rewrote `INTEGER PRIMARY KEY` to Postgres's IDENTITY syntax —
     the reported CI failure (runs on 30374413968).
  2. One statement later: migration 008's SQLite-style table-rebuild
     (`PRAGMA foreign_keys=OFF`, `DROP TABLE`, rename) has no Postgres
     equivalent, and Postgres refuses a `DROP TABLE` another table's FK still
     points at (`incidents.lap_pk -> laps`). `sql.py`'s `to_pg_ddl` now strips
     `PRAGMA foreign_keys` statements and appends `CASCADE` to `DROP TABLE`
     for Postgres — the rebuilt table's own `CREATE TABLE` re-declares the FK,
     so nothing is lost.
  3. `test_auth_ui.py` (Chromium-gated, so silently skipped whenever
     Chromium/the built SPA is absent — the CI default, which is exactly why
     this went unnoticed) still called `create_app(..., access_token=TOKEN)`,
     a parameter the multi-tenant commit renamed to `session_secret`
     everywhere else. Fixed the call sites, the stale docstring, and a
     data-isolation trap the fix surfaced: the test's browser login used a
     *newly inserted* user, which authenticates fine but owns none of the
     imported fixture data (`owner_user_pk` isolation is real and working) —
     the fixture now sets a password on the migration's pre-seeded
     `owner@example.com` row (`user_pk` 1, the actual owner of imported data)
     instead. Also fixed: `login.jsx` still posted `{token}` for a
     single-driver passphrase; `LoginBody` has required `email`+`password`
     since the multi-tenant commit. Added email+password fields, a
     conditionally-rendered Google button (`/api/auth/status` gained
     `google_enabled`, never the client secret), and renumbered this
     branch's two new migrations (007→008, 008→009) around Issue 1's
     migration 007 landing on `main` first, updating `tests/test_blobs.py`'s
     hardcoded `schema_version == 11` to `== len(MIGRATIONS)` so it does not
     silently drift again the same way.
  Not fixed / flagged for the owner: there is still no way to set a real
  password for a seeded user or create additional ones outside direct DB
  access or Google OAuth — a real gap in the multi-tenant flow, out of this
  fix's scope (it is a design decision, not a bug).
- **Known, unrelated to all three issues above:** `test_offline.py`'s trust
  gate still fails locally on a stale/rebuilt SPA (`svg.trackmap` not found)
  — already documented below as invisible to CI (no Chromium there); not
  investigated further this session.

**Snapshot date: 2026-07-27.** On `main` after PR #6 (sync 404/403 guard A30, UI bug fixes), PR #7 & PR #8 & PR #9 (Cloud Run deploy pipeline WIF auth resolution, direct source build via `google-github-actions/deploy-cloudrun@v2`), and Phase 5 history purge (18 orphaned blob & report files removed, `*.blobs/` added to `.gitignore`). The Cloud Run service `driverdna` is live at `https://driverdna-b4wjnb2baa-nn.a.run.app`.
Previous: branch consolidation merge, A24–A29, A23 storage migration, UI U0–U6.
This is the single dated status doc; the verified counts below can be checked
for consistency over time. Binding records remain `docs/SPEC.md` (engine +
amendment log), `docs/ARCHITECTURE_VISION.md` (constitution), `docs/UI-SPEC.md`,
and `docs/COACHING.md` (M7 design). Orientation + full decision log:
`docs/PROJECT-BRIEF.md`.

**Two A23 follow-on hazards closed (2026-07-26, SPEC.md A26/A27).** Both were
found by reading the storage split's consequences, not by hitting them.
`rebuild-map` treated "raw trace unreadable" as "evicted by retention" and
deleted phase times on that basis — so running it from a machine that hadn't
imported a lap destroyed measurements still intact on the machine that had,
and misreported why. Eviction now leaves a tombstone in the blob store (not a
DB column: eviction is per-machine, the store may be shared), and a pre-flight
refuses before modifying anything when a trace is missing without one;
`--allow-missing-traces` overrides. Separately, `sync` labels tracks
`"Name (Variant)"` from the API while manual import uses the filename's bare
name, so doing both silently splits one cohort in two and halves the evidence
behind every baseline, trend and consistency number.
`cohorts.find_label_drift` now reports that at the end of `import` and in
`history` — reported, never merged, and deliberately silent on two *different*
variants, which are distinct cohorts by the spec's own rule.

**Three agents, one contract (2026-07-27, SPEC.md A28).** The owner now also
uses Gemini CLI and Antigravity, with unrestricted scope, during Claude Code
usage-limit windows. `AGENTS.md` is the single portable source of the build
rules — imported by `CLAUDE.md` via `@AGENTS.md`, loaded by Gemini CLI through
`.gemini/settings.json`, and non-negotiables-mirrored into
`.agents/rules/driverdna.md` for Antigravity, which caps a rules file at 12,000
characters (`CLAUDE.md` is 25,908, which is why extraction was necessary rather
than cosmetic). `tests/test_agent_contract.py` pins the mirror byte-for-byte and
the anchors of each non-negotiable separately, so neither drift nor quiet
deletion passes.

**And CI exists now.** Until this snapshot nothing ran the suite on push: every
invariant here is enforced by pytest and nothing else — no linter, no formatter,
no type checker. `.github/workflows/tests.yml` runs it on every push and on PRs
to `main`, on Python 3.11 and 3.12, with a Postgres service container so the A23
dual-backend guards execute rather than skip. **Honest limits:** CI does not
install Chromium, so UI-SPEC trust gates 1 and 5 (`test_render_parity.py`,
`test_offline.py`) skip there — green CI is not evidence those hold, and the
known `test_offline` failure stays invisible to it. And branch protection cannot
enforce "Claude Code on `main`, other agents via PR", because all three tools
push as the owner's one GitHub identity; the branch rule is convention backed by
push-triggered detection, not prevention. Both are recorded in `AGENTS.md`.

| Check | Result |
| --- | --- |
| `rebuild-map`, trace absent without tombstone | **exit 2**, nothing modified, names the lap_pk |
| `rebuild-map`, trace evicted via retention | proceeds, clears + reports, as A22 specified |
| Drift created by a real two-label import | warned at import **and** in `history` |
| Two different track variants | **not** flagged (distinct cohorts) |

**Import unblocked (2026-07-26, SPEC.md A24).** Garage61 renamed its browser
exports a second time, to `Garage 61 - <driver> - <car> - <track> - <laptime> -
<id>.csv`; the parser accepted only the 2026-07-21 double-underscore shape, so
`driverdna import` and `#/upload` both refused real laps. Not an A23 regression
— the rejection happens in a filename-only loop, before the store is opened.
Both newer shapes now go through one splitter, deliberately shared so the same
lap spelled either way yields byte-identical `car`/`track` (they are cohort
keys; two spellings would silently split a cohort). A delimiter *inside* a
field is refused rather than guessed. `--car`/`--track` and the `#/upload`
boxes are now independently optional — a given field applies to every file, a
blank one keeps auto-detecting — so the manual escape hatch that the docs
already promised actually exists. Verified against the owner's real filename,
CLI and browser.

| Check | Result |
| --- | --- |
| Owner's real filename, `driverdna import` with no flags | **imported**, car/track + ULID auto-detected |
| Both filename shapes into one store | **1 cohort**, not 2 |
| `--car` alone, track auto-detected per file | **imported**, note names only the detected field |
| `--car` alone + undetectable filename | **exit 2**, names the missing field, no DB created |
| Re-downloaded ` (1).csv` copy | reported **DUPLICATE**, 1 lap row, `lap_id` free of the suffix |

**Storage (2026-07-26, SPEC.md A23).** The primary store may now be a private,
single-tenant Supabase Postgres; SQLite remains a first-class, fully tested
backend and the offline/rollback path. Verified counts for this change:

| Check | Result |
| --- | --- |
| Test suite, no Postgres present (a clean `git clone`) | **565 passed, 13 skipped** |
| Test suite, against a local Postgres 16 | **578 passed, 0 skipped** |
| Committed `docs/*-report.md` after every phase | **byte-identical** |
| Cross-backend artifacts (same 12 fixture laps, SQLite vs Postgres) | **5/5 byte-identical** |
| `store-copy` SQLite → Postgres, per-table checksums | **15/15 identical** |
| Artifacts regenerated from the copied store | **5/5 byte-identical** |
| Tables in the hosted store | **17, all in `driverdna`, 0 in `public`** |
| Row-level security | **17/17 enabled, 0 policies (deny-all)** |
| `anon`-equivalent role with explicit SELECT grant | **reads 0 rows** |
| text columns without `COLLATE "C"` | **0** |
| float4 columns (would truncate metrics) | **0** |
| Fixture corpus: raw blobs vs compact rows | **~10 MB vs ~564 KB (12 laps)** |
| Migrations | **6** (006 renames `lap_samples`, non-destructively) |

Four latent defects were found and fixed during the port, all invisible on
SQLite because it satisfied them by accident: an unordered `corner_positions`
deciding which corner an incident was labelled with; the vs-self tercile split
lacking a tie-break; `AND 0` relying on int-as-boolean coercion; and incident
sample indices stored as BLOBs in INTEGER columns. Separately,
`docs/coaching-report.md` was found stale since the A18 ranker fix and
regenerated first, so the artifact byte-diff gate would mean something.

**Cutover to Supabase, owner-verified on real data (2026-07-26).** The owner
ran the migration against their actual synced history (not the fixture
corpus this repo's own tests use) and confirmed equivalence independently:
`driverdna report` against `driverdna.db` and against the Supabase connection
URL, diffed file-for-file across every generated Markdown report — zero
differences. `DRIVERDNA_DATABASE_URL` (session pooler) is now the owner's
normal path; `driverdna.db` is retained as the offline rollback, per A23.
This is corroborating, on the owner's own data, on top of the automated
cross-backend and checksum tests already in the suite — the fixture-based
proof and the real-data proof are two different things and both now hold.

**One line:** the deterministic engine (M0a–M7) is complete and verified; the
full UI-SPEC.md milestone track (U0–U4) is built, including the chat view
and the report/SPA visual unification. M6 trend now computes real
directions from dated laps (`sync`, or manual import with `--date`).
**The Spa blind acceptance test finally ran (2026-07-21, SPEC.md A18)** on
11 independent GR86/Spa laps the engine had never seen — it caught a real
bug (an unscreened incident lap could manufacture a phantom vs-self
"opportunity"; fixed to reuse `baseline()`'s existing outlier fence) and a
fictional ground truth (the spec's original Sector-1 prediction was never
engine-corroborated, on any dataset; retracted and replaced with the
engine's actual, now incident-robust output). Full narrative in
PROJECT-BRIEF.md's decision log.
**Incident subsystem built (2026-07-21, SPEC.md A19)**: a spin/off/near-stop
is now measured, not filtered — a deterministic lap-level scan + mechanism
characterization (`incidents/`), surfaced in the payload, a `driverdna
incidents` artifact, and the cohort/laps UI. **Coaching over incidents built
(2026-07-21, SPEC.md A20)**: the coach can now explain an incident's
classification (never choose or override it — the classification-to-principle
link is a fixed 1:1 engine mapping) through the same `coach` structured-output
path findings already use; chat's live Q&A doesn't consume incidents yet.
**Coaching + Driver Model surfaced in the UI, and upload-laps built
(2026-07-21)**: the M7 coaching layer (headline/secondary/self-checks) was
computed but never rendered — now a cohort-page section, grouped by
principle so one notable at many corners is said once, not repeated; the
Driver Model tab redesigned as a pyramid (foundations at the base, never a
blended score); and `#/upload` (`POST /api/laps/upload`, a thin wrapper over
`import_lap_file`) lets a driver import from the browser alone, including
the very first lap — the one write endpoint allowed to create the DB fresh,
closing the last CLI-only gap in UI-SPEC view 7. **Car/track auto-detect
from filename (2026-07-21)**: Garage61's newer export filename shape
embeds driver/car/track/laptime directly; both `driverdna import` (no
flags) and `#/upload` (blank fields) now auto-detect per file
(`parse_garage61_filename`), verified against the owner's real Mustang/
Summit Point laps end to end, in the CLI and a real browser.
**Consistency scoring fixed: per-unit CV normalization, `dm-v2` (2026-07-21,
SPEC.md A21)**: investigated before fixing (per this project's practice) and
found the "Known v1 limitation" note's own diagnosis was wrong — it blamed
cross-cohort pooling, but each CV was already computed per-cohort; the real
mechanism was cross-*metric-type* (a "% lap" metric's naturally tiny CV vs.
a "count" metric's naturally huge one dominating a flat average regardless
of actual driver consistency). Fixed with a documented per-unit reference
scale (9 units, values are observed medians from real telemetry) and
two-level pooling (mean within unit, then across units — a flat mean and a
median were both tried against real data and the existing trend tests, and
rejected; see `model/scoring.py`). Real effect on the committed fixtures:
`consistency` 5.1 → 34.3; `commitment` (inflated the *other* way by the same
bug) 96.5 → 56.1. `SCORING_MODEL_VERSION` bumps `dm-v1` → `dm-v2`. Full
record: PROJECT-BRIEF.md's decision log.
**`rebuild-map` built (2026-07-21, SPEC.md A22)**: `driverdna rebuild-map
--car --track` re-derives a frozen cohort's corner centroids + canonical
windows from the full accumulated lap set (not just the laps that first
froze the map) and re-measures phase times — **in place**, so corner IDs
and evidence IDs never change. A lap whose raw blob was evicted past
retention can't be honestly re-measured, so its stale phase times are
cleared and reported, never left silently outdated. Deterministic and
idempotent; new geometry still enters only through the existing audited
admission path. Closes the A17-deferred corner-map refreeze gap.
**UI design language v2 ("pit wall") specced (2026-07-22)**: owner-directed
redesign — palette kept byte-for-byte, more simplicity, a real button
system, and a bounded personality kit, with iRacing's UI/promo language as
the register reference. `docs/UI-SPEC.md` gains a "Design language v2"
section, view 8 (Garage — cohort index over the existing `/api/cohorts`),
and milestones **U5** (restyle) / **U6** (cockpit actions: `POST /api/sync`
+ `POST /api/cohorts/{slug}/rebuild-map`, CLI-effect parity, token
env-only); the base "no decorative display face" clause is amended (one
condensed Plex face, structure labels only, never data). Color grammar,
trust gates, and philosophy untouched; explicit boundaries recorded (no
license-letter grades on scores, no alarm red, no decorative motion). Spec
+ labeled-placeholder mockup only (`docs/ui-redesign-mockup.html`) — build
awaits owner go, per the M7 spec-first precedent. Full record:
PROJECT-BRIEF.md decision log.
**U5 "pit wall" restyle built (2026-07-22, design language v2)**: the
owner-directed redesign is live in the SPA. `ui/tokens.json` gains
`font.display` (self-hosted IBM Plex Sans Condensed, 600/700 latin, offline
intact) and a `shape` group; a condensed display face now carries structure
labels only (wordmark, tabs, titles, buttons, tile captions), never data. A
single top-right chamfer is the one geometric tell; a real three-tier button
system replaced text-link actions; a constant six-tab shell (Driver · Model ·
Garage · Chat · Import · Config) with a per-view context strip replaced the
shape-shifting nav; a new **Garage** view (view 8) is the cohort index and
driver home is now purely the rollup + pit-board stat tiles. Reference-lap
visibility folded in (R1): reference tile + panel, isolation guarantee line,
"ref n=K" on gap findings, a "References" line (driver + lap time) over one
read-field addition (`driver` on `/api/laps`), and the N=0 direction state.
Copy trimmed throughout after the owner flagged the first mockup "very wordy"
(binding "Copy density" rule now in UI-SPEC.md). Colours, colour grammar,
and all five trust gates unchanged; `_TOKENS` byte-match green; built SPA
reships in-package; suite green. Milestone **U6** (cockpit actions: sync +
rebuild-map buttons) followed once U5's gates passed — see below.
**Reference-lap survey + plan written (2026-07-22, `docs/REFERENCE-LAPS.md`)**:
owner-requested. The machinery exists and is tested (role column,
query-surface isolation, shared corner maps, `reference_envelope` →
`vs_reference_findings` → payload/UI, manual import only per M0b) but has
never fired because the DB holds zero reference laps — `sync` structurally
can't fetch them. The doc gives the owner-runnable recipe (Garage61 web
export → `import --role reference`), six gaps, and a design-stage R-track
(R0 feed-and-pin → R1 visibility → R2 identity/depth → R3 curation) with
open decisions flagged, not picked. Nothing built; awaiting owner reaction.
Same-day follow-up (owner asked to make references easier to see/understand
and put it in the UI plan): R1 fleshed into a see-&-understand layer and
folded into U5 — N=0 vs-reference direction state + button, isolation
guarantee line, reference stat tile, "ref n=K" on gap findings, and a
"References" line (driver + lap time) over one read-field addition (`driver`
on `/api/laps`). Mockup updated to show it; still spec-only.
M0b (API probe) is **done** — a later
session's network policy did reach `garage61.net` successfully (an earlier
snapshot's belief that it was blocked no longer holds); `docs/garage61-api.md`
documents observed behavior. **`sync` (self-lap ingest) is built and
verified live (2026-07-20)**: a real `driverdna sync` run against the
owner's account pulled 25 laps across 25 car/track cohorts, `lap_date` and
`run_index` populated from real API metadata on every row, re-running
sync twice more was fully idempotent (0 new laps, 25 total unchanged), and
`driverdna report` ran clean on the API-sourced laps. Reference laps stay
on the manual `import` path per M0b's finding (other-drivers' laps return
`403 forbidden_lap`) — confirmed again live: every synced lap is `role='self'`.
**U6 "cockpit actions" built (2026-07-26)**: the write-side half of design
language v2. `POST /api/sync` (wraps `sync_driver`, constructing
`Garage61Client()` straight from `GARAGE61_TOKEN` — never from the request)
and `POST /api/cohorts/{slug}/rebuild-map` (wraps the A22 in-place refreeze)
are both pure wrappers, decision-3 style; CLI-effect parity against
`driverdna sync` / `driverdna rebuild-map` is a mocked-client / two-copies-
of-one-fixture-cohort test respectively, plus a dedicated test proving an
unset `GARAGE61_TOKEN` returns HTTP 400 and writes nothing. UI: a
`btn-primary` **Sync** on driver home (missing-token state renders as
guidance text, never an input field) and a `btn small` **Rebuild map** in
the cohort context strip behind its own client-side confirm/cancel gate,
rendering the rebuild report including the cleared-stale-phase notice. All
five trust gates green; no route-list changes needed. Full record:
PROJECT-BRIEF.md's decision log.

## Verified counts (2026-07-29)

Reproduced on this date after adding the Verification discipline rules.

| Count | Value | How to reproduce |
|---|---|---|
| Tests | **710 passed, 32 skipped** (all skips due to missing Chromium/built SPA or local Postgres not configured). | `python3 -m pytest --basetemp=C:\Users\benja\driverdna\tmp\pytest` |
| `AGENTS.md` | **8,341 chars** (budget 11,000; Antigravity's silent cliff 12,000) | `python3 -c "print(len(open('AGENTS.md', encoding='utf-8').read()))"` |

## Verified counts (2026-07-21; tests re-verified 2026-07-26)

Regenerated from the repo this date, not asserted from memory:

| Count | Value | How to reproduce |
|---|---|---|
| Tests passing | **530** (37 test files) — up from 518 before U6; adds `test_cockpit_api.py` (10) + `test_cockpit_ui.py` (2). The one failure (`test_offline.py`) is pre-existing. | `python3 -m pytest` |
| Commits | **75** | `git rev-list --count HEAD` |
| Real laps imported | **12** primary (GR86/Spa 11, Mustang/Laguna 1) + **11** second Spa cohort (`tests/fixtures/spa-blind-2026-07/`) | `driverdna import tests/fixtures` |
| Spa cohort | 11 laps · **3 sessions** | `/api/cohorts/gr86-spa-francorchamps/payload` |
| Spa findings | **15 shown · 91 suppressed** (all suppressions state a reason; 2 fewer shown than the prior snapshot — the incident-outlier fix, A18, correctly demoted 2 partly outlier-inflated findings) | same payload |
| Laguna cohort | 1 lap · 0 sessions · 0 shown · 71 suppressed | insufficient data by design |
| Determinism | byte-identical reports across two independent imports | `driverdna report` ×2, `diff` |

---

## Where we are

### Engine — complete (M0a–M7)

| Milestone | What it does | State |
|---|---|---|
| M0a | Contract lock: schema + absence tests on real fixtures | done |
| M1 | Parse → segment → freeze corner identity → classify | done |
| M2 | 18 metrics + 5 principle detectors + SQLite persistence | done |
| M3 | Attribution over canonical windows, robust baselines, ranker, gates | done |
| M4 | Reports (MD/JSON/HTML) + one-shot coach with local validation | done |
| M5 | Grounded chat: tools, annotations, staged config, mechanical grounding | done |
| M6 | Driver Model: deterministic versioned scoring (Score+Confidence+Evidence+trend) | **done** — taxonomy, belief store, `dm-v2` scoring (per-unit-normalized consistency, 2026-07-21), `driverdna model` artifact, wired into report/coach/chat payload; **trend built (2026-07-20)**: direction of a fundamental's score across dated earlier/recent buckets, live-verified on the 25-lap synced history (braking/rotation improving) |
| M7 | Coaching Intelligence: grounded coaching ontology (`docs/COACHING.md`) | **done** — ontology, eligibility/ranking/gap-band engine, `driverdna coaching` artifact, wired into report/coach/chat payload, grounding validator extended |
| M0b | Garage61 API probe + `sync` | **done, live-verified** — `docs/garage61-api.md`; 25 laps synced from the real account, idempotent, reference isolation held |

### UI — U0–U4, the full milestone track built (2026-07-21)

| Milestone | What it does | State |
|---|---|---|
| U0 | FastAPI layer: pass-through reads, audited writes, `driverdna ui` | done |
| U1 | React SPA read views on the timing-screen design language | done |
| U1 gate 1 | Render-parity crawler (Chromium): no invented on-screen number | done |
| U2 | Writes — annotations + config panel through audited paths | done |
| U3 | Chat view (SSE, validated-only display, staged/confirm) | **done** — browser-verified against a mocked provider (screenshots); real live chat still needs `ANTHROPIC_API_KEY` |
| U4 | Packaging, token unification, offline verification | **done** — static reports migrated onto `ui/tokens.json`'s dark theme; IBM Plex self-hosted in the SPA; trust gate 5 (offline) now a real Playwright test, not just a static grep |

### Data on record

- **12 real laps:** Mustang @ Laguna (1), GR86 @ Spa (11, across 3 sessions).
- **17 live findings** on the Spa cohort once the ≥10-sample / ≥2-session gates
  cleared; 89 still suppressed with stated reasons.
- Determinism verified mechanically (two imports → byte-identical reports).
- One re-download (`C6M4_2` = `VHC6M4`) was caught by content-dedup and rejected.

---

## Where we're going (roadmap)

Immediate, no blockers, recommended order:

0. **M6 — the Driver Model (the newly-declared heart of the product).** A
   deterministic, versioned scoring layer over everything M1–M5 persist:
   per-fundamental Score + Confidence + Evidence Count + trend, additive, no
   rewrite. No API key needed. Governed by `docs/ARCHITECTURE_VISION.md`; scoped
   in `docs/SPEC.md`. Recommended next — it's what makes DriverDNA *DriverDNA*.
   Honest caveat: its longitudinal outputs (trend, archetype, universal pace
   gain) stay gated until there are lap dates and multi-track/car breadth, which
   we don't have yet — the per-fundamental scores work now; the "knows the
   driver not the track" headline earns out with data.
1. **M7 — Coaching Intelligence (design ADOPTED 2026-07-20, `docs/COACHING.md`;
   not yet built).** A grounded coaching ontology layered over the Driver
   Model: `technique → driving principle → coaching principle`, with
   deterministic eligibility + ranking + gap-band tone so the AI *selects and
   phrases* coaching within a fixed vocabulary instead of improvising it.
   Governing rule adopted this pass: **a confidence value never launders an
   unmeasured inference** — measured ground gets committed, hedge-free
   coaching; no-signal fundamentals (vision/eye-line) get a driver-runnable
   **self-check** labeled as a hypothesis, never a score or confidence at any
   level. Sequenced after M6; a detector-level subset (7 of 9 seed principles)
   is groundable on today's engine.
2. **U3 — the chat view: done (2026-07-20).** `ChatSession.ask_stream` (a
   generator; `ask()` is now a thin wrapper over it, one implementation, no
   duplication) feeds three new endpoints (`POST /api/chat/sessions`,
   `.../messages` via SSE, `.../confirm/{n}`) and a new `ui/src/views/chat.jsx`.
   SSE progress states (thinking → consulting_tool* → validating), the
   tool-call audit line, and the staged/confirm card all verified in a real
   Chromium browser against a scripted mock provider (screenshots in the
   session record) — text never streams token-by-token; a rejected reply
   surfaces as a distinct error card. Found and fixed a real bug along the
   way: a chat session's sqlite3 connection outlives the request that opens
   it, and FastAPI dispatches sync endpoints to a thread pool, so later
   messages could land on a different thread than the one that created the
   connection (`sqlite3.ProgrammingError`) — fixed with
   `Database.open(..., check_same_thread=False)` for that one long-lived
   connection only. Only *runs live* with an Anthropic key.
3. **U4 — packaging & polish: done (2026-07-21).** Static HTML reports
   migrated onto `ui/tokens.json`'s dark theme; IBM Plex self-hosted in the
   SPA; trust gate 5 (offline) and HTML determinism both now real tests.
   See the UI table above and PROJECT-BRIEF.md's decision log for the full
   record. The UI-SPEC.md milestone track (U0–U4) is complete.

Done since the last snapshot: **U2 — findings are now actionable.** Annotate a
finding (acknowledged / intentional) so it drops out of priority framing while
the measurement stays, reversible; a config panel retunes thresholds through
`ConfigStore` (propose → confirm → apply, with `config_history` as an audit
view and revert). All writes wrap the audited paths; the parity crawler now
covers the config view too.

Floating / key-gated:

- **M0b + `sync`: done, live-verified (2026-07-20).** A later session's
  network policy reached `garage61.net` successfully (the earlier belief
  that it was blocked no longer holds). `docs/garage61-api.md` documents
  observed behavior; `Garage61Client` + `sync_driver` + `driverdna sync`
  are built from it and verified against the real account (25 laps, 25
  cohorts, idempotent reruns, reference isolation held). See
  `PROJECT-BRIEF.md`'s decision log for the full record.
- **Blind acceptance test** when enough independent Spa data exists that the
  expected answer isn't one I've been told (see Risks).

---

## Decisions made (with rationale)

**Product shape**
- Coach the driver, not the lap; deterministic engine is the only source of
  numbers; three sources (`vs-principle` / `vs-self` / `vs-reference`) never
  blend; "insufficient data" is a first-class answer. (The nine philosophy
  points, owner-confirmed; binding.)
- Python 3.11+ (numpy/scipy/pydantic/typer/anthropic/SQLite). Owner had no
  preference; chosen for the numeric ecosystem.
- Local, single-user, offline. No server beyond `driverdna ui` on localhost.

**Ten review findings folded into the spec before building** (the critique of
the original plan): F1 canonical phase windows (the correctness core), F2
robust baselines, F3 build→freeze→match corner identity, F4 class hysteresis,
F5 split M0a/M0b, F6 chat as its own milestone, F7 mechanical grounding
enforcement, F8 an inspectable artifact per milestone, F9 the vs-self ranker
defined explicitly, F10 blob lap storage.

**Contract amendments discovered from real data** (SPEC amendment log):
- A11 — filenames carry a lap ID only; identities/lap-times moved to a manifest.
- A12 — a complete lap wraps 0 *or* 1 times (line-to-line sampling never wraps);
  added a coverage guard for partial laps; steering is radians but can exceed 2π
  at slow hairpins (road-car wheel past a full turn).
- A13 — `PositionType` is a small enum, not a constant; **content-dedup** added
  so a re-download can't double-count.

**Constitution-level forks Claude Code raised, and how they resolved** (each is
also recorded in the durable docs, per the Decision-discipline rule):
- **Scores adopted (2026-07-19).** Fork: no-scores (keep philosophy #4 as-is) vs.
  scores. Options offered: deterministic+AI-explains / deterministic+AI-proposes-
  weights / AI-generates-each-run. **Owner pick: deterministic, versioned,
  reproducible; every score ships Score + Confidence + Evidence Count; AI
  explains and prioritizes only.** Reason: scores are the product's headline
  value and AI's judgement should articulate, not compute. **This refines
  philosophy #4** ("no overall score" → "no *opaque* blended score") — flagged
  in-doc as SPEC amendment A14 and `docs/ARCHITECTURE_VISION.md`.
- **Coaching Intelligence adopted as M7 (2026-07-19, design stage).** A grounded
  coaching ontology where the AI selects/phrases within a fixed, evidence-
  triggered vocabulary. Checked against the philosophy: **consistent** with #2
  (AI never computes) and the out-of-scope list; no contradiction. Spec:
  `docs/COACHING.md`.
- **COACHING.md flipped to adopted; two honesty rules added (2026-07-20).**
  *A confidence value never launders an unmeasured inference* — no-signal
  fundamentals (vision/eye-line) never get a score or confidence, at any
  level ("Vision, 30% confident" explicitly forbidden); measured ground gets
  full conviction, no hedging. No-signal fundamentals get a driver-runnable
  **self-check** (a hypothesis + in-car exercise) in place of a score.
  Checked against the philosophy in the same edit: consistent with #2 (a
  self-check is interpretation, not a computed number) and #3 (this is what
  "insufficient data" *does*, not a dead end); reconciled against
  `ARCHITECTURE_VISION.md`'s "— · 0% · no telemetry signal" score convention
  (two layers, same rule — M6's "0%" is a fixed flag, never a graduated
  confidence). Also formalized **gap-band eligibility** (coarse, versioned
  loss/trigger-rate bands controlling loud/quiet/silent tone — flagged as a
  formalization of prior intent) and fixed a seed-set defect the new rules
  exist to catch (the old `be_patient` conflated a weak-proxy fundamental with
  a truly unmeasurable one; split into `trust_the_proxy` / `look_further`).
- **Trend + evidence_count made required M6 outputs (2026-07-20).** Every
  belief carries `trend` and `evidence_count` always, holding "unavailable"
  rather than being dropped when data is thin — the longitudinal guarantee,
  made non-optional. `ARCHITECTURE_VISION.md` Scoring Contract condition 5;
  mirrored in SPEC.md's M6 section.
- **Trend computation built (2026-07-20).** With `sync` now populating
  `lap_date`, `trend` is the direction of a fundamental's score across an
  earlier vs recent bucket of the driver's dated laps (same scoring function
  per bucket, deterministic, banded by `trend_delta_points`). Did not itself
  change `dm-v1`'s score/confidence for any evidence set. (The version has
  since moved to `dm-v2` for an unrelated reason — the consistency
  per-unit-normalization fix, 2026-07-21, SPEC.md A21, below.) Two flagged
  v1 limitations (era-relative opportunity baseline; cross-cohort bucket
  composition when dated laps are thin per cohort) remain, unaffected by the
  version bump. Full record in the decision log above.

**UI**
- The normalized JSON payload is the rendering contract; the UI never computes a
  measurement (mechanically enforced by the render-parity crawler).
- Owner amendment: U0-U2 built ahead of the blind acceptance test for
  momentum; **extended to U3 (2026-07-20, PROJECT-BRIEF.md decision log)** —
  U3 is UI plumbing over the already-spec'd, mock-tested `ChatSession` (M5)
  and the render-parity crawler's own numeric-grounding guarantee, not a new
  measurement claim, so it doesn't need the blind test either. U4 (pure
  packaging) follows the same reasoning. The blind test remains the trust
  gate for the engine's *findings*, still blocked on the owner's independent
  multi-session Spa data.

**Working practice**
- Secrets are env-only, never committed. Every threshold lives in config with a
  documented default. Every milestone ships an inspectable artifact. Commit +
  push after each coherent unit.

---

## Decisions we still need to make

| # | Decision | Why it matters | Current default |
|---|---|---|---|
| 1 | Adopt `sync` as the primary ingest path going forward? | `sync` is built and live-verified (2026-07-20): 25 laps pulled, idempotent on rerun, real session/run/date metadata, reference isolation held. Manual `import` remains the fallback for reference laps regardless | Live-verified; not yet the default in any automation (still explicit `driverdna sync`) |
| 2 | Provide `ANTHROPIC_API_KEY`? | Turns coach + chat from mock-tested to actually usable | Deferred; all tests mock it |
| 3 | ~~When to run the blind test?~~ | Resolved 2026-07-21 (A18): ran on 11 independent laps, 6 sessions | Done — see below and PROJECT-BRIEF.md |
| 4 | Session labels for manual imports | Filenames carry no session (old or new Garage61 shape — the newer shape's filename auto-detect resolves car/track, not session); grouping affects repeatability | Manifest per-entry `session` field, or the upload UI's explicit `session` field (2026-07-21) — the CLI's flag-driven `import` (no manifest) still has no `--session` flag |
| 5 | Keep committing the built SPA (`ui/static`)? | Convenient (no node at runtime) vs. a build artifact in git | Committed for now |
| 6 | ~~Corner-map refreeze policy as data grows~~ | Resolved 2026-07-21 (SPEC.md A22): `driverdna rebuild-map` re-derives centroids + windows from the full lap set **in place** (IDs never change, evidence IDs stay valid), re-measures phase times, clears+reports any lap whose blob was evicted. Not a new map version — see A22 for why in-place over versioned | Done — freeze-and-match at import; explicit `rebuild-map` to refreeze |
| 7 | Cross-car reporting | Computed and stored but out of scope for v1 reports | Out of scope v1 |

---

## Risks & things worth knowing

- **The blind test ran (2026-07-21, A18) and it worked exactly as a trust
  gate should: it caught something, rather than rubber-stamping a guess.**
  The spec's original expected answer (Sector-1 high-speed entry, ±1.2 s
  spread) turned out to have never been engine-corroborated on any dataset
  — it was a written belief, not a verified one — and was retracted. The
  process of checking it also surfaced a real ranking bug (one spin, one
  15 s dead-stop lap could manufacture a phantom "opportunity" finding
  because the opportunity calc, unlike `baseline()`, didn't screen
  outliers); that's fixed now, with a regression test. What survives:
  the engine's machinery (gates, decomposability, suppression-with-reason)
  held up under real independent data with no crash, and it now has a
  restated, incident-robust ground truth (loss concentrated at the two slow
  corners, fast corners essentially clean) to compare future runs against.
  Full forensics in PROJECT-BRIEF.md's decision log.
- **The current findings are shaped by "not fresh" laps.** Two slower practice
  laps sit in the self-history and legitimately pull the vs-self opportunities
  (slower-lap-vs-faster-lap is exactly what vs-self measures). More clean laps
  will re-centre the baselines.
- **Corner-map events are surfaced, not silent.** Adding laps admitted C15/C16
  to the map and reclassified C08 fast→medium (slower laps lowered its median
  apex speed past the hysteresis margin). Reviewable in `driverdna corners`.
- **Live provider behavior is unverified.** Coach/chat are correct against the
  mocked provider; the first live runs (once a key exists) will shake out
  prompt/formatting realities the mocks can't.

---

## How to run it

```
python3 -m pip install -e ".[dev]"      # engine + UI + test deps
driverdna demo                           # one command: seed sample laps + open the cockpit
python3 -m pytest                        # 534 tests (2026-07-21)
driverdna import tests/fixtures          # build the local DB from the fixtures
driverdna report                         # Markdown + JSON + self-contained HTML
driverdna corners | metrics | attribution | incidents   # per-milestone inspectable artifacts
driverdna rebuild-map --car GR86 --track Spa-Francorchamps   # refreeze a cohort's map from its full lap set
driverdna ui                             # local cockpit at 127.0.0.1 over your own data
```

Coach/chat additionally need `ANTHROPIC_API_KEY`; `sync` needs `GARAGE61_TOKEN`
(both env-only).
