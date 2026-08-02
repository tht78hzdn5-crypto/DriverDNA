"""Methodology text for the disclosure pattern (UI v3, SPEC.md A33).

The engine, not the SPA, owns the words: `ui/src/views/shared.jsx`'s
`<Methodology id="..."/>` and the eventual static-report equivalent both
read from `GET /api/explain`, so the two surfaces can never silently drift
onto two different explanations of the same figure (the same reasoning as
`report/builder.py`'s `_TOKENS` mirror for colors).

Versioned static data, not computed — exactly like `coaching/ontology.py`:
adding an explanation is a reviewable data change, not new eligibility
code. `explain()` never derives a number; it only labels ones that already
exist elsewhere in the payload.

This module deliberately does not repeat text the payload already carries
per-instance (`metric_definitions`, `describe_key`, `PRINCIPLES[*]
.driving_principle`, `driver_model.note`, `incidents.note`,
`Belief.insufficient_reason`, `finding.gate_reason`) — those stay the
source of truth for their own figures. `METHODOLOGY` fills the gaps: the
general "how" behind a pattern of figures, not a fact about one row.
"""

from __future__ import annotations

METHODOLOGY: dict[str, str] = {
    # --- the three sources (UI-SPEC decision 6) -------------------------
    "source.vs-self": (
        "Compares your own faster laps against your own slower laps at the "
        "same corner — a within-driver comparison. Never compares you to "
        "anyone else. Needs enough repeated attempts at a corner before it "
        "will show anything (a gate, stated when it hasn't cleared yet)."
    ),
    "source.vs-principle": (
        "Checks your inputs against a canonical technique — a fixed rule "
        "about how a corner phase should be driven (e.g. finishing the "
        "brake release before turn-in), not a comparison to your own or "
        "anyone else's other laps."
    ),
    "source.vs-reference": (
        "Compares you to a reference lap you've imported — a faster "
        "driver's data, used only for gap context. A reference lap never "
        "enters your own history, trends, consistency statistics, or "
        "Driver Model scores; the gap it reports is context, not a promise "
        "of recoverable time."
    ),
    # --- phase-time baselines --------------------------------------------
    "baseline.robust": (
        "The robust baseline (\"median-of-top-3\") averages your three "
        "fastest clean attempts at this phase, screening out one-off "
        "outliers first. This is the primary yardstick — it reflects a "
        "corner you can actually repeat, not a single lucky lap."
    ),
    "baseline.single-best": (
        "Your single fastest recorded attempt at this phase. Shown as "
        "context, not the yardstick — one execution can include luck, "
        "traffic, or a risk you wouldn't want to bank on every lap."
    ),
    "baseline.spread": (
        "How much your times at this phase vary lap to lap. A tight spread "
        "means you're repeating the phase consistently; a wide spread "
        "means there's technique still to lock in before the average time "
        "means much."
    ),
    "baseline.outliers_screened": (
        "Attempts excluded from the baseline calculation because they were "
        "statistical outliers (an off, a lockup, a badly compromised entry) "
        "— screened so one bad lap can't drag down what \"typical\" means, "
        "per the engine's fixed outlier-fence rule, not driver judgment."
    ),
    # --- cumulative loss ----------------------------------------------------
    "loss.cumulative": (
        "Seconds lost per lap, summed across phases or corners, each "
        "measured against its own robust baseline above. This is the "
        "product's headline number: technique translated into lap time, "
        "not a synthetic score."
    ),
    # --- confidence / gates --------------------------------------------------
    "gate.confidence": (
        "A finding only appears once it clears a minimum-evidence "
        "threshold (sample count, session count, and — for the Driver "
        "Model — track/car diversity). Below that, the finding still "
        "exists in the data; it's held back and shown as suppressed with "
        "the specific reason and progress toward the gate, never silently "
        "dropped."
    ),
    # --- Driver Model components --------------------------------------------
    "model.adherence": (
        "How often your inputs match the canonical technique for this "
        "fundamental's detectors — a rate, not a lap time. 100% means the "
        "detector never triggered; each trigger is a technique deviation "
        "at that instant, not a verdict on the whole lap."
    ),
    "model.opportunity": (
        "How much time is realistically on the table for this fundamental, "
        "from the cumulative-loss measurement against your own robust "
        "baseline — normalized to a 0-100 scale by a configured ceiling, "
        "never compared to another driver."
    ),
    "model.consistency": (
        "How repeatable your execution is for this fundamental's metrics, "
        "from each metric's coefficient of variation. Different metrics "
        "naturally vary on very different scales (a lap-percentage figure "
        "moves far less than a raw count), so each is first normalized "
        "against its own unit's typical scale before being pooled — "
        "otherwise a naturally-noisy unit would dominate the average "
        "regardless of your actual consistency (SPEC.md A21)."
    ),
    "model.confidence": (
        "How much evidence backs this fundamental's score: sample count "
        "plus session and track/car diversity, each capped at a floor "
        "past which more evidence stops adding confidence. A proxy-based "
        "fundamental's confidence is capped lower than a directly-measured "
        "one, because a proxy is inherently a step removed from what it "
        "estimates."
    ),
    "model.trend": (
        "The direction of this fundamental's score between an earlier and "
        "a recent half of your dated laps, using the same scoring method "
        "on each half. Needs enough dated laps to split meaningfully; "
        "otherwise stated as unavailable rather than guessed. Two known "
        "limitations: the opportunity component's baseline is recomputed "
        "per half (so it's relative to your own era, not absolute), and "
        "when dated laps are thin per cohort, the two halves can pool "
        "different cars/tracks, not skill alone."
    ),
    "model.evidence_count": (
        "The number of laps that contributed evidence to this fundamental "
        "— the sample size the score, confidence, and trend all rest on. "
        "Always shown, never dropped for convenience."
    ),
    "model.history": (
        "The same scoring method as the current Driver Model score, run "
        "independently on each of several date-ordered buckets of your "
        "dated laps — the score over time, not a new kind of number. A "
        "bucket with too little evidence renders as a gap, never "
        "interpolated across, and is never averaged into a smooth line "
        "that didn't happen."
    ),
    # --- incident classifications (Track B) ---------------------------------
    "incident.trail_brake_oversteer": (
        "The engine saw you still braking as the car snapped sideways — "
        "the rear stepped out while trail-braking into the corner, which "
        "usually means too much brake pressure was still on as you turned "
        "in. Practicing a cleaner, earlier brake release before turn-in is "
        "the usual fix."
    ),
    "incident.lift_off_oversteer": (
        "The engine saw a sudden throttle lift just before the car "
        "snapped — a mid-corner lift unloaded the rear tires' grip "
        "suddenly. Smoother, more gradual throttle transitions mid-corner "
        "tend to prevent this."
    ),
    "incident.power_on_oversteer": (
        "The engine saw the throttle already on, with the car still "
        "steered, when it snapped — the power asked for more rear grip "
        "than was available on the way out of the corner. A more gradual "
        "throttle application on exit is the usual fix."
    ),
    "incident.understeer_off": (
        "The engine saw the steering loaded up but the car barely turned "
        "before running off — the front tires washed out rather than "
        "gripping. Often a corner-entry speed or line issue rather than a "
        "single bad input."
    ),
    "incident.external": (
        "The engine saw a sudden vertical load spike at the moment of the "
        "incident — consistent with a kerb strike or track bump rather "
        "than a driving input. Recorded, but not attributed to your "
        "technique."
    ),
    "incident.unclassified": (
        "The engine detected something happened here (a spin, an off, a "
        "near-stop) but the input signature at that moment wasn't clean "
        "enough to name a specific cause with confidence. Stated honestly "
        "rather than guessed — 'insufficient data' is a real answer here, "
        "not a gap in the tool."
    ),
    # --- the newcomer register (SPEC.md A33) --------------------------------
    # One short, non-patronizing line acknowledging the moment — separate
    # from the mechanism explanations above, and never attached to a
    # number. Deliberately plain rather than idiom-heavy (A33's "at most
    # one idiom per screen" is a ceiling, not a quota to hit). No entry for
    # unclassified/external: there's no clean cause to acknowledge, and a
    # generic "don't worry about it" for a lap the engine itself couldn't
    # read would be exactly the guessing the constitution forbids, one
    # level up.
    "incident.empathy.trail_brake_oversteer": (
        "Everyone's had this one — it's a squeeze, not a switch."
    ),
    "incident.empathy.lift_off_oversteer": (
        "A common one when you're pushing entry speed. It fades with reps."
    ),
    "incident.empathy.power_on_oversteer": (
        "A sign you're trying to get the power down earlier, which is the "
        "right instinct."
    ),
    "incident.empathy.understeer_off": (
        "Not a bad instinct — just more speed than the front had grip for "
        "right there."
    ),
}


def explain(key: str) -> str | None:
    """The methodology text for `key`, or None if this key isn't covered."""
    return METHODOLOGY.get(key)
