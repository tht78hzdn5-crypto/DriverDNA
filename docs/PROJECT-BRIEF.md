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
gate); **M6 (Driver Model) is next to build**, **M7 (Coaching Intelligence) is
design-for-review**; waiting on laps and two API keys, not on code.

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
2. **M7 — Coaching Intelligence (design-for-review, `docs/COACHING.md`).** A
   grounded coaching ontology so the AI *selects and phrases* within a fixed,
   evidence-triggered vocabulary. Awaiting owner reaction before build; a
   detector-level subset is groundable on today's engine.
3. **`GARAGE61_TOKEN`** → run M0b (API probe) then build `sync` from *observed*
   behavior (`docs/garage61-api.md`). Nothing may assume API behavior before it.
   Also ends the manual-upload loop — the biggest phone-first win.
4. **`ANTHROPIC_API_KEY`** → first live coach/chat runs (all logic is
   mock-tested; live runs will shake out prompt/formatting realities).
5. **The owner's independent Spa lap set** → the blind acceptance test. Note:
   session labelling for manual imports is now carried in the fixture manifest;
   a general `import --session` flag (or file-timestamp clustering) is still
   wanted so any manually-imported history is rankable without a manifest.
6. **U3/U4** on the UI track (chat view; packaging + shared tokens), and a
   deliberate, versioned map/window `rebuild` command once tens of laps exist
   (freezing early trades optimality for comparability, by design).
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

## The UI (U0–U2 built; U3–U4 remain)

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

Remaining: **U3** the chat view (SSE progress, validated-only display,
staged/confirm — `ChatSession` is already a clean object with `ask()` / `staged`
/ `confirm(n)`); **U4** packaging + migrating the static report templates onto
`ui/tokens.json` for one shared look. A DriverModel view follows M6.

The binding rule throughout: the UI renders what the engine computed and never
computes a measurement (mechanically enforced). What does NOT belong in a UI:
re-ranking that ignores gates, editing measurements, or any number computed
client-side. Scores are welcome — but they come from the engine's deterministic
model (M6), carry confidence + evidence count, and are rendered, never computed.

## Decision log (append-only)

Durable record of forks and their resolutions (per the Decision-discipline rule
in `CLAUDE.md`). Newest first.

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
