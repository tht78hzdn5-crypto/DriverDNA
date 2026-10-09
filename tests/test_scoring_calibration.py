"""Golden-driver calibration tests for the dm-v3 consistency statistic
(SPEC.md A56) — the meaning-ward tests the BUG-042 audit found absent.

The rest of the scoring suite asserts the *formula*: given these inputs,
the component equals the documented arithmetic. These tests assert the
*calibration*: synthetic drivers constructed to sit at known multiples
of each metric's reference dispersion must land where the scale claims
they land — a driver at exactly the reference population's typical
dispersion (1.0x) scores mid-scale, a metronome (0.2x) scores high, a
sloppy driver (2.5x) scores low, and the ordering is monotone. dm-v2's
suite had no test of this shape, which is how a calibration that read
0.0 on the owner's real corpus shipped green (BUG-042).

Construction: for each metric, five values symmetric about a plausible
centre, [c-2e, c-e, c, c+e, c+2e]. The scaled MAD of that set is exactly
1.4826 * e, so choosing e = multiple * anchor / 1.4826 puts the sample
at `multiple` x the metric's reference dispersion by construction. The
values are statistic fixtures, not telemetry (a count metric's values
need not be integers here, centres are approximate) — the stub pattern
is the same one test_scoring.py uses.
"""

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.model.scoring import _consistency_component, _scoring_metric_names

CONFIG = DriverDNAConfig()
_MAD_SCALE = 1.4826

# Plausible centre per metric the consistency fundamental pools. If the
# taxonomy grows a metric, this test fails on the coverage assert —
# deliberately: a new metric needs a reference anchor in config AND a
# centre here before the calibration claim covers it.
_CENTRES = {
    "abs_active_ratio": 0.5,
    "apex_dist_pct": 50.0,
    "brake_application_rate": 1.0,
    "brake_peak": 0.7,
    "brake_point_dist_pct": 50.0,
    "brake_release_duration_s": 0.5,
    "coast_s": 1.0,
    "exit_accel_ms2": 3.0,
    "full_throttle_dist_pct": 60.0,
    "min_speed_kmh": 80.0,
    "steering_corrections": 2.0,
    "steering_smoothness_dps2": 100.0,
    "throttle_brake_overlap_s": 0.2,
    "throttle_modulation_count": 2.0,
    "throttle_pickup_dist_pct": 50.0,
    "trail_brake_overlap_s": 0.4,
    "turn_in_dist_pct": 50.0,
    "yaw_peak_rate": 0.5,
}


class _StubMetricDB:
    def __init__(self, tables):
        self._tables = tables

    def self_metric_table(self, *, driver, car, track, lap_pks=None):
        return self._tables.get((car, track), {})


def _driver_at(multiple: float) -> _StubMetricDB:
    anchors = CONFIG.model.consistency_metric_reference_dispersion
    metrics = {}
    for name in _scoring_metric_names("consistency"):
        centre = _CENTRES[name]
        e = multiple * anchors[name] / _MAD_SCALE
        metrics[name] = [centre - 2 * e, centre - e, centre, centre + e, centre + 2 * e]
    return _StubMetricDB({("CarX", "TrackX"): {"C01": metrics}})


def _component_at(multiple: float) -> float:
    component = _consistency_component(
        _driver_at(multiple), "owner", [("CarX", "TrackX")], "consistency", CONFIG,
    )
    assert component.value is not None
    return component.value


def test_golden_centres_cover_every_pooled_metric():
    assert set(_CENTRES) == set(_scoring_metric_names("consistency"))


def test_typical_driver_scores_midscale():
    # 1.0x = exactly the reference population's typical dispersion for
    # every metric. The map must call that mid-scale, not a floor or a
    # ceiling: expected value is the documented map at pooled = 1.0.
    ceiling = CONFIG.model.consistency_dispersion_ceiling
    value = _component_at(1.0)
    assert value == pytest.approx(1.0 - 1.0 / ceiling)
    assert 0.58 < value < 0.75


def test_consistent_driver_scores_high():
    assert _component_at(0.2) > 0.85


def test_sloppy_driver_scores_low():
    assert _component_at(2.5) < 0.30


def test_component_is_monotone_in_dispersion():
    values = [_component_at(m) for m in (0.2, 0.6, 1.0, 1.8, 2.5)]
    assert values == sorted(values, reverse=True)
    assert len(set(values)) == len(values)
