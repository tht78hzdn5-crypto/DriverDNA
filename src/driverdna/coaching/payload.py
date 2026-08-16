"""The coaching payload section (M7c): eligible/ranked/banded principles,
serialized for report/coach/chat. Deterministic — a straight rendering of
coaching/engine.py's output plus the ontology's static text, nothing
computed here.
"""

from __future__ import annotations

from typing import Any

from driverdna.coaching.engine import (
    CoachingCandidate,
    eligible_principles,
    eligible_strengths,
    select_coaching,
)
from driverdna.coaching.ontology import ONTOLOGY_VERSION, PRINCIPLES
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus


def _candidate_dict(c: CoachingCandidate) -> dict[str, Any]:
    principle = PRINCIPLES[c.principle_id]
    d: dict[str, Any] = {
        "coaching_principle_id": c.principle_id,
        "technique": principle.technique,
        "fundamental": principle.fundamental,
        "signal_status": c.signal_status.value,
        "corner_id": c.corner_id,
        "gap_band": c.gap_band,
        "magnitude": c.magnitude,
        "magnitude_kind": c.magnitude_kind,
        "n": c.n,
        "thin_evidence": c.thin_evidence,
        "evidence_ids": list(c.evidence_ids),
        "driving_principle": principle.driving_principle,
    }
    if c.signal_status is SignalStatus.NO_SIGNAL:
        sc = principle.self_check
        d["self_check"] = {
            "instruction": sc.instruction, "label": sc.label, "basis": sc.basis,
        }
    else:
        d["coaching_expression"] = principle.coaching_expression
        d["drill"] = principle.drill
    return d


def _strength_dict(group: list) -> dict[str, Any]:
    """One principle's strength, with every corner it holds at.

    Grouped rather than flat because a principle clears independently at each
    corner and repeating the identical sentence twelve times is the same
    presentation problem `CoachingInstances` already solved on the fault
    side. Each corner keeps its OWN n and observed value — nothing is
    combined into a total, which for a mix of trigger rates, CVs and seconds
    would be meaningless anyway.
    """
    head = group[0]
    principle = PRINCIPLES[head.principle_id]
    return {
        "coaching_principle_id": head.principle_id,
        "technique": principle.technique,
        "fundamental": principle.fundamental,
        "signal_status": head.signal_status.value,
        "strength_expression": principle.strength_expression,
        "driving_principle": principle.driving_principle,
        "n_corners": len(group),
        "instances": [
            {
                "corner_id": s.corner_id,
                "n": s.n,
                "observed": s.observed,
                "observed_kind": s.observed_kind,
                "evidence_ids": list(s.evidence_ids),
            }
            for s in group
        ],
    }


def coaching_section(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig,
) -> dict[str, Any]:
    candidates = eligible_principles(db, driver=driver, car=car, track=track, config=config)
    strengths = eligible_strengths(db, driver=driver, car=car, track=track, config=config)
    selection = select_coaching(candidates, strengths)
    return {
        "ontology_version": ONTOLOGY_VERSION,
        "headline": _candidate_dict(selection["headline"]) if selection["headline"] else None,
        "headline_reason": selection["headline_reason"],
        "secondary": [_candidate_dict(c) for c in selection["secondary"]],
        "silent_count": selection["silent_count"],
        "self_checks": [_candidate_dict(c) for c in selection["self_checks"]],
        "strengths": [_strength_dict(g) for g in selection["strengths"]],
    }
