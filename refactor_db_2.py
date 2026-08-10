import re

with open('src/driverdna/db.py', 'r') as f:
    code = f.read()

def repl(pattern, repl_str, code):
    new_code = code.replace(pattern, repl_str)
    if new_code == code:
        print('FAILED TO REPLACE:', pattern[:50])
    return new_code

code = repl(
    'SELECT lap_pk FROM laps WHERE lap_pk IN ({placeholders})',
    'SELECT lap_pk FROM laps WHERE lap_pk IN ({placeholders}) AND owner_user_pk = ?',
    code
)

code = repl(
    '''            _batch(
                lap_pks,
                """
                DELETE FROM laps
                WHERE lap_pk IN ({placeholders})
                """''',
    '''            _batch(
                lap_pks,
                """
                DELETE FROM laps
                WHERE lap_pk IN ({placeholders}) AND owner_user_pk = ?
                """''',
    code
)

code = repl(
    '''            self.conn.execute(
                """
                DELETE FROM laps WHERE lap_pk IN (
                    SELECT lap_pk FROM laps
                    WHERE car = ? AND track = ? AND role = 'self'
                    ORDER BY imported_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (car, track, keep),
            )''',
    '''            self.conn.execute(
                """
                DELETE FROM laps WHERE owner_user_pk = ? AND lap_pk IN (
                    SELECT lap_pk FROM laps
                    WHERE car = ? AND track = ? AND role = 'self' AND owner_user_pk = ?
                    ORDER BY imported_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (self.user_pk, car, track, self.user_pk, keep),
            )''',
    code
)

code = repl(
    '''                self.conn.execute(
                    """
                    INSERT INTO corner_maps (car, track, built_from_n_laps)
                    VALUES (?, ?, ?)
                    """,
                    (car, track, n_laps),
                )''',
    '''                self.conn.execute(
                    """
                    INSERT INTO corner_maps (car, track, built_from_n_laps, owner_user_pk)
                    VALUES (?, ?, ?, ?)
                    """,
                    (car, track, n_laps, self.user_pk),
                )''',
    code
)

code = repl(
    '''        row = self.conn.execute(
            """
            SELECT map_pk, built_from_n_laps
            FROM corner_maps
            WHERE car = ? AND track = ?
            """,
            (car, track),
        ).fetchone()''',
    '''        row = self.conn.execute(
            """
            SELECT map_pk, built_from_n_laps
            FROM corner_maps
            WHERE car = ? AND track = ? AND owner_user_pk = ?
            """,
            (car, track, self.user_pk),
        ).fetchone()''',
    code
)

code = repl(
    '''        rows = self.conn.execute(
            """
            SELECT m.map_pk
            FROM corner_maps m
            WHERE m.car = ? AND m.track = ?
            """,
            (car, track),
        ).fetchall()''',
    '''        rows = self.conn.execute(
            """
            SELECT m.map_pk
            FROM corner_maps m
            WHERE m.car = ? AND m.track = ? AND m.owner_user_pk = ?
            """,
            (car, track, self.user_pk),
        ).fetchall()''',
    code
)

with open('src/driverdna/db.py', 'w') as f:
    f.write(code)

print("done")
