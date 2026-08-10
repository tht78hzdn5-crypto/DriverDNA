import re

with open('src/driverdna/db.py', 'r') as f:
    code = f.read()

migration_007 = """    \"\"\"
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
    \"\"\",
"""

if "CREATE TABLE laps_new" not in code:
    print("Migration 008 not found, appending to end of _MIGRATIONS")
    code = code.replace('    """,\n]\n', '    """,\n' + migration_007 + ']\n')
else:
    code = code.replace('    """\n    -- Phase 2: Data Partitioning', migration_007 + '    """\n    -- Phase 2: Data Partitioning')

with open('src/driverdna/db.py', 'w') as f:
    f.write(code)
