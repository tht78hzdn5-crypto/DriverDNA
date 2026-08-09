"""Garage61 OAuth (PKCE, public client) — login, callback, token storage,
disconnect, and sync integration.

Follows the same mock-only pattern as test_auth_api.py's Google tests: the
token exchange and /me fetch are intercepted by unittest.mock, never reaching
the wire. The PKCE cookie, state validation, and token encryption are
exercised for real.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import json
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.db import Database
from driverdna.ui import auth
from driverdna.ui.api import PUBLIC_API_PATHS, create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SECRET = "a-long-random-secret-key-for-g61-tests"
PASSWORD = "correct horse battery staple G61"
G61_CLIENT_ID = "test-garage61-client-id"
G61_CLIENT_SECRET = "test-garage61-client-secret"


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    root = tmp_path_factory.mktemp("g61oauth")
    path = root / "g61.db"
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(path)])
    assert result.exit_code == 0, result.output
    with Database.open(path) as db:
        with db.conn:
            db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                ("driver@driverdna.com", auth.hash_password(PASSWORD)),
            )
    return path


@pytest.fixture
def client(db_path, tmp_path):
    """Guarded app with Garage61 OAuth configured, follow_redirects=False."""
    return TestClient(
        create_app(
            db_path, tmp_path / "config.toml",
            session_secret=SECRET,
            garage61_client_id=G61_CLIENT_ID,
            garage61_client_secret=G61_CLIENT_SECRET,
        ),
        follow_redirects=False,
    )


@pytest.fixture
def authed_client(db_path, tmp_path):
    """Guarded app with Garage61 OAuth configured, already logged in."""
    c = TestClient(
        create_app(
            db_path, tmp_path / "config.toml",
            session_secret=SECRET,
            garage61_client_id=G61_CLIENT_ID,
            garage61_client_secret=G61_CLIENT_SECRET,
        ),
        follow_redirects=False,
    )
    r = c.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": PASSWORD})
    assert r.status_code == 200
    return c


@pytest.fixture
def no_g61_client(db_path, tmp_path):
    """Guarded app without Garage61 configured."""
    return TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=SECRET),
        follow_redirects=False,
    )


# --- login redirect -------------------------------------------------------


def test_login_redirects_to_garage61_with_pkce(client):
    r = client.get("/api/auth/garage61/login")
    assert r.status_code == 307
    location = r.headers["location"]
    assert "garage61.net/app/account/oauth" in location
    assert f"client_id={G61_CLIENT_ID}" in location
    assert "code_challenge_method=S256" in location
    assert "code_challenge=" in location
    assert "state=" in location
    assert "response_type=code" in location
    assert "scope=" in location
    cookie_header = r.headers.get("set-cookie", "")
    assert "_g61_pkce" in cookie_header
    assert "httponly" in cookie_header.lower()


def test_login_refuses_without_garage61_configured(no_g61_client):
    r = no_g61_client.get("/api/auth/garage61/login")
    assert r.status_code == 400


def test_garage61_paths_are_public(client):
    assert "/api/auth/garage61/login" in PUBLIC_API_PATHS
    assert "/api/auth/garage61/callback" in PUBLIC_API_PATHS


# --- callback (mocked token exchange) ------------------------------------


def _mock_urlopen_factory(access_token="fake-access-token", user_id="12345",
                          refresh_token=None, scope="openid profile driving_data",
                          token_error=False, no_access_token=False):
    """Build a mock for urllib.request.urlopen that handles both the token
    exchange and the /me call."""
    def _mock_urlopen(req):
        m = MagicMock()
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "oauth/token" in url:
            if token_error:
                import urllib.error
                err = urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
                err.read = lambda: b'{"error":"invalid_grant"}'
                raise err
            result = {"access_token": access_token, "scope": scope}
            if no_access_token:
                result = {"scope": scope}
            if refresh_token:
                result["refresh_token"] = refresh_token
            m.read.return_value = json.dumps(result).encode()
        elif "/me" in url:
            m.read.return_value = json.dumps({"id": user_id, "name": "Test Driver"}).encode()
        m.__enter__ = lambda s: m
        m.__exit__ = MagicMock(return_value=False)
        return m
    return _mock_urlopen


def _get_pkce_cookie_and_state(client):
    """Initiate the login flow and return (cookies_dict, state_param)."""
    r = client.get("/api/auth/garage61/login")
    assert r.status_code == 307
    import urllib.parse
    qs = urllib.parse.urlparse(r.headers["location"]).query
    params = urllib.parse.parse_qs(qs)
    state = params["state"][0]
    return r.cookies, state


def test_callback_stores_token_and_issues_session(client, db_path):
    cookies, state = _get_pkce_cookie_and_state(client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(user_id="99001")):
        r = client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert r.status_code == 200
    assert auth.SESSION_COOKIE in r.cookies

    with Database.open(db_path) as db:
        row = db.conn.execute(
            "SELECT garage61_user_id, access_ciphertext FROM garage61_tokens "
            "WHERE garage61_user_id=?", ("99001",),
        ).fetchone()
    assert row is not None
    assert "fake-access-token" not in row["access_ciphertext"]


def test_callback_with_refresh_token(client, db_path):
    cookies, state = _get_pkce_cookie_and_state(client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(
        user_id="99002", refresh_token="fake-refresh"
    )):
        r = client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert r.status_code == 200

    with Database.open(db_path) as db:
        row = db.conn.execute(
            "SELECT refresh_ciphertext, refresh_nonce FROM garage61_tokens "
            "WHERE garage61_user_id=?", ("99002",),
        ).fetchone()
    assert row is not None
    assert row["refresh_ciphertext"] is not None
    assert row["refresh_nonce"] is not None


def test_callback_rejects_wrong_state(client):
    cookies, _state = _get_pkce_cookie_and_state(client)
    r = client.get(
        "/api/auth/garage61/callback?code=test-auth-code&state=wrong-state",
        cookies=cookies,
    )
    assert r.status_code == 302
    assert "auth_error" in r.headers["location"]
    assert "state" in r.headers["location"].lower() or "csrf" in r.headers["location"].lower()


def test_callback_rejects_missing_pkce_cookie(client):
    r = client.get("/api/auth/garage61/callback?code=test-auth-code&state=whatever")
    assert r.status_code == 302
    assert "auth_error" in r.headers["location"]
    assert "PKCE" in r.headers["location"] or "pkce" in r.headers["location"].lower()


def test_callback_rejects_tampered_pkce_cookie(client):
    _cookies, state = _get_pkce_cookie_and_state(client)
    r = client.get(
        f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
        cookies={"_g61_pkce": "tampered-data.badhex"},
    )
    assert r.status_code == 302
    assert "auth_error" in r.headers["location"]


def test_callback_handles_token_exchange_error(client):
    cookies, state = _get_pkce_cookie_and_state(client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(token_error=True)):
        r = client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert r.status_code == 302
    assert "auth_error" in r.headers["location"]
    assert "token" in r.headers["location"].lower()


def test_callback_handles_no_access_token(client):
    cookies, state = _get_pkce_cookie_and_state(client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(no_access_token=True)):
        r = client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert r.status_code == 302
    assert "auth_error" in r.headers["location"]


def test_callback_for_already_authenticated_user_stores_token(authed_client, db_path):
    cookies, state = _get_pkce_cookie_and_state(authed_client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(user_id="77001")):
        r = authed_client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert r.status_code == 200

    with Database.open(db_path) as db:
        row = db.conn.execute(
            "SELECT garage61_user_id FROM garage61_tokens WHERE garage61_user_id=?",
            ("77001",),
        ).fetchone()
    assert row is not None


# --- status and disconnect ------------------------------------------------


def test_garage61_status_not_connected_by_default(authed_client):
    r = authed_client.get("/api/garage61/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False


def test_garage61_status_connected_after_callback(client, db_path):
    cookies, state = _get_pkce_cookie_and_state(client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(user_id="88001")):
        r = client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert r.status_code == 200

    status = client.get("/api/garage61/status", cookies=r.cookies)
    assert status.status_code == 200
    body = status.json()
    assert body["connected"] is True
    assert body["garage61_user_id"] == "88001"


def test_garage61_disconnect(client, db_path):
    cookies, state = _get_pkce_cookie_and_state(client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(user_id="88002")):
        r = client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert r.status_code == 200
    session_cookies = r.cookies

    r2 = client.delete("/api/garage61/disconnect", cookies=session_cookies)
    assert r2.status_code == 200
    assert r2.json()["disconnected"] is True

    status = client.get("/api/garage61/status", cookies=session_cookies)
    assert status.json()["connected"] is False


# --- auth_status reflects garage61_enabled --------------------------------


def test_auth_status_reports_garage61_enabled(client, no_g61_client):
    r = client.get("/api/auth/status")
    assert r.json()["garage61_enabled"] is True

    r2 = no_g61_client.get("/api/auth/status")
    assert r2.json()["garage61_enabled"] is False


# --- token never appears in plaintext in any response ---------------------


def test_access_token_is_never_exposed(client, db_path):
    cookies, state = _get_pkce_cookie_and_state(client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(
        access_token="super-secret-g61-token", user_id="sectest"
    )):
        r = client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert "super-secret-g61-token" not in r.text

    with Database.open(db_path) as db:
        row = db.conn.execute(
            "SELECT access_ciphertext FROM garage61_tokens WHERE garage61_user_id=?",
            ("sectest",),
        ).fetchone()
    assert row is not None
    assert "super-secret-g61-token" not in row["access_ciphertext"]


def test_client_secret_is_sent_in_token_exchange(client):
    cookies, state = _get_pkce_cookie_and_state(client)
    captured_data = {}

    def _capturing_urlopen(req):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "oauth/token" in url:
            captured_data["body"] = req.data.decode("utf-8") if req.data else ""
        m = MagicMock()
        if "oauth/token" in url:
            m.read.return_value = json.dumps(
                {"access_token": "tok", "scope": "driving_data"}
            ).encode()
        elif "/me" in url:
            m.read.return_value = json.dumps({"id": "cap1"}).encode()
        m.__enter__ = lambda s: m
        m.__exit__ = MagicMock(return_value=False)
        return m

    with patch("urllib.request.urlopen", _capturing_urlopen):
        client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert f"client_secret={G61_CLIENT_SECRET}" in captured_data["body"]


def test_client_secret_never_in_any_response(client, db_path):
    cookies, state = _get_pkce_cookie_and_state(client)
    with patch("urllib.request.urlopen", _mock_urlopen_factory(user_id="sectest2")):
        r = client.get(
            f"/api/auth/garage61/callback?code=test-auth-code&state={state}",
            cookies=cookies,
        )
    assert G61_CLIENT_SECRET not in r.text

    login_r = client.get("/api/auth/garage61/login")
    assert G61_CLIENT_SECRET not in login_r.headers.get("location", "")

    status_r = client.get("/api/auth/status")
    assert G61_CLIENT_SECRET not in status_r.text


# --- unauthenticated access to protected endpoints -----------------------


def test_garage61_status_requires_auth_when_guarded(db_path, tmp_path):
    guarded = TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=SECRET,
                   garage61_client_id=G61_CLIENT_ID),
    )
    r = guarded.get("/api/garage61/status")
    assert r.status_code == 401


def test_garage61_disconnect_requires_auth_when_guarded(db_path, tmp_path):
    guarded = TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=SECRET,
                   garage61_client_id=G61_CLIENT_ID),
    )
    r = guarded.delete("/api/garage61/disconnect")
    assert r.status_code == 401
