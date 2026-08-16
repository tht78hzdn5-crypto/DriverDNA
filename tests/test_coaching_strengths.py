"""A51: the strength half of the coaching layer.

The mechanism matters and is easy to get wrong. A `CoachingCandidate` exists
only where a gate CLEARED — the detector triggers above `min_trigger_rate`,
or the CV sits above its floor. So a `negligible` band means "the fault
pattern is present but costs almost no time", NOT "the driver does this
well". The genuine strength signal is the inverse: corners where there IS
evidence and the gate stayed shut, which produced no record at all before
this.

These tests pin that distinction, because reading `negligible` as a strength
would tell a driver they are good at the exact thing they are worst at.
"""

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.coaching.engine import eligible_strengths, select_coaching
from driverdna.coaching.ontology import PRINCIPLES, ONTOLOGY_VERSION
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus
from synth import one_corner_lap, ramp
from synth import run_synthetic_lap as _run

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def run_synthetic_lap(db, lap, **kw):
    for k, v in COHORT.items():
        kw.setdefault(k, v)
    kw.setdefault("config", CONFIG)
    return _run(db, lap, **kw)


def _clean_cohort(db, n=10):
    """Laps driven the same way every time: one brake application, released
    smoothly, no overlap — the shape every detector looks for the absence of.

    The per-lap `shift` is load-bearing, not decoration: identical traces are
    content-deduped at ingest, so laps that differ only by filename collapse
    to ONE observation and every strength is then correctly withheld for thin
    evidence. Two samples is enough to make them distinct laps while leaving
    every detector unfired.
    """
    for i in range(n):
        lap = one_corner_lap()
        lap.source_path = lap.source_path.with_name(f"clean{i}.csv")
        shift = i * 2
        lap.brake[:] = 0.0
        ramp(lap.brake, 600 + shift, 630 + shift, 0.0, 0.8)
        lap.brake[630 + shift:690 + shift] = 0.8
        ramp(lap.brake, 690 + shift, 720 + shift, 0.8, 0.0)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")


# --- the ontology half -----------------------------------------------------


def test_every_measured_or_proxy_principle_has_a_strength_expression():
    for p in PRINCIPLES.values():
        if p.signal_status is SignalStatus.NO_SIGNAL:
            continue
        assert p.strength_expression, f"{p.id} has no strength_expression"


def test_no_signal_principle_never_carries_a_strength_expression():
    """A confidence value never launders an unmeasured inference, and neither
    does an affirmation — nothing was measured to be good at."""
    for p in PRINCIPLES.values():
        if p.signal_status is SignalStatus.NO_SIGNAL:
            assert p.strength_expression is None


def test_ontology_version_bumped_for_the_new_field():
    assert ONTOLOGY_VERSION == "coach-onto-v3"


# --- the engine half -------------------------------------------------------


def test_a_clean_cohort_produces_strengths(db):
    _clean_cohort(db)
    strengths = eligible_strengths(db, config=CONFIG, **COHORT)
    assert strengths, "consistently clean laps produced no strength at all"
    for s in strengths:
        assert PRINCIPLES[s.principle_id].strength_expression


def test_a_strength_and_a_candidate_never_claim_the_same_corner(db):
    """The two passes are strict complements — the gate either cleared or it
    did not. Both firing on one (principle, corner) would be a contradiction
    the driver would see as the product arguing with itself."""
    from driverdna.coaching.engine import eligible_principles

    _clean_cohort(db)
    faults = {
        (c.principle_id, c.corner_id)
        for c in eligible_principles(db, config=CONFIG, **COHORT)
        if c.corner_id is not None
    }
    wins = {(s.principle_id, s.corner_id) for s in eligible_strengths(db, config=CONFIG, **COHORT)}
    assert not (faults & wins)


def test_thin_evidence_never_becomes_a_strength(db):
    """A candidate merely FLAGS thin evidence; a strength is a positive
    claim, so it requires the full floor. Two laps of clean driving is not
    proof of a technique."""
    _clean_cohort(db, n=2)
    for s in eligible_strengths(db, config=CONFIG, **COHORT):
        assert s.n >= CONFIG.coaching.thin_evidence_floor_n


def test_no_signal_principle_never_appears_as_a_strength(db):
    _clean_cohort(db)
    ids = {s.principle_id for s in eligible_strengths(db, config=CONFIG, **COHORT)}
    assert "cp.eye_line.look_further" not in ids


def test_strengths_are_deterministic(db):
    _clean_cohort(db)
    first = eligible_strengths(db, config=CONFIG, **COHORT)
    second = eligible_strengths(db, config=CONFIG, **COHORT)
    assert [(s.principle_id, s.corner_id, s.n) for s in first] == \
           [(s.principle_id, s.corner_id, s.n) for s in second]


def test_select_coaching_groups_strengths_without_touching_silent_count():
    """`silent_count` counted `negligible` candidates and still does — A51
    explains that pile, it does not repurpose it."""
    selection = select_coaching([], strengths=[])
    assert selection["strengths"] == []
    assert selection["silent_count"] == 0
