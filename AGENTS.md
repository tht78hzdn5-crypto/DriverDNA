# DriverDNA — build rules for every agent

This file is **binding** for every agent here — Claude Code, Gemini CLI,
Antigravity, anything else — and the single source of these rules. `CLAUDE.md`
imports it; `.agents/rules/driverdna.md` mirrors its non-negotiables;
`.gemini/settings.json` loads it. `tests/test_agent_contract.py` pins the
copies against drift.

Racing-telemetry instrument, **multi-user since A32** (2026-07-28; philosophy
#8 reversed by owner decision, real status in A51). The constitution (the
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

## Decision discipline (standing rule)

Record decisions (e.g., scoring forks, M7 adoption, threshold defaults) and reasons in durable docs at decision time:
- Log resolutions in `docs/SPEC.md` (amendment log) and/or `docs/PROJECT-BRIEF.md` (Decision log), dated.
- If touching the **nine philosophy points** or **out-of-scope list**, name the refined item and why (A14 is the model).
- `docs/STATUS.md` is the single dated snapshot for verified counts. Do not create other status/handoff docs.
- **Every real bug gets an entry in `docs/BUG-LOG.md`** — open or fixed, at the time you find it, including ones you fixed in the same session and ones you are leaving open. It is a defect register, not a status doc (that exemption is deliberate); it records what broke, why, blast radius, and **how it was caught or missed**, and cross-references the SPEC amendment rather than restating it. A bug is not fixed until a test pins it, or the entry says why none can.

## Build order (strict)

Do not begin a milestone until the prior milestone's done-criteria pass. Every
milestone ends with tests green AND its inspectable artifact generated from the
real fixtures and reviewed. No code may assume Garage61 API behavior before
`docs/garage61-api.md` documents it.

The M0a→M7 engine and U0→U6 UI chains are complete; `docs/SPEC.md` defines the
milestones, `CLAUDE.md`'s "Current status" says where the build stands, and
`docs/DEPLOY-SPEC.md` holds the open P/M/H tracks.

## Commands

- Install: `python3 -m pip install -e ".[dev]"`
- Test: `python3 -m pytest`
- Lint: `python3 -m ruff check .` (Python); `npm run lint` in `ui/` (SPA)
- CLI: `driverdna --help`
- Commands given to the owner (Windows shell) must be PowerShell-ready: full paths, no bash-only syntax (`&&`, `$(...)`, POSIX env vars). Use `;` to chain, `$env:NAME` for env vars.

## Testing rules

- Provider (coach/chat) tests use the mocked provider; tests never call live APIs or require secrets.
- Determinism test: run pipeline twice, byte-diff normalized JSON (sorted keys, fixed precision, no wall-clock timestamps).
- Fixture CSVs in `tests/fixtures/` anchor the source contract; synthetic traces cover landmark shapes and edge cases.
- API capabilities are documented from observed behavior (`docs/garage61-api.md`), never assumed.
- The suite stays runnable with `git clone && python3 -m pytest` (no secrets/server/container). Postgres tests run only if `DRIVERDNA_TEST_DATABASE_URL` is set; browser tests skip when Playwright/Chromium is absent.

## Development workflow (TDD)

New features/fixes use Red → Green → Refactor:
1. **Red:** Write failing test. Confirm it fails as expected and breaks nothing else.
2. **Green:** Write minimal code to pass. Do not edit test files here.
3. **Refactor:** Clean up code with all tests green.
Exempt: docs/config-only and unmerged spike work. Stops writing answer and rubric in one thought.

## Multi-agent working agreement

One agent works at a time. The rules below ensure cheap handoffs.

### Branches and merging

- **Every agent goes through a PR to `main` — no direct pushes, ever, no
  exceptions for urgency or a trivial diff** (owner instruction,
  2026-08-09, SPEC.md A47) — supersedes the 2026-07-21 direct-push rule.
  **Convention, not a platform gate: GitHub is not enforcing this.** A
  ruleset was blocked by a paid-plan restriction on private-repo Rulesets;
  classic branch protection is untried. Nothing stops a direct push, so the
  rule holds only because you follow it. Treat as blocking, though none
  mechanically are: `pytest (3.11)`, `pytest (3.12)`, `lint`,
  `browser-tests`, `secrets` (not `mypy`, advisory). Owner may push
  directly for a genuine hotfix; agents may not, ever.
  **Nothing is "done" until merged** (owner instruction, 2026-08-03) — end a
  session by landing its PR, or saying plainly why not.
- Branch naming: `gemini/<topic>`, `antigravity/<topic>`, `claude/<topic>`.
- **A red check won't block you — nothing will.** Fix it before the next
  commit anyway. If `main` is red, fix it before starting new work.

### Commit attribution

Every commit names the agent that wrote it. Use both trailers:
```
Agent: gemini-cli
Co-Authored-By: Gemini CLI <noreply@google.com>
# Similarly for: antigravity (Antigravity <noreply@google.com>), claude-code (Claude Opus 5 <noreply@anthropic.com>)
```

### Start of session — every agent, every time

1. `git pull` and read this file.
2. `git log --oneline -20` to see previous work.
3. Skim `docs/STATUS.md` "Verified counts" and `CLAUDE.md` "Current status".
4. Run `python3 -m pytest` before changing anything to establish a baseline. Never report it green blindly.

### End of session

- Update `docs/STATUS.md` and log decisions per "Decision discipline" above.
- Commit and push before the owner switches tools. Never leave local modifications unpushed.

### What CI does and does not cover

CI (`tests.yml`) runs five jobs on pushes/PRs, all merge gates except `mypy`:

1. **`pytest`** (3.11 + 3.12): the suite minus `-m browser`, with a Postgres service container; fails if Postgres tests skip from missing infra.
2. **`lint`**: `ruff check .` (Python) + `npm run lint` in `ui/` (SPA) — correctness rules only, no formatter (SPEC.md A47).
3. **`secrets`**: gitleaks, pinned binary + checksum, full git history.
4. **`browser-tests`** (3.12): installs Chromium, builds the SPA, runs every `pytest.mark.browser` test; fails if the skip guard still triggers.
5. **`mypy`** (advisory): ratchet against `ci/mypy-baseline.txt` — fails on a new finding, but can't block a merge.

### Working with the durable docs

- `docs/` is the project memory and outranks chat/transcripts/plans. Decisions must go in durable docs to count.
- Antigravity's Knowledge Base and plans are scratch and not committed.
- Reference rules; do not duplicate them except mirroring the non-negotiables block into `.agents/rules/driverdna.md`.

### Scope

All areas are open, but guardrails are off-limits:
- **Never weaken, delete, `skip`, `xfail`, or narrow a test to pass.** Record failures instead.
- **Never edit anything under `tests/fixtures/`**; change code to fit evidence.
- Changing engine **numbers** (metrics, default thresholds) needs a `docs/SPEC.md` amendment and model version bump.
- Never loosen the **grounding validator** (`coach/`, `chat/`) to pass a test.
- Investigate bugs; never implement fixes that contradict engine rules (e.g. filtering outliers).
- Propose major/architectural changes or history rewrites for explicit owner approval first.
- Reading laps to find engine gaps follows `docs/LAP-ANALYSIS-PROTOCOL.md` — observations only, every number quoted from the trace.
