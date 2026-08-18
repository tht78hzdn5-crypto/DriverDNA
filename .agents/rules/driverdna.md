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

If the task you were given is **reading laps to find gaps in the engine**
(rather than building something), it is governed by
`docs/LAP-ANALYSIS-PROTOCOL.md` — read Part 1 and follow it exactly. That
work produces observations only: no edits to `src/`, `tests/`, `docs/` or
`ui/`, no commits, and every number quoted from the trace so
`driverdna verify-observations` can check it.

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
- Multi-user since A32: every query on a partitioned table filters
  `owner_user_pk`, and `laps.driver` is a data label, never the tenant key.
- Secrets (`GARAGE61_TOKEN`, `ANTHROPIC_API_KEY`, `DRIVERDNA_DATABASE_URL`,
  `GEMINI_API_KEY`) are env-only: never persisted, printed, or logged. The
  database URL carries a password, so it is redacted before any connection error
  reaches a log or an HTTP body — and there is deliberately no bare
  `DATABASE_URL` fallback.
- Every threshold lives in config with a documented default; all parameter changes
  flow through ConfigStore, versioned and reversible.
- Nothing is silently repaired at ingest except pedal clipping to [0,1], which
  is quality-flagged with counts. Network/API errors (e.g. 404 vs 403) are
  categorized and surfaced, never swallowed.
- The UI renders what the engine computed and never computes a measurement:
  every on-screen number must exist in the JSON payload or a DB read endpoint.
- Secure by default: Never bypass auth/security requirements to unblock a deployment/test. Flag it instead.
- Driver-facing words live in the engine (`coaching/ontology.py`, `explain.py`, `DETECTOR_LABELS`, `Fundamental.label`), never hardcoded in the SPA. Internal slugs (`coast-window`, `cp.*`, finding IDs) are stable identities that evidence IDs and annotations key off — never rename one to improve wording; add or edit its label. Editing how coaching/feedback appear: see CLAUDE.md's coaching/feedback section.

- Verification discipline:
  1. A skipped test is not a pass. Check/report why tests skipped (missing Postgres/Chromium/SPA are gaps, not green results).
  2. Never build on a red CI branch. If a push/CI turns red, fix it before adding new commits.
  3. UI changes must be manually clicked. Load the page and run the flow (or use real browser tests) to verify frontend-backend parity.
  4. Never silently reverse a "not adopted" decision. Implementing a previously rejected/shelved plan requires a documented re-decision.
  5. Import shared constants in tests (e.g. route paths, config keys) instead of hand-copying them to prevent drift.
  6. "Tests pass" claims require a receipt: state the command, backend/environment used, and what skipped and why.
  7. Check other branches/migrations in flight to avoid duplicate/conflicting database schema changes.
  8. **Never assume a failure is synthetic.** A failing test, error, or wrong number is real until proven otherwise: investigate and state the evidence before concluding it was the test/fixture/environment. Unexplained red is an open bug, never background noise.
<!-- /shared:non-negotiables -->
