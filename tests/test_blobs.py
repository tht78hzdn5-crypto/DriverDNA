"""Raw-blob storage on local disk, and the lossless upgrade from in-database
blobs (migration 006).

The upgrade path matters more than it looks: an existing database holds real
telemetry in `lap_samples`, and the only other copy is the original export.
Dropping that table would have been silent data loss, so 006 renames it and
`drain_legacy_blobs` moves the bytes out only once they are safely on disk.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from driverdna.blobs import (
    FileBlobStore,
    MemoryBlobStore,
    default_blob_root,
    open_blob_store,
)
from driverdna.db import MIGRATIONS, Database
from synth import run_synthetic_lap, track_lap

COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


# --- the store itself ------------------------------------------------------


@pytest.mark.parametrize("make", [lambda tmp: MemoryBlobStore(),
                                  lambda tmp: FileBlobStore(tmp / "blobs")])
def test_store_round_trip(make, tmp_path):
    store = make(tmp_path)
    assert store.get(1) is None
    assert store.has(1) is False
    assert store.delete(1) is False
    assert store.lap_pks() == set()

    store.put(1, b"first")
    store.put(2, b"second")
    assert store.get(1) == b"first"
    assert store.has(2) is True
    assert store.lap_pks() == {1, 2}

    store.put(1, b"overwritten")
    assert store.get(1) == b"overwritten"

    assert store.delete(1) is True
    assert store.get(1) is None
    assert store.lap_pks() == {2}


@pytest.mark.parametrize("make", [lambda tmp: MemoryBlobStore(),
                                  lambda tmp: FileBlobStore(tmp / "blobs")])
def test_eviction_tombstones_round_trip(make, tmp_path):
    """An eviction is recorded separately from the blob's absence, because
    "deliberately gone from here" and "never arrived here" have different
    consequences for rebuild-map (A26)."""
    store = make(tmp_path)
    store.put(1, b"first")
    store.put(2, b"second")
    assert store.evicted_lap_pks() == set()

    store.delete(1)
    assert store.evicted_lap_pks() == set()  # deleting alone claims nothing
    store.mark_evicted(1)
    assert store.evicted_lap_pks() == {1}

    # A tombstone is not a blob, and never becomes one.
    assert store.lap_pks() == {2}
    assert store.get(1) is None
    assert store.has(1) is False

    store.mark_evicted(1)  # idempotent
    assert store.evicted_lap_pks() == {1}


def test_file_store_tombstone_does_not_collide_with_blob_names(tmp_path):
    root = tmp_path / "blobs"
    store = FileBlobStore(root)
    store.put(7, b"payload")
    store.mark_evicted(9)
    assert sorted(p.name for p in root.iterdir()) == ["7.npz", "9.evicted"]
    assert store.lap_pks() == {7}
    assert store.evicted_lap_pks() == {9}


def test_file_store_leaves_no_temp_files(tmp_path):
    """`put` writes then renames, so a reader never sees a truncated blob.
    The temp file must not survive the write."""
    store = FileBlobStore(tmp_path / "blobs")
    store.put(7, b"payload")
    assert sorted(p.name for p in (tmp_path / "blobs").iterdir()) == ["7.npz"]


def test_file_store_ignores_foreign_files(tmp_path):
    """The blob directory is the owner's; a stray file must not crash
    `lap_pks()` or be counted as a lap."""
    root = tmp_path / "blobs"
    store = FileBlobStore(root)
    store.put(3, b"mine")
    (root / "notes.txt").write_text("hello")
    (root / "not-a-number.npz").write_bytes(b"x")
    assert store.lap_pks() == {3}


def test_directory_created_lazily(tmp_path):
    """Merely opening a database must not litter the filesystem."""
    root = tmp_path / "blobs"
    store = FileBlobStore(root)
    assert not root.exists()
    assert store.get(1) is None and store.lap_pks() == set()
    store.put(1, b"x")
    assert root.exists()


# --- blob root resolution --------------------------------------------------


def test_blob_root_is_per_database(tmp_path, monkeypatch):
    """Two databases must never share a blob root — they both start lap_pk
    at 1, so a shared root would have them overwrite each other's telemetry."""
    monkeypatch.delenv("DRIVERDNA_BLOB_ROOT", raising=False)
    real = default_blob_root(tmp_path / "driverdna.db")
    demo = default_blob_root(tmp_path / "demo.db")
    assert real != demo
    assert str(real).endswith("driverdna.db.blobs")


def test_memory_database_gets_a_memory_store(monkeypatch):
    monkeypatch.delenv("DRIVERDNA_BLOB_ROOT", raising=False)
    assert isinstance(open_blob_store(":memory:"), MemoryBlobStore)


def test_remote_url_keys_off_database_name(tmp_path, monkeypatch):
    """A hosted store has no local file to sit beside, so blobs key off its
    name under ~/.driverdna/blobs/."""
    monkeypatch.delenv("DRIVERDNA_BLOB_ROOT", raising=False)
    root = default_blob_root("postgresql://user:pw@host:5432/driverdna")
    assert Path(root).name == "driverdna"
    assert ".driverdna" in str(root)


def test_env_var_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIVERDNA_BLOB_ROOT", str(tmp_path / "elsewhere"))
    assert default_blob_root(tmp_path / "driverdna.db") == tmp_path / "elsewhere"


# --- database integration --------------------------------------------------


def test_import_writes_blob_to_disk_not_the_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DRIVERDNA_BLOB_ROOT", raising=False)
    db_path = tmp_path / "driverdna.db"
    with Database.open(db_path) as db:
        lap_pk = run_synthetic_lap(db, track_lap(src="a.csv"), **COHORT).lap_pk
        arrays = db.load_lap_arrays(lap_pk)
        assert arrays is not None and "speed" in arrays

    assert (tmp_path / "driverdna.db.blobs" / f"{lap_pk}.npz").exists()

    # And nothing raw is left inside the database.
    raw = sqlite3.connect(db_path)
    assert raw.execute(
        "SELECT COUNT(*) FROM lap_samples_legacy"
    ).fetchone()[0] == 0
    raw.close()


# --- the upgrade path ------------------------------------------------------


def _v5_database_with_inline_blobs(db_path: Path) -> list[int]:
    """Build a schema-5 database holding blobs in `lap_samples`, the way
    every database created before migration 006 does."""
    with Database.open(db_path) as db:
        pks = [
            run_synthetic_lap(db, track_lap(src=f"legacy{i}.csv"), **COHORT).lap_pk
            for i in range(3)
        ]
        blobs = {pk: db.blobs.get(pk) for pk in pks}

    # Rewind: put the bytes back inline and undo the rename, so the file
    # looks exactly like a pre-006 database on disk.
    raw = sqlite3.connect(db_path)
    raw.execute("ALTER TABLE lap_samples_legacy RENAME TO lap_samples")
    for pk, data in blobs.items():
        raw.execute(
            "INSERT INTO lap_samples (lap_pk, fmt, data) VALUES (?, 'npz-v1', ?)",
            (pk, data),
        )
    raw.execute("DELETE FROM schema_version WHERE version >= 6")
    raw.execute("DROP TABLE IF EXISTS password_resets")
    raw.execute("DROP TABLE IF EXISTS users")
    raw.execute("DROP TABLE IF EXISTS user_api_keys")
    try:
        raw.execute("ALTER TABLE laps DROP COLUMN owner_user_pk")
    except sqlite3.OperationalError:
        pass
    raw.commit()
    raw.close()

    for pk in pks:
        (db_path.parent / f"{db_path.name}.blobs" / f"{pk}.npz").unlink()
    return pks


def test_old_database_still_reads_its_blobs_before_draining(tmp_path, monkeypatch):
    """Upgrading must not require a migration step to keep working: an
    un-drained database reads its raw traces from the legacy table."""
    monkeypatch.delenv("DRIVERDNA_BLOB_ROOT", raising=False)
    db_path = tmp_path / "driverdna.db"
    pks = _v5_database_with_inline_blobs(db_path)

    with Database.open(db_path) as db:
        assert db.schema_version == len(MIGRATIONS)  # all migrations applied on open
        assert db.conn.execute(
            "SELECT COUNT(*) AS n FROM lap_samples_legacy"
        ).fetchone()["n"] == 3
        assert db.has_raw(pks[0]) is True
        assert db.load_lap_arrays(pks[0]) is not None


def test_draining_is_lossless_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.delenv("DRIVERDNA_BLOB_ROOT", raising=False)
    db_path = tmp_path / "driverdna.db"
    pks = _v5_database_with_inline_blobs(db_path)

    with Database.open(db_path) as db:
        before = {pk: db.load_lap_arrays(pk) for pk in pks}
        assert db.drain_legacy_blobs() == 3
        assert db.conn.execute(
            "SELECT COUNT(*) AS n FROM lap_samples_legacy"
        ).fetchone()["n"] == 0

        for pk in pks:
            after = db.load_lap_arrays(pk)
            assert after is not None
            assert all(np.array_equal(before[pk][k], after[k]) for k in before[pk])

        assert db.drain_legacy_blobs() == 0  # idempotent

    for pk in pks:
        assert (tmp_path / "driverdna.db.blobs" / f"{pk}.npz").exists()


def test_drain_on_a_fresh_database_is_a_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("DRIVERDNA_BLOB_ROOT", raising=False)
    with Database.open(tmp_path / "fresh.db") as db:
        assert db.drain_legacy_blobs() == 0
