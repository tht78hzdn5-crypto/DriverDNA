# DriverDNA — Architecture Vision (Constitution) v1.0

This is the *why*. `docs/SPEC.md` is the *how* (source contract, algorithms,
milestones); `docs/UI-SPEC.md` governs the interface. Where an earlier draft of
this document and the SPEC disagreed, Section "The Scoring Contract" records the
resolution the owner made; both documents now agree. Reconciled 2026-07-19 from
a founding draft (the project's original co-designer) and owner decisions.

Every future change is judged against this document. When convenience and the
constitution conflict, the constitution wins.

## Mission

**DriverDNA measures the driver, not the lap.**

Traditional telemetry answers "where was this lap fast or slow?" DriverDNA
answers "who is this driver, what are their fundamental strengths and
weaknesses, and what should they practice next to be faster *everywhere*?"

The lap is evidence. **The driver model is the product.**

## Prime directive

Every output must contribute to a long-term understanding of the driver's
skill. If a metric cannot improve our understanding of the driver, it should
not exist.

## The pyramid

Everything in the application belongs to exactly one layer:

```
Driver Model      ← beliefs about the driver (scores, confidence, trend)
  Fundamentals    ← universal skills (braking, rotation, exit, consistency…)
  Techniques      ← named behaviours combining observables (trail braking…)
  Observables     ← measured characteristics (release duration, trail overlap…)
  Events          ← objective moments in telemetry (brake start, apex…)
  Raw Telemetry   ← what Garage61 provides (speed, brake, steering, yaw…)
```

Where we are on it today (2026-07-19): Raw Telemetry, Events, and Observables
are **built** (the parser, the nine landmarks, the 18 metrics). Techniques and
Fundamentals are **partial** — losses are tagged by phase and corner class but
not yet composed into named techniques or scored fundamentals. The Driver Model
is **the next milestone (M6)** and does not yet exist.

## Evidence → Belief → Confidence

The central loop:

- Telemetry creates **evidence** (events, observables).
- Evidence updates **beliefs** (fundamental scores).
- Beliefs carry **confidence** that grows with the volume *and breadth* of
  evidence.
- AI **explains** beliefs and prioritizes practice. AI never invents a belief.

Corollary (binding): **new telemetry raises confidence — not necessarily the
score.** A belief that merely sharpens as laps accumulate is the point.

## The Scoring Contract (owner decision, 2026-07-19)

DriverDNA **does** assign scores — this is a deliberate, recorded amendment to
the earlier "no overall score" rule. Scores are the product's headline value.
They are honest *guesses*: opinionated aggregations of real evidence. The
integrity comes from five unbreakable conditions:

1. **Deterministic.** Scores are computed by the engine from measured
   observables via an explicit formula. The same evidence always produces the
   same score. **No score is ever AI-generated.**
2. **Versioned.** The scoring model carries a version (`dm-v1`, …). It may
   evolve through research and validation; when the formula or weights change,
   the version bumps and past beliefs remain recomputable. Weight changes flow
   through `ConfigStore` (versioned, reversible) like every other threshold.
3. **Always three numbers, never one.** Every score ships with **Score +
   Confidence + Evidence Count**. A score without its confidence and evidence
   count is never shown.
4. **Decomposable, never opaque.** Any composite decomposes on demand to the
   evidence beneath it, and the three sources (`vs-principle` / `vs-self` /
   `vs-reference`) remain inspectable underneath. What we still refuse is the
   *opaque* blended number that can't be taken apart.
5. **Trend and evidence count are required outputs, not optional ones**
   (owner decision, 2026-07-20). Every belief the Driver Model emits carries
   **trend** and **evidence_count** as first-class fields — never dropped
   because they're inconvenient to compute, or because current data can't yet
   support them. Where breadth or lap-date metadata is missing, the field is
   still present and reads **"unavailable — [reason]"**; it is never silently
   omitted from the schema. This is the longitudinal guarantee the mission
   promises: the model always shows its work on *how much it knows* and
   *whether it's improving*, even when the honest answer is "not yet."

**Honesty of the guess (required presentation).** Every score is shown as a
model estimate, with its confidence, its evidence count, and a plain statement
of how to raise the confidence — e.g. *"Trail Braking 67 · 71% confident ·
1,428 braking events. This is a model estimate. Upload more Spa laps, or laps
at other tracks and cars, to sharpen it — and if you think it's wrong, tell the
coach why."* The driver can contest any score (annotations already do this).

**Fundamentals we cannot measure are not faked.** Vision/eye-line and tire
slip/utilization have no telemetry signal (proven, locked in the source
contract). They still appear on the pyramid, but their score is "— · 0% · no
telemetry signal," never an invented star. A fundamental with a weak proxy
(e.g. *commitment* from entry-speed retention) gets a low-confidence score that
says so. Confidence is the honesty dial; where there is nothing to see, it is
pinned to zero by construction.

## What AI may and may not do

AI **may**: explain a deterministic score in plain language; summarize the
evidence behind it; recommend the highest-impact practice priority; generate
coaching language and hypotheses (labeled as such).

AI **may not**: produce or adjust a score; invent, estimate, or interpolate any
telemetry number; override a deterministic calculation. Its numeric claims are
mechanically validated against the deterministic payload (the existing
grounding contract), and a score is just another payload number — so this is
enforced, not requested.

## Success criteria

DriverDNA succeeds when:

- Two hundred laps *raise confidence*, not just generate more reports.
- A driver can watch their fundamentals evolve over months.
- Every recommendation answers one question: **"If I have one hour to practice,
  what should I work on to become faster everywhere?"**
- The headline report can eventually describe the *driver* — archetype,
  strengths, weaknesses, primary pace limiter — with little mention of any
  single track or car, and each figure still decomposes to real evidence.

## Relationship to the existing constitution

The nine philosophy principles in `docs/SPEC.md` remain binding, with one
refinement recorded here and mirrored there (SPEC amendment A14): principle 4
("no overall score") becomes "no *opaque* blended score; deterministic,
versioned, confidence-qualified scores are a core output and always decompose
to their separated sources." Everything else — determinism, AI never computes a
measurement, the UI never computes a measurement, traceability, "insufficient
data" as a valid result, env-only secrets — stands unchanged and now protects
the Driver Model too.
