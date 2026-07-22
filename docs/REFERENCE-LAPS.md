# DriverDNA — Reference Laps: what exists, why you've never seen it, the plan

Written 2026-07-22 at the owner's request ("create a schema or a plan on
incorporating reference laps? one may exist but i haven't seen it"). Both
suspicions are right: the schema and the analysis machinery **exist and are
tested**, and the owner has **never seen them fire** — for a structural
reason, not a bug. Part 1 is a factual survey with citations. Part 2 is the
owner-runnable recipe that makes the existing feature visible today, no code
changes. Part 3 is the gap list and a milestone plan (**R-track**), at design
stage per the M7/COACHING.md precedent: R2/R3 contain deliberate open
decisions, flagged, not picked.

Binding context (unchanged by anything in this doc): reference laps never
enter self history, trends, classes, consistency statistics, incidents, or
the Driver Model (constitution; SPEC.md philosophy #5); reference deltas are
"gap to reference," never "recoverable time" (SPEC.md decision 8); the three
sources never blend (decision 3).

## 1. What already exists (built, tested)

**Schema.** `laps.role TEXT NOT NULL CHECK (role IN ('self','reference'))`
(`db.py:57`). Reference laps are full laps: same parser, same quality flags,
same content-hash dedup, driver/car/track/lap-time/date metadata kept.

**Shared yardstick.** Corner maps are keyed `(car, track)` — deliberately
*not* driver — "so reference laps from other drivers share the owner's
corner identities; gap analysis joins on them" (`db.py:436`). A reference
lap is measured over the *same frozen corners and canonical phase windows*
as yours; phase times are stored as compact rows at import and survive
raw-blob eviction (eviction partitions per `(driver, car, track)`,
`db.py:409`, so references have their own newest-N and never crowd yours).

**Isolation, enforced at the query surface.** Every self-history read
filters `role='self'` inside `db.py` itself, not in callers (metric values
`db.py:582`, distributions, detectors `db.py:707`, trend inputs
`db.py:1098`); classification "is a self statistic: reference laps never
move a class" (`pipeline.py:213`); the incident scan never reads them
(`pipeline.py:162`). Tested: SPEC.md M-trust condition 3 — importing a
reference lap perturbs gap sections *only* (verified at M3).

**Analysis.** `attribution/ranker.py:260` (`vs_reference_findings`): per
corner × phase, an **envelope** over *all* reference phase times (median +
best + n), compared against your robust baseline — gap typical-vs-typical
(`your median-of-top-3 − reference median`) and best-vs-best, gated by the
same self-history gates as every finding, `reference_n` carried in
`details`. Findings flow into the payload (`report/payload.py:167`) and so
into reports, coach, chat, and the UI's `vs-reference` source section
("gap to reference (context, not recoverable time)", dotted left rule).

**Ingestion.** Manual only, by decision of record (SPEC.md decision 2,
clarified by M0b/A16): `driverdna import <files> --role reference`
(`cli.py:64`) or `#/upload` with the role select (`upload.jsx:14`). `sync`
structurally cannot ingest references: every lap is self-filtered on
`driver.id` before fetch, and the API 403s (`forbidden_lap`) on other
drivers' CSVs anyway (`docs/garage61-api.md`).

**Existing surfaces.** `driverdna history` prints "N self laps, M reference
laps" per cohort (`cli.py:580`); the laps view has a `role` column
(`laps.jsx:26`).

## 2. Why you've never seen it — and how to see it today

Your DB contains zero reference laps: `sync` can't fetch them, you've never
imported one, and with an empty envelope every vs-reference path is
correctly silent — the section renders nothing rather than an empty shell.
The feature is invisible until fed, and nothing in the UI says feeding it is
possible (gap G1 below).

**Owner-runnable recipe (no code changes):**

1. In the Garage61 **web app** (its own sharing rules, not the API's),
   open a lap you can view from a faster driver — teammate, or any lap
   whose telemetry CSV the site lets you download — same car, same track
   as one of your cohorts.
2. Download the telemetry CSV export (identical shape to your own exports;
   one parser by design, SPEC.md decision 1).
3. Import it tagged as reference — either
   `driverdna import path/to/lap.csv --role reference` (car/track
   auto-detected from the newer filename shape, or pass `--car/--track`),
   or `#/upload` with role = reference.
4. Open the cohort page or run `driverdna attribution`: the `vs-reference`
   section appears with per-corner/phase gap findings. Nothing else about
   your numbers changes — that's trust condition 3, and this first real
   import is a live re-observation of it.

Constraint to respect: the cohort's corner map freezes from laps present at
build time. Import your own laps first so the map is *yours*, then add
references — the reference then joins onto your corner identities. (What
happens if a reference lap is the *first ever* lap in a cohort is untested;
R0 below pins it rather than guessing.)

## 3. Gaps

- **G1 — Invisibility.** No surface says "0 references — you can add
  context here." The empty state that is a designed primary state
  everywhere else (UI-SPEC intent) doesn't exist for references.
- **G2 — Envelope opacity.** `reference_n`, and *who/what* the reference is
  (driver, lap time, date — all stored on `laps` rows), are in the DB and
  partly in finding `details`, but the UI renders none of it. A gap to an
  envelope of one lap reads identically to a gap against thirty.
- **G3 — Undifferentiated pool.** The envelope pools every reference lap in
  the cohort. "Gap to whom?" has no answer; a slow reference import shifts
  the envelope median with no visible trace of its influence.
- **G4 — No curation.** Nothing retires a bad reference import; it lives in
  the envelope forever (short of rebuilding the DB).
- **G5 — Sourcing friction.** Manual export is the only path — correct per
  M0b evidence. Team data packs remain the recorded revisit avenue,
  **deprioritized, not closed** (owner's domain read: packs are used for
  setups in practice; `docs/garage61-api.md`). This doc changes nothing
  there.
- **G6 — No reference depth in the corner drill.** The drill shows the gap
  finding but can't show the reference phase-time distribution beside
  yours, though `db.phase_times(role='reference')` (`db.py:637`) already
  answers exactly that question.

## 4. The plan — R-track (design stage; build on owner go)

- **R0 — Feed it and pin it (no code).** Owner runs the recipe above with
  one real reference CSV. Acceptance: the vs-reference section appears;
  self numbers byte-identical before/after (trust condition 3, observed
  live); the reference-first-in-empty-cohort question answered by a small
  test, documented here. R0 is the gate for everything below — no UI work
  for a feature the instrument's owner hasn't exercised once.
- **R1 — See & understand (UI-only; folded into U5, see UI-SPEC.md
  "Reference-lap visibility").** The owner's ask restated: reference laps
  are currently *invisible until fed and unexplained once present*. R1 fixes
  both, in two halves split by their data dependency:

  **R1a — Discoverability (needs no reference data; not R0-gated — this is
  what leads the owner to R0).** The vs-reference section is a designed
  primary state even at N=0: where it renders nothing today, it renders one
  dim direction line in the gates-panel register — *"No reference laps yet.
  Add a faster driver's lap as a reference for gap context — it never enters
  your history, trends, or scores. Import → role: reference."* — with a real
  button to `#/upload`. One **guarantee line** sits wherever references
  appear, stating the isolation plainly (never history / trends / classes /
  consistency / incidents / Driver Model). The upload role `<option>`
  already carries a short hint (`upload.jsx:106`); R1a promotes it to a
  visible help line under the select, same copy as the guarantee.

  **R1b — Legibility of real references (needs one reference lap; testable
  against a fixture reference lap, which the suite already builds —
  `test_attribution.py:253` et al.).** A **pit-board stat tile** on the
  cohort page: "N reference laps" (count of `/api/laps` rows with
  `role='reference'` — the `shownCount` counting precedent, render-parity
  clean). Each vs-reference finding's meta gains **"ref n=K"** from
  `details.reference_n` (already in the payload — clean by construction), so
  a gap to one lap never reads like a gap to thirty. The **"who"**: a
  compact "References" line listing each reference lap's driver + lap time —
  lap time (`duration_s`) is already returned by `/api/laps`; **driver is
  not**, so R1b adds `driver` to that endpoint's SELECT (`api.py:177`) — a
  single read-field addition, the value then traces to a read endpoint like
  every other on-screen figure (render-parity honored, not bypassed).

  Tests: `#/garage` aside, R1 adds no route, so both hardcoded route lists
  are unchanged; the render-parity crawler now needs a reference lap in its
  fixture DB so the vs-reference section is exercised (add one — the same
  synthetic `role='reference'` helper the attribution tests use); DOM
  assertions on the cohort/laps markup updated in the same change. Deeper
  reference identity (date, per-lap distribution in the corner drill) stays
  in R2.
- **R2 — Reference identity and depth (small engine + payload).** A
  `references` block in the cohort payload: the envelope (n, median, best)
  plus contributing laps (driver, lap time, date — already stored, never
  yet surfaced); corner drill gains a reference distribution beside yours
  via a read endpoint over `db.phase_times(role='reference')`, mirroring
  the existing distribution endpoint. **Open decision (owner):** optional
  import-time label (`--ref-label "teammate JD"` / upload field; nullable
  column, migration) — and if labels exist, whether the envelope ever
  splits per label or stays one pool with labeled contributors. Splitting
  multiplies findings; the honest default is one pool, contributors
  listed. Not picked here.
- **R3 — Curation (owner decision required; options stated, one
  recommended).** (A) An exclusion flag through an audited path — the
  annotations pattern: reference lap stays visible, marked excluded, the
  envelope recomputes without it, the exclusion is reversible and on the
  record. (B) No mechanism — document the re-import stance instead.
  Recommendation: A; it is the smallest mechanism consistent with "nothing
  is silently hidden."

**Non-goals (binding, restated so this plan can't drift):** references in
the Driver Model, trends, classes, consistency, or incidents; any
"recoverable time" framing; blending gap into any score; automatic
reference `sync` (M0b evidence stands until the data-pack scope question is
deliberately reopened); deleting measurements.

## Records

Survey facts are cited inline above. Adoption state and any R-milestone
decisions land in `docs/PROJECT-BRIEF.md`'s decision log (entry
2026-07-22), `docs/STATUS.md`, and — for R1's UI pieces once adopted — as
`docs/UI-SPEC.md` amendments in that document's own style. This file is the
reference-lap source of truth until then.
