"""M6c: the `driverdna model` artifact and its persistence side effect."""

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.report import build_model_report
from driverdna.model.scoring import SCORING_MODEL_VERSION
from driverdna.model.taxonomy import FUNDAMENTALS
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


def test_build_model_report_lists_every_fundamental_and_is_deterministic():
    with _build_db() as db:
        a = build_model_report(db, CONFIG)
        b = build_model_report(db, CONFIG)
    assert a == b
    assert SCORING_MODEL_VERSION in a
    for fid in FUNDAMENTALS:
        assert fid in a
    assert "vision" in a and "no telemetry channel" in a


def test_build_model_report_persists_beliefs(tmp_path):
    db_path = tmp_path / "m.db"
    with Database.open(db_path) as db:
        for i in range(6):
            run_synthetic_lap(db, track_lap(src=f"a{i}.csv"), session_key=f"s{i % 2}")
        build_model_report(db, CONFIG)
        loaded = db.load_beliefs(driver="owner", scoring_model_version=SCORING_MODEL_VERSION)
    assert set(loaded) == set(FUNDAMENTALS)


def test_build_model_report_with_no_laps_says_so():
    with Database.open(":memory:") as db:
        report = build_model_report(db, CONFIG)
    assert "No self laps imported" in report


def test_model_cli_requires_existing_db(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["model", "--db", str(tmp_path / "nope.db")])
    assert result.exit_code == 2
    assert "run `driverdna import`" in result.output


def test_model_cli_writes_report_on_real_fixtures(tmp_path):
    db_path = tmp_path / "r.db"
    runner = CliRunner()
    result = runner.invoke(
        app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    out = tmp_path / "model-report.md"
    result = runner.invoke(
        app, ["model", "--db", str(db_path), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    text = out.read_text()
    assert "Driver Model report" in text
    assert "owner" in text
