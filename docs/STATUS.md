# DriverDNA — Status & Decision Log

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

## Verified counts (2026-07-27)

Reproduced on this date after fixing the red test and adding the sync
404/403 guard + UI bug fixes.

| Count | Value | How to reproduce |
|---|---|---|
| Tests | **passed, 1 failed** (the pre-existing `test_offline.py` Playwright timeout, unchanged). The 13 skips are all browser tests — Chromium absent; this is also why the known `test_offline` failure does not appear in some runs. | `python3 -m pytest` |
| New tests this session | **3** in `tests/test_garage61_sync.py` (404/403 guard + auth-error propagation, A30) | `python3 -m pytest tests/test_garage61_sync.py -k "404 or 403 or auth_error"` |
| `AGENTS.md` | **9,992 chars** (budget 11,000; Antigravity's silent cliff 12,000) | `python3 -c "print(len(open('AGENTS.md').read()))"` |

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
