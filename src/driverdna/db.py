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
    # 007 — performance indexes on hot-path columns
    #
    # Landed on main first via PR #10 (Issue 1's DB-performance fix). Kept
    # as its own migration rather than folded into 008 below, so a database
    # migrated from either branch's history ends up in the same state at
    # each step, not just at the end.
    """
    CREATE INDEX IF NOT EXISTS idx_laps_cohort ON laps(driver, car, track, role);
    CREATE INDEX IF NOT EXISTS idx_corner_obs_lap ON corner_observations(lap_pk);
    CREATE INDEX IF NOT EXISTS idx_corner_obs_corner ON corner_observations(corner_pk);
    CREATE INDEX IF NOT EXISTS idx_metric_values_obs ON metric_values(obs_pk);
    CREATE INDEX IF NOT EXISTS idx_detector_results_obs ON detector_results(obs_pk);
    CREATE INDEX IF NOT EXISTS idx_phase_times_obs ON phase_times(obs_pk);
    CREATE INDEX IF NOT EXISTS idx_corners_map ON corners(map_pk);
    """,
    # 008 — Identity Core (Phase 1)
    """
    CREATE TABLE users (
        user_pk INTEGER PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT ''
    );
    INSERT INTO users (email, password_hash) VALUES ('owner@example.com', 'placeholder');

    CREATE TABLE password_resets (
        token TEXT PRIMARY KEY,
        user_pk INTEGER NOT NULL REFERENCES users(user_pk),
        expires_at TEXT NOT NULL
    );
    """,
    # 009 — Data Partitioning (Phase 2)
    """
    PRAGMA foreign_keys=OFF;
    CREATE TABLE laps_new (
        lap_pk INTEGER PRIMARY KEY,
        owner_user_pk INTEGER NOT NULL,
        lap_id TEXT,
        source_file TEXT NOT NULL,
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('self', 'reference')),
        session_key TEXT,
        run_index INTEGER,
        n_samples INTEGER NOT NULL,
        duration_s REAL NOT NULL,
        imported_at TEXT,
        quality_flags TEXT NOT NULL,
        content_hash TEXT,
        lap_date TEXT,
        UNIQUE(content_hash, source_file, owner_user_pk)
    );
    INSERT INTO laps_new (lap_pk, owner_user_pk, lap_id, source_file, driver, car, track, role, session_key, run_index, n_samples, duration_s, imported_at, quality_flags, content_hash, lap_date)
    SELECT lap_pk, 1, lap_id, source_file, driver, car, track, role, session_key, run_index, n_samples, duration_s, imported_at, quality_flags, content_hash, lap_date FROM laps;
    DROP TABLE laps;
    ALTER TABLE laps_new RENAME TO laps;
    CREATE INDEX idx_laps_cohort ON laps(car, track, role);
    CREATE INDEX idx_laps_content_hash ON laps(content_hash);

    CREATE TABLE corner_maps_new (
        map_pk INTEGER PRIMARY KEY,
        owner_user_pk INTEGER NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        built_from_n_laps INTEGER NOT NULL,
        UNIQUE(car, track, owner_user_pk)
    );
    INSERT INTO corner_maps_new (map_pk, owner_user_pk, car, track, built_from_n_laps)
    SELECT map_pk, 1, car, track, built_from_n_laps FROM corner_maps;
    DROP TABLE corner_maps;
    ALTER TABLE corner_maps_new RENAME TO corner_maps;

    CREATE TABLE incidents_new (
        incident_pk INTEGER PRIMARY KEY,
        lap_pk INTEGER NOT NULL REFERENCES laps(lap_pk) ON DELETE CASCADE,
        owner_user_pk INTEGER NOT NULL,
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
    INSERT INTO incidents_new (incident_pk, lap_pk, owner_user_pk, kinds, classification, confidence, corner_id, span_start, span_end, onset, min_speed_kmh, peak_yaw_rate, rationale, detail)
    SELECT incident_pk, lap_pk, 1, kinds, classification, confidence, corner_id, span_start, span_end, onset, min_speed_kmh, peak_yaw_rate, rationale, detail FROM incidents;
    DROP TABLE incidents;
    ALTER TABLE incidents_new RENAME TO incidents;
    CREATE INDEX idx_incidents_lap ON incidents(lap_pk);

    CREATE TABLE chat_transcripts_new (
        turn_pk INTEGER PRIMARY KEY,
        session_id TEXT NOT NULL,
        owner_user_pk INTEGER NOT NULL,
        bundle_version INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('driver', 'assistant', 'system-event')),
        content TEXT NOT NULL,
        evidence_cited TEXT,
        effects TEXT
    );
    INSERT INTO chat_transcripts_new (turn_pk, session_id, owner_user_pk, bundle_version, role, content, evidence_cited, effects)
    SELECT turn_pk, session_id, 1, bundle_version, role, content, evidence_cited, effects FROM chat_transcripts;
    DROP TABLE chat_transcripts;
    ALTER TABLE chat_transcripts_new RENAME TO chat_transcripts;

    CREATE TABLE driver_beliefs_new (
        belief_pk INTEGER PRIMARY KEY,
        owner_user_pk INTEGER NOT NULL,
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
        UNIQUE (owner_user_pk, driver, fundamental, scoring_model_version)
    );
    INSERT INTO driver_beliefs_new (belief_pk, owner_user_pk, driver, fundamental, signal_status, score, confidence, evidence_count, trend, insufficient_reason, scoring_model_version, taxonomy_version, computed_at)
    SELECT belief_pk, 1, driver, fundamental, signal_status, score, confidence, evidence_count, trend, insufficient_reason, scoring_model_version, taxonomy_version, computed_at FROM driver_beliefs;
    DROP TABLE driver_beliefs;
    ALTER TABLE driver_beliefs_new RENAME TO driver_beliefs;

    CREATE TABLE coach_outputs_new (
        output_pk INTEGER PRIMARY KEY,
        owner_user_pk INTEGER NOT NULL,
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        payload_version INTEGER NOT NULL,
        prompt_version TEXT NOT NULL,
        model TEXT NOT NULL,
        output_json TEXT NOT NULL,
        created_at TEXT
    );
    INSERT INTO coach_outputs_new (output_pk, owner_user_pk, driver, car, track, payload_version, prompt_version, model, output_json, created_at)
    SELECT output_pk, 1, driver, car, track, payload_version, prompt_version, model, output_json, created_at FROM coach_outputs;
    DROP TABLE coach_outputs;
    ALTER TABLE coach_outputs_new RENAME TO coach_outputs;

    CREATE TABLE garage61_sync_state_new (
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        owner_user_pk INTEGER NOT NULL,
        laps_seen INTEGER NOT NULL DEFAULT 0,
        laps_new INTEGER NOT NULL DEFAULT 0,
        last_synced_at TEXT,
        PRIMARY KEY (owner_user_pk, driver, car, track)
    );
    INSERT INTO garage61_sync_state_new (driver, car, track, owner_user_pk, laps_seen, laps_new, last_synced_at)
    SELECT driver, car, track, 1, laps_seen, laps_new, last_synced_at FROM garage61_sync_state;
    DROP TABLE garage61_sync_state;
    ALTER TABLE garage61_sync_state_new RENAME TO garage61_sync_state;

    CREATE TABLE config_history_new (
        change_pk INTEGER PRIMARY KEY,
        owner_user_pk INTEGER NOT NULL,
        key TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT NOT NULL,
        source TEXT NOT NULL,
        note TEXT
    );
    INSERT INTO config_history_new (change_pk, owner_user_pk, key, old_value, new_value, source, note)
    SELECT change_pk, 1, key, old_value, new_value, source, note FROM config_history;
    DROP TABLE config_history;
    ALTER TABLE config_history_new RENAME TO config_history;
    PRAGMA foreign_keys=ON;
    """,
    # 010 — track outline
    """
    ALTER TABLE corner_maps ADD COLUMN track_outline_json TEXT;
    """,
    # 011 - session_epoch for auth
    """
    ALTER TABLE users ADD COLUMN session_epoch TEXT NOT NULL DEFAULT '';
    """,
    # 012 - password resets
    """
    DROP TABLE IF EXISTS password_resets;
    CREATE TABLE password_resets (
        user_pk INTEGER NOT NULL,
        reset_token_hash TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(user_pk) REFERENCES users(user_pk) ON DELETE CASCADE
    );
    CREATE INDEX idx_password_resets_hash ON password_resets(reset_token_hash);
    """,
    # 013 - Gemini provider (DEPLOY-SPEC Track P item 6): which model
    # produced a stored coach explanation is part of the audit trail, not
    # incidental. Default is honest, not aspirational -- every row that
    # already exists in any real database was produced by Claude, since
    # Gemini support didn't exist until this migration.
    """
    ALTER TABLE coach_outputs ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude';
    """,
    # 014 - per-user AI provider keys, BYOK (SPEC.md A37). Reverses the
    # env-only-secrets non-negotiable for exactly this one case, recorded
    # there rather than left implied. ciphertext/nonce are AES-GCM
    # (cryptography, coach/keystore.py); fingerprint is a short, non-secret
    # display hint (e.g. "AIza...7f3c"), never the key itself. One key per
    # (account, provider) -- a fresh PUT overwrites, it doesn't accumulate.
    """
    CREATE TABLE user_api_keys (
        key_pk INTEGER PRIMARY KEY,
        owner_user_pk INTEGER NOT NULL,
        provider TEXT NOT NULL,
        ciphertext TEXT NOT NULL,
        nonce TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (owner_user_pk, provider)
    );
    """,
    # 015 - reference-lap curation (R3, SPEC.md A39). An exclusion is the
    # audited-annotations pattern (finding_annotations, migration 001)
    # applied to a lap instead of a finding: reversible, never deletes the
    # lap or its measurements -- it only removes it from the reference
    # envelope and vs-reference findings until re-included. owner_user_pk
    # follows the user_api_keys (014) shape rather than finding_annotations'
    # (001, predates Data Partitioning) -- exclusion is scoped per account
    # like every table created after migration 009.
    """
    CREATE TABLE reference_exclusions (
        exclusion_pk INTEGER PRIMARY KEY,
        owner_user_pk INTEGER NOT NULL,
        lap_pk INTEGER NOT NULL,
        note TEXT,
        created_at TEXT,
        UNIQUE (owner_user_pk, lap_pk)
    );
    """,
    # 016 - Garage61 OAuth tokens, encrypted at rest. Same keystore.py
    # pattern as BYOK (014) — the access token (and optional refresh token)
    # are AES-GCM encrypted with a key derived from DRIVERDNA_SESSION_SECRET.
    # One row per user; a fresh OAuth flow overwrites via UPSERT. The
    # garage61_user_id is the driver's Garage61 account id (from /me),
    # stored in plaintext for display/debugging — it is not a secret.
    """
    CREATE TABLE garage61_tokens (
        token_pk INTEGER PRIMARY KEY,
        owner_user_pk INTEGER NOT NULL UNIQUE,
        garage61_user_id TEXT,
        access_ciphertext TEXT NOT NULL,
        access_nonce TEXT NOT NULL,
        refresh_ciphertext TEXT,
        refresh_nonce TEXT,
        scopes TEXT,
        created_at TEXT NOT NULL
    );
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


def open_postgres_pool(dsn: str, *, min_size: int = 2, max_size: int = 10) -> "ConnectionPool":
    """A per-process pool: each request checks out its own connection
    (`Database.from_pool`) instead of every request paying a fresh
    TCP+TLS+migration round trip, or — the hazard a single shared connection
    would introduce — multiple concurrent requests contending for the same
    connection.

    `configure` runs once per new physical connection, not per checkout: the
    namespace switch, migration check, and RLS hardening all happen there,
    so steady-state checkouts do none of that work.
    """
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ModuleNotFoundError as exc:  # pragma: no cover - install hint
        raise RuntimeError(
            "Postgres support needs psycopg: pip install 'driverdna[pg]'"
        ) from exc

    def _configure(conn) -> None:
        _namespace_postgres(conn)
        database = Database(conn, dialect=_POSTGRES)  # runs _migrate()
        database._harden_postgres()

    try:
        pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                # See Database._connect_postgres: breaks behind a
                # transaction-mode pooler (Supabase port 6543).
                "prepare_threshold": None,
            },
            configure=_configure,
            open=True,
        )
        pool.wait(timeout=30)
    except Exception as exc:
        raise RuntimeError(f"could not connect to {redact_dsn(dsn)}: {exc}") from None
    return pool


class Database:
    """One connection, migrations applied, typed helpers over the schema."""

    def __init__(
        self,
        conn,
        blobs: BlobStore | None = None,
        dialect: _Dialect | None = None,
        user_pk: int = 1,
    ):
        self.dialect = dialect or _SQLITE
        self.user_pk = user_pk
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
        user_pk: int = 1,
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
            database = cls(conn, blobs, _POSTGRES, user_pk=user_pk)
            database._harden_postgres()
            return database
        return cls(
            sqlite3.connect(str(path), check_same_thread=check_same_thread),
            blobs,
            _SQLITE,
            user_pk=user_pk,
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

    @classmethod
    def from_pool(cls, pool: "ConnectionPool", blobs: BlobStore, user_pk: int = 1) -> "Database":
        """Check out a connection from a pool built by `open_postgres_pool`.

        Each caller gets its own physical connection, never a shared one:
        psycopg connections are not safe for concurrent use from multiple
        threads, and FastAPI runs sync route handlers in a thread pool, so
        two simultaneous requests sharing one connection would be a real
        correctness hazard, not just a missed optimization. `close()` on the
        returned instance returns the connection to the pool rather than
        closing the socket. Already migrated and hardened — the pool's
        `configure` callback does that once per physical connection, not per
        checkout.

        `user_pk` must be passed through explicitly (unlike `Database.open`,
        this bypasses `__init__`) — every query below scopes to
        `self.user_pk`, so a request's tenant would silently fall back to 1
        without it.
        """
        raw = pool.getconn()
        db = object.__new__(cls)
        db.dialect = _POSTGRES
        db.user_pk = user_pk
        db.conn = _Conn(raw, _POSTGRES)
        db.blobs = blobs
        db._pool = pool
        db._pool_raw = raw
        return db

    def close(self) -> None:
        pool = getattr(self, "_pool", None)
        if pool is not None:
            pool.putconn(self._pool_raw)
            return
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _migrate(self) -> None:
        migrations = self.dialect.migrations()
        # Serialize migrations across concurrent pool connections (Postgres
        # only — SQLite has no pool). Without this, min_size=2 means two
        # connections call _configure → _migrate concurrently; both see
        # the same schema_version and both try to run the same DDL, crashing
        # the second one ("relation already exists" / table dropped mid-use).
        _pg = self.dialect is _POSTGRES
        if _pg:
            self.conn.execute("SELECT pg_advisory_lock(1)")
        try:
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
        finally:
            if _pg:
                self.conn.execute("SELECT pg_advisory_unlock(1)")

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
            "SELECT lap_pk FROM laps WHERE source_file = ? AND owner_user_pk = ?", (str(lap.source_path), self.user_pk)
        ).fetchone()
        if existing:
            return int(existing["lap_pk"]), "exists"

        content_hash = _content_hash(lap)
        dup = self.conn.execute(
            "SELECT lap_pk FROM laps WHERE content_hash = ? AND owner_user_pk = ?", (content_hash, self.user_pk)
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
                                     imported_at, quality_flags, content_hash, lap_date,
                                     owner_user_pk)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lap.lap_id, str(lap.source_path), driver, car, track, role,
                    session_key, run_index, lap.n_samples, lap.duration_s, imported_at,
                    flags, content_hash, lap_date, self.user_pk,
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
            "SELECT ls.data FROM lap_samples_legacy ls JOIN laps l ON l.lap_pk = ls.lap_pk WHERE ls.lap_pk = ? AND l.owner_user_pk = ?", (lap_pk, self.user_pk)
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

    def laps_needing_raw(self) -> list[tuple[int, str | None]]:
        """`(lap_pk, content_hash)` for every lap whose raw trace is absent
        here and was not deliberately evicted here — i.e. recoverable by
        re-supplying its source CSV. Ordered by `lap_pk` for determinism.

        This is the backfill worklist after a store move: `store-copy` carries
        the lap rows (with their `content_hash`) but not the blobs, so on the
        target every lap is 'absent, never evicted'. A deliberately-evicted lap
        is excluded — its trace is gone by policy, and re-writing it here would
        only be undone at the next retention pass (same reasoning as
        `unavailable_raw_laps`)."""
        rows = self.conn.execute(
            "SELECT lap_pk, content_hash FROM laps WHERE owner_user_pk = ? ORDER BY lap_pk",
            (self.user_pk,),
        ).fetchall()
        evicted = self.blobs.evicted_lap_pks()
        return [
            (int(r["lap_pk"]), r["content_hash"])
            for r in rows
            if int(r["lap_pk"]) not in evicted and not self.has_raw(int(r["lap_pk"]))
        ]

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
                for r in self.conn.execute(
                    "SELECT ls.lap_pk FROM lap_samples_legacy ls JOIN laps l ON l.lap_pk = ls.lap_pk WHERE l.owner_user_pk = ?", (self.user_pk,)
                )
            }
        if not held:
            return 0

        seen: dict[tuple[str, str, str], int] = {}
        evicted = 0
        for r in self.conn.execute(
            """SELECT lap_pk, driver, car, track FROM laps
               WHERE owner_user_pk = ?
               ORDER BY driver, car, track, lap_pk DESC""",
            (self.user_pk,)
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
            "SELECT ls.lap_pk, ls.data FROM lap_samples_legacy ls JOIN laps l ON l.lap_pk = ls.lap_pk WHERE l.owner_user_pk = ? ORDER BY ls.lap_pk",
            (self.user_pk,)
        ).fetchall():
            lap_pk = int(r["lap_pk"])
            if not self.blobs.has(lap_pk):
                self.blobs.put(lap_pk, r["data"])
            moved += 1
        with self.conn:
            self.conn.execute("DELETE FROM lap_samples_legacy WHERE lap_pk IN (SELECT ls.lap_pk FROM lap_samples_legacy ls JOIN laps l ON l.lap_pk = ls.lap_pk WHERE l.owner_user_pk = ?)", (self.user_pk,))
        return moved

    # --- corner maps -------------------------------------------------------

    def store_corner_map(
        self, corner_map: CornerMap, *, car: str, track: str,
        built_from_n_laps: int, track_outline_json: str | None = None,
    ) -> int:
        """Corner maps are keyed by (car, track) — NOT driver — so reference
        laps from other drivers share the owner's corner identities; gap
        analysis joins on them."""
        with self.conn:
            map_pk = self._insert_returning(
                """INSERT INTO corner_maps (car, track, built_from_n_laps, owner_user_pk, track_outline_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (car, track, built_from_n_laps, self.user_pk, track_outline_json),
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
            "SELECT map_pk FROM corner_maps WHERE car=? AND track=? AND owner_user_pk=?",
            (car, track, self.user_pk),
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
            "SELECT c.corner_pk FROM corners c JOIN corner_maps m ON m.map_pk = c.map_pk WHERE c.map_pk=? AND c.corner_id=? AND m.owner_user_pk=?",
            (map_pk, corner_id, self.user_pk),
        ).fetchone()
        if row is None:
            raise KeyError(f"no corner {corner_id} in map {map_pk}")
        return int(row["corner_pk"])

    def set_corner_class(self, corner_pk: int, cls: str) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE corners SET class=? WHERE corner_pk IN (
                    SELECT c.corner_pk FROM corners c
                    JOIN corner_maps m ON m.map_pk = c.map_pk
                    WHERE c.corner_pk=? AND m.owner_user_pk=?
                )""", (cls, corner_pk, self.user_pk)
            )

    def corner_apex_positions(
        self, corner_pk: int
    ) -> list[tuple[float, float, float]]:
        """(apex_lat, apex_lon, apex_lap_dist) for every SELF observation
        assigned to this corner — the input to an in-place centroid refreeze
        (`rebuild-map`). Compact rows only; survives blob eviction.

        Self-only (SPEC.md A34): a reference lap is linked to this corner and
        measured against it, but where the corner *is* must be decided by the
        driver's own laps. A stranger's line dragging the centroid moves the
        phase windows, and the windows are where every self phase time is
        measured — the isolation guarantee one level below the metrics."""
        rows = self.conn.execute(
            """SELECT o.apex_lat, o.apex_lon, o.apex_lap_dist
               FROM corner_observations o
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN corner_maps m ON m.map_pk = c.map_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE o.corner_pk=? AND m.owner_user_pk=? AND l.role='self'
               ORDER BY o.obs_pk""",
            (corner_pk, self.user_pk),
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
               WHERE l.role = 'self' AND l.driver=? AND l.car=? AND l.track=? AND l.owner_user_pk=?
                 AND c.corner_id=? AND mv.name=? AND mv.value IS NOT NULL
               ORDER BY l.lap_pk, o.span_start""",
            (driver, car, track, self.user_pk, corner_id, metric),
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
        driver's); role='reference' aggregates all reference drivers, minus
        any lap R3 curation has excluded (`reference_exclusions`) -- enforced
        here, at the query surface, so every reader (the envelope, the
        corner drill, vs_reference_findings) inherits it automatically,
        the same discipline role isolation itself uses (SPEC.md A34).
        `lap_pks` (M6 trend only) further restricts to a date-bucket's laps.
        """
        if role == "self" and driver is None:
            raise ValueError("self phase history requires a driver")
        clause = "AND l.driver = ?" if driver is not None else ""
        exclusion_clause = (
            " AND l.lap_pk NOT IN "
            "(SELECT lap_pk FROM reference_exclusions WHERE owner_user_pk=?)"
            if role == "reference" else ""
        )
        pk_clause, pk_params = _lap_pk_filter(lap_pks)
        params = (
            [car, track, corner_id, phase, role, self.user_pk]
            + ([driver] if driver else [])
            + ([self.user_pk] if role == "reference" else [])
            + pk_params
        )
        rows = self.conn.execute(
            f"""SELECT p.time_s, l.lap_pk, l.session_key, o.obs_pk
                FROM phase_times p
                JOIN corner_observations o ON o.obs_pk = p.obs_pk
                JOIN corners c ON c.corner_pk = o.corner_pk
                JOIN laps l ON l.lap_pk = o.lap_pk
                WHERE l.car=? AND l.track=? AND c.corner_id=? AND p.phase=?
                  AND l.role=? AND l.owner_user_pk=? {clause}{exclusion_clause}{pk_clause}
                ORDER BY l.lap_pk, o.span_start""",
            params,
        ).fetchall()
        return [
            {"time_s": float(r["time_s"]), "lap_pk": int(r["lap_pk"]),
             "session_key": r["session_key"], "obs_pk": int(r["obs_pk"])}
            for r in rows
        ]

    def reference_laps_for_cohort(self, *, car: str, track: str) -> list[dict[str, Any]]:
        """Every reference lap for this (car, track), each flagged with
        whether R3 curation has excluded it. Excluded laps stay listed --
        curation marks, it never hides (same contract as
        `annotate_finding`) -- so the identity/depth payload section (R2)
        can show the whole pool while the envelope itself (built from
        `phase_history`) only ever reflects the active subset."""
        exclusions = self.reference_exclusions()
        rows = self.conn.execute(
            """SELECT lap_pk, lap_id, driver, duration_s, lap_date
               FROM laps WHERE role='reference' AND car=? AND track=? AND owner_user_pk=?
               ORDER BY lap_pk""",
            (car, track, self.user_pk),
        ).fetchall()
        return [
            {
                "lap_pk": int(r["lap_pk"]),
                "lap_id": r["lap_id"],
                "driver": r["driver"],
                "duration_s": float(r["duration_s"]),
                "lap_date": r["lap_date"],
                "excluded": int(r["lap_pk"]) in exclusions,
            }
            for r in rows
        ]

    def observation_positions(self, corner_pk: int) -> list[dict[str, Any]]:
        """Landmark positions of this corner's SELF observations — the input to
        `derive_windows` when a corner's canonical phase windows are frozen or
        refrozen. Self-only for the same reason as `corner_apex_positions`
        (SPEC.md A34): the windows define where the driver's own entry/mid/exit
        times are measured, so a reference lap must not shift them."""
        rows = self.conn.execute(
            """SELECT o.landmark_positions FROM corner_observations o
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE o.corner_pk=? AND l.role='self' ORDER BY o.obs_pk""",
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
               WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=? AND l.owner_user_pk=?
                 AND mv.value IS NOT NULL{pk_clause}
               ORDER BY c.corner_id, mv.name, l.lap_pk, o.span_start""",
            [driver, car, track, self.user_pk, *pk_params],
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
               WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=? AND l.owner_user_pk=?{pk_clause}
               GROUP BY c.corner_id, d.detector
               ORDER BY c.corner_id, d.detector""",
            [driver, car, track, self.user_pk, *pk_params],
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
                    """INSERT INTO incidents (lap_pk, owner_user_pk, kinds, classification, confidence,
                        corner_id, span_start, span_end, onset, min_speed_kmh,
                        peak_yaw_rate, rationale, detail)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        lap_pk, self.user_pk, "+".join(inc.kinds), inc.classification, inc.confidence,
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
                   WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=? AND l.owner_user_pk=?
                   ORDER BY i.corner_id IS NULL, i.corner_id, i.span_start, i.incident_pk""",
                (driver, car, track, self.user_pk),
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
        least cfg.min_laps_for_admission DISTINCT SELF laps becomes a new
        corner with the next ID (existing IDs never renumber). Re-links the
        observations and returns the admitted corner IDs — the caller must
        surface them; the map never changes silently.

        Reference observations join a cluster and are linked to the corner it
        becomes — a gap needs them — but they neither count toward the distinct
        -lap threshold nor feed the new centroid (SPEC.md A34). Otherwise a
        corner the driver has driven twice and a stranger once enters the map
        at the stranger's apex, and every later self lap is measured there.
        """
        loaded = self.load_corner_map(car=car, track=track)
        if loaded is None:
            return []
        map_pk, corner_map = loaded

        rows = self.conn.execute(
            """SELECT o.obs_pk, o.apex_lat, o.apex_lon, o.apex_lap_dist, o.lap_pk,
                      l.role
               FROM corner_observations o JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE o.corner_pk IS NULL AND l.car=? AND l.track=? AND l.owner_user_pk=?
               ORDER BY o.obs_pk""",
            (car, track, self.user_pk),
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
                # Only the driver's own laps decide that a corner exists and
                # where it sits; reference observations ride along (below).
                own = [r for r in cl["obs"] if r["role"] == "self"]
                lap_pks = {r["lap_pk"] for r in own}
                if len(lap_pks) < cfg.min_laps_for_admission:
                    continue
                corner_id = f"C{next_num:02d}"
                next_num += 1
                new_pk = self._insert_returning(
                    """INSERT INTO corners (map_pk, corner_id, lat, lon, lap_dist,
                                            n_build_observations)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (map_pk, corner_id,
                     float(np.median([r["apex_lat"] for r in own])),
                     float(np.median([r["apex_lon"] for r in own])),
                     float(np.median([r["apex_lap_dist"] for r in own])),
                     len(own)),
                    "corner_pk",
                )
                self.conn.executemany(
                    "UPDATE corner_observations SET corner_pk=? WHERE obs_pk=?",
                    [(new_pk, r["obs_pk"]) for r in cl["obs"]],
                )
                admitted.append(corner_id)
        return admitted

    # --- per-user AI provider keys (SPEC.md A37, BYOK) -----------------------

    def store_user_api_key(
        self, *, provider: str, ciphertext: str, nonce: str, fingerprint: str,
        created_at: str | None = None,
    ) -> None:
        """One key per (account, provider) — a fresh PUT overwrites, it
        never accumulates. `ON CONFLICT` targets the same UNIQUE
        (owner_user_pk, provider) constraint migration 014 declares."""
        with self.conn:
            self.conn.execute(
                f"""INSERT INTO user_api_keys
                    (owner_user_pk, provider, ciphertext, nonce, fingerprint, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (owner_user_pk, provider) DO UPDATE SET
                        ciphertext=excluded.ciphertext, nonce=excluded.nonce,
                        fingerprint=excluded.fingerprint, created_at=excluded.created_at""",
                (self.user_pk, provider, ciphertext, nonce, fingerprint, created_at),
            )

    def get_user_api_key(self, *, provider: str) -> dict[str, Any] | None:
        """Raw (ciphertext, nonce, fingerprint, created_at) for this
        account's key, or None if unset. Decryption happens in
        coach/keystore.py, given the session secret — never here."""
        row = self.conn.execute(
            """SELECT ciphertext, nonce, fingerprint, created_at FROM user_api_keys
               WHERE owner_user_pk=? AND provider=?""",
            (self.user_pk, provider),
        ).fetchone()
        return dict(row) if row else None

    def delete_user_api_key(self, *, provider: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM user_api_keys WHERE owner_user_pk=? AND provider=?",
                (self.user_pk, provider),
            )
            return cur.rowcount > 0

    # --- coach outputs ------------------------------------------------------

    def store_coach_output(
        self, *, driver: str, car: str, track: str, payload_version: int,
        prompt_version: str, model: str, output_json: str,
        provider: str = "claude", created_at: str | None = None,
    ) -> int:
        with self.conn:
            return self._insert_returning(
                """INSERT INTO coach_outputs
                   (driver, car, track, owner_user_pk, payload_version, prompt_version, model,
                    provider, output_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (driver, car, track, self.user_pk, payload_version, prompt_version, model,
                 provider, output_json, created_at),
                "output_pk",
            )

    def coach_history(self, *, driver: str, car: str, track: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT output_pk, provider, output_json FROM coach_outputs
               WHERE driver=? AND car=? AND track=? AND owner_user_pk=? ORDER BY output_pk""",
            (driver, car, track, self.user_pk),
        ).fetchall()
        history = []
        for r in rows:
            output = json.loads(r["output_json"])
            history.append({
                "output_pk": int(r["output_pk"]),
                "provider": r["provider"],
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

    # --- reference-lap curation (R3, SPEC.md A39) ---------------------------
    #
    # The audited-annotations pattern above, applied to a lap instead of a
    # finding: reversible, upserts in place, never deletes the lap or its
    # measurements. `exclude_reference_lap` validates (unlike
    # `annotate_finding`, which trusts a caller-side check) because the
    # validation here -- "does this lap_pk exist, is it this user's, is it
    # actually a reference lap" -- is a single cheap query naturally owned
    # by this layer, not something that needs the payload/finding-rebuild
    # machinery `annotate`'s own 404 check requires.

    def exclude_reference_lap(
        self, *, lap_pk: int, note: str | None = None, created_at: str | None = None,
    ) -> int:
        """Mark a reference lap excluded from the envelope and
        vs-reference findings. Raises ValueError if `lap_pk` isn't this
        user's, or isn't role='reference' -- a self lap has no exclusion
        concept, it IS the history."""
        row = self.conn.execute(
            "SELECT role FROM laps WHERE lap_pk=? AND owner_user_pk=?",
            (lap_pk, self.user_pk),
        ).fetchone()
        if row is None:
            raise ValueError(f"no such lap: {lap_pk}")
        if row["role"] != "reference":
            raise ValueError(f"lap {lap_pk} is not a reference lap")
        with self.conn:
            return self._insert_returning(
                """INSERT INTO reference_exclusions
                   (owner_user_pk, lap_pk, note, created_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT (owner_user_pk, lap_pk) DO UPDATE SET
                       note       = excluded.note,
                       created_at = excluded.created_at""",
                (self.user_pk, lap_pk, note, created_at),
                "exclusion_pk",
            )

    def reference_exclusions(self) -> dict[int, dict[str, Any]]:
        return {
            int(r["lap_pk"]): {"note": r["note"], "created_at": r["created_at"]}
            for r in self.conn.execute(
                "SELECT * FROM reference_exclusions WHERE owner_user_pk=? ORDER BY lap_pk",
                (self.user_pk,),
            )
        }

    def include_reference_lap(self, lap_pk: int) -> None:
        """Undo an exclusion (never touches the lap or its measurements)."""
        with self.conn:
            self.conn.execute(
                "DELETE FROM reference_exclusions WHERE owner_user_pk=? AND lap_pk=?",
                (self.user_pk, lap_pk),
            )

    def add_chat_turn(
        self, *, session_id: str, bundle_version: int, role: str, content: str,
        evidence_cited: list[str] | None = None,
        effects: dict[str, Any] | None = None,
    ) -> int:
        with self.conn:
            return self._insert_returning(
                """INSERT INTO chat_transcripts
                   (session_id, owner_user_pk, bundle_version, role, content, evidence_cited, effects)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, self.user_pk, bundle_version, role, content,
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
                "SELECT * FROM chat_transcripts WHERE session_id=? AND owner_user_pk=? ORDER BY turn_pk",
                (session_id, self.user_pk),
            )
        ]

    # --- config history -----------------------------------------------------

    def record_config_change(
        self, *, key: str, old_value: str | None, new_value: str, source: str,
        note: str | None = None,
    ) -> int:
        with self.conn:
            return self._insert_returning(
                """INSERT INTO config_history (key, old_value, new_value, source, note, owner_user_pk)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key, old_value, new_value, source, note, self.user_pk),
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
                   (driver, owner_user_pk, fundamental, signal_status, score, confidence,
                    evidence_count, trend, insufficient_reason,
                    scoring_model_version, taxonomy_version, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (owner_user_pk, driver, fundamental, scoring_model_version)
                   DO UPDATE SET
                       signal_status=excluded.signal_status,
                       score=excluded.score,
                       confidence=excluded.confidence,
                       evidence_count=excluded.evidence_count,
                       trend=excluded.trend,
                       insufficient_reason=excluded.insufficient_reason,
                       taxonomy_version=excluded.taxonomy_version,
                       computed_at=excluded.computed_at""",
                (driver, self.user_pk, fundamental, signal_status, score, confidence,
                 evidence_count, trend, insufficient_reason,
                 scoring_model_version, taxonomy_version, computed_at),
            )
        row = self.conn.execute(
            """SELECT belief_pk FROM driver_beliefs
               WHERE driver=? AND fundamental=? AND scoring_model_version=? AND owner_user_pk=?""",
            (driver, fundamental, scoring_model_version, self.user_pk),
        ).fetchone()
        return int(row["belief_pk"])

    def load_beliefs(
        self, *, driver: str, scoring_model_version: str
    ) -> dict[str, dict[str, Any]]:
        """{fundamental: belief dict} for one driver at one model version."""
        rows = self.conn.execute(
            """SELECT * FROM driver_beliefs
               WHERE driver=? AND scoring_model_version=? AND owner_user_pk=?
               ORDER BY fundamental""",
            (driver, scoring_model_version, self.user_pk),
        ).fetchall()
        return {r["fundamental"]: dict(r) for r in rows}

    def driver_session_count(self, driver: str) -> int:
        row = self.conn.execute(
            """SELECT COUNT(DISTINCT session_key) n FROM laps
               WHERE role='self' AND driver=? AND session_key IS NOT NULL AND owner_user_pk=?""",
            (driver, self.user_pk),
        ).fetchone()
        return int(row["n"])

    def fundamental_evidence_lap_count(
        self, *, driver: str, metric_names: tuple[str, ...],
        detector_names: tuple[str, ...],
        lap_pks: frozenset[int] | None = None,
    ) -> int:
        """Distinct self-role laps that contributed >=1 metric value or
        detector result relevant to a fundamental's mapped techniques — the
        driver-facing "how many of your laps taught me something" count.
        Empty metric/detector sets (e.g. vision) return 0, honestly.

        `lap_pks` (M6 trend / score-history, A36) restricts to a date
        bucket's laps, same mechanism as `phase_history`/`self_metric_table`;
        None (every non-bucketed caller) means no restriction.
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
        pk_clause, pk_params = _lap_pk_filter(lap_pks)
        row = self.conn.execute(
            f"""SELECT COUNT(DISTINCT o.lap_pk) n FROM corner_observations o
                JOIN laps l ON l.lap_pk = o.lap_pk
                WHERE l.role='self' AND l.driver=? AND l.owner_user_pk=?
                  AND ({' OR '.join(clauses)}){pk_clause}""",
            [driver, self.user_pk, *params, *pk_params],
        ).fetchone()
        return int(row["n"])

    def driver_dated_lap_count(self, driver: str) -> int:
        """Self-role laps with a real lap_date — the trend-availability
        check. `sync` (M0b+) is the first ingestion path that sets it (from
        the API's startTime)."""
        row = self.conn.execute(
            """SELECT COUNT(*) n FROM laps
               WHERE role='self' AND driver=? AND lap_date IS NOT NULL AND owner_user_pk=?""",
            (driver, self.user_pk),
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
               WHERE role='self' AND driver=? AND lap_date IS NOT NULL AND owner_user_pk=?
               ORDER BY lap_date, lap_pk""",
            (driver, self.user_pk),
        ).fetchall()
        return [int(r["lap_pk"]) for r in rows]

    def dated_self_laps(self, driver: str) -> list[tuple[int, str]]:
        """Same rows and ordering as `dated_self_lap_pks`, paired with each
        lap's `lap_date` string — A36 score history's bucket-label source
        (the date range a bucket actually spans), kept as a sibling method
        rather than changing `dated_self_lap_pks`'s return shape so its
        existing callers (M6 trend) are untouched."""
        rows = self.conn.execute(
            """SELECT lap_pk, lap_date FROM laps
               WHERE role='self' AND driver=? AND lap_date IS NOT NULL AND owner_user_pk=?
               ORDER BY lap_date, lap_pk""",
            (driver, self.user_pk),
        ).fetchall()
        return [(int(r["lap_pk"]), str(r["lap_date"])) for r in rows]

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
                   (driver, car, track, owner_user_pk, laps_seen, laps_new, last_synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (owner_user_pk, driver, car, track) DO UPDATE SET
                       laps_seen=excluded.laps_seen,
                       laps_new=excluded.laps_new,
                       last_synced_at=excluded.last_synced_at""",
                (driver, car, track, self.user_pk, laps_seen, laps_new, synced_at),
            )

    def sync_states(self, driver: str) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.conn.execute(
                """SELECT * FROM garage61_sync_state WHERE driver=? AND owner_user_pk=?
                   ORDER BY car, track""",
                (driver, self.user_pk),
            )
        ]
