# DriverDNA — Coaching Intelligence (COACHING.md) · M7 design

Status: **design for review, nothing built.** This is both the coaching
constitution (the voice and its rules) and the M7 milestone spec (the ontology,
the grounding mechanism, the seed principle set). It sits under
`docs/ARCHITECTURE_VISION.md` (the *why*) and beside `docs/SPEC.md` (the engine
*how*). Where they meet: the engine measures, the Driver Model (M6) scores, and
**Coaching Intelligence (M7) turns scores into what a good instructor would
actually say — grounded in the same evidence, never improvised.**

## The problem this solves

A telemetry tool says *"brake-release slope decreased 17%."* A coach says
*"you're letting the front tires off the hook before they finish slowing the
car, so they've got nothing left when you ask them to steer."* Same event, two
different languages. Today DriverDNA's AI speaks the second language, but it
*improvises* it — our grounding validator checks that every **number** traces to
evidence, and nothing checks the **coaching concepts**. So a plausible-but-wrong
mental model can pass review as long as it cites the right numbers. M7 closes
that: coaching language becomes a **selection from a fixed, evidence-triggered
ontology**, not free LLM prose.

## The prime coaching rule

> **The driver's data decides *whether* to say something. The ontology decides
> *how* to say it. Neither the AI nor a book ever decides *that* something is
> true of this driver.**

Three consequences, binding:

1. **Coaching is interpretation, not measurement.** Every coaching statement is
   the *"why we think this helps"* around a deterministic finding — labeled as
   interpretation, exactly like the existing `hypotheses` discipline. It never
   claims to be a measured fact about the driver.
2. **Books lend language, not authority.** Racing instruction (Bentley, Barber,
   Bondurant, *Going Faster*, *Speed Secrets*, …) is where the *vocabulary and
   mental models* come from — decades of instructors converging on what works.
   We extract the enduring **concepts** and express them **in our own words**.
   We never reproduce copyrighted text, structure, or drills verbatim, and we
   **never justify advice with "an author said so."** The justification is always
   this driver's evidence plus sound vehicle dynamics.
3. **"Insufficient data" applies to coaching too.** If no coaching principle is
   triggered by the data, the coach says *"not enough to coach this yet"* — never
   filler to fill a silence.

## The coaching ontology (extends the M6 pyramid)

M6 gives us `observable → technique → fundamental` (the *what*). M7 adds a second
facet hanging off each **technique**:

```
Technique  (e.g. Brake Release)
  ├── Driving Principle   — the vehicle-dynamics "why" (physics, universal)
  └── Coaching Principle  — how an instructor expresses + drills it (our words)
```

A **CoachingPrinciple** is a structured, versioned object:

```
id                    "cp.brake_release.finish_the_front"
technique             "brake_release"
fundamental           "braking"
driving_principle     "Front tires can't both decelerate and steer at the
                       limit. Releasing brake pressure well before turn-in
                       unloads the front axle before it has finished slowing
                       the car, so there's no grip left to rotate."
coaching_expression   "Let the fronts finish their work before you ask them to
                       steer — trail the brake in, don't drop it."
drill                 "Next session: on medium-speed corners, deliberately
                       delay full brake release ~0.2 s into the corner. Ignore
                       lap time. Feel the car keep pointing at the apex."
trigger               deterministic conditions over THIS driver's measured
                       pattern that must hold for the principle to be eligible
                       (see next section)
evidence_binding      which findings/observables justify it, so the AI cites
                       them (e.g. detector "brake-release-taper", entry-phase
                       vs-self opportunity)
confidence_floor      caps how strongly it's stated when the underlying
                       evidence is thin or proxy-only
version               "coach-onto-v1"
```

The ontology is **the entire vocabulary of coaching the AI is allowed to
speak.** Adding a new coaching concept means adding a versioned principle with
its trigger — a deliberate, reviewable act, exactly like adding a config
threshold. The AI can never introduce a coaching concept that isn't in the
ontology and isn't triggered by the data.

## Trigger-gated selection — the grounding mechanism

This is the crux, and it reuses the machinery we already trust.

**Step 1 — deterministic eligibility (engine, no AI).** From the Driver Model
and findings, the engine computes the set of coaching principles whose
`trigger` conditions are met for this driver/cohort. A trigger is a boolean over
measured quantities — e.g. *"detector `brake-release-taper` fires on ≥ 50 % of
this corner's laps AND the corner's entry-phase vs-self opportunity ≥ the effect
floor."* No principle is eligible unless the data says it applies.

**Step 2 — deterministic ranking (engine, no AI).** Eligible principles are
ranked by impact, reusing the existing signals: cumulative seconds attributable
to the technique, the vs-self rank (opportunity × repeatability), and a bias
toward the highest-opportunity / practicable item. This yields *the one
priority* — deterministically.

**Step 3 — the AI selects and phrases (constrained).** The coach/chat payload
carries the eligible, ranked principles with their evidence. The AI's entire job
is to (a) choose which to lead with, honoring the deterministic ranking, (b)
express the `coaching_expression` and `drill` in fluent, personal instructor
language, and (c) explain it against the cited evidence. It may not invent a
principle, promote an ineligible one, or coach beyond the ontology.

**Step 4 — grounding enforcement (extends the existing validator).** The current
validator rejects unknown evidence IDs and numbers absent from the payload. M7
adds: every coaching statement must cite a `coaching_principle_id` from the
**eligible** set. A response invoking an unknown or ineligible principle, or
asserting a coaching claim with no principle behind it, is rejected and
regenerated once, then surfaced as an error — identical to how an unknown
evidence ID is handled today. (Honest caveat, unchanged: mechanical enforcement
of natural language is approximate; the tests define exactly which violations
are guaranteed caught. What's guaranteed: no ineligible/unknown principle ID,
and no number outside the payload.)

Net: **deterministic decides what to coach and whether; the AI decides only how
to say it, inside a fixed vocabulary.** That is the whole design.

## Voice and vocabulary

The target voice is the **calm engineer who has watched you drive for six
weekends** — not a hype man, not a stats readout. Rules:

- **Speak in mental models and feel, not metrics.** The metric is the trigger;
  the driver never hears it unless they ask.
- **One priority, one drill, one explanation. Never overwhelm.** A session has
  one thing to work on.
- **Process goals over outcomes.** *"Ignore lap time this session; only feel the
  car keep rotating"* — not *"go faster in sector 1."*
- **Consistent identity.** Because the vocabulary is a fixed ontology, the coach
  sounds like the same instructor every time. The goal is a driver eventually
  saying *"I knew it'd tell me to be patient at turn-in"* — a recognizable
  coaching philosophy, not a mood.

Translation, always evidence-triggered (these are `coaching_expression`s, not
free metaphors):

| The engine sees | The coach says |
|---|---|
| brake release completes well before turn-in | "let the fronts finish before you ask them to steer" |
| throttle & brake overlap beyond the blip | "one pedal at a time — hand the car cleanly from brake to throttle" |
| multiple steering corrections entry→apex | "one commitment at turn-in, not a conversation with the wheel" |
| throttle lifts/stabs before full throttle | "roll it on and mean it; if you have to lift, you opened it too early" |
| long coast between brake and throttle | "the car should always be working — shrink the gap where it's doing nothing" |

## Honesty guardrails (recap, binding)

- Coaching principles are **interpretation**, labeled, versioned — never
  measurement.
- **Unmeasurable fundamentals stay uncoached from data.** We can't see your eyes,
  so "vision/commitment" coaching is proxy-only, low-confidence, and says so —
  or stays silent. No confident advice on something we can't observe.
- **Confidence caps tone.** Thin or proxy evidence → the principle is stated
  tentatively ("this *might* be…"), never as a verdict. `confidence_floor` on
  each principle enforces this.
- **No authority-justified advice, no verbatim copyrighted text.** Concepts in
  our own words; justification is always the driver's data.

## Seed coaching-principle set (v1)

Eight principles, each tied to something we **already measure** (the five
detectors + phase attribution), so M7 has real triggers on day one. In our own
words; drills are process-goal framed.

1. **`finish_the_front`** (Braking / brake release) — trigger: `brake-release-taper` fires. *"Trail the brake in; let the fronts finish slowing before they steer."*
2. **`clean_handoff`** (Braking / rotation seam) — trigger: `throttle-brake-overlap` beyond the blip. *"One pedal at a time — hand the car cleanly from brake to throttle."*
3. **`one_commitment`** (Rotation / turn-in) — trigger: `one-steering-input` (corrections > N). *"Settle the entry, then one committed input to the apex."*
4. **`roll_it_on`** (Corner exit / throttle) — trigger: `throttle-monotonic` (stabs before full throttle). *"Pick up later but build smoothly; if you have to lift, you opened too early."*
5. **`always_working`** (Rotation / mid) — trigger: `coast-window` beyond threshold. *"Shrink the coast — the car should always be braking, turning, or driving."*
6. **`carry_the_middle`** (Rotation / minimum speed) — trigger: mid-phase vs-self opportunity high with low apex speed vs baseline. *"Lap time hides in mid-corner speed, not entry bravery."*
7. **`same_lap_twice`** (Consistency) — trigger: high phase spread across laps. *"Match a lap before you try to beat it — repeatability comes before pace."*
8. **`be_patient` (proxy-only)** (Vision / commitment) — trigger: entry-speed-retention proxy; **low confidence, labeled** *"we can't see your eyes."* *"Give the corner a beat before you commit."*

Each ships as data (`coaching_principle_id` + fields above), versioned; weights
and thresholds in `ConfigStore`.

## M7 milestone — scope & done-criteria

**Depends on:** M6 for fundamental-level coaching (scores/trends as triggers).
Note: principles 1–5 trigger off M2 detectors / M3 findings that **already
exist**, so a detector-level subset is groundable on today's engine — but M7 is
sequenced **after M6** so the coach speaks in the Driver Model's terms.

**Build:**
- Coaching ontology as versioned data (the seed set), every principle mapping to
  exactly one technique/fundamental.
- Deterministic **eligibility + ranking engine** (pure function of Driver Model +
  findings; two runs → identical eligible/ranked set).
- Coach/chat payload gains the eligible, ranked principles + evidence bindings.
- **Grounding validator extended**: coaching statements must cite an eligible
  `coaching_principle_id`; ineligible/unknown/invented → rejected.
- Artifact: `driverdna coaching` — per-cohort eligible principles, ranked, with
  triggers shown (the inspectable "why this advice").

**Done when:** eligibility is deterministic and versioned; a mocked-provider
coach/chat response that invokes an ineligible or invented principle is rejected,
not shown; "no eligible principle" yields insufficient-data coaching; every
surfaced piece of advice cites a principle that cites evidence; unmeasurable
fundamentals stay proxy-only/low-confidence or silent.

## Open questions for you to react to

1. **The grounding model** — is "deterministic eligibility + AI phrases within a
   fixed ontology" the right contract? (My strong recommendation: yes — it's the
   only version where coaching can't drift into slop.)
2. **The seed set** — do these eight match how *you* think about coaching? Wrong
   emphasis, missing one, a principle you'd cut?
3. **The voice** — "calm engineer who watched you for six weekends." Right target?
4. **Sequencing** — M7 after M6 as written, or pull the detector-level subset
   (principles 1–5) forward since their triggers already exist?
5. **The library horizon** — start with these eight in our own words and grow
   organically, versus a larger up-front distillation from the instruction books.
