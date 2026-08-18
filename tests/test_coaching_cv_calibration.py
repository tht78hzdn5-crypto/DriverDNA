"""A52: the consistency coaching path's thresholds, recalibrated to the
quantity they actually measure.

A42 (`coach-onto-v2`) changed `same_lap_twice`'s gate from a **raw**
coefficient of variation to a **per-unit normalized** one, and rewrote the
config descriptions to say so — but left every threshold at its raw-CV value.
The scale moved underneath them:

    0.0  perfectly repeatable
    1.0  exactly unit-typical      (dm-v2 scores this component 50)
    2.0  consistency_cv_ceiling    (dm-v2 scores it 0)

Against that scale the old numbers are nonsense in two places at once:

  * `consistency_cv_floor = 0.15` — its own description claims "15% above
    typical variability", but 0.15 on a scale where 1.0 IS typical means 85%
    *better* than typical. Every corner cleared it, so the gate filtered
    nothing.
  * `cv_band_major = 0.5` — a driver with exactly typical consistency banded
    "major" at twice the threshold. All 16 fixture corners banded "major", so
    the band carried no information at all.

The new values are anchored to the scale's own semantics, NOT fitted to the
fixture corpus: floor/moderate at 1.15 (the floor's own stated intent),
notable at 1.50 (midway from typical to the ceiling), major at 2.00 (the
ceiling, where dm-v2 already scores zero).
"""

import pytest

from driverdna.coaching.engine import _cv_band
from driverdna.config import DriverDNAConfig

CONFIG = DriverDNAConfig()
COACH = CONFIG.coaching


# --- the calibration, as a pure function of the band thresholds ------------


def test_exactly_unit_typical_consistency_is_not_major():
    """The regression that motivated A52. 1.0 is the scale's own definition
    of typical; banding it "major" told a perfectly average driver their
    repeatability was the worst thing about their driving."""
    assert _cv_band(1.0, COACH) != "major"


def test_a_driver_better_than_typical_does_not_band_at_all():
    assert _cv_band(0.85, COACH) == "negligible"


def test_the_ceiling_bands_major():
    """`consistency_cv_ceiling` is where dm-v2 already scores this component
    zero — the two layers should agree that this is as bad as it gets."""
    assert _cv_band(CONFIG.model.consistency_cv_ceiling, COACH) == "major"


def test_bands_are_ordered_and_sit_on_the_normalized_scale():
    assert 1.0 <= COACH.cv_band_moderate < COACH.cv_band_notable < COACH.cv_band_major
    assert COACH.cv_band_major == CONFIG.model.consistency_cv_ceiling


def test_gate_floor_matches_its_own_stated_intent():
    """The description says "15% above typical". On the normalized scale that
    is 1.15, not 0.15 — the exact off-by-a-scale A42 left behind."""
    assert COACH.consistency_cv_floor == pytest.approx(1.15)


def test_eligibility_floor_is_the_moderate_band():
    """Preserved from before A52: a CV candidate that exists is at least
    moderate. Changing that is a separate decision, not a side effect."""
    assert COACH.consistency_cv_floor == COACH.cv_band_moderate


def test_commitment_cv_floor_is_untouched_because_it_is_a_raw_cv():
    """`trust_the_proxy` gates on a SINGLE metric, so `_corner_candidate`
    takes the raw-CV path and never normalizes. Its 0.15 was always correct
    and must not be swept along by this recalibration."""
    assert COACH.commitment_cv_floor == pytest.approx(0.15)


# --- what it does to the real fixture corpus -------------------------------
# Values measured from tests/fixtures (n=16 corners): the observed normalized
# pooled CVs run 0.849 to 2.724 with a median of 1.307. Under the old bands
# all 16 were "major"; these assert the new spread is real. Deliberately a
# spread check, not pinned counts — the point is that the band discriminates.


@pytest.mark.parametrize("observed,expected", [
    (0.849, "negligible"),   # this driver's most repeatable corner
    (0.982, "negligible"),   # just better than unit-typical
    (1.131, "negligible"),   # above typical, below the "worth saying" floor
    (1.352, "moderate"),
    (1.428, "moderate"),
    (2.724, "major"),        # the genuine outlier, C02
])
def test_real_fixture_values_spread_across_bands(observed, expected):
    assert _cv_band(observed, COACH) == expected


def test_the_old_thresholds_would_have_called_every_one_of_these_major():
    """Pins the defect itself, so a future edit that quietly reverts the
    scale fails here with the reason attached."""
    old = DriverDNAConfig().coaching.model_copy(
        update={"cv_band_moderate": 0.15, "cv_band_notable": 0.30, "cv_band_major": 0.50},
    )
    observed = [0.849, 0.898, 0.946, 0.959, 0.982, 1.131, 1.236, 1.263,
                1.352, 1.361, 1.369, 1.386, 1.395, 1.400, 1.428, 2.724]
    assert {_cv_band(v, old) for v in observed} == {"major"}
    assert len({_cv_band(v, COACH) for v in observed}) > 1


def test_driver_model_scoring_cannot_be_moved_by_coaching_thresholds():
    """dm-v2 reads config.model.* only; the coaching gate is
    config.coaching.*. A52 must not move a single Driver Model score, and
    this is the structural reason it cannot."""
    import inspect

    from driverdna.model import scoring

    source = inspect.getsource(scoring)
    assert "config.coaching" not in source
    assert "cfg.coaching" not in source
