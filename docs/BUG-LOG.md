# DriverDNA — Bug log

The defect register. One row per real bug: what broke, why, what it touched,
and **how it was caught or how it was missed**.

This is deliberately *not* another status doc. `docs/STATUS.md` stays the
single dated snapshot of verified counts (AGENTS.md); `docs/SPEC.md`'s
amendment log stays the record of decisions and their reasoning. This file
answers a different question — *what has actually been wrong with this
instrument, and would we catch it again* — and cross-references the amendment
that carries the full narrative rather than restating it.

## Why this file exists

A measurement instrument's credibility is the sum of its defects found. Most
of the entries below were **not** caught by the test suite: they were caught
by running the thing on real data, by a live API call, or by a human reading
output that looked plausible. Several were missed by tests that existed,
passed honestly, and were pinned one layer above where the bug actually was.
Writing that down is the point.

## Conventions

- **ID**: `BUG-nnn`, assigned in order of *discovery*, never reused.
- **Status**: `open` · `fixed` · `mitigated` (real fix deferred, exposure
  reduced) · `wontfix` (with a reason).
- **Severity**: `silent-wrong` (produced a wrong number or claim without
  saying so — the worst class in this product) · `breaks` (fails loudly) ·
  `security` · `data-loss` · `cosmetic`.
- Every entry names **how it was caught**. If a test caught it, say which. If
  nothing did, say that plainly — that gap is the useful information.
- A bug is not fixed until a test pins it. If no test can, say why.
- Filing one is a data change, like adding a config threshold: cheap, and
  never a judgement on whoever wrote the code.

---

## Open

### BUG-018 — Service unreachable on the Oracle VM (Cloudflare 1033)
- **Status**: open · **Severity**: breaks · **Found**: 2026-08-08
- **Symptom**: `driver-dna.com` returns Cloudflare error 1033. Persisted after
  a service restart following `pip install .[dev]` against the live venv.
- **Root cause**: unknown. Not diagnosed — `journalctl -u driverdna -n 100
  --no-pager` has not been run since.
- **Blast radius**: the deployed instrument is down. Local and test paths
  unaffected.
- **How it was caught**: owner-visible outage.
- **Next step**: capture the unit's journal before theorising. Candidate
  suspects (unverified): the `pip install` shifting a dependency the unit
  needs, or the interlock in `driverdna ui` refusing to start — A41 made a
  missing passphrase fail closed, which is a *correct* refusal that presents
  as a dead port.

### BUG-019 — Test suite fails on ARM64, passes on x86
- **Status**: open · **Severity**: breaks · **Found**: 2026-08-08
- **Symptom**: `pytest` on the Ampere A1 VM shows `F` markers at roughly 15%,
  31% and 38% of the run. Same commit is green on x86.
- **Root cause**: unknown — tracebacks were never captured.
- **Blast radius**: unknown, and that is the problem. Until the failures are
  read, it is not known whether this is an environment artifact or a real
  architecture-dependent defect in float/collation/ordering behaviour. This
  product's numbers are float-sensitive (see BUG-006), so it must not be
  assumed cosmetic.
- **How it was caught**: running the suite on the target platform — something
  x86 CI cannot do.
- **Next step**: `python3 -m pytest --tb=short 2>&1 | tee pytest-arm64.txt`
  on the VM. Do not theorise before reading it.

### BUG-013b — Cohorts founded by a reference lap keep stranger-built geometry
- **Status**: mitigated · **Severity**: silent-wrong · **Found**: 2026-08-03 (A34)
- **Symptom**: residue of BUG-013. A34's refusal guards *new* imports; a cohort
  whose map was already founded or shifted by a reference lap keeps that
  geometry.
- **Blast radius**: none in this repo (both fixture manifests hold zero
  reference laps, and 7/7 committed reports were byte-identical after the fix)
  — but unknown in the owner's production store.
- **Mitigation**: `driverdna rebuild-map` is the recovery path, and after A34
  its refreeze queries are self-only.
- **Open part**: nothing *detects* an affected cohort, so nobody knows to run
  the recovery. A check comparing a cohort's map provenance against its
  role-filtered lap set would close it.

---

## Fixed

Newest first. The amendment named in each entry carries the full narrative.

### BUG-020 — Committed artifacts could drift from what the code regenerates
- **Status**: fixed 2026-08-09 · **Severity**: silent-wrong · **SPEC**: A46 (found), fix in `tests/test_artifact_freshness.py`
- **Symptom**: `docs/coaching-report.md`, `driver.*` and
  `gr86-spa-francorchamps.*` sat stale for days across two merges. They are
  committed as regression anchors and read as current, by humans and agents.
- **Root cause**: A42 (`coach-onto-v2` CV renormalization) and A43 (census in
  the driver payload) each changed numbers those files contain without
  regenerating them. Nothing failed when they drifted.
- **Blast radius**: anyone reading a committed report got pre-A42 consistency
  numbers. The A46 session initially misread the staleness as its own
  regression and had to regenerate on a clean checkout to prove otherwise —
  the cost of the missing guard was paid in doubt, not just wrong data.
- **How it was caught**: by hand, during A46's number-neutrality check.
- **Fix**: `tests/test_artifact_freshness.py` regenerates all fourteen
  committed artifacts from `tests/fixtures/` into a temp dir and
  byte-compares. One shared fixture import, ~8 s, no secrets or browser.
  A failure names the first differing line and quotes the exact regeneration
  command. Three things make it more than a green tick:
  - `test_the_guard_covers_every_committed_docs_report` fails if a new
    `docs/*-report.md` is committed without being added to the table — the
    same drift, one level up.
  - `test_the_guard_would_catch_a_stale_artifact` mutates one digit of a real
    artifact and asserts rejection (the
    `test_crawler_would_catch_an_invented_number` precedent).
  - Proven end-to-end before commit by changing a real engine string
    (`PHASE_LABELS["exit"]`) and confirming it named exactly the three
    affected artifacts, then reverting.
- **Verified, not assumed, before adopting a strict byte-compare**: all
  fourteen regenerate byte-identical under both CI matrix versions (3.11 and
  3.12) and across two numpy majors. If it ever fails for a platform reason
  — a numpy release moving a last decimal, or BUG-019's ARM64 divergence —
  that is a finding, not noise. Investigate; never loosen it to go green.
- **Found while building the guard**: `driverdna corners` prints the
  fixtures directory it was handed into its own report header, so
  `docs/corners-report.md` is **cwd-dependent** — only the documented
  invocation from the repo root reproduces the committed bytes. The test now
  pins that invocation. Not otherwise fixed: relativising the header would
  itself change a committed artifact, which belongs in its own change.

### BUG-021 — The methodology-id guard did not see hook-referenced ids
- **Status**: fixed 2026-08-09 · **Severity**: silent-wrong
- **Symptom**: `test_every_jsx_methodology_id_reference_exists` matched only
  `<Methodology id="...">`. Ids reached through `useMethodologyText("...")`
  were invisible to it — the four in `SourceLegend`, plus every
  `incident.*` id — so a typo in one would render as **nothing** in the
  browser with the whole suite still green. That is precisely the failure the
  test's own docstring says it exists to prevent.
- **Root cause**: the guard was written when `<Methodology>` was the only way
  to name an id. `useMethodologyText` was extracted later as a public hook
  (for `IncidentCard`'s inline empathy line) and the guard was never widened
  to follow it. A46 then added four more references through the hook.
- **Blast radius**: no live typo — all eleven hook-referenced ids resolve. The
  exposure was the missing guard, not a wrong string on screen.
- **How it was caught**: reading the test to confirm a claim before writing it
  into `CLAUDE.md`. Nothing failed; the gap was only visible in the regex.
- **Fix**: the pattern matches both forms, and an assertion pins that the hook
  form is still reachable so the guard cannot silently narrow again.
  Template-literal ids (`incident.${cls}`) *cannot* be checked statically, so
  two new tests cover them dynamically instead: every classification
  `classify.py` can emit has an `incident.<cls>` explanation, and empathy text
  exists for exactly the mechanisms the engine names a cause for — the
  deliberate absence on `unclassified`/`external` is now pinned as a decision
  rather than looking like an oversight.
- **Lesson**: a guard is only as wide as the syntax it happened to be written
  against. When you add a second way to do the thing a test protects, widen
  the test in the same commit.

### BUG-017 — A detector's per-lap rationale was printed as the corner's figure
- **Status**: fixed 2026-08-09 · **Severity**: silent-wrong · **SPEC**: A46
- **Root cause**: `vs_principle_findings` built its description as
  `f"...{rationale}"` where `rationale = rows[0]["rationale"]` — the **first
  triggering lap's** value. "3.63 s with neither pedal" read as the corner's
  characteristic, not one observation's.
- **Fix**: description is a summary; the rationale moved to
  `details["rationale"]` and renders behind the evidence disclosure, labelled
  as one lap.
- **How it was caught**: reading the string while rewriting it for
  readability. No test asserted anything about it, and none could have — the
  sentence was true, just about the wrong scope.

### BUG-016 — Postgres blob roots collided on the URL's last path segment
- **Status**: fixed 2026-08-06 · **Severity**: data-loss · **SPEC**: A45
- **Root cause**: `default_blob_root` keyed a DSN's blob directory on the last
  URL path segment. Two projects whose path ends `/postgres` — the Supabase
  default — shared one blob root.
- **Fix**: key on `SHA-256(DSN)[:16]`.
- **How it was caught**: source review, not a failure. Lower urgency after
  Supabase was retired, but live in the Postgres backend either way.

### BUG-015 — Google sign-in did not invalidate a prior session
- **Status**: fixed 2026-08-06 · **Severity**: security · **SPEC**: A45
- **Root cause**: `google_callback` did not bump `session_epoch` for existing
  users; the password login path always did. An old cookie stayed valid.
- **How it was caught**: comparing the two auth paths against each other.

### BUG-014 — `--db ""` silently opened an evaporating temp database
- **Status**: fixed 2026-08-05 · **Severity**: silent-wrong · **SPEC**: A41
- **Root cause**: an unset deploy secret passed `--db ""`, which SQLite
  accepts as "private temporary database". Every write went to a store that
  vanished on restart.
- **Blast radius**: presented as a sign-in bounce. **Four prior sessions tried
  to fix it by editing auth code** — the auth layer was innocent.
- **Fix**: `resolve_store("")` raises; the ephemeral session-secret fallback
  is retired and the interlock fails closed; `/health` reports `store`/`auth`.
- **How it was caught**: a session that stopped editing the suspected
  component and read the actual deploy configuration.
- **Lesson**: a symptom in layer A is not evidence of a bug in layer A.

### BUG-013 — Reference laps defined the driver's own corner geometry
- **Status**: fixed 2026-08-03 · **Severity**: silent-wrong · **SPEC**: A34
- **Root cause**: role isolation was enforced in the measurement layer but not
  in the **coordinate system** those measurements are taken in. Three paths
  wrote reference geometry into the corner map: founding (first lap in a
  cohort builds the map, role unchecked), admission (reference laps counted
  toward `min_laps_for_admission` and fed the new centroid), and rebuild
  (A22's refreeze read tables that did not even join `laps`).
- **Blast radius**, measured on the real GT4 cohort: **11 of 14 corners moved**
  (largest 46.94 m), 11 of 14 windows differed, **154 of 191 phase times
  changed** by up to 1.57 s.
- **How it was missed**: `test_reference_import_perturbs_gap_sections_only`
  existed, passed, and **was pinned one layer above the break** — its
  synthetic reference lap matched existing corners, so the admission path
  never ran and it never rebuilt. An audit for an unfiltered `JOIN laps`
  also missed it, because the offending queries did not join `laps` at all.
- **How it was caught**: the owner supplied real reference laps, so the
  vs-reference path ran on real data for the first time.

### BUG-012 — Upload endpoint hardcoded `driver="owner"` regardless of role
- **Status**: fixed 2026-08-03 · **Severity**: silent-wrong · **SPEC**: A39
- **Root cause**: `POST /api/laps/upload` stamped every upload as the owner,
  so a reference lap imported through the browser lost its contributor
  identity.
- **How it was caught**: building R2, which made the `driver` column
  load-bearing for the first time.

### BUG-011 — Coach token ceiling silently starved the thinking-model provider
- **Status**: fixed 2026-08-02 · **Severity**: breaks · **SPEC**: A38
- **Root cause**: `coach.max_tokens` defaulted to 4000, spent on reasoning
  before any output existed. Two prompt ambiguities in the coach system prompt
  were also hit reliably (`coach-v2`→`coach-v3`, wording only).
- **How it was caught**: **a real live API run.** Every provider test is
  mocked by policy, and mocks cannot surface a token ceiling. Nothing else
  would have found this.

### BUG-010 — Every deployed `/api` route was unauthenticated
- **Status**: fixed 2026-07-27 · **Severity**: security · **SPEC**: A31
- **Root cause**: DEPLOY-SPEC track H1 (single-driver auth) was adopted
  2026-07-26 and never built, while the Cloud Run deploy shipped anyway. The
  live service was protected by nothing but
  `--no-allow-unauthenticated`.
- **Fix**: one app-level FastAPI dependency guarding every route, plus a
  done-criterion test that enumerates `app.routes` so a future endpoint is
  guarded by default.
- **How it was caught**: reconciling what the deploy spec said was done
  against what was actually in the code.

### BUG-009 — A negative capability claim was an inference presented as fact
- **Status**: fixed 2026-07-27 · **Severity**: silent-wrong · **SPEC**: A28
- **Root cause**: M0b concluded `/laps` caps at ~1 saved lap per driver per
  cohort. The census was accurate; the conclusion was not — it was `group`'s
  default (`driver` = PB per driver; `group=none` = all laps). The wrong
  premise silently shaped three later decisions.
- **How it was caught**: reading `https://garage61.net/api/openapi/v1.json` —
  the spec the "unreachable" JS developer portal fetches for itself, its URL a
  plain string in the SPA bundle.
- **Lesson, standing**: when a docs site will not render, read its client
  before declaring the documentation unavailable; a negative capability claim
  needs a source, not a probe inference.

### BUG-008 — Cohort labels drift between `sync` and manual import
- **Status**: fixed (detection only) 2026-07-26 · **Severity**: silent-wrong · **SPEC**: A27
- **Root cause**: `sync` labels a track `"Name (Variant)"` from the API;
  manual import uses the filename's bare name. Doing both splits one cohort in
  two, silently halving the evidence behind every baseline, trend and
  consistency number.
- **Fix**: `cohorts.find_label_drift` flags it in `history` and at the end of
  `import`. **Reported, never auto-merged** — the right label is not derivable
  from the strings, and cohort keys are load-bearing for evidence IDs.
- **How it was caught**: reasoning about what happens when both ingest paths
  are used on one car/track.

### BUG-007 — Re-download suffix assumed a space that was never observed
- **Status**: fixed 2026-07-26 · **Severity**: breaks · **SPEC**: A24 → A25
- **Root cause**: A24 stripped a browser re-download's `" (1)"` assuming a
  leading space. The owner's next real Windows re-download produced
  `...(1).csv` with **no space**, and the parser rejected it — the same error
  A24 existed to close.
- **How it was caught**: the owner hit it.
- **Lesson**: A24 itself warned against unverified guesses presented as
  observations, and then made one. Only the no-space spelling is confirmed
  against a real file.

### BUG-006 — Two silent-corruption risks in the Postgres move
- **Status**: fixed 2026-07-26 · **Severity**: silent-wrong · **SPEC**: A23
- **Root cause**: (a) Postgres `REAL` is float4 and would have **truncated
  every metric**; (b) Supabase's `en_US.UTF-8` collation would have
  **reordered every report**.
- **Fix**: `REAL`→`DOUBLE PRECISION`, and every text column `COLLATE "C"`.
  Equivalence is tested, not claimed: the same corpus in either backend
  produces byte-identical artifacts.
- **How it was caught**: reading the dialect differences before trusting them.
  Neither would have failed loudly. Four further latent bugs were found on the
  same pass.

### BUG-005 — `rebuild-map` destroyed recoverable phase times
- **Status**: fixed 2026-07-26 · **Severity**: data-loss · **SPEC**: A26
- **Root cause**: after blobs moved to local disk, an unreadable trace meant
  either "evicted here" (gone) or "imported on another machine" (intact
  there). `rebuild_cohort_map` treated both as eviction: `delete_phase_times`
  plus a report blaming retention.
- **Fix**: eviction writes a tombstone in the **blob store** (per-machine, not
  a DB column — the store may be shared); a pre-flight raises
  `RawTracesUnavailable` before touching anything.
- **How it was caught**: reasoning about the multi-machine case A23 had just
  created.

### BUG-004 — `same_lap_twice` pooled CVs across metric types
- **Status**: fixed 2026-08-06 · **Severity**: silent-wrong · **SPEC**: A42
- **Root cause**: the same defect as BUG-003, one layer down, in
  `coaching/engine.py`'s gate. Five "% lap" metrics with tiny natural CVs
  diluted one "count" metric's genuine signal under a flat mean.
- **How it was caught**: BUG-003 was flagged at the time as probably recurring
  here. It did.

### BUG-003 — `consistency` scoring pooled CVs across metric types
- **Status**: fixed 2026-07-21 · **Severity**: silent-wrong · **SPEC**: A21
- **Root cause**: a "% lap" metric's naturally tiny CV (~0.007) against a
  "count" metric's naturally huge one (~0.99), flat-averaged — so the pooled
  figure tracked which metric types a corner had, not how consistent the
  driver was.
- **Blast radius**: `consistency` 5.1 → 34.3; `commitment`, inflated the
  *other* way by the same mechanism, 96.5 → 56.1. `dm-v1` → `dm-v2`.
- **How it was caught**: investigating a "Known v1 limitation" note — **whose
  own stated diagnosis was wrong.** The note blamed cross-cohort raw-magnitude
  pooling; each CV was already per-cohort. Fixing the documented cause would
  have changed nothing.
- **Lesson**: a recorded diagnosis is a hypothesis, not a finding.

### BUG-002 — ConfigStore's TOML writer emitted invalid TOML for dict values
- **Status**: fixed 2026-07-21 · **Severity**: breaks · **SPEC**: A21
- **Root cause**: the hand-rolled writer had no dict-value branch and fell
  through to Python `repr()`.
- **How it was caught**: incidentally — A21 introduced the first dict-valued
  config field, so the path had never executed.

### BUG-001 — One incident lap inflated vs-self opportunity
- **Status**: fixed 2026-07-21 · **Severity**: silent-wrong · **SPEC**: A18
- **Root cause**: `vs_self_findings` screened outliers out of the *baseline*
  but not out of the fast/slow tercile split, so a single spin manufactured a
  phantom "opportunity" — ~2.5× at one corner.
- **Fix**: reuse `baseline()`'s own median±k·MAD fence at the same
  per-corner-phase granularity, before the split. The raw observation still
  counts in `n` and `evidence_ids`; only the computed figures exclude it.
- **How it was caught**: the **Spa blind acceptance test** on 11 real,
  independent laps. The same run also retracted the spec's original ground
  truth, which had never been engine-corroborated on any dataset.
- **Lesson**: this is the entry that justifies the whole practice of running
  the instrument blind against real laps.

---

## Patterns worth not repeating

Read as a set, the entries above cluster:

1. **The guard was pinned one layer above the break** (BUG-013, and BUG-017 in
   a softer form). A passing test proves what it asserts, not what it is named
   after. When a guarantee spans layers, test it at the lowest one.
2. **A recorded diagnosis got trusted as a finding** (BUG-003, BUG-009,
   BUG-007). This repo's docs are unusually good, which makes their occasional
   wrong claims unusually dangerous. Re-derive before fixing.
3. **Mocks cannot find what only reality has** (BUG-011, BUG-001, BUG-007).
   The provider tests are mocked by policy and should stay so — but "all
   green" and "it works" are different claims.
4. **A symptom's location is not the bug's location** (BUG-014). Four sessions
   edited auth code for a database-configuration bug.
5. **Adopted-but-not-built is a live exposure** (BUG-010, BUG-020). A decision
   in a spec does not defend anything.
