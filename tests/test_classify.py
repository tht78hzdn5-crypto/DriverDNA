"""M1 classification tests: bands, hysteresis, fixture class counts."""

from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.corners.classify import (
    MS_TO_KMH,
    CornerClass,
    classify_speed,
    classify_with_hysteresis,
)
from driverdna.corners.identity import build_corner_map
from driverdna.corners.segmenter import segment_lap
from driverdna.ingest.parser import parse_lap

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIG = DriverDNAConfig()
CLS = CONFIG.classification


@pytest.mark.parametrize(
    "kmh,expected",
    [
        (89.9, CornerClass.SLOW),
        (90.0, CornerClass.MEDIUM),
        (149.9, CornerClass.MEDIUM),
        (150.0, CornerClass.FAST),
    ],
)
def test_raw_bands(kmh, expected):
    assert classify_speed(kmh, CLS) is expected


def test_first_assignment_is_raw_and_not_a_change():
    assert classify_with_hysteresis(89.2, None, CLS) == (CornerClass.SLOW, False)


@pytest.mark.parametrize(
    "kmh,previous,expected,changed",
    [
        # Sticky inside the margin around the edge:
        (89.2, CornerClass.MEDIUM, CornerClass.MEDIUM, False),
        (95.0, CornerClass.SLOW, CornerClass.SLOW, False),
        (146.0, CornerClass.FAST, CornerClass.FAST, False),
        (154.0, CornerClass.MEDIUM, CornerClass.MEDIUM, False),
        # Beyond the margin the class flips, surfaced as a change:
        (84.9, CornerClass.MEDIUM, CornerClass.SLOW, True),
        (95.1, CornerClass.SLOW, CornerClass.MEDIUM, True),
        (144.9, CornerClass.FAST, CornerClass.MEDIUM, True),
        (155.1, CornerClass.MEDIUM, CornerClass.FAST, True),
        # A huge jump can never be held back by hysteresis:
        (200.0, CornerClass.SLOW, CornerClass.FAST, True),
    ],
)
def test_hysteresis(kmh, previous, expected, changed):
    assert classify_with_hysteresis(kmh, previous, CLS) == (expected, changed)


# Regression pins for the real fixtures under DEFAULT config (single lap, so
# median == that lap's min speed). Spa's 89.2 km/h corner is deliberately a
# borderline case sitting 0.8 below the slow/medium edge.
EXPECTED_CLASS_COUNTS = {
    # Laguna's three slow corners: T2 complex, the Corkscrew, T11 hairpin.
    "Garage_61_RH11X7.csv": {"slow": 3, "medium": 7, "fast": 0},
    "Garage_61_HKWPXX.csv": {"slow": 3, "medium": 7, "fast": 4},
}


@pytest.mark.parametrize("filename", sorted(EXPECTED_CLASS_COUNTS))
def test_fixture_class_counts_pinned(filename):
    lap = parse_lap(FIXTURES_DIR / filename)
    spans = segment_lap(lap, CONFIG)
    corner_map = build_corner_map([(lap, spans)], CONFIG.identity)
    ids = corner_map.match_lap(lap, spans, CONFIG.identity)

    speeds: dict[str, list[float]] = {}
    for span, cid in zip(spans, ids):
        speeds.setdefault(cid, []).append(span.min_speed(lap) * MS_TO_KMH)
    counts = Counter(
        classify_speed(float(np.median(v)), CLS).value for v in speeds.values()
    )
    assert dict(counts) == {
        k: v for k, v in EXPECTED_CLASS_COUNTS[filename].items() if v
    }
