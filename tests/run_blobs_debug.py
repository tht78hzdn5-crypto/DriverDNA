import sys
import traceback
from pathlib import Path
from driverdna.db import Database
from synth import run_synthetic_lap, track_lap
from test_blobs import _v5_database_with_inline_blobs
import sqlite3
import tempfile
import driverdna.db

COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}

try:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "driverdna.db"
        
        pks = _v5_database_with_inline_blobs(db_path)
        
        with Database.open(db_path) as db:
            raw = sqlite3.connect(db_path)
            print("LAPS DATA:", raw.execute("SELECT lap_pk, owner_user_pk FROM laps").fetchall())
            print("LAP SAMPLES LEGACY DATA:", raw.execute("SELECT lap_pk FROM lap_samples_legacy").fetchall())
            print("JOIN RESULT:", raw.execute("SELECT ls.lap_pk FROM lap_samples_legacy ls JOIN laps l ON l.lap_pk = ls.lap_pk WHERE l.owner_user_pk = ?", (1,)).fetchall())
            raw.close()
except Exception as e:
    traceback.print_exc()
