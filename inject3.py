import re

with open('src/driverdna/db.py', 'r') as f:
    code = f.read()

m1 = open('phase1.py').read().split('migration_007 = """')[1].split('""",')[0]
m2 = open('migration008.txt').read()

target = '    """\n    ALTER TABLE lap_samples RENAME TO lap_samples_legacy;\n    """,\n)'

replacement = '    """\n    ALTER TABLE lap_samples RENAME TO lap_samples_legacy;\n    """,\n    """' + m1 + '    """,\n    """\n' + m2 + '    """,\n)'

code = code.replace(target, replacement)

# Now replace the Database class initialization
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

with open('src/driverdna/db.py', 'w') as f:
    f.write(code)
