"""BUG-035: on the deployed VM, migration 008 seeds `owner@example.com`
at `user_pk=1` with a `'placeholder'` password no `verify_password` can
match, and migration 009 backfills every pre-A32 row to that account —
so all data predating 2026-07-28 belongs to a login nobody can complete.
The owner registers as `user_pk=2` via the runbook and their real
history sits stranded behind an unusable login (SPEC.md A53).

A53 adopted: **reassign pre-A32 rows to the live account, live row wins
on unique-constraint collision, no merge heuristic** (owner's own words:
"don't care if that data goes away").

Coverage:
- `Database.reassign_owner(from_pk, to_pk)` walks every partitioned
  table (discovered at runtime, not hardcoded, so future partitioning is
  automatic), returns per-table `{reassigned, discarded}` counts.
- On a collision under any unique constraint the source row is DELETEd
  — matching A53's "live row wins". FK cascades from `laps` / `corner_maps`
  clean up downstream measurements without extra code, which is exactly
  the "no merge heuristic" the decision spelled out.
- `driverdna reassign-owner --from N --to M [--dry-run]` — a real
  admin tool the runbook can point at.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.db import Database


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _import_as_owner(tmp_path: Path) -> Path:
    """CLI import runs under `owner_user_pk=1` (the CLI's default). Gives
    us the "user 1" side: real laps, corner map, measurements — a full
    partitioned surface stranded on the seeded-placeholder login."""
    db_path = tmp_path / "reassign.db"
    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    return db_path


def _add_second_user(db_path: Path) -> int:
    """Insert `user_pk=2` — the owner's real account per the runbook."""
    with Database.open(db_path) as db:
        with db.conn:
            row = db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?) "
                "RETURNING user_pk",
                ("owner-real@example.com", "hash-real"),
            ).fetchone()
    return int(row["user_pk"])


def _count(db, table: str, user_pk: int) -> int:
    return db.conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE owner_user_pk=?", (user_pk,)
    ).fetchone()["n"]


# --- The core: reassignment reaches every partitioned table -------------


def test_reassign_moves_all_rows_from_one_user_to_another(tmp_path):
    """The base case. User 1 has the full fixture; user 2 is empty; the
    tool moves every row across, per-table counts add up to what was
    there before."""
    db_path = _import_as_owner(tmp_path)
    to_pk = _add_second_user(db_path)

    with Database.open(db_path) as db:
        before = {t: _count(db, t, 1) for t in db.partitioned_tables()}
    assert before["laps"] > 0, "fixture broken: user 1 has no laps"
    assert before["corner_maps"] > 0

    with Database.open(db_path) as db:
        counts = db.reassign_owner(from_pk=1, to_pk=to_pk)

    with Database.open(db_path) as db:
        after_from = {t: _count(db, t, 1) for t in db.partitioned_tables()}
        after_to = {t: _count(db, t, to_pk) for t in db.partitioned_tables()}

    # User 1 must have zero rows in every partitioned table.
    for table, n in after_from.items():
        assert n == 0, f"user 1 still holds {n} rows in {table} after reassign"

    # Everything user 1 had before, user 2 has now — no collisions in
    # this base case, so reassigned == before and discarded == 0.
    for table, n in before.items():
        assert counts[table]["reassigned"] == n, (
            f"{table}: expected {n} reassigned, got {counts[table]}"
        )
        assert counts[table]["discarded"] == 0
        assert after_to[table] == n, (
            f"{table}: user 2 has {after_to[table]}, expected {n}"
        )


def test_reassign_discards_on_unique_collision_target_row_wins(tmp_path):
    """A53's core decision. Both users have a row that collides on a
    unique constraint (`finding_annotations.UNIQUE(owner_user_pk,
    finding_id)`) — after reassign, user 2's row survives with its own
    status/note, and user 1's is discarded."""
    db_path = _import_as_owner(tmp_path)
    to_pk = _add_second_user(db_path)

    with Database.open(db_path) as db:
        finding_id = "vs-self:GR86:Spa-Francorchamps:C01:mid:opportunity"

        # User 1 annotates first.
        with db.conn:
            db.conn.execute(
                "INSERT INTO finding_annotations "
                "(owner_user_pk, finding_id, status, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (1, finding_id, "acknowledged", "user-1-note", "2026-07-01"),
            )
            # User 2's colliding row.
            db.conn.execute(
                "INSERT INTO finding_annotations "
                "(owner_user_pk, finding_id, status, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (to_pk, finding_id, "intentional", "user-2-note-wins", "2026-08-01"),
            )

        counts = db.reassign_owner(from_pk=1, to_pk=to_pk)

    with Database.open(db_path) as db:
        rows = db.conn.execute(
            "SELECT owner_user_pk, status, note FROM finding_annotations "
            "WHERE finding_id=?", (finding_id,),
        ).fetchall()

    assert len(rows) == 1, (
        f"collision resolution left {len(rows)} rows; expected exactly 1: {[dict(r) for r in rows]}"
    )
    assert rows[0]["owner_user_pk"] == to_pk
    assert rows[0]["note"] == "user-2-note-wins", (
        "target row was overwritten by source — the decision was live row wins"
    )
    # Counts must reflect the discard.
    assert counts["finding_annotations"] == {"reassigned": 0, "discarded": 1}


def test_reassign_deletes_are_transitive_through_fk_cascades(tmp_path):
    """A53 said "no merge heuristic". Discarding a `laps` row on collision
    means measurements attached to it (observations, incidents, etc.)
    go too, via existing FK cascades — that IS the no-heuristic behaviour.
    Pin it so a future FK-schema change doesn't quietly leave orphans."""
    db_path = _import_as_owner(tmp_path)
    to_pk = _add_second_user(db_path)

    # Force a collision on corner_maps (UNIQUE(car, track, owner_user_pk)).
    # User 2 imports a fresh copy of the fixtures under their own pk,
    # producing their own corner map — so both accounts share (GR86, Spa,
    # <their pk>) → reassign has to discard user 1's map and every
    # downstream measurement.
    with Database.open(db_path, user_pk=to_pk) as db:
        # Repurpose the import path — but the CLI is user_pk=1 only, so
        # we take a shortcut and duplicate user 1's corner_map row under
        # user 2 directly. That's sufficient to trigger the UNIQUE
        # collision, which is what we're testing.
        with db.conn:
            db.conn.execute(
                "INSERT INTO corner_maps (owner_user_pk, car, track, "
                "built_from_n_laps, track_outline_json) "
                "VALUES (?, 'GR86', 'Spa-Francorchamps', 1, NULL)"
            , (to_pk,))
        # The corner_maps table pre-reassign — user 1 has one, user 2 has one.
        pre_map = db.conn.execute(
            "SELECT owner_user_pk, COUNT(*) AS n FROM corner_maps GROUP BY owner_user_pk"
        ).fetchall()
        counts_by_user = {int(r["owner_user_pk"]): r["n"] for r in pre_map}
        assert counts_by_user.get(1, 0) >= 1
        assert counts_by_user.get(to_pk, 0) == 1

        # Get user 1's map_pk so we can prove its dependent rows go
        # after the reassign.
        u1_map_pk = db.conn.execute(
            "SELECT map_pk FROM corner_maps WHERE owner_user_pk=1"
        ).fetchone()["map_pk"]
        corners_before = db.conn.execute(
            "SELECT COUNT(*) AS n FROM corners WHERE map_pk=?", (u1_map_pk,),
        ).fetchone()["n"]
        assert corners_before > 0, "no dependent corners on user 1's map"

        counts = db.reassign_owner(from_pk=1, to_pk=to_pk)

    with Database.open(db_path) as db:
        # User 1's corner_maps row is gone…
        u1_still = db.conn.execute(
            "SELECT COUNT(*) AS n FROM corner_maps WHERE owner_user_pk=1"
        ).fetchone()["n"]
        assert u1_still == 0
        # …and so are its dependent `corners` rows (FK CASCADE).
        orphans = db.conn.execute(
            "SELECT COUNT(*) AS n FROM corners WHERE map_pk=?", (u1_map_pk,),
        ).fetchone()["n"]
        assert orphans == 0, (
            f"{orphans} orphan `corners` rows survived the discard — "
            f"FK cascade broke, and A53's 'no merge heuristic' rule "
            f"needed the cascade to clean up measurements"
        )
    # And the count reflects the discard.
    assert counts["corner_maps"]["discarded"] >= 1


def test_reassign_dry_run_writes_nothing(tmp_path):
    """CLI must offer a dry-run so the runbook can preview counts before
    the live VM sees a write. Both counts (reassigned/discarded) are
    computed, but nothing is committed."""
    db_path = _import_as_owner(tmp_path)
    to_pk = _add_second_user(db_path)
    result = CliRunner().invoke(
        cli_app,
        ["reassign-owner", "--db", str(db_path),
         "--from", "1", "--to", str(to_pk), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    # Dry run must NOT have moved anything.
    with Database.open(db_path) as db:
        assert _count(db, "laps", 1) > 0
        assert _count(db, "laps", to_pk) == 0


def test_reassign_cli_end_to_end(tmp_path):
    """The runbook path. `driverdna reassign-owner` prints per-table
    counts and moves the data."""
    db_path = _import_as_owner(tmp_path)
    to_pk = _add_second_user(db_path)
    result = CliRunner().invoke(
        cli_app,
        ["reassign-owner", "--db", str(db_path),
         "--from", "1", "--to", str(to_pk)],
    )
    assert result.exit_code == 0, result.output
    # Human-readable table output is a soft check — just confirm the
    # count for `laps` shows up so the runbook can eyeball the run.
    assert "laps" in result.output
    with Database.open(db_path) as db:
        assert _count(db, "laps", 1) == 0
        assert _count(db, "laps", to_pk) > 0


def test_reassign_refuses_when_to_pk_does_not_exist(tmp_path):
    """Guard: if the destination user doesn't exist, reassignment would
    create orphaned rows pointing at a nonexistent user_pk. Fail loudly."""
    db_path = _import_as_owner(tmp_path)
    result = CliRunner().invoke(
        cli_app,
        ["reassign-owner", "--db", str(db_path),
         "--from", "1", "--to", "99999"],
    )
    assert result.exit_code != 0
    # And user 1's data is untouched — the check must happen BEFORE any
    # write.
    with Database.open(db_path) as db:
        assert _count(db, "laps", 1) > 0


def test_reassign_refuses_when_from_equals_to(tmp_path):
    """Guard against operator error — passing --from 2 --to 2 would be
    a silent no-op that reads as success."""
    db_path = _import_as_owner(tmp_path)
    to_pk = _add_second_user(db_path)
    result = CliRunner().invoke(
        cli_app,
        ["reassign-owner", "--db", str(db_path),
         "--from", str(to_pk), "--to", str(to_pk)],
    )
    assert result.exit_code != 0
