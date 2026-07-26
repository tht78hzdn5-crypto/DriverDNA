"""Shared fixtures, including the opt-in Postgres backend.

The suite must stay runnable with `git clone && python3 -m pytest` — no
secrets, no server, no container. So SQLite always runs and Postgres runs only
when DRIVERDNA_TEST_DATABASE_URL points at a local instance, mirroring the
skip-if-absent convention `test_offline.py` already uses for Chromium.
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit

import pytest

TEST_DATABASE_URL_ENV = "DRIVERDNA_TEST_DATABASE_URL"

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _configured_pg_url() -> str | None:
    """The configured test database, refusing anything non-local.

    This guard is not paranoia. Each Postgres test creates a schema and drops
    it with CASCADE at teardown; pointed at the owner's real Supabase project
    by a stray environment variable, the suite would delete live telemetry.
    A test database must be one you can afford to lose, so it must be local.
    """
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not url:
        return None
    host = urlsplit(url).hostname or ""
    if host not in _LOCAL_HOSTS:
        raise pytest.UsageError(
            f"{TEST_DATABASE_URL_ENV} points at {host!r}, which is not local. "
            "The Postgres tests create and DROP SCHEMA ... CASCADE, so they "
            "refuse to run against a remote database."
        )
    return url


PG_URL = None
try:
    PG_URL = _configured_pg_url()
except pytest.UsageError:
    raise

BACKENDS = ["sqlite"] + (["postgres"] if PG_URL else [])

requires_postgres = pytest.mark.skipif(
    PG_URL is None,
    reason=f"no local Postgres configured (set {TEST_DATABASE_URL_ENV})",
)


@pytest.fixture(params=BACKENDS)
def backend(request):
    return request.param


@pytest.fixture()
def pg_schema():
    """A private schema per test, dropped afterwards.

    Faster than create/drop database and safe to run in parallel, since two
    tests never share a schema name.
    """
    if PG_URL is None:
        pytest.skip("no local Postgres configured")
    import psycopg

    name = f"ddna_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA "{name}"')
    try:
        yield f"{PG_URL}?options=-c%20search_path%3D{name}"
    finally:
        with psycopg.connect(PG_URL, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{name}" CASCADE')


@pytest.fixture()
def store(backend, tmp_path, pg_schema_optional):
    """A connection target for whichever backend is under test."""
    if backend == "sqlite":
        return str(tmp_path / "test.db")
    return pg_schema_optional


@pytest.fixture()
def pg_schema_optional(backend, request):
    """`pg_schema`, but only materialised for the Postgres parameterisation —
    so the SQLite run never touches a database server."""
    if backend != "postgres":
        return None
    return request.getfixturevalue("pg_schema")
