"""`driverdna demo` — the one-command local-cockpit launcher.

The server launch (uvicorn.run) blocks and isn't unit-testable, same as the
`ui` command; these cover the seeding helpers it composes and that the
command is wired up.
"""

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import _demo_fixtures_dir, _seed_demo_db, app
from driverdna.config import load_config
from driverdna.db import Database


def test_demo_fixtures_dir_resolves_in_a_source_checkout():
    fx = _demo_fixtures_dir()
    assert fx is not None and (fx / "manifest.toml").exists()


def test_seed_demo_db_imports_sample_laps(tmp_path):
    config = load_config()
    with Database.open(tmp_path / "demo.db") as db:
        n = _seed_demo_db(db, _demo_fixtures_dir(), config)
        cohorts = db.conn.execute("SELECT DISTINCT car, track FROM laps").fetchall()
    assert n == 12  # the committed fixture corpus
    # Two cohorts: one rich (Spa), one that shows the gated empty state (Laguna).
    assert {(r["car"], r["track"]) for r in cohorts} == {
        ("GR86", "Spa-Francorchamps"), ("Mustang", "Laguna Seca"),
    }


def test_seed_demo_db_is_idempotent(tmp_path):
    config = load_config()
    with Database.open(tmp_path / "demo.db") as db:
        first = _seed_demo_db(db, _demo_fixtures_dir(), config)
        again = _seed_demo_db(db, _demo_fixtures_dir(), config)
    assert first == again == 12  # a non-empty demo DB is left alone


def test_demo_command_is_registered():
    result = CliRunner().invoke(app, ["demo", "--help"])
    assert result.exit_code == 0 and "seed the bundled sample laps" in result.output
