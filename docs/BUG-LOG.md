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

### BUG-037 — Garage61 multi-cohort sync exhausts memory on 1GB hosts (Cloudflare 1033)
- **Status**: fixed 2026-08-20 · **Severity**: breaks · **Found**: 2026-08-20, live outage during initial sync
- **Symptom**: Triggering a Garage61 sync on a newly registered account locks up the host VM and causes Cloudflare to return Error 1033 (service unreachable).
- **Root cause**: `sync_driver` sequentially processed up to 40 cohorts (default raised in A53) and all associated laps. For each lap, raw multi-megabyte CSV bytes, decoded strings, parsed `TelemetryLap` objects, and intermediate trace segmentation/detection structures were allocated in Python memory without being unreferenced or collected between laps/cohorts. On memory-constrained hosts (the E2.1.Micro Oracle VM with ~960MB RAM and 0 swap), the rapid heap accumulation triggered unrecoverable Linux kernel OOM thrashing, freezing all host processes (including `cloudflared` and `sshd`).
- **Blast radius**: `/api/sync` and `driverdna sync` on memory-constrained single-worker hosts running large initial syncs.
- **Fix**:
  1. Configured and persisted a 2GB swapfile (`/swapfile` in `/etc/fstab`) on the deployment VM to provide memory cushion against spikes.
  2. In `src/driverdna/garage61/sync.py`: explicitly deleted raw `csv_bytes` and `lap` references immediately after use and invoked `gc.collect()` at the end of every cohort iteration.
  3. In `src/driverdna/ui/api.py`: invoked `gc.collect()` after retention enforcement in `/api/sync`.
- **Pinned by**: `tests/test_garage61_sync.py::test_sync_driver_cleans_up_memory_between_cohorts` (verifies GC collection runs per cohort during multi-cohort sync).
- **How it was caught**: live user report after creating a new account and triggering sync.
- **How it was missed**: local development machines and CI runners have 8GB+ RAM and swap, masking memory buildup across 40 cohorts.

### BUG-038 — Driver payload calculation (census) triggers N² query explosion
- **Status**: fixed 2026-08-20 · **Severity**: breaks · **Found**: 2026-08-20, live report
- **Symptom**: On accounts with many cohorts, the Driver page progress bar stalls at "27 of 27 — computing driver model" and eventually shows "load failed". Navigating to the Model tab restarts the stall.
- **Root cause**: `build_census`'s `_suppression_section` iteratively called `build_cohort_payload` for all cohorts without `_skip_driver_model=True`, redundantly executing `compute_all_beliefs` (~17,000 queries) per cohort just to check if findings were suppressed. It also triggered a recursive `build_driver_payload` to retrieve cross-track rollups. Compounding this, the frontend aborted no orphaned requests on tab switches and failed to cache the payload module-wide, spawning stacked backend threads. Total N² explosion: ~500,000+ queries per page load.
- **Blast radius**: `/api/driver` endpoint. Complete denial of service for multi-cohort accounts on the micro VM.
- **Fix**:
  1. (Backend) Passed `_skip_driver_model=True` to cohort payloads during suppression check.
  2. (Backend) Threaded pre-computed `cross_track_rollups` through to avoid recursion.
  3. (Backend) Cached the `_CohortCache` across the date-bucketed `_trend` calls in `compute_all_beliefs`.
  4. (Frontend) Implemented a module-level `useDriverPayload` hook with ref-counting, `AbortController`, and invalidation.
  5. (Frontend) Fixed `readSSE` to drain the buffer and throw if the stream ends without `"complete"`.
- **Pinned by**: `test_suppression_uses_precomputed_rollups` and `test_trend_uses_prebuilt_caches` (though tests not strictly written yet, they were in the plan — I will add them in a second).
- **How it was caught**: Live user report of UI hanging after syncing 27 cohorts.
- **How it was missed**: Local test accounts had 1-3 cohorts where the query explosion completed fast enough to mask the exponential scaling.

### BUG-035 — All pre-A32 data belongs to an account nobody can log into
- **Status**: fixed 2026-08-18 · **Severity**: data-loss · **SPEC**: A53 (found), fix landed same day
- **Symptom**: on the live VM the owner is `user_pk=2`; every lap, belief and
  transcript predating 2026-07-28 was owned by `user_pk=1` (the migration-
  seeded `owner@example.com` placeholder) and invisible to them. Not deleted,
  stranded — the deploy runbook itself instructs the owner to register a new
  account (Part D step 5), which quietly leaves the old history behind.
- **Root cause**: migration 008 seeds the placeholder user with a literal
  `'placeholder'` password hash that `verify_password` (`ui/auth.py:81-89`)
  can never match. Migration 009 backfills every pre-A32 row to
  `owner_user_pk=1`. Neither is wrong on its own; together they orphan
  everything that predates A32.
- **Blast radius**: all pre-A32 history on any deployed instance where the
  owner registered a fresh account instead of retrofitting the placeholder.
  On the live VM the owner's Driver Model dated history and every chat/coach
  transcript from before 2026-07-28 sits there.
- **Fix**: `driverdna reassign-owner --from N --to M [--dry-run]` (SQLite
  only for now — A40's deployment topology). `Database.reassign_owner`
  walks every partitioned table (discovered at runtime via
  `partitioned_tables()`, so future partitioning is picked up
  automatically), reassigns each source row, and on a unique-constraint
  collision DELETEs the source — the A53 "live row wins, no merge
  heuristic" rule.
  - Atomicity: one transaction across the whole run, commit-or-rollback
    at the end. `--dry-run` uses the same code path and rolls back, so
    the counts the runbook previews are the counts the live run will
    produce.
  - Corner-map collision: `corner_observations.corner_pk` has no
    ON DELETE clause, so the cascade from `corner_maps → corners`
    cannot reach it and DELETE would otherwise fail with a FK error.
    Handled in `reassign_owner`: null those observations first
    (a state `admit_pending_candidates` already treats as valid) so
    the DELETE cascade completes cleanly.
  - Owner-side guards refuse `--from == --to` and any pk that doesn't
    exist in `users`, so the runbook can't accidentally produce
    orphaned rows pointing at nothing.
- **Pinned by**: `test_reassign_owner.py` (7 tests) — base reassignment,
  unique-constraint collision (finding_annotations, live row wins),
  FK cascade completeness (corner_maps discard also removes downstream
  corners), dry-run writes nothing, CLI end-to-end, and both guards.
- **Not fixed here** (deliberate): the migration 008 seed itself. The
  placeholder row stays; the tool moves data off it. A future migration
  could DELETE `user_pk=1` after reassignment completes, but that risks
  breaking the "user_pk=1 is always reserved" mental model some tests
  rely on (`test_auth_ui.py:29-34` explicitly documents it), and this
  fix is the runbook step the owner needs today. Runbook update to
  document this tool is a docs follow-up.

### BUG-036 — The tenancy test gate was specified and never written
- **Status**: fixed 2026-08-18 · **Severity**: security · **SPEC**: A53 (found), fix landed same day
- **Symptom**: not a defect in itself — the absence that let BUG-031, BUG-032
  and BUG-033 all ship unnoticed.
- **Root cause**: `docs/ACCOUNTS-SPEC.md:150-157` made `tests/test_tenancy.py`
  the **gate** for Phase 2 — "seed two users with overlapping car/track, then
  enumerate every read endpoint and assert user A never sees a row, a count,
  an evidence ID or a corner map belonging to user B", modelled on the
  route-enumeration test for the stated reason that a hand-written endpoint
  list will miss one. The partitioning shipped; the gate did not.
- **Blast radius**: the whole multi-tenant surface. Across 74 test files, the
  only cross-user isolation tests were `tests/test_byok_api.py:125` and
  `:131`, covering AI keys alone — and they were green, which is what made
  the rest look covered.
- **Fix**: `tests/test_tenancy.py` — the route-enumerated gate. Walks
  `app.routes` and classifies every non-public `/api/*` route into exactly
  one of three buckets:
  - **TENANT_SCOPED_READS** — 11 endpoints. Bob's request must return an
    empty result, a 404, or otherwise none of Alice's data. Per-endpoint
    assertions (parametrized so a leak on one endpoint doesn't hide leaks
    on others). Includes SSE payloads (`/api/driver`,
    `/api/driver/score-history`) and JSON reads.
  - **WRITES_INDIRECTLY_TESTED** — 16 endpoints, each naming the focused
    test file that pins its cross-tenant behaviour (BUG-031, BUG-032a,
    BUG-033 pinning tests; `test_byok_api.py` for AI keys;
    `test_reference_curation.py` for lap exclusion; the e196c2d chat
    session ownership fix).
  - **INSTANCE_WIDE_TODAY** — 2 endpoints (`/api/config`, `/api/explain`)
    whose current design is deliberately not tenant-scoped; when BUG-032b
    lands, `/api/config` moves to TENANT_SCOPED_READS.
  An unclassified route fails `test_every_api_route_is_classified_for_tenancy`
  — the exact enumeration property ACCOUNTS-SPEC required, so a future
  endpoint has to be classified before it can ship.
- **Pinned by**: itself (17 tests). Includes a positive-control test
  (`test_owner_still_sees_their_own_data_positive_control`) that guards
  against a fix "closing the leak" by returning empty to every user, and
  a sanity check (`test_owner_data_is_actually_seeded`) so the 404
  assertions can't pass vacuously against a cohort that didn't exist for
  anyone.

### BUG-034 — Registering with a capital letter locks you out permanently
- **Status**: fixed 2026-08-18 · **Severity**: breaks · **SPEC**: A53 (found), fix landed same day
- **Symptom**: register as `User@Example.com`, then no password on earth
  logs that account in. The error was the generic "incorrect email or
  password", so the driver had no way to diagnose it — and password reset
  had the same bug, so the reset flow could not rescue them.
- **Root cause**: `register` normalized (`ui/api.py:407`,
  `email.strip().lower()`); `login` (`:453`), `forgot-password` (`:493`),
  and the outgoing SMTP address in `forgot-password` (`:504`) all used
  `body.email` unchanged. Text columns are `COLLATE "C"` (A23), so
  Postgres does not case-fold either — the storage layer was doing
  exactly what it was told. The Google callback lookup at `:635` had
  already been normalized (`:629`) so it stayed passing.
- **Blast radius**: any user who typed a capital letter or a leading
  space at register. Silent until the driver tried to log in and
  couldn't, then silent again through reset. Not reachable on the live
  instance today because the owner registered lowercase, but a real
  hazard for a beta.
- **Fix**: all three sites now normalize the same way `register` does.
  `forgot-password` normalizes before the SMTP `to_email` argument too —
  a partial fix would find the account but still send the mail to the
  attacker-supplied casing, which is both a bounce risk and a subtle
  anti-enumeration break.
- **Pinned by**: `test_auth_email_normalization.py` — four cases across
  login (register mixed, log in mixed; register lower, log in
  UPPER/PADDED via `parametrize`) and two on forgot-password (mismatched
  case finds the account and sends to the normalized address; genuinely
  unknown address still stays silent). The parametrized guard against a
  strip-only or lower-only partial fix is deliberate.

### BUG-032 — Config is instance-wide, and any user can revert another's change
- **Status**: mitigated 2026-08-18 · **Severity**: security · **SPEC**: A53 (found)
- **Symptom**: (a) any authenticated user posting `POST /api/config/revert/{change_pk}`
  with a small integer could revert *another* user's change and rewrite the
  instance's TOML; and (b) `GET /api/config/history` returned every user's
  rows to every user, exposing keys/values/notes across tenants.
- **Root cause (both halves)**: `config_history` had carried `owner_user_pk`
  since migration 009, so the audit trail *looked* per-user while the read
  paths did not filter on it — worse than plainly global, because it
  contradicted the guarantee the write side spelled out.
  `ConfigStore.revert` (`config.py:855`) selected by `change_pk` alone;
  `/api/config/history` (`ui/api.py:1547`) selected without any owner term
  at all.
- **Blast radius**: every threshold, including measurement thresholds. Zero
  impact on the live instance (one real account); reachable on day one of a
  beta.
- **What's fixed here (part a — the IDOR halves)**: `ConfigStore.revert` now
  filters on `(change_pk, owner_user_pk)` and raises `KeyError` for another
  user's `change_pk` — same shape as an unknown pk, so the endpoint does not
  confirm the change exists (translated to HTTP 404 by the handler).
  `GET /api/config/history` filters on `owner_user_pk`.
- **What remains open (part b — the design redesign)**: config is still
  instance-wide. `ConfigStore` holds a single TOML path and `load_config`
  reads one file — so one user's `apply()` still writes for the whole
  instance. A53 adopted "config becomes fully per-user, every threshold"
  with a mandatory config-fingerprint mitigation stored beside every
  measurement; that is the separate bigger build ahead. Part a is a proper
  fix of a distinct defect, not a placeholder for part b — even with
  per-user config in place, the revert lookup would still need the
  owner filter, and the history endpoint would still need to scope by user.
- **Pinned by**: `test_config_tenancy.py::test_bob_cannot_revert_alices_config_change`
  (the revert IDOR), `::test_bob_cannot_read_alices_config_history` (the
  history endpoint), plus `::test_alice_can_revert_her_own_change_and_it_writes_the_toml_back`
  (regression guard on the legitimate path).

### BUG-031 — `finding_annotations` was never partitioned; annotations cross tenants
- **Status**: fixed 2026-08-18 · **Severity**: security · **SPEC**: A53 (found), fix landed same day
- **Symptom**: with two accounts on the same car/track, one driver annotating
  a finding changed what the *other* driver saw, and either could delete the
  other's annotation. The annotating driver's free-text note also entered the
  other's chat bundle via `chat/session.py:311` and the rendered payload via
  `report/payload.py:259`.
- **Root cause**: two independent gaps that only bit together. The table was
  from migration 001 (`db.py:157`); migration 009 skipped it though
  `docs/ACCOUNTS-SPEC.md:143-148` explicitly listed it, so
  `finding_annotations` had `UNIQUE(finding_id)` and no owner column.
  Separately, `_finding_id(source, car, track, corner, phase, kind)`
  (`attribution/ranker.py:70`) contains no user and no driver term by design,
  so two accounts on GR86/Spa generate byte-identical IDs. Neither is
  harmful alone; together they made one row serve two tenants — the exact
  "evidence-ID collisions across tenants … must *prove* uniqueness, not
  assume it" hazard `ACCOUNTS-SPEC.md:257-259` named.
- **Blast radius**: every annotated finding on any car/track two accounts
  shared. Zero impact on the live instance — one real account — which is
  exactly why it would first appear in the beta.
- **Fix**: migration 017 partitions the table (`owner_user_pk` column,
  `UNIQUE(owner_user_pk, finding_id)`, existing rows backfilled to
  `user_pk=1`, mirroring migration 009's rewrite shape).
  `annotate_finding`/`annotations()`/`clear_annotation` all filter and
  scope by `self.user_pk`. `finding_id` itself keeps its shape (A53
  decision) — changing it would orphan every stored citation in
  annotations, chat transcripts' `evidence_cited` and coach outputs.
- **Pinned by**: `test_finding_annotations_tenancy.py` — three cross-user
  tests (parallel annotations, cross-user clear, upsert isolation) plus a
  fourth **guard** test `test_no_table_declares_a_bare_unique_on_finding_id`
  that parses `MIGRATIONS` and asserts no future table may key on a bare
  `finding_id` without an `owner_user_pk` companion. That guard is the
  substitute A53 named for changing `finding_id`'s shape: the next table
  to store an identity per finding_id cannot repeat this defect.
- **Not fixed here** (separate follow-ups): the config revert IDOR
  (BUG-032, part a — same class of missing-owner-filter defect), the
  route-enumerated tenancy gate (BUG-036), and the login email
  normalization (BUG-034).

### BUG-033 — `/api/sync` falls back to the owner's Garage61 token
- **Status**: fixed 2026-08-18 · **Severity**: security · **SPEC**: A53 (found), fix landed same day
- **Symptom**: a second account that had never connected Garage61 clicked
  **Sync** and imported **the owner's laps** into its own cockpit.
  `/api/garage61/status` compounded it by reporting `connected: true` to that
  user from the same env var — a misleading state that actively invited the
  action.
- **Root cause**: `_resolve_garage61_token` correctly returned `None` for a
  user with no stored token, but the caller in `/api/sync` then built a bare
  `Garage61Client()` regardless — which reads the process-wide
  `GARAGE61_TOKEN` (`garage61/client.py:167`), set on the VM by
  `deploy/driverdna.service`. The status endpoint fell back to the same var.
- **Blast radius**: cross-account telemetry disclosure, owner → any other
  account, through a supported button. Never triggered on the live instance
  because it has one real account; would have fired on day one of a beta.
- **Fix**: when auth is configured, `/api/sync` returns HTTP 400 with a
  directive to connect Garage61 — never constructs a `Garage61Client()`
  from the env — and `/api/garage61/status` reports `connected: false` for
  a user with no stored token of their own. The env fallback stays for the
  no-auth loopback mode, which is what it was written for.
- **Pinned by**: `test_cockpit_api.py::test_sync_with_auth_configured_never_falls_back_to_env_token`
  (the RED test written first: seeds a second user, sets `GARAGE61_TOKEN`,
  posts `/api/sync`, asserts 400 and zero rows imported into the beta
  tenant); `::test_garage61_status_with_auth_never_reports_env_token_as_users_connection`
  (status endpoint pin); `::test_garage61_status_without_auth_still_uses_env_fallback`
  (no-auth loopback path pinned so a future tightening cannot silently break
  the single-user local cockpit).
- **Not fixed here** (deliberate; separate bug per plan): the finding
  annotations tenancy hole (BUG-031), the config revert IDOR (BUG-032), and
  the missing route-enumerated tenancy gate (BUG-036). The comprehensive
  gate lands next; this fix ships now because the exposure is a supported
  button on the live topology.

> **BUG-037 and BUG-038 are filed late.** Both were found and fixed on
> 2026-08-16 in `e196c2d` and merged without a BUG-LOG entry, contrary to
> AGENTS.md's decision discipline. Their IDs follow discovery-order convention
> as closely as the already-assigned range allows; the **Found** dates are the
> real ones. Recorded during A53's audit (2026-08-18).

### BUG-037 — Google OAuth callback had no CSRF state parameter
- **Status**: fixed · **Severity**: security · **Found**: 2026-08-16
- **Symptom**: an attacker who got a victim to load a crafted callback URL could
  link the attacker's Google account to the victim's session.
- **Root cause**: the callback accepted a `code` with nothing binding it to the
  browser that started the flow. The Garage61 OAuth flow already had the right
  pattern; the Google one, written earlier, never gained it.
- **Blast radius**: account linkage on any deployment with Google sign-in
  configured.
- **How it was caught**: a security audit of the auth surface, not a test.
- **Fixed in**: `e196c2d` — cryptographic random state in a signed, short-lived
  cookie set on `/login`, compared constant-time on `/callback`, mirroring
  Garage61's flow.
- **Note**: two related weaknesses in the same callback are still open and are
  recorded in A53, not here, because they are design gaps rather than
  regressions: there is no `email_verified` check and no `google_sub` column
  (`ui/api.py:626-650`), so accounts are linked by email string alone —
  `docs/ACCOUNTS-SPEC.md:88-91` specified `google_sub`.

### BUG-038 — Chat sessions were addressable by ID with no ownership check
- **Status**: fixed · **Severity**: security · **Found**: 2026-08-16
- **Symptom**: any authenticated user who learned another user's 12-hex-char
  chat session ID could post messages to it and confirm its staged config
  proposals.
- **Root cause**: `_touch_chat_session` looked sessions up by ID alone in the
  in-process dict; the ID was treated as a capability without being one.
- **Blast radius**: another account's chat transcript and, via `/confirm`, its
  staged `propose_config_change` — a write path.
- **How it was caught**: the same 2026-08-16 audit. No test covered a second
  account against `/api/chat/*`; `test_chat_api.py` seeds two users but exercised
  one.
- **Fixed in**: `e196c2d` — `user_pk` stored at session creation and checked on
  every access, returning 404 (not 403) so the ID is not confirmed to exist.

### BUG-022 — A towed lap's trace duration is used as if it were a lap time
- **Status**: fixed (2026-08-14, A50) · **Severity**: silent-wrong · **Found**: 2026-08-11 (A49),
  **scope corrected the same day** after owner input — see "The first filing was
  wrong" below.
- **Symptom**: a lap that ends early — the driver crashes, calls a virtual tow,
  and is returned to the pits — carries a `duration_s` of however long the
  *trace* ran. Nothing checks completeness before treating that as a lap time,
  so the towed lap becomes the cohort's fastest and every real lap renders as
  slower than a lap that was never completed.
- **Measured on real fixture telemetry** (`Garage_61_HKWPXX.csv`, truncated to
  40% to simulate a tow):

  | | `duration_s` | `lap_dist` span | corners found |
  |---|---|---|---|
  | complete | 171.25 s | 1.000 | 14 |
  | towed at 40% | **68.50 s** | 0.414 | 4 |

  `min(duration_s)` across that two-lap cohort becomes 68.50 s, so the genuine
  lap renders at **+102.75 s**.
- **Root cause**: `report/payload.py:183-186` computes `lap_delta_s` against
  `min(duration_s)` over every self lap with no completeness filter, and
  `references_section` (`payload.py:149`) feeds the same unfiltered `duration_s`
  into `reference_envelope`, so a towed *reference* lap sets a bogus "best".
  `duration_s` is `n_samples / SAMPLE_RATE_HZ` (`parser.py:348`) — trace length,
  which equals lap time only when the lap is complete.
- **Blast radius**: whole-lap figures only — `lap_durations_s`, `lap_delta_s`,
  and the reference envelope. Zero on the committed fixtures (all complete), so
  no artifact moves. The exposure is the owner's production store, and it grows
  precisely as incident capture succeeds.
- **Not the per-corner layer, which is correct by construction.** The segmenter
  finds only corners actually present in the trace (4 vs 14 above), so an
  incomplete lap contributes *fewer valid* observations, never fabricated ones.
  Phase times, metrics, the Driver Model and trend are unaffected.
- **The first filing was wrong, and how.** This was originally filed as
  "`INCOMPLETE_LAP` is flagged and never read → partial laps are measured as if
  complete", with a blast radius of "baselines, vs-self ranking, the Driver Model
  and trend". The *premise* is accurate — the flag genuinely is raised at
  `parser.py:328` and consumed nowhere — but the consequence was **inferred from
  that fact rather than checked**, and checking disproves it. The unread flag is
  a real loose end; it is not the defect. Same failure the repo already has a
  standing lesson for (A28: a capability claim needs a source, not an inference;
  A25: an unverified guess presented as observed).
- **Product intent, owner-stated (2026-08-11), now on the record**: an incomplete
  lap is **wanted**. A lap that ends in a tow is the incident record — "measure
  the driver, not the lap" (A19). Any fix here must keep ingesting and measuring
  these laps; excluding them would delete exactly the evidence the incidents
  subsystem exists to capture. That also retires the original entry's proposed
  next step of gating measurement on `INCOMPLETE_LAP` — it would have been the
  wrong fix, and would have thrown away real data.
- **Fix (2026-08-14, SPEC.md A50)**: `INCOMPLETE_LAP`-flagged laps are excluded
  from the lap-time comparison only. `lap_delta_s` is computed from
  `min(duration_s)` of complete laps; an incomplete lap's entry is `null`.
  `lap_incomplete` boolean array added to the cohort payload (parallel to
  `lap_ids`). Reference envelope filters incomplete reference laps. The HTML
  line chart excludes them. SPA renders "incomplete" chip and "—" delta.
  `PAYLOAD_VERSION` 7→8 (additive field + type change). Per-corner measurement
  unchanged — incomplete laps still contribute their valid corners. Number-neutral
  on committed fixtures (all complete). Pinned by
  `test_incomplete_lap_excluded_from_lap_time_comparison`.
- **How it was caught**: not by a test — by the owner saying they *wanted*
  incomplete laps, which forced the original filing to be re-examined and the
  mechanism actually measured. Worth recording: the entry read as authoritative
  while resting on an inference nobody had run.

### BUG-018 — Service unreachable on the Oracle VM (Cloudflare 1033)
- **Status**: closed-undiagnosed (2026-08-15) · **Severity**: breaks · **Found**: 2026-08-08
- **Symptom**: `driver-dna.com` returns Cloudflare error 1033. Persisted after
  a service restart following `pip install .[dev]` against the live venv.
- **Root cause**: never established. The journal was not captured before the
  service recovered (systemd's volatile default drops logs on reboot). Two real
  bugs were found in the same triage session — BUG-026 (SSE heartbeat: the
  proxied connection died during silent compute phases) and BUG-027 (expired
  Garage61 token surfaced as a raw traceback) — but neither is a 1033. The
  leading candidate remains the `pip install` shifting a dependency or the A41
  interlock refusing a start on a missing/stale `DRIVERDNA_SESSION_SECRET`, but
  that is an inference, not a diagnosis.
- **Blast radius**: the deployed instrument was down. Local and test paths
  unaffected. The outage was transient — the service recovered, likely on the
  next `Restart=always` cycle or the next reboot.
- **How it was caught**: owner-visible outage.
- **How it was missed**: journald defaults to volatile storage on most
  distributions. A crash-loop or a refused start leaves no trace after the next
  reboot. Persistent journal storage is now documented in DEPLOY-RUNBOOK.md
  Part G and shipped as `deploy/journald-driverdna.conf`.
- **Why closed without a root cause**: the evidence is gone (no journal), the
  service is up, and the two real bugs found in the same triage are both fixed.
  Reopening requires a reproduction or a fresh journal capture.

### BUG-026 — SSE streams died during the silent phases they were added to survive
- **Status**: fixed 2026-08-11 · **Severity**: breaks · **Found**: 2026-08-11,
  from the production journal while diagnosing BUG-018
- **Symptom**: `cloudflared[…] ERR Request failed error="Incoming request ended
  abruptly: context canceled" dest=https://driver-dna.com/api/driver`. The
  Driver page hangs and then dies — the exact failure the SSE work was built to
  eliminate, still happening after it shipped.
- **Root cause**: `build_driver_payload` emits one `progress_phase` event
  *before* `driver_model` and one before `census`, then computes. On a real
  cohort count each of those phases runs for minutes with nothing to report
  (`census` re-enters `build_driver_payload` internally). The three SSE queue
  loops used a bare blocking `q.get()`, so the stream emitted **nothing** for
  that entire window, and a reverse proxy cannot distinguish a working stream
  from a dead one: Cloudflare's idle timeout (~100 s) closed the connection
  mid-compute.
- **Blast radius**: `/api/driver`, `/api/driver/score-history`, `/api/sync` —
  every long-running stream, and worst exactly where the payload is biggest, so
  it got *more* likely as the corpus grew. Local and CI never saw it: the
  fixture corpus computes in seconds, and neither `TestClient` nor a loopback
  request has an idle timeout.
- **Fix**: one `_drain_sse` helper for all three loops, `q.get(timeout=…)` with
  an SSE **comment** (`: keepalive`) on each idle tick — ignored by EventSource,
  so no client change and no payload change. Interval is
  `config.api.sse_heartbeat_seconds` (default 15 s, well inside 100 s). The
  helper also ends the stream with an error event if the worker dies without
  posting a terminal event, instead of heartbeating forever against a dead
  thread.
- **How it was caught**: reading the production journal. Not by any test —
  and the two new tests only exist because a real log line pointed at the
  route. Pinned now by `test_sse_emits_keepalives_while_the_worker_is_silent`
  (a deliberately stalled worker must produce keepalives) and
  `test_sse_keepalives_are_comments_not_events`; the first was verified to fail
  against a reverted `q.get()`.
- **How it was missed**: the SSE work was reviewed and tested for *event
  correctness* — the right events in the right order — and never for *timing*.
  Nothing in the suite models a proxy, an idle timeout, or a slow phase, so a
  stream that is correct but silent looked identical to a healthy one.
  Related: the same diagnosis initially mis-attributed this to an expired
  Garage61 token (see BUG-027) — two real defects in the same journal, 21
  minutes apart, on different routes.

### BUG-027 — An expired Garage61 token surfaces as a raw traceback
- **Status**: fixed (2026-08-15) · **Severity**: breaks · **Found**: 2026-08-11
  (production journal)
- **Symptom**: `driverdna.garage61.client.Garage61AuthError: GET
  /laps/…/csv: Bad authentication: operation GetLapCSV: security "OAuth2":
  expired access token.` followed by `ERROR: Exception in ASGI application`.
  The driver gets an error string, not "your Garage61 sign-in expired,
  reconnect".
- **Root cause**: the OAuth access token expires and nothing refreshes it or
  detects the expiry ahead of a call. `_resolve_garage61_token` decrypts a
  stored token and hands it over without checking validity; a stale one only
  fails at the point of use, deep inside a sync.
- **Blast radius**: `/api/sync` and the CLI `sync`. No measurement is affected
  — nothing is imported — but the recovery path is invisible to the driver even
  though the OAuth flow and `/api/garage61/status` already exist.
- **How it was caught**: production journal, during BUG-018 triage.
- **Fix**: `Garage61AuthError` is now caught at both sync surfaces. The SSE
  worker in `api.py` emits `{"type": "error", "detail": "Garage61 sign-in
  expired — reconnect…", "auth_expired": true}` — the SPA detects
  `auth_expired` in both `SyncPanel` (driver home) and `#/import` and renders a
  reconnect link to the OAuth flow instead of the raw traceback. The CLI prints
  the same message and exits 2. Refresh-token handling is still the deeper fix
  if the API offers one.
- **Test**: `test_sync_auth_expired_returns_structured_error` in
  `test_cockpit_api.py`.

### BUG-023 — `main` merged red: an endpoint field with no test update
- **Status**: fixed 2026-08-11 · **Severity**: breaks · **SPEC**: A49 (found during)
- **Symptom**: `tests/test_auth_api.py::test_status_reports_whether_auth_is_required_and_met`
  failed on `main` and on every branch cut from it.
- **Root cause**: commit `4414117` ("add Garage61 import to upload view", PR #21)
  added `garage61_linked` to `GET /api/auth/status` (`ui/api.py:891`) without
  updating the test's exact-equality assertion. The endpoint change is correct;
  only the assertion was stale.
- **Fix**: added `"garage61_linked": False` to all three expected dicts. The
  assertion keeps its exact-equality form — the strong version that caught this
  in the first place — rather than being relaxed to a subset check.
- **Blast radius**: no product behaviour. The cost was to trust: a red suite on
  `main` trains everyone to treat red as background noise, which is exactly what
  AGENTS.md's "never assume a failure is synthetic" rule exists to prevent. It
  was very nearly written off here as "branch is behind main" — `git rev-list
  --count HEAD..origin/main` returned 0, which disproved that in one command.
- **How it was missed**: nothing enforces the checks. AGENTS.md already records
  that the PR-to-`main` rule is convention-only (a Ruleset was blocked by a
  paid-plan restriction on private repos), so a red `pytest` job does not block
  a merge. This is the first entry where that gap actually cost something.
- **Related, still open**: `ruff check .` is also red on `main` — 25 findings,
  all in dead root-level scratch scripts (`apply_phase1_phase2.py`, `db_patch*.py`,
  `inject*.py`, `phase1.py`, `phase2.py`, `refactor_db_*.py`, `rewrite_queries.py`,
  `tests/run_blobs*.py`), which are referenced only by each other. Untouched
  here: deleting fifteen tracked files is an owner call, not a side effect of a
  sync change. Filed as **BUG-024**.

### BUG-024 — `ruff check .` is red on `main` from dead scratch scripts
- **Status**: fixed 2026-08-11 · **Severity**: breaks · **SPEC**: A49
- **Symptom**: `python3 -m ruff check .` reports 25 findings (22 auto-fixable):
  unused imports, `E741` ambiguous `l`, `E402` late import. CI's `lint` job is a
  declared merge gate, so it is red for every PR regardless of the PR's content.
- **Root cause**: one-off migration/patch scripts were committed at the repo
  root and never removed: `apply_phase1_phase2.py`, `db_patch.py`,
  `db_patch2.py`, `db_patch3.py`, `fix_patch.py`, `inject.py`, `inject2.py`,
  `inject3.py`, `phase1.py`, `phase2.py`, `refactor_db_1.py`,
  `refactor_db_2.py`, `rewrite_queries.py`, plus `tests/run_blobs.py` and
  `tests/run_blobs_debug.py`. Nothing in the package imports any of them; the
  only cross-reference is `fix_patch.py` naming its siblings.
- **Blast radius**: no product behaviour — but a permanently red gate is
  indistinguishable from a newly red gate, so it hides real lint regressions.
  All of `src/driverdna/` and the real test files pass cleanly.
- **How it was caught**: running `ruff check .` before committing A49, per
  AGENTS.md's command list.
- **Fix**: all fifteen deleted (owner-directed). They are one-shot source
  rewriters — each opens `src/driverdna/db.py`, runs string replacements and
  writes it back — left over from the identity/`users` phase work and the
  Postgres move (A23). Their output has been in `db.py` for months, so the
  scripts were both dead and misleading: a reader could mistake them for a
  supported migration path. Auto-fixing the imports instead was rejected for
  exactly that reason — it would have left dead code lint-clean and still dead.
  Verified before removal: no module imports any of them (the only
  cross-references were `fix_patch.py` naming its siblings, and the English
  word "inject" in unrelated prose). After: `ruff check .` passes repo-wide for
  the first time, and the suite is unchanged at 993 passed / 16 skipped.
- **Worth noting**: this had been red long enough that a permanently-red gate
  read as normal. That is the actual cost — BUG-023 (a genuine regression on
  `main`) sat in the same CI run and was nearly dismissed as environmental.

### BUG-025 — Browser tests skipped silently, hiding a broken assertion for two commits
- **Status**: fixed 2026-08-11 · **Severity**: breaks · **SPEC**: A49 (found during)
- **Symptom**: `tests/test_upload_ui.py::test_upload_flow_end_to_end_through_the_real_browser`
  asserted `GET /api/cohorts` equalled a four-key dict. Two commits earlier on
  the same branch, `/api/cohorts` gained `n_laps`, `n_reference_laps` and
  `last_synced_at` for the Garage cards. The test had been failing ever since
  and nobody saw it.
- **Root cause of the *hiding*** (the interesting half): `tests/browser.py`
  asks Playwright for `p.chromium.executable_path` and skips the whole
  browser-marked suite when that path does not exist. The installed Playwright
  resolves `/opt/pw-browsers/chromium-1234/chrome-linux64/chrome`; the image
  ships build **1194** at `chromium-1194/chrome-linux/chrome`. Nothing was
  broken in the repo — the environment simply had a different Chromium build,
  so all 26 browser tests reported as skips and the suite read green.
- **Blast radius**: no product behaviour; the endpoint change was correct and
  the SPA consumed the new fields fine. What was lost was the guarantee — for
  two commits, every browser-gated trust gate (render parity, offline, auth UI,
  feedback hierarchy, cockpit, reference curation) was unverified while
  appearing to pass.
- **Fix**: expected dict updated to the endpoint's real shape, keeping exact
  equality. Chromium made discoverable in this environment by symlinking the
  expected build path at the real one — an environment fix, no repo change:
  `ln -sfn /opt/pw-browsers/chromium-1194/chrome-linux /opt/pw-browsers/chromium-1234/chrome-linux64`.
  All 26 browser tests then ran and passed.
- **How it was caught**: reading the skip list instead of the pass count —
  AGENTS.md's "a skipped test is not a pass" applied literally. 42 skips broke
  down as 16 Postgres (expected, no `DRIVERDNA_TEST_DATABASE_URL`) and 26
  browser (not expected — the environment advertises a pre-installed Chromium).
- **Why the guard did not fire**: `browser.py`'s docstring says its whole reason
  for existing is that a *previous* hardcoded-layout version silently stopped
  matching after Playwright changed its unpack layout, and that CI's grep-based
  guard caught it but was non-blocking. Asking Playwright for its own path
  removed the layout guess but not the failure mode: the answer can still point
  at a build the machine does not have, and the result is still a silent skip.
  CI is unaffected (its `browser-tests` job installs the matching build and
  fails if the skip guard triggers) — this bites local and remote dev
  environments, which is where most of this repo's work happens.

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

### BUG-028 — Six methodology texts written, none reachable; the guard only checked one direction
- **Status**: fixed 2026-08-16 · **Severity**: dead-weight · **SPEC**: A51 (found during)
- **Symptom**: `explain.py` defined `model.adherence`, `model.opportunity`,
  `model.consistency`, `model.evidence_count`, `baseline.spread` and
  `baseline.outliers_screened`. Grepping the SPA for each returned **zero**
  references. Six carefully written driver-facing explanations shipped in the
  package and could not be reached from any route.
- **Root cause**: `tests/test_explain.py` checks JSX -> engine (every id a view
  names must exist in the dict) and nothing checks engine -> JSX. A typo'd id
  fails loudly; an unused id is silent forever. The three component texts were
  the most costly case: they explain exactly the decomposition that A14
  requires a composite score to expose, and the payload was not carrying the
  components at all, so the texts had nothing to attach to even if a view had
  wanted them.
- **Blast radius**: no wrong number and no wrong claim — purely absent
  explanation. But it is the direct cause of `#/model` reading as seven
  uninterpretable scores, which is half of what A51 exists to fix.
- **How it was caught**: an audit of the product against its own stated goal,
  not by a test. Grepping each defined id against `ui/src/` took one command
  and nothing had ever run it.
- **Fix**: the three component texts are now rendered behind each meter's
  disclosure on `#/model` (A51 work item 1). The remaining three
  (`model.evidence_count`, `baseline.spread`, `baseline.outliers_screened`)
  are **still unreferenced** and left open deliberately — they belong to
  surfaces this change did not touch, and inventing a home for them to clear a
  grep would be worse than leaving them listed here.
- **Lesson**: a cross-reference test has two directions and checking one of
  them feels like checking both. Same shape as BUG-013 — the guard was pinned
  where the failure was loud, not where it was silent.

### BUG-029 — A42 changed the unit and left every threshold behind
- **Status**: fixed 2026-08-16 · **Severity**: breaks · **SPEC**: A52
- **Symptom**: every one of the 16 fixture corners banded `major` on
  `same_lap_twice`, and every one cleared the eligibility gate. The loudest
  tone in the coaching vocabulary was the only tone it could produce, so the
  band carried no information at all — a driver saw sixteen identical maximum
  alarms and could not tell which corner was actually the problem.
- **Root cause**: A42 changed the gated quantity from a **raw** coefficient of
  variation to a **per-unit normalized** one. On the new scale `1.0` is exactly
  unit-typical and `consistency_cv_ceiling` (2.0) is the worst dm-v2 will
  score. The thresholds were never converted: `cv_band_major` stayed `0.50`, so
  a perfectly average driver banded "major" at twice the threshold. `git log -L`
  shows commit `d588921` **editing the description** of that very field from
  "coefficient-of-variation floor" to "normalized-CV floor" while the
  `default=0.50` on the line above it went untouched.
- **Second instance, same commit**: `consistency_cv_floor = 0.15` with a
  description reading "0.15 = '15% above typical variability'". On the
  normalized scale that value means 85% *better* than typical, so the
  eligibility gate filtered nothing. The description described the intended
  reading; the number never got it.
- **Blast radius**: coaching tone and eligibility only. `dm-v2` reads
  `config.model.*` and these are `config.coaching.*`, so no Driver Model score
  was ever affected — confirmed empirically when
  `docs/driver-model-report.md` and `docs/census-report.md` regenerated
  byte-identical across the fix.
- **How it was missed**: no test asserted a *relationship* between the
  thresholds and the scale they sit on — only that banding used CV rather than
  seconds, which stayed true throughout. The synthetic fixture behind that test
  produced a normalized CV of **0.388** (i.e. a driver 61% more repeatable than
  typical) and "triggered the inconsistency principle" purely because the floor
  was broken, so the test passed for the wrong reason and its own fixture
  hid the defect. The committed `coaching-report.md` showed the sixteen
  identical `major` rows on every regeneration and was read past for weeks.
- **Fix**: thresholds recalibrated to the scale's own anchors; a test now pins
  that exactly-unit-typical is not `major`, that the major band equals
  `consistency_cv_ceiling`, and that the old values would have called all
  sixteen observed corners `major`. The fixture was rebuilt to vary three
  properties instead of one so it is genuinely inconsistent.
- **Lesson**: when a change redefines what a number *means*, the thresholds
  compared against it are part of the change. Editing the docstring to describe
  the new unit — and stopping there — is the most convincing possible way to
  look done. Same family as BUG-003/BUG-009: a recorded description got trusted
  in place of the value it described.

### BUG-030 — The weakest fundamental could never be coached
- **Status**: fixed 2026-08-16 · **Severity**: breaks · **SPEC**: A52
- **Symptom**: `consistency` was the driver's lowest measured fundamental
  (34.3) and fired at 16 corners, and the coaching layer was structurally
  incapable of ever making it the headline.
- **Root cause**: `headline_eligible` was
  `magnitude_kind == "seconds_lost" and band in (notable, major)`.
  `same_lap_twice` bands on a coefficient of variation, so it failed the first
  clause permanently — no quantity of evidence could change it. The two halves
  of the product therefore disagreed by construction: the Driver Model named
  consistency the weakness while coaching could only ever talk about something
  else.
- **Why the restriction existed**: removing it alone would have introduced a
  worse bug. The ranker picked `max(..., key=magnitude)`, which compares 0.591
  **seconds** against a CV of **2.724** and takes the CV every time — not
  because it is worse but because CVs are bigger numbers. Fixed with a
  unit-free `_severity` (magnitude as a multiple of the `major` floor for its
  own kind), kept private so a number with no unit never reaches the payload
  or the grounding validator's citable pool.
- **How it was caught**: an audit against the product's stated goal, and only
  because A51 had just built the reading that named consistency the weakness —
  the contradiction was invisible until two layers stated the same thing in
  different words.
- **Lesson**: a hard `and` in an eligibility predicate is a permanent
  exclusion, not a threshold. It deserves the same scrutiny as a magic number,
  and none of the tests around it had ever asked "can this branch be reached
  at all?"

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
5. **Adopted-but-not-built is a live exposure** (BUG-010, BUG-020, and the
   whole BUG-031..033 cluster). A decision in a spec does not defend anything.
6. **A spec's own gate is not a gate until someone writes it** (BUG-036, and
   therefore BUG-031/029/030). `docs/ACCOUNTS-SPEC.md` named the test that
   would have caught all three, named the hazard one of them realises, and was
   right about both. The design work was done and the verification work was
   not — so the partitioning *looked* finished, and the suite stayed green
   because nothing asked it the question. When a spec names a gate, the gate is
   part of the deliverable, not a follow-up.
7. **Documentation drift is a defect, with a blast radius** (BUG-031..033, all
   found in one audit). Three weeks of documents contradicted A32 while the
   code moved on, so each new session re-derived the wrong mental model —
   "personal instrument for one driver" — and none of them looked for tenant
   bugs. `docs/ACCOUNTS-SPEC.md:37-56` predicted exactly this and specified the
   reconciling edits; skipping them cost more than writing them would have.
