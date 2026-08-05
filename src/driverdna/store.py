"""Where the database lives, and how its address is kept out of the logs.

A SQLite path is not a secret. A Postgres URL is — it carries the database
password — so it joins GARAGE61_TOKEN and ANTHROPIC_API_KEY under the
env-only rule: never written to config, never printed, never logged.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DATABASE_URL_ENV = "DRIVERDNA_DATABASE_URL"

_DSN_CREDENTIALS = re.compile(r"(?P<scheme>\w+://)(?P<userinfo>[^/@]*)@")


def redact_dsn(dsn: str) -> str:
    """A connection string safe to show a human.

    psycopg's own errors happily quote the DSN, so anything that surfaces a
    connection failure — a CLI message, an HTTP error body, a traceback —
    must pass through here first. The username is kept (it is diagnostic and
    not a secret); the password is not.
    """
    def _strip(match: re.Match) -> str:
        userinfo = match.group("userinfo")
        user = userinfo.split(":", 1)[0]
        return f"{match.group('scheme')}{user}:***@" if ":" in userinfo else match.group(0)

    return _DSN_CREDENTIALS.sub(_strip, dsn)


def is_postgres_url(target: Path | str) -> bool:
    return str(target).startswith(("postgresql://", "postgres://"))


def resolve_store(db_path: Path | str | None) -> str:
    """Pick the store: an explicit `--db` wins, then the environment.

    Deliberately no bare `DATABASE_URL` fallback. A generic one left in the
    shell by an unrelated project could silently repoint the instrument at
    the wrong database, and for a tool whose whole value is longitudinal,
    "quietly pointed at the wrong history" is the worst failure available.
    """
    if db_path is not None:
        if not str(db_path).strip():
            raise ValueError(
                "--db was given an empty value — refusing rather than opening "
                "SQLite's private, connection-scoped temporary database "
                "(deleted the instant the connection closes, silently "
                "discarding every write while reporting success). This "
                "usually means a shell interpolated an unset environment "
                "variable into a quoted argument, e.g. --db \"$DRIVERDNA_DATABASE_URL\"."
            )
        return str(db_path)
    url = os.environ.get(DATABASE_URL_ENV)
    if url:
        return url
    return "driverdna.db"


def describe(target: Path | str) -> str:
    """How to name this store in output — never the raw URL."""
    return redact_dsn(str(target)) if is_postgres_url(target) else str(target)


def missing_reason(target: Path | str) -> str | None:
    """Why this store cannot be read yet, or None if it can.

    A SQLite store is missing when its file is absent. A hosted store has no
    file to stat and its schema is created on connect, so "missing" there
    means "no laps imported yet" — the same thing the driver actually needs
    told, which is why both paths end in the same message.
    """
    if is_postgres_url(target):
        return None  # connection failure is reported by Database.open itself
    return None if Path(target).exists() else f"no DB at {target}"


def is_empty(db) -> bool:
    """Whether a reachable store holds no laps yet."""
    return db.conn.execute("SELECT COUNT(*) AS n FROM laps").fetchone()["n"] == 0
