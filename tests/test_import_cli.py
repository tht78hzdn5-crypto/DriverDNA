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


def test_metrics_without_db_fails_loudly(tmp_path):
    result = CliRunner().invoke(
        app, ["metrics", "--db", str(tmp_path / "missing.db")]
    )
    assert result.exit_code == 2
    assert "no DB" in result.output
