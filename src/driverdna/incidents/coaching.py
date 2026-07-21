"""Layer 3 wiring (deterministic half): which coaching principle, if any, an
incident's classification is eligible to be explained through.

This mapping is the engine's, not the AI's — mirroring how M7's coaching
engine deterministically decides which principles are eligible before any
prompt is built (docs/COACHING.md). The AI never picks a principle for an
incident; it only writes the plain-language "why" for the one principle the
engine already assigned, citing the incident's evidence.

Only a *named mechanism* is eligible. `unclassified` (the engine couldn't
tell) and `external` (possibly not the driver at all) get no principle —
explaining a cause the engine itself didn't identify would be exactly the
guessing the constitution forbids, one level up from a no_signal fundamental.
"""

from __future__ import annotations

from driverdna.coaching.ontology import PRINCIPLES

#: incident classification -> the one coaching principle eligible to explain
#: it. Chosen from the existing nine seed principles (docs/COACHING.md) by
#: matching mechanism to technique, not invented for this feature.
_MECHANISM_PRINCIPLE: dict[str, str] = {
    "trail_brake_oversteer": "cp.brake_release.finish_the_front",
    "lift_off_oversteer": "cp.throttle_pickup.roll_it_on",
    "power_on_oversteer": "cp.throttle_pickup.roll_it_on",
    "understeer_off": "cp.turn_in.one_commitment",
}
assert all(pid in PRINCIPLES for pid in _MECHANISM_PRINCIPLE.values())


def eligible_principle_for(classification: str) -> str | None:
    """The coaching principle this classification may be explained through,
    or None when the engine has nothing definite enough to explain."""
    return _MECHANISM_PRINCIPLE.get(classification)
