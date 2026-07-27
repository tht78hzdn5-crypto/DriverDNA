"""Write-path hardening for a publicly reachable cockpit
(docs/DEPLOY-SPEC.md track H1, item 3).

> The write endpoints get, in addition to auth: an upload size cap and
> content-type check, a rate limit on `/api/chat/*` and any coach invocation
> (they cost money and quota, and are the only endpoints that reach a third
> party), and `no-store` on every API response.

`no-store` is asserted in `test_auth_api.py` alongside the session it
protects; the cap, the type check and the chat limit live here.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.config import load_config
from driverdna.ui.api import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
A_REAL_LAP = FIXTURES_DIR / "Garage_61_B3M5ZW.csv"


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "hard.db", tmp_path / "config.toml"))


def _lap_count(db_path: Path) -> int:
    from driverdna.db import Database

    if not db_path.exists():
        return 0
    with Database.open(db_path) as db:
        return db.conn.execute("SELECT COUNT(*) AS n FROM laps").fetchone()["n"]


# --- upload size cap ------------------------------------------------------


def test_the_upload_cap_has_a_documented_default_with_real_headroom():
    api = load_config().api
    assert api.max_upload_mb >= 8, (
        "the committed fixture laps are ~1.8MB each; a cap without headroom "
        "would reject a long track at a high sample rate"
    )


def test_an_oversized_upload_is_refused_and_imports_nothing(client, tmp_path):
    cap_bytes = load_config().api.max_upload_mb * 1024 * 1024
    oversized = b"lap_dist,speed\n" + b"1,2\n" * ((cap_bytes // 4) + 1)
    response = client.post(
        "/api/laps/upload",
        files={"files": ("huge.csv", oversized, "text/csv")},
        data={"car": "GR86", "track": "Spa-Francorchamps"},
    )
    assert response.status_code == 413
    assert _lap_count(tmp_path / "hard.db") == 0


def test_a_real_lap_is_comfortably_under_the_cap(client, tmp_path):
    """The cap has to admit the actual data this instrument exists for —
    asserted against a committed fixture, not against an assumed size."""
    response = client.post(
        "/api/laps/upload",
        files={"files": (A_REAL_LAP.name, A_REAL_LAP.read_bytes(), "text/csv")},
        data={"car": "GR86", "track": "Spa-Francorchamps"},
    )
    assert response.status_code == 200, response.text
    assert _lap_count(tmp_path / "hard.db") == 1


# --- content-type check ---------------------------------------------------


@pytest.mark.parametrize("name", ["laps.zip", "laps.csv.exe", "notes.txt", "noextension"])
def test_a_non_csv_upload_is_refused_by_name(client, tmp_path, name):
    response = client.post(
        "/api/laps/upload",
        files={"files": (name, b"lap_dist,speed\n1,2\n", "text/csv")},
        data={"car": "GR86", "track": "Spa-Francorchamps"},
    )
    assert response.status_code == 422
    assert name in response.json()["detail"]
    assert _lap_count(tmp_path / "hard.db") == 0


def test_the_refusal_names_every_bad_file_not_just_the_first(client):
    response = client.post(
        "/api/laps/upload",
        files=[
            ("files", ("one.zip", b"x", "application/zip")),
            ("files", ("two.txt", b"x", "text/plain")),
        ],
        data={"car": "GR86", "track": "Spa-Francorchamps"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "one.zip" in detail and "two.txt" in detail


def test_a_csv_extension_is_matched_case_insensitively(client, tmp_path):
    """Windows hands back `.CSV` often enough that rejecting it would be a
    bug report, not a security win."""
    response = client.post(
        "/api/laps/upload",
        files={"files": ("LAP.CSV", A_REAL_LAP.read_bytes(), "text/csv")},
        data={"car": "GR86", "track": "Spa-Francorchamps"},
    )
    assert response.status_code == 200, response.text


def test_a_redownload_suffix_still_uploads(client):
    """SPEC.md A24/A25: a browser re-download is `... (1).csv` or `...(1).csv`.
    The type check must not undo that."""
    response = client.post(
        "/api/laps/upload",
        files={"files": ("lap(1).csv", A_REAL_LAP.read_bytes(), "text/csv")},
        data={"car": "GR86", "track": "Spa-Francorchamps"},
    )
    assert response.status_code == 200, response.text


# --- chat rate limit ------------------------------------------------------


def test_chat_is_rate_limited(client):
    """Chat and coach are the only endpoints that reach a third party, and
    they cost money and quota. The limiter is asserted through a route that
    needs no provider — an unknown session 404s, which is fine: what is
    being tested is that the limit fires at all."""
    limit = load_config().api.chat_requests_per_minute
    seen = [
        client.post("/api/chat/sessions/nosuch/confirm/0").status_code
        for _ in range(limit + 1)
    ]
    assert seen[:limit] == [404] * limit
    assert seen[-1] == 429


def test_the_rate_limit_does_not_apply_to_ordinary_reads(client, tmp_path):
    """Nothing about reading your own findings should be throttled."""
    CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(tmp_path / "hard.db")]
    )
    limit = load_config().api.chat_requests_per_minute
    for _ in range(limit + 5):
        assert client.get("/api/cohorts").status_code == 200
