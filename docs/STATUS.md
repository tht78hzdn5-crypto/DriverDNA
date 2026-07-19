# DriverDNA — Status & Decision Log

Point-in-time snapshot, 2026-07-19. Branch `claude/plan-review-philosophy-hl3cdg`
(20 commits). Authoritative spec: `docs/SPEC.md`; UI spec: `docs/UI-SPEC.md`.
This document is a snapshot — the spec and its amendment log remain the binding
record.

**One line:** the deterministic engine (M0a–M5) and the UI foundation (U0 API,
U1 read views + render-parity gate) are complete and verified; 313 tests green;
11 real Spa laps now produce 17 live, gated findings. The build is waiting on
laps and two API keys, not on code.

---

## Where we are

### Engine — complete (M0a–M5)

| Milestone | What it does | State |
|---|---|---|
| M0a | Contract lock: schema + absence tests on real fixtures | done |
| M1 | Parse → segment → freeze corner identity → classify | done |
| M2 | 18 metrics + 5 principle detectors + SQLite persistence | done |
| M3 | Attribution over canonical windows, robust baselines, ranker, gates | done |
| M4 | Reports (MD/JSON/HTML) + one-shot coach with local validation | done |
| M5 | Grounded chat: tools, annotations, staged config, mechanical grounding | done |
| M0b | Garage61 API probe + `sync` | **blocked on `GARAGE61_TOKEN`** |

### UI — foundation complete (U0–U1)

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
1. **U3 — the chat view.** Wire `ChatSession` into the UI: SSE progress states,
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

- **M0b + `sync`** the moment a `GARAGE61_TOKEN` exists — ends manual CSV
  uploads (the biggest phone-first win). Nothing is built assuming API behavior
  until the probe documents it.
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

**UI**
- The normalized JSON payload is the rendering contract; the UI never computes a
  measurement (mechanically enforced by the render-parity crawler).
- Owner amendment: U0/U1 built ahead of the blind acceptance test for momentum;
  U2–U4 keep the original gate (revisit when reached).

**Working practice**
- Secrets are env-only, never committed. Every threshold lives in config with a
  documented default. Every milestone ships an inspectable artifact. Commit +
  push after each coherent unit.

---

## Decisions we still need to make

| # | Decision | Why it matters | Current default |
|---|---|---|---|
| 1 | Provide `GARAGE61_TOKEN`? | Unblocks `sync` — automatic lap ingest, no manual uploads | Deferred; manual import works |
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
python3 -m pytest                        # 313 tests
driverdna import tests/fixtures          # build the local DB from the fixtures
driverdna report                         # Markdown + JSON + self-contained HTML
driverdna corners | metrics | attribution   # per-milestone inspectable artifacts
driverdna ui                             # local cockpit at 127.0.0.1 (needs .[ui])
```

Coach/chat additionally need `ANTHROPIC_API_KEY`; `sync` needs `GARAGE61_TOKEN`
(both env-only).
