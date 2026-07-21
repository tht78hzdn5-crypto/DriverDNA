"""M2 end-to-end: `driverdna import` on the fixtures, then `driverdna metrics`."""

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.metrics.report import build_metrics_report
from driverdna.report.payload import build_cohort_payload

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_full_spa_cohort_clears_gates_and_surfaces_events(tmp_path):
    """The trust milestone: with the real 10-lap / 3-session Spa cohort, some
    vs-self findings pass the confidence gates, and the map/class events the
    slower laps triggered are surfaced by the import — never silent."""
    db_path = tmp_path / "spa.db"
    result = CliRunner().invoke(app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    # Admission and class change are announced on stdout, not hidden:
    assert "ADMITTED to map" in result.output
    assert "CLASS CHANGE" in result.output

    with Database.open(db_path) as db:
        payload = build_cohort_payload(
            db, driver="owner", car="GR86", track="Spa-Francorchamps",
            config=DriverDNAConfig(),
        )
    assert payload["cohort"]["n_laps"] == 11
    assert payload["cohort"]["n_sessions"] == 3
    shown = [f for f in payload["findings"] if f["shown"]]
    assert shown, "10 laps across 3 sessions must clear the sample/session gates"
    # Every shown finding still carries its evidence and stands on >= 10 samples.
    assert all(f["n"] >= 10 for f in shown if f["source"] == "vs-self")
    assert all(f["evidence_ids"] for f in shown)


def test_import_fixtures_and_render_metrics(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()

    result = runner.invoke(
        app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    assert "10/10 matched" in result.output  # Laguna
    assert "14/14 matched" in result.output  # Spa (first lap builds the map)
    assert "DUPLICATE" not in result.output  # fixtures are all distinct laps

    # Re-import is a no-op, loudly — one skip line per manifest fixture.
    from driverdna.ingest.contract import load_fixture_manifest

    result = runner.invoke(app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0
    assert result.output.count("skipped") == len(load_fixture_manifest(FIXTURES_DIR))

    out = tmp_path / "metrics.md"
    result = runner.invoke(
        app, ["metrics", "--db", str(db_path), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    text = out.read_text()
    assert "owner — GR86 @ Spa-Francorchamps" in text
    assert "owner — Mustang @ Laguna Seca" in text
    assert "min_speed_kmh" in text and "Detector triggers" in text

    # The report is deterministic against the same DB.
    with Database.open(db_path) as db:
        assert build_metrics_report(db) == build_metrics_report(db)


def test_import_without_manifest_requires_metadata(tmp_path):
    empty = tmp_path / "csvs"
    empty.mkdir()
    result = CliRunner().invoke(app, ["import", str(empty)])
    assert result.exit_code == 2
    assert "--car and --track" in result.output


def _as_new_filename_format(dest_dir, src, *, car="Ford_Mustang_GT4",
                             track="Summit_Point_Raceway", lap_id="01KY31T54KGGQ351PDAMC7M6ER"):
    """A copy of a committed fixture's real telemetry, renamed to the newer
    Garage61 export filename shape — the content doesn't matter for testing
    filename-based auto-detection, only the name does, so this reuses an
    existing fixture rather than committing a second duplicate CSV."""
    dest = dest_dir / f"Garage_61__Benjamin_Richards__{car}__{track}__01.26.602__{lap_id}.csv"
    dest.write_bytes(src.read_bytes())
    return dest


def test_import_auto_detects_car_track_from_new_filename_format_without_flags(tmp_path):
    src_dir = tmp_path / "csvs"
    src_dir.mkdir()
    _as_new_filename_format(src_dir, FIXTURES_DIR / "Garage_61_HKWPXX.csv")
    db_path = tmp_path / "auto.db"

    result = CliRunner().invoke(app, ["import", str(src_dir), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "auto-detected from filename: Ford Mustang GT4 @ Summit Point Raceway" in result.output
    with Database.open(db_path) as db:
        row = db.conn.execute("SELECT car, track FROM laps").fetchone()
        assert (row["car"], row["track"]) == ("Ford Mustang GT4", "Summit Point Raceway")


def test_import_mixed_unresolvable_filenames_rejects_nothing_imported(tmp_path):
    """One auto-detectable file plus one old-format file, no --car/--track:
    the whole batch is rejected, itemized — nothing partially imported."""
    src_dir = tmp_path / "csvs"
    src_dir.mkdir()
    _as_new_filename_format(src_dir, FIXTURES_DIR / "Garage_61_HKWPXX.csv")
    (src_dir / "Garage_61_OLDFMT.csv").write_bytes(
        (FIXTURES_DIR / "Garage_61_HKWPXX.csv").read_bytes()
    )
    db_path = tmp_path / "mixed.db"

    result = CliRunner().invoke(app, ["import", str(src_dir), "--db", str(db_path)])
    assert result.exit_code == 2
    assert "Garage_61_OLDFMT.csv" in result.output
    assert not db_path.exists()


def test_metrics_without_db_fails_loudly(tmp_path):
    result = CliRunner().invoke(
        app, ["metrics", "--db", str(tmp_path / "missing.db")]
    )
    assert result.exit_code == 2
    assert "no DB" in result.output
