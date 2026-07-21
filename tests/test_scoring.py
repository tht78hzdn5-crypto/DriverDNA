"""M6b: dm-v1, the deterministic per-fundamental scoring model.

Two layers of tests: pure-function checks on the weight-redistribution rule
(no DB needed), and DB-backed checks that compute_belief behaves per
SPEC.md's Milestone 6 done-criteria — deterministic, honest about
insufficient evidence, and never scores a no_signal fundamental.
"""

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.scoring import (
    SCORING_MODEL_VERSION,
    _Component,
    _consistency_component,
    _weighted_score,
    compute_all_beliefs,
    compute_belief,
    store_all_beliefs,
)
from driverdna.model.taxonomy import TAXONOMY_VERSION, FUNDAMENTALS, SignalStatus
from synth import one_corner_lap, ramp, track_lap
from synth import run_synthetic_lap as _run

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def run_synthetic_lap(db, lap, **kw):
    kw.setdefault("driver", COHORT["driver"])
    kw.setdefault("car", COHORT["car"])
    kw.setdefault("track", COHORT["track"])
    kw.setdefault("config", CONFIG)
    return _run(db, lap, **kw)


# --- _weighted_score: the redistribution rule, as a pure function ----------


def test_weighted_score_all_three_available():
    components = {
        "adherence": _Component(0.8, 10),
        "opportunity": _Component(0.6, 10),
        "consistency": _Component(0.4, 10),
    }
    score = _weighted_score(components, CONFIG)
    expected = (
        0.8 * CONFIG.model.weight_adherence
        + 0.6 * CONFIG.model.weight_opportunity
        + 0.4 * CONFIG.model.weight_consistency
    ) * 100.0
    assert score == pytest.approx(expected)


def test_weighted_score_redistributes_missing_component():
    # opportunity absent (e.g. a fundamental with no mapped phases): its
    # weight must be redistributed across adherence + consistency, not
    # silently dropped (which would understate every score by the missing
    # component's weight).
    components = {
        "adherence": _Component(1.0, 10),
        "opportunity": _Component(None, 0),
        "consistency": _Component(0.0, 10),
    }
    score = _weighted_score(components, CONFIG)
    w_a, w_c = CONFIG.model.weight_adherence, CONFIG.model.weight_consistency
    expected = (1.0 * w_a + 0.0 * w_c) / (w_a + w_c) * 100.0
    assert score == pytest.approx(expected)


def test_weighted_score_single_available_component_takes_it_whole():
    components = {
        "adherence": _Component(None, 0),
        "opportunity": _Component(None, 0),
        "consistency": _Component(0.73, 10),
    }
    assert _weighted_score(components, CONFIG) == pytest.approx(73.0)


def test_weighted_score_none_available_returns_none():
    components = {
        "adherence": _Component(None, 0),
        "opportunity": _Component(None, 0),
        "consistency": _Component(None, 0),
    }
    assert _weighted_score(components, CONFIG) is None


# --- _consistency_component: dm-v2 per-unit normalization ------------------
#
# Real fixtures exposed the actual mechanism (2026-07-21): "% lap" landmark
# metrics have a naturally tiny raw CV (~0.007) while small-integer "count"
# metrics have a naturally huge one (~0.99+), for equally repeatable driving.
# dm-v1 pooled raw CVs with a flat mean, so whichever metrics happened to be
# high-CV *by unit* dominated the pooled signal regardless of the driver's
# actual consistency. These tests stub `self_metric_table` directly (the
# only Database method _consistency_component calls) so the normalization
# math is exercised in isolation, without a full synthetic-lap pipeline.


class _StubMetricDB:
    def __init__(self, tables: dict[tuple[str, str], dict]):
        self._tables = tables

    def self_metric_table(self, *, driver, car, track, lap_pks=None):
        return self._tables.get((car, track), {})


def _cv(values: list[float]) -> float:
    arr = np.asarray(values, dtype=float)
    return float(np.std(arr, ddof=1) / abs(np.mean(arr)))


def test_consistency_per_unit_normalization_prevents_high_cv_unit_from_dominating():
    # turn_in_dist_pct ("% lap") near its own reference scale; steering_
    # corrections ("count") near ITS reference scale - both roughly
    # "typical" for their own unit, but ~115x apart in raw CV.
    pct_values = [50.0, 50.4, 49.6, 50.3, 49.7]
    count_values = [0.0, 1.0, 2.0, 1.0, 3.0]
    assert _cv(count_values) > 100 * _cv(pct_values)  # the real scale mismatch

    db = _StubMetricDB({
        ("CarX", "TrackX"): {
            "C01": {
                "turn_in_dist_pct": pct_values,
                "steering_corrections": count_values,
            },
        },
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "consistency", CONFIG,
    )
    assert component.value is not None
    # Both metrics sit near their own reference (normalized ~1.0), so the
    # pooled score should land near the "typical" midpoint (ceiling=2.0 ->
    # normalized 1.0 scores 50) - not crushed toward 0 by the count metric's
    # much larger raw number, and not pulled toward 100 by the pct metric's
    # much smaller one.
    assert 0.30 < component.value < 0.70

    # Matches the documented formula exactly: per-metric CV / that metric's
    # own unit reference, meaned within unit then across units.
    ref = CONFIG.model.consistency_unit_reference_cv
    expected_pooled = (
        _cv(pct_values) / ref["% lap"] + _cv(count_values) / ref["count"]
    ) / 2
    expected = max(0.0, min(1.0, 1.0 - expected_pooled / CONFIG.model.consistency_cv_ceiling))
    assert component.value == pytest.approx(expected)


def test_consistency_unit_with_many_samples_does_not_outweigh_a_thin_one():
    # "% lap" here contributes 4 corners' worth of samples (all genuinely
    # inconsistent, real raw CV far above reference) against a single
    # "count" sample near ITS OWN reference. A flat mean over every
    # (corner, metric) sample would let the numerous "% lap" samples
    # swamp the lone "count" one; per-unit-then-across-unit pooling keeps
    # them at equal, one-vote-per-unit weight instead.
    noisy_pct = [10.0, 14.0, 8.0, 16.0, 9.0]  # real spread, well above reference
    typical_count = [0.0, 1.0, 2.0, 1.0, 3.0]

    db = _StubMetricDB({
        ("CarX", "TrackX"): {
            "C01": {"turn_in_dist_pct": noisy_pct},
            "C02": {"brake_point_dist_pct": noisy_pct},
            "C03": {"apex_dist_pct": noisy_pct},
            "C04": {"throttle_pickup_dist_pct": noisy_pct, "steering_corrections": typical_count},
        },
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "consistency", CONFIG,
    )
    ref = CONFIG.model.consistency_unit_reference_cv
    pct_norm = _cv(noisy_pct) / ref["% lap"]
    count_norm = _cv(typical_count) / ref["count"]
    expected_pooled = (pct_norm + count_norm) / 2  # one vote per unit, not per sample
    expected = max(0.0, min(1.0, 1.0 - expected_pooled / CONFIG.model.consistency_cv_ceiling))
    assert component.value == pytest.approx(expected)
    # A flat per-sample mean (4 noisy "% lap" samples vs. 1 "count" sample)
    # would have pulled the pool much closer to the noisy pct signal alone -
    # confirm the per-unit result differs from that flat alternative.
    flat_mean = (pct_norm * 4 + count_norm) / 5
    assert not (expected_pooled == pytest.approx(flat_mean))


# --- no_signal fundamentals never reach the component math -----------------


def test_no_signal_fundamental_never_scores(db):
    belief = compute_belief(db, driver="owner", fundamental_id="vision", config=CONFIG)
    assert belief.signal_status is SignalStatus.NO_SIGNAL
    assert belief.score is None
    assert belief.confidence == 0.0
    assert belief.evidence_count == 0
    assert belief.trend == "unavailable"
    assert belief.insufficient_reason and "no telemetry channel" in belief.insufficient_reason
    assert belief.scoring_model_version == SCORING_MODEL_VERSION
    assert belief.taxonomy_version == TAXONOMY_VERSION


def test_no_signal_fundamental_never_scores_even_with_unrelated_data(db):
    # Loading the DB with plenty of (unrelated) evidence must not change
    # vision's answer - there is no code path from other fundamentals'
    # evidence into an unmeasurable one.
    for i in range(6):
        run_synthetic_lap(db, track_lap(src=f"lap{i}.csv"), session_key=f"s{i % 2}")
    belief = compute_belief(db, driver="owner", fundamental_id="vision", config=CONFIG)
    assert belief.score is None and belief.signal_status is SignalStatus.NO_SIGNAL


# --- insufficient evidence: honest, not a guess -----------------------------


def test_insufficient_evidence_below_floor(db):
    for i in range(2):  # well under min_evidence_for_score (5)
        run_synthetic_lap(db, track_lap(src=f"lap{i}.csv"))
    belief = compute_belief(db, driver="owner", fundamental_id="rotation", config=CONFIG)
    assert belief.score is None
    assert belief.confidence == 0.0
    assert "insufficient evidence" in belief.insufficient_reason
    assert str(CONFIG.model.min_evidence_for_score) in belief.insufficient_reason


def test_insufficient_evidence_with_no_laps_at_all(db):
    belief = compute_belief(db, driver="nobody", fundamental_id="braking", config=CONFIG)
    assert belief.score is None and belief.evidence_count == 0


# --- real evidence: a scored, deterministic belief --------------------------


def _rotation_cohort(db, n=12):
    for i in range(n):
        run_synthetic_lap(db, track_lap(src=f"lap{i}.csv"), session_key=f"s{i % 2}")


def test_rotation_scores_with_real_evidence(db):
    _rotation_cohort(db)
    belief = compute_belief(db, driver="owner", fundamental_id="rotation", config=CONFIG)
    assert belief.signal_status is SignalStatus.MEASURED
    assert belief.insufficient_reason is None
    assert 0.0 <= belief.score <= 100.0
    assert 0.0 < belief.confidence <= 1.0
    assert belief.evidence_count > 0
    assert belief.trend == "unavailable"


def test_compute_belief_is_deterministic(db):
    _rotation_cohort(db)
    b1 = compute_belief(db, driver="owner", fundamental_id="rotation", config=CONFIG)
    b2 = compute_belief(db, driver="owner", fundamental_id="rotation", config=CONFIG)
    assert b1 == b2


def test_compute_all_beliefs_covers_every_fundamental(db):
    _rotation_cohort(db)
    beliefs = compute_all_beliefs(db, driver="owner", config=CONFIG)
    assert set(beliefs) == set(FUNDAMENTALS)
    for fid, belief in beliefs.items():
        assert belief.fundamental == fid
        assert belief.trend == "unavailable"
        assert (belief.score is None) or (0.0 <= belief.score <= 100.0)


# --- vehicle_management: real metric, but zero variation is honestly
#     "insufficient", not a fabricated perfect score -------------------------


def test_vehicle_management_insufficient_when_abs_never_varies(db):
    # abs_active_ratio only gets computed when a corner actually has braking
    # (metrics/technique.py) - one_corner_lap brakes, so the metric IS
    # recorded, but abs_active is never set to true anywhere in synth
    # fixtures, so every value is the real (not missing) number 0.0. A
    # constant-zero metric yields no usable coefficient of variation
    # (mean == 0) - the only component vehicle_management has (no
    # detectors, no phases). The score must come back "insufficient",
    # never a fabricated 100% or 0%.
    _braking_cohort(db)
    belief = compute_belief(db, driver="owner", fundamental_id="vehicle_management", config=CONFIG)
    assert belief.signal_status is SignalStatus.PROXY
    assert belief.evidence_count > 0
    assert belief.score is None
    assert "insufficient evidence" in belief.insufficient_reason


# --- braking / commitment: full three-component (or proxy-capped) path -----


def _braking_cohort(db, n=6):
    for i in range(n):
        lap = one_corner_lap()
        lap.source_path = lap.source_path.with_name(f"brake{i}.csv")
        shift = i * 4
        lap.brake[:] = 0.0
        ramp(lap.brake, 600 + shift, 630 + shift, 0.0, 0.8)
        lap.brake[630 + shift:690 + shift] = 0.8
        ramp(lap.brake, 690 + shift, 720 + shift, 0.8, 0.0)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")


def test_braking_full_three_component_score(db):
    _braking_cohort(db)
    belief = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    assert belief.signal_status is SignalStatus.MEASURED
    assert belief.insufficient_reason is None
    assert 0.0 <= belief.score <= 100.0
    assert 0.0 < belief.confidence <= 1.0


def test_commitment_confidence_is_capped_as_proxy(db):
    _braking_cohort(db)
    belief = compute_belief(db, driver="owner", fundamental_id="commitment", config=CONFIG)
    assert belief.signal_status is SignalStatus.PROXY
    if belief.score is not None:  # real signal exists (brake_point_dist_pct)
        assert belief.confidence <= CONFIG.model.proxy_confidence_cap + 1e-9


# --- store_all_beliefs: the persistence round trip --------------------------


def test_store_all_beliefs_persists_every_fundamental(db):
    _rotation_cohort(db)
    computed = store_all_beliefs(db, driver="owner", config=CONFIG)
    loaded = db.load_beliefs(driver="owner", scoring_model_version=SCORING_MODEL_VERSION)
    assert set(loaded) == set(FUNDAMENTALS) == set(computed)
    assert loaded["vision"]["score"] is None
    assert loaded["vision"]["signal_status"] == "no_signal"
    assert loaded["rotation"]["score"] == computed["rotation"].score
    assert loaded["rotation"]["evidence_count"] == computed["rotation"].evidence_count


# --- trend: direction of the score across dated earlier/recent buckets ------
#
# Lever: brake-peak spread within a bucket drives its consistency (and
# bucket-relative opportunity) score. A varied bucket scores lower than a
# flat (repeatable) one, so varied->flat reads "improving" and flat->varied
# "declining". Each lap gets a unique vert_accel marker (read by no
# metric/detector) so identical-shaped laps are still distinct telemetry and
# don't collapse under content-dedup — real laps never are identical.
#
# Peaks span a wide 0.1-0.9 range (dm-v2, 2026-07-21): only brake_peak and
# brake_application_rate respond to a varied peak height directly (timing
# landmarks like brake_point_dist_pct don't move), and dm-v2's per-unit
# pooling (model/scoring.py) gives each metric's *unit* equal weight rather
# than each raw sample — so the signal needs to be unmistakable within its
# own two units to clear trend_delta_points, the same bar a real, clearly
# inconsistent driver would clear.

_VARIED_PEAKS = [0.1, 0.3, 0.5, 0.7, 0.9]
_FLAT_PEAKS = [0.9, 0.9, 0.9, 0.9, 0.9]


def _brake_peak_lap(i, peak):
    lap = one_corner_lap()
    lap.source_path = lap.source_path.with_name(f"bp{i}.csv")
    lap.vert_accel[:] = 9.8 + i * 1e-6
    lap.brake[:] = 0.0
    ramp(lap.brake, 600, 630, 0.0, peak)
    lap.brake[630:690] = peak
    ramp(lap.brake, 690, 720, peak, 0.0)
    return lap


def _dated_brake_cohort(db, peaks, *, dated=True):
    for i, peak in enumerate(peaks):
        # 2026-01-01, -02, ... — increasing so import order is date order.
        date = f"2026-01-{i + 1:02d}" if dated else None
        run_synthetic_lap(
            db, _brake_peak_lap(i, peak), session_key=f"s{i % 2}", lap_date=date
        )


def test_trend_improving_when_recent_laps_are_more_repeatable(db):
    _dated_brake_cohort(db, _VARIED_PEAKS + _FLAT_PEAKS)  # earlier varied, recent flat
    belief = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    assert belief.trend == "improving"


def test_trend_declining_when_recent_laps_are_less_repeatable(db):
    _dated_brake_cohort(db, _FLAT_PEAKS + _VARIED_PEAKS)  # earlier flat, recent varied
    belief = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    assert belief.trend == "declining"


def test_trend_stable_when_both_buckets_match(db):
    _dated_brake_cohort(db, _FLAT_PEAKS + _FLAT_PEAKS)
    belief = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    assert belief.trend == "stable"


def test_trend_unavailable_without_dates(db):
    # Same evidence, no lap_date — the honest gap that today's undated
    # fixtures (and manual import) still hit.
    _dated_brake_cohort(db, _VARIED_PEAKS + _FLAT_PEAKS, dated=False)
    belief = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    assert belief.score is not None  # the belief itself still scores
    assert belief.trend == "unavailable"


def test_trend_unavailable_below_min_dated_laps(db):
    # 6 dated laps: enough to score (>= min_evidence_for_score) but under
    # 2 x trend_min_laps_per_bucket, so no direction is claimed.
    assert 6 < 2 * CONFIG.model.trend_min_laps_per_bucket + 2
    _dated_brake_cohort(db, [0.4, 0.5, 0.6, 0.7, 0.8, 0.8])
    belief = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    assert belief.score is not None
    assert belief.trend == "unavailable"


def test_trend_ignores_undated_laps_in_bucketing(db):
    # Undated laps never enter the timeline: 6 dated (< gate) + 6 undated
    # still yields "unavailable", not a direction fabricated from the
    # undated ones.
    _dated_brake_cohort(db, [0.4, 0.5, 0.6, 0.7, 0.8, 0.8])
    for i, peak in enumerate(_FLAT_PEAKS):
        run_synthetic_lap(
            db, _brake_peak_lap(100 + i, peak), session_key=f"u{i}", lap_date=None
        )
    belief = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    assert belief.trend == "unavailable"


def test_trend_is_deterministic(db):
    _dated_brake_cohort(db, _VARIED_PEAKS + _FLAT_PEAKS)
    b1 = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    b2 = compute_belief(db, driver="owner", fundamental_id="braking", config=CONFIG)
    assert b1 == b2 and b1.trend == "improving"
