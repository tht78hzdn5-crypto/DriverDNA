"""The coaching ontology (M7): the entire vocabulary the AI is allowed to
speak (docs/COACHING.md). Versioned static data, not computed — adding a
concept means adding a principle here, a deliberate reviewable act, exactly
like adding a config threshold.

Every principle maps to exactly one taxonomy.py technique (measured/proxy)
or fundamental (no_signal), so `signal_status` here is never invented
independently of M6's own tri-state rule — see test_coaching_ontology.py's
cross-check.

Gate descriptors (`DetectorGate`, `MetricCVGate`, `FindingGate`,
`AlwaysEligible`) are declarative: coaching/engine.py interprets them
against a cohort's real DB rows. Keeping the gate as data alongside the
principle (rather than a bespoke function per principle) is what makes
"adding a coaching concept" stay a data change, not new eligibility code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from driverdna.model.taxonomy import FUNDAMENTALS, TECHNIQUES, SignalStatus

ONTOLOGY_VERSION = "coach-onto-v1"


@dataclass(frozen=True)
class DetectorGate:
    """Eligible where `detector`'s trigger rate on a corner reaches the
    shared pattern floor (config.detectors.min_trigger_rate) — the same
    floor a vs-principle finding uses, reused rather than duplicated."""

    detector: str


@dataclass(frozen=True)
class MetricCVGate:
    """Eligible where `metric`'s coefficient of variation on a corner
    reaches `floor_key` (a CoachingConfig field name, resolved by the
    engine — kept as a name, not a copied float, so the threshold has one
    home in ConfigStore)."""

    metric: str
    floor_key: str


@dataclass(frozen=True)
class FindingGate:
    """Eligible where a `phase` vs-self finding for the corner is already
    `shown` (reuses ranker.vs_self_findings's own tested gates, rather than
    inventing a parallel statistical test)."""

    phase: str


@dataclass(frozen=True)
class AlwaysEligible:
    """no_signal only: never gated on data, never the headline (see
    docs/COACHING.md's `trigger` field note — "quiet-only, never the
    headline" IS the trigger for a no_signal principle)."""


Gate = DetectorGate | MetricCVGate | FindingGate | AlwaysEligible


@dataclass(frozen=True)
class SelfCheck:
    instruction: str
    label: str
    basis: str


@dataclass(frozen=True)
class CoachingPrinciple:
    id: str
    technique: str
    fundamental: str
    signal_status: SignalStatus
    driving_principle: str
    gate: Gate
    band_phase: str | None  # phase to band via cumulative_loss; None = band by CV
    coaching_expression: str | None = None  # measured/proxy only
    drill: str | None = None  # measured/proxy only
    self_check: SelfCheck | None = None  # no_signal only
    evidence_binding: tuple[str, ...] = field(default_factory=tuple)


PRINCIPLES: dict[str, CoachingPrinciple] = {
    p.id: p
    for p in (
        CoachingPrinciple(
            id="cp.brake_release.finish_the_front",
            technique="brake_release", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "Front tires can't both decelerate and steer at the limit. "
                "Releasing brake pressure well before turn-in unloads the "
                "front axle before it has finished slowing the car, so "
                "there's no grip left to rotate."
            ),
            gate=DetectorGate("brake-release-taper"),
            band_phase="entry",
            coaching_expression=(
                "Let the fronts finish their work before you ask them to "
                "steer — trail the brake in, don't drop it."
            ),
            drill=(
                "Next session: on medium-speed corners, deliberately delay "
                "full brake release ~0.2 s into the corner. Ignore lap "
                "time. Feel the car keep pointing at the apex."
            ),
            evidence_binding=("brake-release-taper", "entry cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.pedal_overlap.clean_handoff",
            technique="pedal_overlap", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "Throttle and brake fighting each other confuses the "
                "weight transfer the car needs to plant one axle at a "
                "time. Beyond a deliberate heel-toe blip, overlap just "
                "burns the front brakes against the rear tires."
            ),
            gate=DetectorGate("throttle-brake-overlap"),
            band_phase="entry",
            coaching_expression=(
                "One pedal at a time — hand the car cleanly from brake to "
                "throttle."
            ),
            drill=(
                "Next session: find the exact moment you're fully off the "
                "brake before any throttle. Widen that gap if it's "
                "currently negative."
            ),
            evidence_binding=("throttle-brake-overlap", "entry cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.turn_in.one_commitment",
            technique="turn_in", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "Every extra steering correction between turn-in and apex "
                "is the car negotiating a line you haven't committed to — "
                "each one scrubs speed the corner didn't need to lose."
            ),
            gate=DetectorGate("one-steering-input"),
            band_phase="mid",
            coaching_expression=(
                "Settle the entry, then one committed input to the apex."
            ),
            drill=(
                "Next session: pick your turn-in point before the corner "
                "and commit to a single steering input. Ignore lap time; "
                "count your own corrections."
            ),
            evidence_binding=("one-steering-input", "mid cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.throttle_pickup.roll_it_on",
            technique="throttle_pickup", fundamental="corner_exit",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "A lift after picking up throttle means the pickup point "
                "was a guess, not a commitment — the car had to give back "
                "grip mid-application it never should have been asked for."
            ),
            gate=DetectorGate("throttle-monotonic"),
            band_phase="exit",
            coaching_expression=(
                "Pick up later but build smoothly; if you have to lift, "
                "you opened it too early."
            ),
            drill=(
                "Next session: delay throttle pickup slightly and apply "
                "it as one continuous build to full throttle — no stabs, "
                "no lifts."
            ),
            evidence_binding=("throttle-monotonic", "exit cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.coasting.always_working",
            technique="coasting", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "Neither pedal working means neither axle is doing "
                "anything useful — the car coasts through time that "
                "braking, turning, or driving could have used."
            ),
            gate=DetectorGate("coast-window"),
            band_phase="mid",
            coaching_expression=(
                "Shrink the coast — the car should always be braking, "
                "turning, or driving."
            ),
            drill=(
                "Next session: find where you're on neither pedal "
                "mid-corner and close that gap by a fraction — brake a "
                "touch later or pick up throttle a touch sooner."
            ),
            evidence_binding=("coast-window", "mid cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.rotation_efficiency.carry_the_middle",
            technique="rotation_efficiency", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "Mid-corner speed compounds down the following straight; "
                "an entry-braking gain rarely does. A real, repeatable "
                "gap between your faster and slower laps through the "
                "middle of a corner is where the lap time actually is."
            ),
            # Reuses the tested vs-self finding gate directly rather than a
            # bespoke statistical test: a shown mid-phase finding already
            # means "opportunity cleared its floor and gates" — which is
            # what "low apex speed vs baseline" is measuring underneath.
            gate=FindingGate("mid"),
            band_phase="mid",
            coaching_expression=(
                "Lap time hides in mid-corner speed, not entry bravery."
            ),
            drill=(
                "Next session: on this corner, ignore your braking point "
                "entirely. Only chase the number on the speedo at the "
                "apex."
            ),
            evidence_binding=("vs-self mid-phase finding",),
        ),
        CoachingPrinciple(
            id="cp.repeatability.same_lap_twice",
            technique="repeatability", fundamental="consistency",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "A technique that varies lap to lap isn't a technique yet "
                "— it's a range of outcomes. Pace built on an inconsistent "
                "input is pace you can't reliably reproduce under "
                "pressure."
            ),
            gate=MetricCVGate(metric="*", floor_key="consistency_cv_floor"),
            band_phase=None,  # consistency is cross-cutting (taxonomy.py) — bands on its own CV
            coaching_expression=(
                "Match a lap before you try to beat it — repeatability "
                "comes before pace."
            ),
            drill=(
                "Next session: try to execute this corner exactly the "
                "same way three laps in a row. Ignore lap time; judge "
                "yourself only on how close the three felt."
            ),
            evidence_binding=("pooled measured-metric coefficient of variation",),
        ),
        CoachingPrinciple(
            id="cp.entry_commitment.trust_the_proxy",
            technique="entry_commitment", fundamental="commitment",
            signal_status=SignalStatus.PROXY,
            driving_principle=(
                "Brake-point timing is an indirect stand-in for entry "
                "commitment, not a direct measurement of it — a moving "
                "brake point can mean the driver is protecting margin "
                "rather than driving to the corner's actual limit."
            ),
            gate=MetricCVGate(metric="brake_point_dist_pct", floor_key="commitment_cv_floor"),
            band_phase="entry",
            coaching_expression=(
                "This might be about commitment more than outright speed "
                "— you're giving up entry speed sooner than the corner "
                "needs."
            ),
            drill=(
                "Worth testing: hold your entry line half a beat longer "
                "and see if the exit actually gets worse."
            ),
            evidence_binding=("brake_point_dist_pct coefficient of variation",),
        ),
        CoachingPrinciple(
            id="cp.eye_line.look_further",
            technique="eye_line", fundamental="vision",
            signal_status=SignalStatus.NO_SIGNAL,
            driving_principle=(
                "Where the eyes point is where the hands steer toward. "
                "Looking at the apex instead of through it tends to "
                "produce a line that arrives at the apex correctly and "
                "has nowhere good to go after it."
            ),
            gate=AlwaysEligible(),
            band_phase=None,  # no_signal: no gap band, quiet self-check only
            self_check=SelfCheck(
                instruction=(
                    "Say out loud where you're looking the instant you "
                    "turn in. If you can't answer before you're already "
                    "at the apex, you're looking too late."
                ),
                label="coaching hypothesis, not a measurement — we can't see your eyes",
                basis=(
                    "Where the eyes point is where the hands tend to "
                    "steer toward; there is no eye-tracking channel in "
                    "the telemetry, so this can never be measured, only "
                    "self-tested."
                ),
            ),
            evidence_binding=(),
        ),
    )
}


def principles_for_fundamental(fundamental_id: str) -> tuple[CoachingPrinciple, ...]:
    return tuple(sorted(
        (p for p in PRINCIPLES.values() if p.fundamental == fundamental_id),
        key=lambda p: p.id,
    ))
