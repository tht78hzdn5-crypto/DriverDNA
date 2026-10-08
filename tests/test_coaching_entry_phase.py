"""coach-onto-v5 (SPEC.md A56): the entry-phase principles.

Tranche 1 of the coaching-ontology expansion (docs/COACHING-FUNDAMENTALS-
REVIEW.md §3): three braking techniques were measured and scored but had
no principle — `trail_braking`, `brake_application`, and
`brake_point_selection` could never be spoken. These tests pin the new
`MetricStatGate` eligibility, the config thresholds it reads, the strength
complements, and the measured-over-proxy presentation precedence between
`cp.brake_point_selection.same_marker` (measured, robust IQR of
brake_point_dist_pct) and `cp.entry_commitment.trust_the_proxy` (proxy,
raw CV of the same metric).

Synthetic cohorts run the full pipeline, mirroring test_coaching_engine.py:
each builder isolates exactly one entry fault so a firing (or silence) is
attributable to one gate.
"""

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

TRAIL = "cp.trail_braking.carry_the_brake"
APPLICATION = "cp.brake_application.get_to_peak"
SAME_MARKER = "cp.brake_point_selection.same_marker"
PROXY = "cp.entry_commitment.trust_the_proxy"


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


def _entry_window(db) -> tuple[float, float]:
    map_pk, _ = db.load_corner_map(car=COHORT["car"], track=COHORT["track"])
    stored = db.load_corner_windows(map_pk)
    windows = phase_windows_from_stored(stored["C01"])
    return windows.window("entry")


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


def _no_trail_lap(src: str, peak: float = 0.85):
    """Brake fully released before the steering starts: overlap = 0.
    Application is steep (~1.8/s) and the brake point never moves, so the
    ONLY new-principle fault available is the missing trail braking."""
    n = 1800
    speed, throttle = _base_traces(n)
    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, peak)
    brake[630:650] = peak
    ramp(brake, 650, 680, peak, 0.0)
    return make_lap(n, speed=speed, brake=brake, steering_deg=_steering(n),
                    throttle=throttle, src=src)


def _trail_lap(src: str, peak: float = 0.85):
    """Brake carried ~1.6 s into the steering: the trail-braking strength.
    Steering begins earlier (660) so the held brake overlaps it."""
    n = 1800
    speed, throttle = _base_traces(n)
    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, peak)
    brake[630:710] = peak
    ramp(brake, 710, 770, peak, 0.0)
    return make_lap(n, speed=speed, brake=brake,
                    steering_deg=_steering(n, start=660),
                    throttle=throttle, src=src)


def _slow_application_lap(src: str):
    """A 3-second squeeze to peak 0.85 (rate ~0.29/s) that IS trailed into
    the corner — isolates the application fault from the trail fault."""
    n = 1800
    speed = np.full(n, 45.0)
    ramp(speed, 470, 750, 45.0, 28.0)
    ramp(speed, 750, 900, 28.0, 45.0)
    throttle = np.ones(n)
    ramp(throttle, 450, 470, 1.0, 0.0)
    throttle[470:780] = 0.0
    ramp(throttle, 780, 830, 0.0, 1.0)
    brake = np.zeros(n)
    ramp(brake, 470, 650, 0.0, 0.85)
    brake[650:690] = 0.85
    ramp(brake, 690, 730, 0.85, 0.0)
    return make_lap(n, speed=speed, brake=brake,
                    steering_deg=_steering(n, start=660),
                    throttle=throttle, src=src)


def _fast_application_lap(src: str):
    """Peak reached in ~0.1 s and trailed in: the application strength."""
    n = 1800
    speed, throttle = _base_traces(n)
    brake = np.zeros(n)
    ramp(brake, 600, 608, 0.0, 0.85)
    brake[608:700] = 0.85
    ramp(brake, 700, 760, 0.85, 0.0)
    return make_lap(n, speed=speed, brake=brake,
                    steering_deg=_steering(n, start=660),
                    throttle=throttle, src=src)


def _brake_point_lap(src: str, start: int):
    """One canonical corner whose whole brake event sits at `start`;
    steering/speed/throttle are the canonical fixed traces, mirroring
    test_coaching_engine.py's _braking_cv_cohort (brake-only shifts are
    the proven way to move brake_point_dist_pct within one corner map)."""
    lap = make_lap(1800, src=src)
    from synth import one_corner_lap
    canonical = one_corner_lap()
    lap.speed = canonical.speed
    lap.throttle = canonical.throttle
    lap.steering_deg = canonical.steering_deg
    brake = np.zeros(1800)
    ramp(brake, start, start + 30, 0.0, 0.85)
    brake[start + 30:start + 70] = 0.85
    ramp(brake, start + 70, start + 100, 0.85, 0.0)
    lap.brake = brake
    return lap


def _cohort(db, builder, n=8, warp_entry=False):
    run_synthetic_lap(db, builder("lap0.csv"), session_key="s0")
    window = _entry_window(db) if warp_entry else None
    for i in range(1, n):
        lap = builder(f"lap{i}.csv")
        if warp_entry:
            lap = warp_time(lap, window, (i % 4) * 0.08)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")


# --- the statistic itself ----------------------------------------------------


def test_metric_stat_median_and_iqr():
    assert _metric_stat([1.0, 2.0, 9.0], "median") == 2.0
    # IQR is a spread in the metric's own units — no division by a mean,
    # so a position metric whose mean approaches zero cannot explode it
    # (the pooled-CV pathology flagged in the fundamentals review §4.4).
    assert _metric_stat([0.0, 0.0, 0.0, 4.0], "iqr") == pytest.approx(1.0)
    assert _metric_stat([5.0], "median") is None  # too few values to state
    assert _metric_stat([1.0, 2.0, 3.0], "iqr") is None  # IQR needs >= 4


# --- ontology shape ------------------------------------------------------------


def test_entry_phase_principles_exist_with_the_ontology_shape():
    for pid, technique in (
        (TRAIL, "trail_braking"),
        (APPLICATION, "brake_application"),
        (SAME_MARKER, "brake_point_selection"),
    ):
        p = PRINCIPLES[pid]
        assert p.technique == technique and p.fundamental == "braking"
        assert p.signal_status is SignalStatus.MEASURED
        assert isinstance(p.gate, MetricStatGate)
        assert p.band_phase == "entry"
        assert p.coaching_expression and p.drill and p.strength_expression
        assert p.evidence_binding


def test_thresholds_live_in_config_with_the_documented_defaults():
    cfg = CONFIG.coaching
    assert cfg.braking_zone_peak_floor == 0.50
    assert cfg.trail_brake_overlap_floor_s == 0.10
    assert cfg.brake_application_rate_floor == 0.35
    assert cfg.brake_point_iqr_floor_pct == 1.0


# --- trail braking -------------------------------------------------------------


def test_trail_braking_fires_when_brake_is_dropped_before_turn_in(db):
    _cohort(db, _no_trail_lap, n=8, warp_entry=True)
    found = _candidates(db, TRAIL)
    assert found, "zero brake-while-steering overlap must make it eligible"
    c = found[0]
    assert c.corner_id == "C01"
    assert c.magnitude_kind == "seconds_lost"  # bands on the entry phase
    assert c.n == 8
    assert c.evidence_ids


def test_trail_braking_is_a_strength_when_the_brake_is_carried_in(db):
    _cohort(db, _trail_lap, n=8)
    assert not _candidates(db, TRAIL)
    strengths = _strengths(db, TRAIL)
    assert strengths, "carrying the brake past turn-in must read as a strength"
    s = strengths[0]
    assert s.observed_kind == "metric_median"
    assert s.observed >= 1.0  # ~1.6 s of brake-while-steering by construction


def test_trail_braking_guard_keeps_light_braking_corners_out_of_scope(db):
    _cohort(db, lambda src: _no_trail_lap(src, peak=0.30), n=8)
    assert not _candidates(db, TRAIL)
    assert not _strengths(db, TRAIL)


# --- brake application -----------------------------------------------------------


def test_brake_application_fires_on_a_slow_squeeze(db):
    _cohort(db, _slow_application_lap, n=8, warp_entry=True)
    found = _candidates(db, APPLICATION)
    assert found, "a ~0.29/s median application rate must clear the floor"
    assert found[0].magnitude_kind == "seconds_lost"
    # ...and the trail gate stays silent: this driver DOES carry the brake in.
    assert not _candidates(db, TRAIL)


def test_brake_application_is_a_strength_on_a_decisive_application(db):
    _cohort(db, _fast_application_lap, n=8)
    assert not _candidates(db, APPLICATION)
    strengths = _strengths(db, APPLICATION)
    assert strengths
    assert strengths[0].observed >= 2.0  # ~8/s by construction, far above the floor


def test_brake_application_guard_keeps_trivial_peaks_out_of_scope(db):
    def lazy_light(src):
        lap = _slow_application_lap(src)
        lap.brake = lap.brake * (0.30 / 0.85)
        return lap

    _cohort(db, lazy_light, n=8)
    assert not _candidates(db, APPLICATION)
    assert not _strengths(db, APPLICATION)


# --- brake-point selection -------------------------------------------------------


def test_same_marker_fires_on_a_wandering_brake_point(db):
    for i in range(10):
        run_synthetic_lap(db, _brake_point_lap(f"bp{i}.csv", 560 + i * 30),
                          session_key=f"s{i % 2}")
    found = _candidates(db, SAME_MARKER)
    assert found, "an ~8 %lap IQR of brake points must clear the 1.0 floor"
    assert found[0].n == 10


def test_same_marker_is_a_strength_on_a_fixed_marker(db):
    for i in range(10):
        run_synthetic_lap(db, _brake_point_lap(f"bp{i}.csv", 600 + (i % 3) * 4),
                          session_key=f"s{i % 2}")
    assert not _candidates(db, SAME_MARKER)
    strengths = _strengths(db, SAME_MARKER)
    assert strengths, "a brake point hit within a few samples must read as a strength"
    assert strengths[0].observed_kind == "metric_iqr"
    assert strengths[0].observed < 1.0


def test_same_marker_needs_four_laps_before_it_says_anything(db):
    for i in range(3):
        run_synthetic_lap(db, _brake_point_lap(f"bp{i}.csv", 560 + i * 60),
                          session_key="s0")
    assert not _candidates(db, SAME_MARKER)
    assert not _strengths(db, SAME_MARKER)


# --- measured-over-proxy precedence (presentation only) --------------------------


def _cand(principle_id, corner="C01", band="notable"):
    return CoachingCandidate(
        principle_id=principle_id, signal_status=(
            SignalStatus.PROXY if principle_id == PROXY else SignalStatus.MEASURED
        ),
        corner_id=corner, gap_band=band, magnitude=0.2,
        magnitude_kind="seconds_lost", n=20, thin_evidence=False,
        evidence_ids=(), headline_eligible=band in ("notable", "major"),
    )


def _strength(principle_id, corner="C01"):
    return CoachingStrength(
        principle_id=principle_id, signal_status=(
            SignalStatus.PROXY if principle_id == PROXY else SignalStatus.MEASURED
        ),
        corner_id=corner, n=20, observed=0.1,
        observed_kind="metric_iqr", evidence_ids=(),
    )


def _presented_principles(selection):
    shown = set()
    if selection["headline"] is not None:
        shown.add(selection["headline"].principle_id)
    shown.update(c.principle_id for c in selection["secondary"])
    return shown


def test_proxy_yields_where_the_measured_principle_has_a_candidate():
    selection = select_coaching([_cand(PROXY), _cand(SAME_MARKER)], [])
    assert SAME_MARKER in _presented_principles(selection)
    assert PROXY not in _presented_principles(selection)


def test_proxy_yields_where_the_measured_principle_has_a_strength():
    selection = select_coaching([_cand(PROXY)], [_strength(SAME_MARKER)])
    assert PROXY not in _presented_principles(selection)


def test_proxy_strength_yields_where_the_measured_principle_has_a_candidate():
    selection = select_coaching([_cand(SAME_MARKER)], [_strength(PROXY)])
    grouped = {g[0].principle_id for g in selection["strengths"]}
    assert PROXY not in grouped


def test_proxy_is_untouched_at_corners_the_measured_principle_is_silent_on():
    selection = select_coaching(
        [_cand(PROXY, corner="C02"), _cand(SAME_MARKER, corner="C01")], [],
    )
    assert PROXY in _presented_principles(selection)


def test_eligibility_itself_is_not_suppressed(db):
    """Precedence is presentation-only: on a wandering brake point BOTH
    principles stay eligible — the pinned behaviour of
    test_coaching_engine.py's proxy test — and the selection decides
    which one speaks."""
    for i in range(10):
        run_synthetic_lap(db, _brake_point_lap(f"bp{i}.csv", 560 + i * 30),
                          session_key=f"s{i % 2}")
    eligible_ids = {c.principle_id for c in eligible_principles(db, config=CONFIG, **COHORT)}
    assert SAME_MARKER in eligible_ids
    selection = select_coaching(
        eligible_principles(db, config=CONFIG, **COHORT),
        eligible_strengths(db, config=CONFIG, **COHORT),
        config=CONFIG,
    )
    assert PROXY not in _presented_principles(selection)


def test_rollup_applies_the_same_precedence(db):
    for i in range(10):
        run_synthetic_lap(db, _brake_point_lap(f"bp{i}.csv", 560 + i * 30),
                          session_key=f"s{i % 2}")
    rollup = build_coaching_rollup(db, driver="owner", config=CONFIG)
    fault_ids = {p["coaching_principle_id"] for p in rollup["patterns"]}
    assert SAME_MARKER in fault_ids
    proxy_patterns = [p for p in rollup["patterns"] if p["coaching_principle_id"] == PROXY]
    assert all(
        inst["corner_id"] != "C01" for p in proxy_patterns for inst in p["instances"]
    )
