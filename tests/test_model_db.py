"""M6a: the belief store and its evidence-counting queries.

store_belief/load_beliefs are exercised directly against the schema;
driver_session_count / fundamental_evidence_lap_count / driver_dated_lap_count
are exercised against the real pipeline (synth.run_synthetic_lap) so the SQL
is checked against actual corner_observations/metric_values/detector_results
rows, not a hand-built stand-in for them.
"""

from pathlib import Path

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from synth import track_lap, run_synthetic_lap

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def _belief(**overrides):
    base = dict(
        driver="owner",
        fundamental="braking",
        signal_status="measured",
        score=72.5,
        confidence=0.6,
        evidence_count=14,
        trend="unavailable",
        insufficient_reason=None,
        scoring_model_version="dm-v1",
        taxonomy_version="pyramid-v1",
    )
    base.update(overrides)
    return base


def test_store_belief_round_trip_and_load_beliefs(db):
    db.store_belief(**_belief())
    db.store_belief(**_belief(fundamental="rotation", score=55.0, evidence_count=9))

    loaded = db.load_beliefs(driver="owner", scoring_model_version="dm-v1")

    assert set(loaded) == {"braking", "rotation"}
    assert loaded["braking"]["score"] == 72.5
    assert loaded["braking"]["confidence"] == 0.6
    assert loaded["braking"]["evidence_count"] == 14
    assert loaded["rotation"]["score"] == 55.0


def test_load_beliefs_scoped_to_driver_and_version(db):
    db.store_belief(**_belief(driver="owner", scoring_model_version="dm-v1"))
    db.store_belief(**_belief(driver="other-driver", scoring_model_version="dm-v1"))
    db.store_belief(**_belief(driver="owner", scoring_model_version="dm-v2", score=80.0))

    assert set(db.load_beliefs(driver="owner", scoring_model_version="dm-v1")) == {"braking"}
    assert set(db.load_beliefs(driver="other-driver", scoring_model_version="dm-v1")) == {"braking"}
    assert db.load_beliefs(driver="owner", scoring_model_version="dm-v1")["braking"]["score"] == 72.5
    assert db.load_beliefs(driver="owner", scoring_model_version="dm-v2")["braking"]["score"] == 80.0


def test_store_belief_upsert_replaces_prior_row_same_version(db):
    pk1 = db.store_belief(**_belief(score=72.5, evidence_count=14))
    pk2 = db.store_belief(**_belief(score=81.0, evidence_count=20, trend="improving"))

    assert pk1 == pk2  # same (driver, fundamental, version) -> same row
    n = db.conn.execute("SELECT COUNT(*) n FROM driver_beliefs").fetchone()["n"]
    assert n == 1
    loaded = db.load_beliefs(driver="owner", scoring_model_version="dm-v1")
    assert loaded["braking"]["score"] == 81.0
    assert loaded["braking"]["evidence_count"] == 20
    assert loaded["braking"]["trend"] == "improving"


def test_store_belief_version_bump_keeps_old_version_row(db):
    db.store_belief(**_belief(scoring_model_version="dm-v1", score=72.5))
    db.store_belief(**_belief(scoring_model_version="dm-v2", score=90.0))

    n = db.conn.execute("SELECT COUNT(*) n FROM driver_beliefs").fetchone()["n"]
    assert n == 2
    assert db.load_beliefs(driver="owner", scoring_model_version="dm-v1")["braking"]["score"] == 72.5
    assert db.load_beliefs(driver="owner", scoring_model_version="dm-v2")["braking"]["score"] == 90.0


def test_store_belief_no_signal_allows_null_score(db):
    db.store_belief(**_belief(
        fundamental="vision", signal_status="no_signal", score=None,
        confidence=0.0, evidence_count=0, insufficient_reason="no telemetry channel",
    ))
    loaded = db.load_beliefs(driver="owner", scoring_model_version="dm-v1")
    assert loaded["vision"]["score"] is None
    assert loaded["vision"]["insufficient_reason"] == "no telemetry channel"


def test_driver_session_count(db):
    run_synthetic_lap(db, track_lap(src="s1a.csv"), session_key="s1", config=CONFIG)
    run_synthetic_lap(db, track_lap(src="s1b.csv"), session_key="s1", config=CONFIG)
    run_synthetic_lap(db, track_lap(src="s2a.csv"), session_key="s2", config=CONFIG)
    # No session_key at all -> not counted.
    run_synthetic_lap(db, track_lap(src="nosession.csv"), config=CONFIG)
    # Reference-role lap, same driver name would collide by role filter, not driver.
    run_synthetic_lap(
        db, track_lap(src="ref.csv"), driver="owner", role="reference",
        session_key="s3", config=CONFIG,
    )

    assert db.driver_session_count("owner") == 2
    assert db.driver_session_count("nobody") == 0


def test_fundamental_evidence_lap_count_counts_distinct_laps_with_real_metric(db):
    run_synthetic_lap(db, track_lap(src="a.csv"), config=CONFIG)
    run_synthetic_lap(db, track_lap(src="b.csv"), config=CONFIG)

    n = db.fundamental_evidence_lap_count(
        driver="owner", metric_names=("min_speed_kmh",), detector_names=(),
    )
    assert n == 2


def test_fundamental_evidence_lap_count_empty_names_returns_zero(db):
    run_synthetic_lap(db, track_lap(src="a.csv"), config=CONFIG)
    assert db.fundamental_evidence_lap_count(
        driver="owner", metric_names=(), detector_names=(),
    ) == 0


def test_fundamental_evidence_lap_count_excludes_reference_role(db):
    run_synthetic_lap(db, track_lap(src="self.csv"), driver="owner", role="self", config=CONFIG)
    run_synthetic_lap(db, track_lap(src="ref.csv"), driver="owner", role="reference", config=CONFIG)

    n = db.fundamental_evidence_lap_count(
        driver="owner", metric_names=("min_speed_kmh",), detector_names=(),
    )
    assert n == 1


def test_fundamental_evidence_lap_count_unknown_metric_returns_zero(db):
    run_synthetic_lap(db, track_lap(src="a.csv"), config=CONFIG)
    n = db.fundamental_evidence_lap_count(
        driver="owner", metric_names=("no_such_metric",), detector_names=(),
    )
    assert n == 0


def test_driver_dated_lap_count_zero_by_default(db):
    run_synthetic_lap(db, track_lap(src="a.csv"), config=CONFIG)
    run_synthetic_lap(db, track_lap(src="b.csv"), config=CONFIG)
    assert db.driver_dated_lap_count("owner") == 0


def test_driver_dated_lap_count_counts_only_dated_self_laps_for_driver(db):
    run_synthetic_lap(db, track_lap(src="a.csv"), driver="owner", role="self", config=CONFIG)
    run_synthetic_lap(db, track_lap(src="b.csv"), driver="owner", role="self", config=CONFIG)
    run_synthetic_lap(db, track_lap(src="ref.csv"), driver="owner", role="reference", config=CONFIG)

    with db.conn:
        db.conn.execute(
            "UPDATE laps SET lap_date=? WHERE source_file=?", ("2026-07-01", "a.csv"),
        )
        # Dating the reference lap must not count toward the self-only total.
        db.conn.execute(
            "UPDATE laps SET lap_date=? WHERE source_file=?", ("2026-07-01", "ref.csv"),
        )

    assert db.driver_dated_lap_count("owner") == 1
