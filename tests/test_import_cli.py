"""M2 end-to-end: `driverdna import` on the fixtures, then `driverdna metrics`."""

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.db import Database
from driverdna.metrics.report import build_metrics_report

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_import_fixtures_and_render_metrics(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()

    result = runner.invoke(
        app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    assert "10/10 matched" in result.output  # Laguna
    assert "14/14 matched" in result.output  # Spa

    # Re-import is a no-op, loudly.
    result = runner.invoke(app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0
    assert result.output.count("skipped") == 2

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
