"""M1 corner-identity tests: build -> freeze -> match, fallbacks, fixtures."""

from pathlib import Path

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.corners.identity import build_corner_map
from driverdna.corners.segmenter import segment_lap
from driverdna.ingest.parser import parse_lap
from synth import (
    CORNER_WINDOWS,
    TRACK_LAT,
    TRACK_LON,
    TRACK_N as N,
    make_lap,
    ramp,
    track_lap,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIG = DriverDNAConfig()


def build_map_from(*laps):
    pairs = [(lap, segment_lap(lap, CONFIG)) for lap in laps]
    return build_corner_map(pairs, CONFIG.identity), pairs


def test_build_assigns_track_ordered_ids():
    corner_map, _ = build_map_from(track_lap())
    assert [c.corner_id for c in corner_map.corners] == ["C01", "C02", "C03"]
    dists = [c.lap_dist for c in corner_map.corners]
    assert dists == sorted(dists)


def test_jittered_lap_matches_same_ids_in_order():
    corner_map, _ = build_map_from(track_lap())
    jittered = track_lap(lat=TRACK_LAT + 0.0003)  # ~33 m offset, inside radius
    spans = segment_lap(jittered, CONFIG)
    ids = corner_map.match_lap(jittered, spans, CONFIG.identity)
    assert ids == ["C01", "C02", "C03"]


def test_missing_corner_matches_the_rest():
    corner_map, _ = build_map_from(track_lap())
    partial = track_lap(windows=[CORNER_WINDOWS[0], CORNER_WINDOWS[2]])
    spans = segment_lap(partial, CONFIG)
    ids = corner_map.match_lap(partial, spans, CONFIG.identity)
    assert ids == ["C01", "C03"]


def test_unknown_corner_is_unmatched_not_forced():
    corner_map, _ = build_map_from(track_lap())
    extra = track_lap(windows=CORNER_WINDOWS + [(2200, 2350)])
    spans = segment_lap(extra, CONFIG)
    ids = corner_map.match_lap(extra, spans, CONFIG.identity)
    assert ids == ["C01", "C02", None, "C03"]


def test_degraded_gps_falls_back_to_lap_distance():
    corner_map, _ = build_map_from(track_lap())
    blind = track_lap(lat=np.full(N, np.nan), lon=np.full(N, np.nan))
    spans = segment_lap(blind, CONFIG)
    ids = corner_map.match_lap(blind, spans, CONFIG.identity)
    assert ids == ["C01", "C02", "C03"]


def _double_dip_lap(deeper_first: bool):
    """One complex with two speed dips 0.12 of a lap (~133 m) apart."""
    steering = np.zeros(N)
    steering[650:1250] = 25.0
    speed = np.full(N, 50.0)
    d1, d2 = (24.0, 26.0) if deeper_first else (26.0, 24.0)
    ramp(speed, 660, 700, 50.0, d1)
    ramp(speed, 700, 900, d1, 30.0)
    ramp(speed, 900, 1132, 30.0, d2)
    ramp(speed, 1132, 1250, d2, 50.0)
    return make_lap(N, speed=speed, steering_deg=steering, lat=TRACK_LAT.copy(), lon=TRACK_LON.copy())


def test_primary_apex_flip_still_matches_via_secondary_apex():
    lap_a = _double_dip_lap(deeper_first=True)
    corner_map, _ = build_map_from(lap_a)
    assert len(corner_map.corners) == 1

    lap_b = _double_dip_lap(deeper_first=False)  # primary now ~133 m away
    spans = segment_lap(lap_b, CONFIG)
    assert len(spans) == 1 and len(spans[0].landmarks.apexes) == 2
    ids = corner_map.match_lap(lap_b, spans, CONFIG.identity)
    assert ids == ["C01"]


def test_build_is_deterministic():
    map_a, _ = build_map_from(track_lap())
    map_b, _ = build_map_from(track_lap())
    assert map_a == map_b


@pytest.mark.parametrize(
    "filename,n_corners",
    [("Garage_61_RH11X7.csv", 10), ("Garage_61_HKWPXX.csv", 14)],
)
def test_fixture_self_match_is_complete_and_ordered(filename, n_corners):
    lap = parse_lap(FIXTURES_DIR / filename)
    spans = segment_lap(lap, CONFIG)
    corner_map = build_corner_map([(lap, spans)], CONFIG.identity)
    assert len(corner_map.corners) == n_corners
    ids = corner_map.match_lap(lap, spans, CONFIG.identity)
    assert ids == [f"C{i + 1:02d}" for i in range(n_corners)]


def test_real_race_laps_match_the_frozen_map():
    """Cross-lap identity on real data: the map frozen from the best lap
    must match the messier race laps well, never assign one identity twice
    in a lap, and leave genuine drift unmatched rather than forcing it."""
    best = parse_lap(FIXTURES_DIR / "Garage_61_HKWPXX.csv")
    corner_map = build_corner_map(
        [(best, segment_lap(best, CONFIG))], CONFIG.identity
    )
    for filename in ("Garage_61_W5JRZB.csv", "Garage_61_K56YRV.csv",
                     "Garage_61_VHC6M4.csv"):
        lap = parse_lap(FIXTURES_DIR / filename)
        spans = segment_lap(lap, CONFIG)
        ids = corner_map.match_lap(lap, spans, CONFIG.identity)
        matched = [i for i in ids if i is not None]
        assert len(matched) >= 11, f"{filename}: only {len(matched)} matched"
        assert len(matched) == len(set(matched)), (
            f"{filename}: an identity was assigned to two spans"
        )
        assert matched == sorted(matched), f"{filename}: IDs out of track order"
