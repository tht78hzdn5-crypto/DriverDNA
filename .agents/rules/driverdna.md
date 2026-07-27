# DriverDNA — always-on rules

Set this rule to **Always On** in Antigravity's rules panel.

**Before your first edit in this repository, read `AGENTS.md` at the workspace
root, in full.** It is the binding, single source of the build rules — decision
discipline, build order, commands, testing rules, and the multi-agent working
agreement (branch naming, commit attribution, start/end-of-session steps).
This file carries only the hardest rules, so that they land even if that
reference is never followed.

Before touching the engine, also read `docs/ARCHITECTURE_VISION.md` (the *why*)
and `docs/SPEC.md` (the *how*, including the nine binding philosophy
principles).

Two rules from `AGENTS.md` that matter before you write anything:

- Work on an `antigravity/<topic>` branch, never directly on `main`, and merge
  only once CI is green.
- Run `python3 -m pytest` before changing anything, to establish a baseline.

The block below is mirrored verbatim from `AGENTS.md` and pinned byte-for-byte
by `tests/test_agent_contract.py`. Edit it in `AGENTS.md`, then copy it here —
never only here.

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
- Nothing is silently repaired at ingest except pedal clipping to [0,1], which is
  quality-flagged with counts.
- The UI renders what the engine computed and never computes a measurement:
  every on-screen number must exist in the JSON payload or a DB read endpoint.
<!-- /shared:non-negotiables -->
