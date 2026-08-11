"""`driverdna sync` CLI: mirrors test_coach.py's requires-key pattern — the
CLI-level test only checks clean failure without a token; full behavior is
covered directly against sync_driver/Garage61Client (test_garage61_sync.py,
test_garage61_client.py) with a mocked transport, never the live API.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import driverdna.garage61.client as garage61_client
from driverdna.cli import _validate_after, app
from driverdna.config import DriverDNAConfig


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


# --- what the driver is told about the cohort cap (SPEC.md A49) -----------

FIXTURES = Path(__file__).parent / "fixtures"
_ME = {"id": "me-01", "slug": "owner"}


def _json(obj):
    return 200, json.dumps(obj).encode("utf-8")


class _ThreeCohortTransport:
    """Three cohorts, three distinct last-driven dates, one lap each."""

    def get(self, path, params):
        if path == "/me":
            return _json(_ME)
        if path == "/me/statistics":
            return _json({"drivingStatistics": [
                {"car": 8, "track": 69, "lapsDriven": 1, "day": "2026-01-05"},
                {"car": 9, "track": 71, "lapsDriven": 1, "day": "2026-07-30"},
                {"car": 8, "track": 71, "lapsDriven": 1, "day": "2025-11-02"},
            ]})
        if path == "/cars":
            return _json({"items": [{"id": 8, "name": "GR86"},
                                    {"id": 9, "name": "Mustang GT4"}]})
        if path == "/tracks":
            return _json({"items": [{"id": 69, "name": "Spa", "variant": ""},
                                    {"id": 71, "name": "Okayama", "variant": ""}]})
        if path == "/laps":
            return _json({"items": [{
                "id": f"L{params['tracks']}-{params.get('cars')}",
                "driver": {"id": _ME["id"]}, "event": "e", "session": 1, "run": 0,
                "startTime": "2026-07-30T00:00:00Z", "clean": True,
                "missing": False, "incomplete": False, "offtrack": False,
                "discontinuity": False, "pitlane": params.get("cars") == 9,
            }], "total": 1})
        if path.endswith("/csv"):
            name = ("Garage_61_HKWPXX.csv" if "69" in path else "Garage_61_RH11X7.csv")
            return 200, (FIXTURES / name).read_bytes()
        raise AssertionError(f"unexpected path {path}")


def _mock_sync(monkeypatch, config: DriverDNAConfig) -> None:
    """`sync` imports both names lazily inside the command body, so patching
    them where they are *defined* is what reaches the call sites."""
    real = garage61_client.Garage61Client
    monkeypatch.setattr(
        garage61_client, "Garage61Client",
        lambda *a, **k: real(transport=_ThreeCohortTransport(), token="x"),
    )
    monkeypatch.setattr("driverdna.config.load_config", lambda *a, **k: config)


def test_sync_cli_names_every_cohort_the_cap_skipped(tmp_path, monkeypatch):
    """A bare count would hide a wrong ordering — and the ordering rests on the
    API's `day`, whose format is unverified. So each skipped cohort is named
    with the date it was last driven."""
    _mock_sync(monkeypatch, DriverDNAConfig.model_validate({"sync": {"max_cohorts": 1}}))
    result = CliRunner().invoke(app, ["sync", "--db", str(tmp_path / "s.db")])

    assert result.exit_code == 0, result.output
    assert "2 cohort(s) not synced (sync.max_cohorts=1)" in result.output
    assert "GR86 @ Spa (last driven 2026-01-05)" in result.output
    assert "GR86 @ Okayama (last driven 2025-11-02)" in result.output
    # Newest-first: only the 2026-07-30 cohort was actually pulled.
    assert "Mustang GT4 @ Okayama: 1 seen" in result.output
    assert "set it to 0, to sync every cohort" in result.output


def test_sync_cli_is_silent_about_the_cap_when_nothing_was_capped(tmp_path, monkeypatch):
    _mock_sync(monkeypatch, DriverDNAConfig())
    result = CliRunner().invoke(app, ["sync", "--db", str(tmp_path / "s.db")])

    assert result.exit_code == 0, result.output
    assert "not synced" not in result.output


def test_sync_cli_reports_imported_pitlane_laps(tmp_path, monkeypatch):
    """skip_pitlane_laps defaults off, so the driver is told the laps came in
    and how to change that — the count is the evidence for the decision."""
    _mock_sync(monkeypatch, DriverDNAConfig())
    result = CliRunner().invoke(app, ["sync", "--db", str(tmp_path / "s.db")])

    assert "1 lap(s) flagged `pitlane` were imported anyway" in result.output
    assert "sync.skip_pitlane_laps = true" in result.output
