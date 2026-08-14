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


@pytest.fixture
def guarded_behind_proxy(db_path, tmp_path):
    return TestClient(
        create_app(
            db_path, tmp_path / "config.toml", session_secret=TOKEN, behind_proxy=True
        )
    )


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


def test_behind_proxy_trusts_the_resolved_scheme_not_the_raw_header(guarded_behind_proxy):
    """docs/VM-MIGRATION.md §3.3: with --behind-proxy, uvicorn's
    ProxyHeadersMiddleware (wired by the CLI to trust only 127.0.0.1) has
    already resolved `request.url.scheme` from X-Forwarded-Proto before the
    app sees the request, so the app trusts that resolved value instead of
    re-reading the header itself — which has no trust boundary at the app
    layer and would believe anyone who could reach the port at all."""
    plain = guarded_behind_proxy.post(
        "/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN}
    )
    assert "Secure" not in plain.headers["set-cookie"]

    https = guarded_behind_proxy.post(
        "https://testserver/api/auth/login",
        json={"email": "driver@driverdna.com", "password": TOKEN},
    )
    assert "Secure" in https.headers["set-cookie"]

    # The raw header alone, with no real https:// scheme, must NOT be enough
    # in this mode — that would be exactly the un-trust-boundaried read this
    # mode exists to stop trusting.
    spoofed = guarded_behind_proxy.post(
        "/api/auth/login",
        json={"email": "driver@driverdna.com", "password": TOKEN},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert "Secure" not in spoofed.headers["set-cookie"]


# --- the loud warning (VM-MIGRATION.md §3.1 option (c)) --------------------


def test_forwarded_headers_without_proxy_mode_or_auth_warn_loudly(unguarded, caplog):
    """If a request arrives bearing X-Forwarded-For while no session secret
    is configured and --behind-proxy was never set, a real reverse proxy in
    front of this loopback-bound instance would mean every request is
    authenticated as the owner with no login at all — the exact "entire
    internet reaches the cockpit" failure mode. A hard refusal at request
    time would be a confusing failure mode (per the design doc's own
    reasoning), so this warns loudly instead."""
    import logging

    with caplog.at_level(logging.WARNING):
        unguarded.get("/health", headers={"X-Forwarded-For": "203.0.113.7"})
    assert any("X-Forwarded" in r.message for r in caplog.records)


def test_the_warning_fires_at_most_once_per_app(unguarded, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        unguarded.get("/health", headers={"X-Forwarded-For": "203.0.113.7"})
        unguarded.get("/health", headers={"X-Forwarded-For": "203.0.113.7"})
    warnings = [r for r in caplog.records if "X-Forwarded" in r.message]
    assert len(warnings) == 1


def test_no_warning_without_forwarded_headers(unguarded, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        unguarded.get("/health")
    assert not any("X-Forwarded" in r.message for r in caplog.records)


def test_no_warning_when_behind_proxy_is_correctly_configured(guarded_behind_proxy, caplog):
    """--behind-proxy plus a configured secret is exactly the safe
    configuration this warning exists to nudge people toward — it must stay
    silent once they've done that."""
    import logging

    with caplog.at_level(logging.WARNING):
        guarded_behind_proxy.get("/health", headers={"X-Forwarded-For": "203.0.113.7"})
    assert not any("X-Forwarded" in r.message for r in caplog.records)


def test_client_key_resolves_the_real_client_through_the_configured_proxy_wrapping(
    db_path, tmp_path
):
    """Locks in the exact end-to-end behaviour --behind-proxy depends on:
    wrapping the app in uvicorn's own ProxyHeadersMiddleware with
    trusted_hosts=127.0.0.1 (precisely what the CLI passes to uvicorn.run
    under --behind-proxy) rewrites scope["client"] from X-Forwarded-For for
    a peer connecting from 127.0.0.1 — so the login throttle keys on the
    real client, not the proxy's own loopback address. A lockout triggered
    by one attacker's forwarded IP must not also lock out a different real
    client arriving through the very same proxy."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    inner = create_app(
        db_path, tmp_path / "config.toml", session_secret=TOKEN, behind_proxy=True
    )
    wrapped = ProxyHeadersMiddleware(inner, trusted_hosts="127.0.0.1")
    client = TestClient(wrapped, client=("127.0.0.1", 40404))

    for _ in range(5):
        r = client.post(
            "/api/auth/login",
            json={"email": "driver@driverdna.com", "password": "wrong"},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
        assert r.status_code == 401

    locked = client.post(
        "/api/auth/login",
        json={"email": "driver@driverdna.com", "password": "wrong"},
        headers={"X-Forwarded-For": "203.0.113.7"},
    )
    assert locked.status_code == 429

    other = client.post(
        "/api/auth/login",
        json={"email": "driver@driverdna.com", "password": TOKEN},
        headers={"X-Forwarded-For": "198.51.100.9"},
    )
    assert other.status_code == 200


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
        "garage61_enabled": False, "garage61_linked": False,
    }
    guarded.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN})
    assert guarded.get("/api/auth/status").json() == {
        "required": True, "authenticated": True, "google_enabled": False,
        "garage61_enabled": False, "garage61_linked": False,
    }
    assert unguarded.get("/api/auth/status").json() == {
        "required": False, "authenticated": True, "google_enabled": False,
        "garage61_enabled": False, "garage61_linked": False,
    }


def test_status_never_reveals_the_passphrase(guarded):
    assert TOKEN not in guarded.get("/api/auth/status").text


def test_google_callback_invalidates_prior_session_for_existing_user(db_path, tmp_path):
    """A second Google sign-in for an existing user must end the prior session
    (SPEC.md A41: session-per-device inconsistency). The OAuth path must bump
    session_epoch just like the password login path does."""
    import json as _json
    from unittest.mock import MagicMock, patch

    client = TestClient(
        create_app(
            db_path, tmp_path / "config.toml",
            session_secret=TOKEN,
            google_client_id="test-client-id",
            google_client_secret="test-client-secret",
        ),
        follow_redirects=False,
    )

    # First login via password → captures old session cookie.
    r = client.post("/api/auth/login", json={"email": "driver@driverdna.com", "password": TOKEN})
    assert r.status_code == 200
    old_cookie = r.cookies[auth.SESSION_COOKIE]

    # Verify old cookie is valid.
    assert client.get("/api/driver", cookies={auth.SESSION_COOKIE: old_cookie}).status_code == 200

    # Mock Google's token + tokeninfo endpoints so the callback never hits the wire.
    def _mock_urlopen(req):
        m = MagicMock()
        url = req.full_url
        if "tokeninfo" in url:
            m.read.return_value = _json.dumps(
                {"aud": "test-client-id", "email": "driver@driverdna.com"}
            ).encode()
        else:
            m.read.return_value = _json.dumps({"id_token": "fake-id-token"}).encode()
        m.__enter__ = lambda s: m
        m.__exit__ = MagicMock(return_value=False)
        return m

    # Initiate the Google login to obtain the state cookie and state param.
    login_r = client.get("/api/auth/google/login")
    assert login_r.status_code == 307
    import urllib.parse
    location = login_r.headers["location"]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    state = qs["state"][0]
    state_cookie = login_r.cookies["_google_oauth_state"]

    with patch("urllib.request.urlopen", _mock_urlopen):
        r2 = client.get(
            f"/api/auth/google/callback?code=abc&state={state}",
            cookies={"_google_oauth_state": state_cookie},
        )
    assert r2.status_code == 200  # HTML meta-refresh page, not a redirect

    # Old cookie must now be rejected — epoch was bumped by the OAuth sign-in.
    assert client.get("/api/driver", cookies={auth.SESSION_COOKIE: old_cookie}).status_code == 401


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
