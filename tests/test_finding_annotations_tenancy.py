"""BUG-031: `finding_annotations` was never partitioned, and finding IDs
carry no tenant term. So on any car/track two beta users share, one
driver's annotation used to suppress the other's finding and leak its
free-text note into their chat bundle — the exact "evidence-ID collisions
across tenants" hazard `docs/ACCOUNTS-SPEC.md:257-259` named as needing
proof, not assumption.

These are the pinning tests for the fix (SPEC.md A53). They run at the DB
layer rather than through the HTTP surface, because the bug lives in
`db.annotate_finding` / `db.annotations()` / `db.clear_annotation` — the
API handler is a thin wrapper. That also isolates this from other API
concerns (auth setup, rate limiting) and keeps a Red run readable.

Not covered here (separate work):
- A comprehensive route-enumerated cross-tenant gate — BUG-036, next PR.
  It will re-assert the property from the HTTP layer.
- Whether `finding_id`'s own shape should carry a tenant term. A53 decided
  no; the guard test below pins the *substitute* — no new table may key
  on a bare `finding_id` — so the next table to use one cannot repeat
  this defect.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from driverdna.db import Database, MIGRATIONS


FINDING_ID = "vs-self:GR86:Spa-Francorchamps:C01:mid:opportunity"


def _seed_users(db_path: Path) -> tuple[int, int]:
    """Two users, returned as their user_pks. Migration 008 already seeds
    the placeholder owner row at user_pk=1; we add two real ones."""
    with Database.open(db_path) as db:
        with db.conn:
            a = db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?) "
                "RETURNING user_pk",
                ("alice@example.com", "hash-a"),
            ).fetchone()["user_pk"]
            b = db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?) "
                "RETURNING user_pk",
                ("bob@example.com", "hash-b"),
            ).fetchone()["user_pk"]
    return int(a), int(b)


def test_two_users_can_annotate_the_same_finding_id_without_seeing_each_other(tmp_path):
    """The core defect. Before the fix `finding_annotations` had
    `UNIQUE(finding_id)`, so the second user's INSERT `ON CONFLICT`
    overwrote the first user's row — and `annotations()` had no owner
    filter, so both users read one row back regardless of who wrote it.
    """
    db_path = tmp_path / "tenancy.db"
    a_pk, b_pk = _seed_users(db_path)

    # Alice annotates first.
    with Database.open(db_path, user_pk=a_pk) as db:
        db.annotate_finding(
            finding_id=FINDING_ID, status="acknowledged", note="alice-private-note",
        )
        alice_annotations = db.annotations()

    # Bob annotates the same finding_id with different status and note.
    with Database.open(db_path, user_pk=b_pk) as db:
        db.annotate_finding(
            finding_id=FINDING_ID, status="intentional", note="bob-private-note",
        )
        bob_annotations = db.annotations()

    # Each user must see only their own row and their own note.
    assert alice_annotations == {
        FINDING_ID: {"status": "acknowledged", "note": "alice-private-note"},
    }
    assert bob_annotations == {
        FINDING_ID: {"status": "intentional", "note": "bob-private-note"},
    }

    # And Alice's row must not have been overwritten by Bob's upsert —
    # re-read after Bob's write.
    with Database.open(db_path, user_pk=a_pk) as db:
        alice_after = db.annotations()
    assert alice_after == {
        FINDING_ID: {"status": "acknowledged", "note": "alice-private-note"},
    }


def test_clear_annotation_never_touches_another_users_row(tmp_path):
    """The delete had no owner filter either. Bob could delete Alice's
    annotation just by knowing (or guessing) the deterministic
    `finding_id`."""
    db_path = tmp_path / "tenancy.db"
    a_pk, b_pk = _seed_users(db_path)

    with Database.open(db_path, user_pk=a_pk) as db:
        db.annotate_finding(finding_id=FINDING_ID, status="acknowledged")

    # Bob has no annotation on that finding; clearing should not affect
    # Alice's row. (The API layer 404s on this case — the DB layer is
    # deliberately no-op for symmetry with the upsert path.)
    with Database.open(db_path, user_pk=b_pk) as db:
        db.clear_annotation(FINDING_ID)

    with Database.open(db_path, user_pk=a_pk) as db:
        alice_after = db.annotations()
    assert FINDING_ID in alice_after, (
        "Bob's clear on the same finding_id destroyed Alice's annotation"
    )


def test_reannotation_upserts_only_the_callers_row(tmp_path):
    """Alice re-annotating (upsert-in-place, keeps annotation_pk stable)
    must not touch Bob's row, and vice versa."""
    db_path = tmp_path / "tenancy.db"
    a_pk, b_pk = _seed_users(db_path)

    with Database.open(db_path, user_pk=a_pk) as db:
        alice_pk_first = db.annotate_finding(
            finding_id=FINDING_ID, status="acknowledged", note="v1",
        )
    with Database.open(db_path, user_pk=b_pk) as db:
        db.annotate_finding(finding_id=FINDING_ID, status="intentional", note="bob-v1")
    with Database.open(db_path, user_pk=a_pk) as db:
        alice_pk_second = db.annotate_finding(
            finding_id=FINDING_ID, status="intentional", note="v2",
        )

    # Alice's annotation_pk survives her upsert (A53's own contract,
    # spelled out at db.py:1813 — the pk must stay stable, and staying
    # stable requires the ON CONFLICT target to key on Alice's row alone).
    assert alice_pk_first == alice_pk_second

    with Database.open(db_path, user_pk=a_pk) as db:
        assert db.annotations()[FINDING_ID]["note"] == "v2"
    with Database.open(db_path, user_pk=b_pk) as db:
        assert db.annotations()[FINDING_ID]["note"] == "bob-v1"


# -- Guard: no new table may key on a bare `finding_id` -------------------
#
# A53 recorded this as the substitute for changing `finding_id`'s own
# shape: `finding_id` is a stable identity that annotations, chat
# transcripts' `evidence_cited` and coach outputs all cite, so changing it
# would orphan every stored citation. Partitioning the ONE table that
# stores an identity per finding_id closes the defect completely — but
# only as long as no future table repeats the bare-column pattern.
#
# The check parses `MIGRATIONS` (the schema's own text) rather than an
# introspection query, because the schema is expressed *there* and the
# regression surface is a migration author adding a bad line.

_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\)\s*;",
    re.DOTALL | re.IGNORECASE,
)
_FINDING_ID_COL_RE = re.compile(r"\bfinding_id\b", re.IGNORECASE)


def _tables_with_finding_id() -> dict[str, str]:
    """Return {final_table_name: body} for every CREATE TABLE ever run
    that mentions `finding_id`. Renames (`_new` shadows) collapse to the
    final table name in migration order — same convention migration 009
    established when it partitioned every other table."""
    seen: dict[str, str] = {}
    for script in MIGRATIONS:
        for m in _TABLE_RE.finditer(script):
            name, body = m.group(1), m.group(2)
            if _FINDING_ID_COL_RE.search(body):
                seen[name] = body
        # Follow renames the same migration used to swap tables in place.
        for m in re.finditer(
            r"ALTER\s+TABLE\s+(\w+)\s+RENAME\s+TO\s+(\w+)",
            script,
            re.IGNORECASE,
        ):
            src, dst = m.group(1), m.group(2)
            if src in seen:
                seen[dst] = seen.pop(src)
        for m in re.finditer(r"DROP\s+TABLE\s+(\w+)", script, re.IGNORECASE):
            seen.pop(m.group(1), None)
    return seen


def test_no_table_declares_a_bare_unique_on_finding_id():
    """A53's guard: any future table that stores something keyed on
    `finding_id` must partition it with `owner_user_pk`, or a bare
    `UNIQUE(finding_id)` would repeat BUG-031 exactly (evidence-ID
    collisions across tenants).

    Detects both `UNIQUE (finding_id)` on the column definition itself
    and standalone `UNIQUE (finding_id)` / `PRIMARY KEY (finding_id)`
    constraints inside the body.
    """
    for name, body in _tables_with_finding_id().items():
        collapsed = " ".join(body.split())
        # Bare UNIQUE on the column definition (e.g. `finding_id TEXT UNIQUE`).
        col_unique = re.search(
            r"\bfinding_id\s+\w+(?:\s+NOT\s+NULL)?\s+UNIQUE\b",
            collapsed,
            re.IGNORECASE,
        )
        assert not col_unique, (
            f"table `{name}` declares `finding_id UNIQUE` without an "
            f"`owner_user_pk` companion — BUG-031's shape. If the "
            f"identity really is per-tenant, partition with "
            f"`UNIQUE(owner_user_pk, finding_id)`."
        )
        # Standalone UNIQUE/PRIMARY KEY constraints that name finding_id
        # but not owner_user_pk.
        for constraint in re.finditer(
            r"\b(?:UNIQUE|PRIMARY\s+KEY)\s*\(([^)]+)\)",
            collapsed,
            re.IGNORECASE,
        ):
            cols = [c.strip().lower() for c in constraint.group(1).split(",")]
            if "finding_id" in cols and "owner_user_pk" not in cols:
                pytest.fail(
                    f"table `{name}` has a UNIQUE/PK constraint on "
                    f"`finding_id` without `owner_user_pk`: {cols}. "
                    f"This is the BUG-031 shape."
                )
