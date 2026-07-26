"""Copying a store between backends, and proving the copy is faithful.

The hard requirement is that primary keys survive unchanged. Evidence IDs are
literally these numbers — `f"obs:{obs_pk}"` (coaching/engine.py),
`f"incident:{incident_pk}"` (db.py) — and finding IDs embed `corner_id`.
Annotations key on finding_id, chat transcripts cite evidence IDs, and stored
coach outputs contain them as text. Renumbering during a copy would silently
invalidate every persisted citation, annotation and belief in the driver's
history, which is exactly the kind of quiet corruption this project exists to
refuse. So rows are written with explicit primary keys and the identity
sequences are reset afterwards.

Raw lap blobs are not copied: they live on local disk (see blobs.py), keyed
per-database. A copied store is a store whose *summaries* moved; the machine
holding the blobs still holds them, and any other machine honestly reports
the raw trace as unavailable — the same state retention already produces.
"""

from __future__ import annotations

import hashlib

#: Foreign-key dependency order. Parents first, so every insert has its
#: referent. `lap_samples_legacy` is deliberately absent — blobs are local.
TABLES: tuple[str, ...] = (
    "laps",
    "corner_maps",
    "corners",
    "corner_windows",
    "corner_observations",
    "phase_times",
    "metric_values",
    "detector_results",
    "incidents",
    "config_history",
    "coach_outputs",
    "finding_annotations",
    "chat_transcripts",
    "driver_beliefs",
    "garage61_sync_state",
)

#: Tables whose primary key is an auto-assigned surrogate. After copying with
#: explicit values the sequence must be moved past the highest one, or the
#: next insert collides.
IDENTITY_COLUMNS: dict[str, str] = {
    "laps": "lap_pk",
    "corner_maps": "map_pk",
    "corners": "corner_pk",
    "corner_observations": "obs_pk",
    "config_history": "change_pk",
    "coach_outputs": "output_pk",
    "finding_annotations": "annotation_pk",
    "chat_transcripts": "turn_pk",
    "driver_beliefs": "belief_pk",
    "incidents": "incident_pk",
}

#: A stable read order per table, so two stores serialize identically.
_ORDER: dict[str, str] = {
    "corner_windows": "corner_pk",
    "phase_times": "obs_pk, phase",
    "metric_values": "obs_pk, name",
    "detector_results": "obs_pk, detector",
    "garage61_sync_state": "driver, car, track",
}


def _order_by(table: str) -> str:
    return _ORDER.get(table) or IDENTITY_COLUMNS[table]


def _columns(db, table: str) -> list[str]:
    """Column names in declaration order, read from the store itself rather
    than hardcoded, so a schema change cannot silently desync this module."""
    cur = db.conn.execute(f"SELECT * FROM {table} WHERE 1=0")
    return [d[0] for d in cur.description]


#: Integer columns that older databases may hold as BLOBs.
#:
#: `store_incidents` used to pass numpy int64 sample indices straight to
#: sqlite3, which has no adapter for that type and stored the raw
#: little-endian bytes into an INTEGER column — accepted silently by SQLite's
#: dynamic typing. The write path is fixed, but rows already on disk still
#: carry BLOBs, and a strictly-typed store rejects them. The values are
#: unambiguously recoverable, so a copy repairs them rather than either
#: failing or propagating the corruption; `repaired_int_columns` reports how
#: many, because a silent repair is exactly what this project forbids.
_LEGACY_INT_COLUMNS: dict[str, tuple[str, ...]] = {
    "incidents": ("span_start", "span_end", "onset"),
}

#: Populated by `_rows`; read by callers that want to report the repair.
repaired_int_columns: dict[str, int] = {}


def _coerce_legacy_int(value):
    if isinstance(value, (bytes, bytearray)):
        return int.from_bytes(bytes(value), "little", signed=True)
    return value


def _rows(db, table: str) -> list[dict]:
    cols = _columns(db, table)
    legacy = _LEGACY_INT_COLUMNS.get(table, ())
    out = []
    for row in db.conn.execute(f"SELECT * FROM {table} ORDER BY {_order_by(table)}"):
        record = {c: row[c] for c in cols}
        for col in legacy:
            fixed = _coerce_legacy_int(record[col])
            if fixed is not record[col]:
                repaired_int_columns[f"{table}.{col}"] = (
                    repaired_int_columns.get(f"{table}.{col}", 0) + 1
                )
            record[col] = fixed
        out.append(record)
    return out


def is_empty(db) -> bool:
    for table in TABLES:
        if db.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]:
            return False
    return True


def copy_store(source, target) -> dict[str, int]:
    """Copy every compact row from `source` into an empty `target`.

    Refuses a non-empty target rather than merging. A half-merged evidence
    store cannot be untangled afterwards, and "nothing is silently merged" is
    a standing rule here.
    """
    if not is_empty(target):
        raise ValueError(
            "target store already holds data — refusing to merge. "
            "Copy into an empty store, or clear it deliberately first."
        )

    counts: dict[str, int] = {}
    for table in TABLES:
        rows = _rows(source, table)
        counts[table] = len(rows)
        if not rows:
            continue
        cols = _columns(source, table)
        placeholders = ", ".join("?" for _ in cols)
        statement = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
        )
        with target.conn:
            target.conn.executemany(
                statement, [tuple(r[c] for c in cols) for r in rows]
            )

    _resync_sequences(target)
    return counts


def _resync_sequences(db) -> None:
    """Move each identity sequence past the highest copied key.

    Skipped on SQLite, whose rowid allocator already derives the next value
    from MAX(pk). Forgetting this on Postgres produces a duplicate-key error
    on the *next* import — loud, but only after cutover.
    """
    if db.dialect.name != "postgres":
        return
    for table, pk in IDENTITY_COLUMNS.items():
        db.conn.execute(
            f"""SELECT setval(
                    pg_get_serial_sequence('{table}', '{pk}'),
                    COALESCE((SELECT MAX({pk}) FROM {table}), 1),
                    (SELECT MAX({pk}) IS NOT NULL FROM {table})
                )"""
        )


# --- verification ----------------------------------------------------------


def _normalize(value) -> str:
    """A backend-independent rendering of one cell.

    `repr()` on a float is the point: it round-trips full float64 precision,
    so a value silently truncated to float4 by a wrong column type produces a
    different string immediately, at the row level, instead of surfacing much
    later as a changed report byte.
    """
    if value is None:
        return "\x00NULL"
    if isinstance(value, bool):
        return f"bool:{value}"
    if isinstance(value, float):
        return f"float:{value!r}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, (bytes, bytearray)):
        return f"bytes:{hashlib.sha256(bytes(value)).hexdigest()}"
    return f"str:{value}"


def checksum(db) -> dict[str, tuple[int, str]]:
    """Per-table (row count, sha256) over the normalized contents."""
    out: dict[str, tuple[int, str]] = {}
    for table in TABLES:
        digest = hashlib.sha256()
        rows = _rows(db, table)
        for row in rows:
            for col in _columns(db, table):
                digest.update(_normalize(row[col]).encode())
                digest.update(b"\x1f")
            digest.update(b"\x1e")
        out[table] = (len(rows), digest.hexdigest())
    return out


def compare(source, target) -> list[str]:
    """Tables whose contents differ. Empty means the copy is faithful."""
    a, b = checksum(source), checksum(target)
    return [t for t in TABLES if a[t] != b[t]]
