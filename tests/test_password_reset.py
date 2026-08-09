import pytest
from pathlib import Path
from driverdna.ui.api import create_app
from fastapi.testclient import TestClient

@pytest.fixture(scope="function")
def db_path(tmp_path: Path) -> Path:
    from driverdna.db import Database
    
    path = tmp_path / "test.db"
    with Database.open(path):
        pass
    
    return path

@pytest.fixture
def app(db_path: Path, tmp_path: Path) -> TestClient:
    # Use empty config to simulate no session secret
    config = tmp_path / "config.toml"
    config.write_text("")
    
    smtp_config = {"host": "test", "port": "123", "user": "a", "password": "b"}
    api = create_app(db_path, config, smtp_config=smtp_config)
    return TestClient(api)

def test_forgot_password_sends_email_if_user_exists(app: TestClient, db_path: Path, monkeypatch):
    emails_sent = []
    
    def fake_send(host, port, user, password, to_email, reset_link):
        emails_sent.append((to_email, reset_link))
        
    monkeypatch.setattr("driverdna.ui.email.send_reset_email", fake_send)
    
    # Try with existing owner
    resp = app.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    assert resp.status_code == 200
    assert len(emails_sent) == 1
    assert emails_sent[0][0] == "owner@example.com"
    assert "token=" in emails_sent[0][1]

    # Try with nonexistent user
    emails_sent.clear()
    resp = app.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert len(emails_sent) == 0

def test_reset_password_changes_password_and_clears_token(app: TestClient, db_path: Path, monkeypatch):
    emails_sent = []
    monkeypatch.setattr("driverdna.ui.email.send_reset_email", lambda *a: emails_sent.append(a[-1]))
    
    app.post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    link = emails_sent[0]
    token = link.split("token=")[1]
    
    # Attempt reset with invalid token
    resp = app.post("/api/auth/reset-password", json={"token": "invalid", "new_password": "newpass"})
    assert resp.status_code == 400
    
    # Attempt reset with valid token
    resp = app.post("/api/auth/reset-password", json={"token": token, "new_password": "newpass"})
    assert resp.status_code == 200
    
    # Attempt reset again with same token
    resp = app.post("/api/auth/reset-password", json={"token": token, "new_password": "newer"})
    assert resp.status_code == 400
