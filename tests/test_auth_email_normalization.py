"""BUG-034 (SPEC.md A53): `POST /api/auth/register` normalized email
(strip + lower) before insert, but login, forgot-password, and the
Google callback lookup queried with the raw string. Text columns are
`COLLATE "C"` (A23), so Postgres does not case-fold either — the
storage layer is doing exactly what it was told.

The consequence: register as `User@Example.com` and no password on
earth logs that account in. The error is the generic "incorrect email
or password", so the driver has no way to diagnose it — and password
reset has the same bug, so the reset flow cannot rescue them.

Fix and pin every lookup path. The Google callback path already
normalizes (`ui/api.py:629`), so it stays passing here — that
regression guard is deliberate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from driverdna.db import Database
from driverdna.ui.api import create_app


SECRET = "email-normalization-test-secret-passphrase-long-enough"
MIXED = "User@Example.com"
LOWER = "user@example.com"
UPPER = "USER@EXAMPLE.COM"
PADDED = "  User@Example.com  "
PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def guarded_client(tmp_path):
    db_path = tmp_path / "email-norm.db"
    # Migration seeds owner@example.com at user_pk=1; we register through
    # the HTTP layer to prove the register path itself is unchanged.
    with Database.open(db_path):
        pass
    app = create_app(db_path, tmp_path / "cfg.toml", session_secret=SECRET)
    return TestClient(app)


def test_register_normalizes_then_login_with_the_typed_original_succeeds(guarded_client):
    """The exact defect scenario. Register with mixed case; login with
    the same mixed case. Before the fix, the stored row was
    `user@example.com` and login looked up `User@Example.com` verbatim,
    with COLLATE "C" collation refusing the comparison — permanent
    lockout on a spelling the user typed themselves."""
    r = guarded_client.post("/api/auth/register",
                            json={"email": MIXED, "password": PASSWORD})
    assert r.status_code == 200, r.text

    # Log out so we're not authenticated by the register-set cookie.
    guarded_client.post("/api/auth/logout")

    r = guarded_client.post("/api/auth/login",
                            json={"email": MIXED, "password": PASSWORD})
    assert r.status_code == 200, (
        f"login with the same casing used at register failed: {r.text}"
    )


@pytest.mark.parametrize("variant", [LOWER, UPPER, PADDED])
def test_login_accepts_any_case_or_whitespace(guarded_client, variant):
    """Register lower, then log in with several spellings that must
    resolve to the same row. Guards against a partial fix that only
    handles `.lower()` and not `.strip()`, or vice versa."""
    r = guarded_client.post("/api/auth/register",
                            json={"email": LOWER, "password": PASSWORD})
    assert r.status_code == 200
    guarded_client.post("/api/auth/logout")

    r = guarded_client.post("/api/auth/login",
                            json={"email": variant, "password": PASSWORD})
    assert r.status_code == 200, (
        f"login with {variant!r} failed: {r.text}"
    )


def test_forgot_password_finds_the_account_regardless_of_typed_case(
    tmp_path, monkeypatch,
):
    """Forgot-password had the same defect. Register as `LOWER`, then
    request a reset for `MIXED` — the reset row must land, and the
    email must be sent to the normalized address (not to whatever the
    user typed).

    SMTP is mocked at `driverdna.ui.email.send_reset_email` because
    forgot-password uses it directly rather than through a DI seam."""
    sent: list[tuple] = []

    def fake_send(host, port, user, password, to_email, reset_link):
        sent.append((host, port, user, password, to_email, reset_link))

    # Register + login require the app; SMTP config is what enables
    # forgot-password beyond the 400 short-circuit.
    monkeypatch.setattr("driverdna.ui.api.send_reset_email", fake_send, raising=False)
    monkeypatch.setattr("driverdna.ui.email.send_reset_email", fake_send)

    db_path = tmp_path / "email-norm-forgot.db"
    with Database.open(db_path):
        pass
    smtp = {"host": "smtp.example.com", "port": "587",
            "user": "u", "password": "p"}
    app = create_app(
        db_path, tmp_path / "cfg.toml",
        session_secret=SECRET, smtp_config=smtp,
    )
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": LOWER, "password": PASSWORD})
    assert r.status_code == 200
    c.post("/api/auth/logout")

    # Ask for a reset with a different casing than what was stored.
    r = c.post("/api/auth/forgot-password", json={"email": UPPER})
    # Always returns 200 (anti-enumeration), so success is measured by
    # whether the mocked SMTP call happened.
    assert r.status_code == 200, r.text
    assert len(sent) == 1, (
        f"forgot-password on a mismatched-case address should have found "
        f"the account and sent a reset email, but sent no email: {sent}"
    )
    # And the address it was sent to is the normalized form, not the
    # attacker-supplied casing.
    assert sent[0][4] == LOWER, (
        f"reset email sent to {sent[0][4]!r} rather than the normalized "
        f"{LOWER!r} — a partial fix would find the account but still "
        f"echo the caller's spelling"
    )


def test_forgot_password_stays_silent_for_a_truly_unknown_address(
    tmp_path, monkeypatch,
):
    """The anti-enumeration property (return 200, send nothing) must
    survive the fix. A bug where the fix accidentally distinguished
    "known but wrong case" from "unknown" would leak account existence
    through the observable side effect of NOT sending an email."""
    sent = []

    def fake_send(*args):
        sent.append(args)

    monkeypatch.setattr("driverdna.ui.api.send_reset_email", fake_send, raising=False)
    monkeypatch.setattr("driverdna.ui.email.send_reset_email", fake_send)

    db_path = tmp_path / "email-norm-unknown.db"
    with Database.open(db_path):
        pass
    smtp = {"host": "smtp.example.com", "port": "587",
            "user": "u", "password": "p"}
    app = create_app(
        db_path, tmp_path / "cfg.toml",
        session_secret=SECRET, smtp_config=smtp,
    )
    c = TestClient(app)

    r = c.post("/api/auth/forgot-password",
               json={"email": "nobody@example.com"})
    assert r.status_code == 200
    assert sent == [], (
        f"forgot-password sent an email for an unregistered address: {sent}"
    )
