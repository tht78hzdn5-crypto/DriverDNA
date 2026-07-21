"""M1 segmentation tests: synthetic landmark shapes + fixture regression pins."""

from pathlib import Path

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.corners.segmenter import segment_lap
from driverdna.ingest.parser import parse_lap
from synth import make_lap, one_corner_lap, ramp

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIG = DriverDNAConfig()

# Regression pins for the real fixtures under DEFAULT config. A conscious
# threshold change may move these — update them with the config change.
EXPECTED_CORNER_COUNT = {"Garage_61_RH11X7.csv": 10, "Garage_61_HKWPXX.csv": 14}
EXPECTED_SLOWEST_KMH = {"Garage_61_RH11X7.csv": 62.9, "Garage_61_HKWPXX.csv": 51.9}


def near(value, target, tol):
    assert value is not None and abs(value - target) <= tol, (
        f"expected ~{target}±{tol}, got {value}"
    )


# --- Synthetic shapes ------------------------------------------------------


def test_single_corner_all_landmarks():
    lap = one_corner_lap()
    corners = segment_lap(lap, CONFIG)
    assert len(corners) == 1
    lm = corners[0].landmarks
    near(lm.brake_start, 602, 4)
    near(lm.peak_brake, 630, 4)
    near(lm.turn_in, 672, 6)
    near(lm.brake_release, 719, 5)
    near(lm.apex, 750, 6)
    near(lm.throttle_pickup, 766, 4)
    near(lm.full_throttle, 817, 6)
    near(lm.exit, 876, 8)
    assert lm.entry == lm.brake_start
    assert lm.apexes == (lm.apex,)


def test_steering_only_corner_has_no_brake_landmarks():
    n = 1800
    steering = np.zeros(n)
    ramp(steering, 600, 615, 0.0, 20.0)
    steering[615:885] = 20.0
    ramp(steering, 885, 900, 20.0, 0.0)
    speed = np.full(n, 50.0)
    ramp(speed, 600, 750, 50.0, 40.0)
    ramp(speed, 750, 900, 40.0, 50.0)
    throttle = np.ones(n)
    ramp(throttle, 580, 620, 1.0, 0.6)
    throttle[620:800] = 0.6
    ramp(throttle, 800, 860, 0.6, 1.0)

    lap = make_lap(n, speed=speed, steering_deg=steering, throttle=throttle)
    corners = segment_lap(lap, CONFIG)
    assert len(corners) == 1
    lm = corners[0].landmarks
    assert lm.brake_start is None and lm.peak_brake is None and lm.brake_release is None
    assert lm.turn_in is not None and lm.entry == lm.turn_in
    near(lm.apex, 750, 8)
    # Never lifted below pickup level: deepest modulation stands in.
    assert lm.throttle_pickup is not None and 600 <= lm.throttle_pickup <= 700
    near(lm.full_throttle, 855, 6)


def test_double_apex_complex_is_one_corner_with_two_apexes():
    n = 1800
    steering = np.zeros(n)
    ramp(steering, 590, 605, 0.0, 25.0)
    steering[605:995] = 25.0
    ramp(steering, 995, 1010, 25.0, 0.0)
    speed = np.full(n, 50.0)
    ramp(speed, 600, 700, 50.0, 25.0)
    ramp(speed, 700, 800, 25.0, 32.0)
    ramp(speed, 800, 900, 32.0, 24.0)
    ramp(speed, 900, 1000, 24.0, 50.0)

    lap = make_lap(n, speed=speed, steering_deg=steering)
    corners = segment_lap(lap, CONFIG)
    assert len(corners) == 1
    lm = corners[0].landmarks
    assert len(lm.apexes) == 2
    near(lm.apexes[0], 700, 8)
    near(lm.apexes[1], 900, 8)
    assert lm.apex == lm.apexes[1]  # primary = global minimum (24 < 25)


def test_nearby_activity_merges_into_one_corner():
    n = 1800
    steering = np.zeros(n)
    steering[600:700] = 20.0
    steering[715:800] = 20.0  # 0.25 s gap < merge_gap_s
    lap = make_lap(n, steering_deg=steering)
    assert len(segment_lap(lap, CONFIG)) == 1


def test_distant_activity_stays_two_corners():
    n = 1800
    steering = np.zeros(n)
    steering[600:700] = 20.0
    steering[880:980] = 20.0  # 3 s gap
    lap = make_lap(n, steering_deg=steering)
    assert len(segment_lap(lap, CONFIG)) == 2


def test_gear0_spans_are_excluded():
    n = 1800
    steering = np.zeros(n)
    steering[300:500] = 20.0
    gear = np.full(n, 4, dtype=np.int64)
    gear[250:550] = 0
    lap = make_lap(n, steering_deg=steering, gear=gear)
    assert segment_lap(lap, CONFIG) == []


def test_short_blip_is_dropped():
    n = 1800
    steering = np.zeros(n)
    steering[600:618] = 15.0  # 0.3 s < min_corner_duration_s
    lap = make_lap(n, steering_deg=steering)
    assert segment_lap(lap, CONFIG) == []


# --- Real fixtures ---------------------------------------------------------


@pytest.mark.parametrize("filename", sorted(EXPECTED_CORNER_COUNT))
def test_fixture_corner_count_pinned(filename):
    lap = parse_lap(FIXTURES_DIR / filename)
    corners = segment_lap(lap, CONFIG)
    assert len(corners) == EXPECTED_CORNER_COUNT[filename]


@pytest.mark.parametrize("filename", sorted(EXPECTED_CORNER_COUNT))
def test_fixture_landmark_invariants(filename):
    lap = parse_lap(FIXTURES_DIR / filename)
    corners = segment_lap(lap, CONFIG)
    prev_end = 0
    for c in corners:
        lm = c.landmarks
        assert prev_end <= c.start < c.end <= lap.n_samples
        prev_end = c.end
        assert c.start <= lm.entry < c.end
        assert c.start <= lm.apex < c.end
        assert lm.apex in lm.apexes
        if lm.brake_start is not None and lm.peak_brake is not None:
            assert lm.brake_start <= lm.peak_brake
        if lm.peak_brake is not None and lm.brake_release is not None:
            assert lm.peak_brake <= lm.brake_release
        if lm.throttle_pickup is not None and lm.full_throttle is not None:
            assert lm.throttle_pickup <= lm.full_throttle
        assert c.start <= lm.exit < c.end


@pytest.mark.parametrize("filename", sorted(EXPECTED_CORNER_COUNT))
def test_fixture_slowest_corner_pinned(filename):
    lap = parse_lap(FIXTURES_DIR / filename)
    corners = segment_lap(lap, CONFIG)
    slowest = min(c.min_speed(lap) for c in corners) * 3.6
    assert abs(slowest - EXPECTED_SLOWEST_KMH[filename]) < 3.0


def test_spa_bus_stop_is_multi_apex():
    lap = parse_lap(FIXTURES_DIR / "Garage_61_HKWPXX.csv")
    corners = segment_lap(lap, CONFIG)
    assert any(len(c.landmarks.apexes) >= 2 for c in corners)


@pytest.mark.parametrize("filename", sorted(EXPECTED_CORNER_COUNT))
def test_segmentation_is_deterministic(filename):
    lap = parse_lap(FIXTURES_DIR / filename)
    assert segment_lap(lap, CONFIG) == segment_lap(lap, CONFIG)
