# DriverDNA — Coaching Intelligence (COACHING.md) · M7 design

Status: **design ADOPTED (owner decision, 2026-07-20) — built (2026-07-20).**
This is the M7 spec Claude Code implemented against — see docs/SPEC.md's
"Milestone 7" section for the build summary, including two ambiguities in
this document that were resolved (and flagged, not picked silently) during
implementation: headline eligibility requires the notable/major gap band
specifically (this doc's "moderate...never headline" vs. "insufficient data
if nothing clears moderate" read as slightly inconsistent — the more specific,
more repeated rule won), and gap band (volume) and `signal_status`
(conviction) turned out to need to be independent axes, not one field
governing both. This is both the coaching constitution (the voice and its
rules) and the M7 milestone spec (the ontology, the grounding mechanism, the
seed principle set). It sits under
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

A **CoachingPrinciple** is a structured, versioned object. Its shape depends on
`signal_status` — this is the field that keeps a confidence number from ever
being bolted onto something we can't measure (see "Conviction where measured,
silence or self-check where not," below).

```
id                    "cp.brake_release.finish_the_front"
technique             "brake_release"
fundamental           "braking"
signal_status         "measured"   — measured | proxy | no_signal.
                       measured: trigger is a real detector/finding/opportunity.
                       proxy: trigger is a weak, indirect stand-in (labeled as
                       such wherever shown).
                       no_signal: the fundamental has no telemetry channel at
                       all (vision/eye-line, tire slip). A no_signal principle
                       NEVER carries coaching_expression, confidence_floor, or
                       any confidence value — it carries self_check instead.
driving_principle     "Front tires can't both decelerate and steer at the
                       limit. Releasing brake pressure well before turn-in
                       unloads the front axle before it has finished slowing
                       the car, so there's no grip left to rotate."
coaching_expression   "Let the fronts finish their work before you ask them to
                       steer — trail the brake in, don't drop it."
                       (measured/proxy only — omitted when signal_status is
                       no_signal)
drill                 "Next session: on medium-speed corners, deliberately
                       delay full brake release ~0.2 s into the corner. Ignore
                       lap time. Feel the car keep pointing at the apex."
                       (measured/proxy only)
self_check            a driver-runnable check performed IN THE CAR, replacing
                       coaching_expression + drill when signal_status is
                       no_signal (see the dedicated section below). Present
                       only on no_signal principles.
trigger               deterministic conditions over THIS driver's measured
                       pattern that must hold for the principle to be eligible
                       (see next section). For a no_signal principle there is
                       no measured pattern to trigger on — it is always
                       eligible for quiet, self-check delivery (offered as a
                       labeled hypothesis alongside or after the loud, measured
                       headline) and NEVER eligible to lead or to be delivered
                       loud. That restriction — quiet-only, never the headline
                       — is itself the "trigger."
evidence_binding      which findings/observables justify it, so the AI cites
                       them (e.g. detector "brake-release-taper", entry-phase
                       vs-self opportunity). Empty/absent for no_signal
                       principles — there is no evidence, which is the point.
confidence_floor      caps how strongly a MEASURED or PROXY principle is
                       stated when its own evidence is thin (few laps, wide
                       spread). Absent — not zero, ABSENT — on no_signal
                       principles: they don't get a softened confidence
                       number, they don't get any confidence number.
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

**Step 2 — deterministic ranking and gap-band tone (engine, no AI).** Eligible
principles are ranked by impact, reusing the existing signals: cumulative
seconds attributable to the technique, the vs-self rank (opportunity ×
repeatability), and a bias toward the highest-opportunity / practicable item.
This yields *the one priority* — deterministically. The **magnitude** of that
impact is also bucketed into a **gap band** (`negligible` / `moderate` /
`notable` / `major`), which controls how confidently it's delivered — loud on
a real, sizeable gap; quiet on a small one; silent below the floor. Mechanics
in "Gap bands," below.

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

### Gap bands — mechanics

*(Formalizing intent from prior discussion into a concrete rule; flag if this
diverges from what was scoped earlier — nothing here is built yet, so it's
cheap to correct.)*

Not every eligible principle deserves the same tone, and the strict M3/M6
finding-level statistical gates (≥ 10 phase samples, ≥ 2 sessions) shouldn't be
the only lever the coach has for confidence — a driver with four laps still has
*something* real and sizeable to hear about, even if no individual finding has
cleared full statistical significance yet.

- Every technique-level measured quantity a principle can trigger on
  (cumulative typical loss vs. baseline from M3's `cumulative_loss`, or a
  detector's trigger rate from M2) is bucketed into a band by **absolute,
  versioned thresholds in `ConfigStore`** — seconds of loss, or a trigger-rate
  floor. Banding adds **no new number**; it's a coarser label on one already
  computed.
- **Bands are looser-gated than statistical findings, on purpose.**
  `cumulative_loss` is a plain measured median — it exists, and is usually
  nonzero, well before a corner's phase clears the sample/session bar a
  *finding* needs to be `shown`. That's why there's typically something real
  to point to even early in a driver's data: the coarse signal arrives before
  the fine-grained one does. It is still a real, engine-computed number —
  never invented for the coach's convenience.
- **Delivery tone by band:**
  - `major` / `notable` → **loud.** The coach commits to it as the session's
    one priority, states the drill plainly. No hedging.
  - `moderate` → **quiet.** Mentioned only if asked, or as a minor secondary
    note — never the headline.
  - `negligible` → **silent.** Not surfaced. This isn't where the time is.
- **The headline never lowers the bar to have something to say.** Ranking
  (Step 2) picks the single largest gap-band-eligible item to lead. If
  *nothing* clears `moderate` — one lap, or a driver whose laps are already
  near-identical — the coach says exactly that: insufficient data for the
  headline slot too. "There's usually plenty visible" describes what real
  driving data looks like; it is never a license to manufacture a loud-sounding
  priority out of noise.
- **Gap bands govern tone, not truth.** A `major`-band item still cites only
  the evidence actually behind it — a real cumulative-loss number, not a
  fabricated N or confidence it hasn't earned. If the driver asks "how sure
  are you," the honest answer is the real evidence, including "this isn't
  fully gated yet, n=4" when that's what it is. Loud tone is about conviction
  in *what to work on*, never about overstating *how well-measured* it is.

Net: **deterministic decides what to coach and whether, and how loud to say it;
the AI decides only how to phrase it, inside a fixed vocabulary.** That is the
whole design.

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
  saying *"I knew it'd tell me to let the fronts finish before I turn in"* — a
  recognizable coaching philosophy, not a mood.

Translation, always evidence-triggered (these are `coaching_expression`s, not
free metaphors):

| The engine sees | The coach says |
|---|---|
| brake release completes well before turn-in | "let the fronts finish before you ask them to steer" |
| throttle & brake overlap beyond the blip | "one pedal at a time — hand the car cleanly from brake to throttle" |
| multiple steering corrections entry→apex | "one commitment at turn-in, not a conversation with the wheel" |
| throttle lifts/stabs before full throttle | "roll it on and mean it; if you have to lift, you opened it too early" |
| long coast between brake and throttle | "the car should always be working — shrink the gap where it's doing nothing" |

## Conviction where measured, silence or self-check where not (owner decision, 2026-07-20)

COACHING.md previously said "confidence caps tone" and left it there — which
under-specified the failure mode that actually matters: a confidence *number*
can itself become the lie, dressing up a guess as a measurement. This section
replaces the old "Confidence caps tone" bullet with the binding rule and its
two consequences.

> **A confidence value never launders an unmeasured inference.**

- **On measured ground** — the trigger is a real detector, finding, or
  opportunity — **the coach commits.** No hedging, no "might," no qualifier
  salad. State the priority and the drill like a coach who is sure, because
  the data is sure. `confidence_floor` here only softens phrasing when the
  *measured* evidence itself is thin (few laps, wide spread) — it never turns
  real signal into false bravado, and it never turns real signal into mush
  either. This is what fixes "too hedged to be useful" without loosening the
  grounding: the fix isn't "hedge less everywhere," it's "hedge exactly where
  the ground is actually soft, and nowhere else."
- **On no-signal ground** — the fundamental has no telemetry channel at all
  (vision/eye-line, tire slip/utilization) — **the principle carries no score
  and no confidence value, at any level.** *"Vision, 30% confident"* is
  forbidden: a low number bolted onto a no-signal claim is a guess wearing the
  costume of rigor, and it is worse than silence, because it *looks*
  disciplined and a driver will practice it. No-signal fundamentals never emit
  a score. They carry a **self-check** instead (next section).
- **On proxy ground** — a weak, indirect measurement (e.g. commitment via
  entry-speed retention) — the principle is explicitly labeled `proxy` and
  stated tentatively ("this *might* be…"). This is the one place a soft
  qualifier belongs, because it's the one place there's some real signal, just
  known to be indirect. `confidence_floor` governs this tone.

Loud on measured ground. Quiet — or a self-check, never a fake number — on
ground we can't measure. Nothing here is optional: `signal_status` is what a
principle's schema enforces (previous section), this is *why*.

**Constitution check (same edit).** Does "— · 0% · no telemetry signal" in
`ARCHITECTURE_VISION.md`'s Scoring Contract contradict "no confidence value at
any level"? No — that "0%" is a fixed, invariant *not-applicable* marker,
identical on every no-signal fundamental, chosen by nobody and never varying.
It can't be mistaken for a real degree of belief the way a graduated "30%"
can. The Driver Model's score table (M6) never fakes a *number*; the coaching
layer (M7) never fakes a *confidence*. Same rule, two layers.

## Self-checks replace scores for no-signal fundamentals (owner decision, 2026-07-20)

A no-signal fundamental doesn't get a hedged score — it gets a **self-check**:
a short, driver-runnable exercise performed *in the car*, because the driver
is the sensor the telemetry doesn't have. This turns "we can't measure this"
from an apology into a coaching move, and it's the piece that makes the tool
feel like a coach instead of a gauge.

A **self-check** is a structured field on a `no_signal` `CoachingPrinciple`:

```
self_check.instruction   what the driver does, in the car, to test the idea
                          themselves (e.g. "say out loud where you're looking
                          the instant you turn in — if you can't answer before
                          you're at the apex, you're looking too late")
self_check.label         always shown alongside it: "coaching hypothesis, not
                          a measurement" (or equivalent) — never omitted
self_check.basis         the driving principle behind it, in plain language,
                          same as any other principle's driving_principle
```

No score field, no confidence field — the object literally has nowhere to put
one.

**What a 10-second driver hears** (illustrative phrasing, not literal UI copy —
note the loud/measured half never recites a raw number either; per Voice and
Vocabulary, the driver hears mental models, the metric is the trigger, not the
message):

> *"Your biggest loss right now is mid-corner speed at C09 — Pouhon. This
> session: carry more speed through the apex before you think about the exit.
> Don't chase lap time — chase the number on the speedo at the apex."*
>
> *"One more thing, and I want to be straight about this: I can't see your
> eyes, so I can't measure whether you're looking through the corner early
> enough — that's a coaching hypothesis, not something in your telemetry. Try
> it yourself next session: say out loud where you're looking the instant you
> turn in. If you can't answer before you're already at the apex, you're
> looking too late."*

Loud, coarse, and confident on the measured gap (there's always something
real once there's more than a lap or two — see Gap bands). Then the
unmeasurable fundamental offered as a clearly labeled hypothesis with a way
for the driver to test it themselves — never a percentage.

**Constitution check (same edit).** Self-checks are **interpretation, not
measurement** — clean under philosophy #2 (AI never computes or invents a
measurement; a self-check is a suggested exercise, not a number, and the AI's
only role is to phrase a self-check that's already in the ontology, same as
any other coaching_expression). They're also what philosophy #3
("insufficient data" is a first-class result) *does* here instead of going
mute — a first-class "we don't know" can still hand the driver something
useful to do; it doesn't have to be a dead end. And they don't contradict
`ARCHITECTURE_VISION.md`'s Scoring Contract: a no-signal fundamental still
shows "— · 0% · no telemetry signal" wherever the **Driver Model** (M6)
presents its score table — that's unchanged. The self-check is what the
**coaching layer** (M7) offers in the slot where a scored fundamental would
offer a drill. M6 never fakes a number; M7 never fakes a confidence; neither
contradicts the other.

## Honesty guardrails (recap, binding)

- Coaching principles are **interpretation**, labeled, versioned — never
  measurement.
- **`signal_status` governs everything.** `measured` → commit. `proxy` →
  labeled and tentative. `no_signal` → self-check, never a score or
  confidence value at any level (see above).
- **No authority-justified advice, no verbatim copyrighted text.** Concepts in
  our own words; justification is always the driver's data.

## Seed coaching-principle set (v1)

Nine principles (was eight — see the fix at #8/#9 below), each tied to
something we **already measure** or explicitly marked for what it isn't. In our
own words; drills/self-checks are process-goal framed. `signal_status` shown
for every entry now, not just the edge case, so the pattern is visible
throughout.

1. **`finish_the_front`** [measured] (Braking / brake release) — trigger: `brake-release-taper` fires. *"Trail the brake in; let the fronts finish slowing before they steer."*
2. **`clean_handoff`** [measured] (Braking / rotation seam) — trigger: `throttle-brake-overlap` beyond the blip. *"One pedal at a time — hand the car cleanly from brake to throttle."*
3. **`one_commitment`** [measured] (Rotation / turn-in) — trigger: `one-steering-input` (corrections > N). *"Settle the entry, then one committed input to the apex."*
4. **`roll_it_on`** [measured] (Corner exit / throttle) — trigger: `throttle-monotonic` (stabs before full throttle). *"Pick up later but build smoothly; if you have to lift, you opened too early."*
5. **`always_working`** [measured] (Rotation / mid) — trigger: `coast-window` beyond threshold. *"Shrink the coast — the car should always be braking, turning, or driving."*
6. **`carry_the_middle`** [measured] (Rotation / minimum speed) — trigger: mid-phase vs-self opportunity high with low apex speed vs baseline. *"Lap time hides in mid-corner speed, not entry bravery."*
7. **`same_lap_twice`** [measured] (Consistency) — trigger: high phase spread across laps. *"Match a lap before you try to beat it — repeatability comes before pace."*
8. **`trust_the_proxy`** [**proxy**] (Commitment) — trigger: entry-speed-retention proxy crosses its floor. Stated tentatively, `confidence_floor` applied: *"This might be about commitment more than outright speed — you're giving up entry speed sooner than the corner needs. Worth testing: hold your entry line half a beat longer and see if the exit actually gets worse."*
9. **`look_further`** [**no_signal**] (Vision / eye-line) — no trigger; always eligible for quiet, self-check-only delivery, never the headline (see the `trigger` field note, above). **Fixes seed-eight defect:** the original `be_patient` conflated a measurable-but-weak fundamental (commitment, → #8, proxy) with a truly unmeasurable one (vision/eye-line, no telemetry channel at all) under one id, and described the latter as "low confidence, labeled" — exactly the pattern the new rule forbids. Split cleanly: `self_check.instruction`: *"Say out loud where you're looking the instant you turn in. If you can't answer before you're already at the apex, you're looking too late."* `self_check.label`: "coaching hypothesis, not a measurement — we can't see your eyes." No score, no confidence, at any level.

Each ships as data (`coaching_principle_id` + fields above), versioned; weights
and thresholds in `ConfigStore`.

## M7 milestone — scope & done-criteria

**Depends on:** M6 for fundamental-level coaching (scores/trends as triggers).
Note: principles 1–5 trigger off M2 detectors / M3 findings that **already
exist**, so a detector-level subset is groundable on today's engine — but M7 is
sequenced **after M6** so the coach speaks in the Driver Model's terms.

**Build:**
- Coaching ontology as versioned data (the seed set), every principle mapping to
  exactly one technique/fundamental, every principle carrying `signal_status`.
- Deterministic **eligibility + ranking + gap-band engine** (pure function of
  Driver Model + findings + `cumulative_loss`; two runs → identical
  eligible/ranked/banded set). Gap-band thresholds versioned in `ConfigStore`.
- Coach/chat payload gains the eligible, ranked, banded principles + evidence
  bindings; `no_signal` principles carry `self_check`, never a confidence field.
- **Grounding validator extended**: coaching statements must cite an eligible
  `coaching_principle_id`; ineligible/unknown/invented → rejected. **A response
  attaching any confidence/percentage language to a `no_signal` principle is
  rejected**, same mechanism, new check.
- Artifact: `driverdna coaching` — per-cohort eligible principles, ranked, with
  triggers and gap bands shown (the inspectable "why this advice, and why this
  loud").

**Done when:** eligibility, ranking, and gap-band assignment are deterministic
and versioned; a mocked-provider coach/chat response that invokes an ineligible
or invented principle is rejected, not shown; a response putting a confidence
value on a `no_signal` principle is rejected, not shown; "nothing clears
`moderate`" yields insufficient-data coaching for the headline slot, not a
manufactured priority; every surfaced piece of advice cites a principle that
cites evidence (or, for `no_signal`, is clearly labeled a self-check); no
`no_signal` principle ever renders with a score or confidence, at any level,
in any test.

## Status of the open questions (updated 2026-07-20)

1. **The grounding model** — **adopted as written**: deterministic eligibility
   + AI phrases within a fixed ontology.
2. **Conviction/silence and self-checks** — **adopted, this edit** (the two
   sections above): loud on measured ground, self-check (never a laundered
   confidence) on no-signal ground.
3. **Gap-band eligibility** — **adopted, formalized this edit, built
   2026-07-20**. During implementation, two sentences in this section read as
   mutually inconsistent ("moderate...never headline" vs. "insufficient data
   if nothing clears moderate") — resolved in favor of the more specific,
   more repeated rule (headline requires notable/major); flag if the intended
   reading was actually the looser one.
4. **The seed set** — nine principles now (the vision/commitment split fixes a
   defect the new rules exist to catch). **Built as specified**, unchanged.
   Still open: does the rest of the set match your read of coaching
   priorities? Anything to cut or add?
5. **The voice** — "calm engineer who watched you for six weekends" stands
   unless corrected. Encoded in the coach/chat system prompts as of the M7
   build; not yet exercised against a live provider (mocked-provider tests
   only, same as M4/M5).
6. **Sequencing** — M7 after M6 stands as written; built after M6 as
   specified.
7. **The library horizon** — starting with this seed set and growing
   organically stands unless corrected.

Items 4–7 default to what's written above per no correction received; flag any
of them and they change in a future revision — the ontology is versioned data
specifically so that's cheap.

## A second grounded-citation surface: incidents (2026-07-21, SPEC.md A20)

Findings aren't the only thing the coach can now cite — a detected incident
(`incidents/detector.py` + `classify.py`, SPEC.md A19) can be too, through the
same trigger-gated discipline this document specifies for findings: the
engine decides eligibility deterministically (a fixed `classification ->
coaching_principle_id` map, `incidents/coaching.py`, reusing this document's
existing seed set — no new principles), the AI only narrates, and the
mechanical validator rejects any deviation exactly as it rejects an unknown
evidence ID or an ineligible `coaching_principle_id`. The one incident-specific
rule beyond what findings already require: the cited principle must match the
engine's verdict *exactly*, not merely be "an eligible principle" — the
mapping is 1:1, so there's nothing for the AI to choose. `unclassified`/
`external` incidents map to no principle and cannot be explained at all,
mirroring a `no_signal` fundamental one level down.
