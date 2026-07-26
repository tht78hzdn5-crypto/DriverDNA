"""Raw lap telemetry blob storage — one compressed npz per lap, on local disk.

Raw samples used to live in a `lap_samples` BLOB column. They now live beside
the database rather than inside it, because the queryable record moved to a
hosted Postgres and the raw traces did not: a lap is ~300-580 KB compressed,
they are only ever read whole, and pushing them over the wire would have cost
roughly 2x the free-tier database allowance plus ~1 GB of egress on a single
`rebuild-map`.

The consequence is deliberate and already-handled: a blob is present on the
machine that imported it, and absent elsewhere. That is not a new failure
mode — `load_lap_arrays` has always returned None for an evicted blob, and
every caller already degrades honestly (the track-trace view 404s, the
pipeline skips re-measurement, `raw_retained` reports false). "Absent here"
simply joins "evicted by retention" on that same path.

Blob roots are per-database by construction, so two databases can never
collide on a lap_pk: a SQLite file `X.db` stores blobs in `X.db.blobs/`, and
a remote store uses `~/.driverdna/blobs/<database-name>/`. Both are
overridable via `--blobs` or DRIVERDNA_BLOB_ROOT.
"""

from __future__ import annotations

import os
from pathlib import Path

BLOB_ROOT_ENV = "DRIVERDNA_BLOB_ROOT"

#: Marker meaning "this database keeps no blobs on disk" (in-memory tests).
MEMORY = ":memory:"


class BlobStore:
    """Raw-blob storage keyed by lap_pk.

    `get` returning None is a first-class answer, not an error: it means the
    lap's raw trace is not available *here*, whether because retention evicted
    it or because it was imported on another machine.
    """

    def put(self, lap_pk: int, data: bytes) -> None:
        raise NotImplementedError

    def get(self, lap_pk: int) -> bytes | None:
        raise NotImplementedError

    def delete(self, lap_pk: int) -> bool:
        """Remove one blob. Returns whether anything was there to remove."""
        raise NotImplementedError

    def has(self, lap_pk: int) -> bool:
        raise NotImplementedError

    def lap_pks(self) -> set[int]:
        """Every lap_pk this store currently holds a blob for."""
        raise NotImplementedError


class MemoryBlobStore(BlobStore):
    """For `:memory:` databases — the database itself does not outlive the
    process, so neither should its blobs."""

    def __init__(self) -> None:
        self._data: dict[int, bytes] = {}

    def put(self, lap_pk: int, data: bytes) -> None:
        self._data[int(lap_pk)] = data

    def get(self, lap_pk: int) -> bytes | None:
        return self._data.get(int(lap_pk))

    def delete(self, lap_pk: int) -> bool:
        return self._data.pop(int(lap_pk), None) is not None

    def has(self, lap_pk: int) -> bool:
        return int(lap_pk) in self._data

    def lap_pks(self) -> set[int]:
        return set(self._data)


class FileBlobStore(BlobStore):
    """One `<lap_pk>.npz` per lap under `root`.

    The directory is created lazily on first write, so merely opening a
    database never leaves a stray directory behind.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, lap_pk: int) -> Path:
        return self.root / f"{int(lap_pk)}.npz"

    def put(self, lap_pk: int, data: bytes) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._path(lap_pk)
        # Write-then-rename: a crash mid-write leaves the old blob or no
        # blob, never a truncated one that would parse as corrupt telemetry.
        tmp = target.with_suffix(".npz.tmp")
        tmp.write_bytes(data)
        tmp.replace(target)

    def get(self, lap_pk: int) -> bytes | None:
        path = self._path(lap_pk)
        return path.read_bytes() if path.exists() else None

    def delete(self, lap_pk: int) -> bool:
        path = self._path(lap_pk)
        if not path.exists():
            return False
        path.unlink()
        return True

    def has(self, lap_pk: int) -> bool:
        return self._path(lap_pk).exists()

    def lap_pks(self) -> set[int]:
        if not self.root.exists():
            return set()
        out: set[int] = set()
        for p in self.root.glob("*.npz"):
            try:
                out.add(int(p.stem))
            except ValueError:
                continue  # not ours; leave it alone
        return out


def default_blob_root(db_path: Path | str) -> Path | str:
    """Where a database's blobs live when nothing overrides it.

    Per-database by construction, so `demo.db` and `driverdna.db` can never
    write over each other's lap_pk-keyed blobs. DRIVERDNA_BLOB_ROOT overrides
    for a specific database only if you point it somewhere unshared — it is
    taken literally, on the assumption the caller means it.
    """
    override = os.environ.get(BLOB_ROOT_ENV)
    if override:
        return Path(override).expanduser()

    text = str(db_path)
    if text == MEMORY:
        return MEMORY
    if "://" in text:
        # A remote store has no local file to sit beside; key off its name.
        name = text.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0] or "default"
        return Path.home() / ".driverdna" / "blobs" / name
    return Path(f"{text}.blobs")


def open_blob_store(db_path: Path | str, blob_root: Path | str | None = None) -> BlobStore:
    root = blob_root if blob_root is not None else default_blob_root(db_path)
    if root == MEMORY:
        return MemoryBlobStore()
    return FileBlobStore(Path(root))
