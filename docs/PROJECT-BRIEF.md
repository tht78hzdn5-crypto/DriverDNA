# DriverDNA — Project Brief

Snapshot 2026-07-19 · branch `claude/plan-review-philosophy-hl3cdg` · all v1
milestones (M0a–M5) built and tested; externally-blocked items listed under
"What's needed next". Authoritative spec: `docs/SPEC.md`. Build rules:
`CLAUDE.md`. This brief is the orientation document for anyone (human or AI)
picking the project up.

## What it is

A personal racing-telemetry instrument for one driver (iRacing via Garage61
CSV exports). It parses laps, finds corners, measures driving technique
deterministically, attributes time lost per corner phase, and reports
transferable findings denominated in cumulative seconds — sharpening as laps
accumulate. An AI layer (one-shot coaching plan + interactive chat) explains
and prioritizes the deterministic findings; it can never invent a
measurement. Python 3.11+, numpy/scipy, pydantic, typer, SQLite, anthropic
SDK. Local CLI only — no server, no hosted anything.

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
tests/            144 tests; fixtures = 2 real laps + synthetic factories
```

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

1. **`GARAGE61_TOKEN`** → run M0b (API probe): auth, listing, fetch,
   pagination, rate limits, other-driver lap access, and an API-vs-manual
   parity diff of the same lap. Then build `Garage61Client` + `sync` from
   *observed* behavior (`docs/garage61-api.md`). Nothing may assume API
   behavior before this.
2. **Session metadata for manual imports.** Fixture/manual imports currently
   have `session_key = NULL`, so the ≥2-sessions gate suppresses everything
   regardless of lap count. Sync metadata will provide sessions; until then
   the import CLI needs `--session` (or file-timestamp clustering per the
   spec) to make manually-imported history rankable.
3. **`ANTHROPIC_API_KEY`** → first live coach/chat runs (all logic is
   mock-tested; live runs will shake out prompt/formatting issues).
4. **The owner's GR86/Spa lap set (≥2 sessions)** → the blind acceptance
   test (expected: high-speed-entry commitment + entry-phase inconsistency).
5. **Map/window refreeze as an explicit operation.** Canonical windows and
   corner maps freeze from the first lap(s) by design (comparability over
   optimality). Once tens of laps exist, add a deliberate, versioned
   `rebuild-map` command (old maps kept; change surfaced) — never automatic.
6. More laps, of anything — gates clear at ≥10 phase samples + ≥2 sessions.

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

## Building a UI

**The contract already exists**: the normalized JSON report payload
(per-cohort + driver rollup) contains every number, finding, gate reason,
annotation, and caveat — `driverdna report` writes it; `report/payload.py`
builds it. A UI must render what the engine computed and never compute a new
measurement (philosophy #2). The self-contained HTML reports are the
zero-infrastructure baseline UI today.

To build an interactive local UI, add:

1. **A thin local read API** (FastAPI, ~200 lines): endpoints wrapping
   `build_cohort_payload` / `build_driver_payload`, the corners/metrics
   artifacts, and lap lists. Read-only; the DB stays the single source.
2. **Chat wiring**: `ChatSession` is already a clean programmatic object
   (`ask()`, `staged`, `confirm(n)`); expose it over SSE/websocket. The UI
   must render the staged-proposal state and make /confirm an explicit,
   separate user action (never a default button on the message).
3. **Annotation UX**: buttons on findings → `db.annotate_finding`; show
   annotated findings in their own group, measurement visible.
4. **Charts**: all series come from the payload (cumulative loss, per-class,
   lap trend, metric distributions via the chat tool query or a mirror
   endpoint). Any charting lib is fine in an interactive UI — the
   no-external-assets rule binds only the static report files.
5. **Config panel**: list `config_snapshot()` with `describe_key()` docs;
   edits go through `ConfigStore.propose/apply` so history and revert keep
   working; show `config_history` as an audit view.
6. **Packaging**: plain `uvicorn` + browser is enough for a personal tool;
   Tauri/Electron only if a desktop app feel is wanted.

What does NOT belong in a UI: blended scores, re-ranking that ignores gates,
editing measurements, or any number computed client-side.
