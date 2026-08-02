"""SPEC.md A35: per-user AI keys (BYOK) — write-only in one direction (PUT
accepts the raw key; GET/nothing ever echoes it back), encrypted at rest,
and isolated per account. Mirrors test_auth_api.py's real-login pattern
rather than mocking the auth layer, so the account isolation is genuine.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.db import Database
from driverdna.ui.auth import hash_password
from driverdna.ui.api import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SECRET = "a-long-random-secret-key-for-byok-tests"
PASSWORD_A = "correct horse battery staple A"
PASSWORD_B = "correct horse battery staple B"
REAL_KEY = "AIzaSyD-a-realistic-looking-fake-gemini-key-000"


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    root = tmp_path_factory.mktemp("byok")
    path = root / "byok.db"
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(path)])
    assert result.exit_code == 0, result.output
    with Database.open(path) as db:
        with db.conn:
            db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                ("owner-a@driverdna.com", hash_password(PASSWORD_A)),
            )
            db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                ("owner-b@driverdna.com", hash_password(PASSWORD_B)),
            )
    return path


@pytest.fixture
def client_a(db_path, tmp_path):
    c = TestClient(create_app(db_path, tmp_path / "config.toml", session_secret=SECRET))
    r = c.post("/api/auth/login", json={"email": "owner-a@driverdna.com", "password": PASSWORD_A})
    assert r.status_code == 200
    return c


@pytest.fixture
def client_b(db_path, tmp_path):
    c = TestClient(create_app(db_path, tmp_path / "config.toml", session_secret=SECRET))
    r = c.post("/api/auth/login", json={"email": "owner-b@driverdna.com", "password": PASSWORD_B})
    assert r.status_code == 200
    return c


@pytest.fixture
def unconfigured_client(db_path, tmp_path):
    # No session_secret -> auth is off (local loopback mode) but BYOK has no
    # key-encryption key to derive from.
    return TestClient(create_app(db_path, tmp_path / "config.toml"))


def test_set_then_get_reports_fingerprint_never_the_key(client_a):
    r = client_a.put("/api/settings/ai-key", json={"provider": "gemini", "key": REAL_KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["fingerprint"] != REAL_KEY
    assert REAL_KEY not in r.text

    r = client_a.get("/api/settings/ai-key", params={"provider": "gemini"})
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["fingerprint"].startswith("AIza") and body["fingerprint"].endswith("-000")
    assert REAL_KEY not in r.text
    assert "set_at" in body


def test_unset_provider_reports_not_configured(client_a):
    r = client_a.get("/api/settings/ai-key", params={"provider": "claude"})
    assert r.status_code == 200
    assert r.json() == {"provider": "claude", "configured": False}


def test_delete_then_second_delete_404s(client_a):
    client_a.put("/api/settings/ai-key", json={"provider": "gemini", "key": REAL_KEY})
    r = client_a.delete("/api/settings/ai-key", params={"provider": "gemini"})
    assert r.status_code == 200
    assert r.json() == {"provider": "gemini", "configured": False}

    r = client_a.get("/api/settings/ai-key", params={"provider": "gemini"})
    assert r.json()["configured"] is False

    r = client_a.delete("/api/settings/ai-key", params={"provider": "gemini"})
    assert r.status_code == 404


def test_invalid_provider_rejected(client_a):
    r = client_a.put("/api/settings/ai-key", json={"provider": "openai", "key": "x"})
    assert r.status_code == 422
    r = client_a.get("/api/settings/ai-key", params={"provider": "openai"})
    assert r.status_code == 422


def test_empty_key_rejected(client_a):
    r = client_a.put("/api/settings/ai-key", json={"provider": "gemini", "key": "   "})
    assert r.status_code == 422


def test_key_is_actually_encrypted_at_rest(client_a, db_path):
    client_a.put("/api/settings/ai-key", json={"provider": "gemini", "key": REAL_KEY})
    with Database.open(db_path) as db:
        row = db.conn.execute(
            "SELECT ciphertext, nonce FROM user_api_keys WHERE provider='gemini'"
        ).fetchone()
    assert REAL_KEY not in row["ciphertext"]
    assert REAL_KEY.encode() not in row["ciphertext"].encode()


def test_one_users_key_is_invisible_to_another(client_a, client_b):
    client_a.put("/api/settings/ai-key", json={"provider": "gemini", "key": REAL_KEY})
    r = client_b.get("/api/settings/ai-key", params={"provider": "gemini"})
    assert r.json()["configured"] is False


def test_each_user_can_set_their_own_independently(client_a, client_b):
    client_a.put("/api/settings/ai-key", json={"provider": "gemini", "key": "key-for-a"})
    client_b.put("/api/settings/ai-key", json={"provider": "gemini", "key": "key-for-b"})
    fa = client_a.get("/api/settings/ai-key", params={"provider": "gemini"}).json()["fingerprint"]
    fb = client_b.get("/api/settings/ai-key", params={"provider": "gemini"}).json()["fingerprint"]
    assert fa != fb
    # B deleting their own key must not touch A's.
    client_b.delete("/api/settings/ai-key", params={"provider": "gemini"})
    assert client_a.get("/api/settings/ai-key", params={"provider": "gemini"}).json()["configured"] is True


def test_byok_requires_a_configured_session_secret(unconfigured_client):
    r = unconfigured_client.put("/api/settings/ai-key", json={"provider": "gemini", "key": REAL_KEY})
    assert r.status_code == 400
    assert "DRIVERDNA_SESSION_SECRET" in r.text


def test_unauthenticated_request_is_401_not_a_leak(db_path, tmp_path):
    """The app-level guard fires before this endpoint's own logic, same as
    every other route (DEPLOY-SPEC H done-criterion)."""
    guarded = TestClient(create_app(db_path, tmp_path / "config.toml", session_secret=SECRET))
    r = guarded.get("/api/settings/ai-key", params={"provider": "gemini"})
    assert r.status_code == 401
