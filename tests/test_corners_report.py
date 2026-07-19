"""M1 artifact tests: `driverdna corners` renders and is deterministic."""

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.config import DriverDNAConfig
from driverdna.corners.report import build_corners_report

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_report_contains_both_cohorts_and_ids():
    text = build_corners_report(FIXTURES_DIR, DriverDNAConfig())
    assert "Mustang @ Laguna Seca" in text
    assert "GR86 @ Spa-Francorchamps — 8 laps" in text
    assert "C01" in text and "C10" in text and "C14" in text
    # The map freezes from the first lap; messier race laps legitimately
    # produce unmatched candidate observations, which are surfaced.
    assert "Unmatched corner observations:" in text


def test_report_is_deterministic():
    config = DriverDNAConfig()
    assert build_corners_report(FIXTURES_DIR, config) == build_corners_report(
        FIXTURES_DIR, config
    )


def test_cli_writes_report(tmp_path):
    out = tmp_path / "corners.md"
    result = CliRunner().invoke(
        app, ["corners", "--fixtures-dir", str(FIXTURES_DIR), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.exists() and "Corner report" in out.read_text()
