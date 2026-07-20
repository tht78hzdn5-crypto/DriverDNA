"""M7b: deterministic eligibility, ranking, and gap-band tone.

Real synthetic cohorts (not hand-built candidate objects) so the gate
queries (detector rate, vs-self finding reuse, metric CV) run against the
actual DB shape M2/M3/M6 already produce.
"""

import numpy as np
import pytest

from driverdna.coaching.engine import (
    CoachingCandidate,
    eligible_principles,
    select_coaching,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus
from driverdna.pipeline import phase_windows_from_stored
from synth import make_lap, one_corner_lap, ramp, track_lap, warp_time
from synth import run_synthetic_lap as _run

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


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


def _early_release_lap(src: str) -> "TelemetryLap":
    n = 1800
    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, 0.7)
    ramp(brake, 630, 660, 0.7, 0.0)
    steering = np.zeros(n)
    ramp(steering, 680, 710, 0.0, 25.0)
    steering[710:840] = 25.0
    ramp(steering, 840, 870, 25.0, 0.0)
    speed = np.full(n, 45.0)
    ramp(speed, 600, 760, 45.0, 28.0)
    ramp(speed, 760, 900, 28.0, 45.0)
    throttle = np.ones(n)
    ramp(throttle, 580, 600, 1.0, 0.0)
    throttle[600:780] = 0.0
    ramp(throttle, 780, 830, 0.0, 1.0)
    return make_lap(
        n, speed=speed, brake=brake, steering_deg=steering, throttle=throttle, src=src,
    )


def _entry_window(db) -> tuple[float, float]:
    map_pk, _ = db.load_corner_map(car=COHORT["car"], track=COHORT["track"])
    stored = db.load_corner_windows(map_pk)
    windows = phase_windows_from_stored(stored["C01"])
    return windows.window("entry")


def _finish_the_front_cohort(db, n=8):
    """Every lap triggers brake-release-taper (100% >= the 0.5 floor);
    increasing warp on the entry window gives real, growing seconds-lost
    for gap-band ranking, decoupled from whether the detector fires."""
    base = _early_release_lap("release0.csv")
    run_synthetic_lap(db, base, session_key="s0")
    window = _entry_window(db)
    for i in range(1, n):
        lap = _early_release_lap(f"release{i}.csv")
        lap = warp_time(lap, window, i * 0.06)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")


def _rotation_cohort(db, n=12):
    for i in range(n):
        run_synthetic_lap(db, track_lap(src=f"lap{i}.csv"), session_key=f"s{i % 2}")


def _mid_weakness_cohort(db, n_fast=6, n_slow=6, warp_s=0.4):
    for i in range(n_fast):
        run_synthetic_lap(db, track_lap(src=f"fast{i}.csv"), session_key=f"s{i % 2}")
    for i in range(n_slow):
        lap = warp_time(track_lap(src=f"slow{i}.csv"), (0.19, 0.22), warp_s)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")


def _braking_cv_cohort(db, n=8):
    for i in range(n):
        lap = one_corner_lap()
        lap.source_path = lap.source_path.with_name(f"brake{i}.csv")
        shift = i * 8  # bigger shift than test_scoring's, for a real CV
        lap.brake[:] = 0.0
        ramp(lap.brake, 600 + shift, 630 + shift, 0.0, 0.8)
        lap.brake[630 + shift:690 + shift] = 0.8
        ramp(lap.brake, 690 + shift, 720 + shift, 0.8, 0.0)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")


# --- no_signal: always present, never gated ---------------------------------


def test_no_signal_principle_always_present_even_with_no_laps(db):
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    self_checks = [c for c in candidates if c.signal_status is SignalStatus.NO_SIGNAL]
    assert len(self_checks) == 1
    c = self_checks[0]
    assert c.principle_id == "cp.eye_line.look_further"
    assert c.corner_id is None and c.gap_band is None and c.magnitude is None
    assert c.evidence_ids == () and not c.headline_eligible


def test_no_signal_principle_never_headline_eligible_regardless_of_data(db):
    _finish_the_front_cohort(db)
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    look_further = next(c for c in candidates if c.principle_id == "cp.eye_line.look_further")
    assert not look_further.headline_eligible
    result = select_coaching(candidates)
    assert result["headline"] is None or result["headline"].principle_id != "cp.eye_line.look_further"
    assert look_further in result["self_checks"]


# --- detector-gated eligibility + banding -----------------------------------


def test_detector_gated_principle_eligible_with_growing_gap_band(db):
    _finish_the_front_cohort(db)
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    c = next(c for c in candidates if c.principle_id == "cp.brake_release.finish_the_front")
    assert c.corner_id == "C01"
    assert c.magnitude_kind == "seconds_lost"
    assert c.gap_band in ("moderate", "notable", "major")
    assert c.n == 8
    assert all(e.startswith("obs:") for e in c.evidence_ids)


def test_detector_gate_absent_when_never_triggers(db):
    _rotation_cohort(db)  # track_lap never brakes -> brake-release-taper never fires
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    assert not any(c.principle_id == "cp.brake_release.finish_the_front" for c in candidates)


def test_is_deterministic(db):
    _finish_the_front_cohort(db)
    a = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    b = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    assert a == b


# --- FindingGate (carry_the_middle) reuses vs_self_findings ------------------


def test_finding_gate_eligible_when_vs_self_finding_shown(db):
    _mid_weakness_cohort(db)
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    carry = [c for c in candidates if c.principle_id == "cp.rotation_efficiency.carry_the_middle"]
    assert carry, "the planted mid-phase weakness must make carry_the_middle eligible"
    assert any(c.corner_id == "C01" for c in carry)
    top = max(carry, key=lambda c: c.magnitude)
    assert top.gap_band in ("moderate", "notable", "major")
    assert top.evidence_ids  # reused straight from the finding


def test_finding_gate_absent_without_a_shown_finding(db):
    _rotation_cohort(db)  # identical laps -> no shown vs-self finding anywhere
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    assert not any(c.principle_id == "cp.rotation_efficiency.carry_the_middle" for c in candidates)


# --- MetricCVGate (trust_the_proxy, same_lap_twice) --------------------------


def test_trust_the_proxy_eligible_on_real_brake_point_variation(db):
    _braking_cv_cohort(db)
    # brake_point_dist_pct's own spread here is real but modest (a shifting
    # brake ramp confined to stay well clear of turn-in, so segmentation
    # stays valid) - lower the floor rather than distort the synthetic
    # corner geometry chasing an arbitrary default threshold.
    tuned = CONFIG.model_copy(deep=True)
    tuned.coaching.commitment_cv_floor = 0.02
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=tuned)
    proxy = [c for c in candidates if c.principle_id == "cp.entry_commitment.trust_the_proxy"]
    assert proxy
    assert all(c.signal_status is SignalStatus.PROXY for c in proxy)
    assert all(c.magnitude_kind == "seconds_lost" for c in proxy)  # bands on entry phase


def test_same_lap_twice_bands_on_its_own_cv_not_seconds(db):
    _braking_cv_cohort(db)
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    consistency = [c for c in candidates if c.principle_id == "cp.repeatability.same_lap_twice"]
    assert consistency
    for c in consistency:
        assert c.magnitude_kind == "coefficient_of_variation"
        assert not c.headline_eligible  # never competes for the seconds-ranked headline


def test_cv_gate_absent_when_metrics_barely_vary(db):
    _rotation_cohort(db)  # near-identical laps -> near-zero CV
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    assert not any(c.principle_id == "cp.repeatability.same_lap_twice" for c in candidates)
    assert not any(c.principle_id == "cp.entry_commitment.trust_the_proxy" for c in candidates)


# --- select_coaching: headline / secondary / silent -------------------------


def test_select_coaching_no_data_yields_insufficient_headline(db):
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    result = select_coaching(candidates)
    assert result["headline"] is None
    assert "insufficient data" in result["headline_reason"]
    assert result["self_checks"]


def test_select_coaching_picks_largest_seconds_candidate_as_headline(db):
    _finish_the_front_cohort(db, n=10)
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    result = select_coaching(candidates)
    headline = result["headline"]
    assert headline is not None
    assert headline.principle_id == "cp.brake_release.finish_the_front"
    assert headline.headline_eligible
    pool = [c for c in candidates if c.headline_eligible]
    assert headline.magnitude == max(c.magnitude for c in pool)
    assert headline not in result["secondary"]


def test_select_coaching_secondary_excludes_negligible_and_headline():
    negligible = CoachingCandidate(
        principle_id="cp.a", signal_status=SignalStatus.MEASURED, corner_id="C01",
        gap_band="negligible", magnitude=0.01, magnitude_kind="seconds_lost", n=10,
        thin_evidence=False, evidence_ids=(), headline_eligible=False,
    )
    moderate = CoachingCandidate(
        principle_id="cp.b", signal_status=SignalStatus.MEASURED, corner_id="C01",
        gap_band="moderate", magnitude=0.08, magnitude_kind="seconds_lost", n=10,
        thin_evidence=False, evidence_ids=(), headline_eligible=False,
    )
    major = CoachingCandidate(
        principle_id="cp.c", signal_status=SignalStatus.MEASURED, corner_id="C01",
        gap_band="major", magnitude=0.5, magnitude_kind="seconds_lost", n=10,
        thin_evidence=False, evidence_ids=(), headline_eligible=True,
    )
    result = select_coaching([negligible, moderate, major])
    assert result["headline"] is major
    assert result["secondary"] == [moderate]
    assert result["silent_count"] == 1


def test_thin_evidence_flag_reflects_the_configured_floor(db):
    _finish_the_front_cohort(db, n=CONFIG.coaching.thin_evidence_floor_n - 1)
    candidates = eligible_principles(db, driver="owner", car="TestCar", track="SynthRing", config=CONFIG)
    c = next(c for c in candidates if c.principle_id == "cp.brake_release.finish_the_front")
    assert c.thin_evidence
