import json
import re

with open('src/driverdna/db.py', 'r') as f:
    code = f.read().replace('\r\n', '\n')

queries = {}

queries['init'] = """    def __init__(
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

queries['open'] = """    @classmethod
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

def extract(key, pattern):
    match = re.search(pattern, code, re.MULTILINE | re.DOTALL)
    if match:
        queries[key] = match.group(0)
    else:
        print(f'FAILED: {key}')

extract('import_lap', r'"""INSERT INTO laps \(lap_id, source_file, driver, car, track, role,\n.*?flags, content_hash, lap_date,\n\s*\),')
extract('load_lap_arrays_legacy_select', r'"SELECT data FROM lap_samples_legacy WHERE lap_pk = \?", \(lap_pk,\)')
extract('retained_lap_pks_1', r'for r in self.conn.execute\("SELECT lap_pk FROM lap_samples_legacy"\):')
extract('retained_lap_pks_2', r'"""SELECT lap_pk, driver, car, track FROM laps\n\s*ORDER BY driver, car, track, lap_pk DESC"""\n\s*\):')
extract('retained_lap_pks_delete', r'"DELETE FROM lap_samples_legacy WHERE lap_pk = \?", \(lap_pk,\)')
extract('dump_blobs_select', r'"SELECT lap_pk, data FROM lap_samples_legacy ORDER BY lap_pk"\n\s*\).fetchall\(\):')
extract('dump_blobs_delete', r'self.conn.execute\("DELETE FROM lap_samples_legacy"\)')

extract('corner_maps_insert', r'"""INSERT INTO corner_maps \(car, track, built_from_n_laps\)\n\s*VALUES \(\?, \?, \?\)""",\n\s*\(car, track, built_from_n_laps\),')
extract('corner_maps_select', r'"SELECT map_pk FROM corner_maps WHERE car=\? AND track=\?",\n\s*\(car, track\),')
extract('corners_select', r'"SELECT corner_pk FROM corners WHERE map_pk=\? AND corner_id=\?",\n\s*\(map_pk, corner_id\),')
extract('corners_update', r'"UPDATE corners SET class=\? WHERE corner_pk=\?", \(cls, corner_pk\)')
extract('corner_observations_select', r'"""SELECT apex_lat, apex_lon, apex_lap_dist FROM corner_observations\n\s*WHERE corner_pk=\? ORDER BY obs_pk""",\n\s*\(corner_pk,\),')
extract('phase_times_select', r'"""SELECT phase, time_s FROM phase_times\n\s*WHERE obs_pk IN \(SELECT obs_pk FROM corner_observations WHERE corner_pk=\?\)\n\s*ORDER BY obs_pk""",\n\s*\(corner_pk,\),')

extract('cohort_laps_stats', r'"""\n\s*SELECT COUNT\(\*\) n, SUM\(duration_s\) d, SUM\(n_samples\) s, MIN\(lap_date\) earliest, MAX\(lap_date\) latest\n\s*FROM laps WHERE car = \? AND track = \? AND role = \'self\'\n\s*""",\n\s*\(car, track\),')
extract('cohort_laps_self', r'WHERE l.car = \? AND l.track = \? AND l.role = \'self\'\n\s*ORDER BY l.lap_pk DESC LIMIT \?\n\s*""",\n\s*\(car, track, limit\),')
extract('cohort_laps_ref', r'WHERE l.car = \? AND l.track = \? AND l.role = \'reference\'\n\s*ORDER BY l.lap_pk DESC\n\s*""",\n\s*\(car, track\),')

extract('find_duplicate', r'WHERE lap_pk IN \(\{placeholders\}\)\n\s*""",\n\s*tuple\(lap_pks\),')
extract('get_cohort_baseline', r'WHERE car = \? AND track = \?\n\s*ORDER BY lap_pk\n\s*""",\n\s*\(car, track\),')

extract('incidents_select', r'FROM incidents\n\s*WHERE lap_pk = \?\n\s*""",\n\s*\(lap_pk,\),')
extract('incidents_insert', r'"""INSERT INTO incidents \(lap_pk, kinds, classification, confidence,\n\s*corner_id, span_start, span_end, onset, min_speed_kmh,\n\s*peak_yaw_rate, rationale, detail\)\n\s*VALUES \(\?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?\)""",\n\s*\(\n\s*lap_pk, "\+".join\(inc.kinds\), inc.classification, inc.confidence,\n\s*inc.corner_id, int\(inc.span_start\), int\(inc.span_end\),\n\s*int\(inc.onset\), float\(inc.min_speed_kmh\),\n\s*float\(inc.peak_yaw_rate\), inc.rationale, inc.detail,\n\s*\),')

extract('garage61_select', r'"SELECT laps_seen, laps_new, last_synced_at FROM garage61_sync_state WHERE driver=\? AND car=\? AND track=\?",\n\s*\(driver, car, track\),')
extract('garage61_upsert', r'"""INSERT INTO garage61_sync_state \(driver, car, track, laps_seen, laps_new, last_synced_at\)\n\s*VALUES \(\?, \?, \?, \?, \?, \?\)\n\s*ON CONFLICT \(driver, car, track\) DO UPDATE SET\n\s*laps_seen=excluded.laps_seen,\n\s*laps_new=excluded.laps_new,\n\s*last_synced_at=excluded.last_synced_at""",\n\s*\(driver, car, track, seen, new, at\),')

extract('chat_transcripts_select', r'"""SELECT role, content, evidence_cited, effects\n\s*FROM chat_transcripts WHERE session_id = \?\n\s*ORDER BY turn_pk""",\n\s*\(session_id,\),')
extract('chat_transcripts_insert', r'"""INSERT INTO chat_transcripts\n\s*\(session_id, bundle_version, role, content, evidence_cited, effects\)\n\s*VALUES \(\?, \?, \?, \?, \?, \?\)""",\n\s*\(\n\s*session_id, bundle_version, role, content,\n\s*json.dumps\(evidence_cited or \[\], sort_keys=True\),\n\s*json.dumps\(effects or \{\}, sort_keys=True\),\n\s*\),')
extract('chat_transcripts_delete', r'"DELETE FROM chat_transcripts WHERE session_id = \?", \(session_id,\)')

extract('driver_beliefs_upsert', r'"""INSERT INTO driver_beliefs\n\s*\(driver, fundamental, signal_status, score, confidence,\n\s*evidence_count, trend, insufficient_reason,\n\s*scoring_model_version, taxonomy_version, computed_at\)\n\s*VALUES \(\?, \?, \?, \?, \?, \?, \?, \?, \?, \?, \?\)\n\s*ON CONFLICT \(driver, fundamental, scoring_model_version\)\n\s*DO UPDATE SET\n\s*signal_status=excluded.signal_status,\n\s*score=excluded.score,\n\s*confidence=excluded.confidence,\n\s*evidence_count=excluded.evidence_count,\n\s*trend=excluded.trend,\n\s*insufficient_reason=excluded.insufficient_reason,\n\s*taxonomy_version=excluded.taxonomy_version,\n\s*computed_at=excluded.computed_at""",\n\s*\(\n\s*driver, fundamental, signal_status, score, confidence,\n\s*evidence_count, trend, insufficient_reason,\n\s*scoring_model_version, taxonomy_version, computed_at,\n\s*\),')
extract('driver_beliefs_select', r'"""SELECT fundamental, signal_status, score, confidence, evidence_count,\n\s*trend, insufficient_reason, scoring_model_version, taxonomy_version,\n\s*computed_at\n\s*FROM driver_beliefs\n\s*WHERE driver = \?""",\n\s*\(driver,\),')

extract('coach_outputs_insert', r'"""INSERT INTO coach_outputs\n\s*\(driver, car, track, payload_version, prompt_version, model,\n\s*output_json, created_at\)\n\s*VALUES \(\?, \?, \?, \?, \?, \?, \?, \?\)""",\n\s*\(driver, car, track, payload_version, prompt_version, model,\n\s*json.dumps\(output_json, sort_keys=True\), created_at\),')
extract('coach_outputs_select', r'"""SELECT output_pk, output_json FROM coach_outputs\n\s*WHERE driver=\? AND car=\? AND track=\? ORDER BY output_pk""",\n\s*\(driver, car, track\),')

extract('config_history_insert', r'"""INSERT INTO config_history \(key, old_value, new_value, source, note\)\n\s*VALUES \(\?, \?, \?, \?, \?\)""",\n\s*\(key, old_value, new_value, source, note\),')
extract('config_history_select', r'"SELECT change_pk, key, old_value, new_value, source, note FROM config_history ORDER BY change_pk"\n\s*\).fetchall\(\):')


with open('queries.json', 'w') as f:
    json.dump(queries, f, indent=2)
