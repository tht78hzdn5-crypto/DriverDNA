"""`driverdna store-copy`: moving a store without changing what it says.

The hard requirement is that primary keys survive. Evidence IDs are literally
those numbers — `obs:{obs_pk}`, `incident:{incident_pk}` — and annotations,
chat transcripts and stored coach outputs all cite them. A copy that
renumbered would silently invalidate the driver's whole history.
"""

from __future__ import annotations

import pytest

from conftest import requires_postgres
from driverdna.db import Database
from driverdna.migrate import IDENTITY_COLUMNS, TABLES, checksum, compare, copy_store
from synth import run_synthetic_lap, track_lap, warp_time

COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}
C01_WARP = (0.19, 0.22)


def _populate(db) -> None:
    for i in range(4):
        run_synthetic_lap(db, track_lap(src=f"fast{i}.csv"), session_key=f"s{i % 2 + 1}")
    for i in range(3):
        lap = warp_time(track_lap(src=f"slow{i}.csv"), C01_WARP, 0.4)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2 + 1}")
    db.annotate_finding(finding_id="f:probe", status="acknowledged", note="mine")
    db.add_chat_turn(
        session_id="s1", bundle_version=1, role="driver", content="why?",
        evidence_cited=["obs:1"],
    )


def test_copy_preserves_contents_between_sqlite_stores(tmp_path):
    with Database.open(tmp_path / "src.db") as src:
        _populate(src)
        with Database.open(tmp_path / "dst.db") as dst:
            counts = copy_store(src, dst)
            assert counts["laps"] == 7
            assert compare(src, dst) == [], "copy is not faithful"


def test_copy_preserves_primary_keys(tmp_path):
    """The whole point: evidence IDs are these numbers."""
    with Database.open(tmp_path / "src.db") as src:
        _populate(src)
        before = {
            table: [r[pk] for r in src.conn.execute(f"SELECT {pk} FROM {table}")]
            for table, pk in IDENTITY_COLUMNS.items()
        }
        with Database.open(tmp_path / "dst.db") as dst:
            copy_store(src, dst)
            after = {
                table: [r[pk] for r in dst.conn.execute(f"SELECT {pk} FROM {table}")]
                for table, pk in IDENTITY_COLUMNS.items()
            }
    for table in IDENTITY_COLUMNS:
        assert sorted(before[table]) == sorted(after[table]), f"{table} renumbered"


def test_copy_refuses_a_non_empty_target(tmp_path):
    """Never merge. A half-merged evidence store cannot be untangled, and
    "nothing is silently merged" is a standing rule."""
    with Database.open(tmp_path / "src.db") as src:
        _populate(src)
        with Database.open(tmp_path / "dst.db") as dst:
            _populate(dst)
            with pytest.raises(ValueError, match="refusing to merge"):
                copy_store(src, dst)


def test_checksum_notices_a_single_changed_value(tmp_path):
    """The verification has to be able to fail, or it proves nothing."""
    with Database.open(tmp_path / "src.db") as src:
        _populate(src)
        with Database.open(tmp_path / "dst.db") as dst:
            copy_store(src, dst)
            assert compare(src, dst) == []
            # A non-null row specifically: `value` is nullable, and
            # NULL + 0.001 is NULL, which would change nothing.
            with dst.conn:
                changed = dst.conn.execute(
                    """UPDATE metric_values SET value = value + 0.001
                       WHERE rowid = (SELECT MIN(rowid) FROM metric_values
                                      WHERE value IS NOT NULL)"""
                ).rowcount
            assert changed == 1
            assert "metric_values" in compare(src, dst)


def test_checksum_distinguishes_float_precision(tmp_path):
    """A float silently narrowed to float4 must change the checksum — that is
    what makes this catch a wrong column type at the row level rather than
    months later as a changed report byte."""
    with Database.open(tmp_path / "a.db") as a, Database.open(tmp_path / "b.db") as b:
        for db, value in ((a, 0.1234567890123456), (b, 0.12345678)):
            db.conn.execute(
                """INSERT INTO laps (source_file, driver, car, track, role,
                                     n_samples, duration_s, quality_flags)
                   VALUES ('p.csv','owner','C','T','self',1,?,'[]')""",
                (value,),
            )
            db.conn.commit()
        assert checksum(a)["laps"] != checksum(b)["laps"]


def test_incident_sample_indices_are_stored_as_integers(tmp_path):
    """Regression: numpy int64 sample indices used to reach sqlite3 unadapted
    and land as BLOBs in an INTEGER column — accepted silently by SQLite's
    dynamic typing, rejected outright by a strictly-typed store, and sorting
    after every integer in the meantime."""
    from driverdna.incidents.detector import Incident

    with Database.open(tmp_path / "x.db") as db:
        lap_pk = run_synthetic_lap(db, track_lap(src="inc.csv")).lap_pk
        import numpy as np

        db.store_incidents(lap_pk, [
            Incident(
                kinds=("near_stop",), classification="unclassified",
                confidence="low", corner_id="C01",
                span_start=np.int64(100), span_end=np.int64(200),
                onset=np.int64(100), min_speed_kmh=np.float64(12.5),
                peak_yaw_rate=np.float64(0.5), rationale="synthetic",
                detail={},
            )
        ])
        row = db.conn.execute(
            "SELECT span_start, span_end, onset FROM incidents"
        ).fetchone()
        for col in ("span_start", "span_end", "onset"):
            assert isinstance(row[col], int), f"{col} is {type(row[col]).__name__}"


# --- across backends -------------------------------------------------------


@requires_postgres
def test_copy_sqlite_to_postgres_is_faithful(pg_schema, tmp_path):
    with Database.open(tmp_path / "src.db") as src:
        _populate(src)
        with Database.open(pg_schema, blob_root=tmp_path / "b") as dst:
            copy_store(src, dst)
            assert compare(src, dst) == []
            for table in TABLES:
                n_src = src.conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"
                ).fetchone()["n"]
                n_dst = dst.conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"
                ).fetchone()["n"]
                assert n_src == n_dst, table


@requires_postgres
def test_identity_sequences_are_reset_after_copy(pg_schema, tmp_path):
    """Without `setval`, the next import collides on a duplicate key — loud,
    but only after cutover."""
    with Database.open(tmp_path / "src.db") as src:
        _populate(src)
        with Database.open(pg_schema, blob_root=tmp_path / "b") as dst:
            copy_store(src, dst)
            highest = dst.conn.execute(
                "SELECT MAX(lap_pk) AS m FROM laps"
            ).fetchone()["m"]
            new_pk = dst._insert_returning(
                """INSERT INTO laps (source_file, driver, car, track, role,
                                     n_samples, duration_s, quality_flags)
                   VALUES ('after.csv','owner','C','T','self',1,1.0,'[]')""",
                (),
                "lap_pk",
            )
            assert new_pk > highest


@requires_postgres
def test_round_trip_back_to_sqlite(pg_schema, tmp_path):
    """The reverse direction is the backup story: a free-tier project has no
    point-in-time recovery, so `store-copy --from-postgres` is what makes the
    local-offline path a tested capability rather than a memory."""
    with Database.open(tmp_path / "src.db") as src:
        _populate(src)
        with Database.open(pg_schema, blob_root=tmp_path / "b") as mid:
            copy_store(src, mid)
            with Database.open(tmp_path / "back.db") as back:
                copy_store(mid, back)
                assert compare(src, back) == []
