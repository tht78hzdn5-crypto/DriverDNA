import re

with open('src/driverdna/db.py', 'r') as f:
    code = f.read()

# Replace import_lap
code = code.replace(
    '''            """
            INSERT INTO laps (
                lap_id, source_file, driver, car, track, role, session_key, run_index,
                n_samples, duration_s, imported_at, quality_flags, content_hash, lap_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lap.lap_id, lap.source_file, lap.driver, lap.car, lap.track,
                lap.role, lap.session_key, lap.run_index, lap.n_samples,
                lap.duration_s, lap.imported_at, json.dumps(lap.quality_flags),
                _content_hash(lap), lap.lap_date,
            ),''',
    '''            """
            INSERT INTO laps (
                lap_id, source_file, driver, car, track, role, session_key, run_index,
                n_samples, duration_s, imported_at, quality_flags, content_hash, lap_date, owner_user_pk
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lap.lap_id, lap.source_file, lap.driver, lap.car, lap.track,
                lap.role, lap.session_key, lap.run_index, lap.n_samples,
                lap.duration_s, lap.imported_at, json.dumps(lap.quality_flags),
                _content_hash(lap), lap.lap_date, self.user_pk,
            ),'''
)

code = code.replace(
    'SELECT lap_pk FROM laps WHERE content_hash = ? AND source_file != ?',
    'SELECT lap_pk FROM laps WHERE content_hash = ? AND source_file != ? AND owner_user_pk = ?'
)

code = code.replace(
    '''        row = self.conn.execute(
            "SELECT lap_pk FROM laps WHERE source_file = ?", (lap.source_file,)
        ).fetchone()''',
    '''        row = self.conn.execute(
            "SELECT lap_pk FROM laps WHERE source_file = ? AND owner_user_pk = ?", (lap.source_file, self.user_pk)
        ).fetchone()'''
)

code = code.replace(
    '''                    "SELECT lap_pk FROM laps WHERE content_hash = ? AND source_file != ?",
                    (_content_hash(lap), lap.source_file),''',
    '''                    "SELECT lap_pk FROM laps WHERE content_hash = ? AND source_file != ? AND owner_user_pk = ?",
                    (_content_hash(lap), lap.source_file, self.user_pk),'''
)


with open('src/driverdna/db.py', 'w') as f:
    f.write(code)
