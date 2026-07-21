"""M2 tests: deterministic technique metrics + principle detectors."""

from pathlib import Path

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.corners.segmenter import segment_lap
from driverdna.ingest.parser import parse_lap
from driverdna.metrics.detectors import run_detectors
from driverdna.metrics.technique import (
    METRIC_DEFS,
    compute_corner_metrics,
    summarize,
)
from synth import make_lap, one_corner_lap, ramp

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIG = DriverDNAConfig()


def corner_of(lap):
    corners = segment_lap(lap, CONFIG)
    assert len(corners) == 1
    return corners[0]


def detector_by_name(results, name):
    return next((r for r in results if r.detector == name), None)


# --- Canonical corner ------------------------------------------------------


def test_one_corner_metric_values():
    lap = one_corner_lap()
    metrics = compute_corner_metrics(lap, corner_of(lap), CONFIG)

    assert set(metrics) == set(METRIC_DEFS)
    assert abs(metrics["brake_peak"] - 0.8) < 0.02
    assert 1.2 < metrics["brake_application_rate"] < 2.2
    # Release measured from leaving the near-peak plateau (~690) to off (~719).
    assert abs(metrics["brake_release_duration_s"] - 0.48) < 0.15
    assert abs(metrics["trail_brake_overlap_s"] - 0.78) < 0.15
    assert metrics["throttle_brake_overlap_s"] < 0.05
    assert abs(metrics["turn_in_dist_pct"] - 37.4) < 0.5
    assert metrics["steering_corrections"] == 0
    assert metrics["steering_smoothness_dps2"] >= 0
    assert abs(metrics["min_speed_kmh"] - 90.0) < 2.0
    assert abs(metrics["coast_s"] - 0.78) < 0.15
    assert metrics["throttle_modulation_count"] == 0
    assert metrics["abs_active_ratio"] == 0.0


def test_one_corner_detector_states():
    lap = one_corner_lap()
    span = corner_of(lap)
    metrics = compute_corner_metrics(lap, span, CONFIG)
    results = run_detectors(lap, span, metrics, CONFIG)

    assert len(results) == 5  # every detector has inputs on this corner
    taper = detector_by_name(results, "brake-release-taper")
    assert taper is not None and not taper.triggered  # release after turn-in
    assert not detector_by_name(results, "throttle-brake-overlap").triggered
    assert not detector_by_name(results, "one-steering-input").triggered
    assert not detector_by_name(results, "throttle-monotonic").triggered
    coast = detector_by_name(results, "coast-window")
    assert coast.triggered  # 0.78 s of coasting > 0.5 s default
    assert "coasting" in coast.rationale.lower() or "coast" in coast.rationale.lower()
    assert all(r.source == "vs-principle" for r in results)


# --- Shaped faults trigger their detectors ---------------------------------


def test_steering_corrections_counted_and_flagged():
    lap = one_corner_lap()
    st = lap.steering_deg
    ramp(st, 700, 706, 25.0, 15.0)
    ramp(st, 706, 712, 15.0, 25.0)
    ramp(st, 718, 724, 25.0, 32.0)
    ramp(st, 724, 730, 32.0, 25.0)

    span = corner_of(lap)
    metrics = compute_corner_metrics(lap, span, CONFIG)
    assert metrics["steering_corrections"] == 3
    result = detector_by_name(run_detectors(lap, span, metrics, CONFIG), "one-steering-input")
    assert result.triggered and result.value == 3


def test_throttle_brake_overlap_flagged():
    n = 1800
    brake = np.zeros(n)
    brake[600:660] = 0.5
    throttle = np.zeros(n)
    throttle[610:670] = 0.3
    speed = np.full(n, 40.0)
    ramp(speed, 600, 660, 40.0, 25.0)
    ramp(speed, 660, 720, 25.0, 40.0)
    lap = make_lap(n, speed=speed, brake=brake, throttle=throttle)

    span = corner_of(lap)
    metrics = compute_corner_metrics(lap, span, CONFIG)
    assert abs(metrics["throttle_brake_overlap_s"] - 0.83) < 0.06
    result = detector_by_name(
        run_detectors(lap, span, metrics, CONFIG), "throttle-brake-overlap"
    )
    assert result.triggered
    # Brake-only corner: no steering landmarks, so the one-input detector
    # must be absent, not fabricated.
    assert detector_by_name(run_detectors(lap, span, metrics, CONFIG), "one-steering-input") is None


def test_throttle_stab_flagged():
    lap = one_corner_lap()
    th = lap.throttle
    ramp(th, 760, 790, 0.0, 0.9)
    ramp(th, 790, 800, 0.9, 0.6)
    ramp(th, 800, 830, 0.6, 1.0)
    th[830:] = 1.0

    span = corner_of(lap)
    metrics = compute_corner_metrics(lap, span, CONFIG)
    assert metrics["throttle_modulation_count"] == 1
    result = detector_by_name(run_detectors(lap, span, metrics, CONFIG), "throttle-monotonic")
    assert result.triggered


def test_early_brake_release_flagged():
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
    lap = make_lap(n, speed=speed, brake=brake, steering_deg=steering, throttle=throttle)

    span = corner_of(lap)
    metrics = compute_corner_metrics(lap, span, CONFIG)
    result = detector_by_name(run_detectors(lap, span, metrics, CONFIG), "brake-release-taper")
    assert result.triggered
    assert result.value > CONFIG.detectors.release_gap_max_s


# --- Aggregation and determinism -------------------------------------------


def test_summarize():
    s = summarize([1.0, 2.0, 3.0])
    assert (s.n, s.median, s.mean) == (3, 2.0, 2.0)
    assert abs(s.spread - 1.0) < 1e-12
    assert summarize([5.0]).spread == 0.0
    assert summarize([]) is None


@pytest.mark.parametrize(
    "filename", ["Garage_61_RH11X7.csv", "Garage_61_HKWPXX.csv"]
)
def test_fixture_metrics_deterministic_and_sane(filename):
    lap = parse_lap(FIXTURES_DIR / filename)
    spans = segment_lap(lap, CONFIG)
    for span in spans:
        a = compute_corner_metrics(lap, span, CONFIG)
        b = compute_corner_metrics(lap, span, CONFIG)
        assert a == b
        for name, value in a.items():
            if value is not None:
                assert np.isfinite(value), f"{name} not finite"
        results = run_detectors(lap, span, a, CONFIG)
        assert all(np.isfinite(r.value) for r in results)
