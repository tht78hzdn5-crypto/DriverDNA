"""U0 write-path test for POST /api/laps/upload (UI-SPEC decision 3): the
endpoint wraps `import_lap_file`, the exact function `driverdna import`
calls per file, so its DB effects must be identical to the CLI equivalent.
Also the one deliberate exception to "reads require an existing DB" — this
endpoint creates one fresh, so a driver can go from nothing to a populated
cockpit through the browser alone.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.db import Database
from driverdna.ui.api import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ONE_LAP = FIXTURES_DIR / "Garage_61_HKWPXX.csv"  # GR86 @ Spa-Francorchamps


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "upload.db"
    app = create_app(db_path, tmp_path / "config.toml")
    return TestClient(app), db_path


def _upload(client, path, **form):
    with open(path, "rb") as fh:
        return client.post(
            "/api/laps/upload",
            files=[("files", (path.name, fh, "text/csv"))],
            data={"car": "GR86", "track": "Spa-Francorchamps", **form},
        )


def test_upload_creates_a_fresh_db_and_imports(client):
    c, db_path = client
    assert not db_path.exists()
    r = _upload(c, ONE_LAP)
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == [{
        "filename": "Garage_61_HKWPXX.csv", "car": "GR86", "track": "Spa-Francorchamps",
        "auto_detected": False, "status": "imported", "lap_pk": 1,
        "corners_matched": 14, "corners_total": 14, "admitted": [], "class_changes": [],
    }]
    assert db_path.exists()  # the cold-start path: no CLI ever touched


def test_reupload_same_file_is_a_reported_duplicate_not_double_counted(client):
    c, _ = client
    _upload(c, ONE_LAP)
    r = _upload(c, ONE_LAP)
    assert r.json()["results"][0]["status"] == "duplicate"
    with Database.open(client[1]) as db:
        assert db.conn.execute("SELECT COUNT(*) n FROM laps").fetchone()["n"] == 1


def test_malformed_date_rejected_nothing_imported(client):
    c, db_path = client
    r = _upload(c, ONE_LAP, date="not-a-date")
    assert r.status_code == 422
    assert not db_path.exists()  # rejected before the DB is even opened


def test_valid_date_and_session_are_applied(client):
    c, db_path = client
    _upload(c, ONE_LAP, date="2026-07-15", session="s1")
    with Database.open(db_path) as db:
        row = db.conn.execute("SELECT lap_date, session_key FROM laps").fetchone()
        assert row["lap_date"] == "2026-07-15" and row["session_key"] == "s1"


def test_invalid_role_rejected(client):
    c, db_path = client
    r = _upload(c, ONE_LAP, role="nonsense")
    assert r.status_code == 422
    assert not db_path.exists()


def test_reference_role_is_isolated_like_the_cli_path(client):
    c, db_path = client
    _upload(c, ONE_LAP, role="reference")
    with Database.open(db_path) as db:
        assert db.conn.execute("SELECT role FROM laps").fetchone()["role"] == "reference"


def test_multi_file_upload_in_one_request(client):
    c, db_path = client
    files = [
        ("files", (p.name, open(p, "rb"), "text/csv"))
        for p in [ONE_LAP, FIXTURES_DIR / "Garage_61_W5JRZB.csv"]
    ]
    r = c.post("/api/laps/upload", files=files,
               data={"car": "GR86", "track": "Spa-Francorchamps"})
    for _, (_, fh, _) in files:
        fh.close()
    assert r.status_code == 200
    assert [x["status"] for x in r.json()["results"]] == ["imported", "imported"]
    with Database.open(db_path) as db:
        assert db.conn.execute("SELECT COUNT(*) n FROM laps").fetchone()["n"] == 2


def _as_new_filename_format(tmp_path, src, *, car="Ford_Mustang_GT4",
                             track="Summit_Point_Raceway", lap_id="01KY31T54KGGQ351PDAMC7M6ER"):
    """A copy of a committed fixture's real telemetry bytes, renamed to the
    newer Garage61 export filename shape (Garage_61__<driver>__<car>__
    <track>__<laptime>__<id>.csv) — the content doesn't matter for testing
    filename-based car/track detection, only the name does, so this avoids
    committing a second, duplicate multi-hundred-KB CSV fixture."""
    dest = tmp_path / f"Garage_61__Benjamin_Richards__{car}__{track}__01.26.602__{lap_id}.csv"
    dest.write_bytes(src.read_bytes())
    return dest


def test_upload_without_car_track_auto_detects_from_new_filename_format(client):
    c, db_path = client
    new_style = _as_new_filename_format(db_path.parent, ONE_LAP)
    with open(new_style, "rb") as fh:
        r = c.post("/api/laps/upload", files=[("files", (new_style.name, fh, "text/csv"))], data={})
    assert r.status_code == 200
    result = r.json()["results"][0]
    assert result["car"] == "Ford Mustang GT4"
    assert result["track"] == "Summit Point Raceway"
    assert result["auto_detected"] is True
    assert result["status"] == "imported"
    with Database.open(db_path) as db:
        row = db.conn.execute("SELECT car, track FROM laps").fetchone()
        assert (row["car"], row["track"]) == ("Ford Mustang GT4", "Summit Point Raceway")


def test_upload_unresolvable_filename_without_car_track_rejected_nothing_imported(client):
    c, db_path = client
    with open(ONE_LAP, "rb") as fh:  # old-format filename, no car/track given
        r = c.post("/api/laps/upload", files=[("files", (ONE_LAP.name, fh, "text/csv"))], data={})
    assert r.status_code == 422
    assert "Garage_61_HKWPXX.csv" in r.json()["detail"]
    assert not db_path.exists()  # rejected before the DB was even opened


def test_explicit_car_track_overrides_filename_for_every_file(client):
    """When car/track ARE given, they apply uniformly -- even to a file
    whose name would otherwise auto-detect something different."""
    c, db_path = client
    new_style = _as_new_filename_format(db_path.parent, ONE_LAP)
    with open(new_style, "rb") as fh:
        r = c.post(
            "/api/laps/upload",
            files=[("files", (new_style.name, fh, "text/csv"))],
            data={"car": "GR86", "track": "Spa-Francorchamps"},
        )
    result = r.json()["results"][0]
    assert result["car"] == "GR86" and result["track"] == "Spa-Francorchamps"
    assert result["auto_detected"] is False


def test_db_effects_identical_to_cli_import(tmp_path):
    """The decision-3 requirement, proven directly: the same file, imported
    via the API vs the CLI to independent fresh DBs, produces byte-identical
    lap rows and the same corner-observation count."""
    api_db = tmp_path / "api.db"
    app = create_app(api_db, tmp_path / "cfg.toml")
    with open(ONE_LAP, "rb") as fh:
        TestClient(app).post(
            "/api/laps/upload",
            files=[("files", (ONE_LAP.name, fh, "text/csv"))],
            data={"car": "GR86", "track": "Spa-Francorchamps"},
        )

    cli_db = tmp_path / "cli.db"
    with tempfile.TemporaryDirectory() as d:
        shutil.copy(ONE_LAP, Path(d) / ONE_LAP.name)
        result = CliRunner().invoke(
            cli_app,
            ["import", d, "--car", "GR86", "--track", "Spa-Francorchamps", "--db", str(cli_db)],
        )
        assert result.exit_code == 0, result.output

    def snapshot(db_path):
        with Database.open(db_path) as db:
            lap = dict(db.conn.execute(
                "SELECT car, track, role, n_samples, duration_s, quality_flags FROM laps"
            ).fetchone())
            obs = db.conn.execute("SELECT COUNT(*) n FROM corner_observations").fetchone()["n"]
            return lap, obs

    assert snapshot(api_db) == snapshot(cli_db)
