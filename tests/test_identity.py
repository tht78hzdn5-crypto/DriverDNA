"""M1 corner-identity tests: build -> freeze -> match, fallbacks, fixtures."""

from pathlib import Path

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.corners.identity import build_corner_map
from driverdna.corners.segmenter import segment_lap
from driverdna.ingest.parser import parse_lap
from synth import make_lap, ramp

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIG = DriverDNAConfig()

# GPS along a synthetic "track": ~1113 m of latitude over one lap, so corners
# separated by 0.1 of a lap are ~111 m apart — well beyond the 75 m radius.
N = 3600
TRACK_LAT = 36.5 + 0.01 * np.linspace(0.0, 1.0, N)
TRACK_LON = np.full(N, -121.75)

CORNER_WINDOWS = [(700, 850), (1700, 1850), (2900, 3050)]


def track_lap(windows=CORNER_WINDOWS, lat=None, lon=None):
    steering = np.zeros(N)
    speed = np.full(N, 50.0)
    for start, end in windows:
        steering[start:end] = 20.0
        mid = (start + end) // 2
        ramp(speed, start, mid, 50.0, 30.0)
        ramp(speed, mid, end, 30.0, 50.0)
    return make_lap(
        N,
        speed=speed,
        steering_deg=steering,
        lat=lat if lat is not None else TRACK_LAT.copy(),
        lon=lon if lon is not None else TRACK_LON.copy(),
    )


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
