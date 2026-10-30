"""coach-onto-v8 (SPEC.md A60): the steering/throttle principles.

Tranche 3 of the coaching-ontology expansion (docs/COACHING-FUNDAMENTALS-
REVIEW.md §3): three measured techniques were scored but had no principle
— `steering_smoothness`, `throttle_modulation`, and `exit_acceleration`
could never be spoken. These tests pin the new `MetricStatGate`
eligibility, the config thresholds it reads, the strength complements,
and the presentation precedence between `cp.throttle_modulation.one_squeeze`
(measured: median modulation count) and `cp.throttle_pickup.roll_it_on`
(detector: any stab-and-lift) — plus the two reinforce pairs, where both
voices speak because they measure different things.

Synthetic cohorts run the full pipeline, mirroring
test_coaching_entry_phase.py: each builder isolates exactly one fault so
a firing (or silence) is attributable to one gate. The canonical corner
geometry (brake 600-680, steering from 690, apex ~760, throttle back
780-830) is shared with that file so a cohort means the same thing in
both; the helpers are copied, not imported, because no test module
imports another in this repo.
"""

import dataclasses

import numpy as np
import pytest

from driverdna.coaching.engine import (
    CoachingCandidate,
    CoachingStrength,
    _metric_stat,
    eligible_principles,
    eligible_strengths,
    select_coaching,
)
from driverdna.coaching.ontology import PRINCIPLES, MetricStatGate
from driverdna.coaching.rollup import build_coaching_rollup
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus
from driverdna.pipeline import phase_windows_from_stored
from synth import make_lap, ramp, warp_time
from synth import run_synthetic_lap as _run

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}

STEERING = "cp.steering_smoothness.smooth_hands"
MODULATION = "cp.throttle_modulation.one_squeeze"
EXIT_ACCEL = "cp.exit_acceleration.commit_early"
ONE_COMMITMENT = "cp.turn_in.one_commitment"
ROLL_IT_ON = "cp.throttle_pickup.roll_it_on"


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


def _phase_window(db, phase) -> tuple[float, float]:
    map_pk, _ = db.load_corner_map(car=COHORT["car"], track=COHORT["track"])
    stored = db.load_corner_windows(map_pk)
    windows = phase_windows_from_stored(stored["C01"])
    return windows.window(phase)


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


def _cohort(db, builder, n=8, warp_phase=None):
    run_synthetic_lap(db, builder("lap0.csv"), session_key="s0")
    window = _phase_window(db, warp_phase) if warp_phase else None
    for i in range(1, n):
        lap = builder(f"lap{i}.csv")
        if window is not None:
            lap = warp_time(lap, window, (i % 4) * 0.08)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")


def _with_long_accel(lap, value):
    """Set the LongAccel channel over the exit region. Synthetic laps
    carry zeros there by construction (make_lap has no long_accel
    parameter), so the exit gate's input channel is set explicitly —
    the speed trace is left untouched so corner detection is identical
    between the weak and strong cohorts and only this channel differs."""
    arr = np.zeros(lap.n_samples)
    arr[700:1000] = value
    return dataclasses.replace(lap, long_accel=arr)


def _rough_steering_lap(src: str):
    """A 3 Hz, ±6° wiggle through turn-in→apex on top of the canonical
    ramp: RMS steering acceleration in the thousands by construction,
    far above the 500 floor, while the steering never leaves the
    active band — so the corner itself is unchanged."""
    n = 1800
    speed, throttle = _base_traces(n)
    steering = _steering(n)
    t = np.arange(40) / 60.0
    steering[720:760] = 25.0 + 6.0 * np.sin(2 * np.pi * 3.0 * t)
    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, 0.85)
    brake[630:650] = 0.85
    ramp(brake, 650, 680, 0.85, 0.0)
    return make_lap(n, speed=speed, brake=brake, steering_deg=steering,
                    throttle=throttle, src=src)


def _smooth_steering_lap(src: str):
    """A raised-cosine turn-in (690→760, 0→25°) and hold: zero slope at
    both joints, so the second derivative stays bounded and small —
    RMS steering acceleration in the tens. A linear ramp was tried
    first and rejected: its joints spike the second derivative into
    the low hundreds, which is not smooth hands by any measure."""
    n = 1800
    speed, throttle = _base_traces(n)
    steering = np.zeros(n)
    t = np.arange(70) / 70.0
    steering[690:760] = 25.0 * (1.0 - np.cos(np.pi * t)) / 2.0
    steering[760:840] = 25.0
    ramp(steering, 840, 870, 25.0, 0.0)
    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, 0.85)
    brake[630:650] = 0.85
    ramp(brake, 650, 680, 0.85, 0.0)
    return make_lap(n, speed=speed, brake=brake, steering_deg=steering,
                    throttle=throttle, src=src)


def _modulating_throttle_lap(src: str):
    """Four 0.85↔0.45 stabs between pickup and full throttle, each drop
    0.40 — eight times the 0.05 counting floor — then a sustained
    full-throttle ramp. The oscillation stays below the 0.95
    full-throttle level, so the whole sequence sits inside the
    pickup→full-throttle window the count reads."""
    n = 1800
    speed, _ = _base_traces(n)
    throttle = np.ones(n)
    ramp(throttle, 580, 600, 1.0, 0.0)
    throttle[600:780] = 0.0
    ramp(throttle, 780, 800, 0.0, 0.85)
    for k in range(4):
        throttle[800 + k * 24:812 + k * 24] = 0.85
        throttle[812 + k * 24:824 + k * 24] = 0.45
    ramp(throttle, 896, 920, 0.45, 1.0)
    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, 0.85)
    brake[630:650] = 0.85
    ramp(brake, 650, 680, 0.85, 0.0)
    return make_lap(n, speed=speed, brake=brake, steering_deg=_steering(n),
                    throttle=throttle, src=src)


def _clean_throttle_lap(src: str):
    """The canonical monotonic pickup ramp: zero modulations."""
    n = 1800
    speed, throttle = _base_traces(n)
    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, 0.85)
    brake[630:650] = 0.85
    ramp(brake, 650, 680, 0.85, 0.0)
    return make_lap(n, speed=speed, brake=brake, steering_deg=_steering(n),
                    throttle=throttle, src=src)


def _weak_exit_lap(src: str):
    """LongAccel 0.2 m/s² through the exit: far below the 1.25 floor."""
    return _with_long_accel(_clean_throttle_lap(src), 0.2)


def _strong_exit_lap(src: str):
    """LongAccel 5.0 m/s² through the exit: far above the 1.25 floor."""
    return _with_long_accel(_clean_throttle_lap(src), 5.0)


# --- the statistic itself ----------------------------------------------------


def test_metric_stat_median_needs_two_values():
    assert _metric_stat([5.0], "median") is None  # too few values to state
    assert _metric_stat([0.0, 2.0], "median") == 1.0


# --- ontology shape ------------------------------------------------------------


def test_steering_throttle_principles_exist_with_the_ontology_shape():
    for pid, technique, fundamental, band in (
        (STEERING, "steering_smoothness", "rotation", "mid"),
        (MODULATION, "throttle_modulation", "corner_exit", "exit"),
        (EXIT_ACCEL, "exit_acceleration", "corner_exit", "exit"),
    ):
        p = PRINCIPLES[pid]
        assert p.technique == technique and p.fundamental == fundamental
        assert p.signal_status is SignalStatus.MEASURED
        assert isinstance(p.gate, MetricStatGate)
        assert p.band_phase == band
        assert p.coaching_expression and p.drill and p.strength_expression
        assert p.evidence_binding


def test_thresholds_live_in_config_with_the_documented_defaults():
    cfg = CONFIG.coaching
    # Corpus anchors (851-lap owner corpus, per-corner medians): dps2
    # p75 484 → floor 500; modulation count p90 1 → floor 1.0;
    # exit accel p25 1.286 → floor 1.25.
    assert cfg.steering_smoothness_floor_dps2 == 500.0
    assert cfg.throttle_modulation_floor_count == 1.0
    assert cfg.exit_accel_floor_ms2 == 1.25


def test_exit_gate_reads_acceleration_not_full_throttle_position():
    """full_throttle_dist_pct is a lap-position metric (Brands Hatch
    medians run 10.2 → 93.8 across C01→C09), so it must never be leveled
    across corners; the exit gate reads exit_accel_ms2 only."""
    p = PRINCIPLES[EXIT_ACCEL]
    assert p.gate.metric == "exit_accel_ms2"


# --- steering smoothness -------------------------------------------------------


def test_steering_smoothness_fires_on_rough_hands(db):
    _cohort(db, _rough_steering_lap, n=8, warp_phase="mid")
    found = _candidates(db, STEERING)
    assert found, "a ~3 Hz wiggle must clear the 500 dps² floor"
    c = found[0]
    assert c.corner_id == "C01"
    assert c.magnitude_kind == "seconds_lost"  # bands on the mid phase
    assert c.n == 8
    assert c.evidence_ids


def test_steering_smoothness_is_a_strength_on_smooth_hands(db):
    _cohort(db, _smooth_steering_lap, n=8)
    assert not _candidates(db, STEERING)
    strengths = _strengths(db, STEERING)
    assert strengths, "a linear ramp and hold must read as a strength"
    s = strengths[0]
    assert s.observed_kind == "metric_median"
    assert s.observed < 100  # tens by construction, far below the floor


def test_steering_smoothness_and_one_commitment_reinforce(db):
    """Different metrics, different drills: RMS steering acceleration
    (smooth the rate) vs correction count (commit to one input). Both
    speak at the same corner; neither suppresses the other."""
    _cohort(db, _rough_steering_lap, n=8, warp_phase="mid")
    assert _candidates(db, STEERING)
    assert _candidates(db, ONE_COMMITMENT)
    selection = select_coaching(
        eligible_principles(db, config=CONFIG, **COHORT),
        eligible_strengths(db, config=CONFIG, **COHORT),
        config=CONFIG,
    )
    shown = _presented_principles(selection)
    assert STEERING in shown
    assert ONE_COMMITMENT in shown


# --- throttle modulation -------------------------------------------------------


def test_throttle_modulation_fires_on_stab_and_lift(db):
    _cohort(db, _modulating_throttle_lap, n=8, warp_phase="exit")
    found = _candidates(db, MODULATION)
    assert found, "a median of 4 modulations must clear the 1.0 floor"
    c = found[0]
    assert c.corner_id == "C01"
    assert c.magnitude_kind == "seconds_lost"  # bands on the exit phase
    assert c.n == 8
    assert c.evidence_ids


def test_throttle_modulation_is_a_strength_on_a_clean_squeeze(db):
    _cohort(db, _clean_throttle_lap, n=8)
    assert not _candidates(db, MODULATION)
    strengths = _strengths(db, MODULATION)
    assert strengths, "zero modulations must read as a strength"
    s = strengths[0]
    assert s.observed_kind == "metric_median"
    assert s.observed == 0


def test_throttle_modulation_needs_two_laps_before_it_says_anything(db):
    run_synthetic_lap(db, _modulating_throttle_lap("only.csv"))
    assert not _candidates(db, MODULATION)
    assert not _strengths(db, MODULATION)


# --- exit acceleration ---------------------------------------------------------


def test_exit_acceleration_fires_on_a_weak_exit(db):
    _cohort(db, _weak_exit_lap, n=8, warp_phase="exit")
    found = _candidates(db, EXIT_ACCEL)
    assert found, "a 0.2 m/s² median exit acceleration must clear the floor"
    c = found[0]
    assert c.corner_id == "C01"
    assert c.magnitude_kind == "seconds_lost"  # bands on the exit phase
    assert c.n == 8
    assert c.evidence_ids


def test_exit_acceleration_is_a_strength_on_a_strong_exit(db):
    _cohort(db, _strong_exit_lap, n=8)
    assert not _candidates(db, EXIT_ACCEL)
    strengths = _strengths(db, EXIT_ACCEL)
    assert strengths, "a 5.0 m/s² median exit acceleration must read as a strength"
    s = strengths[0]
    assert s.observed_kind == "metric_median"
    assert s.observed == pytest.approx(5.0)


def test_exit_acceleration_and_modulation_reinforce(db):
    """Input shape vs outcome: a stabbing throttle and a weak exit are
    different faults with different drills, so both speak."""
    def builder(src):
        return _with_long_accel(_modulating_throttle_lap(src), 0.2)

    _cohort(db, builder, n=8, warp_phase="exit")
    assert _candidates(db, MODULATION)
    assert _candidates(db, EXIT_ACCEL)
    selection = select_coaching(
        eligible_principles(db, config=CONFIG, **COHORT),
        eligible_strengths(db, config=CONFIG, **COHORT),
        config=CONFIG,
    )
    shown = _presented_principles(selection)
    assert MODULATION in shown
    assert EXIT_ACCEL in shown


# --- measured-over-detector precedence (presentation only) ----------------------


def _cand(principle_id, corner="C01", band="notable"):
    return CoachingCandidate(
        principle_id=principle_id, signal_status=SignalStatus.MEASURED,
        corner_id=corner, gap_band=band, magnitude=0.2,
        magnitude_kind="seconds_lost", n=20, thin_evidence=False,
        evidence_ids=(), headline_eligible=band in ("notable", "major"),
    )


def _strength(principle_id, corner="C01"):
    return CoachingStrength(
        principle_id=principle_id, signal_status=SignalStatus.MEASURED,
        corner_id=corner, n=20, observed=0.1,
        observed_kind="metric_median", evidence_ids=(),
    )


def _presented_principles(selection):
    shown = set()
    if selection["headline"] is not None:
        shown.add(selection["headline"].principle_id)
    shown.update(c.principle_id for c in selection["secondary"])
    return shown


def test_roll_it_on_yields_where_throttle_modulation_has_a_candidate():
    selection = select_coaching([_cand(ROLL_IT_ON), _cand(MODULATION)], [])
    assert MODULATION in _presented_principles(selection)
    assert ROLL_IT_ON not in _presented_principles(selection)


def test_roll_it_on_yields_where_throttle_modulation_has_a_strength():
    selection = select_coaching([_cand(ROLL_IT_ON)], [_strength(MODULATION)])
    assert ROLL_IT_ON not in _presented_principles(selection)


def test_roll_it_on_strength_yields_where_throttle_modulation_has_a_candidate():
    selection = select_coaching([_cand(MODULATION)], [_strength(ROLL_IT_ON)])
    grouped = {g[0].principle_id for g in selection["strengths"]}
    assert ROLL_IT_ON not in grouped


def test_roll_it_on_is_untouched_at_corners_the_modulation_principle_is_silent_on():
    selection = select_coaching(
        [_cand(ROLL_IT_ON, corner="C02"), _cand(MODULATION, corner="C01")], [],
    )
    assert ROLL_IT_ON in _presented_principles(selection)


def test_eligibility_itself_is_not_suppressed(db):
    """Precedence is presentation-only: on a stabbing throttle BOTH
    principles stay eligible, and the selection decides which one
    speaks — the pinned A57 behaviour, extended to the detector pair."""
    _cohort(db, _modulating_throttle_lap, n=8, warp_phase="exit")
    eligible_ids = {c.principle_id for c in eligible_principles(db, config=CONFIG, **COHORT)}
    assert MODULATION in eligible_ids
    assert ROLL_IT_ON in eligible_ids
    selection = select_coaching(
        eligible_principles(db, config=CONFIG, **COHORT),
        eligible_strengths(db, config=CONFIG, **COHORT),
        config=CONFIG,
    )
    assert ROLL_IT_ON not in _presented_principles(selection)


def test_rollup_applies_the_same_precedence(db):
    _cohort(db, _modulating_throttle_lap, n=8, warp_phase="exit")
    rollup = build_coaching_rollup(db, driver="owner", config=CONFIG)
    fault_ids = {p["coaching_principle_id"] for p in rollup["patterns"]}
    assert MODULATION in fault_ids
    roll_patterns = [p for p in rollup["patterns"] if p["coaching_principle_id"] == ROLL_IT_ON]
    assert all(
        inst["corner_id"] != "C01" for p in roll_patterns for inst in p["instances"]
    )
