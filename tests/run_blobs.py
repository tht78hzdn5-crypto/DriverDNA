import sys
import traceback
from pathlib import Path
from driverdna.db import Database
from synth import run_synthetic_lap, track_lap
import sqlite3
import pytest

COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}

def _v5_database_with_inline_blobs(db_path: Path) -> list[int]:
    with Database.open(db_path) as db:
        pks = [
            run_synthetic_lap(db, track_lap(src=f"legacy{i}.csv"), **COHORT).lap_pk
            for i in range(3)
        ]
        blobs = {pk: db.blobs.get(pk) for pk in pks}

    raw = sqlite3.connect(db_path)
    raw.execute("ALTER TABLE lap_samples_legacy RENAME TO lap_samples")
    for pk, data in blobs.items():
        raw.execute(
            "INSERT INTO lap_samples (lap_pk, fmt, data) VALUES (?, 'npz-v1', ?)",
            (pk, data),
        )
    raw.execute("DELETE FROM schema_version WHERE version = 6")
    raw.commit()
    raw.close()

    for pk in pks:
        blob_file = db_path.parent / f"{db_path.name}.blobs" / f"{pk}.npz"
        if blob_file.exists():
            blob_file.unlink()
    return pks

try:
    import tempfile
    import os
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "driverdna.db"
        pks = _v5_database_with_inline_blobs(db_path)

        with Database.open(db_path) as db:
            assert db.schema_version == 6
            n = db.conn.execute("SELECT COUNT(*) AS n FROM lap_samples_legacy").fetchone()["n"]
            if n != 3:
                print(f"FAILED: n={n} instead of 3")
            else:
                print("PASSED test_old_database_still_reads_its_blobs_before_draining")
except Exception as e:
    traceback.print_exc()

try:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "driverdna.db"
        pks = _v5_database_with_inline_blobs(db_path)

        with Database.open(db_path) as db:
            print("LAPS in DB:")
            print(db.conn.execute("SELECT * FROM laps").fetchall())
            print("LAP SAMPLES LEGACY in DB:")
            print(db.conn.execute("SELECT * FROM lap_samples_legacy").fetchall())
            print("JOIN RESULT:")
            print(db.conn.execute("SELECT ls.lap_pk, ls.data FROM lap_samples_legacy ls JOIN laps l ON l.lap_pk = ls.lap_pk WHERE l.owner_user_pk = ?", (1,)).fetchall())
            
            before = {pk: db.load_lap_arrays(pk) for pk in pks}
            n_drained = db.drain_legacy_blobs()
            if n_drained != 3:
                print(f"FAILED drain: n_drained={n_drained}")
            else:
                print("PASSED test_draining_is_lossless_and_idempotent")
except Exception as e:
    traceback.print_exc()
