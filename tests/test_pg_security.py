"""Supabase hardening: the telemetry must not be reachable from the internet.

Supabase automatically exposes the `public` schema over PostgREST, and the
anon key that grants it ships in every project. A table sitting in `public`
without row-level security is readable at
`https://<project>.supabase.co/rest/v1/<table>` by anyone who has that key —
so `laps`, `chat_transcripts` and `driver_beliefs` there would publish the
driver's telemetry and coaching conversations to an unauthenticated endpoint,
while README.md advertises the opposite.

Two independent layers, both asserted here: the tables live in a `driverdna`
schema that PostgREST does not expose by default, and RLS is enabled with no
policies so that even a role holding an explicit SELECT grant reads nothing.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import PG_URL, requires_postgres
from driverdna.db import PG_SCHEMA, Database

pytestmark = requires_postgres


@pytest.fixture()
def fresh_database():
    """A throwaway *database* rather than a schema.

    The namespace behaviour is what is under test, so the DSN must not
    pre-select a schema the way the shared `pg_schema` fixture does.
    """
    import psycopg

    name = f"ddna_sec_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base = PG_URL.rsplit("/", 1)[0]
    try:
        yield f"{base}/{name}"
    finally:
        with psycopg.connect(PG_URL, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s",
                (name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


def test_tables_land_in_the_driverdna_schema_not_public(fresh_database, tmp_path):
    with Database.open(fresh_database, blob_root=tmp_path) as db:
        assert db.conn.execute(
            "SELECT current_schema() AS s"
        ).fetchone()["s"] == PG_SCHEMA

        in_public = db.conn.execute(
            "SELECT count(*) AS n FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()["n"]
        assert in_public == 0, "tables in `public` are exposed over PostgREST"

        in_ours = db.conn.execute(
            "SELECT count(*) AS n FROM pg_tables WHERE schemaname = ?",
            (PG_SCHEMA,),
        ).fetchone()["n"]
        assert in_ours >= 16


def test_every_table_has_rls_enabled_and_no_policies(fresh_database, tmp_path):
    with Database.open(fresh_database, blob_root=tmp_path) as db:
        unprotected = [
            r["tablename"]
            for r in db.conn.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = ? AND NOT rowsecurity",
                (PG_SCHEMA,),
            )
        ]
        assert unprotected == [], f"tables without RLS: {unprotected}"

        # Zero policies is the point: RLS with no policy denies every role
        # except the owner. A policy added by accident would open a door.
        policies = db.conn.execute(
            "SELECT count(*) AS n FROM pg_policies WHERE schemaname = ?",
            (PG_SCHEMA,),
        ).fetchone()["n"]
        assert policies == 0


def test_an_anon_role_reads_nothing_even_with_select_granted(fresh_database, tmp_path):
    """The behavioural proof, standing in for Supabase's `anon`.

    Granting SELECT is deliberate — it shows the namespace is not the only
    thing protecting the data. Without RLS this role would read every lap.
    """
    with Database.open(fresh_database, blob_root=tmp_path) as db:
        db.conn.execute("CREATE ROLE anon_probe NOLOGIN")
        db.conn.execute(f'GRANT USAGE ON SCHEMA "{PG_SCHEMA}" TO anon_probe')
        db.conn.execute(
            f'GRANT SELECT ON ALL TABLES IN SCHEMA "{PG_SCHEMA}" TO anon_probe'
        )
        db.conn.execute(
            """INSERT INTO laps (owner_user_pk, source_file, driver, car, track, role,
                                 n_samples, duration_s, quality_flags)
               VALUES (1, 'secret.csv', 'owner', 'GR86', 'Spa', 'self', 1, 1.0, '[]')"""
        )
        assert db.conn.execute("SELECT count(*) AS n FROM laps").fetchone()["n"] == 1

        db.conn.execute("SET ROLE anon_probe")
        try:
            for table in ("laps", "chat_transcripts", "driver_beliefs"):
                seen = db.conn.execute(
                    f"SELECT count(*) AS n FROM {table}"
                ).fetchone()["n"]
                assert seen == 0, f"anon role could read {table}"
        finally:
            db.conn.execute("RESET ROLE")
            db.conn.execute("DROP OWNED BY anon_probe")
            db.conn.execute("DROP ROLE anon_probe")


def test_an_explicit_schema_choice_is_not_overridden(pg_schema, tmp_path):
    """A DSN that already selects a schema means it — the test harness gives
    each test its own, and hijacking that would break isolation."""
    with Database.open(pg_schema, blob_root=tmp_path) as db:
        current = db.conn.execute("SELECT current_schema() AS s").fetchone()["s"]
        assert current.startswith("ddna_test_")
        assert current != PG_SCHEMA


def test_connection_failure_never_prints_the_password():
    """psycopg's own errors quote the DSN, so the wrapper must redact before
    the message reaches a log, a CLI message or an HTTP body."""
    bad = "postgresql://someone:hunter2@127.0.0.1:1/nope"
    with pytest.raises(RuntimeError) as exc:
        Database.open(bad)
    assert "hunter2" not in str(exc.value)
    assert "***" in str(exc.value)
