"""M2 persistence tests: blobs, migrations, retention, isolation, admission."""

from pathlib import Path

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.db import MIGRATIONS, Database
from synth import CORNER_WINDOWS, one_corner_lap, run_synthetic_lap, track_lap

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIG = DriverDNAConfig()

COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def test_migrations_apply_fully(db):
    assert db.schema_version == len(MIGRATIONS)


def test_lap_blob_round_trip(db):
    lap = one_corner_lap()
    lap_pk, was_new = db.import_lap(lap, **COHORT)
    assert was_new
    arrays = db.load_lap_arrays(lap_pk)
    assert np.array_equal(arrays["speed"], lap.speed)
    assert np.array_equal(arrays["gear"], lap.gear)
    assert arrays["abs_active"].dtype == np.bool_
    assert np.array_equal(arrays["lap_dist"], lap.lap_dist)


def test_reimport_same_source_is_noop(db):
    lap = one_corner_lap()
    pk1, new1 = db.import_lap(lap, **COHORT)
    pk2, new2 = db.import_lap(lap, **COHORT)
    assert (pk1, new1, pk2, new2) == (pk1, True, pk1, False)
    assert db.conn.execute("SELECT COUNT(*) n FROM laps").fetchone()["n"] == 1


def test_retention_evicts_blobs_only_and_preserves_history(db):
    pks = []
    for i in range(5):
        lap = track_lap(src=f"lap{i}.csv")
        result = _run_pipeline(db, lap)
        pks.append(result.lap_pk)

    history_before = db.self_metric_history(
        **COHORT, corner_id="C01", metric="min_speed_kmh"
    )
    assert len(history_before) == 5

    evicted = db.enforce_retention(keep=3)
    assert evicted == 2
    assert db.load_lap_arrays(pks[0]) is None
    assert db.load_lap_arrays(pks[1]) is None
    assert db.load_lap_arrays(pks[4]) is not None
    # Compact rows and trends untouched:
    assert db.conn.execute("SELECT COUNT(*) n FROM laps").fetchone()["n"] == 5
    assert (
        db.self_metric_history(**COHORT, corner_id="C01", metric="min_speed_kmh")
        == history_before
    )


def _run_pipeline(db, lap, *, driver="owner", role="self"):
    return run_synthetic_lap(db, lap, driver=driver, role=role, config=CONFIG)


def test_reference_lap_never_enters_self_history(db):
    _run_pipeline(db, track_lap(src="self1.csv"))
    _run_pipeline(db, track_lap(src="self2.csv"))

    table_before = db.self_metric_table(**COHORT)
    detectors_before = db.self_detector_table(**COHORT)
    classes_before = db.corner_classes(car=COHORT["car"], track=COHORT["track"])

    result = _run_pipeline(
        db, track_lap(src="ref1.csv"), driver="faster-driver", role="reference"
    )
    # Reference lap matches the SAME frozen identities (shared map)...
    assert result.assigned == ["C01", "C02", "C03"]
    # ...but self history, detector counts, and classes are byte-identical.
    assert db.self_metric_table(**COHORT) == table_before
    assert db.self_detector_table(**COHORT) == detectors_before
    assert (
        db.corner_classes(car=COHORT["car"], track=COHORT["track"]) == classes_before
    )
    # The reference observations do exist (for M3 gap analysis):
    n_obs = db.conn.execute(
        "SELECT COUNT(*) n FROM corner_observations"
    ).fetchone()["n"]
    assert n_obs == 9  # 3 laps x 3 corners


def test_candidate_admission_after_min_laps(db):
    _run_pipeline(db, track_lap(src="base.csv"))  # builds + freezes 3 corners
    extra = CORNER_WINDOWS + [(2200, 2350)]

    r1 = _run_pipeline(db, track_lap(windows=extra, src="a.csv"))
    assert r1.assigned == ["C01", "C02", None, "C03"] and r1.admitted == []
    r2 = _run_pipeline(db, track_lap(windows=extra, src="b.csv"))
    assert r2.admitted == []
    r3 = _run_pipeline(db, track_lap(windows=extra, src="c.csv"))
    assert r3.admitted == ["C04"]  # third distinct lap crosses the threshold

    # Admitted corner is linked, classified, and permanent:
    classes = db.corner_classes(car=COHORT["car"], track=COHORT["track"])
    assert classes["C04"] is not None
    unlinked = db.conn.execute(
        "SELECT COUNT(*) n FROM corner_observations WHERE corner_pk IS NULL"
    ).fetchone()["n"]
    assert unlinked == 0


def test_first_import_builds_and_freezes_map(db):
    result = _run_pipeline(db, track_lap(src="first.csv"))
    assert result.assigned == ["C01", "C02", "C03"]
    loaded = db.load_corner_map(car=COHORT["car"], track=COHORT["track"])
    assert loaded is not None and len(loaded[1].corners) == 3
    classes = db.corner_classes(car=COHORT["car"], track=COHORT["track"])
    assert set(classes.values()) == {"medium"}  # 30 m/s = 108 km/h


def test_config_history_records(db):
    db.record_config_change(
        key="detectors.overlap_max_s",
        old_value="0.75",
        new_value="0.9",
        source="cli",
        note="testing",
    )
    row = db.conn.execute("SELECT * FROM config_history").fetchone()
    assert row["key"] == "detectors.overlap_max_s" and row["source"] == "cli"
