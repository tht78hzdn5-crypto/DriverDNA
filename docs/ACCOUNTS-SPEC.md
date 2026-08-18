# DriverDNA — Accounts, Multi-User & Blob Storage Spec (design stage)

**Status: SUPERSEDED as a status doc, still authoritative as the design.**
Adopted by SPEC.md **A32** (2026-07-28) and largely built; audited 2026-08-18
by **A53**, which is the current status of record.

- **Built:** Phase 0 (constitution), Phase 1 (identity core), Phase 2 (data
  partitioning), Phase 3 (Google OAuth), Phase 4 (SMTP password reset).
- **Not built, still open:** the **Phase 2 test gate** (`tests/test_tenancy.py`,
  specified below and never written); **invite-only registration** after the
  first account (specified below, registration shipped fully open — A53 adopts
  first-user-only); `GcsBlobStore` (Phase 2b — moot, A40 returned the deploy to
  a single VM with local-disk blobs); the dedicated `DRIVERDNA_SECRET_KEY`
  (sessions still sign off the passphrase); `google_sub` and username columns.
- **Built but broken:** `finding_annotations` was named in Phase 2's table list
  and never partitioned; hazard 4 below ("evidence-ID collisions across tenants
  … must *prove* uniqueness, not assume it") describes a defect that is now
  real. See A53 and BUG-031.

The original text is kept unedited below — the measurements, the architectural
crux and the hazards are still the best record of *why* this was built this
way, and three of its hazards came true. Read it as design rationale, not as a
statement of what exists.

Nothing here overrides `docs/SPEC.md` (engine), `docs/ARCHITECTURE_VISION.md`
(constitution) or `docs/UI-SPEC.md` (interface) **until SPEC.md A32 is written**.
Where this document and those conflict today, they win. That ordering is
deliberate: this design reverses standing constitutional text, and a design doc
must not be able to do that by itself.

---

## Why this exists

Single-driver auth shipped 2026-07-27 (SPEC.md **A31**, `docs/DEPLOY-SPEC.md`
track H1): a passphrase exchanged for a signed HttpOnly cookie, explicitly *not*
a user system. Asked afterwards for "more of a traditional login experience", the
owner chose, in order:

1. **Username + password** — two fields, conventional, and it makes password
   managers work (a lone password field has nothing to anchor autofill to).
2. **Sign in with Google.**
3. **Real accounts** — registration, stored user records, password reset by
   email.
4. **Each user has their own data.**
5. **Object storage for raw traces, plus a per-cohort track outline in the
   database.**

Choice 4 is what makes this large, and it was chosen after the cost was stated
plainly ("weeks, not days — and it makes DriverDNA a product rather than an
instrument"). Choices 3 and 4 together reverse the constitution.

## What this reverses, and where

Three documents say the opposite of this design today. All three must change in
the same edit as A32, and the amendment must say **reversed by owner decision**,
not "refined":

- `docs/DEPLOY-SPEC.md` lines 34-40 — *"DriverDNA stays single-tenant. Auth is a
  lock on one driver's own door, not a user system. There is no user table, no
  registration, no tenant column, no per-user data partitioning, and no second
  identity."*
- `docs/UI-SPEC.md` "Out of scope" — multi-user listed under the **permanent**
  exclusions.
- `docs/SPEC.md` **A31**, written hours earlier, which *reaffirmed* single-tenancy
  and stated it "is explicitly not precedent" for multi-user. A32 must name A31
  and say the owner overrode it, with the date. Leaving that implicit would make
  the amendment log lie about its own history.

`docs/DEPLOY-SPEC.md`'s framing also says a second real user "is productization
and it goes back to the owner as its own decision, with its own amendment."
That is exactly what happened. The process was followed; the answer was yes.

---

## The architectural crux

**`corner_maps` is `UNIQUE (car, track)` with no tenant key** (`db.py`), and
corner maps are shared globally. Two users on the same car and track would match
against one frozen map, and each other's laps would be *admitted* into it —
silently shifting the other's corner centroids, phase windows, and therefore
every measurement downstream. `corner_pk` is embedded in evidence IDs, which the
grounding validator treats as load-bearing.

This is the single most expensive consequence of per-user data, and the reason
this is not "add a users table". Corner maps must become
`UNIQUE (owner_user_pk, car, track)`.

## Two concepts that must never be conflated

- **`laps.driver`** — *who drove this lap*. Stays exactly what it is: a data
  label. Reference laps carry someone else's name here, which is the entire
  point of them, so this can never become the tenant key.
- **`owner_user_pk`** (new) — *whose account this row belongs to*. The tenant
  key.

Collapsing these would break reference laps, which is the mistake this section
exists to prevent.

---

## Design

**Identity.** New `users` table: unique email, unique username, `password_hash`
+ `password_salt` via **`hashlib.scrypt`** — stdlib and memory-hard, so the
project's "no new dependency" precedent holds and no vendor enters for the
password path. `google_sub` nullable for linked accounts. `session_epoch`, bumped
on password change so a reset invalidates every outstanding session.

**Sessions.** `ui/auth.py`'s existing scheme extends rather than being replaced:
the signed value gains `user_pk` and `session_epoch` alongside the expiry. It
stays **stateless** — no session table — which is what lets it verify on any
instance after any restart. The signing key moves from being derived off the
passphrase to a dedicated `DRIVERDNA_SECRET_KEY` (env-only), because the
passphrase stops being the credential.

**`DRIVERDNA_ACCESS_TOKEN` is kept as break-glass**, not deleted: it is how you
get in when the users table is empty or you have locked yourself out, and it is
what the fail-closed `--host` interlock keeps checking.

**Registration is invite-only after the first account.** The first user
bootstraps and becomes owner; registration then closes. An open registration form
on a public URL is an abuse vector, and "possibly more than one person" does not
mean "anyone".

---

## Phases

Strictly ordered. Each ends with tests green and is independently reviewable;
this is far too large for one change.

### Phase 0 — Constitution first
Nothing builds until this is written, because every later phase cites it.
SPEC.md **A32** naming philosophy #8 as the principle it reverses, the owner's
decision and date, A31 explicitly overridden, and the two new server-side
outbound paths (Google, SMTP) that **trust gate 5b** must be amended to permit.
**Gate 5a is unaffected and stays as-is** — Google sign-in is a top-level
redirect, not an XHR, so the SPA still makes zero third-party requests. Matching
edits to DEPLOY-SPEC and UI-SPEC out-of-scope lists, plus a PROJECT-BRIEF
decision-log entry.

### Phase 1 — Identity core
Migration 007: `users`. scrypt hashing with parameters in config. First-user
bootstrap then invite-only. Login by username *or* email. SPA gains a username
field, a register view, show/hide password, correct `autocomplete` attributes
(`username` / `current-password` — this is what makes password managers work at
all), and real error and session-expired states.

### Phase 2 — Data partitioning (the expensive one)
Migration 008 adds `owner_user_pk` to `laps`, **`corner_maps`** (with
`UNIQUE (owner_user_pk, car, track)` replacing `UNIQUE (car, track)`),
`coach_outputs`, `driver_beliefs`, `garage61_sync_state`, `incidents`,
`chat_transcripts`, `finding_annotations` and `config_history`. Existing rows
backfill to the bootstrap user. Every query gains the scope. Retention becomes
per-user. Reference-lap isolation now has **two** axes — `role` *and* owner — and
both must hold.

Gate: a new **cross-tenant isolation suite** (`tests/test_tenancy.py`). Seed two
users with overlapping car/track, then enumerate every read endpoint and assert
user A never sees a row, a count, an evidence ID or a corner map belonging to
user B. Modelled on the route-enumeration test, for the same reason — a
hand-written list of endpoints will miss one. (That lesson was learned the hard
way on 2026-07-27, when a `/api/`-prefixed enumeration missed `/openapi.json`.)

### Phase 2b — Blob storage (see measurements below)
`GcsBlobStore` against the existing `BlobStore` interface, plus a per-cohort
track outline persisted in the database.

### Phase 3 — Sign in with Google
Server-side authorization-code flow: the browser only does a top-level redirect,
the server exchanges the code and issues the same session cookie, so gate 5a
stays green. Verified email links to an existing account or creates one under the
invite rule. Needs a GCP OAuth client and `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET` (env-only), with a redirect URI pinned to the Cloud Run
hostname. **Token verification needs no crypto dependency**: the ID token arrives
direct from Google's token endpoint over TLS in the back channel, so signature
verification is not required — state this in code, because it looks like an
omission otherwise.

### Phase 4 — Password reset over SMTP
`password_resets` table holding a **hash** of the token, single-use, short
expiry. Stdlib `smtplib` + `email.message`, credentials env-only. Reset bumps
`session_epoch`, ending every existing session. Requests are rate-limited and
respond identically whether or not the address exists, so the endpoint is not an
account-enumeration oracle.

### Phase 5 — Re-prove the gates
Render-parity and offline crawlers re-run signed in; the grounding validator
re-proved against a second user's payload (evidence IDs must stay unique across
tenants); full suite on both backends; determinism re-verified **per user**,
since partitioned corner maps change what determinism means here.

---

## Blob storage and capacity — measured, not estimated

Measured on the 12 committed fixture laps, 2026-07-27:

| | per lap | share |
|---|---|---|
| DB rows (summaries, metrics, phase times) | **32 KB** | 3.6% |
| Raw trace blob (`.npz`) | **867 KB** | **96.4%** |

Three tables are ~80% of the DB side: `metric_values` (9.2 KB/lap),
`detector_results` (9.9 KB/lap), `corner_observations` (7.5 KB/lap).

### The hosted deployment is already broken here, quietly

Cloud Run's container filesystem is in-memory: writes count against the instance
memory limit and vanish on cold start. So on the live service today —

1. `GET /api/cohorts/{slug}/track-trace` 404s after any restart.
2. **`rebuild-map` refuses outright.** A26's tombstone rule correctly reads
   "trace missing, no tombstone" as unsafe, and on Cloud Run *every* trace is
   exactly that. A correct safety feature is currently a hard block.
3. Import writes ~867 KB/lap into memory on a 512 MB default.

Reports still work only because M3 stores phase times compactly at import. Good
design, and it has been hiding this.

### Decision (owner, 2026-07-27): object storage **plus** a cohort outline in the DB

1. **`GcsBlobStore`.** `blobs.py` already defines an abstract `BlobStore`
   (`put`/`get`/`delete`/`has`/`lap_pks`/`mark_evicted`/`evicted_lap_pks`) with
   `MemoryBlobStore` and `FileBlobStore` behind an `open_blob_store()` factory —
   so this is **one class plus a factory branch**, not a refactor. GCS because
   the deployment is already on GCP. Tombstones move with it; a shared store
   makes them global, which is what A26 wanted anyway. Keeps `rebuild-map` and
   future re-measurement alive.
2. **A stored per-cohort track outline**, so no *read* view depends on a blob.
   `track-trace` already downsamples to 800 points (`TRACE_POINTS`, `api.py`) and
   needs one trace per cohort, not per lap — roughly 19 KB packed, once per
   cohort. Persist it beside the frozen corner map; write it when the map
   freezes and refresh it on `rebuild-map` (deterministic: the map's own lap, not
   "newest retained"). A missing or evicted blob then degrades nothing a driver
   looks at.

### Capacity

| | ceiling | note |
|---|---|---|
| Database | **~10,000 laps total**, all users combined | ~40 KB/lap in Postgres, ~52 with indexes, against a 500 MB free tier. Grows forever — retention evicts blobs only, never summaries. |
| Blobs | not the constraint | 87 MB per cohort at the default retention of 100/cohort; ~8.7 GB for ten 10-cohort users ≈ **$0.17/month** on GCS. |

The free-tier **database** is the real limit, not storage. For reference: a
committed sim racer runs perhaps 500–1,500 laps a year, so ~10,000 laps is about
ten users at a thousand laps each, or 7–20 driver-years for one. For a webapp,
drop default `retention.raw_laps_per_cohort` from 100 to ~20–30 and make it
per-user. **Verify current Supabase tier limits at build time** rather than
trusting this number.

---

## Hazards, flagged before starting

1. **This would be the largest change in the repo's history**, and it converts a
   personal instrument into a multi-tenant application. Recorded so the reason is
   not lost later.
2. **⚠️ Coordinate with the in-flight Antigravity database-indexing work before
   Phase 2.** It touches `db.py` migrations, exactly as Phase 2 does.
   - Migration numbers will collide (two `007`s).
   - Index key shapes would be wrong: post-tenancy the right key is
     `(owner_user_pk, car, track)`, not `(car, track)`.
   - Indexes add ~30% to a database already bounded at ~10k laps.
   There are only **2 explicit indexes** today, so that work is greenfield.
   Preferred order: **indexing lands first, this rebases onto it.** `AGENTS.md`
   is explicit that agents work one at a time and that two agents on one working
   tree is the failure mode no test catches.
3. **`--max-instances=1` matters more, not less**: chat sessions and both
   in-process limiters are per-instance.
4. **Evidence-ID collisions across tenants** are the subtle risk to the grounding
   validator. Phase 2 must *prove* uniqueness, not assume it.
5. **Two new outbound dependencies** (Google, SMTP) mean the process is no longer
   self-contained even with a SQLite store. Gate 5b's wording covers this once
   amended; gate 5a is untouched.
6. **Password reset needs SMTP credentials as env-only secrets**, joining
   `GARAGE61_TOKEN`, `ANTHROPIC_API_KEY`, `DRIVERDNA_DATABASE_URL`,
   `DRIVERDNA_ACCESS_TOKEN` and the new `DRIVERDNA_SECRET_KEY`. The
   non-negotiable extends verbatim: never persisted, printed, or logged.

## Out of scope even here

The permanent exclusions (A17, restated by A23 and A31) are **not** touched by
this design and survive it intact: editing measurements, client-side computation
of any figure, blended scores, and setup advice. Multi-user changes who can log
in and whose data they see. It changes nothing about how a number is produced or
what may be shown.
