"""Regression pins for dm-v3 behaviours (SPEC.md A56, PR #54) that the
fix-verification suite does not already cover.

Deliberately NOT duplicated here (already pinned elsewhere):
- live-corpus-profile saturation, near-origin brake points, wrap-around
  samples, bimodal brake points, and the 0.0-bound trend gate
  (tests/test_scoring_saturation.py);
- per-metric normalization, two-level pooling, the all-zero skip, and
  the golden-driver calibration (tests/test_scoring.py,
  tests/test_scoring_calibration.py).

What this module pins instead:
- the `_scaled_mad` resolution floor for majority-tied samples;
- the per-unit fallback anchor when a metric has no per-metric anchor,
  and the no-anchor-at-all skip (philosophy #3: never normalize
  against a guess);
- `vehicle_management` staying off the 0.0 floor on a genuinely
  variable ABS profile (BUG-042's second half — the saturation suite
  pins the `consistency` component only);
- the version constants themselves, literally: the rest of the suite
  checks them self-consistently, so a silent revert of either string
  would pass every other test.

Not pinned, deliberately: the 100.0-bound mirror of the BUG-043 trend
gate, and the exact live-corpus beliefs (consistency 56.19 and company).
The mirror has no realistic path through `compute_belief` — a headline
of exactly 100.0 forces every bucket's pooled dispersion near zero, so
no bucket delta can clear `trend_delta_points` — and the corpus beliefs
need the owner's 282-lap corpus, which is not in this repo. The gate's
code is symmetric; only its reachable side is pinned.
"""

import copy

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.model.scoring import (
    SCORING_MODEL_VERSION,
    _consistency_component,
    _scaled_mad,
)
from driverdna.report.payload import PAYLOAD_VERSION

CONFIG = DriverDNAConfig()


class _StubMetricDB:
    """The stub pattern from test_scoring.py: `_consistency_component`
    only calls `self_metric_table`."""

    def __init__(self, tables):
        self._tables = tables

    def self_metric_table(self, *, driver, car, track, lap_pks=None):
        return self._tables.get((car, track), {})


# --- _scaled_mad resolution floor -------------------------------------------


def test_scaled_mad_resolution_floor_for_majority_tied_samples():
    # Four laps share the median exactly and one visibly differs: the
    # raw MAD is 0, but the sample is not perfectly repeatable. The
    # floor reports the finest dispersion the sample itself can
    # express — the smallest nonzero deviation, scaled by the same
    # constant — instead of claiming perfect repeatability.
    assert _scaled_mad([50.0, 50.0, 50.0, 50.0, 50.5]) == pytest.approx(1.4826 * 0.5)
    # A genuinely constant sample still reads exactly zero: the floor
    # only fires when the sample visibly varies.
    assert _scaled_mad([50.0, 50.0, 50.0, 50.0, 50.0]) == 0.0
    # Sanity on an ordinary sample: median 50.0, deviations
    # [0, 0.4, 0.4, 0.3, 0.3], MAD 0.3.
    assert _scaled_mad([50.0, 50.4, 49.6, 50.3, 49.7]) == pytest.approx(1.4826 * 0.3)


def test_majority_tied_sample_is_not_perfectly_repeatable_at_component_level():
    # Same shape one level up: without the floor this sample's
    # component would read exactly 1.0 (perfect). With it, the pooled
    # dispersion is the floored scaled MAD over the metric's anchor.
    values = [50.0, 50.0, 50.0, 50.0, 50.5]
    db = _StubMetricDB({
        ("CarX", "TrackX"): {"C01": {"turn_in_dist_pct": values}},
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "consistency", CONFIG,
    )
    assert component.value is not None
    assert component.value < 1.0
    anchor = CONFIG.model.consistency_metric_reference_dispersion["turn_in_dist_pct"]
    expected = 1.0 - (_scaled_mad(values) / anchor) / CONFIG.model.consistency_dispersion_ceiling
    assert component.value == pytest.approx(expected)


# --- anchor fallback, and the no-anchor skip ---------------------------------


def test_per_unit_fallback_anchor_used_when_metric_anchor_missing():
    # Brands Hatch C10's real brake points (BUG-044's sample): with the
    # metric's own anchor deleted, the component must fall back to the
    # '% lap' unit anchor — not skip the sample, and not guess.
    cfg = copy.deepcopy(CONFIG)
    del cfg.model.consistency_metric_reference_dispersion["brake_point_dist_pct"]
    values = [0.24, 0.24, 0.30, 0.76, 1.27]
    db = _StubMetricDB({
        ("CarX", "TrackX"): {"C01": {"brake_point_dist_pct": values}},
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "braking", cfg,
    )
    assert component.value is not None
    unit_anchor = cfg.model.consistency_unit_reference_dispersion["% lap"]
    expected = 1.0 - (_scaled_mad(values) / unit_anchor) / cfg.model.consistency_dispersion_ceiling
    assert component.value == pytest.approx(expected)


def test_sample_skipped_when_no_anchor_exists_at_any_level():
    # Same sample, but with both the metric anchor and its unit anchor
    # deleted: there is nothing honest to normalize against, so the
    # sample carries no component value rather than a guessed one
    # (philosophy #3).
    cfg = copy.deepcopy(CONFIG)
    del cfg.model.consistency_metric_reference_dispersion["brake_point_dist_pct"]
    del cfg.model.consistency_unit_reference_dispersion["% lap"]
    db = _StubMetricDB({
        ("CarX", "TrackX"): {"C01": {"brake_point_dist_pct": [0.24, 0.24, 0.30, 0.76, 1.27]}},
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "braking", cfg,
    )
    assert component.value is None


# --- vehicle_management: BUG-042's second half -------------------------------


def test_vehicle_management_does_not_saturate_on_variable_abs_profile():
    # Under dm-v2 the live corpus's vehicle_management pooled past the
    # same ceiling as consistency and clamped to exactly 0.0. A
    # genuinely variable ABS profile must read as imperfect, not as
    # the worst the scale can express.
    values = [0.1, 0.3, 0.5, 0.7, 0.9]
    db = _StubMetricDB({
        ("CarX", "TrackX"): {"C01": {"abs_active_ratio": values}},
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "vehicle_management", CONFIG,
    )
    assert component.value is not None
    assert 0.0 < component.value < 1.0
    anchor = CONFIG.model.consistency_metric_reference_dispersion["abs_active_ratio"]
    expected = 1.0 - (_scaled_mad(values) / anchor) / CONFIG.model.consistency_dispersion_ceiling
    assert component.value == pytest.approx(expected)


# --- version constants, literally --------------------------------------------


def test_scoring_model_version_is_dm_v3():
    # The rest of the suite threads SCORING_MODEL_VERSION through
    # self-consistently; only a literal pin catches a silent revert.
    assert SCORING_MODEL_VERSION == "dm-v3"


def test_payload_version_is_13():
    # v12 is the payload that carries trend_reason (A56),
    # speculative_guess (BUG-046), and the tendency era fields (A55).
    # Same reasoning: a literal pin, not a round-trip.
    assert PAYLOAD_VERSION == 13
