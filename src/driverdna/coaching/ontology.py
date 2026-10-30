"""The coaching ontology (M7): the entire vocabulary the AI is allowed to
speak (docs/COACHING.md). Versioned static data, not computed — adding a
concept means adding a principle here, a deliberate reviewable act, exactly
like adding a config threshold.

Every principle maps to exactly one taxonomy.py technique (measured/proxy)
or fundamental (no_signal), so `signal_status` here is never invented
independently of M6's own tri-state rule — see test_coaching_ontology.py's
cross-check.

Gate descriptors (`DetectorGate`, `MetricDispersionGate`, `MetricStatGate`,
`FindingGate`, `AlwaysEligible`) are declarative: coaching/engine.py interprets them
against a cohort's real DB rows. Keeping the gate as data alongside the
principle (rather than a bespoke function per principle) is what makes
"adding a coaching concept" stay a data change, not new eligibility code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from driverdna.model.taxonomy import SignalStatus

ONTOLOGY_VERSION = "coach-onto-v8"


@dataclass(frozen=True)
class DetectorGate:
    """Eligible where `detector`'s trigger rate on a corner reaches the
    shared pattern floor (config.detectors.min_trigger_rate) — the same
    floor a vs-principle finding uses, reused rather than duplicated."""

    detector: str


@dataclass(frozen=True)
class MetricDispersionGate:
    """Eligible where `metric`'s normalized scaled-MAD dispersion on a
    corner reaches `floor_key` (a CoachingConfig field name, resolved by
    the engine — kept as a name, not a copied float, so the threshold has
    one home in ConfigStore).

    The statistic is dm-v3's (SPEC.md A56), migrated to coaching by A58
    (BUG-044): per-metric scaled MAD divided by the metric's measured
    reference dispersion, pooled two levels (mean within each unit, then
    mean across units) when `metric` is "*". A coefficient of variation
    is the wrong statistic here — it divides by the sample's own mean,
    so a position metric's reading tracks where its landmark sits as
    much as how much it moves. The old `MetricCVGate` is removed, not
    kept alongside: two gate types reading the same evidence with
    different statistics would double-speak."""

    metric: str
    floor_key: str


@dataclass(frozen=True)
class MetricStatGate:
    """Eligible where a per-corner statistic of one metric crosses a
    floor (coach-onto-v5, SPEC.md A57) — for measured techniques whose
    fault is a LEVEL or a SPREAD of a metric rather than a detector
    pattern or a coefficient of variation.

    `stat` is "median" (the corner's typical lap) or "iqr" (the
    interquartile range of the corner's laps, in the metric's own
    units — a dispersion that never divides by a mean, so a position
    metric whose mean approaches zero cannot explode it the way a CV
    does). `direction` is "below" (eligible at or under the floor) or
    "above" (eligible at or over it). `floor_key` names a
    CoachingConfig field, resolved by the engine like MetricDispersionGate's.

    `guard_metric`/`guard_floor_key` optionally scope the corner: the
    guard metric's median must reach the guard floor before the corner
    is in scope at all (e.g. only judge entry technique where a
    substantial braking event exists). Out of scope means neither a
    candidate nor a strength — the corner is not being judged, not
    being praised.
    """

    metric: str
    stat: str  # "median" | "iqr"
    direction: str  # "below" | "above"
    floor_key: str
    guard_metric: str | None = None
    guard_floor_key: str | None = None


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


Gate = DetectorGate | MetricDispersionGate | MetricStatGate | FindingGate | AlwaysEligible


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
    #: What to say when the driver is CLEARING this principle's gate on real
    #: evidence (A51). measured/proxy only — a no_signal principle can never
    #: become a strength, because nothing was measured to be good at.
    strength_expression: str | None = None
    #: Tendency-framed variants keyed by fault state (A59, Stage 2):
    #: a persistent framing naming the habit, not the corner, and a
    #: resolved framing acknowledging the fix and citing the era it
    #: stopped. Templates, filled with the pattern's era facts at render
    #: time. Empty for principles with no bespoke framing — the generic
    #: state line carries those. measured/proxy only.
    tendency_variants: dict[str, str] = field(default_factory=dict)
    #: The escalated second assignment for a persistent pattern (A59).
    #: Rendered only when the pattern's tendency state is persistent.
    #: measured/proxy only.
    drill_followup: str | None = None
    self_check: SelfCheck | None = None  # no_signal only
    evidence_binding: tuple[str, ...] = field(default_factory=tuple)


PRINCIPLES: dict[str, CoachingPrinciple] = {
    p.id: p
    for p in (
        CoachingPrinciple(
            id="cp.brake_release.finish_the_front",
            technique="brake_release", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Dropping the fronts at turn-in keeps showing up, "
                    "era after era ({eras_fired} of {eras_total}) — this "
                    "is the release habit, not one corner."
                ),
                "resolved": (
                    "The abrupt release stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. The fronts stay loaded now."
                ),
            },
            drill_followup=(
                "Second assignment: on your fastest corner, release the "
                "brake in two distinct stages and note where the car "
                "starts to push — then move the second stage later by a "
                "car length."
            ),
            driving_principle=(
                "Front tires can't both decelerate and steer at the limit. "
                "Releasing brake pressure well before turn-in unloads the "
                "front axle before it has finished slowing the car, so "
                "there's no grip left to rotate."
            ),
            gate=DetectorGate("brake-release-taper"),
            band_phase="entry",
            coaching_expression=(
                "Your brake release is too abrupt. Trail the brake in gracefully; "
                "let the fronts bite and finish decelerating before you ask them to steer."
            ),
            drill=(
                "Next session: on medium-speed corners, deliberately delay "
                "full brake release ~0.2 s into the corner. Ignore lap "
                "time. Feel the car keep pointing at the apex."
            ),
            strength_expression=(
                "Your brake release is doing its job — the fronts stay "
                "loaded into the corner instead of being dropped at turn-in."
            ),
            evidence_binding=("brake-release-taper", "entry cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.pedal_overlap.clean_handoff",
            technique="pedal_overlap", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Overlapping pedals keeps showing up, era after era "
                    "({eras_fired} of {eras_total}) — this is the handoff "
                    "habit, not one corner."
                ),
                "resolved": (
                    "The pedal overlap stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. The handoff is clean now."
                ),
            },
            drill_followup=(
                "Second assignment: run a full session with a deliberate, "
                "counted beat between brake-off and throttle-on, and watch "
                "whether the overlap corners stop firing."
            ),
            driving_principle=(
                "Throttle and brake fighting each other confuses the "
                "weight transfer the car needs to plant one axle at a "
                "time. Beyond a deliberate heel-toe blip, overlap just "
                "burns the front brakes against the rear tires."
            ),
            gate=DetectorGate("throttle-brake-overlap"),
            band_phase="entry",
            coaching_expression=(
                "You're fighting the car with overlapping pedals. Make it a clean, "
                "deliberate handoff from brake to throttle."
            ),
            drill=(
                "Next session: find the exact moment you're fully off the "
                "brake before any throttle. Widen that gap if it's "
                "currently negative."
            ),
            strength_expression=(
                "Clean handoff — you're off the brake before you're on the "
                "throttle, so the car always knows which axle it's working."
            ),
            evidence_binding=("throttle-brake-overlap", "entry cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.turn_in.one_commitment",
            technique="turn_in", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Sawing at the wheel mid-corner keeps showing up, era "
                    "after era ({eras_fired} of {eras_total}) — this is "
                    "the turn-in habit, not one corner."
                ),
                "resolved": (
                    "The mid-corner corrections stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. Turn-in is one commitment now."
                ),
            },
            drill_followup=(
                "Second assignment: pick your worst sawing corner and "
                "drive it eyes-up — look at the exit before you turn in, "
                "and count corrections out loud."
            ),
            driving_principle=(
                "Every extra steering correction between turn-in and apex "
                "is the car negotiating a line you haven't committed to — "
                "each one scrubs speed the corner didn't need to lose."
            ),
            gate=DetectorGate("one-steering-input"),
            band_phase="mid",
            coaching_expression=(
                "You're sawing at the wheel mid-corner. Settle the entry, trust your eyes, "
                "and use one committed, decisive steering input to the apex."
            ),
            drill=(
                "Next session: pick your turn-in point before the corner "
                "and commit to a single steering input. Ignore lap time; "
                "count your own corrections."
            ),
            strength_expression=(
                "You're committing to the line — turn-in to apex on one "
                "input, with no mid-corner renegotiation."
            ),
            evidence_binding=("one-steering-input", "mid cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.throttle_pickup.roll_it_on",
            technique="throttle_pickup", fundamental="corner_exit",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Stabbing the throttle keeps showing up, era after "
                    "era ({eras_fired} of {eras_total}) — this is the "
                    "pickup habit, not one corner."
                ),
                "resolved": (
                    "The throttle stabs stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. The pickup rolls on now."
                ),
            },
            drill_followup=(
                "Second assignment: run a session where every throttle "
                "application takes a full second from first touch to full "
                "— then shorten it only where the rear stays settled."
            ),
            driving_principle=(
                "A lift after picking up throttle means the pickup point "
                "was a guess, not a commitment — the car had to give back "
                "grip mid-application it never should have been asked for."
            ),
            gate=DetectorGate("throttle-monotonic"),
            band_phase="exit",
            coaching_expression=(
                "You're stabbing the throttle and lifting. Roll it on smoothly and "
                "progressively—if you have to lift, you got greedy too early."
            ),
            drill=(
                "Next session: delay throttle pickup slightly and apply "
                "it as one continuous build to full throttle — no stabs, "
                "no lifts."
            ),
            strength_expression=(
                "Your throttle pickup is committed — once you open it, it "
                "stays open, so the rear never has to give grip back."
            ),
            evidence_binding=("throttle-monotonic", "exit cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.coasting.always_working",
            technique="coasting", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Riding as a passenger through the coasting zone keeps "
                    "showing up, era after era ({eras_fired} of "
                    "{eras_total}) — this is the coasting habit, not one "
                    "corner."
                ),
                "resolved": (
                    "The coasting stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. The car works all the way "
                    "through now."
                ),
            },
            drill_followup=(
                "Second assignment: pick the longest coasting zone and "
                "close it from both ends in one session — brake a touch "
                "later AND pick up a touch sooner."
            ),
            driving_principle=(
                "Neither pedal working means neither axle is doing "
                "anything useful — the car coasts through time that "
                "braking, turning, or driving could have used."
            ),
            gate=DetectorGate("coast-window"),
            band_phase="mid",
            coaching_expression=(
                "You're a passenger in the coasting zone. The car must always be working—"
                "either braking, turning, or driving."
            ),
            drill=(
                "Next session: find where you're on neither pedal "
                "mid-corner and close that gap by a fraction — brake a "
                "touch later or pick up throttle a touch sooner."
            ),
            strength_expression=(
                "Almost no coasting here — the car is braking, turning or "
                "driving nearly all the way through."
            ),
            evidence_binding=("coast-window", "mid cumulative_loss"),
        ),
        CoachingPrinciple(
            id="cp.rotation_efficiency.carry_the_middle",
            technique="rotation_efficiency", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Mid-corner speed keeps falling away, era after era "
                    "({eras_fired} of {eras_total}) — this is the "
                    "middle-of-corner habit, not one corner."
                ),
                "resolved": (
                    "The mid-corner gap stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. The middle holds up now."
                ),
            },
            drill_followup=(
                "Second assignment: on your worst mid-corner corner, chase "
                "apex speed for ten laps straight and ignore the "
                "stopwatch — then check whether the pattern moved."
            ),
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
            strength_expression=(
                "Your mid-corner speed holds up — there's no repeatable gap "
                "between your quicker and slower laps through the middle."
            ),
            evidence_binding=("vs-self mid-phase finding",),
        ),
        CoachingPrinciple(
            id="cp.repeatability.same_lap_twice",
            technique="repeatability", fundamental="consistency",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Not matching a lap before trying to beat it keeps "
                    "showing up, era after era ({eras_fired} of "
                    "{eras_total}) — this is the repeatability habit, not "
                    "one corner."
                ),
                "resolved": (
                    "The lap-to-lap spread stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. The laps repeat now."
                ),
            },
            drill_followup=(
                "Second assignment: pick one corner and run five laps "
                "aiming for identical inputs, then compare the traces — "
                "find the input that still moves."
            ),
            driving_principle=(
                "A technique that varies lap to lap isn't a technique yet "
                "— it's a range of outcomes. Pace built on an inconsistent "
                "input is pace you can't reliably reproduce under "
                "pressure."
            ),
            gate=MetricDispersionGate(metric="*", floor_key="consistency_dispersion_floor"),
            band_phase=None,  # consistency is cross-cutting (taxonomy.py) — bands on its own dispersion
            coaching_expression=(
                "Match a lap before you try to beat it — repeatability "
                "comes before pace."
            ),
            drill=(
                "Next session: try to execute this corner exactly the "
                "same way three laps in a row. Ignore lap time; judge "
                "yourself only on how close the three felt."
            ),
            strength_expression=(
                "You're repeating yourself — your inputs land in the same "
                "place lap after lap, which is what makes pace reproducible."
            ),
            evidence_binding=("pooled normalized scaled-MAD dispersion",),
        ),
        CoachingPrinciple(
            id="cp.entry_commitment.trust_the_proxy",
            technique="entry_commitment", fundamental="commitment",
            signal_status=SignalStatus.PROXY,
            tendency_variants={
                "persistent": (
                    "Giving up entry speed early keeps showing up, era "
                    "after era ({eras_fired} of {eras_total}) — this is "
                    "the commitment habit, not one corner."
                ),
                "resolved": (
                    "The early entry give-up stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. Entry commitment holds now."
                ),
            },
            drill_followup=(
                "Second assignment: on one corner, deliberately brake five "
                "metres later for a full session and log whether the exit "
                "actually suffered."
            ),
            driving_principle=(
                "Brake-point timing is an indirect stand-in for entry "
                "commitment, not a direct measurement of it — a moving "
                "brake point can mean the driver is protecting margin "
                "rather than driving to the corner's actual limit."
            ),
            gate=MetricDispersionGate(metric="brake_point_dist_pct", floor_key="commitment_dispersion_floor"),
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
            strength_expression=(
                "Your braking points are settled lap to lap — which reads "
                "as entry commitment, though this one is inferred from brake "
                "point rather than measured directly."
            ),
            evidence_binding=("brake_point_dist_pct normalized scaled-MAD dispersion",),
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
        # --- coach-onto-v5 (SPEC.md A57): the entry-phase tranche. Three
        # measured braking techniques that had metrics and scores but no
        # principle. Appended, not interleaved: nothing above this line
        # changed, so every v4 eligibility outcome is reproducible from
        # the principles above alone.
        CoachingPrinciple(
            id="cp.trail_braking.carry_the_brake",
            technique="trail_braking", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Coming fully off the brake before the car turns keeps "
                    "showing up, era after era ({eras_fired} of "
                    "{eras_total}) — this is the trail-braking habit, not "
                    "one corner."
                ),
                "resolved": (
                    "The straight-line-only braking stopped firing after "
                    "era {last_seen_era} — clear for the last "
                    "{clearing_streak} eras. The brake carries into the "
                    "corner now."
                ),
            },
            drill_followup=(
                "Second assignment: on your heaviest braking corner, hold "
                "a breath of brake until the car has clearly rotated, for "
                "ten laps — then check the pattern."
            ),
            driving_principle=(
                "Braking and steering draw on one front-tire budget. "
                "Releasing the brake completely before turn-in unloads "
                "the nose at the exact moment it needs load to bite and "
                "rotate; carrying a shrinking brake pressure past "
                "turn-in keeps the front planted while the steering "
                "takes over the budget."
            ),
            gate=MetricStatGate(
                metric="trail_brake_overlap_s", stat="median",
                direction="below", floor_key="trail_brake_overlap_floor_s",
                guard_metric="brake_peak",
                guard_floor_key="braking_zone_peak_floor",
            ),
            band_phase="entry",
            coaching_expression=(
                "You brake in a straight line and come fully off before "
                "the car turns. Carry the brake past turn-in and release "
                "it as you add steering — keep the nose loaded while "
                "the car rotates."
            ),
            drill=(
                "Next session: on your heaviest braking corner, hold a "
                "breath of brake pressure until the car has clearly "
                "started to rotate, then finish the release. Ignore lap "
                "time; feel the front stay planted."
            ),
            strength_expression=(
                "You're carrying the brake into the corner — the front "
                "stays loaded through turn-in instead of being unloaded "
                "before it."
            ),
            evidence_binding=(
                "trail_brake_overlap_s median", "brake_peak median",
                "entry cumulative_loss",
            ),
        ),
        CoachingPrinciple(
            id="cp.brake_application.get_to_peak",
            technique="brake_application", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "Squeezing the brake on instead of getting to pressure "
                    "keeps showing up, era after era ({eras_fired} of "
                    "{eras_total}) — this is the application habit, not "
                    "one corner."
                ),
                "resolved": (
                    "The slow brake application stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. Peak pressure comes "
                    "decisively now."
                ),
            },
            drill_followup=(
                "Second assignment: on the heaviest braking zone, make "
                "every application a quick build to peak for a full "
                "session and watch the pattern."
            ),
            driving_principle=(
                "A braking zone is spent at whatever pressure the pedal "
                "has reached. A slow squeeze spends its first half "
                "below the tire's limit — track the corner never gives "
                "back — and the peak, when it finally arrives, has less "
                "room left to work in. Decisiveness belongs at the "
                "start of the pedal; finesse belongs at the release."
            ),
            gate=MetricStatGate(
                metric="brake_application_rate", stat="median",
                direction="below",
                floor_key="brake_application_rate_floor",
                guard_metric="brake_peak",
                guard_floor_key="braking_zone_peak_floor",
            ),
            band_phase="entry",
            coaching_expression=(
                "You're squeezing the brake on instead of getting to "
                "pressure. Build to peak decisively — the application "
                "should be quick; the release is where the finesse "
                "lives."
            ),
            drill=(
                "Next session: on the heaviest braking zone, make the "
                "initial application a deliberate, quick build to full "
                "pressure, then manage the release as usual. Ignore lap "
                "time; judge only how fast the pedal reaches its peak."
            ),
            strength_expression=(
                "You get to peak pressure decisively — the braking zone "
                "is spent at the tire's limit, not on the way to it."
            ),
            evidence_binding=(
                "brake_application_rate median", "brake_peak median",
                "entry cumulative_loss",
            ),
        ),
        CoachingPrinciple(
            id="cp.brake_point_selection.same_marker",
            technique="brake_point_selection", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            tendency_variants={
                "persistent": (
                    "A wandering brake point keeps showing up, era after "
                    "era ({eras_fired} of {eras_total}) — this is the "
                    "marker habit, not one corner."
                ),
                "resolved": (
                    "The wandering brake point stopped firing after era "
                    "{last_seen_era} — clear for the last "
                    "{clearing_streak} eras. The marker holds now."
                ),
            },
            drill_followup=(
                "Second assignment: write your brake marker down before "
                "the session, brake on it for every lap, and move it only "
                "between sessions."
            ),
            driving_principle=(
                "Everything downstream — peak pressure, release, "
                "turn-in — keys off where braking starts. A brake point "
                "chosen by feel each lap turns every later input into a "
                "new experiment; a physical marker makes the whole "
                "entry repeatable, which is why schools teach markers "
                "before they teach speed."
            ),
            # IQR, never the CV: see config.brake_point_iqr_floor_pct.
            # Where this measured principle has any verdict at a corner,
            # the entry-commitment PROXY (same metric, dispersion gate) is
            # not presented for that corner — one voice per piece of
            # evidence, and the measured voice wins. The selection-layer
            # rule lives in coaching/engine.py (select_coaching) and
            # coaching/rollup.py; eligibility itself is untouched.
            gate=MetricStatGate(
                metric="brake_point_dist_pct", stat="iqr",
                direction="above", floor_key="brake_point_iqr_floor_pct",
            ),
            band_phase="entry",
            coaching_expression=(
                "Your brake point wanders — the middle half of your "
                "laps starts braking across a wide band of track. Pick "
                "one physical marker for this corner and start braking "
                "on it, every lap."
            ),
            drill=(
                "Next session: name a board, seam, or shadow as this "
                "corner's brake marker. Brake on it for ten laps "
                "whether it feels early or late; move it between "
                "sessions if you must, never within one."
            ),
            strength_expression=(
                "Your brake point is a marker, not a mood — braking "
                "starts in the same place lap after lap."
            ),
            evidence_binding=(
                "brake_point_dist_pct interquartile range",
                "entry cumulative_loss",
            ),
        ),
        # --- coach-onto-v8 (SPEC.md A60): the steering/throttle tranche.
        # Three measured techniques that had metrics and scores but no
        # principle. Appended, not interleaved: nothing above this line
        # changed, so every v7 eligibility outcome is reproducible from
        # the principles above alone.
        CoachingPrinciple(
            id="cp.steering_smoothness.smooth_hands",
            technique="steering_smoothness", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "Steering is a placement, not a negotiation. Every "
                "correction mid-corner scrubs speed and unloads the "
                "tire that is already doing the most work; a wheel "
                "placed once and held lets the car settle onto its "
                "line, and unwinding as the throttle goes back on "
                "hands the grip budget from steering to acceleration "
                "without a fight."
            ),
            # No suppression rule vs one_commitment (see SPEC.md A60):
            # different metrics (RMS steering acceleration vs
            # correction count), different drills (smooth the rate vs
            # commit to one input) — the two reinforce, so both speak.
            gate=MetricStatGate(
                metric="steering_smoothness_dps2", stat="median",
                direction="above",
                floor_key="steering_smoothness_floor_dps2",
            ),
            band_phase="mid",
            coaching_expression=(
                "Your hands are working too hard through the middle "
                "of the corner. Place the wheel once, hold it steady, "
                "and unwind it gradually as you feed the throttle back "
                "in — instead of correcting all the way to the apex."
            ),
            drill=(
                "Next session: on one corner, turn in once and freeze "
                "your hands until the car is pointed at the exit. If "
                "you feel yourself adjusting mid-corner, move the "
                "turn-in point between sessions — never the wheel "
                "within one."
            ),
            strength_expression=(
                "Your steering is calm through the middle of the "
                "corner — one input, held steady, unwound as the "
                "throttle goes on."
            ),
            evidence_binding=(
                "steering_smoothness_dps2 median",
                "mid cumulative_loss",
            ),
        ),
        CoachingPrinciple(
            id="cp.throttle_modulation.one_squeeze",
            technique="throttle_modulation", fundamental="corner_exit",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "The throttle is a commitment, not a question. Each "
                "lift-and-stab between pickup and full throttle "
                "unloads the rear, then asks it to take load again — "
                "the car never settles, and the exit speed that "
                "should carry down the straight is spent managing "
                "the weight transfer instead. One progressive squeeze "
                "lets the rear load once and stay loaded."
            ),
            # Where this measured principle has any verdict at a corner,
            # the roll_it_on DETECTOR (same evidence: stab-and-lift
            # between pickup and full throttle) is not presented for
            # that corner — one voice per piece of evidence, and the
            # measured voice wins. The selection-layer rule lives in
            # coaching/engine.py (select_coaching) and coaching/rollup.py;
            # eligibility itself is untouched.
            gate=MetricStatGate(
                metric="throttle_modulation_count", stat="median",
                direction="above",
                floor_key="throttle_modulation_floor_count",
            ),
            band_phase="exit",
            coaching_expression=(
                "You're stabbing at the throttle on exit instead of "
                "squeezing it on. Feed it in once, progressively, "
                "from pickup to full throttle — every lift in between "
                "costs drive."
            ),
            drill=(
                "Next session: on one corner, count your throttle "
                "applications out loud. It should be one. If you lift "
                "mid-exit, you picked the throttle up too early — wait "
                "for the car to settle, then commit."
            ),
            strength_expression=(
                "Your throttle application is clean — one progressive "
                "squeeze from pickup to full throttle."
            ),
            evidence_binding=(
                "throttle_modulation_count median",
                "exit cumulative_loss",
            ),
        ),
        CoachingPrinciple(
            id="cp.exit_acceleration.commit_early",
            technique="exit_acceleration", fundamental="corner_exit",
            signal_status=SignalStatus.MEASURED,
            driving_principle=(
                "An exit is spent at whatever acceleration the car "
                "achieves, and the straight never gives back what the "
                "exit gives away. A gentle run out of the corner — "
                "late to full throttle, soft on the pedal — caps the "
                "speed carried onto the straight no matter how good "
                "the entry was."
            ),
            # No suppression rule vs throttle_modulation / roll_it_on
            # (see SPEC.md A60): input shape vs outcome — different
            # faults, different drills, so both speak. The gate reads
            # exit_accel_ms2 ONLY: full_throttle_dist_pct is a
            # lap-position metric (Brands Hatch medians 10.2 → 93.8
            # across C01→C09) and must never be leveled across corners.
            # The band comes from exit cumulative_loss, so a weak-accel
            # trigger only surfaces where real exit loss exists — the
            # corner-type confound (fast corners read lower regardless
            # of driver) is sized, not hidden.
            gate=MetricStatGate(
                metric="exit_accel_ms2", stat="median",
                direction="below", floor_key="exit_accel_floor_ms2",
            ),
            band_phase="exit",
            coaching_expression=(
                "You're soft on exit — the car isn't accelerating "
                "hard out of the corner. Commit to full throttle "
                "earlier and hold it there; every metre spent short "
                "of full throttle is speed you never get back."
            ),
            drill=(
                "Next session: on one corner, aim to be at full "
                "throttle before the exit kerb and hold it to the next "
                "braking zone. If the car runs wide, you went too "
                "early — back it up half a car length, never a whole "
                "corner."
            ),
            strength_expression=(
                "Your exits are strong — you get to full throttle "
                "early and the car accelerates hard out of the corner."
            ),
            evidence_binding=(
                "exit_accel_ms2 median",
                "exit cumulative_loss",
            ),
        ),
    )
}


#: Tendency layer (SPEC.md A55, Stage 1): the words for a rollup
#: pattern's longitudinal state, computed by coaching/rollup.py from
#: per-era eligibility. Like every other driver-facing sentence, the text
#: lives here as versioned data; the numbers are filled from the payload,
#: never invented by a renderer. State semantics (coaching.eras, A59):
#: `new` = fired only in the most recent era; `recurring` = fired in at
#: least two eras including the most recent, below the persistent share;
#: `persistent` = most recent era and at least
#: config.coaching.tendency_persistent_min_share of all eras; `improving`
#: = fired in the last three eras with the band down a full rank from
#: two eras ago and held there; `regression` = the mirror, band up a
#: full rank and held; `dormant` = not fired in the most recent era,
#: clearing streak below config.coaching.tendency_resolved_min_eras;
#: `resolved` = clearing streak at or above that threshold, where a
#: clearing era is one where the principle did not fire and either
#: showed as a strength or was evaluated below its gate.
TENDENCY_STATE_LINES: dict[str, str] = {
    "new": (
        "First fired in the most recent era ({eras_fired} of "
        "{eras_total} eras) — new, not yet a habit."
    ),
    "recurring": (
        "Fired in {eras_fired} of {eras_total} eras, including the most "
        "recent — it keeps coming back."
    ),
    "persistent": (
        "Fired in {eras_fired} of {eras_total} eras, including the most "
        "recent — this is the habit, not a corner, and it isn't fixed yet."
    ),
    "improving": (
        "Fired in {eras_fired} of {eras_total} eras, including the most "
        "recent — but the band fell from {band_before} to {current_band} "
        "and held there."
    ),
    "dormant": (
        "Fired in {eras_fired} of {eras_total} eras, but not in the "
        "most recent — quiet lately, not yet resolved."
    ),
    "regression": (
        "Fired in {eras_fired} of {eras_total} eras, including the most "
        "recent — and the band rose from {band_before} to {current_band} "
        "and held there."
    ),
    "resolved": (
        "Fired in {eras_fired} of {eras_total} eras, clear for the last "
        "{clearing_streak} eras — it has stopped firing."
    ),
}


def tendency_line(
    *, state: str | None, eras_fired: int, eras_total: int,
    current_band: str | None = None, current_band_corners: int = 0,
    band_before: str | None = None, clearing_streak: int = 0,
) -> str | None:
    """The one rendered sentence for a pattern's tendency annotation, or
    None when there is no state to state (no dated-era evidence — the
    annotation makes no longitudinal claim rather than guessing one).

    `current_band`/`current_band_corners` are the pattern's pooled
    present, reduced by the caller from the pattern's own instances:
    the loudest gap band among them and how many corners sit at it.
    `band_before` is the band two eras ago (improving/regression only);
    `clearing_streak` is the run of consecutive clearing eras (resolved).
    """
    if state is None:
        return None
    line = TENDENCY_STATE_LINES[state].format(
        eras_fired=eras_fired, eras_total=eras_total,
        current_band=current_band, band_before=band_before or "",
        clearing_streak=clearing_streak,
    )
    if current_band is not None:
        corners = (
            f"{current_band_corners} corner"
            + ("s" if current_band_corners != 1 else "")
        )
        line += f" Currently {current_band} at {corners}."
    return line


#: The strength side's own state sentences (A59). A strength's eras are
#: the eras it showed as clearing; `lapsed` = cleared before, not in the
#: most recent era. Strengths carry no band, so there is no "Currently"
#: suffix here.
STRENGTH_TENDENCY_STATE_LINES: dict[str, str] = {
    "new": (
        "First clear in the most recent era ({eras_fired} of "
        "{eras_total} eras) — new, not yet a habit."
    ),
    "recurring": (
        "Clear in {eras_fired} of {eras_total} eras, including the most "
        "recent — it keeps holding, then slipping."
    ),
    "persistent": (
        "Clear in {eras_fired} of {eras_total} eras, including the most "
        "recent — holding up."
    ),
    "lapsed": (
        "Clear in {eras_fired} of {eras_total} eras, but not in the "
        "most recent — it has slipped lately."
    ),
}


def strength_tendency_line(
    *, state: str | None, eras_fired: int, eras_total: int,
) -> str | None:
    """The one rendered sentence for a strength's tendency annotation,
    or None when there is no state to state."""
    if state is None:
        return None
    return STRENGTH_TENDENCY_STATE_LINES[state].format(
        eras_fired=eras_fired, eras_total=eras_total,
    )


def tendency_variant(
    principle: "CoachingPrinciple", *, state: str | None,
    eras_fired: int, eras_total: int,
    first_seen_era: int | None, last_seen_era: int | None,
    clearing_streak: int,
) -> str | None:
    """A principle's bespoke tendency-framed variant for a state, filled
    with the pattern's era facts — or None when the principle carries no
    variant for that state (the generic state line carries it then).

    Variants cite eras only this driver's history has (era counts, the
    era a fix stopped after), so the interchangeability test holds:
    swapping in another driver's laps with the same aggregates still
    yields sentences grounded in that driver's eras.
    """
    if state is None:
        return None
    template = principle.tendency_variants.get(state)
    if template is None:
        return None
    return template.format(
        eras_fired=eras_fired, eras_total=eras_total,
        first_seen_era=first_seen_era, last_seen_era=last_seen_era,
        clearing_streak=clearing_streak,
    )


def principles_for_fundamental(fundamental_id: str) -> tuple[CoachingPrinciple, ...]:
    return tuple(sorted(
        (p for p in PRINCIPLES.values() if p.fundamental == fundamental_id),
        key=lambda p: p.id,
    ))
