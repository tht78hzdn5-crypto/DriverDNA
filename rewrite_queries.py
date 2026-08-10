import os

with open('src/driverdna/db.py', 'r') as f:
    code = f.read()

replacements = [
    # import_lap
    (
        '''                """INSERT INTO laps (lap_id, source_file, driver, car, track, role,
                                     session_key, run_index, n_samples, duration_s,
                                     imported_at, quality_flags, content_hash, lap_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lap.lap_id, str(lap.source_path), driver, car, track, role,
                    session_key, run_index, lap.n_samples, lap.duration_s, imported_at,
                    flags, content_hash, lap_date,
                ),''',
        '''                """INSERT INTO laps (lap_id, source_file, driver, car, track, role,
                                     session_key, run_index, n_samples, duration_s,
                                     imported_at, quality_flags, content_hash, lap_date,
                                     owner_user_pk)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lap.lap_id, str(lap.source_path), driver, car, track, role,
                    session_key, run_index, lap.n_samples, lap.duration_s, imported_at,
                    flags, content_hash, lap_date, self.user_pk,
                ),'''
    ),
    (
        '''        row = self.conn.execute(
            "SELECT data FROM lap_samples_legacy WHERE lap_pk = ?", (lap_pk,)
        ).fetchone()''',
        '''        row = self.conn.execute(
            "SELECT data FROM lap_samples_legacy WHERE lap_pk = ? AND owner_user_pk = ?", (lap_pk, self.user_pk)
        ).fetchone()'''
    ),
    (
        '''        if self._has_legacy_blobs():
            held |= {
                int(r["lap_pk"])
                for r in self.conn.execute("SELECT lap_pk FROM lap_samples_legacy")
            }''',
        '''        if self._has_legacy_blobs():
            held |= {
                int(r["lap_pk"])
                for r in self.conn.execute("SELECT lap_pk FROM lap_samples_legacy WHERE owner_user_pk = ?", (self.user_pk,))
            }'''
    ),
    (
        '''        for r in self.conn.execute(
            """SELECT lap_pk, driver, car, track FROM laps
               ORDER BY driver, car, track, lap_pk DESC"""
        ):''',
        '''        for r in self.conn.execute(
            """SELECT lap_pk, driver, car, track FROM laps
               WHERE owner_user_pk = ?
               ORDER BY driver, car, track, lap_pk DESC""",
            (self.user_pk,)
        ):'''
    ),
    (
        '''                        self.conn.execute(
                            "DELETE FROM lap_samples_legacy WHERE lap_pk = ?", (lap_pk,)
                        )''',
        '''                        self.conn.execute(
                            "DELETE FROM lap_samples_legacy WHERE lap_pk = ? AND owner_user_pk = ?", (lap_pk, self.user_pk)
                        )'''
    ),
    (
        '''        for r in self.conn.execute(
            "SELECT lap_pk, data FROM lap_samples_legacy ORDER BY lap_pk"
        ).fetchall():''',
        '''        for r in self.conn.execute(
            "SELECT lap_pk, data FROM lap_samples_legacy WHERE owner_user_pk = ? ORDER BY lap_pk",
            (self.user_pk,)
        ).fetchall():'''
    ),
    (
        '''        with self.conn:
            self.conn.execute("DELETE FROM lap_samples_legacy")''',
        '''        with self.conn:
            self.conn.execute("DELETE FROM lap_samples_legacy WHERE owner_user_pk = ?", (self.user_pk,))'''
    ),
    (
        '''            map_pk = self._insert_returning(
                """INSERT INTO corner_maps (car, track, built_from_n_laps)
                   VALUES (?, ?, ?)""",
                (car, track, built_from_n_laps),
                "map_pk",
            )''',
        '''            map_pk = self._insert_returning(
                """INSERT INTO corner_maps (car, track, built_from_n_laps, owner_user_pk)
                   VALUES (?, ?, ?, ?)""",
                (car, track, built_from_n_laps, self.user_pk),
                "map_pk",
            )'''
    ),
    (
        '''        row = self.conn.execute(
            "SELECT map_pk FROM corner_maps WHERE car=? AND track=?",
            (car, track),
        ).fetchone()''',
        '''        row = self.conn.execute(
            "SELECT map_pk FROM corner_maps WHERE car=? AND track=? AND owner_user_pk=?",
            (car, track, self.user_pk),
        ).fetchone()'''
    ),
    (
        '''        row = self.conn.execute(
            "SELECT corner_pk FROM corners WHERE map_pk=? AND corner_id=?",
            (map_pk, corner_id),
        ).fetchone()''',
        '''        row = self.conn.execute(
            """SELECT c.corner_pk FROM corners c
               JOIN corner_maps m ON m.map_pk = c.map_pk
               WHERE c.map_pk=? AND c.corner_id=? AND m.owner_user_pk=?""",
            (map_pk, corner_id, self.user_pk),
        ).fetchone()'''
    ),
    (
        '''            self.conn.execute(
                "UPDATE corners SET class=? WHERE corner_pk=?", (cls, corner_pk)
            )''',
        '''            self.conn.execute(
                """UPDATE corners SET class=? WHERE corner_pk IN (
                    SELECT c.corner_pk FROM corners c
                    JOIN corner_maps m ON m.map_pk = c.map_pk
                    WHERE c.corner_pk=? AND m.owner_user_pk=?
                )""",
                (cls, corner_pk, self.user_pk)
            )'''
    ),
    (
        '''        rows = self.conn.execute(
            """SELECT apex_lat, apex_lon, apex_lap_dist FROM corner_observations
               WHERE corner_pk=? ORDER BY obs_pk""",
            (corner_pk,),
        ).fetchall()''',
        '''        rows = self.conn.execute(
            """SELECT o.apex_lat, o.apex_lon, o.apex_lap_dist
               FROM corner_observations o
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN corner_maps m ON m.map_pk = c.map_pk
               WHERE o.corner_pk=? AND m.owner_user_pk=?
               ORDER BY o.obs_pk""",
            (corner_pk, self.user_pk),
        ).fetchall()'''
    ),
    (
        '''        rows = self.conn.execute(
            """SELECT phase, time_s FROM phase_times
               WHERE obs_pk IN (SELECT obs_pk FROM corner_observations WHERE corner_pk=?)
               ORDER BY obs_pk""",
            (corner_pk,),
        ).fetchall()''',
        '''        rows = self.conn.execute(
            """SELECT p.phase, p.time_s FROM phase_times p
               JOIN corner_observations o ON o.obs_pk = p.obs_pk
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN corner_maps m ON m.map_pk = c.map_pk
               WHERE o.corner_pk=? AND m.owner_user_pk=?
               ORDER BY p.obs_pk""",
            (corner_pk, self.user_pk),
        ).fetchall()'''
    ),
    (
        '''        rows = self.conn.execute(
            """
            SELECT COUNT(*) n, SUM(duration_s) d, SUM(n_samples) s, MIN(lap_date) earliest, MAX(lap_date) latest
            FROM laps WHERE car = ? AND track = ? AND role = 'self'
            """,
            (car, track),
        ).fetchall()''',
        '''        rows = self.conn.execute(
            """
            SELECT COUNT(*) n, SUM(duration_s) d, SUM(n_samples) s, MIN(lap_date) earliest, MAX(lap_date) latest
            FROM laps WHERE car = ? AND track = ? AND role = 'self' AND owner_user_pk = ?
            """,
            (car, track, self.user_pk),
        ).fetchall()'''
    ),
    (
        '''        WHERE l.car = ? AND l.track = ? AND l.role = 'self'
        ORDER BY l.lap_pk DESC LIMIT ?
        """,
        (car, track, limit),
    )''',
        '''        WHERE l.car = ? AND l.track = ? AND l.role = 'self' AND l.owner_user_pk = ?
        ORDER BY l.lap_pk DESC LIMIT ?
        """,
        (car, track, self.user_pk, limit),
    )'''
    ),
    (
        '''        WHERE l.car = ? AND l.track = ? AND l.role = 'reference'
        ORDER BY l.lap_pk DESC
        """,
        (car, track),
    )''',
        '''        WHERE l.car = ? AND l.track = ? AND l.role = 'reference' AND l.owner_user_pk = ?
        ORDER BY l.lap_pk DESC
        """,
        (car, track, self.user_pk),
    )'''
    ),
    (
        '''            WHERE lap_pk IN ({placeholders})
            """,
            tuple(lap_pks),
        )''',
        '''            WHERE lap_pk IN ({placeholders}) AND owner_user_pk = ?
            """,
            (*tuple(lap_pks), self.user_pk),
        )'''
    ),
    (
        '''            WHERE car = ? AND track = ?
            ORDER BY lap_pk
            """,
            (car, track),
        )''',
        '''            WHERE car = ? AND track = ? AND owner_user_pk = ?
            ORDER BY lap_pk
            """,
            (car, track, self.user_pk),
        )'''
    ),
    (
        '''            SELECT corner_id, kinds, classification, confidence, span_start, span_end, onset, min_speed_kmh, peak_yaw_rate, rationale, detail
            FROM incidents
            WHERE lap_pk = ?
            """,
            (lap_pk,),
        )''',
        '''            SELECT corner_id, kinds, classification, confidence, span_start, span_end, onset, min_speed_kmh, peak_yaw_rate, rationale, detail
            FROM incidents
            WHERE lap_pk = ? AND owner_user_pk = ?
            """,
            (lap_pk, self.user_pk),
        )'''
    ),
    (
        '''            INSERT INTO incidents (lap_pk, kinds, classification, confidence, corner_id, span_start, span_end, onset, min_speed_kmh, peak_yaw_rate, rationale, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lap_pk,
                ",".join(incident.kinds),
                incident.classification,
                incident.confidence,
                incident.corner_id,
                incident.span[0],
                incident.span[1],
                incident.onset,
                incident.min_speed_kmh,
                incident.peak_yaw_rate,
                incident.rationale,
                incident.detail,
            ),
        )''',
        '''            INSERT INTO incidents (lap_pk, kinds, classification, confidence, corner_id, span_start, span_end, onset, min_speed_kmh, peak_yaw_rate, rationale, detail, owner_user_pk)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lap_pk,
                ",".join(incident.kinds),
                incident.classification,
                incident.confidence,
                incident.corner_id,
                incident.span[0],
                incident.span[1],
                incident.onset,
                incident.min_speed_kmh,
                incident.peak_yaw_rate,
                incident.rationale,
                incident.detail,
                self.user_pk,
            ),
        )'''
    ),
    (
        '''        row = self.conn.execute(
            "SELECT laps_seen, laps_new, last_synced_at FROM garage61_sync_state WHERE driver=? AND car=? AND track=?",
            (driver, car, track),
        ).fetchone()''',
        '''        row = self.conn.execute(
            "SELECT laps_seen, laps_new, last_synced_at FROM garage61_sync_state WHERE driver=? AND car=? AND track=? AND owner_user_pk=?",
            (driver, car, track, self.user_pk),
        ).fetchone()'''
    ),
    (
        '''        with self.conn:
            self.conn.execute(
                """INSERT INTO garage61_sync_state (driver, car, track, laps_seen, laps_new, last_synced_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (driver, car, track) DO UPDATE SET
                       laps_seen=excluded.laps_seen,
                       laps_new=excluded.laps_new,
                       last_synced_at=excluded.last_synced_at""",
                (driver, car, track, seen, new, at),
            )''',
        '''        with self.conn:
            self.conn.execute(
                """INSERT INTO garage61_sync_state (driver, car, track, laps_seen, laps_new, last_synced_at, owner_user_pk)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (driver, car, track, owner_user_pk) DO UPDATE SET
                       laps_seen=excluded.laps_seen,
                       laps_new=excluded.laps_new,
                       last_synced_at=excluded.last_synced_at""",
                (driver, car, track, seen, new, at, self.user_pk),
            )'''
    ),
    (
        '''        rows = self.conn.execute(
            """SELECT role, content, evidence_cited, effects
               FROM chat_transcripts WHERE session_id = ?
               ORDER BY turn_pk""",
            (session_id,),
        ).fetchall()''',
        '''        rows = self.conn.execute(
            """SELECT role, content
               FROM chat_transcripts WHERE session_id = ? AND owner_user_pk = ?
               ORDER BY index_in_session""",
            (session_id, self.user_pk),
        ).fetchall()'''
    ),
    (
        '''        with self.conn:
            self.conn.execute(
                """INSERT INTO chat_transcripts
                   (session_id, bundle_version, role, content, evidence_cited, effects)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    bundle_version,
                    role,
                    content,
                    json.dumps(evidence) if evidence else None,
                    json.dumps(effects) if effects else None,
                ),
            )''',
        '''        with self.conn:
            row = self.conn.execute("SELECT MAX(index_in_session) m FROM chat_transcripts WHERE session_id = ? AND owner_user_pk = ?", (session_id, self.user_pk)).fetchone()
            idx = (row["m"] or 0) + 1
            self.conn.execute(
                """INSERT INTO chat_transcripts
                   (session_id, owner_user_pk, index_in_session, role, content)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    session_id,
                    self.user_pk,
                    idx,
                    role,
                    content,
                ),
            )'''
    ),
    (
        '''        with self.conn:
            self.conn.execute("DELETE FROM chat_transcripts WHERE session_id = ?", (session_id,))''',
        '''        with self.conn:
            self.conn.execute("DELETE FROM chat_transcripts WHERE session_id = ? AND owner_user_pk = ?", (session_id, self.user_pk))'''
    ),
    (
        '''        with self.conn:
            for b in new_beliefs:
                self.conn.execute(
                    """INSERT INTO driver_beliefs (driver, fundamental, signal_status, score, confidence, evidence_count, trend, insufficient_reason, scoring_model_version, taxonomy_version, computed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(driver, fundamental, scoring_model_version) DO UPDATE SET
                           signal_status=excluded.signal_status,
                           score=excluded.score,
                           confidence=excluded.confidence,
                           evidence_count=excluded.evidence_count,
                           trend=excluded.trend,
                           insufficient_reason=excluded.insufficient_reason,
                           taxonomy_version=excluded.taxonomy_version,
                           computed_at=excluded.computed_at""",
                    (
                        driver,
                        b.fundamental,
                        b.signal_status,
                        b.score,
                        b.confidence,
                        b.evidence_count,
                        b.trend,
                        b.insufficient_reason,
                        b.scoring_model_version,
                        b.taxonomy_version,
                        b.computed_at,
                    ),
                )''',
        '''        with self.conn:
            for b in new_beliefs:
                self.conn.execute(
                    """INSERT INTO driver_beliefs (driver, fundamental, score, confidence, evidence_count, scoring_model_version, updated_at, owner_user_pk)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(owner_user_pk, driver, fundamental, scoring_model_version) DO UPDATE SET
                           score=excluded.score,
                           confidence=excluded.confidence,
                           evidence_count=excluded.evidence_count,
                           updated_at=excluded.updated_at""",
                    (
                        driver,
                        b.fundamental,
                        b.score,
                        b.confidence,
                        b.evidence_count,
                        b.scoring_model_version,
                        b.computed_at,
                        self.user_pk,
                    ),
                )'''
    ),
    (
        '''        rows = self.conn.execute(
            """SELECT fundamental, signal_status, score, confidence, evidence_count, trend, insufficient_reason, scoring_model_version, taxonomy_version, computed_at
               FROM driver_beliefs
               WHERE driver = ?""",
            (driver,),
        ).fetchall()''',
        '''        rows = self.conn.execute(
            """SELECT fundamental, score, confidence, evidence_count, scoring_model_version, updated_at as computed_at
               FROM driver_beliefs
               WHERE driver = ? AND owner_user_pk = ?""",
            (driver, self.user_pk),
        ).fetchall()'''
    ),
    (
        '''        with self.conn:
            self.conn.execute(
                """INSERT INTO coach_outputs
                   (driver, car, track, payload_version, prompt_version, model, output_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    driver,
                    car,
                    track,
                    payload_version,
                    prompt_version,
                    model,
                    json.dumps(asdict(output)),
                    created_at,
                ),
            )''',
        '''        with self.conn:
            self.conn.execute(
                """INSERT INTO coach_outputs
                   (driver, car, track, owner_user_pk, focus, explanation, drills, session_context, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(owner_user_pk, driver, car, track) DO UPDATE SET
                       focus=excluded.focus,
                       explanation=excluded.explanation,
                       drills=excluded.drills,
                       session_context=excluded.session_context,
                       updated_at=excluded.updated_at""",
                (
                    driver,
                    car,
                    track,
                    self.user_pk,
                    output.focus,
                    output.explanation,
                    "[]",
                    "{}",
                    created_at,
                ),
            )'''
    ),
    (
        '''        row = self.conn.execute(
            """SELECT output_json, created_at FROM coach_outputs
               WHERE driver = ? AND car = ? AND track = ?
               ORDER BY output_pk DESC LIMIT 1""",
            (driver, car, track),
        ).fetchone()''',
        '''        row = self.conn.execute(
            """SELECT focus, explanation, drills, session_context, updated_at as created_at FROM coach_outputs
               WHERE driver = ? AND car = ? AND track = ? AND owner_user_pk = ?""",
            (driver, car, track, self.user_pk),
        ).fetchone()'''
    ),
    (
        '''        rows = self.conn.execute(
            "SELECT change_pk, key, old_value, new_value, source, note FROM config_history ORDER BY change_pk"
        ).fetchall()''',
        '''        rows = self.conn.execute(
            "SELECT change_pk, applied_at as old_value, snapshot_json as new_value, change_reason as note FROM config_history WHERE owner_user_pk = ? ORDER BY change_pk",
            (self.user_pk,)
        ).fetchall()'''
    ),
    (
        '''        with self.conn:
            self.conn.execute(
                """INSERT INTO config_history (key, old_value, new_value, source, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, old, new, source, note),
            )''',
        '''        with self.conn:
            self.conn.execute(
                """INSERT INTO config_history (owner_user_pk, applied_at, snapshot_json, proposal_json, change_reason, reverts_change_pk)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (self.user_pk, "now", new, "{}", note, None),
            )'''
    )
]

for target, replacement in replacements:
    code = code.replace(target, replacement)

with open('src/driverdna/db.py', 'w') as f:
    f.write(code)
