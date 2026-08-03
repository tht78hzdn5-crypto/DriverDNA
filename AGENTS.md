# DriverDNA — build rules for every agent

This file is **binding** for every agent working on this repository — Claude
Code, Gemini CLI, Antigravity, or anything else — and the single source of
these rules. `CLAUDE.md` imports it; `.agents/rules/driverdna.md` mirrors its
non-negotiables for Antigravity; `.gemini/settings.json` loads it for Gemini
CLI. `tests/test_agent_contract.py` keeps those copies from drifting.

Personal racing-telemetry instrument for one driver. The constitution (the
*why*) is **docs/ARCHITECTURE_VISION.md**: DriverDNA measures the driver, not
the lap — the persistent Driver Model is the product. The engine spec (the
*how*) is **docs/SPEC.md** — read both before changing anything. The philosophy
(nine principles, owner-confirmed, refined by A14) lives in `docs/SPEC.md`
§Philosophy and is binding; when in doubt, the constitution wins over
convenience.

<!-- shared:non-negotiables -->
## Non-negotiables

- The deterministic engine is the only source of numbers, **including scores**.
  AI (coach/chat) explains scores and prioritizes practice; it never produces or
  adjusts a number.
- Sources stay separately inspectable. Composite **scores are allowed but only
  deterministic, versioned, and confidence-qualified** — Score + Confidence +
  Evidence Count, always decomposable to the sources; never opaque, never
  AI-generated (A14 / ARCHITECTURE_VISION.md).
- "Insufficient data" over guessing, always. Every finding carries N, spread,
  source tag, and evidence IDs.
- Reference laps never enter self history, trends, or consistency statistics.
- Secrets (`GARAGE61_TOKEN`, `ANTHROPIC_API_KEY`, `DRIVERDNA_DATABASE_URL`,
  `GEMINI_API_KEY`) are env-only: never persisted, printed, or logged. The
  database URL carries a password, so it is redacted before any connection error
  reaches a message, a log, or an HTTP body — and there is deliberately no bare
  `DATABASE_URL` fallback.
- Every threshold lives in config with a documented default; all parameter changes
  flow through ConfigStore, versioned and reversible.
- Nothing is silently repaired at ingest except pedal clipping to [0,1], which
  is quality-flagged with counts. Network/API errors (e.g. 404 vs 403) are
  categorized and surfaced, never swallowed.
- The UI renders what the engine computed and never computes a measurement:
  every on-screen number must exist in the JSON payload or a DB read endpoint.
- Secure by default: Never bypass auth/security requirements to unblock a deployment/test. Flag it instead.
<!-- /shared:non-negotiables -->

## Decision discipline (standing rule)

When a decision is made — especially one an agent surfaced as a fork (scoring
approach, M7 adoption, a threshold default) — the pick **and its reason** are
recorded in the durable docs at decision time, never left only in chat:

- The resolution goes in `docs/SPEC.md` (amendment log) and/or
  `docs/PROJECT-BRIEF.md` (Decision log), dated.
- If the decision touches the **nine philosophy points** or the **out-of-scope
  list**, the record must *name the principle or item it refines and why*, in
  the same edit — flagged at decision time, not left to be caught later. A14
  (scores refine philosophy #4) is the model.
- `docs/STATUS.md` is the single dated snapshot; verified counts (tests, laps,
  sessions, findings, commits) live there so they can be checked over time.
  Do not create a second status or handoff document — this is the one.

## Build order (strict)

Do not begin a milestone until the prior milestone's done-criteria pass. Every
milestone ends with tests green AND its inspectable artifact generated from the
real fixtures and reviewed. No code may assume Garage61 API behavior before
`docs/garage61-api.md` documents it.

The M0a→M7 engine chain and the U0→U6 UI chain are both complete; `docs/SPEC.md`
defines the milestones, `CLAUDE.md`'s "Current status" says where the build
actually stands, and `docs/DEPLOY-SPEC.md` holds the open P/M/H tracks.

## Commands

- Install: `python3 -m pip install -e ".[dev]"`
- Test: `python3 -m pytest`
- CLI: `driverdna --help`
- The owner runs the CLI from a local Windows shell. Any command block given to
  them must be PowerShell-ready: full paths (not relative to some assumed cwd),
  and no bash-only syntax (`&&` chaining, `$(...)`, POSIX env-var syntax).
  `;` chains commands in PowerShell; `$env:NAME` reads/sets an env var.

## Testing rules

- Provider (coach/chat) tests use the mocked provider only; tests never call live
  APIs and never require secrets.
- Determinism is tested mechanically: run the pipeline twice, byte-diff the
  normalized JSON (sorted keys, fixed float precision, no wall-clock timestamps).
- The fixture CSVs in `tests/fixtures/` are the regression anchor for the source
  contract; synthetic traces cover landmark shapes, double-apex handling, and
  detector edge cases.
- API capabilities are documented from observed behavior (docs/garage61-api.md),
  never assumed.
- The suite stays runnable with `git clone && python3 -m pytest` — no secrets,
  no server, no container. Postgres tests activate only when
  `DRIVERDNA_TEST_DATABASE_URL` points at a *local* instance; browser tests
  skip when Playwright or Chromium is absent.

## Development workflow (TDD)

New features and bug fixes follow Red → Green → Refactor:

1. **Red:** write a failing test first. Run the suite; confirm it fails for
   the expected reason and nothing existing broke.
2. **Green:** write minimum code to pass. Never modify test files in this
   step — fix the test in Red first, then return to Green.
3. **Refactor:** clean up with all tests green.

Exempt: docs-only, config-only, and unmerged spike work. This stops an agent
from writing both the answer and the grading rubric in one thought.

## Multi-agent working agreement

More than one agent works on this repository, one at a time (usually because the
owner hit a usage limit on another). The rules below make a handoff in either
direction cheap, so no agent has to guess what the last one did.

### Branches and merging

- **Claude Code commits directly to `main`** (owner instruction, 2026-07-21).
  **Nothing is "done" until merged** (owner instruction, 2026-08-03) — end a
  session by merging to `main`, or saying plainly why not.
- **Every other agent works on a prefixed branch** and merges to `main` only
  after CI is green: `gemini/<topic>` for Gemini CLI, `antigravity/<topic>` for
  Antigravity.
- Known property, not an oversight: CI gates *merges*, so a direct push to
  `main` can still break it, and a branch cut afterwards inherits the breakage.
  Push-triggered CI surfaces that within a minute rather than preventing it.
  If `main` is red, fix it before starting new work.

### Commit attribution

Every commit names the agent that wrote it, so `git log` alone answers "who did
this and when". Use both trailers — `Agent:` is the machine-readable one
(`git log --grep='^Agent: gemini-cli'` is exact), `Co-Authored-By:` keeps
GitHub's attribution working:

```
Agent: gemini-cli
Co-Authored-By: Gemini CLI <noreply@google.com>

Agent: antigravity
Co-Authored-By: Antigravity <noreply@google.com>

Agent: claude-code
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

### Start of session — every agent, every time

1. `git pull`
2. Read this file.
3. `git log --oneline -20` — see what the previous agent did.
4. Skim `docs/STATUS.md` "Verified counts" and `CLAUDE.md` "Current status".
5. Run `python3 -m pytest` **before changing anything**, to establish a
   baseline. Read the output; never blindly report it green — a suite that
   was already red is not yours to be surprised by later.

### End of session

- Update `docs/STATUS.md`'s dated snapshot.
- Record any decision per "Decision discipline" above — `docs/SPEC.md`
  amendment log (next `A<n>`) and/or `docs/PROJECT-BRIEF.md` decision log,
  dated.
- Commit and push before the owner switches tools. **Two agents on one working
  tree is the one failure mode no test can catch.**

### What CI does and does not cover

`.github/workflows/tests.yml` runs the full suite on every push and on PRs to
`main`, across Python 3.11 and 3.12, with a Postgres service container so the
dual-backend tests actually execute — and a step fails the job if any test
skipped for "no local Postgres configured", so a container that never came up
cannot leave the A23 guards silently unrun. Rationale: the workflow's comments.

It does **not** install Chromium, so the two UI-SPEC trust-gate tests
(`tests/test_render_parity.py`, `tests/test_offline.py`) skip in CI — the
owner's to run locally. Deliberate (a gate red by default gets ignored), but it
means **green CI is not proof the browser trust gates hold**. Say so rather
than implying full coverage.

### Working with the durable docs

- `docs/` is the project's memory and outranks anything in a chat transcript,
  a tool's own "knowledge base", or a generated plan artifact. **If a
  decision matters, it goes in the durable docs or it did not happen.**
- Antigravity's Knowledge Base and generated artifacts (task lists, plans,
  walkthroughs) are scratch, not project truth, and are not committed.
- Do not restate this file's rules elsewhere — reference it. The one
  exception is the non-negotiables block mirrored into
  `.agents/rules/driverdna.md`, pinned byte-for-byte by
  `tests/test_agent_contract.py`.

### Scope

No area is off-limits to any agent — engine, AI layer, UI, docs. The
guardrails are the constitution, the test suite, and CI, not a file list.
That's exactly why the guardrails themselves are off-limits:

- **Never weaken, delete, `skip`, `xfail`, or narrow an existing test to get
  to green.** A failing test is a finding — record it and say so. Silencing
  it converts a real defect into a false all-clear, and every downstream gate
  starts lying.
- **Never edit anything under `tests/fixtures/`.** Those are real recorded
  laps, the regression anchor for the source contract and the A18 blind
  acceptance test. Change the code to fit the evidence, never the reverse.
- Changing a **number** the engine produces (a metric, score, or threshold
  default) is a spec-level change: a `docs/SPEC.md` amendment, plus a model
  version bump if the formula or weights move — never a quiet edit.
- Changing the **grounding validator** (`coach/`, `chat/`) is the
  highest-risk edit here. Its job is making "AI never produces a number"
  mechanical, not requested — loosening it to pass a test defeats the point.
- **Investigate bug reports.** Cross-reference UI reports against `docs/SPEC.md`
  and engine payloads. Never implement a "fix" that contradicts engine rules
  (e.g. filtering outliers).
- **Propose major changes.** Architectural changes (e.g. collapsing services)
  or destructive operations (history rewrites) need explicit owner approval
  first.
