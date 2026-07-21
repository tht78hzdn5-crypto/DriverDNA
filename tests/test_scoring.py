"""M6b: dm-v1, the deterministic per-fundamental scoring model.

Two layers of tests: pure-function checks on the weight-redistribution rule
(no DB needed), and DB-backed checks that compute_belief behaves per
SPEC.md's Milestone 6 done-criteria — deterministic, honest about
insufficient evidence, and never scores a no_signal fundamental.
"""

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.scoring import (
    SCORING_MODEL_VERSION,
    _Component,
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

_VARIED_PEAKS = [0.4, 0.5, 0.6, 0.7, 0.8]
_FLAT_PEAKS = [0.8, 0.8, 0.8, 0.8, 0.8]


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
