"""coach-onto-v9 (SPEC.md A61): the vehicle-management principle.

Tranche 4 of the coaching-ontology expansion (docs/COACHING-FUNDAMENTALS-
REVIEW.md §3): `abs_usage` was the one measured vehicle-management
technique with a metric, a score, and no principle — ABS intervention
could never be spoken. This tranche gives it one `MetricStatGate`
principle, `cp.abs_usage.stay_off_the_abs`, and nothing else: tire
utilization, weight transfer, and slip management stay no_signal (no
channel in the Garage61 CSV contract), and car control as a principle
stays honestly absent — the detector design in SPEC.md A61 shows why
no over-rotation/understeer principle can be measured from the
available channels, and incident-level balance is already classified
and routed to existing principles.

Synthetic cohorts run the full pipeline, mirroring
test_coaching_steering_throttle.py: each builder isolates exactly one
fault so a firing (or silence) is attributable to one gate. The
canonical corner geometry (brake 600-680, steering from 690, apex ~760,
throttle back 780-830) is shared with that file so a cohort means the
same thing in both; the helpers are copied, not imported, because no
test module imports another in this repo. `make_lap` carries no
abs_active parameter (synthetic laps default it to all-False), so the
ABS channel is set explicitly with dataclasses.replace — the same
shape as the long_accel override in the steering/throttle file.
"""

import dataclasses

import numpy as np
import pytest

from driverdna.coaching.engine import (
    CoachingCandidate,
    CoachingStrength,
    eligible_principles,
    eligible_strengths,
    select_coaching,
)
from driverdna.coaching.ontology import PRINCIPLES, MetricStatGate
from driverdna.coaching.rollup import build_coaching_rollup
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus
from synth import make_lap, ramp
from synth import run_synthetic_lap as _run

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}

ABS = "cp.abs_usage.stay_off_the_abs"
GET_TO_PEAK = "cp.brake_application.get_to_peak"


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def run_synthetic_lap(db, lap, **kw):
    kw.setdefault("driver", COHORT["driver"])
    kw.setdefault("car", COHORT["car"])
    kw.setdefault("track", COHORT["track"])
    kw.setdefault("config", CONFIG)
    return _run(db, lap, **kw)


def _candidates(db, principle_id, config=CONFIG):
    return [
        c for c in eligible_principles(db, config=config, **COHORT)
        if c.principle_id == principle_id
    ]


def _strengths(db, principle_id, config=CONFIG):
    return [
        s for s in eligible_strengths(db, config=config, **COHORT)
        if s.principle_id == principle_id
    ]


def _base_traces(n=1800):
    speed = np.full(n, 45.0)
    ramp(speed, 600, 760, 45.0, 28.0)
    ramp(speed, 760, 900, 28.0, 45.0)
    throttle = np.ones(n)
    ramp(throttle, 580, 600, 1.0, 0.0)
    throttle[600:780] = 0.0
    ramp(throttle, 780, 830, 0.0, 1.0)
    return speed, throttle


def _steering(n=1800, start=690):
    steering = np.zeros(n)
    ramp(steering, start, start + 30, 0.0, 25.0)
    steering[start + 30:840] = 25.0
    ramp(steering, 840, 870, 25.0, 0.0)
    return steering


def _clean_braking_lap(src: str):
    """The canonical corner with a normal braking event and no ABS:
    brake ramps 600-630 to 0.85, holds to 650, releases by 680."""
    n = 1800
    speed, throttle = _base_traces(n)
    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, 0.85)
    brake[630:650] = 0.85
    ramp(brake, 650, 680, 0.85, 0.0)
    return make_lap(n, speed=speed, brake=brake, steering_deg=_steering(n),
                    throttle=throttle, src=src)


def _with_abs(lap, start, end):
    """Set the ABSActive channel over [start, end). Synthetic laps
    carry all-False there by construction (make_lap has no abs_active
    parameter), so the ABS gate's input channel is set explicitly —
    the brake trace is left untouched so corner detection is identical
    between the heavy and clean cohorts and only this channel differs."""
    arr = np.zeros(lap.n_samples, dtype=np.bool_)
    arr[start:end] = True
    return dataclasses.replace(lap, abs_active=arr)


def _abs_heavy_lap(src: str):
    """ABS active across the whole braking window: ratio 1.0 by
    construction, far above the 0.25 floor."""
    return _with_abs(_clean_braking_lap(src), 600, 680)


def _abs_partial_lap(src: str):
    """ABS active over roughly half the braking window: ratio ~0.5,
    above the floor without saturating it."""
    return _with_abs(_clean_braking_lap(src), 600, 640)


def _cohort(db, builder, n=8, warp_phase=None):
    from driverdna.pipeline import phase_windows_from_stored

    run_synthetic_lap(db, builder("lap0.csv"), session_key="s0")
    window = None
    if warp_phase is not None:
        map_pk, _ = db.load_corner_map(car=COHORT["car"], track=COHORT["track"])
        stored = db.load_corner_windows(map_pk)
        window = phase_windows_from_stored(stored["C01"]).window(warp_phase)
    for i in range(1, n):
        lap = builder(f"lap{i}.csv")
        if window is not None:
            from synth import warp_time

            lap = warp_time(lap, window, (i % 4) * 0.08)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")


# --- ontology shape ------------------------------------------------------------


def test_abs_principle_exists_with_the_ontology_shape():
    p = PRINCIPLES[ABS]
    assert p.technique == "abs_usage"
    assert p.fundamental == "vehicle_management"
    assert p.signal_status is SignalStatus.MEASURED
    assert isinstance(p.gate, MetricStatGate)
    assert p.band_phase == "entry"
    assert p.coaching_expression and p.drill and p.strength_expression
    assert p.evidence_binding


def test_threshold_lives_in_config_with_the_documented_default():
    cfg = CONFIG.coaching
    # Corpus anchor (885-lap owner corpus, per-corner medians across
    # the 295 corners with >= 2 laps): p75 0.223 → floor 0.25.
    assert cfg.abs_active_ratio_floor == 0.25


def test_abs_gate_reads_ratio_not_brake_peak():
    """Brake peak is a different fault (application) with its own
    principle; the ABS gate reads the share of braking time with ABS
    active only."""
    p = PRINCIPLES[ABS]
    assert p.gate.metric == "abs_active_ratio"
    assert p.gate.stat == "median"
    assert p.gate.direction == "above"


# --- the gate ------------------------------------------------------------------


def test_abs_fires_on_abs_heavy_braking(db):
    _cohort(db, _abs_heavy_lap, n=8, warp_phase="entry")
    found = _candidates(db, ABS)
    assert found, "a 1.0 median ABS ratio must clear the 0.25 floor"
    c = found[0]
    assert c.corner_id == "C01"
    assert c.magnitude_kind == "seconds_lost"  # bands on the entry phase
    assert c.n == 8
    assert c.evidence_ids


def test_abs_fires_on_a_middling_ratio(db):
    _cohort(db, _abs_partial_lap, n=8, warp_phase="entry")
    found = _candidates(db, ABS)
    assert found, "a ~0.5 median ABS ratio must clear the 0.25 floor"


def test_abs_is_a_strength_on_clean_braking(db):
    _cohort(db, _clean_braking_lap, n=8)
    assert not _candidates(db, ABS)
    strengths = _strengths(db, ABS)
    assert strengths, "zero ABS intervention must read as a strength"
    s = strengths[0]
    assert s.observed_kind == "metric_median"
    assert s.observed == 0


def test_abs_needs_two_laps_before_it_says_anything(db):
    run_synthetic_lap(db, _abs_heavy_lap("only.csv"))
    assert not _candidates(db, ABS)
    assert not _strengths(db, ABS)


def test_abs_appears_in_the_rollup_when_firing(db):
    _cohort(db, _abs_heavy_lap, n=8, warp_phase="entry")
    rollup = build_coaching_rollup(db, driver="owner", config=CONFIG)
    fault_ids = {p["coaching_principle_id"] for p in rollup["patterns"]}
    assert ABS in fault_ids


# --- no suppression (reinforce, not precedence) ---------------------------------


def _cand(principle_id, corner="C01", band="notable"):
    return CoachingCandidate(
        principle_id=principle_id, signal_status=SignalStatus.MEASURED,
        corner_id=corner, gap_band=band, magnitude=0.2,
        magnitude_kind="seconds_lost", n=20, thin_evidence=False,
        evidence_ids=(), headline_eligible=band in ("notable", "major"),
    )


def _presented_principles(selection):
    shown = set()
    if selection["headline"] is not None:
        shown.add(selection["headline"].principle_id)
    shown.update(c.principle_id for c in selection["secondary"])
    return shown


def test_abs_reinforces_rather_than_suppressing_braking_principles():
    """ABS ratio (threshold crossing under braking) and brake
    application (how peak is reached) are different measurements with
    different drills, so both speak; no suppression rule is
    registered for the ABS principle in either presentation path."""
    selection = select_coaching([_cand(ABS), _cand(GET_TO_PEAK)], [])
    shown = _presented_principles(selection)
    assert ABS in shown
    assert GET_TO_PEAK in shown
