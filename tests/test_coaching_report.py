"""M7c: the `driverdna coaching` artifact."""

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.coaching.ontology import ONTOLOGY_VERSION
from driverdna.coaching.report import build_coaching_report
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


def _build_db():
    db = Database.open(":memory:")
    for i in range(6):
        run_synthetic_lap(db, track_lap(src=f"fast{i}.csv"), session_key=f"s{i % 2 + 1}")
    for i in range(6):
        lap = warp_time(track_lap(src=f"slow{i}.csv"), (0.19, 0.22), 0.4)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2 + 1}")
    return db


def test_build_coaching_report_is_deterministic_and_shows_self_checks():
    with _build_db() as db:
        a = build_coaching_report(db, CONFIG)
        b = build_coaching_report(db, CONFIG)
    assert a == b
    assert ONTOLOGY_VERSION in a
    assert "cp.eye_line.look_further" in a
    assert "coaching hypothesis, not a measurement" in a


def test_build_coaching_report_with_no_laps_says_so():
    with Database.open(":memory:") as db:
        report = build_coaching_report(db, CONFIG)
    assert "No self laps imported" in report


def test_coaching_cli_requires_existing_db(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["coaching", "--db", str(tmp_path / "nope.db")])
    assert result.exit_code == 2
    assert "run `driverdna import`" in result.output


def test_coaching_cli_writes_report_on_real_fixtures(tmp_path):
    db_path = tmp_path / "r.db"
    runner = CliRunner()
    result = runner.invoke(
        app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    out = tmp_path / "coaching-report.md"
    result = runner.invoke(app, ["coaching", "--db", str(db_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    text = out.read_text()
    assert "Coaching report" in text
    assert "owner" in text
    assert "Self-checks" in text
