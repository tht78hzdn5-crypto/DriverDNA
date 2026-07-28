"""The auth guard and its endpoints (docs/DEPLOY-SPEC.md track H1).

`test_auth.py` proves the crypto; this file proves the wiring — that the guard
is actually attached to every route, that the cookie carries the flags it is
supposed to, and that an unconfigured app is unchanged from before auth
existed (which is what keeps the rest of the suite honest rather than merely
passing).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.ui import auth
from driverdna.ui.api import PUBLIC_API_PATHS, create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TOKEN = "a-long-random-passphrase-for-one-driver"


@pytest.fixture(scope="module")
def db_path(tmp_path_factory):
    root = tmp_path_factory.mktemp("auth")
    path = root / "auth.db"
    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(path)]
    )
    assert result.exit_code == 0, result.output
    
    # Create the user to login with
    from driverdna.db import Database
    from driverdna.ui.auth import hash_password
    with Database.open(path) as db:
        with db.conn:
            db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                ("driver@driverdna.com", hash_password(TOKEN))
            )
    return path


@pytest.fixture
def guarded(db_path, tmp_path):
    return TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=TOKEN)
    )


@pytest.fixture
def unguarded(db_path, tmp_path):
    return TestClient(create_app(db_path, tmp_path / "config.toml"))


def _concrete_api_routes(app):
    """Every `/api/*` route the app declares, with path params filled in.

    Enumerated from `app.routes` rather than hardcoded — DEPLOY-SPEC's own
    done-criterion, so that an endpoint added later cannot quietly ship
    unguarded. `1` substitutes for every param because it satisfies both the
    `str` and the `int` converters in use.
    """
    import re

    seen = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            seen.append((method, path, re.sub(r"\{[^}]+\}", "1", path)))
    assert seen, "no /api routes discovered — the enumeration itself is broken"
    return seen


# --- the done-criterion ---------------------------------------------------


def test_every_api_route_refuses_an_unauthenticated_request(guarded):
    """DEPLOY-SPEC.md H done-criteria: *"Every /api/* route returns 401
    without a session (a test that enumerates the app's own route table, so a
    future endpoint can't be forgotten)."*"""
    unguarded_routes = []
    for method, declared, path in _concrete_api_routes(guarded.app):
        if declared in PUBLIC_API_PATHS:
            continue
        response = guarded.request(method, path)
        if response.status_code != 401:
            unguarded_routes.append(f"{method} {declared} → {response.status_code}")
    assert not unguarded_routes, (
        "these routes answered something other than 401 without a session: "
        + ", ".join(unguarded_routes)
    )


def test_no_route_outside_api_is_left_open_either(guarded):
    """Broader than DEPLOY-SPEC's criterion, because the narrow version missed
    a real one. `/openapi.json` is registered by FastAPI with `add_route`, not
    `add_api_route`, so app-level dependencies never see it — and a
    `/api/`-prefixed enumeration never looks at it. It answered 200 on a live
    server with a passphrase set, publishing the whole endpoint surface,
    request models and all.

    So: enumerate *every* route the app declares and require each to be either
    guarded or deliberately public. The static SPA shell is mounted after
    `create_app` (in `cli.py`) and is intentionally public — it is what renders
    the sign-in screen — so it is not in this app object at all.
    """
    import re

    open_routes = []
    for route in guarded.app.routes:
        path = getattr(route, "path", "")
        if path in PUBLIC_API_PATHS:
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            concrete = re.sub(r"\{[^}]+\}", "1", path)
            if guarded.request(method, concrete).status_code != 401:
                open_routes.append(f"{method} {path}")
    assert not open_routes, (
        "reachable without a session: " + ", ".join(open_routes)
    )


def test_the_api_schema_is_not_public(guarded, unguarded):
    """Called out on its own because it is the one that got away, and a
    regression here would be silent."""
    assert guarded.get("/openapi.json").status_code == 401
    # With no passphrase configured it stays available, so nothing that
    # relies on it locally (readiness probes, tooling) changes.
    assert unguarded.get("/openapi.json").status_code == 200


def test_the_guard_runs_before_body_validation(guarded):
    """A 422 instead of a 401 would mean the request body was parsed before
    the caller was authenticated — attacker-controlled input reaching the
    validator on a public endpoint."""
    response = guarded.post("/api/chat/sessions", json={"nonsense": True})
    assert response.status_code == 401


def test_the_guard_runs_before_the_database_is_opened(tmp_path):
    """A 404 "no database" would leak whether the instrument has data. The
    DB path here does not exist at all."""
    client = TestClient(
        create_app(tmp_path / "nope.db", tmp_path / "config.toml", session_secret=TOKEN)
    )
    assert client.get("/api/driver").status_code == 401


# --- login, logout, status ------------------------------------------------


def test_the_right_passphrase_opens_the_cockpit(guarded):
    assert guarded.get("/api/driver").status_code == 401
    assert guarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN}).status_code == 200
    assert guarded.get("/api/driver").status_code == 200


def test_the_session_cookie_is_httponly_and_samesite(guarded):
    response = guarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN})
    cookie = response.headers["set-cookie"]
    assert auth.SESSION_COOKIE in cookie
    # Attribute names and values are case-insensitive (RFC 6265); Starlette
    # emits `SameSite=lax`, so compare in one case rather than pinning theirs.
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered


def test_the_cookie_is_marked_secure_behind_an_https_proxy(guarded):
    """Cloud Run terminates TLS and forwards `X-Forwarded-Proto: https`, so
    the app cannot read the scheme off the request URL. Without this the
    session cookie would go out unmarked over a real HTTPS deployment."""
    plain = guarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN})
    assert "Secure" not in plain.headers["set-cookie"]  # plain-http loopback dev

    forwarded = guarded.post(
        "/api/auth/login",
        json={"email": "driver@driverdna.com", "password": TOKEN},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert "Secure" in forwarded.headers["set-cookie"]


def test_a_wrong_passphrase_is_refused_and_never_echoed(guarded):
    response = guarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": "hunter2"})
    assert response.status_code == 401
    # Neither the guess nor the real secret may appear in the response.
    assert "hunter2" not in response.text
    assert TOKEN not in response.text
    assert guarded.get("/api/driver").status_code == 401


def test_logout_ends_the_session(guarded):
    guarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN})
    assert guarded.get("/api/driver").status_code == 200
    assert guarded.post("/api/auth/logout").status_code == 200
    assert guarded.get("/api/driver").status_code == 401


def test_a_forged_cookie_does_not_open_anything(guarded):
    guarded.cookies.set(auth.SESSION_COOKIE, "9999999999.deadbeef")
    assert guarded.get("/api/driver").status_code == 401


def test_status_reports_whether_auth_is_required_and_met(guarded, unguarded):
    assert guarded.get("/api/auth/status").json() == {
        "required": True, "authenticated": False, "google_enabled": False,
    }
    guarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN})
    assert guarded.get("/api/auth/status").json() == {
        "required": True, "authenticated": True, "google_enabled": False,
    }
    assert unguarded.get("/api/auth/status").json() == {
        "required": False, "authenticated": True, "google_enabled": False,
    }


def test_status_never_reveals_the_passphrase(guarded):
    assert TOKEN not in guarded.get("/api/auth/status").text


def test_google_enabled_reflects_configuration_not_the_secret(db_path, tmp_path):
    client = TestClient(
        create_app(
            db_path, tmp_path / "config.toml",
            google_client_id="a-client-id", google_client_secret="a-client-secret",
        )
    )
    body = client.get("/api/auth/status").text
    assert client.get("/api/auth/status").json()["google_enabled"] is True
    assert "a-client-secret" not in body


# --- an unconfigured app is the app we had before -------------------------


def test_without_a_token_every_route_stays_open(unguarded):
    """This is what keeps the existing suite passing *unmodified* — the proof
    that auth is additive rather than a rewrite. It is also the local
    `driverdna ui` experience: no login on loopback."""
    assert unguarded.get("/api/driver").status_code == 200
    assert unguarded.get("/api/cohorts").status_code == 200


def test_logging_in_is_refused_when_no_passphrase_is_configured(unguarded):
    """With auth off there is nothing to log in to, and accepting any
    passphrase would be worse than accepting none."""
    response = unguarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": "anything"})
    assert response.status_code == 400
    assert auth.SESSION_SECRET_ENV in response.json()["detail"]


# --- throttling -----------------------------------------------------------


def test_repeated_wrong_guesses_are_locked_out(db_path, tmp_path):
    client = TestClient(
        create_app(db_path, tmp_path / "config.toml", session_secret=TOKEN)
    )
    config = __import__(
        "driverdna.config", fromlist=["load_config"]
    ).load_config(tmp_path / "config.toml")
    for _ in range(config.auth.login_max_attempts):
        assert client.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": "no"}).status_code == 401

    locked = client.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": "no"})
    assert locked.status_code == 429
    # And the lockout is not bypassed by suddenly knowing the passphrase.
    assert client.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN}).status_code == 429


# --- responses are not cacheable ------------------------------------------


def test_api_responses_carry_no_store(guarded):
    """A cached finding is a wrong number shown as a current one (UI-SPEC's
    service-worker rule). It is also a session-bearing response sitting in a
    shared cache."""
    guarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN})
    for path in ("/api/driver", "/api/cohorts", "/api/auth/status"):
        assert guarded.get(path).headers["cache-control"] == "no-store"
