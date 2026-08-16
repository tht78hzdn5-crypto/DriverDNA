"""A brand-new deployment (no SQLite file on disk yet) must still let its
first driver register through the browser. `/api/auth/register` is public
(`PUBLIC_API_PATHS`), but its handler used to route through `open_db()`,
which 404s when the store file doesn't exist — the only other endpoint that
creates the DB fresh (`/api/laps/upload`) requires being logged in first, so
a cold deployment had no browser-only path to its first account at all.
"""

from fastapi.testclient import TestClient

from driverdna.ui.api import create_app

TOKEN = "a-long-random-passphrase-for-one-driver"


def test_register_creates_the_db_when_it_does_not_exist_yet(tmp_path):
    db_path = tmp_path / "does-not-exist-yet.db"
    assert not db_path.exists()

    client = TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=TOKEN)
    )
    resp = client.post(
        "/api/auth/register",
        json={"email": "first-driver@example.com", "password": "correct-horse-9"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["authenticated"] is True
    assert db_path.exists()
    assert "driverdna_session" in resp.cookies


def test_registered_user_can_then_log_in(tmp_path):
    db_path = tmp_path / "cold.db"
    client = TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=TOKEN)
    )
    reg = client.post(
        "/api/auth/register",
        json={"email": "driver@example.com", "password": "correct-horse-9"},
    )
    assert reg.status_code == 200, reg.text

    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"email": "driver@example.com", "password": "correct-horse-9"},
    )
    assert login.status_code == 200, login.text


def test_duplicate_registration_is_still_refused_on_a_cold_db(tmp_path):
    db_path = tmp_path / "cold2.db"
    client = TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=TOKEN)
    )
    body = {"email": "driver@example.com", "password": "correct-horse-9"}
    first = client.post("/api/auth/register", json=body)
    assert first.status_code == 200, first.text
    second = client.post("/api/auth/register", json=body)
    assert second.status_code == 409


def test_garage61_linked_reflects_the_env_token_fallback(tmp_path, monkeypatch):
    """`/api/auth/status`'s `garage61_linked` used to only check the
    per-user OAuth token table, so a token-only deployment (bare
    `GARAGE61_TOKEN`, no OAuth app registered) always reported
    `garage61_linked: false` — which hid the Import tab's whole Garage61
    Sync section (gated on `garage61Enabled || garage61Linked` in
    `upload.jsx`) even though sync itself works off the env token alone."""
    db_path = tmp_path / "linked.db"
    client = TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=TOKEN)
    )
    client.post(
        "/api/auth/register",
        json={"email": "driver@example.com", "password": "correct-horse-9"},
    )

    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    status = client.get("/api/auth/status").json()
    assert status["garage61_linked"] is False

    monkeypatch.setenv("GARAGE61_TOKEN", "a-real-looking-token")
    status = client.get("/api/auth/status").json()
    assert status["garage61_linked"] is True
