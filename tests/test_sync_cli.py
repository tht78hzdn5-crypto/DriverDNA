"""`driverdna sync` CLI: mirrors test_coach.py's requires-key pattern — the
CLI-level test only checks clean failure without a token; full behavior is
covered directly against sync_driver/Garage61Client (test_garage61_sync.py,
test_garage61_client.py) with a mocked transport, never the live API.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from driverdna.cli import _validate_after, app


def test_sync_cli_requires_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    runner.invoke(app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)])
    result = runner.invoke(app, ["sync", "--db", str(db_path)])
    assert result.exit_code == 2
    assert "GARAGE61_TOKEN" in result.output


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("2026-07-01", "2026-07-01T00:00:00Z"),      # bare date -> midnight UTC
        ("2026-07-01T10:30:00", "2026-07-01T10:30:00Z"),  # naive -> read as UTC
        ("2026-07-01T10:30:00Z", "2026-07-01T10:30:00Z"),
        ("2026-07-01T12:30:00+02:00", "2026-07-01T12:30:00+02:00"),
    ],
)
def test_validate_after_normalises_to_rfc3339(given, expected):
    """A28: the API's `after` is `format: date-time`, and this API silently
    ignores values it cannot parse — so a bare date must be normalised
    locally rather than sent as-is and hoped for."""
    assert _validate_after(given) == expected


@pytest.mark.parametrize("bad", ["yesterday", "2026-13-01", "07/01/2026", ""])
def test_sync_cli_rejects_a_malformed_after_date(bad, tmp_path, monkeypatch):
    """Loud rejection, never a silent pass-through: an unparseable `after`
    reaching the API would be ignored and quietly become an unbounded
    backfill. Fails before the token check, so no network call is implied."""
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    result = CliRunner().invoke(
        app, ["sync", "--db", str(tmp_path / "t.db"), "--after", bad]
    )
    assert result.exit_code == 2
    assert "is not valid" in result.output
