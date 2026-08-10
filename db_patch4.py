import re

with open('src/driverdna/db.py', 'r') as f:
    code = f.read().replace('\r\n', '\n')

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
    ) -> "Database":
        \"\"\"`check_same_thread=False` is for long-lived connections handed
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
        \"\"\"
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
        )"""

new_open = """    @classmethod
    def open(
        cls,
        path: Path | str = ":memory:",
        *,
        check_same_thread: bool = True,
        blob_root: Path | str | None = None,
        user_pk: int = 1,
    ) -> "Database":
        \"\"\"`check_same_thread=False` is for long-lived connections handed
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
        \"\"\"
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
        )"""

code = code.replace(old_open, new_open)

def safe_replace(pattern, repl):
    global code
    if not re.search(pattern, code, re.MULTILINE):
        print(f"FAILED TO MATCH: {pattern[:50]}")
    code = re.sub(pattern, repl, code, count=1, flags=re.MULTILINE)

# import_lap
safe_replace(
    r'INSERT INTO laps \(lap_id, source_file, driver, car, track, role,\s*session_key, run_index, n_samples, duration_s,\s*imported_at, quality_flags, content_hash, lap_date\)\s*VALUES \(\?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?\)',
    r'INSERT INTO laps (lap_id, source_file, driver, car, track, role,\n                                     session_key, run_index, n_samples, duration_s,\n                                     imported_at, quality_flags, content_hash, lap_date,\n                                     owner_user_pk)\n                   VALUES (?, ?, ?, ?, ?, ?,\n                           ?, ?, ?, ?, ?, ?, ?, ?, ?)'
)
safe_replace(
    r'flags, content_hash, lap_date,\s*\),',
    r'flags, content_hash, lap_date, self.user_pk,\n                ),'
)

# _load_lap_arrays_legacy
safe_replace(
    r'SELECT data FROM lap_samples_legacy WHERE lap_pk = \?',
    r'SELECT data FROM lap_samples_legacy WHERE lap_pk = ? AND owner_user_pk = ?'
)
safe_replace(
    r'\("SELECT data FROM lap_samples_legacy WHERE lap_pk = \?", \(lap_pk,\)\)',
    r'("SELECT data FROM lap_samples_legacy WHERE lap_pk = ? AND owner_user_pk = ?", (lap_pk, self.user_pk))'
)

# _retained_lap_pks (1)
safe_replace(
    r'SELECT lap_pk FROM lap_samples_legacy',
    r'SELECT lap_pk FROM lap_samples_legacy WHERE owner_user_pk = ?'
)
safe_replace(
    r'for r in self\.conn\.execute\("SELECT lap_pk FROM lap_samples_legacy"\)',
    r'for r in self.conn.execute("SELECT lap_pk FROM lap_samples_legacy WHERE owner_user_pk = ?", (self.user_pk,))'
)

# retained_lap_pks (2)
safe_replace(
    r'SELECT lap_pk, driver, car, track FROM laps\s*ORDER BY driver, car, track, lap_pk DESC',
    r'SELECT lap_pk, driver, car, track FROM laps\n               WHERE owner_user_pk = ?\n               ORDER BY driver, car, track, lap_pk DESC'
)
safe_replace(
    r'ORDER BY driver, car, track, lap_pk DESC\"\"\"\s*\):',
    r'ORDER BY driver, car, track, lap_pk DESC\"\"\",\n            (self.user_pk,)\n        ):'
)

# DELETE FROM lap_samples_legacy WHERE lap_pk = ?
safe_replace(
    r'"DELETE FROM lap_samples_legacy WHERE lap_pk = \?", \(lap_pk,\)',
    r'"DELETE FROM lap_samples_legacy WHERE lap_pk = ? AND owner_user_pk = ?", (lap_pk, self.user_pk)'
)

# dump_blobs
safe_replace(
    r'SELECT lap_pk, data FROM lap_samples_legacy ORDER BY lap_pk',
    r'SELECT lap_pk, data FROM lap_samples_legacy WHERE owner_user_pk = ? ORDER BY lap_pk'
)
safe_replace(
    r'ORDER BY lap_pk"\s*\)\.fetchall\(\)',
    r'ORDER BY lap_pk",\n            (self.user_pk,)\n        ).fetchall()'
)

# delete FROM lap_samples_legacy
safe_replace(
    r'self\.conn\.execute\("DELETE FROM lap_samples_legacy"\)',
    r'self.conn.execute("DELETE FROM lap_samples_legacy WHERE owner_user_pk = ?", (self.user_pk,))'
)

# INSERT INTO corner_maps
safe_replace(
    r'INSERT INTO corner_maps \(car, track, built_from_n_laps\)\s*VALUES \(\?, \?, \?\)',
    r'INSERT INTO corner_maps (car, track, built_from_n_laps, owner_user_pk)\n                   VALUES (?, ?, ?, ?)'
)
safe_replace(
    r'\(car, track, built_from_n_laps\),\s*"map_pk"',
    r'(car, track, built_from_n_laps, self.user_pk),\n                "map_pk"'
)

# SELECT map_pk FROM corner_maps
safe_replace(
    r'SELECT map_pk FROM corner_maps WHERE car=\? AND track=\?',
    r'SELECT map_pk FROM corner_maps WHERE car=? AND track=? AND owner_user_pk=?'
)
safe_replace(
    r'\(car, track\),',
    r'(car, track, self.user_pk),'
)

# SELECT corner_pk FROM corners
safe_replace(
    r'SELECT corner_pk FROM corners WHERE map_pk=\? AND corner_id=\?',
    r'SELECT c.corner_pk FROM corners c JOIN corner_maps m ON m.map_pk = c.map_pk WHERE c.map_pk=? AND c.corner_id=? AND m.owner_user_pk=?'
)
safe_replace(
    r'\(map_pk, corner_id\),',
    r'(map_pk, corner_id, self.user_pk),'
)

# UPDATE corners
safe_replace(
    r'"UPDATE corners SET class=\? WHERE corner_pk=\?", \(cls, corner_pk\)',
    r'\"\"\"UPDATE corners SET class=? WHERE corner_pk IN (\n                    SELECT c.corner_pk FROM corners c\n                    JOIN corner_maps m ON m.map_pk = c.map_pk\n                    WHERE c.corner_pk=? AND m.owner_user_pk=?\n                )\"\"\",\n                (cls, corner_pk, self.user_pk)'
)

# corner_observations
safe_replace(
    r'SELECT apex_lat, apex_lon, apex_lap_dist FROM corner_observations\s*WHERE corner_pk=\?',
    r'SELECT o.apex_lat, o.apex_lon, o.apex_lap_dist\n               FROM corner_observations o\n               JOIN corners c ON c.corner_pk = o.corner_pk\n               JOIN corner_maps m ON m.map_pk = c.map_pk\n               WHERE o.corner_pk=? AND m.owner_user_pk=?'
)
safe_replace(
    r'WHERE corner_pk=\? ORDER BY obs_pk\"\"\",\s*\(corner_pk,\),',
    r'WHERE o.corner_pk=? AND m.owner_user_pk=?\n               ORDER BY o.obs_pk\"\"\",\n            (corner_pk, self.user_pk),'
)

# phase_times
safe_replace(
    r'SELECT phase, time_s FROM phase_times\s*WHERE obs_pk IN \(SELECT obs_pk FROM corner_observations WHERE corner_pk=\?\)\s*ORDER BY obs_pk',
    r'SELECT p.phase, p.time_s FROM phase_times p\n               JOIN corner_observations o ON o.obs_pk = p.obs_pk\n               JOIN corners c ON c.corner_pk = o.corner_pk\n               JOIN corner_maps m ON m.map_pk = c.map_pk\n               WHERE o.corner_pk=? AND m.owner_user_pk=?\n               ORDER BY p.obs_pk'
)
safe_replace(
    r'ORDER BY obs_pk\"\"\",\s*\(corner_pk,\),',
    r'ORDER BY p.obs_pk\"\"\",\n            (corner_pk, self.user_pk),'
)

# cohort_laps stats
safe_replace(
    r"FROM laps WHERE car = \? AND track = \? AND role = 'self'",
    r"FROM laps WHERE car = ? AND track = ? AND role = 'self' AND owner_user_pk = ?"
)
safe_replace(
    r"AND role = 'self'\\s*\"\"\",\\s*\\(car, track\\),",
    r"AND role = 'self' AND owner_user_pk = ?\n            \"\"\",\n            (car, track, self.user_pk),"
)

# self laps order
safe_replace(
    r"WHERE l\.car = \? AND l\.track = \? AND l\.role = 'self'\s*ORDER BY l\.lap_pk DESC LIMIT \?",
    r"WHERE l.car = ? AND l.track = ? AND l.role = 'self' AND l.owner_user_pk = ?\n        ORDER BY l.lap_pk DESC LIMIT ?"
)
safe_replace(
    r"ORDER BY l\.lap_pk DESC LIMIT \?\s*\"\"\",\s*\(car, track, limit\),",
    r"ORDER BY l.lap_pk DESC LIMIT ?\n        \"\"\",\n        (car, track, self.user_pk, limit),"
)

# reference laps order
safe_replace(
    r"WHERE l\.car = \? AND l\.track = \? AND l\.role = 'reference'\s*ORDER BY l\.lap_pk DESC",
    r"WHERE l.car = ? AND l.track = ? AND l.role = 'reference' AND l.owner_user_pk = ?\n        ORDER BY l.lap_pk DESC"
)
safe_replace(
    r"ORDER BY l\.lap_pk DESC\s*\"\"\",\s*\(car, track\),",
    r"ORDER BY l.lap_pk DESC\n        \"\"\",\n        (car, track, self.user_pk),"
)

# find_duplicate_laps
safe_replace(
    r"WHERE lap_pk IN \({placeholders}\)",
    r"WHERE lap_pk IN ({placeholders}) AND owner_user_pk = ?"
)
safe_replace(
    r"WHERE lap_pk IN \({placeholders}\)\s*\"\"\",\s*tuple\(lap_pks\),",
    r"WHERE lap_pk IN ({placeholders}) AND owner_user_pk = ?\n            \"\"\",\n            (*tuple(lap_pks), self.user_pk),"
)

# get_cohort_baseline
safe_replace(
    r"WHERE car = \? AND track = \?\s*ORDER BY lap_pk",
    r"WHERE car = ? AND track = ? AND owner_user_pk = ?\n            ORDER BY lap_pk"
)
safe_replace(
    r"ORDER BY lap_pk\s*\"\"\",\s*\(car, track\),",
    r"ORDER BY lap_pk\n            \"\"\",\n            (car, track, self.user_pk),"
)

# select incidents
safe_replace(
    r"FROM incidents\s*WHERE lap_pk = \?",
    r"FROM incidents\n            WHERE lap_pk = ? AND owner_user_pk = ?"
)
safe_replace(
    r"WHERE lap_pk = \?\s*\"\"\",\s*\(lap_pk,\),",
    r"WHERE lap_pk = ? AND owner_user_pk = ?\n            \"\"\",\n            (lap_pk, self.user_pk),"
)

# insert incidents
safe_replace(
    r"INSERT INTO incidents \(lap_pk, kinds, classification, confidence, corner_id, span_start, span_end, onset, min_speed_kmh, peak_yaw_rate, rationale, detail\)",
    r"INSERT INTO incidents (lap_pk, kinds, classification, confidence, corner_id, span_start, span_end, onset, min_speed_kmh, peak_yaw_rate, rationale, detail, owner_user_pk)"
)
safe_replace(
    r"rationale, detail\)\s*VALUES \(\?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?\)",
    r"rationale, detail, owner_user_pk)\n            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
safe_replace(
    r"incident\.rationale,\s*incident\.detail,\s*\),",
    r"incident.rationale,\n                incident.detail,\n                self.user_pk,\n            ),"
)

# garage61 select
safe_replace(
    r"WHERE driver=\? AND car=\? AND track=\?",
    r"WHERE driver=? AND car=? AND track=? AND owner_user_pk=?"
)
safe_replace(
    r"WHERE driver=\\? AND car=\\? AND track=\\?\",\\s*\\(driver, car, track\\),",
    r"WHERE driver=? AND car=? AND track=? AND owner_user_pk=?\",\n            (driver, car, track, self.user_pk),"
)

# garage61 upsert
safe_replace(
    r"INSERT INTO garage61_sync_state \(driver, car, track, laps_seen, laps_new, last_synced_at\)\s*VALUES \(\?, \?, \?, \?, \?, \?\)\s*ON CONFLICT \(driver, car, track\)",
    r"INSERT INTO garage61_sync_state (driver, car, track, laps_seen, laps_new, last_synced_at, owner_user_pk)\n                   VALUES (?, ?, ?, ?, ?, ?, ?)\n                   ON CONFLICT (owner_user_pk, driver, car, track)"
)
safe_replace(
    r"VALUES \(\?, \?, \?, \?, \?, \?\)",
    r"VALUES (?, ?, ?, ?, ?, ?, ?)"
)
safe_replace(
    r"\(driver, car, track, seen, new, at\),",
    r"(driver, car, track, seen, new, at, self.user_pk),"
)

# chat transcripts select
safe_replace(
    r"FROM chat_transcripts WHERE session_id = \?",
    r"FROM chat_transcripts WHERE session_id = ? AND owner_user_pk = ?"
)
safe_replace(
    r"FROM chat_transcripts WHERE session_id = \?\s*ORDER BY turn_pk\"\"\",\s*\(session_id,\),",
    r"FROM chat_transcripts WHERE session_id = ? AND owner_user_pk = ?\n               ORDER BY turn_pk\"\"\",\n            (session_id, self.user_pk),"
)

# chat transcripts insert
safe_replace(
    r"INSERT INTO chat_transcripts\s*\(session_id, bundle_version, role, content, evidence_cited, effects\)\s*VALUES \(\?, \?, \?, \?, \?, \?\)",
    r"INSERT INTO chat_transcripts\n                   (session_id, owner_user_pk, bundle_version, role, content, evidence_cited, effects)\n                   VALUES (?, ?, ?, ?, ?, ?, ?)"
)
safe_replace(
    r"\(\s*session_id,\s*bundle_version,",
    r"(\n                    session_id,\n                    self.user_pk,\n                    bundle_version,"
)

# chat transcripts delete
safe_replace(
    r'"DELETE FROM chat_transcripts WHERE session_id = \?", \(session_id,\)',
    r'"DELETE FROM chat_transcripts WHERE session_id = ? AND owner_user_pk = ?", (session_id, self.user_pk)'
)

# driver beliefs upsert
safe_replace(
    r"INSERT INTO driver_beliefs \(driver, fundamental, signal_status, score, confidence, evidence_count, trend, insufficient_reason, scoring_model_version, taxonomy_version, computed_at\)",
    r"INSERT INTO driver_beliefs (driver, owner_user_pk, fundamental, signal_status, score, confidence, evidence_count, trend, insufficient_reason, scoring_model_version, taxonomy_version, computed_at)"
)
safe_replace(
    r"VALUES \(\?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?\)\s*ON CONFLICT\s*\(driver, fundamental, scoring_model_version\)",
    r"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                   ON CONFLICT(owner_user_pk, driver, fundamental, scoring_model_version)"
)
safe_replace(
    r"\(\s*driver,\s*b\.fundamental,",
    r"(\n                        driver,\n                        self.user_pk,\n                        b.fundamental,"
)

# driver beliefs select
safe_replace(
    r"FROM driver_beliefs\s*WHERE driver = \?",
    r"FROM driver_beliefs\n               WHERE driver = ? AND owner_user_pk = ?"
)
safe_replace(
    r"WHERE driver = \?\"\"\",\s*\(driver,\),",
    r"WHERE driver = ? AND owner_user_pk = ?\"\"\",\n            (driver, self.user_pk),"
)

# coach outputs insert
safe_replace(
    r"INSERT INTO coach_outputs\s*\(driver, car, track, payload_version, prompt_version, model, output_json, created_at\)\s*VALUES \(\?, \?, \?, \?, \?, \?, \?, \?\)",
    r"INSERT INTO coach_outputs\n                   (driver, car, track, owner_user_pk, payload_version, prompt_version, model, output_json, created_at)\n                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
safe_replace(
    r"\(\s*driver,\s*car,\s*track,\s*payload_version,",
    r"(\n                    driver,\n                    car,\n                    track,\n                    self.user_pk,\n                    payload_version,"
)

# coach outputs select
safe_replace(
    r"WHERE driver = \? AND car = \? AND track = \?",
    r"WHERE driver = ? AND car = ? AND track = ? AND owner_user_pk = ?"
)
safe_replace(
    r"WHERE driver = \? AND car = \? AND track = \?\s*ORDER BY output_pk DESC LIMIT 1\"\"\",\s*\(driver, car, track\),",
    r"WHERE driver = ? AND car = ? AND track = ? AND owner_user_pk = ?\n               ORDER BY output_pk DESC LIMIT 1\"\"\",\n            (driver, car, track, self.user_pk),"
)

# config history insert
safe_replace(
    r"INSERT INTO config_history \(key, old_value, new_value, source, note\)\s*VALUES \(\?, \?, \?, \?, \?\)",
    r"INSERT INTO config_history (key, old_value, new_value, source, note, owner_user_pk)\n                   VALUES (?, ?, ?, ?, ?, ?)"
)
safe_replace(
    r"\(key, old_value, new_value, source, note\)",
    r"(key, old_value, new_value, source, note, self.user_pk)"
)

# config history select
safe_replace(
    r"SELECT change_pk, key, old_value, new_value, source, note FROM config_history ORDER BY change_pk",
    r"SELECT change_pk, key, old_value, new_value, source, note FROM config_history WHERE owner_user_pk = ? ORDER BY change_pk"
)
safe_replace(
    r"ORDER BY change_pk\"\s*\)\.fetchall\(\)",
    r"ORDER BY change_pk\",\n            (self.user_pk,)\n        ).fetchall()"
)

with open('src/driverdna/db.py', 'w') as f:
    f.write(code)
