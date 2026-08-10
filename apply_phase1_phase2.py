import re

with open('src/driverdna/db.py', 'r') as f:
    code = f.read()

# Fix CRLF just in case
code = code.replace('\r\n', '\n')

# 1. Update _MIGRATIONS
migration_007 = """
    -- Phase 1: Identity Core
    CREATE TABLE users (
        user_pk INTEGER PRIMARY KEY AUTOINCREMENT,
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
"""

migration_008 = """
    -- Phase 2: Data Partitioning
    CREATE TABLE laps_new (
        lap_pk INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_user_pk INTEGER NOT NULL,
        lap_id TEXT,
        source_file TEXT NOT NULL,
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('self', 'reference')),
        session_key TEXT NOT NULL,
        run_index INTEGER NOT NULL,
        n_samples INTEGER NOT NULL,
        duration_s REAL NOT NULL,
        imported_at TEXT NOT NULL,
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
        map_pk INTEGER PRIMARY KEY AUTOINCREMENT,
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
"""

target = '    """\n    ALTER TABLE lap_samples RENAME TO lap_samples_legacy;\n    """,\n)'
replacement = '    """\n    ALTER TABLE lap_samples RENAME TO lap_samples_legacy;\n    """,\n    """' + migration_007 + '    """,\n    """' + migration_008 + '    """,\n)'
code = code.replace(target, replacement)


# 2. Update __init__ and open()
old_init = """    def __init__(
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
        self._migrate()"""

new_init = """    def __init__(
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
        self._migrate()"""

code = code.replace(old_init, new_init)

old_open = """    @classmethod
    def open(
        cls,
        path: Path | str = ":memory:",
        *,
        check_same_thread: bool = True,
        blob_root: Path | str | None = None,
    ) -> "Database":"""

new_open = """    @classmethod
    def open(
        cls,
        path: Path | str = ":memory:",
        *,
        check_same_thread: bool = True,
        blob_root: Path | str | None = None,
        user_pk: int = 1,
    ) -> "Database":"""

code = code.replace(old_open, new_open)

old_open_body = """        if is_postgres_url(path):
            conn = cls._connect_postgres(str(path))
            _namespace_postgres(conn)
            database = cls(conn, blobs, _POSTGRES)
            database._harden_postgres()
            return database
        return cls(
            sqlite3.connect(str(path), check_same_thread=check_same_thread),
            blobs,
            _SQLITE,
        )"""

new_open_body = """        if is_postgres_url(path):
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
        )"""

code = code.replace(old_open_body, new_open_body)

# 3. Carefully update the queries!
# To avoid python regex nightmares, I'll use exact strings that I extract!

import json
with open('queries.json', 'r') as f:
    queries = json.load(f)

def rep(old, new):
    global code
    if old not in code:
        print(f"FAILED TO FIND EXACT STRING:\n{old}\n---")
    else:
        code = code.replace(old, new)

rep(
    queries['import_lap'],
    '"""INSERT INTO laps (lap_id, source_file, driver, car, track, role,\n                                     session_key, run_index, n_samples, duration_s,\n                                     imported_at, quality_flags, content_hash, lap_date,\n                                     owner_user_pk)\n                   VALUES (?, ?, ?, ?, ?, ?,\n                           ?, ?, ?, ?, ?, ?, ?, ?, ?)""",\n                (\n                    lap.lap_id, str(lap.source_path), driver, car, track, role,\n                    session_key, run_index, lap.n_samples, lap.duration_s, imported_at,\n                    flags, content_hash, lap_date, self.user_pk,\n                ),'
)
rep(queries['load_lap_arrays_legacy_select'], '"SELECT data FROM lap_samples_legacy WHERE lap_pk = ? AND owner_user_pk = ?", (lap_pk, self.user_pk)')
rep(queries['retained_lap_pks_1'], 'for r in self.conn.execute("SELECT lap_pk FROM lap_samples_legacy WHERE owner_user_pk = ?", (self.user_pk,)):')
rep(queries['retained_lap_pks_2'], '"""SELECT lap_pk, driver, car, track FROM laps\n               WHERE owner_user_pk = ?\n               ORDER BY driver, car, track, lap_pk DESC""",\n            (self.user_pk,)\n        ):')
rep(queries['retained_lap_pks_delete'], '"DELETE FROM lap_samples_legacy WHERE lap_pk = ? AND owner_user_pk = ?", (lap_pk, self.user_pk)')
rep(queries['dump_blobs_select'], '"SELECT lap_pk, data FROM lap_samples_legacy WHERE owner_user_pk = ? ORDER BY lap_pk",\n            (self.user_pk,)\n        ).fetchall():')
rep(queries['dump_blobs_delete'], 'self.conn.execute("DELETE FROM lap_samples_legacy WHERE owner_user_pk = ?", (self.user_pk,))')

rep(queries['corner_maps_insert'], '"""INSERT INTO corner_maps (car, track, built_from_n_laps, owner_user_pk)\n                   VALUES (?, ?, ?, ?)""",\n                (car, track, built_from_n_laps, self.user_pk),')
rep(queries['corner_maps_select'], '"SELECT map_pk FROM corner_maps WHERE car=? AND track=? AND owner_user_pk=?",\n            (car, track, self.user_pk),')
rep(queries['corners_select'], '"SELECT c.corner_pk FROM corners c JOIN corner_maps m ON m.map_pk = c.map_pk WHERE c.map_pk=? AND c.corner_id=? AND m.owner_user_pk=?",\n            (map_pk, corner_id, self.user_pk),')
rep(queries['corners_update'], '"""UPDATE corners SET class=? WHERE corner_pk IN (\n                    SELECT c.corner_pk FROM corners c\n                    JOIN corner_maps m ON m.map_pk = c.map_pk\n                    WHERE c.corner_pk=? AND m.owner_user_pk=?\n                )""", (cls, corner_pk, self.user_pk)')
rep(queries['corner_observations_select'], '"""SELECT o.apex_lat, o.apex_lon, o.apex_lap_dist\n               FROM corner_observations o\n               JOIN corners c ON c.corner_pk = o.corner_pk\n               JOIN corner_maps m ON m.map_pk = c.map_pk\n               WHERE o.corner_pk=? AND m.owner_user_pk=? ORDER BY o.obs_pk""",\n            (corner_pk, self.user_pk),')
rep(queries['phase_times_select'], '"""SELECT p.phase, p.time_s FROM phase_times p\n               JOIN corner_observations o ON o.obs_pk = p.obs_pk\n               JOIN corners c ON c.corner_pk = o.corner_pk\n               JOIN corner_maps m ON m.map_pk = c.map_pk\n               WHERE o.corner_pk=? AND m.owner_user_pk=?\n               ORDER BY p.obs_pk""",\n            (corner_pk, self.user_pk),')

rep(queries['cohort_laps_stats'], '"""\n            SELECT COUNT(*) n, SUM(duration_s) d, SUM(n_samples) s, MIN(lap_date) earliest, MAX(lap_date) latest\n            FROM laps WHERE car = ? AND track = ? AND role = \'self\' AND owner_user_pk = ?\n            """,\n            (car, track, self.user_pk),')
rep(queries['cohort_laps_self'], 'WHERE l.car = ? AND l.track = ? AND l.role = \'self\' AND l.owner_user_pk = ?\n        ORDER BY l.lap_pk DESC LIMIT ?\n        """,\n        (car, track, self.user_pk, limit),')
rep(queries['cohort_laps_ref'], 'WHERE l.car = ? AND l.track = ? AND l.role = \'reference\' AND l.owner_user_pk = ?\n        ORDER BY l.lap_pk DESC\n        """,\n        (car, track, self.user_pk),')

rep(queries['find_duplicate'], 'WHERE lap_pk IN ({placeholders}) AND owner_user_pk = ?\n            """,\n            (*tuple(lap_pks), self.user_pk),')
rep(queries['get_cohort_baseline'], 'WHERE car = ? AND track = ? AND owner_user_pk = ?\n            ORDER BY lap_pk\n            """,\n            (car, track, self.user_pk),')

rep(queries['incidents_select'], 'FROM incidents\n            WHERE lap_pk = ? AND owner_user_pk = ?\n            """,\n            (lap_pk, self.user_pk),')
rep(queries['incidents_insert'], '"""INSERT INTO incidents (lap_pk, kinds, classification, confidence,\n                        corner_id, span_start, span_end, onset, min_speed_kmh,\n                        peak_yaw_rate, rationale, detail, owner_user_pk)\n                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",\n                    (\n                        lap_pk, "+".join(inc.kinds), inc.classification, inc.confidence,\n                        inc.corner_id, int(inc.span_start), int(inc.span_end),\n                        int(inc.onset), float(inc.min_speed_kmh),\n                        float(inc.peak_yaw_rate), inc.rationale, inc.detail, self.user_pk,\n                    ),')

rep(queries['garage61_select'], '"SELECT laps_seen, laps_new, last_synced_at FROM garage61_sync_state WHERE driver=? AND car=? AND track=? AND owner_user_pk=?",\n            (driver, car, track, self.user_pk),')
rep(queries['garage61_upsert'], '"""INSERT INTO garage61_sync_state (driver, car, track, laps_seen, laps_new, last_synced_at, owner_user_pk)\n                   VALUES (?, ?, ?, ?, ?, ?, ?)\n                   ON CONFLICT (owner_user_pk, driver, car, track) DO UPDATE SET\n                       laps_seen=excluded.laps_seen,\n                       laps_new=excluded.laps_new,\n                       last_synced_at=excluded.last_synced_at""",\n                (driver, car, track, seen, new, at, self.user_pk),')

rep(queries['chat_transcripts_select'], '"""SELECT role, content, evidence_cited, effects\n               FROM chat_transcripts WHERE session_id = ? AND owner_user_pk = ?\n               ORDER BY turn_pk""",\n            (session_id, self.user_pk),')
rep(queries['chat_transcripts_insert'], '"""INSERT INTO chat_transcripts\n                   (session_id, owner_user_pk, bundle_version, role, content, evidence_cited, effects)\n                   VALUES (?, ?, ?, ?, ?, ?, ?)""",\n                (\n                    session_id, self.user_pk, bundle_version, role, content,\n                    json.dumps(evidence_cited or [], sort_keys=True),\n                    json.dumps(effects or {}, sort_keys=True),\n                ),')
rep(queries['chat_transcripts_delete'], '"DELETE FROM chat_transcripts WHERE session_id = ? AND owner_user_pk = ?", (session_id, self.user_pk)')

rep(queries['driver_beliefs_upsert'], '"""INSERT INTO driver_beliefs\n                   (driver, owner_user_pk, fundamental, signal_status, score, confidence,\n                    evidence_count, trend, insufficient_reason,\n                    scoring_model_version, taxonomy_version, computed_at)\n                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                   ON CONFLICT(owner_user_pk, driver, fundamental, scoring_model_version)\n                   DO UPDATE SET\n                       signal_status=excluded.signal_status,\n                       score=excluded.score,\n                       confidence=excluded.confidence,\n                       evidence_count=excluded.evidence_count,\n                       trend=excluded.trend,\n                       insufficient_reason=excluded.insufficient_reason,\n                       taxonomy_version=excluded.taxonomy_version,\n                       computed_at=excluded.computed_at""",\n                (\n                    driver, self.user_pk, fundamental, signal_status, score, confidence,\n                    evidence_count, trend, insufficient_reason,\n                    scoring_model_version, taxonomy_version, computed_at,\n                ),')
rep(queries['driver_beliefs_select'], '"""SELECT fundamental, signal_status, score, confidence, evidence_count,\n               trend, insufficient_reason, scoring_model_version, taxonomy_version,\n               computed_at\n               FROM driver_beliefs\n               WHERE driver = ? AND owner_user_pk = ?""",\n            (driver, self.user_pk),')

rep(queries['coach_outputs_insert'], '"""INSERT INTO coach_outputs\n                   (driver, car, track, owner_user_pk, payload_version, prompt_version, model,\n                    output_json, created_at)\n                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",\n                (driver, car, track, self.user_pk, payload_version, prompt_version, model,\n                 json.dumps(output_json, sort_keys=True), created_at),')
rep(queries['coach_outputs_select'], '"""SELECT output_pk, output_json FROM coach_outputs\n               WHERE driver=? AND car=? AND track=? AND owner_user_pk=? ORDER BY output_pk""",\n            (driver, car, track, self.user_pk),')

rep(queries['config_history_insert'], '"""INSERT INTO config_history (key, old_value, new_value, source, note, owner_user_pk)\n                   VALUES (?, ?, ?, ?, ?, ?)""",\n                (key, old_value, new_value, source, note, self.user_pk),')
rep(queries['config_history_select'], '"SELECT change_pk, key, old_value, new_value, source, note FROM config_history WHERE owner_user_pk = ? ORDER BY change_pk",\n            (self.user_pk,)\n        ).fetchall():')

with open('src/driverdna/db.py', 'w') as f:
    f.write(code)
