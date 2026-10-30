"""A58: the consistency coaching path's thresholds, recalibrated to the
statistic they actually measure — again.

A52 recalibrated the CV thresholds to the normalized-CV scale (1.0 =
unit-typical, 2.0 = ceiling). A58 replaces the statistic itself: the
coaching gates now read dm-v3's normalized scaled-MAD dispersion, so
the CV scale and its thresholds no longer govern any gate. The scale
semantics carry over unchanged — 1.0 is still exactly typical — which
is why the numbers look familiar:

    0.0  perfectly repeatable
    1.0  exactly reference-typical (the A56 anchor)
    1.15 floor / moderate ("15% above typical", the A52 stated intent)
    1.50 notable (midway from typical toward the old ceiling's neighborhood)
    2.00 major

This file replaces tests/test_coaching_cv_calibration.py, whose tests
pinned the CV scale. Each superseded test is named in the PR description;
the one structural test that survives (scoring cannot be moved by
coaching thresholds) is kept verbatim below, because it constrains the
new gates exactly as it constrained the old ones.

The old CV fields (`consistency_cv_floor`, `commitment_cv_floor`,
`cv_band_*`) are retained in config for stored-TOML compatibility
(`extra="forbid"` would refuse an old file that still names them) but no
gate reads them; their descriptions say so.
"""

import pytest

from driverdna.coaching.engine import _dispersion_band
from driverdna.config import DriverDNAConfig

CONFIG = DriverDNAConfig()
COACH = CONFIG.coaching


# --- the calibration, as a pure function of the band thresholds ------------


def test_exactly_typical_dispersion_is_not_major():
    """The regression that motivated A52, restated for the new statistic.
    1.0 is the scale's own definition of typical; banding it "major"
    told a perfectly average driver their repeatability was the worst
    thing about their driving."""
    assert _dispersion_band(1.0, COACH) != "major"


def test_a_driver_better_than_typical_does_not_band_at_all():
    assert _dispersion_band(0.85, COACH) == "negligible"


def test_bands_are_ordered_and_sit_on_the_normalized_scale():
    assert 1.0 <= COACH.dispersion_band_moderate < COACH.dispersion_band_notable
    assert COACH.dispersion_band_notable < COACH.dispersion_band_major


def test_gate_floor_matches_its_own_stated_intent():
    """The description says "15% above typical". On the normalized
    dispersion scale that is 1.15."""
    assert COACH.consistency_dispersion_floor == pytest.approx(1.15)


def test_eligibility_floor_is_the_moderate_band():
    """Preserved from before A58: a dispersion candidate that exists is
    at least moderate. Changing that is a separate decision, not a side
    effect."""
    assert COACH.consistency_dispersion_floor == COACH.dispersion_band_moderate


def test_commitment_dispersion_floor_matches_its_stated_intent():
    """`trust_the_proxy` gates on a SINGLE metric's normalized scaled
    MAD; 1.15 is the same "15% above typical" reading as the pooled
    floor, on the brake-point anchor (0.41386 % lap, A56)."""
    assert COACH.commitment_dispersion_floor == pytest.approx(1.15)


def test_driver_model_scoring_cannot_be_moved_by_coaching_thresholds():
    """dm-v3 reads config.model.* only; the coaching gates are
    config.coaching.* (plus a read of the model anchors, which moves no
    score). A58 must not move a single Driver Model score, and this is
    the structural reason it cannot. Kept verbatim from the superseded
    CV calibration file."""
    import inspect

    from driverdna.model import scoring

    source = inspect.getsource(scoring)
    assert "config.coaching" not in source
    assert "cfg.coaching" not in source
