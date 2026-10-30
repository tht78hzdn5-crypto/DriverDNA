"""BUG-044 coaching migration (SPEC.md A58): the coaching gates read the
dm-v3 absolute-robust statistic — per-metric scaled MAD normalized by the
measured reference dispersions — instead of dm-v2 normalized CVs.

These are the gate-level mirrors of the scorer-level shapes pinned in
tests/test_scoring_saturation.py, using the same real values from
docs/BUG-LOG.md BUG-044:

- near-origin landmark: Brands Hatch C10 brake points [0.24, 0.24, 0.30,
  0.76, 1.27] — CV read ~110x normalized; scaled MAD reads ~0.21x.
- wrap-around sample: Silverstone C18 apex positions [99.0, 98.4, 0.013,
  93.9] — CV read ~95x normalized; scaled MAD reads ~8.6x (loose, truly,
  but bounded).
- bimodal brake points: Brands Hatch C01 [0.81, 9.27, 1.13, 1.52, 10.92]
  — CV read ~143x normalized regardless of cluster tightness; scaled MAD
  reads ~2.5x (poor, honestly measured, not absurd).

The gate statistic is `_normalized_pooled_dispersion` in
coaching/engine.py: two-level pooling (mean within each unit, then mean
across units) over per-metric normalized scaled MADs, reusing dm-v3's
`_scaled_mad` and `config.model.consistency_metric_reference_dispersion`
(the A56 anchors, verified against the 851-lap owner corpus in the A58
amendment). Skip rules mirror scoring: fewer than 2 values, all-zero
samples (the measured event never occurred), and metrics with no anchor
are skipped rather than normalized against a guess.
"""

import pytest

from driverdna.coaching.engine import (
    _dispersion_band,
    _normalized_pooled_dispersion,
)
from driverdna.config import DriverDNAConfig

CONFIG = DriverDNAConfig()
COACH = CONFIG.coaching
METRIC_REF = CONFIG.model.consistency_metric_reference_dispersion
UNIT_REF = CONFIG.model.consistency_unit_reference_dispersion

# --- the three BUG-044 shapes, at gate level -------------------------------


def test_near_origin_brake_point_is_not_a_dispersion_explosion():
    # Scaled MAD 0.089 points against the 0.414-point anchor -> ~0.21,
    # a repeatable landmark. Under the old CV gate this corner's pooled
    # value read ~110x and banded major; under dispersion it sits below
    # the 1.15 floor, so the gate does not fire at all.
    table = {"C10": {"brake_point_dist_pct": [0.24, 0.24, 0.30, 0.76, 1.27]}}
    value = _normalized_pooled_dispersion(
        table, "C10", ("brake_point_dist_pct",), METRIC_REF, UNIT_REF)
    assert value is not None
    assert value == pytest.approx(0.215, abs=0.01)
    assert value < COACH.commitment_dispersion_floor


def test_wrap_around_sample_is_bounded_not_manufactured():
    # Median 96.15; deviations [2.85, 2.25, 96.137, 2.25]; median
    # deviation 2.55 -> scaled MAD 3.78 -> ~8.6x the apex anchor. The
    # corner's apex placement genuinely is loose, so the value must stay
    # above the floor — but bounded, unlike the old ~95x CV reading.
    table = {"C18": {"apex_dist_pct": [99.0, 98.4, 0.013, 93.9]}}
    value = _normalized_pooled_dispersion(
        table, "C18", ("apex_dist_pct",), METRIC_REF, UNIT_REF)
    assert value is not None
    assert value == pytest.approx(8.55, abs=0.1)
    assert value < 20.0  # bounded: one sample cannot manufacture ~95x


def test_bimodal_brake_points_read_as_poor_not_absurd():
    # Median 1.52; deviations [0.71, 7.75, 0.39, 0, 9.40]; median
    # deviation 0.71 -> scaled MAD 1.05 -> ~2.5x the anchor. Poor
    # repeatability, honestly measured: above the floor (the gate fires)
    # and nowhere near the old ~143x CV reading.
    table = {"C01": {"brake_point_dist_pct": [0.81, 9.27, 1.13, 1.52, 10.92]}}
    value = _normalized_pooled_dispersion(
        table, "C01", ("brake_point_dist_pct",), METRIC_REF, UNIT_REF)
    assert value is not None
    assert value == pytest.approx(2.54, abs=0.05)
    assert value >= COACH.commitment_dispersion_floor
    assert value < 10.0


# --- pooling structure (mirrors the old per-unit CV test, new statistic) ---


def test_pooled_dispersion_is_per_unit_normalized_not_flat_mean():
    """Five '% lap' metrics perfectly consistent (scaled MAD = 0) + one
    'count' metric at typical scale. A flat mean gives ~1.235/6 = 0.206.
    Per-unit normalization gives (0.0 + 1.235) / 2 = 0.617 — the same
    two-level logic dm-v2's pooling had, over the new statistic."""
    table = {
        "C01": {
            "brake_point_dist_pct": [10.0] * 8,
            "turn_in_dist_pct": [10.0] * 8,
            "apex_dist_pct": [10.0] * 8,
            "throttle_pickup_dist_pct": [10.0] * 8,
            "full_throttle_dist_pct": [10.0] * 8,
            "steering_corrections": [0.148, 3.852] * 4,
        },
    }
    metric_names = (
        "brake_point_dist_pct", "turn_in_dist_pct", "apex_dist_pct",
        "throttle_pickup_dist_pct", "full_throttle_dist_pct", "steering_corrections",
    )
    result = _normalized_pooled_dispersion(
        table, "C01", metric_names, METRIC_REF, UNIT_REF)
    assert result is not None
    assert 0.5 < result < 0.7, f"expected per-unit normalized ≈ 0.617, got {result}"
    flat = 1.235 / 6
    assert abs(result - flat) > 0.2, (
        f"per-unit result {result:.3f} is too close to flat mean {flat:.3f}; "
        "normalization is not being applied"
    )


# --- skip rules and the resolution floor -----------------------------------


def test_all_zero_sample_carries_no_dispersion_evidence():
    # ABS never active: the repeatability of an event that never
    # happened is not measurable (scoring's stated grounds, reused).
    table = {"C01": {"abs_active_ratio": [0.0, 0.0, 0.0, 0.0]}}
    assert _normalized_pooled_dispersion(
        table, "C01", ("abs_active_ratio",), METRIC_REF, UNIT_REF) is None


def test_single_value_sample_is_skipped():
    table = {"C01": {"brake_peak": [0.8]}}
    assert _normalized_pooled_dispersion(
        table, "C01", ("brake_peak",), METRIC_REF, UNIT_REF) is None


def test_metric_without_anchor_is_skipped_not_guessed():
    table = {"C01": {"brake_peak": [0.5, 0.6, 0.7, 0.8]}}
    assert _normalized_pooled_dispersion(
        table, "C01", ("brake_peak",), {}, {}) is None


def test_resolution_floor_for_majority_tied_samples():
    # MAD is exactly 0 but the sample visibly varies (three laps share
    # the median exactly): the dispersion is the sample's smallest
    # nonzero absolute deviation, scaled — here 1.0 * 1.4826, which
    # normalizes to exactly 1.0 against throttle_modulation_count's
    # own 1.4826 anchor. Reporting 0 would claim perfect repeatability
    # for a sample that varies.
    table = {"C01": {"throttle_modulation_count": [2.0, 2.0, 2.0, 3.0]}}
    value = _normalized_pooled_dispersion(
        table, "C01", ("throttle_modulation_count",), METRIC_REF, UNIT_REF)
    assert value is not None
    assert value == pytest.approx(1.0)


def test_constant_sample_normalizes_to_exactly_zero():
    # A sample that never varies is perfectly repeatable, not missing
    # evidence: it contributes 0, pulling the pool toward repeatable.
    table = {"C01": {"brake_peak": [0.8, 0.8, 0.8, 0.8]}}
    value = _normalized_pooled_dispersion(
        table, "C01", ("brake_peak",), METRIC_REF, UNIT_REF)
    assert value is not None
    assert value == pytest.approx(0.0)


# --- banding on the new scale ----------------------------------------------


def test_exactly_unit_typical_dispersion_is_not_major():
    """1.0 is the scale's own definition of typical; banding it "major"
    would tell a perfectly average driver their repeatability was the
    worst thing about their driving (the A52 regression shape, new
    statistic)."""
    assert _dispersion_band(1.0, COACH) != "major"


def test_a_driver_better_than_typical_does_not_band_at_all():
    assert _dispersion_band(0.85, COACH) == "negligible"


def test_bands_are_ordered_and_sit_on_the_normalized_scale():
    assert 1.0 <= COACH.dispersion_band_moderate < COACH.dispersion_band_notable
    assert COACH.dispersion_band_notable < COACH.dispersion_band_major


def test_gate_floor_matches_its_own_stated_intent():
    """The description says "15% above typical". On the normalized
    dispersion scale that is 1.15 — the same stated intent A52 fixed
    for the CV scale, carried onto the new statistic."""
    assert COACH.consistency_dispersion_floor == pytest.approx(1.15)


def test_eligibility_floor_is_the_moderate_band():
    """Preserved from before: a dispersion candidate that exists is at
    least moderate. Changing that is a separate decision, not a side
    effect."""
    assert COACH.consistency_dispersion_floor == COACH.dispersion_band_moderate


@pytest.mark.parametrize("observed,expected", [
    (0.85, "negligible"),   # better than typical
    (1.0, "negligible"),    # exactly typical
    (1.15, "moderate"),     # the floor itself
    (1.35, "moderate"),
    (1.50, "notable"),
    (1.90, "notable"),
    (2.00, "major"),        # the major band
    (2.54, "major"),        # the bimodal brake-point reading
])
def test_dispersion_values_band_as_expected(observed, expected):
    assert _dispersion_band(observed, COACH) == expected


# --- the scale itself is the anchor, not the fixture corpus ----------------

def test_bands_do_not_depend_on_fixture_values():
    """The band thresholds are scale semantics (1.0 = typical), not
    fitted to any corpus: moving the fixture corpus must not move them.
    A52's old-thresholds regression, restated for the new scale."""
    assert COACH.dispersion_band_moderate == pytest.approx(1.15)
    assert COACH.dispersion_band_notable == pytest.approx(1.50)
    assert COACH.dispersion_band_major == pytest.approx(2.00)
