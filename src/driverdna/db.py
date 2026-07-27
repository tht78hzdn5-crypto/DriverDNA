"""SQLite persistence: schema, migrations, lap-blob storage, eviction (M2).

Raw lap samples are stored as one compressed npz blob per lap — laps are
always loaded whole, nothing queries individual samples by SQL. Everything
queryable lives in compact relational rows: laps (metadata + quality flags),
frozen corner maps, per-lap corner observations (span, landmarks, apex
position), metric values, detector results, config history. Compact rows are
permanent; only raw blobs are windowed (newest N per driver/car/track
cohort, transactional single-row deletes that can never touch summaries).

Role isolation is enforced at the query surface: `self_metric_history` and
everything derived from it filter role='self', so reference laps can never
enter the driver's own history or trends.

Corner-map admission: unmatched observations accumulate as candidates; once
the same location is seen on enough distinct laps (config
identity.min_laps_for_admission), `admit_pending_candidates` appends a new
corner (next ID — existing IDs never renumber) and returns the admitted IDs
so the caller surfaces the map change. Nothing changes the map silently.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from driverdna.blobs import BlobStore, MemoryBlobStore, open_blob_store
from driverdna.config import IdentityConfig
from driverdna.sql import to_pg, to_pg_migrations
from driverdna.store import is_postgres_url, redact_dsn
from driverdna.corners.identity import CornerIdentity, CornerMap, _gps_ok, _meters
from driverdna.corners.segmenter import CornerSpan, Landmarks
from driverdna.ingest.parser import TelemetryLap

_BLOB_CHANNELS = (
    "elapsed_s", "lap_dist", "lap_dist_pct_raw", "speed", "lat", "lon",
    "brake", "throttle", "rpm", "steering_deg", "gear", "clutch",
    "abs_active", "drs_active", "lat_accel", "long_accel", "vert_accel",
    "yaw", "yaw_rate", "position_type",
)

MIGRATIONS: tuple[str, ...] = (
    # 001 — initial schema
    """
    CREATE TABLE laps (
        lap_pk INTEGER PRIMARY KEY,
        lap_id TEXT,
        source_file TEXT NOT NULL UNIQUE,
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('self', 'reference')),
        session_key TEXT,
        run_index INTEGER,
        n_samples INTEGER NOT NULL,
        duration_s REAL NOT NULL,
        imported_at TEXT,
        quality_flags TEXT NOT NULL
    );
    CREATE TABLE lap_samples (
        lap_pk INTEGER PRIMARY KEY REFERENCES laps(lap_pk) ON DELETE CASCADE,
        fmt TEXT NOT NULL,
        data BLOB NOT NULL
    );
    CREATE TABLE corner_maps (
        map_pk INTEGER PRIMARY KEY,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        built_from_n_laps INTEGER NOT NULL,
        UNIQUE (car, track)
    );
    CREATE TABLE corners (
        corner_pk INTEGER PRIMARY KEY,
        map_pk INTEGER NOT NULL REFERENCES corner_maps(map_pk) ON DELETE CASCADE,
        corner_id TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        lap_dist REAL NOT NULL,
        n_build_observations INTEGER NOT NULL,
        class TEXT,
        UNIQUE (map_pk, corner_id)
    );
    CREATE TABLE corner_observations (
        obs_pk INTEGER PRIMARY KEY,
        lap_pk INTEGER NOT NULL REFERENCES laps(lap_pk) ON DELETE CASCADE,
        corner_pk INTEGER REFERENCES corners(corner_pk),
        span_start INTEGER NOT NULL,
        span_end INTEGER NOT NULL,
        landmarks TEXT NOT NULL,
        landmark_positions TEXT NOT NULL,
        apex_lat REAL NOT NULL,
        apex_lon REAL NOT NULL,
        apex_lap_dist REAL NOT NULL,
        min_speed_ms REAL NOT NULL,
        UNIQUE (lap_pk, span_start)
    );
    CREATE TABLE corner_windows (
        corner_pk INTEGER PRIMARY KEY REFERENCES corners(corner_pk) ON DELETE CASCADE,
        entry_start REAL,
        turn_in REAL,
        apex REAL NOT NULL,
        exit_end REAL
    );
    CREATE TABLE phase_times (
        obs_pk INTEGER NOT NULL REFERENCES corner_observations(obs_pk) ON DELETE CASCADE,
        phase TEXT NOT NULL CHECK (phase IN ('entry', 'mid', 'exit')),
        time_s REAL NOT NULL,
        PRIMARY KEY (obs_pk, phase)
    );
    CREATE TABLE metric_values (
        obs_pk INTEGER NOT NULL REFERENCES corner_observations(obs_pk) ON DELETE CASCADE,
        name TEXT NOT NULL,
        value REAL,
        PRIMARY KEY (obs_pk, name)
    );
    CREATE TABLE detector_results (
        obs_pk INTEGER NOT NULL REFERENCES corner_observations(obs_pk) ON DELETE CASCADE,
        detector TEXT NOT NULL,
        triggered INTEGER NOT NULL,
        value REAL NOT NULL,
        threshold REAL NOT NULL,
        unit TEXT NOT NULL,
        rationale TEXT NOT NULL,
        PRIMARY KEY (obs_pk, detector)
    );
    CREATE TABLE config_history (
        change_pk INTEGER PRIMARY KEY,
        key TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT NOT NULL,
        source TEXT NOT NULL,
        note TEXT
    );
    CREATE TABLE coach_outputs (
        output_pk INTEGER PRIMARY KEY,
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        payload_version INTEGER NOT NULL,
        prompt_version TEXT NOT NULL,
        model TEXT NOT NULL,
        output_json TEXT NOT NULL,
        created_at TEXT
    );
    CREATE TABLE finding_annotations (
        annotation_pk INTEGER PRIMARY KEY,
        finding_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('acknowledged', 'intentional')),
        note TEXT,
        created_at TEXT
    );
    CREATE TABLE chat_transcripts (
        turn_pk INTEGER PRIMARY KEY,
        session_id TEXT NOT NULL,
        bundle_version INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('driver', 'assistant', 'system-event')),
        content TEXT NOT NULL,
        evidence_cited TEXT,
        effects TEXT
    );
    """,
    # 002 — content fingerprint so a re-download under a different filename
    # can't silently double-count a lap in self history.
    """
    ALTER TABLE laps ADD COLUMN content_hash TEXT;
    CREATE INDEX idx_laps_content_hash ON laps(content_hash);
    """,
    # 003 — Driver Model (M6): the belief store, plus a real lap_date column
    # distinct from imported_at (bookkeeping: when WE stored it) for trend,
    # which needs when the lap was actually DRIVEN. lap_date is unpopulated
    # until sync or a user-supplied import date exists (SPEC.md M6); trend
    # reads "unavailable" until then — the column exists now so nothing needs
    # a rewrite when that ingestion path lands.
    """
    ALTER TABLE laps ADD COLUMN lap_date TEXT;
    CREATE TABLE driver_beliefs (
        belief_pk INTEGER PRIMARY KEY,
        driver TEXT NOT NULL,
        fundamental TEXT NOT NULL,
        signal_status TEXT NOT NULL CHECK (signal_status IN ('measured','proxy','no_signal')),
        score REAL,
        confidence REAL NOT NULL,
        evidence_count INTEGER NOT NULL,
        trend TEXT NOT NULL CHECK (trend IN ('improving','stable','declining','unavailable')),
        insufficient_reason TEXT,
        scoring_model_version TEXT NOT NULL,
        taxonomy_version TEXT NOT NULL,
        computed_at TEXT,
        UNIQUE (driver, fundamental, scoring_model_version)
    );
    """,
    # 004 — sync (M0b+): bookkeeping for `driverdna sync`. Idempotency itself
    # comes from the existing source_file/content_hash dedup in import_lap
    # (a sync-fetched lap's source_file is "garage61-api://<api lap id>");
    # this table is a driver-visible summary of the last sync per cohort, not
    # a second dedup mechanism.
    """
    CREATE TABLE garage61_sync_state (
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        laps_seen INTEGER NOT NULL DEFAULT 0,
        laps_new INTEGER NOT NULL DEFAULT 0,
        last_synced_at TEXT,
        PRIMARY KEY (driver, car, track)
    );
    """,
    # 005 — incidents (spins, offs, near-stops): deterministic detection +
    # mechanism characterization, one row per detected event. Not a
    # quality-flag (an incident is a driving event, not a data-quality issue
    # like a clipped pedal); surfaced first-class. Self laps only — reference
    # laps are never scanned into self incident records.
    """
    CREATE TABLE incidents (
        incident_pk INTEGER PRIMARY KEY,
        lap_pk INTEGER NOT NULL REFERENCES laps(lap_pk) ON DELETE CASCADE,
        kinds TEXT NOT NULL,
        classification TEXT NOT NULL,
        confidence TEXT NOT NULL,
        corner_id TEXT,
        span_start INTEGER NOT NULL,
        span_end INTEGER NOT NULL,
        onset INTEGER NOT NULL,
        min_speed_kmh REAL NOT NULL,
        peak_yaw_rate REAL NOT NULL,
        rationale TEXT NOT NULL,
        detail TEXT NOT NULL
    );
    CREATE INDEX idx_incidents_lap ON incidents(lap_pk);
    """,
    # 006 — raw blobs move out of the database and onto local disk (see
    # blobs.py for why). A rename, deliberately not a DROP: an existing
    # database still holds real telemetry here, and losing it would mean
    # re-importing from source CSVs to recover. `driverdna migrate-blobs`
    # drains this table onto disk and empties it; until then
    # `load_lap_arrays` falls back to it, so an un-migrated database keeps
    # working exactly as before.
    """
    ALTER TABLE lap_samples RENAME TO lap_samples_legacy;
    """,
)


def _content_hash(lap: TelemetryLap) -> str:
    """Deterministic fingerprint of a lap's telemetry content.

    Hashes the normalized sample channels (not the file bytes), so the same
    lap re-exported or re-downloaded — different filename, whitespace, or BOM
    — fingerprints identically, while a genuinely different lap does not.
    """
    h = hashlib.sha1()
    for channel in _BLOB_CHANNELS:
        h.update(np.ascontiguousarray(getattr(lap, channel)).tobytes())
    return h.hexdigest()


def _lap_blob(lap: TelemetryLap) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **{c: getattr(lap, c) for c in _BLOB_CHANNELS})
    return buf.getvalue()


def _lap_pk_filter(lap_pks: frozenset[int] | None) -> tuple[str, list[int]]:
    """SQL fragment restricting `laps l` to a lap-pk set — the mechanism M6's
    trend uses to score an earlier vs recent date-bucket over the same
    machinery. None means no restriction (every non-trend caller). An empty
    set matches nothing (an empty bucket honestly has no evidence), not
    everything."""
    if lap_pks is None:
        return "", []
    if not lap_pks:
        # `AND 1=0`, not `AND 0`: a bare integer is not a boolean outside
        # SQLite, and this fragment is on the M6 trend path (an empty bucket).
        return " AND 1=0", []
    ordered = sorted(lap_pks)
    return f" AND l.lap_pk IN ({','.join('?' * len(ordered))})", ordered


def _landmarks_json(landmarks: Landmarks) -> str:
    return json.dumps(asdict(landmarks), sort_keys=True)


def landmark_positions(lap: TelemetryLap, landmarks: Landmarks) -> dict[str, Any]:
    """Landmark lap-distance positions (mod 1) — the compact record canonical
    phase windows are derived from; must survive raw-blob eviction."""

    def pos(idx: int | None) -> float | None:
        return None if idx is None else float(lap.lap_dist[idx]) % 1.0

    data = {k: pos(v) for k, v in asdict(landmarks).items() if k != "apexes"}
    data["apexes"] = [pos(a) for a in landmarks.apexes]
    return data


def landmarks_from_json(text: str) -> Landmarks:
    data = json.loads(text)
    data["apexes"] = tuple(data["apexes"])
    return Landmarks(**data)


class _Conn:
    """Connection proxy: one SQL dialect in, either backend out.

    Exists so the ~28 call sites outside this module that reach through
    `db.conn.execute(...)` keep working untouched. `db.conn` was already a
    de-facto public API across a dozen modules; this makes it an explicit one
    and confines the dialect difference to a single object.

    The context-manager mapping is the part that matters. sqlite3's
    `Connection.__exit__` commits and leaves the connection open; psycopg3's
    commits and **closes** it. There are 19 `with self.conn:` blocks below, so
    delegating naively would close the connection after the first write and
    fail everything after it. Postgres therefore maps `with conn:` onto
    `conn.transaction()`, which has sqlite3's semantics.
    """

    def __init__(self, raw, dialect: "_Dialect"):
        self._raw = raw
        self._dialect = dialect
        self._tx = None

    # --- statement execution ---
    def execute(self, sql: str, params=None):
        sql = self._dialect.sql(sql)
        return self._raw.execute(sql, params) if params is not None else self._raw.execute(sql)

    def executemany(self, sql: str, seq):
        return self._dialect.many(self._raw, self._dialect.sql(sql), list(seq))

    def executescript(self, script: str):
        return self._dialect.script(self._raw, script)

    # --- transactions ---
    def __enter__(self):
        if self._dialect.autocommit:
            self._tx = self._raw.transaction()
            self._tx.__enter__()
        return self

    def __exit__(self, *exc):
        if self._tx is not None:
            tx, self._tx = self._tx, None
            return tx.__exit__(*exc)
        return self._raw.__exit__(*exc)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    @property
    def closed(self) -> bool:
        return bool(getattr(self._raw, "closed", False))

    @property
    def raw(self):
        return self._raw


class _Dialect:
    """What differs between the two backends, and nothing more."""

    name = "sqlite"
    autocommit = False

    def sql(self, sql: str) -> str:
        return sql

    def script(self, raw, script: str):
        return raw.executescript(script)

    def many(self, raw, sql: str, seq):
        return raw.executemany(sql, seq)

    def table_exists_sql(self) -> str:
        return "SELECT name FROM sqlite_master WHERE type='table' AND name=?"

    def migrations(self) -> tuple[str, ...]:
        return MIGRATIONS


class _PostgresDialect(_Dialect):
    name = "postgres"
    # Reads sit outside a transaction and writes inside an explicit one —
    # sqlite3's model. It also keeps connections out of "idle in
    # transaction", which a pooled remote store punishes.
    autocommit = True

    def sql(self, sql: str) -> str:
        return to_pg(sql)

    def script(self, raw, script: str):
        # psycopg runs a multi-statement string in one execute when there are
        # no placeholders; wrap it so a migration applies all-or-nothing.
        with raw.transaction():
            return raw.execute(script)

    def many(self, raw, sql: str, seq):
        # psycopg puts executemany on the cursor, not the connection.
        with raw.cursor() as cur:
            cur.executemany(sql, seq)
        return cur

    def table_exists_sql(self) -> str:
        return (
            "SELECT tablename AS name FROM pg_tables "
            "WHERE tablename=? AND schemaname = ANY(current_schemas(false))"
        )

    def migrations(self) -> tuple[str, ...]:
        return to_pg_migrations(MIGRATIONS)


_SQLITE = _Dialect()
_POSTGRES = _PostgresDialect()

#: Tables live here, never in `public`.
#:
#: Supabase automatically exposes everything in `public` over PostgREST, so a
#: table sitting there without row-level security is readable at
#: https://<project>.supabase.co/rest/v1/<table> by anyone holding the anon
#: key — and that key ships in every Supabase project. `laps`,
#: `chat_transcripts` and `driver_beliefs` in `public` would mean the driver's
#: telemetry and coaching conversations were published to an unauthenticated
#: HTTP endpoint. PostgREST does not expose non-`public` schemas by default,
#: so the namespace alone closes it; RLS below is the second layer.
PG_SCHEMA = "driverdna"

_DEFAULT_SEARCH_PATHS = {'"$user", public', '"$user",public', "public"}


def _namespace_postgres(conn) -> None:
    """Put this connection in the `driverdna` schema.

    Skipped when the DSN already selects a schema — the test harness gives
    each test its own — so an explicit choice is never overridden.
    """
    current = conn.execute("SHOW search_path").fetchone()["search_path"]
    if current.strip() not in _DEFAULT_SEARCH_PATHS:
        return
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{PG_SCHEMA}"')
    conn.execute(f'SET search_path TO "{PG_SCHEMA}"')


class Database:
    """One connection, migrations applied, typed helpers over the schema."""

    def __init__(
        self,
        conn,
        blobs: BlobStore | None = None,
        dialect: _Dialect | None = None,
    ):
        self.dialect = dialect or _SQLITE
        self.conn = conn if isinstance(conn, _Conn) else _Conn(conn, self.dialect)
        self.blobs = blobs if blobs is not None else MemoryBlobStore()
        if self.dialect is _SQLITE:
            conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    @classmethod
    def open(
        cls,
        path: Path | str = ":memory:",
        *,
        check_same_thread: bool = True,
        blob_root: Path | str | None = None,
    ) -> "Database":
        """`check_same_thread=False` is for long-lived connections handed
        across a thread pool (e.g. the UI's per-chat-session connection,
        UI-SPEC decision 5) — sequential access from different threads over
        the connection's life, never truly concurrent, so this is safe;
        every other caller keeps the default thread-affine connection.

        `blob_root` overrides where raw lap blobs are kept; by default they
        sit beside the database (see `blobs.default_blob_root`), so no two
        databases can collide on a lap_pk-keyed filename.

        `path` may also be a `postgresql://` URL, which selects the Postgres
        backend. Raw blobs stay on local disk either way — only the queryable
        rows move.
        """
        blobs = open_blob_store(path, blob_root)
        if is_postgres_url(path):
            conn = cls._connect_postgres(str(path))
            _namespace_postgres(conn)
            database = cls(conn, blobs, _POSTGRES)
            database._harden_postgres()
            return database
        return cls(
            sqlite3.connect(str(path), check_same_thread=check_same_thread),
            blobs,
            _SQLITE,
        )

    @staticmethod
    def _connect_postgres(dsn: str):
        """Imported lazily so a SQLite-only install never needs psycopg —
        the same treatment `anthropic` gets in coach/provider.py."""
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:  # pragma: no cover - install hint
            raise RuntimeError(
                "Postgres support needs psycopg: pip install 'driverdna[pg]'"
            ) from exc

        try:
            return psycopg.connect(
                dsn,
                autocommit=True,
                row_factory=dict_row,
                # psycopg's automatic statement preparation breaks behind a
                # transaction-mode pooler (Supabase port 6543). Off by
                # default so moving between poolers cannot surprise us.
                prepare_threshold=None,
            )
        except Exception as exc:
            raise RuntimeError(f"could not connect to {redact_dsn(dsn)}: {exc}") from None

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _migrate(self) -> None:
        migrations = self.dialect.migrations()
        with self.conn:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = self.conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
            current = row["v"] or 0
            if current >= len(migrations):
                return
        # Each migration is its own transaction: `executescript` commits on
        # SQLite, and on Postgres the dialect wraps the script itself, so the
        # version row is recorded alongside rather than inside that block.
        for i, script in enumerate(migrations[current:], start=current + 1):
            self.conn.executescript(script)
            with self.conn:
                self.conn.execute("INSERT INTO schema_version VALUES (?)", (i,))

    def _harden_postgres(self) -> None:
        """Enable row-level security, with no policies, on every table.

        The second layer behind the `driverdna` namespace. RLS with zero
        policies denies every role except the table owner (which this
        connection is) and superusers — so if a future change ever exposed
        these tables through PostgREST, Supabase's `anon` and `authenticated`
        roles would still read nothing rather than everything.

        Runs on connect, so it costs one catalogue query in the steady state
        and issues ALTERs only for tables that are actually unprotected —
        `Database.open` happens per request in the UI, and 17 unconditional
        ALTERs there would be a real cost for no work.
        """
        rows = self.conn.execute(
            """SELECT tablename FROM pg_tables
               WHERE schemaname = current_schema() AND NOT rowsecurity
               ORDER BY tablename"""
        ).fetchall()
        for row in rows:
            table = row["tablename"]
            self.conn.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')

    def _insert_returning(self, sql: str, params: tuple, pk_col: str) -> int:
        """Run an INSERT and return the affected row's primary key.

        `RETURNING` rather than `cursor.lastrowid` for two reasons: it is the
        portable spelling, and it is the *correct* one for an upsert —
        `lastrowid` is only meaningful on the INSERT path, so an
        `ON CONFLICT ... DO UPDATE` that takes the UPDATE path leaves it
        holding a stale value. Requires SQLite >= 3.35 (2021); the project
        already requires Python >= 3.11.
        """
        row = self.conn.execute(f"{sql} RETURNING {pk_col}", params).fetchone()
        return int(row[pk_col])

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
        return int(row["v"] or 0)

    # --- laps --------------------------------------------------------------

    def import_lap(
        self,
        lap: TelemetryLap,
        *,
        driver: str,
        car: str,
        track: str,
        role: str = "self",
        session_key: str | None = None,
        run_index: int | None = None,
        imported_at: str | None = None,
        lap_date: str | None = None,
    ) -> tuple[int, str]:
        """Store lap row + raw blob. Returns (lap_pk, status).

        status is one of:
          "imported"  — a new lap was stored.
          "exists"    — this exact source file was already imported (no-op).
          "duplicate" — the telemetry is byte-identical to an already-stored
                        lap under a different filename (e.g. a re-download);
                        NOT stored, so it can't double-count in self history.

        Nothing is silently overwritten or silently merged; the caller
        surfaces "exists"/"duplicate" to the driver.
        """
        existing = self.conn.execute(
            "SELECT lap_pk FROM laps WHERE source_file = ?", (str(lap.source_path),)
        ).fetchone()
        if existing:
            return int(existing["lap_pk"]), "exists"

        content_hash = _content_hash(lap)
        dup = self.conn.execute(
            "SELECT lap_pk FROM laps WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if dup:
            return int(dup["lap_pk"]), "duplicate"

        flags = json.dumps(
            [{"code": str(f.code), "detail": f.detail} for f in lap.quality_flags],
            sort_keys=True,
        )
        with self.conn:
            lap_pk = self._insert_returning(
                """INSERT INTO laps (lap_id, source_file, driver, car, track, role,
                                     session_key, run_index, n_samples, duration_s,
                                     imported_at, quality_flags, content_hash, lap_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lap.lap_id, str(lap.source_path), driver, car, track, role,
                    session_key, run_index, lap.n_samples, lap.duration_s, imported_at,
                    flags, content_hash, lap_date,
                ),
                "lap_pk",
            )
        # Outside the transaction: the blob is a file now, so it cannot join
        # the row's atomicity. Written after the commit so a failed insert can
        # never leave an orphan blob; a failed write after a committed row is
        # simply a lap whose raw trace is unavailable — the state retention
        # produces anyway, and which every reader already handles.
        self.blobs.put(lap_pk, _lap_blob(lap))
        return lap_pk, "imported"

    def load_lap_arrays(self, lap_pk: int) -> dict[str, np.ndarray] | None:
        """Raw samples for a lap, or None when they are not available here.

        None is a normal answer, not an error: the blob may have been evicted
        by retention, or the lap may have been imported on another machine.
        Callers already degrade honestly on it.
        """
        data = self.blobs.get(lap_pk)
        if data is None:
            data = self._legacy_blob(lap_pk)
        if data is None:
            return None
        with np.load(io.BytesIO(data)) as npz:
            return {name: npz[name] for name in npz.files}

    def _legacy_blob(self, lap_pk: int) -> bytes | None:
        """Read a blob still sitting in the pre-migration-006 `lap_samples`
        table. Kept so upgrading never silently loses raw traces; `driverdna
        migrate-blobs` drains it and the fallback then costs nothing."""
        if not self._has_legacy_blobs():
            return None
        row = self.conn.execute(
            "SELECT data FROM lap_samples_legacy WHERE lap_pk = ?", (lap_pk,)
        ).fetchone()
        return row["data"] if row is not None else None

    def _has_legacy_blobs(self) -> bool:
        if getattr(self, "_legacy_checked", None) is None:
            row = self.conn.execute(
                self.dialect.table_exists_sql(), ("lap_samples_legacy",)
            ).fetchone()
            self._legacy_checked = row is not None
        return bool(self._legacy_checked)

    def has_raw(self, lap_pk: int) -> bool:
        """Whether this lap's raw trace is readable on this machine."""
        return self.blobs.has(lap_pk) or self._legacy_blob(lap_pk) is not None

    def unavailable_raw_laps(self, lap_pks: Iterable[int]) -> list[int]:
        """Of `lap_pks`, those whose raw trace is missing *and* was never
        evicted here — i.e. imported on another machine, still intact there.

        An evicted lap is deliberately excluded: its trace is gone for good,
        so a caller that needs raw samples cannot ever get them and should
        proceed on that basis. One that is merely absent here is a different
        situation entirely, and destroying measurements derived from it would
        throw away what another machine can still reproduce (SPEC.md A26).
        """
        evicted = self.blobs.evicted_lap_pks()
        return sorted(
            int(pk) for pk in lap_pks
            if int(pk) not in evicted and not self.has_raw(int(pk))
        )

    def enforce_retention(self, keep: int) -> int:
        """Evict raw blobs beyond the newest `keep` laps per cohort.

        Only blobs are removed; laps, observations, metrics, and detector
        rows — everything trends are built from — are untouched. Returns the
        number of blobs evicted.

        The eviction set is still chosen by the same per-cohort ranking, but
        applied to the blob store rather than to a table, so the filesystem
        is the single source of truth for what raw data exists and no pointer
        row can drift out of step with it.
        """
        held = self.blobs.lap_pks()
        if self._has_legacy_blobs():
            held |= {
                int(r["lap_pk"])
                for r in self.conn.execute("SELECT lap_pk FROM lap_samples_legacy")
            }
        if not held:
            return 0

        seen: dict[tuple[str, str, str], int] = {}
        evicted = 0
        for r in self.conn.execute(
            """SELECT lap_pk, driver, car, track FROM laps
               ORDER BY driver, car, track, lap_pk DESC"""
        ):
            lap_pk = int(r["lap_pk"])
            if lap_pk not in held:
                continue
            cohort = (r["driver"], r["car"], r["track"])
            seen[cohort] = seen.get(cohort, 0) + 1
            if seen[cohort] > keep:
                self.blobs.delete(lap_pk)
                # Tombstone the eviction: "gone deliberately, here" has to
                # stay distinguishable from "never arrived here", or
                # `rebuild-map` cannot tell a permanently unmeasurable lap
                # from one whose blob is intact on another machine (A26).
                self.blobs.mark_evicted(lap_pk)
                if self._has_legacy_blobs():
                    with self.conn:
                        self.conn.execute(
                            "DELETE FROM lap_samples_legacy WHERE lap_pk = ?", (lap_pk,)
                        )
                evicted += 1
        return evicted

    def drain_legacy_blobs(self) -> int:
        """Move any pre-migration-006 blobs out of the database and onto disk.

        Idempotent, and non-destructive until every blob has been written:
        rows are deleted only after their file exists.
        """
        if not self._has_legacy_blobs():
            return 0
        moved = 0
        for r in self.conn.execute(
            "SELECT lap_pk, data FROM lap_samples_legacy ORDER BY lap_pk"
        ).fetchall():
            lap_pk = int(r["lap_pk"])
            if not self.blobs.has(lap_pk):
                self.blobs.put(lap_pk, r["data"])
            moved += 1
        with self.conn:
            self.conn.execute("DELETE FROM lap_samples_legacy")
        return moved

    # --- corner maps -------------------------------------------------------

    def store_corner_map(
        self, corner_map: CornerMap, *, car: str, track: str,
        built_from_n_laps: int,
    ) -> int:
        """Corner maps are keyed by (car, track) — NOT driver — so reference
        laps from other drivers share the owner's corner identities; gap
        analysis joins on them."""
        with self.conn:
            map_pk = self._insert_returning(
                """INSERT INTO corner_maps (car, track, built_from_n_laps)
                   VALUES (?, ?, ?)""",
                (car, track, built_from_n_laps),
                "map_pk",
            )
            for c in corner_map.corners:
                self.conn.execute(
                    """INSERT INTO corners (map_pk, corner_id, lat, lon, lap_dist,
                                            n_build_observations)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (map_pk, c.corner_id, c.lat, c.lon, c.lap_dist,
                     c.n_build_observations),
                )
        return map_pk

    def load_corner_map(self, *, car: str, track: str) -> tuple[int, CornerMap] | None:
        row = self.conn.execute(
            "SELECT map_pk FROM corner_maps WHERE car=? AND track=?",
            (car, track),
        ).fetchone()
        if row is None:
            return None
        map_pk = int(row["map_pk"])
        corners = tuple(
            CornerIdentity(
                corner_id=r["corner_id"], lat=r["lat"], lon=r["lon"],
                lap_dist=r["lap_dist"],
                n_build_observations=r["n_build_observations"],
            )
            for r in self.conn.execute(
                "SELECT * FROM corners WHERE map_pk=? ORDER BY corner_id", (map_pk,)
            )
        )
        return map_pk, CornerMap(corners=corners)

    def corner_pk(self, map_pk: int, corner_id: str) -> int:
        row = self.conn.execute(
            "SELECT corner_pk FROM corners WHERE map_pk=? AND corner_id=?",
            (map_pk, corner_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"no corner {corner_id} in map {map_pk}")
        return int(row["corner_pk"])

    def set_corner_class(self, corner_pk: int, cls: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE corners SET class=? WHERE corner_pk=?", (cls, corner_pk)
            )

    def corner_apex_positions(
        self, corner_pk: int
    ) -> list[tuple[float, float, float]]:
        """(apex_lat, apex_lon, apex_lap_dist) for every observation currently
        assigned to this corner — the input to an in-place centroid refreeze
        (`rebuild-map`). Compact rows only; survives blob eviction."""
        rows = self.conn.execute(
            """SELECT apex_lat, apex_lon, apex_lap_dist FROM corner_observations
               WHERE corner_pk=? ORDER BY obs_pk""",
            (corner_pk,),
        ).fetchall()
        return [
            (float(r["apex_lat"]), float(r["apex_lon"]), float(r["apex_lap_dist"]))
            for r in rows
        ]

    def update_corner_centroid(
        self, corner_pk: int, *, lat: float, lon: float, lap_dist: float
    ) -> None:
        """Overwrite a corner's frozen centroid in place (`rebuild-map`); the
        corner_pk and corner_id never change, so every evidence ID that
        resolves through this corner stays valid."""
        with self.conn:
            self.conn.execute(
                "UPDATE corners SET lat=?, lon=?, lap_dist=? WHERE corner_pk=?",
                (lat, lon, lap_dist, corner_pk),
            )

    def observations_of_corner(self, corner_pk: int) -> list[tuple[int, int]]:
        """(obs_pk, lap_pk) for every observation assigned to this corner."""
        rows = self.conn.execute(
            "SELECT obs_pk, lap_pk FROM corner_observations WHERE corner_pk=? ORDER BY obs_pk",
            (corner_pk,),
        ).fetchall()
        return [(int(r["obs_pk"]), int(r["lap_pk"])) for r in rows]

    def delete_phase_times(self, obs_pk: int) -> None:
        """Drop an observation's phase times (`rebuild-map`, when a lap's raw
        blob was evicted so its phase times can't be honestly re-interpolated
        against the new windows — never left silently stale)."""
        with self.conn:
            self.conn.execute("DELETE FROM phase_times WHERE obs_pk=?", (obs_pk,))

    # --- observations, metrics, detectors ----------------------------------

    def store_observation(
        self,
        *,
        lap: TelemetryLap,
        lap_pk: int,
        span: CornerSpan,
        corner_pk: int | None,
        metrics: dict[str, float | None],
        detector_results: list[Any],
    ) -> int:
        apex = span.landmarks.apex
        with self.conn:
            obs_pk = self._insert_returning(
                """INSERT INTO corner_observations
                   (lap_pk, corner_pk, span_start, span_end, landmarks,
                    landmark_positions, apex_lat, apex_lon, apex_lap_dist,
                    min_speed_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lap_pk, corner_pk, span.start, span.end,
                    _landmarks_json(span.landmarks),
                    json.dumps(landmark_positions(lap, span.landmarks), sort_keys=True),
                    float(lap.lat[apex]), float(lap.lon[apex]),
                    float(lap.lap_dist[apex]) % 1.0, span.min_speed(lap),
                ),
                "obs_pk",
            )
            self.conn.executemany(
                "INSERT INTO metric_values (obs_pk, name, value) VALUES (?, ?, ?)",
                [(obs_pk, name, value) for name, value in sorted(metrics.items())],
            )
            self.conn.executemany(
                """INSERT INTO detector_results
                   (obs_pk, detector, triggered, value, threshold, unit, rationale)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (obs_pk, r.detector, int(r.triggered), r.value, r.threshold,
                     r.unit, r.rationale)
                    for r in detector_results
                ],
            )
        return obs_pk

    def self_metric_history(
        self, *, driver: str, car: str, track: str, corner_id: str, metric: str
    ) -> list[float]:
        """Per-lap values for one metric on one corner — role='self' ONLY.

        This is the single gate through which trends and consistency see
        data; reference laps are excluded here, not in each caller.
        """
        rows = self.conn.execute(
            """SELECT mv.value FROM metric_values mv
               JOIN corner_observations o ON o.obs_pk = mv.obs_pk
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN corner_maps m ON m.map_pk = c.map_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE l.role = 'self' AND l.driver=? AND l.car=? AND l.track=?
                 AND c.corner_id=? AND mv.name=? AND mv.value IS NOT NULL
               ORDER BY l.lap_pk, o.span_start""",
            (driver, car, track, corner_id, metric),
        ).fetchall()
        return [float(r["value"]) for r in rows]

    # --- canonical windows and phase times ----------------------------------

    def store_corner_windows(
        self, corner_pk: int, *, entry_start: float | None, turn_in: float | None,
        apex: float, exit_end: float | None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO corner_windows
                   (corner_pk, entry_start, turn_in, apex, exit_end)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (corner_pk) DO UPDATE SET
                       entry_start = excluded.entry_start,
                       turn_in     = excluded.turn_in,
                       apex        = excluded.apex,
                       exit_end    = excluded.exit_end""",
                (corner_pk, entry_start, turn_in, apex, exit_end),
            )

    def load_corner_windows(self, map_pk: int) -> dict[str, dict[str, float | None]]:
        rows = self.conn.execute(
            """SELECT c.corner_id, w.entry_start, w.turn_in, w.apex, w.exit_end
               FROM corner_windows w JOIN corners c ON c.corner_pk = w.corner_pk
               WHERE c.map_pk = ? ORDER BY c.corner_id""",
            (map_pk,),
        ).fetchall()
        return {
            r["corner_id"]: {
                "entry_start": r["entry_start"], "turn_in": r["turn_in"],
                "apex": r["apex"], "exit_end": r["exit_end"],
            }
            for r in rows
        }

    def store_phase_times(self, obs_pk: int, times: dict[str, float]) -> None:
        with self.conn:
            self.conn.executemany(
                """INSERT INTO phase_times (obs_pk, phase, time_s) VALUES (?, ?, ?)
                   ON CONFLICT (obs_pk, phase) DO UPDATE SET time_s = excluded.time_s""",
                [(obs_pk, phase, t) for phase, t in sorted(times.items())],
            )

    def phase_history(
        self, *, car: str, track: str, corner_id: str, phase: str, role: str,
        driver: str | None = None, lap_pks: frozenset[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Per-lap phase times for one corner, filtered by role.

        role='self' additionally requires driver (self history is one
        driver's); role='reference' aggregates all reference drivers.
        `lap_pks` (M6 trend only) further restricts to a date-bucket's laps.
        """
        if role == "self" and driver is None:
            raise ValueError("self phase history requires a driver")
        clause = "AND l.driver = ?" if driver is not None else ""
        pk_clause, pk_params = _lap_pk_filter(lap_pks)
        params = (
            [car, track, corner_id, phase, role]
            + ([driver] if driver else [])
            + pk_params
        )
        rows = self.conn.execute(
            f"""SELECT p.time_s, l.lap_pk, l.session_key, o.obs_pk
                FROM phase_times p
                JOIN corner_observations o ON o.obs_pk = p.obs_pk
                JOIN corners c ON c.corner_pk = o.corner_pk
                JOIN laps l ON l.lap_pk = o.lap_pk
                WHERE l.car=? AND l.track=? AND c.corner_id=? AND p.phase=?
                  AND l.role=? {clause}{pk_clause}
                ORDER BY l.lap_pk, o.span_start""",
            params,
        ).fetchall()
        return [
            {"time_s": float(r["time_s"]), "lap_pk": int(r["lap_pk"]),
             "session_key": r["session_key"], "obs_pk": int(r["obs_pk"])}
            for r in rows
        ]

    def observation_positions(self, corner_pk: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT landmark_positions FROM corner_observations WHERE corner_pk=? ORDER BY obs_pk",
            (corner_pk,),
        ).fetchall()
        return [json.loads(r["landmark_positions"]) for r in rows]

    def self_metric_table(
        self, *, driver: str, car: str, track: str,
        lap_pks: frozenset[int] | None = None,
    ) -> dict[str, dict[str, list[float]]]:
        """{corner_id: {metric: per-lap values}} — role='self' only.
        `lap_pks` (M6 trend only) restricts to a date-bucket's laps."""
        pk_clause, pk_params = _lap_pk_filter(lap_pks)
        rows = self.conn.execute(
            f"""SELECT c.corner_id, mv.name, mv.value FROM metric_values mv
               JOIN corner_observations o ON o.obs_pk = mv.obs_pk
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
                 AND mv.value IS NOT NULL{pk_clause}
               ORDER BY c.corner_id, mv.name, l.lap_pk, o.span_start""",
            [driver, car, track, *pk_params],
        ).fetchall()
        table: dict[str, dict[str, list[float]]] = {}
        for r in rows:
            table.setdefault(r["corner_id"], {}).setdefault(r["name"], []).append(
                float(r["value"])
            )
        return table

    def self_detector_table(
        self, *, driver: str, car: str, track: str,
        lap_pks: frozenset[int] | None = None,
    ) -> dict[str, dict[str, tuple[int, int]]]:
        """{corner_id: {detector: (triggered, total)}} — role='self' only.
        `lap_pks` (M6 trend only) restricts to a date-bucket's laps."""
        pk_clause, pk_params = _lap_pk_filter(lap_pks)
        rows = self.conn.execute(
            f"""SELECT c.corner_id, d.detector,
                      SUM(d.triggered) AS trig, COUNT(*) AS total
               FROM detector_results d
               JOIN corner_observations o ON o.obs_pk = d.obs_pk
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?{pk_clause}
               GROUP BY c.corner_id, d.detector
               ORDER BY c.corner_id, d.detector""",
            [driver, car, track, *pk_params],
        ).fetchall()
        table: dict[str, dict[str, tuple[int, int]]] = {}
        for r in rows:
            table.setdefault(r["corner_id"], {})[r["detector"]] = (
                int(r["trig"]), int(r["total"])
            )
        return table

    def corner_classes(self, *, car: str, track: str) -> dict[str, str | None]:
        loaded = self.load_corner_map(car=car, track=track)
        if loaded is None:
            return {}
        map_pk, _ = loaded
        return {
            r["corner_id"]: r["class"]
            for r in self.conn.execute(
                "SELECT corner_id, class FROM corners WHERE map_pk=? ORDER BY corner_id",
                (map_pk,),
            )
        }

    def corner_positions(self, *, car: str, track: str) -> dict[str, float]:
        """corner_id -> apex lap-distance fraction (0-1) from the frozen map;
        used to label an incident's location."""
        loaded = self.load_corner_map(car=car, track=track)
        if loaded is None:
            return {}
        map_pk, _ = loaded
        # ORDER BY is load-bearing, not cosmetic: `_corner_at` picks the
        # nearest corner with `min()`, which returns the *first* minimum, so
        # on a distance tie the label is decided by row order — and that
        # label is persisted into incidents.corner_id. Ordering by corner_id
        # makes the tie-break stated rather than inherited from storage
        # (`corner_classes` below already does this).
        return {
            r["corner_id"]: float(r["lap_dist"])
            for r in self.conn.execute(
                "SELECT corner_id, lap_dist FROM corners WHERE map_pk=? ORDER BY corner_id",
                (map_pk,),
            )
        }

    # --- incidents ----------------------------------------------------------

    def store_incidents(self, lap_pk: int, incidents: list) -> None:
        """Persist detected incidents for one lap. Deterministic order
        (by span start) so two imports produce identical rows.

        The sample indices are cast to plain `int` deliberately. They arrive
        as numpy int64 from array arithmetic, and sqlite3 has no adapter for
        that type — it stored the raw little-endian bytes into an INTEGER
        column instead, which SQLite's dynamic typing accepts silently. That
        left `span_start`/`span_end`/`onset` holding BLOBs, which sort after
        every integer (so `ORDER BY i.span_start` was subtly wrong) and which
        a strictly-typed store rejects outright.
        """
        with self.conn:
            for inc in sorted(incidents, key=lambda i: i.span_start):
                self.conn.execute(
                    """INSERT INTO incidents (lap_pk, kinds, classification, confidence,
                        corner_id, span_start, span_end, onset, min_speed_kmh,
                        peak_yaw_rate, rationale, detail)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        lap_pk, "+".join(inc.kinds), inc.classification, inc.confidence,
                        inc.corner_id, int(inc.span_start), int(inc.span_end),
                        int(inc.onset),
                        float(inc.min_speed_kmh), float(inc.peak_yaw_rate),
                        inc.rationale,
                        json.dumps(inc.detail, sort_keys=True),
                    ),
                )

    def incidents_for_cohort(self, *, driver: str, car: str, track: str) -> list[dict]:
        """All incidents for a cohort's self laps, newest-driven first then
        by position, each with its lap_id for evidence. Deterministic."""
        return [
            {
                "incident_id": f"incident:{r['incident_pk']}",
                "lap_id": r["lap_id"],
                "lap_pk": r["lap_pk"],
                "kinds": r["kinds"],
                "classification": r["classification"],
                "confidence": r["confidence"],
                "corner_id": r["corner_id"],
                "min_speed_kmh": r["min_speed_kmh"],
                "peak_yaw_rate": r["peak_yaw_rate"],
                "rationale": r["rationale"],
                "detail": json.loads(r["detail"]),
            }
            for r in self.conn.execute(
                """SELECT i.*, l.lap_id FROM incidents i JOIN laps l ON l.lap_pk=i.lap_pk
                   WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
                   ORDER BY i.corner_id IS NULL, i.corner_id, i.span_start, i.incident_pk""",
                (driver, car, track),
            )
        ]

    def incident_counts_by_lap(self, lap_pks: list[int]) -> dict[int, int]:
        """lap_pk -> incident count, for the laps view."""
        if not lap_pks:
            return {}
        marks = ",".join("?" * len(lap_pks))
        return {
            r["lap_pk"]: r["n"]
            for r in self.conn.execute(
                f"SELECT lap_pk, COUNT(*) n FROM incidents WHERE lap_pk IN ({marks}) GROUP BY lap_pk",
                lap_pks,
            )
        }

    # --- candidate admission ------------------------------------------------

    def admit_pending_candidates(
        self, *, car: str, track: str, cfg: IdentityConfig
    ) -> list[str]:
        """Admit consistently-unmatched corners to the frozen map.

        Clusters unmatched observations in the cohort; a cluster seen on at
        least cfg.min_laps_for_admission DISTINCT laps becomes a new corner
        with the next ID (existing IDs never renumber). Re-links the
        observations and returns the admitted corner IDs — the caller must
        surface them; the map never changes silently.
        """
        loaded = self.load_corner_map(car=car, track=track)
        if loaded is None:
            return []
        map_pk, corner_map = loaded

        rows = self.conn.execute(
            """SELECT o.obs_pk, o.apex_lat, o.apex_lon, o.apex_lap_dist, o.lap_pk
               FROM corner_observations o JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE o.corner_pk IS NULL AND l.car=? AND l.track=?
               ORDER BY o.obs_pk""",
            (car, track),
        ).fetchall()
        clusters: list[dict[str, Any]] = []
        for r in rows:
            best = None
            best_d = math.inf
            for cl in clusters:
                if _gps_ok(r["apex_lat"], r["apex_lon"]) and _gps_ok(cl["lat"], cl["lon"]):
                    d = _meters(r["apex_lat"], r["apex_lon"], cl["lat"], cl["lon"])
                    ok = d <= cfg.match_radius_m
                else:
                    d = abs(r["apex_lap_dist"] - cl["lap_dist"])
                    d = min(d, 1.0 - d)
                    ok = d <= cfg.dist_pct_fallback_radius
                if ok and d < best_d:
                    best, best_d = cl, d
            if best is None:
                clusters.append(
                    {"lat": r["apex_lat"], "lon": r["apex_lon"],
                     "lap_dist": r["apex_lap_dist"], "obs": [r]}
                )
            else:
                best["obs"].append(r)

        admitted: list[str] = []
        next_num = 1 + max(
            (int(c.corner_id[1:]) for c in corner_map.corners), default=0
        )
        with self.conn:
            for cl in clusters:
                lap_pks = {r["lap_pk"] for r in cl["obs"]}
                if len(lap_pks) < cfg.min_laps_for_admission:
                    continue
                corner_id = f"C{next_num:02d}"
                next_num += 1
                new_pk = self._insert_returning(
                    """INSERT INTO corners (map_pk, corner_id, lat, lon, lap_dist,
                                            n_build_observations)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (map_pk, corner_id,
                     float(np.median([r["apex_lat"] for r in cl["obs"]])),
                     float(np.median([r["apex_lon"] for r in cl["obs"]])),
                     float(np.median([r["apex_lap_dist"] for r in cl["obs"]])),
                     len(cl["obs"])),
                    "corner_pk",
                )
                self.conn.executemany(
                    "UPDATE corner_observations SET corner_pk=? WHERE obs_pk=?",
                    [(new_pk, r["obs_pk"]) for r in cl["obs"]],
                )
                admitted.append(corner_id)
        return admitted

    # --- coach outputs ------------------------------------------------------

    def store_coach_output(
        self, *, driver: str, car: str, track: str, payload_version: int,
        prompt_version: str, model: str, output_json: str,
        created_at: str | None = None,
    ) -> int:
        with self.conn:
            return self._insert_returning(
                """INSERT INTO coach_outputs
                   (driver, car, track, payload_version, prompt_version, model,
                    output_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (driver, car, track, payload_version, prompt_version, model,
                 output_json, created_at),
                "output_pk",
            )

    def coach_history(self, *, driver: str, car: str, track: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT output_pk, output_json FROM coach_outputs
               WHERE driver=? AND car=? AND track=? ORDER BY output_pk""",
            (driver, car, track),
        ).fetchall()
        history = []
        for r in rows:
            output = json.loads(r["output_json"])
            history.append({
                "output_pk": int(r["output_pk"]),
                "plan_titles": [p.get("title") for p in output.get("coaching_plan", [])],
            })
        return history

    # --- annotations and chat transcripts -----------------------------------

    def annotate_finding(
        self, *, finding_id: str, status: str, note: str | None = None,
        created_at: str | None = None,
    ) -> int:
        """Record driver intent about a finding. Suppresses it from priority
        framing; the underlying measurement is never deleted.

        Re-annotating a finding updates the existing row in place. The older
        `INSERT OR REPLACE` deleted and reinserted it, silently renumbering
        `annotation_pk`; keeping the pk stable is both portable and closer to
        what "the measurement is never deleted" already promises.
        """
        with self.conn:
            return self._insert_returning(
                """INSERT INTO finding_annotations
                   (finding_id, status, note, created_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT (finding_id) DO UPDATE SET
                       status     = excluded.status,
                       note       = excluded.note,
                       created_at = excluded.created_at""",
                (finding_id, status, note, created_at),
                "annotation_pk",
            )

    def annotations(self) -> dict[str, dict[str, Any]]:
        return {
            r["finding_id"]: {"status": r["status"], "note": r["note"]}
            for r in self.conn.execute(
                "SELECT * FROM finding_annotations ORDER BY finding_id"
            )
        }

    def clear_annotation(self, finding_id: str) -> None:
        """Remove a finding's annotation (never touches the measurement)."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM finding_annotations WHERE finding_id = ?", (finding_id,)
            )

    def add_chat_turn(
        self, *, session_id: str, bundle_version: int, role: str, content: str,
        evidence_cited: list[str] | None = None,
        effects: dict[str, Any] | None = None,
    ) -> int:
        with self.conn:
            return self._insert_returning(
                """INSERT INTO chat_transcripts
                   (session_id, bundle_version, role, content, evidence_cited, effects)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id, bundle_version, role, content,
                    json.dumps(evidence_cited or [], sort_keys=True),
                    json.dumps(effects or {}, sort_keys=True),
                ),
                "turn_pk",
            )

    def chat_session_turns(self, session_id: str) -> list[dict[str, Any]]:
        return [
            {
                "role": r["role"], "content": r["content"],
                "bundle_version": int(r["bundle_version"]),
                "evidence_cited": json.loads(r["evidence_cited"] or "[]"),
                "effects": json.loads(r["effects"] or "{}"),
            }
            for r in self.conn.execute(
                "SELECT * FROM chat_transcripts WHERE session_id=? ORDER BY turn_pk",
                (session_id,),
            )
        ]

    # --- config history -----------------------------------------------------

    def record_config_change(
        self, *, key: str, old_value: str | None, new_value: str, source: str,
        note: str | None = None,
    ) -> int:
        with self.conn:
            return self._insert_returning(
                """INSERT INTO config_history (key, old_value, new_value, source, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, old_value, new_value, source, note),
                "change_pk",
            )

    # --- driver model (M6) ---------------------------------------------------

    def store_belief(
        self, *, driver: str, fundamental: str, signal_status: str,
        score: float | None, confidence: float, evidence_count: int, trend: str,
        insufficient_reason: str | None, scoring_model_version: str,
        taxonomy_version: str, computed_at: str | None = None,
    ) -> int:
        """Upsert the current belief for (driver, fundamental, model version).

        Recomputation always replaces the prior row for the same model
        version — beliefs are a live, recomputed-at-import projection of the
        evidence, not an append-only history. A version bump leaves the OLD
        version's row alone (still queryable) and creates a new one.
        """
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO driver_beliefs
                   (driver, fundamental, signal_status, score, confidence,
                    evidence_count, trend, insufficient_reason,
                    scoring_model_version, taxonomy_version, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (driver, fundamental, scoring_model_version)
                   DO UPDATE SET
                       signal_status=excluded.signal_status,
                       score=excluded.score,
                       confidence=excluded.confidence,
                       evidence_count=excluded.evidence_count,
                       trend=excluded.trend,
                       insufficient_reason=excluded.insufficient_reason,
                       taxonomy_version=excluded.taxonomy_version,
                       computed_at=excluded.computed_at""",
                (driver, fundamental, signal_status, score, confidence,
                 evidence_count, trend, insufficient_reason,
                 scoring_model_version, taxonomy_version, computed_at),
            )
        row = self.conn.execute(
            """SELECT belief_pk FROM driver_beliefs
               WHERE driver=? AND fundamental=? AND scoring_model_version=?""",
            (driver, fundamental, scoring_model_version),
        ).fetchone()
        return int(row["belief_pk"])

    def load_beliefs(
        self, *, driver: str, scoring_model_version: str
    ) -> dict[str, dict[str, Any]]:
        """{fundamental: belief dict} for one driver at one model version."""
        rows = self.conn.execute(
            """SELECT * FROM driver_beliefs
               WHERE driver=? AND scoring_model_version=?
               ORDER BY fundamental""",
            (driver, scoring_model_version),
        ).fetchall()
        return {r["fundamental"]: dict(r) for r in rows}

    def driver_session_count(self, driver: str) -> int:
        row = self.conn.execute(
            """SELECT COUNT(DISTINCT session_key) n FROM laps
               WHERE role='self' AND driver=? AND session_key IS NOT NULL""",
            (driver,),
        ).fetchone()
        return int(row["n"])

    def fundamental_evidence_lap_count(
        self, *, driver: str, metric_names: tuple[str, ...],
        detector_names: tuple[str, ...],
    ) -> int:
        """Distinct self-role laps that contributed >=1 metric value or
        detector result relevant to a fundamental's mapped techniques — the
        driver-facing "how many of your laps taught me something" count.
        Empty metric/detector sets (e.g. vision) return 0, honestly.
        """
        if not metric_names and not detector_names:
            return 0
        clauses, params = [], []
        if metric_names:
            placeholders = ",".join("?" * len(metric_names))
            clauses.append(
                f"""o.obs_pk IN (SELECT obs_pk FROM metric_values
                     WHERE name IN ({placeholders}) AND value IS NOT NULL)"""
            )
            params.extend(metric_names)
        if detector_names:
            placeholders = ",".join("?" * len(detector_names))
            clauses.append(
                f"""o.obs_pk IN (SELECT obs_pk FROM detector_results
                     WHERE detector IN ({placeholders}))"""
            )
            params.extend(detector_names)
        row = self.conn.execute(
            f"""SELECT COUNT(DISTINCT o.lap_pk) n FROM corner_observations o
                JOIN laps l ON l.lap_pk = o.lap_pk
                WHERE l.role='self' AND l.driver=? AND ({' OR '.join(clauses)})""",
            [driver, *params],
        ).fetchone()
        return int(row["n"])

    def driver_dated_lap_count(self, driver: str) -> int:
        """Self-role laps with a real lap_date — the trend-availability
        check. `sync` (M0b+) is the first ingestion path that sets it (from
        the API's startTime)."""
        row = self.conn.execute(
            """SELECT COUNT(*) n FROM laps
               WHERE role='self' AND driver=? AND lap_date IS NOT NULL""",
            (driver,),
        ).fetchone()
        return int(row["n"])

    def dated_self_lap_pks(self, driver: str) -> list[int]:
        """Self-role lap_pks that carry a lap_date, ordered by (lap_date,
        lap_pk) — M6 trend's time axis. lap_pk breaks date ties into a total,
        deterministic order (the Scoring Contract's 'explicitly ordered by
        lap timestamp'). Undated laps are excluded: they can't be placed on
        the timeline, so they never enter a trend bucket."""
        rows = self.conn.execute(
            """SELECT lap_pk FROM laps
               WHERE role='self' AND driver=? AND lap_date IS NOT NULL
               ORDER BY lap_date, lap_pk""",
            (driver,),
        ).fetchall()
        return [int(r["lap_pk"]) for r in rows]

    # --- garage61 sync state (M0b+) ------------------------------------------

    def record_sync_state(
        self, *, driver: str, car: str, track: str, laps_seen: int, laps_new: int,
        synced_at: str | None = None,
    ) -> None:
        """Upsert the last-sync summary for one (driver, car, track) cohort.

        Not a dedup mechanism — that's the existing source_file/content_hash
        checks in import_lap — this is just a driver-visible "what did the
        last sync do" record.
        """
        with self.conn:
            self.conn.execute(
                """INSERT INTO garage61_sync_state
                   (driver, car, track, laps_seen, laps_new, last_synced_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (driver, car, track) DO UPDATE SET
                       laps_seen=excluded.laps_seen,
                       laps_new=excluded.laps_new,
                       last_synced_at=excluded.last_synced_at""",
                (driver, car, track, laps_seen, laps_new, synced_at),
            )

    def sync_states(self, driver: str) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.conn.execute(
                """SELECT * FROM garage61_sync_state WHERE driver=?
                   ORDER BY car, track""",
                (driver,),
            )
        ]
