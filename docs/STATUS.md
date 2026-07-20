# DriverDNA — Status & Decision Log

**Snapshot date: 2026-07-20.** Branch `claude/plan-review-philosophy-hl3cdg`.
This is the single dated status doc; the verified counts below can be checked
for consistency over time. Binding records remain `docs/SPEC.md` (engine +
amendment log), `docs/ARCHITECTURE_VISION.md` (constitution), `docs/UI-SPEC.md`,
and `docs/COACHING.md` (M7 design). Orientation + full decision log:
`docs/PROJECT-BRIEF.md`.

**One line:** the deterministic engine (M0a–M7) is complete and verified; the
UI through writes (U0–U2 + render-parity gate) is done, with U3 (chat view) the
declared next UI-track milestone. M0b (API probe) is **done** — a later
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

## Verified counts (2026-07-20)

Regenerated from the repo this date, not asserted from memory:

| Count | Value | How to reproduce |
|---|---|---|
| Tests passing | **423** (27 test files) | `python3 -m pytest` |
| Commits on branch | **35** | `git rev-list --count HEAD` |
| Real laps imported | **12** (GR86/Spa 11, Mustang/Laguna 1) | `driverdna import tests/fixtures` |
| Spa cohort | 11 laps · **3 sessions** | `/api/cohorts/gr86-spa-francorchamps/payload` |
| Spa findings | **17 shown · 89 suppressed** (all suppressions state a reason) | same payload |
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
| M6 | Driver Model: deterministic versioned scoring (Score+Confidence+Evidence) | **done** — taxonomy, belief store, `dm-v1` scoring, `driverdna model` artifact, wired into report/coach/chat payload |
| M7 | Coaching Intelligence: grounded coaching ontology (`docs/COACHING.md`) | **done** — ontology, eligibility/ranking/gap-band engine, `driverdna coaching` artifact, wired into report/coach/chat payload, grounding validator extended |
| M0b | Garage61 API probe + `sync` | `GARAGE61_TOKEN` in hand; **blocked on this session's network policy** (see below) |

### UI — through writes (U0–U2)

| Milestone | What it does | State |
|---|---|---|
| U0 | FastAPI layer: pass-through reads, audited writes, `driverdna ui` | done |
| U1 | React SPA read views on the timing-screen design language | done |
| U1 gate 1 | Render-parity crawler (Chromium): no invented on-screen number | done |
| U2 | Writes — annotations + config panel through audited paths | done |
| U3 | Chat view (SSE, validated-only display, staged/confirm) | **next** |
| U4 | Packaging (`driverdna ui` ships built assets), token unification | pending |

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
2. **U3 — the chat view.** Wire `ChatSession` into the UI: SSE progress states,
   validated-only rendering, the read-only tool-call audit, and the
   staged/confirm flow. Fully built and mock-tested underneath; only *runs
   live* with an Anthropic key, so it can be built and tested now but not
   enjoyed until the key exists.
2. **U4 — packaging & polish.** `driverdna ui` one-command launch, static HTML
   report templates migrated onto `ui/tokens.json` so both surfaces share one
   look (report determinism tests stay green through the restyle).

Done since the last snapshot: **U2 — findings are now actionable.** Annotate a
finding (acknowledged / intentional) so it drops out of priority framing while
the measurement stays, reversible; a config panel retunes thresholds through
`ConfigStore` (propose → confirm → apply, with `config_history` as an audit
view and revert). All writes wrap the audited paths; the parity crawler now
covers the config view too.

Floating / key-gated:

- **M0b + `sync`** — `GARAGE61_TOKEN` is now in hand (2026-07-20; stored in a
  local, gitignored `.env`, never committed). The probe is still blocked: this
  session's outbound network policy is an allowlist (npm/pypi/github/anthropic
  etc.) that doesn't include `garage61.net`, and the agent-proxy runbook is
  explicit that a policy 403 is reported, not routed around. Next step is
  either widening this environment's network policy, or running the probe
  script from a machine that can reach the API and feeding the observed
  behavior back for `docs/garage61-api.md`. Nothing is built assuming API
  behavior until the probe documents it.
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

**UI**
- The normalized JSON payload is the rendering contract; the UI never computes a
  measurement (mechanically enforced by the render-parity crawler).
- Owner amendment: U0/U1/U2 built ahead of the blind acceptance test for
  momentum; U3–U4 keep the original gate (revisit when reached).

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
| 3 | When to run the blind test? | It's only meaningful on data whose answer I don't already know | Deferred until independent data |
| 4 | Session labels for manual imports | Filenames carry no session; grouping affects repeatability | Best-effort by upload batch, editable in the manifest |
| 5 | Keep committing the built SPA (`ui/static`)? | Convenient (no node at runtime) vs. a build artifact in git | Committed for now |
| 6 | Corner-map refreeze policy as data grows | Windows/identities freeze early for comparability; a deliberate rebuild command may be wanted later | Freeze-and-match; admissions surfaced |
| 7 | Cross-car reporting | Computed and stored but out of scope for v1 reports | Out of scope v1 |

---

## Risks & things worth knowing

- **The blind test is not yet proof.** Its expected answer (Spa Sector-1 entry
  commitment + entry inconsistency) is written in the spec I built from, so a
  pass is a smoke test against gross failure, not independent validation. It
  becomes real when data arrives whose answer I haven't seen. That the top
  findings already cluster on entry/mid consistency, unprompted, is encouraging
  but not conclusive.
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
python3 -m pytest                        # 315 tests (2026-07-20)
driverdna import tests/fixtures          # build the local DB from the fixtures
driverdna report                         # Markdown + JSON + self-contained HTML
driverdna corners | metrics | attribution   # per-milestone inspectable artifacts
driverdna ui                             # local cockpit at 127.0.0.1 (needs .[ui])
```

Coach/chat additionally need `ANTHROPIC_API_KEY`; `sync` needs `GARAGE61_TOKEN`
(both env-only).
