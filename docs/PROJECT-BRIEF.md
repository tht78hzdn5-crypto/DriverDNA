# DriverDNA — Project Brief

Updated 2026-07-21 · branch `main`. Orientation
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
6. The UI-SPEC.md milestone track (U0–U4) is now fully built (U4 done
   2026-07-21). A deliberate, versioned map/window `rebuild` command once
   tens of laps exist remains open (freezing early trades optimality for
   comparability, by design) — this is the veteran cold-start item A17
   already flagged.
7. More laps, of anything — gates clear at ≥10 phase samples + ≥2 sessions.

## Scaling

- **As a personal instrument (its stated purpose): nothing needed.** SQLite +
  numpy handle years of one driver's data with orders of magnitude to spare
  (a lap ≈ 6k rows; raw blobs are windowed anyway; compact rows are tiny).
  Import cost ~1–2 s/lap, report generation sub-second.
- **The Postgres port described here has since happened, for the
  single-user case only** (2026-07-26, SPEC.md A23). What was done: the
  compact relational schema ports as-is behind a dialect shim, and the
  deterministic payload is unchanged. What was **not** done, and stays out of
  scope: object storage for blobs (they went to local disk instead, which is
  cheaper and keeps the transactional guarantee), queued ingest, the payload
  as a public API, and per-user tenant keys. Multi-user remains excluded.
  Measured on the fixture corpus: 12 laps are ~10 MB of raw blobs against
  ~564 KB of compact rows, so keeping blobs local moves ~95% of the bytes off
  the wire and puts a 500 MB free tier out of reach until several thousand
  laps. The philosophy constraints (no blending, gates, evidence IDs) are
  architecture-independent and survived the port unchanged.
- **The real scaling axis is trust**: keep the determinism byte-diff, the
  trust-gate tests, and the amendment discipline in SPEC.md as the suite any
  refactor must pass.

## The UI (U0–U4 built — the full milestone track)

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

**U4: packaging & polish, done (2026-07-21).** Closed the three concrete
gaps a scoping pass found (the UI command and package-data shipping were
already true since U0): (1) static HTML reports were still the original
light theme — `report/builder.py` now declares `_TOKENS`, a mirror of
`ui/tokens.json` kept honest by a test that reads the real file, and
renders one `:root { --name: value; }` block that both the `<style>` and
the inline SVG charts reference via `var(--name)` (a standard SVG
presentation-attribute capability) — no JS runtime needed in a static
file. Chart colors now match the SPA's own `app.css` `.lossrow`
convention exactly, including the single-largest-value amber highlight.
(2) IBM Plex was named "bundled" in the design language but no font files
existed anywhere — `@fontsource/ibm-plex-{sans,mono}` now self-host them
in the SPA, latin subset only (this UI is 100% English/numeric; the
unsubsetted import would have shipped ~46 unused cyrillic/greek/etc.
files) and only the four weights `app.css` actually sets — 8 files,
176KB. Verified via `document.fonts` in a real browser, not just build
output. Reports stay on the system-font fallback (SPA-only, per the
earlier owner call) — an unavailable named font just falls through the
stack. (3) Trust gate 5 ("offline") had only a static grep
(`test_ui_static.py`); added a real dynamic test that actively blocks
every non-localhost request via Playwright route interception across
every route (including chat) and asserts each one still renders real
content. Also closed a gap the milestone's own text named: HTML output
had no determinism test, only payload/JSON — added one (byte-identical
across independent renders). A DriverModel UI view (open when U4 shipped)
was built 2026-07-21 — see the decision-log entry above.

The binding rule throughout: the UI renders what the engine computed and never
computes a measurement (mechanically enforced). What does NOT belong in a UI:
re-ranking that ignores gates, editing measurements, or any number computed
client-side. Scores are welcome — but they come from the engine's deterministic
model (M6), carry confidence + evidence count, and are rendered, never computed.

## Decision log (append-only)

Durable record of forks and their resolutions (per the Decision-discipline rule
in `AGENTS.md`). Newest first.

- **2026-08-03 — The reference-lap feature's first real run broke its own
  guarantee (A34).** The owner supplied a reference lap and six matching Mustang
  GT4 laps at Spa, so the vs-reference path finally ran on real data. It works
  — 30 gap findings, 6.54 s of a real 10.73 s lap-time gap. It also showed that
  "reference laps never enter self history" was enforced only in the
  *measurement* queries, not in the **corner map** those measurements are taken
  in. A reference lap could found a cohort's map outright, count toward corner
  admission, and feed `rebuild-map`'s refreeze. Measured: 11 of 14 corners
  moved, 154 of the owner's 191 phase times changed by up to 1.57 s, and Driver
  Model scores followed. Fixed self-only at all three, with the reference
  observations still linked and measured — **isolation is not exclusion**.
  Two things worth keeping: the existing M3 trust-gate test passed honestly the
  whole time because its synthetic reference lap only ever matches corners that
  already exist, so it never exercised admission or rebuild — *a guarantee
  pinned one layer above where it can break is not pinned*; and no committed
  number moved, because both fixture manifests hold zero reference laps, which
  is exactly why the fixtures never caught it. **Standing lesson: a capability
  that has never run on real data has never been tested, however green its
  tests are.**
- **2026-07-28 - Multi-tenant, SaaS Productization, Google OAuth, and SMTP Password Resets.** The strict "one driver's instrument" rule (Philosophy #8, A31) was overridden by explicit owner directive to productize the app as a SaaS platform (A32).
  A new `users` table was added, backing both a Google OAuth TLS callback route and a standalone SMTP-based password reset flow (via SendGrid). Every data structure (`laps`, `incidents`, `model_cache`, etc.) was partitioned with `owner_user_pk`, and the row-level security was tested extensively. Trust gate 5b was amended in A32 to permit outbound calls to `smtp.sendgrid.net` and Google OAuth endpoints. All deterministic grounding tests remain strictly isolated per tenant.

- **2026-07-27 — single-driver auth built, and it is a passphrase rather than
  an identity provider (SPEC.md A31, DEPLOY-SPEC track H1).** The owner asked
  for "a free auth solution — could be Auth0, could be something else, that
  works with our tech stack."

  *The first finding was that the question was overdue.* `docs/DEPLOY-SPEC.md`
  had specified this exact mechanism on 2026-07-26 and it was never built,
  while the Cloud Run deployment shipped anyway. So the live service had been
  sitting at a public hostname with **no application-level authentication at
  all** — every `/api` route open, including `sync`, `config/apply`,
  `laps/upload` and `chat` — held up only by Cloud Run's
  `--no-allow-unauthenticated` IAM flag. DEPLOY-SPEC's own build order says
  "H1 must precede any exposure, by definition"; the deploy went first.

  *The fork the owner named — Auth0 or something else — turned out to be
  decided by the test suite rather than by preference.* Two existing tests
  mechanically exclude a browser-side identity SDK:
  `tests/test_ui_static.py` asserts the built JS bundle contains no
  `https://` (and it runs in CI with no browser, so this is not a soft
  constraint), and `tests/test_offline.py` aborts every non-same-origin
  browser request and asserts none was attempted. Auth0, Clerk, Firebase and
  Supabase Auth all embed a tenant URL and all fetch from a third-party
  origin. Weakening either test to accommodate one is exactly what AGENTS.md
  forbids.

  A **server-side** OIDC flow (browser only ever does a top-level redirect,
  the server exchanges the code and sets its own cookie) would have passed
  both gates — that was checked, not assumed, and it is the honest version of
  "Auth0 is possible here." It was rejected on cost/benefit and the owner
  chose the alternative: for one driver it buys MFA in exchange for a vendor,
  a dependency, a client secret, a redirect URI pinned to the Cloud Run
  hostname, a new external dependency at the process level (needing a UI-SPEC
  gate-5b amendment), and a user-management model DEPLOY-SPEC explicitly
  forbids.

  **Chosen: `DRIVERDNA_ACCESS_TOKEN` → signed, expiring, HttpOnly cookie.**
  Stdlib only (`hmac`/`hashlib`/`base64`), so no new dependency and no
  third-party origin at either the browser or the process level — which is
  why **no trust gate wording had to be weakened or amended**. Three
  properties were deliberate: single-tenant by construction (no user table,
  so the "no multi-tenancy" half of philosophy #8 is reaffirmed rather than
  eroded); stateless (the cookie carries an expiry and its signature, so it
  verifies on any instance after any restart — Cloud Run scales to N); and
  revocable by rotation (the signing key derives from the passphrase).

  Two decisions worth recording because they are the kind that get
  second-guessed later. **Auth is off when no passphrase is configured** —
  that is what keeps the local loopback instrument identical to before, and
  it is the mechanical proof the change is additive, since every pre-existing
  test passed unmodified. And **the guard is an app-level dependency rather
  than a per-route one**, so an endpoint added in future is guarded by
  default rather than by someone remembering; DEPLOY-SPEC's own
  done-criterion is a test that enumerates `app.routes`, which exists
  precisely because the opposite is so easy to get wrong.

  *One hole the tests missed, worth its own paragraph.* With everything green
  including a route-enumeration test taken verbatim from DEPLOY-SPEC's
  done-criteria, curling the live server showed `/openapi.json` answering
  **200 with a passphrase set** — the whole endpoint surface and every request
  model, readable by anyone. FastAPI registers its schema with `add_route`
  rather than `add_api_route`, so app-level dependencies never see it, and
  the enumeration test filtered on paths starting with `/api/`, so it never
  looked. The fix is small; the lesson is not, and it is the reason the test
  now walks every route the app declares: **a guard proven only against the
  paths you thought to list is not proven, and a green suite is not a
  substitute for asking the running thing.**

  *Found along the way, recorded rather than quietly fixed:* the `--host`
  flag had shipped for the container without its fail-closed interlock, so
  `Dockerfile`'s `--host 0.0.0.0` had nothing stopping it publishing an
  unguarded instrument; `main` was red on a pre-existing `AGENTS.md`
  size-budget failure; and the platform drift from this document's Oracle
  VM + SQLite + Tailscale decision to Cloud Run + Supabase was never
  recorded in an amendment, which left DEPLOY-SPEC's H2/H3 describing a
  deployment that does not exist. **Consequence to sequence carefully:** the
  interlock means the Cloud Run service now needs `DRIVERDNA_ACCESS_TOKEN`
  in its environment or it will refuse to start, and `deploy.yml` deploys on
  every push to `main`. Set the secret before merging.

- **2026-07-27 — the build rules became portable and CI became a real gate,
  because more than one agent now works here (SPEC.md A29).** The owner uses
  Gemini CLI and Antigravity during Claude Code usage-limit windows, with
  unrestricted scope, and asked how to keep the three from working against
  each other.

  *The real problem was not wiring, it was enforcement.* Pointing another tool
  at the docs is a settings file. The risk is a capable model violating an
  invariant — "the engine is the only source of numbers", reference-lap
  isolation, insufficient-data-over-guessing — while writing code that looks
  entirely reasonable. This project's own answer to that is philosophy #9,
  "designed to be distrusted": enforce mechanically, don't ask nicely. So the
  work is two-thirds tests and CI, one-third documentation.

  *Fork: where do the rules live?* Rejected: copy them into `GEMINI.md` and an
  Antigravity rule (three copies, guaranteed drift); rejected: leave
  `CLAUDE.md` as the source (25,908 chars, and Antigravity silently refuses a
  rules file over 12,000 — the rules would simply never arrive). Chosen: one
  portable `AGENTS.md`, imported by `CLAUDE.md` via `@AGENTS.md`, loaded by
  Gemini CLI through `.gemini/settings.json`, and mirrored — only its
  non-negotiables — into `.agents/rules/driverdna.md` because Antigravity's
  docs do not promise a root `AGENTS.md` is read at all.

  *That one mirror is pinned, not trusted*, by `tests/test_agent_contract.py`,
  reusing the `ui/tokens.json` ↔ `_TOKENS` parity pattern. Both the drift guard
  and the settings guard were made to fail deliberately before the file was
  accepted. A third guard came from asking what drift *cannot* catch: an agent
  tidying a rule out of **both** copies keeps the mirror consistent, so the
  block's load-bearing clauses are anchor-asserted separately. That negative
  control was run and observed.

  *There was no test CI at all.* Every invariant in this project is enforced by
  pytest and nothing else — no linter, no formatter, no type checker — and
  nothing ran it on push. `tests.yml` now runs the suite on every push and PR
  across Python 3.11/3.12, with a Postgres service container so the A23
  dual-backend guards (`COLLATE "C"`, `DOUBLE PRECISION`, RLS) actually execute
  instead of skipping. Given unrestricted scope over `sql.py` and `db.py`, that
  container is the highest-value part of this change: those defects are
  invisible on SQLite by construction.

  *Flagged, not silently accepted — branch protection cannot tell the agents
  apart.* The agreed rule is "Claude Code commits to `main`; the others branch
  and merge on green". GitHub cannot enforce that, because all three tools push
  as the owner's single identity: protecting `main` blocks Claude Code too, and
  an admin bypass hands the same bypass to everyone. So the branch rule is a
  convention backed by *detection* (push-triggered CI on every branch including
  `main`), not by prevention. Two ways to close it if the convention proves
  insufficient — protect `main` for everyone and accept a PR per Claude change,
  or a repo-local `.githooks/pre-push` keyed on the `Agent:` commit trailer,
  which is the only mechanism that keys on the agent rather than the identity.
  Neither was adopted now; the owner chose to keep Claude Code on `main`.

  *Also fixed:* `.github/workflows/gemini-assistant.yml` had never once worked.
  It pinned `run-gemini-cli@v1`; no `v1` tag exists (the action is pre-1.0).
  Its only run — the owner's issue #4, "gemini test" — failed in six seconds on
  `Unable to resolve action`, which is why nothing ever replied. Repinned to
  `v0.1.22` and gated on the repository owner, since the job holds
  `contents: write` and is driven by issue-comment text.

- **2026-07-27 — the `/laps` "personal-best endpoint" finding was wrong; it
  was a parameter default (SPEC.md A28).** The owner emailed Garage61 asking
  for un-deduplicated laps or a session endpoint. Alex from Garage61 replied
  that the feature already exists: **`group=none`**, plus `lapTypes`,
  `event`, `unclean` and `maxAge` filtering. He was right.

  *What we had concluded, and why it was wrong.* M0b censused two shared
  cohorts and found every driver — 30 in one, 66 in the other — had exactly
  one lap, against 979 laps driven on the account. It correctly ruled out a
  free-plan cap, then concluded the remaining explanation was the endpoint's
  fixed shape, and wrote that down as "not something a different plan or more
  API calls can pull around." The census was good work; the inference was the
  failure. Universality across accounts excludes an *account-specific* cause,
  but a parameter default is universal too — and invisible to a probe that
  never varies it. The honest conclusion available at the time was "one lap
  per driver per cohort **under the parameters we sent**." The endpoint's own
  summary, "Find laps and lap **records**," was a real clue, and it got read
  as confirmation of a ceiling rather than as a hint that a switch existed.

  *The more useful error.* M0b recorded the endpoint reference as
  unreachable — "a JS-rendered SPA not reachable by this session's fetch
  tooling" — and stopped. But the SPA fetches a plain OpenAPI JSON, and its
  URL is a literal string in the bundle: `https://garage61.net/api/openapi/
  v1.json`, no token needed. Downloading the Angular chunks and grepping them
  took a few minutes and produced the complete, authoritative parameter list,
  including several things M0b had listed as permanently unconfirmed
  (`limit` max 1000; `after`/`age` as the real date filters, versus the
  `start`/`end` that were guessed and silently ignored). **Standing lesson:
  when a documentation site won't render, read its client — the data source
  usually is reachable.**

  *This is A24/A25's lesson again, one level up.* Those amendments were about
  not presenting an unverified guess as observed. Here the guess concerned
  what the API *cannot* do, which is the more expensive kind: it silently
  shaped three later decisions (dated manual import, A27's premise, and M6's
  trend limitations) around a limit that never existed. Negative capability
  claims now need a documented source, not an inference from a probe.

  *Resolutions.* `sync` sends `group=none`, `drivers=me`, `unclean=true`, and
  driver-supplied `after`/`age`. Dated manual import is **not** retired — it
  remains the only path for pre-API history and laps Garage61 never held.
  Owner confirmed including unclean laps (A19: a spin is measured, not
  filtered) and confirmed the account is still on the free plan, so telemetry
  access for non-PB laps stays genuinely unknown: sync checks each lap's
  `canViewTelemetry` and reports what it finds instead of assuming. Because
  no `GARAGE61_TOKEN` was available in this session, nothing here is
  live-verified, and the client-side self-filter is kept unconditionally —
  `drivers=me` is an optimisation, never the guarantee.

- **2026-07-26 — two hazards created by A23's storage split, found by reading
  rather than by breakage (SPEC.md A26, A27).** Both were flagged while
  answering the owner's questions about where lap data should live, and fixed
  at their request.

  *`rebuild-map` was destroying recoverable measurements (A26).* Moving blobs
  to local disk gave `load_lap_arrays() is None` a second meaning. The old
  code read it one way — evicted — and deleted phase times accordingly, so
  running `rebuild-map` from a machine that merely hadn't imported those laps
  would wipe measurements that were intact elsewhere, and blame retention in
  the report. The fork was how to distinguish the two causes. Rejected:
  inferring it from the retention setting ("is this lap within the newest
  N?"), which breaks the moment retention is lowered and raised again, and
  which infers something the system can just record. Chosen: an eviction
  tombstone in the **blob store**, because eviction is a per-machine event and
  the database may be shared — a DB column would tell machine B that a blob
  it never held was "evicted". Then the harder question: on detecting an
  absent trace, clear, skip, or refuse? Clearing destroys recoverable data;
  skipping leaves the cohort with some phase times on new windows and some on
  retired ones, which is precisely the silent mixing A22 exists to prevent.
  So: refuse, before mutating anything, with an explicit override.

  *Cohort labels can drift between `sync` and `import` (A27).* `sync` folds
  the API's track `variant` into the label; a manual import takes the
  filename, which has none. Since the API returns only one lap per cohort, the
  documented workflow is to do both — so the split is structural, and it
  halves the evidence behind every longitudinal number without erroring. Built
  detection, not repair: which label is correct isn't derivable from the
  strings, and cohort keys are load-bearing for evidence IDs, so an automatic
  merge would risk the quiet corruption this project exists to refuse. The
  deliberate non-goal was equally important — two *different* variants are
  legitimately distinct cohorts per the spec's own rule, so flagging them
  would make the warning noise and get it ignored. Surfaced at the end of
  `import` specifically, because that is the moment the divergent label is
  created and the fix still costs one re-import.

- **2026-07-26 — Garage61 renamed its exports again; one splitter for both
  shapes, and `--car`/`--track` become independently optional (SPEC.md A24).**
  The owner reported import "not working in my local shell", suspecting the
  new database. It was not the database. A lap downloaded from the browser
  arrived as `Garage 61 - <driver> - <car> - <track> - <laptime> - <id>.csv`
  — ` - ` delimited, literal spaces in fields — while the parser accepted
  only the 2026-07-21 double-underscore shape. The 422 the owner saw is
  raised in a filename-only loop, before `Database.open` is reached; an
  existing test already pinned that ordering, which is what ruled A23 out
  quickly rather than by inspection of the new store.

  *The fork that mattered was not "add a second regex".* It was how to keep
  the two shapes from disagreeing. `car`/`track` are cohort keys, so the same
  lap spelled either way must yield byte-identical strings; per-shape lazy
  regexes absorb a surplus delimiter at different groups, so the shapes would
  diverge precisely on the ambiguous filenames. Chose one splitter
  parameterized by prefix/delimiter/underscore-decoding, with an explicit
  five-field count and no backtracking, and made parity a test rather than an
  argument.

  *A filename with the delimiter inside a field is refused, not guessed.*
  Two resolutions were considered and both rejected for putting a wrong value
  in the cohort key with no error: extras-to-track (a driver name containing
  ` - ` mislabels the cohort) and extras-to-driver (a config-suffixed track
  like `Watkins Glen - Boot` mislabels it the other way). A wrong cohort key
  is invisible; a refusal is loud and the driver types the field. This is
  non-negotiable #3 applied to metadata rather than to measurements.

  *The escape hatch was documented but did not exist.* `explicit = bool(car
  and track)` silently discarded a single supplied field and then reported
  "car/track not given" — the exact message the owner was staring at next to
  the car they had typed. Offered the choice between a clearer error and a
  working one-field override, the owner chose the override: a given field now
  applies to every file while a blank one keeps auto-detecting. That is what
  makes the next rename survivable without a code change.

  Verified end-to-end on the owner's real filename, CLI and browser, plus the
  cohort-parity check against two real fixtures. One incidental find, flagged
  in A24 and deliberately left for separate work at the owner's direction:
  hosted blob roots key on the DSN's last path segment, which is `postgres`
  for every Supabase project, so two projects would silently serve each
  other's telemetry.

- **2026-07-26 — the store moves to a hosted Supabase Postgres; SQLite stays a
  first-class backend; raw blobs stay local (SPEC.md A23).** The owner asked
  what the current DB solution was, having spun up a Supabase project and
  suspected it was unused. It was: `sqlite3` appeared in exactly one module,
  and the only mention of Postgres anywhere was the aspirational paragraph in
  this file's own Scaling section. Asked to migrate fully, and told the
  trade-offs, the owner chose a **dual-backend** shim over Postgres-only and
  **blobs on local disk** over either `bytea` or Supabase Storage.

  *Why dual-backend rather than Postgres-only.* The test suite is this
  project's constitution in executable form, and the standing rule is that it
  needs no secrets and no live services. Postgres-only would have turned
  `git clone && pytest` into a project requiring a running server — a real
  loss of auditability, which philosophy #8 ranks above generality. It also
  keeps a rollback path: a free-tier project pauses after 7 days idle, and an
  instrument that cannot open its own data because a hosted service is asleep
  is a worse instrument. Cost, stated plainly: schema changes are now written
  once and translated, and the parity tests are what keep that honest.

  *Why blobs on disk.* Rejected `bytea` (a lap is ~830 KB here; at the default
  retention of 100/cohort across 25 cohorts that is ~1 GB, twice the free
  tier, and one `rebuild-map` would pull ~1 GB of egress because the pipeline
  loops `load_lap_arrays` over every observation). Rejected Supabase Storage
  (a second remote system with no shared transaction, so a committed row
  delete with a failed object delete leaves the two silently divergent —
  exactly the class of inconsistency philosophy #7 forbids). Local disk keeps
  the transactional guarantee and costs nothing. The trade-off is real and
  accepted: a lap's raw trace is readable only on the machine that imported
  it. That degrades into the *existing, already-tested* "evicted by retention"
  path — `load_lap_arrays` has always returned None there, the track-trace
  view 404s, the pipeline skips re-measurement — so findings, trends, scores
  and reports are unaffected.

  *What the migration surfaced.* Four pre-existing defects, all invisible on
  SQLite because it satisfied them by accident: `corner_positions` had no
  `ORDER BY` while its dict order decided which corner an incident was
  labelled with (and `rebuild-map` reshuffles those rows); the vs-self tercile
  split had no tie-break while slicing fast/slow groups out of that order;
  `AND 0` relied on int-as-boolean coercion on the M6 trend path; and
  `store_incidents` passed numpy int64 sample indices to sqlite3 unadapted, so
  three INTEGER columns held raw little-endian BLOBs. Also found: psycopg3's
  `with conn:` *closes* the connection where sqlite3's does not, which across
  19 such blocks would have been silent and catastrophic — caught by testing
  the assumption rather than reading the docs. And `docs/coaching-report.md`
  had been stale since the A18 ranker fix, so the artifact byte-diff gate was
  quietly meaningless until it was regenerated first.

  *Security, decided rather than assumed.* Supabase auto-exposes `public` over
  PostgREST using an anon key that ships in every project, so tables there
  would have published the driver's telemetry and chat transcripts to an
  unauthenticated endpoint — while README.md advertised the opposite. Tables
  live in a `driverdna` schema and carry RLS with zero policies; proven by a
  role standing in for `anon` with an explicit SELECT grant reading zero rows.

  *The proof.* The same fixture corpus imported into either backend produces
  byte-identical metrics, attribution, incidents, coaching and driver-model
  artifacts, and a `store-copy` of a populated SQLite store into Postgres
  reports all 15 tables checksum-identical with the artifacts still
  byte-identical afterwards. An earlier cross-backend run *did* differ — which
  turned out to be the harness dropping the manifest's `session_key`, not the
  backend. Recorded because it is exactly the sort of false positive that
  would otherwise discredit a real one.

- **2026-07-26 — U6 "cockpit actions" built (`POST /api/sync` +
  `POST /api/cohorts/{slug}/rebuild-map`).** The second, write-side half of
  design language v2, unblocked once U5's gates went green. Both endpoints
  are pure wrappers per decision 3 — no business logic in `api.py`: `/api/sync`
  constructs `Garage61Client()` straight from the environment (`GARAGE61_TOKEN`)
  and calls `sync_driver` verbatim, never reading a token from the request
  body; `/api/cohorts/{slug}/rebuild-map` resolves the slug via the existing
  `resolve()` and calls `rebuild_cohort_map` (the A22 in-place refreeze),
  404ing both on an unknown slug and on a resolvable cohort with no frozen
  map yet — mirroring `driverdna rebuild-map`'s exit-2 in both cases.
  CLI-effect parity (decision 3's binding condition) proven directly in
  `tests/test_cockpit_api.py`: a mocked `Garage61Client` (canned lap listing +
  CSV bytes, never a live API or a real token) is synced through both the
  endpoint and `driverdna sync` to independent fresh DBs, asserting identical
  lap/corner-observation/sync-state rows; separately, one real fixture
  cohort (GR86 @ Spa-Francorchamps) is imported once, copied to two DB
  files, rebuilt via the endpoint and via `driverdna rebuild-map`, asserting
  identical `corners`/`corner_windows`/`phase_times` rows. A dedicated test
  proves the token stays env-only: `GARAGE61_TOKEN` unset returns HTTP 400
  with the client's own actionable message and the DB is never even opened.
  10 API tests plus 2 browser-driven tests (`tests/test_cockpit_ui.py`,
  mirroring `test_upload_ui.py`'s convention) — suite 518 → 530, all green.
  UI, v2 button system: a `btn-primary` **Sync** on driver home renders each
  cohort's seen/new/skipped/admitted/class-change lines verbatim (a `.reason`
  guidance line — "Set GARAGE61_TOKEN to sync." — replaces the button's
  output when the token is absent, never an input field, so the secret never
  transits the browser); a `btn small` **Rebuild map** in the cohort context
  strip opens a client-side confirm/cancel gate (decision 5 — the same
  non-default-action discipline as the config panel's staged card, just
  without server-side staging, since a map rebuild has no engine-level
  "propose" step to mirror), then renders the rebuild report as a per-corner
  table (centroid shift, window changed, laps re-measured, laps cleared)
  plus the admitted/class-change/cleared-stale-phase notices, and triggers a
  payload refetch afterward since corner geometry, classes, and loss figures
  can move. Four implementation-time decisions flagged in UI-SPEC.md's U6
  section (details the spec's seven conditions left open, not changes to
  them): both endpoints require a pre-existing DB via the same `open_db()`
  helper every write endpoint but `/api/laps/upload` uses (upload remains the
  sole cold-start exception); the missing-token error is HTTP 400 specifically
  (in the required 4xx range, chosen over 422 — reserved for an invalid
  request body, which this isn't — and over the 503 already used elsewhere
  in this file for a missing `ANTHROPIC_API_KEY`); `/api/sync` returns a bare
  `list[CohortSync]` per condition 1's literal wording rather than an
  upload-style `{results, evicted}` wrapper (retention eviction still runs
  for parity, just isn't separately echoed); Sync lives on driver home only,
  not duplicated onto Garage. All five trust gates green; no route-list
  changes needed (both buttons live on already-covered routes, and their
  result panels render only after a click, so the static crawlers never see
  them — the same reasoning that already excludes `#/upload`). `npm run
  build` ships the updated SPA bundle in-package.
- **2026-07-22 — U5 "pit wall" restyle built (design language v2).** Executed
  the v2 spec on the owner's go. Token layer: `ui/tokens.json` gains
  `font.display` (IBM Plex Sans Condensed, self-hosted 600/700 latin —
  bundled, offline intact) and a `shape` group (chamfer sizes); `main.jsx`
  generalized from colour-only to inject every token group as a CSS var;
  `report/builder.py`'s `_TOKENS` mirror gains `display` so the byte-match
  test stays green (reports don't reference it yet — SPA-only, like the
  bundled fonts). Shell: a constant six-tab bar (Driver · Model · Garage ·
  Chat · Import · Config) with the DriverDNA wordmark + a helix/racing-line
  inline-SVG mark; cohort-scoped nav moved to a per-view context strip
  (`ContextStrip`). New **Garage** view (view 8) over the existing
  `/api/cohorts`; driver home is now purely the rollup + pit-board stat
  tiles. Button system (chamfered, condensed-uppercase labels, inset focus
  ring): `btn-primary`/`btn`/`btn small`/`btn confirm`, and every action
  that was a text link is now a button. Reference-lap visibility folded in
  (R1): a "Reference laps" cohort tile + panel, the isolation guarantee
  line, "ref n=K" on vs-reference findings, a "References" line naming
  driver + lap time over the one read-field addition (`driver` on
  `/api/laps`), and the N=0 direction state. Copy trimmed throughout per the
  owner's "very wordy" note (the explanatory `.sub` paragraphs cut to one
  line or a `title` tooltip; measurement copy and gate reasons kept verbatim).
  Colours, colour grammar, and all five trust gates unchanged. Two
  route-list details resolved at build (flagged in UI-SPEC U5): `#/garage`
  added to the offline route list only (no measurement to parity-crawl,
  like `#/upload`); no `role='reference'` lap seeded into the shared
  `tests/fixtures/` DB (reference figures are parity-clean by construction;
  seeding would perturb determinism/report-snapshot tests). Built SPA
  reships in-package; suite green. Mockup: `docs/ui-redesign-mockup.html`.
- **2026-07-22 — UI copy flagged "very wordy" (owner).** Recorded as binding
  copy guidance in UI-SPEC.md ("Copy density"): the instrument speaks in
  labels, not paragraphs (iRacing/timing-screen register) — captions ≤ 3
  words, state lines one sentence, explanatory sub-paragraphs cut to a line
  or a tooltip; measurement copy and gate reasons keep their exact words.
  Acted on in the U5 build above, not just filed.
- **2026-07-22 — Reference-lap survey + R-track plan written
  (`docs/REFERENCE-LAPS.md`), owner-requested.** Owner asked for "a schema or
  a plan on incorporating reference laps — one may exist but i haven't seen
  it." Both halves true, so the doc does both: a cited survey showing the
  machinery is built and tested (role column + CHECK, query-surface
  isolation, shared `(car,track)` corner maps so gaps join on the owner's
  own corner identities, `reference_envelope` + `vs_reference_findings`
  through payload/report/UI, manual-import-only per M0b/A16) and the
  structural reason it has never fired: the owner's DB contains zero
  reference laps — `sync` can't fetch them and none was ever imported, so
  every vs-reference path is correctly silent. Doc includes the
  owner-runnable recipe (Garage61 web export → `import --role reference` →
  the vs-reference section appears; a live re-observation of trust
  condition 3), six honest gaps (invisibility, envelope opacity,
  undifferentiated pool, no curation, sourcing friction, no drill-level
  reference depth), and a design-stage **R-track**: R0 (owner feeds one
  real reference lap; gate for everything else) → R1 (visibility, UI-only)
  → R2 (reference identity/depth; label semantics deliberately left open)
  → R3 (curation; option A, an audited annotations-style exclusion,
  recommended over B, no mechanism). Non-goals restated as binding
  (no references in Driver Model/trends/classes/consistency/incidents, no
  "recoverable time", no auto-sync, no blending). Nothing built; awaiting
  owner reaction, M7 precedent.
  *Follow-up same day (owner: "make the reference lap easier to see and
  understand and incorporate that into the ui plan"):* R1 fleshed into a
  "see & understand" layer and **folded into U5** (UI-SPEC.md
  "Reference-lap visibility"). Split by data dependency: R1a
  discoverability (N=0 vs-reference direction state + import button, the
  isolation guarantee line, upload help — needs no data, isn't R0-gated,
  and is what leads the owner to R0) and R1b legibility (reference stat
  tile, "ref n=K" on gap findings from the payload, a "References" line
  naming driver + lap time). One read-field addition only: `driver` on
  `/api/laps` (`api.py`) so the name traces to a read endpoint — render
  parity honored, engine untouched. Mockup updated to show both states
  (`docs/ui-redesign-mockup.html`). Crawler fixture gains one
  `role='reference'` lap so the section is exercised.
- **2026-07-22 — UI design language v2 ("pit wall") specced, owner-directed.**
  Owner asked for a better UI design: keep the color scheme; more simplicity,
  more buttons, a small tinge of personality; iRacing's UI/promotional
  language as the reference register. Specced as an amendment
  (`docs/UI-SPEC.md`, "Design language v2"), not a rewrite: all eleven token
  colors, the three color-grammar rules, structural source-tag identity, the
  mono-numeral rule, suppression rendering, motion rules, and all five trust
  gates are explicitly unchanged. What v2 adds: an IBM Plex Sans **Condensed**
  display face for structure labels only — this amends the base section's "no
  decorative display face" clause, and the recorded reason is that the
  clause's intent (no typographic editorializing about *numbers*) survives
  verbatim while structure labels gain a voice from the same Plex
  superfamily; a single top-right 45° chamfer as the one geometric tell; a
  three-tier button system plus the rule "an action is a button, navigation
  is a link"; a constant six-tab shell (contextual links move to a per-view
  context strip); a **Garage** view (view 8 — the cohort index over the
  existing `GET /api/cohorts`, no new endpoint; driver home stops doubling as
  the cohort list); pit-board stat tiles (payload values or rendered-item
  counts only, the `shownCount` precedent); and a bounded four-element
  personality kit with binding boundaries — no license-class letter cosplay
  on scores (a letter on a score is a grade, an opaque blend by another
  name), no alarm red, no decorative motion, idiom in state copy only. New
  milestones: **U5** (restyle; `#/garage` added to both hardcoded browser
  route lists) and **U6** (cockpit actions: `POST /api/sync` +
  `POST /api/cohorts/{slug}/rebuild-map`, both CLI-effect-parity tested;
  `GARAGE61_TOKEN` stays env-only, never an input field; rebuild-map behind
  its own explicit confirm since it rewrites frozen geometry). Checked
  against the philosophy: no principle touched; #6's anti-blend line is
  guarded explicitly by the license-letter ban. Spec-first per the M7
  precedent — build awaits owner go. Mockup with labeled placeholder
  numbers: `docs/ui-redesign-mockup.html`. Delivered on session branch
  `claude/driverdna-ui-redesign-j6riya`.
- **2026-07-21 — `rebuild-map`: in-place refreeze of a frozen corner map from
  its full lap set (SPEC.md A22), the last of the owner's E→F→G arc.** Corner
  maps + canonical phase windows freeze from a cohort's first laps (M1) and
  never re-derive as more accumulate — deferred since A17 because it only
  bites at veteran-scale histories. Owner chose to take it on now; a real
  motivating case exists (two independent Spa/GR86 cohorts —
  `tests/fixtures` + committed `spa-blind-2026-07/` — that froze from
  disjoint lap sets). Investigation-first, per the arc's rule: read
  `corners/identity.py`, `pipeline.py`'s import + `_freeze_windows_for_
  admitted` + `_reclassify`, and every `db.py` corner/window/phase-time
  path before designing. Two forks surfaced with the full mechanism in hand
  and owner-decided (not assumed):
  - **Versioning: in-place, NOT a new `map_pk`** (owner: "lets go #1"). Same
    `corner_pk`/`corner_id`; each corner's centroid is recomputed from its
    *currently assigned* observations' apex positions (so centroid and
    assignment stay consistent — no re-matching), its windows from all its
    observations' landmark positions via the existing `derive_windows`, then
    phase times re-measured. This literally generalizes
    `_freeze_windows_for_admitted` (which already does exactly this for one
    newly-admitted corner) to every corner. Rejected — a versioned map (new
    `map_pk` per rebuild, old evidence pinned): would force dropping
    `corner_maps`' `UNIQUE(car, track)`, adding a current-map concept, and
    adding `AND c.map_pk = <current>` to *every* query joining `corners`
    (`self_metric_table`, `self_detector_table`, `phase_history`,
    `vs_self_findings` and siblings) or a two-version cohort would silently
    double-count — a large, invasive query-layer change for a
    history-of-past-maps feature not needed at this scale. Every other frozen
    value in the codebase is single-current, so in-place is consistent, not
    an exception. The property actually worth protecting is evidence-ID
    stability, and in-place gives it outright: `corner_observations` rows are
    never renumbered or deleted, only their linked window/phase-time data is
    refreshed (verified by test — corner_pks and obs→corner assignments
    byte-identical across a rebuild).
  - **Evicted-blob laps: clear the stale phase times + report loudly** (owner:
    "make sure #2 gets added to the plan if it's important" — it is, so it's
    in the plan, SPEC A22, and here). A lap whose raw blob was evicted past
    retention can't have its phase times honestly re-interpolated against the
    new windows; leaving the old numbers would present a measurement against
    a retired window — silent repair, forbidden (philosophy #7). So the
    command DELETEs those `phase_times` rows and lists every affected
    `(lap_pk, corner_id)`; identity/metrics/detectors/evidence-ID all stay
    intact, only the phase-time figure goes — an honest "insufficient data"
    gap, same as anywhere else. Doesn't fire at today's volume (retention
    default 100/cohort), but is defined and tested (a shrunk retention forces
    an eviction; `total_cleared > 0`, phase rows gone, observation rows
    intact). New geometry still enters through the existing audited admission
    path (verified: a below-threshold candidate stays unadmitted until the
    threshold is lowered, then rebuild admits it — never a silent map
    change). Deterministic + idempotent: two independent import+rebuild runs
    produce byte-identical centroids and windows, and a second rebuild of the
    same DB is a no-op. Real two-cohort run: merging the primary + blind Spa
    cohorts and rebuilding sharpened centroids by up to ~58 m toward the
    full-set median and shifted 20/21 windows, IDs unchanged. No committed
    artifact changes (the `corners`/`metrics`/`model` reports all regenerate
    from a fresh import with no rebuild step). 10 new tests; 534 green.
- **2026-07-21 — `consistency`'s cross-metric-type CV pooling fixed
  (`dm-v2`, SPEC.md A21), after the original diagnosis turned out to be
  wrong.** Owner-specified order for this arc: doc fixes, then this fix,
  then a `rebuild-map` command. The M6 "Known v1 limitation" note (written
  when M6 shipped, 2026-07-20) blamed *cross-cohort* raw-magnitude pooling —
  two cars with different natural scales for the same metric inflating the
  pooled CV. Investigated before writing any fix code (this project's
  standing practice: verify a documented mechanism against real code and
  real data first): reading `_consistency_component` showed each CV was
  *already* computed from one cohort's own value array, never pooled raw
  across cohorts — the original note's mechanism was simply inaccurate. A
  real two-cohort test (the primary GR86/Spa fixtures plus a second, real
  car/track cohort) confirmed it empirically: the *same* metric's CV came
  out comparable across cars (e.g. `min_speed_kmh` 0.078 vs 0.069;
  `apex_dist_pct` 0.008 vs 0.011) — cross-cohort pooling wasn't depressing
  anything. The real mechanism, found by grouping raw CVs by
  `metrics/technique.py METRIC_DEFS`'s existing `unit` field: percentage-
  of-distance metrics ("% lap": turn-in point, brake point, apex, throttle
  pickup) have a naturally tiny CV, observed median ~0.007, while small-
  integer count metrics (steering corrections, throttle modulation) have a
  naturally huge one, observed median ~0.99 — a ~140x scale gap. Pooling
  raw CVs with a flat mean let whichever metrics were high-CV *by unit*
  dominate the pooled signal regardless of the driver's actual consistency.
  <br><br>
  Presented four fix options to the owner via AskUserQuestion; **owner
  picked per-metric normalization**: divide each metric's raw CV by a
  documented per-unit reference scale before pooling. Two design choices
  had to be made beyond that pick, both settled empirically against real
  data and the existing test suite rather than assumed:
  1. *Reference values*: fixed, documented per-unit constants
     (`config.model.consistency_unit_reference_cv`, 9 units) rather than
     recomputed live from whatever's being scored — a live self-reference
     (e.g. each metric's own median from the same query) was considered and
     rejected: normalizing a sample against a reference drawn from that same
     sample set trends any driver's pooled score toward a fixed "shape"
     constant regardless of their actual consistency, destroying the score's
     discriminative power. The 9 defaults are observed median raw CV per
     unit from real committed multi-car/multi-track telemetry, not guessed.
  2. *Pooling structure*: two-level (mean within each unit, then mean across
     units), not a flat mean over every sample. A flat mean was tried first
     and rejected against real data: a unit with many contributing
     corners/metrics (e.g. "% lap", ~5 metrics × many corners) dominated a
     flat pool by sample count alone, and dividing by a very small reference
     amplifies any one genuinely inconsistent corner into a normalized value
     large enough to crush the whole average — observed for real: one
     corner's genuinely wide entry/exit-point variation swung the flat-
     pooled score to 0 regardless of every other corner's real consistency.
     A median (flat, or at either level of the two-level scheme) was also
     tried and rejected: with as few as one corner's worth of metrics in a
     pool, a median just selects whichever metric ranks middle, which need
     not be the one actually varying — this broke three existing trend
     tests (`test_trend_improving/declining/is_deterministic`) outright, a
     real regression the test suite caught, not a style preference. Mean at
     both levels keeps every sample proportionally represented while
     capping how far any single unit's sample count can skew the result.
  <br><br>
  The ceiling (`consistency_cv_ceiling`) also needed recalibrating, since
  its old default (0.5) was tuned for raw CV magnitudes, not multiples of a
  unit reference: 2.0 was chosen so a normalized value of 1.0 ("exactly
  your own typical/reference consistency for that kind of metric") scores
  50 — a clean, legible midpoint. This is a real formula change for the
  same evidence, so `SCORING_MODEL_VERSION` bumps `dm-v1` → `dm-v2` per the
  Scoring Contract. Real-fixture effect (`docs/driver-model-report.md`):
  `consistency` 5.1 → 34.3 (no longer crushed near zero, the original
  complaint); `braking` 71.9 → 80.5; `corner_exit` 66.0 → 65.2; `rotation`
  58.6 → 60.2; `commitment` 96.5 → 56.1 — this last one dropped because it
  was inflated by the *same* bug in the opposite direction: its only
  consistency metric is a "% lap" type, which scored trivially near-perfect
  against the old ceiling regardless of real spread. Both directions
  correcting confirms the fix generalizes, not just patches the one
  symptom that prompted it.
  <br><br>
  One incidental bug found and fixed while implementing: `ConfigStore._write_
  toml` (`config.py`) is a hand-rolled TOML writer (no library dependency;
  `tomllib` is stdlib read-only) that had only ever needed to render bool/
  str/numeric config values — it fell back to Python's `repr()` for anything
  else, which produces `{'key': value}` (colon separator, single-quoted
  keys) for a dict, not valid TOML (`{"key" = value}`). Never hit before
  because no config field had ever been dict-valued; `consistency_unit_
  reference_cv` is the first. Fixed generally (`_render_toml_value`,
  recursive, quotes keys) rather than special-cased, and round-trip tested
  (write → `tomllib` read back → equals the original dict) — caught by the
  full test suite (`test_api.py`/`test_chat.py`'s config propose/apply/
  revert tests), not by the new scoring tests themselves.
  <br><br>
  Left deliberately unfixed, flagged in SPEC.md: the M7 coaching layer's
  `same_lap_twice` principle has the *same* cross-metric-type CV pooling
  issue, one level down (per-corner instead of per-driver;
  `coaching/engine.py`, `CoachingConfig.consistency_cv_floor`) — a different
  code path, out of this fix's scope, likely reusable via the same
  `consistency_unit_reference_cv` table whenever that principle's scoring is
  next revisited.
- **2026-07-21 — Car/track auto-detected from Garage61's newer export
  filename shape, closing the gap flagged when upload-laps first shipped.**
  A real second batch of owner laps (Ford Mustang GT4 @ Summit Point
  Raceway) used a filename Garage61 apparently switched to for some exports:
  `Garage_61__<driver>__<car>__<track>__<laptime>__<id>.csv`, double-
  underscore delimited, versus the short `Garage_61_<LAPID>.csv` form every
  fixture and the M0a contract were built on. New `parse_garage61_filename`
  (`ingest/parser.py`) recognizes it — additive, doesn't touch the locked
  parsing contract itself, only widens what can produce `lap_id`. Wired into
  both entry points: `driverdna import` with no `--car`/`--track` now tries
  per-file auto-detect (itemizes, in one loud error, any file that can't
  resolve — never partially imports), and the upload API's `car`/`track`
  form fields became optional the same way, each file landing in its own
  resolved cohort. Real end-to-end proof, not just unit tests: imported the
  owner's actual 4 distinct Mustang laps (a 5th was a re-download duplicate,
  same pattern as the Spa uploads) with zero flags typed, in both the CLI
  and a real Playwright browser session. One finding recorded in
  `docs/garage61-api.md`, flagged unverified rather than asserted: the new
  filename's trailing ID is 26 characters starting `01K...`, matching the
  API's own ULID `id` field's shape — unlike the old short code, which M0b
  already established as a different ID space entirely. If that holds
  against a live call (not tested here), the `/laps/{id}/csv` parity gap
  M0b hit might be closable for laps in this format; left for whoever next
  has a live token and a lap in this shape.
- **2026-07-21 — Upload-laps UI built, closing the last CLI-only gap in
  UI-SPEC view 7 ("Laps"), plus a git-workflow change: commits go straight
  to `main` from here on.** Owner asked directly for the workflow switch
  ("auto commit and push everything to main in the future") — merged the one
  commit still ahead on the feature branch (a trivial fork, both sides
  descending from the same parent) and will keep committing to `main`
  directly; the branch + PR flow used for the rest of this session is
  retired. On upload: `POST /api/laps/upload` is a thin multipart wrapper
  over `import_lap_file` — the exact function `driverdna import` calls per
  file, verified not just asserted: the same fixture lap imported via the
  API and via the CLI to independent fresh DBs produced byte-identical lap
  rows and corner-observation counts (`test_upload_api.py`). One deliberate
  exception to every other endpoint's "DB must already exist" rule: this one
  creates it, so a driver can go from nothing to a working cockpit through
  the browser alone. That surfaced a real gap while testing it end to end in
  a live browser (not just the API in isolation, per this project's UI
  testing rule) — Driver Home's cohorts panel called `/api/cohorts`
  unconditionally, so before the very first lap ever exists it showed a raw
  `no DB at ... run driverdna import first` error, a CLI instruction a
  browser-only user has no way to act on. Fixed: that specific 404 now routes
  to the same "Import laps →" direction the zero-cohorts state already gives
  (UI-SPEC's "empty state is a primary state" principle extended one layer
  earlier, to before a DB file exists at all). New `#/upload` view: file
  picker, car/track/role/date/session fields (mirroring `driverdna import`'s
  own flags exactly), and the engine's own per-file report rendered back
  verbatim (matched/admitted/class-changed/duplicate) — nothing computed in
  the browser. The landing link into a freshly-created cohort uses the
  server's own returned slug, never a client-side-regenerated one (decision
  2: no derivation in the SPA). Same pass also finally surfaced the M7
  coaching layer in the UI (computed since M7 but never rendered) and
  redesigned the Driver Model tab as a pyramid, per direct owner feedback
  after using the product for the first time ("sound advice, wants it
  friendlier and prettier") — full detail in the entry below this one, from
  earlier the same day. 11 new tests (API-parity + a real Playwright flow:
  file picked, submitted, result rendered, landed cohort verified) on top of
  today's earlier 486. `python-multipart` added as a declared dependency
  (FastAPI's Form/File support requires it; wasn't installed, a real gap
  caught by actually running the endpoint, not just importing it).
- **2026-07-21 — Coaching surfaced in the UI and the Driver Model tab
  redesigned, per direct owner feedback after using the product for the
  first time.** Feedback was specific: the coach's advice ("sound") needed
  to be "a little more user friendly and visually appealing," same for the
  model tab. Investigation before building anything found the real issue
  wasn't styling: the whole M7 grounded-coaching layer (headline / secondary
  / self-checks) was fully computed in the payload and never rendered
  anywhere in the SPA — findings only ever showed raw numbers. Added
  `CoachingHeadline`/`CoachingSecondary`/`CoachingSelfChecks`
  (`ui/src/views/shared.jsx`) to the cohort page. Caught and fixed a real UX
  problem while building it, not just guessed at: on the real Spa data one
  principle (repeatability) clears the gate at 14 different corners
  independently, and rendering that as 14 identical paragraphs read as spam
  — grouped by principle instead, said once, with each corner's own
  magnitude as a compact tag (pure layout; every number still traces 1:1 to
  its own record). A second pass caught the headline's own principle
  re-appearing verbatim in secondary for its other corners too — now
  cross-referenced instead of repeated. For the model tab, owner chose a
  bold pyramid over refined meters (offered both); built as a truncated
  SVG pyramid, foundations at the base, deliberately NOT a radar/spider
  chart since its enclosed area would read as a blended overall score,
  which the philosophy forbids (rule 6). Score magnitude uses one neutral
  steel-grey hue per the dataviz skill's sequential-encoding rule, never
  the palette's reserved semantic colors. Fixed a real grammar violation
  found while rechecking the file: the fundamentals meter list's trend
  arrows were colored green/red, quietly breaking the "no alarm color on
  driving" rule since Phase C first built the tab. Verified against the
  live-built SPA with Playwright screenshots, not just described — including
  catching and closing a real render-parity coverage gap the pyramid
  introduced (its SVG score text used a custom class the crawler's `.num`
  selector didn't match, so those numbers weren't mechanically checked until
  fixed). 486 tests green at the time.
- **2026-07-21 — Coaching over incidents built (SPEC.md A20): the deferred
  Layer 3, closing the loop A19 opened.** Owner asked to continue straight
  into it after the model view. The design question was whether the AI picks
  *which* coaching principle explains an incident from a set of eligible
  ones (as `coaching_priorities` already allows for findings) or whether that
  link is itself deterministic. Went with the latter, and it's the more
  defensible reading of the constitution: an incident's classification is
  already a diagnosis the engine made (A19); letting the AI then choose among
  several plausible principles for *why* would reopen exactly the
  diagnosis-by-AI door non-negotiable #1 closes for scores. So
  `incidents/coaching.py` fixes a 1:1 map from classification to principle
  (reusing the nine existing seed principles, no new ones invented), computed
  once in the payload; the coach's `incident_explanations` output is
  mechanically rejected if it cites anything other than that exact principle
  — the AI has zero choice, only prose, same posture as a `finding_id`'s
  number. `unclassified`/`external` incidents get no principle and cannot be
  explained — the engine didn't name a cause, so the AI doesn't either.
  Scope: built for the `coach` structured-output path (JSON schema, local
  validator, persisted plans) since that's where the existing grounded-output
  machinery already lives; chat's live Q&A doesn't consume incidents yet —
  deliberately left as a boundary, tested on both sides (a coach payload now
  carries `incidents`; a chat bundle still doesn't), not silently forgotten.
  6 new tests (wrong-principle rejection, unclassified-incident rejection,
  missing confidence, invented number, acceptance + markdown rendering).
  481 tests green. No live run possible (`ANTHROPIC_API_KEY` unset in this
  environment, as for every coach/chat feature so far) — mock-provider tested
  only, consistent with the rest of the suite.
- **2026-07-21 — Driver Model UI view built: M6 is finally visible.** The
  Driver Model is the constitution's centre of gravity ("the persistent Driver
  Model is the product"), yet the whole U0–U4 UI track shipped without a screen
  for it — it lived only in the payload and the `driverdna model` artifact.
  New render-only `#/model` view surfaces the 7 fundamentals (score /
  confidence / evidence / trend) from `/api/driver`'s existing `driver_model`
  section; render-parity crawler extended to cover it. The A14 rule is now
  enforced *visually* too, not just in the engine: a `no_signal` fundamental
  renders in its own "stated, never scored" section with no score/confidence
  at any level — `vision` on the fixture data is the live example. Scope call:
  rendered fundamentals, the granularity the belief store carries; a
  technique-level decomposition (the 17 techniques under the 7 fundamentals)
  would first need the payload to expose per-technique signals — a follow-on,
  outside "render-only". Completes the three-item arc (preserve laps →
  incidents → model view) from this session's "what's next".
- **2026-07-21 — Incident subsystem built (SPEC.md A19): a spin is a
  measurement, not noise.** Owner's insight, and it's deeply on-thesis: every
  other telemetry app treats a spin or an off as an annoyance to filter;
  "measure the driver, not the lap" makes it the single richest driver signal
  on a lap. Owner-chosen scope: Layers 1+2 (detect + characterize,
  deterministic) this pass; the coaching "why & what to do" (Layer 3) is the
  next pass and cannot precede the classification it must cite. Verified the
  telemetry supports it before designing anything — the real `9XVJTW` La
  Source trace shows the whole mechanism (hard trailing brake → rear steps out
  → off-track via `PositionType` 3→4 → opposite-lock catch → near-stop) from
  channels the parser already carries. Detection (`detector.py`): a lap-level
  scan for near-stop / off-track / steering-reversal-with-yaw-spike snap,
  merged into one event, labelled with the nearest frozen corner.
  Characterization (`classify.py`): mechanism named from the state at the
  *causal* onset. Two design decisions worth recording, both found by testing
  against the real lap, not guessed: (a) onset is the *first yaw divergence*,
  not the peak-yaw moment — at peak yaw the driver is already reacting
  (throttle stab, opposite lock) and the causal input is gone, which
  misclassified the real spin as power-on until fixed; (b) the snap signal is
  a steering *reversal through zero* with an elevated yaw rate, not
  "steering-opposite-to-yaw" — in this data steering and yaw share a sign
  convention and reversed together, so the opposite-sign heuristic would have
  missed it. Conservative by construction: an ambiguous signature is
  `unclassified` (detected, cause not named), confidence is a coarse word
  never a laundered percentage, and one incident is N=1 — an event, never a
  trait. Deliberately did NOT build a separate ingest-time incident detector:
  the existing MAD outlier fence already isolates exactly the two known
  incidents, so a second mechanism would add surface area, not correctness —
  and did NOT feed incidents to the coach/chat, because the grounded
  citation path for them is Layer 3's job (a model must not narrate a spin it
  cannot cite). Persistence (`incidents` table, migration 005), payload
  section (PAYLOAD_VERSION 3→4, stripped from AI bundles), `driverdna
  incidents` artifact, and cohort/laps UI. Validated end-to-end on the
  committed real ground truth: `9XVJTW`→trail_brake_oversteer/high at C01,
  `9PH9M2`→near-stop at C15, the two genuinely-slow La Source laps flag real
  near-stops (5–19 km/h vs 45–70 clean), every clean lap silent — no false
  positives. ~26 tests (synthetic per-mechanism, determinism, isolation, real
  ground truth). 475 total green.
- **2026-07-21 — 11 independent Spa blind-test laps committed as a second
  cohort** (`tests/fixtures/spa-blind-2026-07/`), out of the primary fixtures
  glob so no existing anchor moves. They were the owner's own laps for the A18
  blind test — now preserved (the scratchpad is ephemeral) and doubling as
  real-data regression material; the two incident laps (`9XVJTW`, `9PH9M2`)
  are the ground-truth fixtures the incident subsystem above asserts against.
- **2026-07-21 — Spa blind test finally run (SPEC.md A18): it caught a real
  bug and a fictional ground truth, not a passing grade.** The owner supplied
  laps in batches; each was hashed against `tests/fixtures/` and every prior
  batch before import — most turned out to be re-downloads (browser `_2`/`_3`
  suffixes) of laps already in the corpus the engine was built on, which
  cannot count as independent evidence. 11 genuinely new GR86/Spa laps across
  6 sessions survived that filter and were imported to an isolated scratch DB
  (never `tests/fixtures/`), clearing both `min_sessions` (6≥2) and, per
  corner, `min_phase_samples` (10-11 raw). Verified before trusting the
  result: a whole-lap incident exclusion would have dropped nearly every
  corner below the sample gate, but the actual incidents were corner-specific
  (see below), so a corner-level exclusion left every corner at or above the
  floor — no additional laps were needed to run the real test.
  Two findings came out of the run, both worth recording on their own:
  (1) **The predicted ground truth in gate 1 (Sector-1 high-speed-entry
  commitment, ±1.2 s spread) never held — on the new data, or, re-checked
  directly, on the original fixture corpus either** (max per-corner entry
  spread ≈0.15 s in both — an order of magnitude under the claim). It was
  never engine-corroborated; it read as a coarse, unverified belief about the
  driving written into binding acceptance criteria before anything could
  check it against the criteria's own instrument. Retracted in SPEC.md gate 1,
  replaced with the engine's actual output as the new comparison point:
  loss concentrated at the two slow corners (La Source, Bus Stop), fast
  corners (Eau Rouge/Raidillon, Blanchimont) essentially loss-free — the
  inverse of the original claim.
  (2) **Investigating why the top two reported findings looked implausibly
  large (C01 mid 2.06 s, C15 exit 1.95 s) found a genuine engine bug.**
  Per-lap phase-time forensics (cross-checked against raw speed traces, not
  just the numbers) identified one lap with a 5 km/h near-stop at La Source
  (a spin) and one with a 15-second dead stop at the Bus Stop — both landed
  in the slow tercile of `vs_self_findings`'s opportunity split, which,
  unlike `baseline()`, applied no outlier screening. Confirmed by removing
  the incident laps by hand first (C01 mid fell to 0.82 s, matching the
  post-fix engine run exactly) before touching any code. Fixed: the same
  median±k·MAD fence `baseline()` already used (`outlier_mad_k`, config
  default 3.5, already owner-approved and versioned) is now applied to the
  opportunity/repeatability computation too — `engine.screen_outliers`
  refactored into a reusable `outlier_mask` so `ranker.py` can filter full
  observation records, not just bare time values. Deliberately *not* built:
  a new ingest-time "incident detector" — hand-verifying the MAD fence
  against both known incidents showed the existing statistical mechanism
  already isolates exactly them, so a second, redundant subsystem would
  have added surface area without adding correctness.
  `docs/attribution-report.md` regenerated from the real fixture corpus: two
  previously-"shown" findings (C03 exit, C02 mid) turn out to have been
  partly outlier-inflated themselves and are now correctly suppressed as
  no-effect/gated — the fix changed fixture-corpus output too, not just the
  new blind-test data. New regression test
  (`test_vs_self_opportunity_ignores_one_incident_lap`, `tests/test_attribution.py`)
  plants an isolated severe incident on top of the existing planted-weakness
  cohort and asserts it's screened while the raw sample stays counted
  (`details.n_outliers`, never silently dropped). 450 tests green.
  Net verdict: the *machinery* passed — no crash, gates enforced, sources
  decomposable, and it surfaced a real robustness gap in its own ranking
  logic, which is what a trust gate is for. The *specific prediction* did
  not pass, because it was never a real prediction. SPEC.md gate 1 now
  states what the engine actually, repeatably finds on clean independent
  data as the standing comparison point for any future re-run.
- **2026-07-21 — U4 built; the UI-SPEC.md milestone track (U0–U4) is
  complete.** Three concrete gaps, from a scoping pass before starting:
  static HTML reports were still the pre-token-system light theme
  (`#1a1a1a` text, `#4472a8` chart blue — genuinely off the color grammar,
  since blue isn't in the semantic palette at all); no IBM Plex font files
  existed anywhere despite the design language naming them "bundled";
  trust gate 5 ("offline") had only a static grep, not the dynamic check
  its own wording describes. All three closed — see "The UI" section
  above for the full build record. One fork worth naming: fonts were
  self-hosted in the SPA only, not reports (owner's explicit call,
  recorded earlier 2026-07-21) — base64-inlining them into every
  self-contained report file would have added ~100-200KB per file for a
  cosmetic win reports don't need; an unavailable named font in report
  HTML just falls through to the system stack, which was already the
  status quo. Also fixed while verifying: chart colors were literally
  outside the token palette (blue has no semantic meaning in the timing
  convention), not just a different shade of an existing one — this was a
  correctness gap against UI-SPEC's color-grammar rule 1, not only a
  cosmetic mismatch.
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
