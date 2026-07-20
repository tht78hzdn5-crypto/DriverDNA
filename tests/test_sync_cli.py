"""`driverdna sync` CLI: mirrors test_coach.py's requires-key pattern — the
CLI-level test only checks clean failure without a token; full behavior is
covered directly against sync_driver/Garage61Client (test_garage61_sync.py,
test_garage61_client.py) with a mocked transport, never the live API.
"""

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app


def test_sync_cli_requires_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    runner.invoke(app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)])
    result = runner.invoke(app, ["sync", "--db", str(db_path)])
    assert result.exit_code == 2
    assert "GARAGE61_TOKEN" in result.output
