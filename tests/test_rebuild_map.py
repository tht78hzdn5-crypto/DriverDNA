"""rebuild-map (SPEC.md A22): in-place refreeze of a frozen cohort map.

The command re-derives every corner's centroid + canonical windows from the
cohort's FULL current observation set (not just the laps that first froze the
map) and re-measures phase times, WITHOUT changing corner IDs (evidence-ID
stability) and WITHOUT silently keeping a phase-time number it can no longer
honestly re-interpolate (evicted raw blob -> cleared + reported).
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.pipeline import rebuild_cohort_map
from synth import CORNER_WINDOWS, track_lap
from synth import run_synthetic_lap as _run

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BLIND_DIR = FIXTURES_DIR / "spa-blind-2026-07"
CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def _run_pipeline(db, lap, **kw):
    kw.setdefault("config", CONFIG)
    return _run(db, lap, **kw)


def _windows(db, car="TestCar", track="SynthRing"):
    map_pk, _ = db.load_corner_map(car=car, track=track)
    return db.load_corner_windows(map_pk)


def _corner_pks(db, car="TestCar", track="SynthRing"):
    map_pk, _ = db.load_corner_map(car=car, track=track)
    return {
        r["corner_id"]: r["corner_pk"]
        for r in db.conn.execute(
            "SELECT corner_id, corner_pk FROM corners WHERE map_pk=? ORDER BY corner_id",
            (map_pk,),
        )
    }


# --- the core guarantee: sharpen the frozen window from the full lap set -----


def test_rebuild_refreezes_windows_from_full_set_not_just_build_lap(db):
    # The map freezes its windows from the FIRST lap only; later laps are
    # measured against them but never re-derive them. Give the later laps
    # subtly different landmark timing (shifted corner windows within match
    # radius) so the full-set median window genuinely differs from lap 1's.
    _run_pipeline(db, track_lap(src="build.csv"))
    before = _windows(db)
    for i in range(4):
        shifted = [(s + 12 * (i + 1), e + 12 * (i + 1)) for s, e in CORNER_WINDOWS]
        _run_pipeline(db, track_lap(windows=shifted, src=f"later{i}.csv"))

    result = rebuild_cohort_map(db, config=CONFIG, **COHORT)
    assert result.existed
    after = _windows(db)
    # At least one canonical window moved once the full set is considered.
    assert any(result_c.window_changed for result_c in result.corners)
    assert after != before


def test_rebuild_keeps_corner_ids_and_observation_rows_stable(db):
    # Evidence IDs resolve through corner_pk / obs_pk; an in-place rebuild must
    # never renumber or delete either.
    for i in range(4):
        _run_pipeline(db, track_lap(src=f"lap{i}.csv"))
    pks_before = _corner_pks(db)
    obs_before = db.conn.execute(
        "SELECT obs_pk, corner_pk FROM corner_observations ORDER BY obs_pk"
    ).fetchall()

    rebuild_cohort_map(db, config=CONFIG, **COHORT)

    assert _corner_pks(db) == pks_before  # same IDs -> same corner_pks
    obs_after = db.conn.execute(
        "SELECT obs_pk, corner_pk FROM corner_observations ORDER BY obs_pk"
    ).fetchall()
    assert [(r["obs_pk"], r["corner_pk"]) for r in obs_after] == [
        (r["obs_pk"], r["corner_pk"]) for r in obs_before
    ]


def test_rebuild_is_idempotent(db):
    for i in range(4):
        shifted = [(s + 8 * i, e + 8 * i) for s, e in CORNER_WINDOWS]
        _run_pipeline(db, track_lap(windows=shifted, src=f"lap{i}.csv"))
    rebuild_cohort_map(db, config=CONFIG, **COHORT)  # first: may sharpen
    windows_after_first = _windows(db)

    second = rebuild_cohort_map(db, config=CONFIG, **COHORT)
    # Nothing left to change: centroids don't move, no window shifts.
    assert all(c.centroid_shift_m in (0.0, None) for c in second.corners)
    assert all(not c.window_changed for c in second.corners)
    assert _windows(db) == windows_after_first


# --- the trust question: an evicted blob can't be re-measured, honestly ------


def test_rebuild_clears_and_reports_phase_times_when_blob_evicted(db):
    pks = [_run_pipeline(db, track_lap(src=f"lap{i}.csv")).lap_pk for i in range(5)]
    phase_before = db.conn.execute("SELECT COUNT(*) n FROM phase_times").fetchone()["n"]
    assert phase_before > 0

    evicted = db.enforce_retention(keep=2)  # laps[0..2]'s blobs gone
    assert evicted == 3

    result = rebuild_cohort_map(db, config=CONFIG, **COHORT)
    # The evicted laps are reported, not silently left with stale numbers.
    assert result.total_cleared > 0
    cleared_pks = {pk for c in result.corners for pk in c.laps_cleared}
    assert cleared_pks == set(pks[:3])
    # Their phase-time rows are gone...
    remaining = {
        r["lap_pk"]
        for r in db.conn.execute(
            """SELECT DISTINCT o.lap_pk FROM phase_times p
               JOIN corner_observations o ON o.obs_pk = p.obs_pk"""
        )
    }
    assert remaining.isdisjoint(set(pks[:3]))
    # ...but their observation rows (and thus evidence IDs) are untouched.
    n_obs = db.conn.execute("SELECT COUNT(*) n FROM corner_observations").fetchone()["n"]
    assert n_obs == 5 * len(CORNER_WINDOWS)


# --- new geometry still enters only through the audited admission path -------


def test_rebuild_admits_newly_eligible_candidate_when_threshold_lowered(db):
    # Two laps carry an extra corner — below the default admission threshold
    # (3), so they stay unmatched candidates through import. Lowering the
    # threshold and rebuilding admits them (the map never changed silently:
    # admission is the same audited path a normal import uses).
    extra = CORNER_WINDOWS + [(2200, 2350)]
    _run_pipeline(db, track_lap(src="base.csv"))
    _run_pipeline(db, track_lap(windows=extra, src="a.csv"))
    _run_pipeline(db, track_lap(windows=extra, src="b.csv"))
    assert "C04" not in _corner_pks(db)  # not yet admitted at threshold 3

    lowered = DriverDNAConfig()
    lowered.identity.min_laps_for_admission = 2
    result = rebuild_cohort_map(db, config=lowered, **COHORT)
    assert result.admitted == ["C04"]
    assert "C04" in _corner_pks(db)


def test_rebuild_missing_cohort_reports_not_existed(db):
    _run_pipeline(db, track_lap(src="x.csv"))
    result = rebuild_cohort_map(
        db, driver="owner", car="NoSuchCar", track="Nowhere", config=CONFIG
    )
    assert result.existed is False
    assert result.corners == []


# --- real two-cohort data (the plan's motivating case) + the CLI -------------


def test_rebuild_on_real_merged_spa_cohorts_is_stable_and_idempotent(tmp_path):
    db_path = tmp_path / "spa.db"
    runner = CliRunner()
    # Primary GR86/Spa fixtures + the committed blind cohort (same car/track,
    # frozen from a disjoint lap set) merged into one DB.
    assert runner.invoke(app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]).exit_code == 0
    assert runner.invoke(app, ["import", str(BLIND_DIR), "--db", str(db_path)]).exit_code == 0

    with Database.open(db_path) as db:
        ids_before = set(_corner_pks(db, "GR86", "Spa-Francorchamps"))
        first = rebuild_cohort_map(
            db, driver="owner", car="GR86", track="Spa-Francorchamps", config=CONFIG
        )
        # IDs never renumber; the full-set refreeze moves real windows.
        assert set(_corner_pks(db, "GR86", "Spa-Francorchamps")) == ids_before
        assert any(c.window_changed for c in first.corners)

        second = rebuild_cohort_map(
            db, driver="owner", car="GR86", track="Spa-Francorchamps", config=CONFIG
        )
        assert all(not c.window_changed for c in second.corners)
        assert all(c.centroid_shift_m in (0.0, None) for c in second.corners)


def test_rebuild_map_cli_reports_summary(tmp_path):
    db_path = tmp_path / "spa.db"
    runner = CliRunner()
    assert runner.invoke(app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]).exit_code == 0

    result = runner.invoke(
        app,
        ["rebuild-map", "--car", "GR86", "--track", "Spa-Francorchamps", "--db", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    assert "rebuilt GR86 @ Spa-Francorchamps" in result.output
    assert "re-measured" in result.output


def test_rebuild_map_cli_errors_on_missing_db(tmp_path):
    result = CliRunner().invoke(
        app,
        ["rebuild-map", "--car", "GR86", "--track", "Spa", "--db", str(tmp_path / "no.db")],
    )
    assert result.exit_code == 2
    assert "no DB" in result.output


def test_rebuild_map_cli_errors_on_unknown_cohort(tmp_path):
    db_path = tmp_path / "spa.db"
    runner = CliRunner()
    assert runner.invoke(app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]).exit_code == 0
    result = runner.invoke(
        app,
        ["rebuild-map", "--car", "Nope", "--track", "Nowhere", "--db", str(db_path)],
    )
    assert result.exit_code == 2
    assert "nothing to rebuild" in result.output
