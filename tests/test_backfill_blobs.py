"""`driverdna backfill-blobs`: restoring raw traces after a store move.

`store-copy` faithfully carries every compact row (evidence IDs, driver-model
history, transcripts) but deliberately does NOT carry raw lap blobs — they are
per-machine, keyed `<lap_pk>.npz` on local disk. After a Postgres -> SQLite
migration the new box therefore has the lap rows but no raw traces, and
re-importing the CSVs is a no-op: `store_lap` sees the copied row's
`content_hash` and returns "duplicate" without writing a blob.

Backfill is the dedicated recovery path. It matches each CSV to a lap by the
lap's own content fingerprint and writes the blob straight into the store,
never touching (or renumbering) a lap row — so evidence IDs stay valid and the
one thing blobs unlock, `rebuild-map` re-measurement, works again.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.migrate import copy_store
from driverdna.pipeline import RawTracesUnavailable, backfill_blobs, rebuild_cohort_map

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIG = DriverDNAConfig()


def _import_fixtures(db_path: Path) -> None:
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output


def _store_copied_target(tmp_path: Path) -> tuple[Path, Path, list[int]]:
    """A source DB with blobs, and a target that has the rows (via store-copy)
    but no blobs — the exact post-migration state."""
    source = tmp_path / "source.db"
    _import_fixtures(source)
    target = tmp_path / "target.db"
    with Database.open(source) as src, Database.open(target) as dst:
        copy_store(src, dst)
    with Database.open(target) as dst:
        needy = dst.laps_needing_raw()
        lap_pks = [pk for pk, _ in needy]
    assert lap_pks, "expected copied laps whose raw trace is absent"
    return source, target, lap_pks


def test_backfill_restores_every_blob_after_store_copy(tmp_path):
    source, target, lap_pks = _store_copied_target(tmp_path)

    with Database.open(target) as dst:
        assert all(not dst.has_raw(pk) for pk in lap_pks)
        result = backfill_blobs(dst, FIXTURES_DIR)
        assert sorted(result.restored) == sorted(lap_pks)
        assert result.unmatched_laps == []
        assert all(dst.has_raw(pk) for pk in lap_pks)


def test_backfilled_arrays_are_identical_to_source(tmp_path):
    source, target, lap_pks = _store_copied_target(tmp_path)
    with Database.open(target) as dst:
        backfill_blobs(dst, FIXTURES_DIR)

    with Database.open(source) as src, Database.open(target) as dst:
        for pk in lap_pks:
            a = src.load_lap_arrays(pk)
            b = dst.load_lap_arrays(pk)
            assert a is not None and b is not None
            assert a.keys() == b.keys()
            for channel in a:
                assert np.array_equal(a[channel], b[channel]), channel


def test_backfill_leaves_lap_rows_and_pks_untouched(tmp_path):
    source, target, lap_pks = _store_copied_target(tmp_path)
    with Database.open(target) as dst:
        before = [r["lap_pk"] for r in dst.conn.execute("SELECT lap_pk FROM laps ORDER BY lap_pk")]
        backfill_blobs(dst, FIXTURES_DIR)
        after = [r["lap_pk"] for r in dst.conn.execute("SELECT lap_pk FROM laps ORDER BY lap_pk")]
    assert before == after


def test_backfill_ignores_csvs_that_match_no_needy_lap(tmp_path):
    """A CSV whose content matches nothing in the store is reported, never
    written to some unrelated lap — matching is by content fingerprint."""
    source, target, lap_pks = _store_copied_target(tmp_path)
    with Database.open(target) as dst:
        # Restore everything first, so a second pass has no needy laps left.
        backfill_blobs(dst, FIXTURES_DIR)
        second = backfill_blobs(dst, FIXTURES_DIR)
    assert second.restored == []
    # Every fixture CSV now matches an already-satisfied lap, so none are used.
    assert sorted(second.unmatched_csvs) and second.unmatched_laps == []


def test_rebuild_map_refuses_without_blobs_then_succeeds_after_backfill(tmp_path):
    """The concrete payoff: rebuild-map needs raw traces. It refuses on the
    freshly-copied store, and re-measures once backfill has restored them."""
    source, target, lap_pks = _store_copied_target(tmp_path)

    with Database.open(target) as dst:
        with pytest.raises(RawTracesUnavailable):
            rebuild_cohort_map(
                dst, driver="owner", car="GR86", track="Spa-Francorchamps", config=CONFIG
            )

    with Database.open(target) as dst:
        backfill_blobs(dst, FIXTURES_DIR)
        result = rebuild_cohort_map(
            dst, driver="owner", car="GR86", track="Spa-Francorchamps", config=CONFIG
        )
    assert result is not None


def test_backfill_blobs_cli_end_to_end(tmp_path):
    """The full migration shape through the CLI: import, store-copy to a fresh
    store (no blobs), then `backfill-blobs --from` restores them."""
    runner = CliRunner()
    source = tmp_path / "source.db"
    _import_fixtures(source)

    target = tmp_path / "target.db"
    copied = runner.invoke(
        cli_app, ["store-copy", "--from", str(source), "--to", str(target)]
    )
    assert copied.exit_code == 0, copied.output

    with Database.open(target) as dst:
        lap_pks = [pk for pk, _ in dst.laps_needing_raw()]
    assert lap_pks

    done = runner.invoke(
        cli_app, ["backfill-blobs", "--from", str(FIXTURES_DIR), "--db", str(target)]
    )
    assert done.exit_code == 0, done.output
    assert f"restored {len(lap_pks)} raw lap blob(s)" in done.output

    with Database.open(target) as dst:
        assert all(dst.has_raw(pk) for pk in lap_pks)
