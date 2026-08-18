"""BUG-032a: `ConfigStore.revert` had no owner filter, and
`GET /api/config/history` returned every user's rows. Either was enough
for one authenticated caller to reach into another user's config: revert
by guessing (or leaking) a small integer `change_pk`; read by asking.

`config_history` had carried `owner_user_pk` since migration 009 — the
audit trail *looked* per-user while the reads did not, which is worse
than plainly global (the write side spelled out an isolation guarantee
the read side did not honour). Pinned here (SPEC.md A53).

Scope: this is BUG-032**a** — the missing-owner-filter defect only. The
per-user config redesign (BUG-032b: overrides, fingerprints beside every
measurement, canonical reference config) is a separate build and is not
touched by these tests. Config remains instance-wide today, so an
`apply()` writes a single TOML file for the whole instance. The bug is
that ANY user could revert it or read history rows they did not create.

Runs at the HTTP layer (not just the ConfigStore layer), because the
attack shape is a user posting an integer at a URL, and the fix has to
hold together across `config.py` (the store) and `ui/api.py` (the
history endpoint).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from driverdna.db import Database
from driverdna.ui.api import create_app
from driverdna.ui.auth import hash_password


SECRET = "config-tenancy-test-secret-passphrase-long-enough"
ALICE_EMAIL, ALICE_PW = "alice@example.com", "alice-not-bob-password"
BOB_EMAIL, BOB_PW = "bob@example.com", "bob-not-alice-password"

# A safe, boring config key with a known default and a valid range.
# `detectors.max_corrections` is used by test_api.py's config tests too,
# so the write path is proven to work.
CFG_KEY = "detectors.max_corrections"
CFG_ORIG = 1
CFG_NEW = 3


def _seed_two_users(db_path: Path) -> None:
    with Database.open(db_path) as db:
        with db.conn:
            db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (ALICE_EMAIL, hash_password(ALICE_PW)),
            )
            db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (BOB_EMAIL, hash_password(BOB_PW)),
            )


@pytest.fixture
def two_user_app(tmp_path):
    db_path = tmp_path / "config-tenancy.db"
    config_path = tmp_path / "cfg.toml"  # starts absent; apply() creates it
    _seed_two_users(db_path)
    app = create_app(db_path, config_path, session_secret=SECRET)
    return {
        "app": app, "db_path": db_path, "config_path": config_path,
    }


def _login(app, email: str, password: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def _apply(client: TestClient) -> int:
    """Apply `CFG_KEY: CFG_ORIG -> CFG_NEW` as the current user; return the
    change_pk of the created history row."""
    r = client.post("/api/config/propose", json={"key": CFG_KEY, "new_value": CFG_NEW})
    assert r.status_code == 200, r.text
    proposal = r.json()
    r = client.post("/api/config/apply", json={"proposal": proposal})
    assert r.status_code == 200, r.text
    return int(r.json()["change_pk"])


def test_bob_cannot_revert_alices_config_change(two_user_app):
    """The BUG-032a pinning test. Alice applies a change; Bob POSTs to
    /api/config/revert/{alice_change_pk}. Bob's request must be refused
    — not silently succeed and rewrite the TOML back to Alice's old
    value. Any status in [400, 500) is acceptable; the fix chose 404
    (matches an unknown-change_pk, so the endpoint does not confirm the
    change exists)."""
    alice = _login(two_user_app["app"], ALICE_EMAIL, ALICE_PW)
    bob = _login(two_user_app["app"], BOB_EMAIL, BOB_PW)

    alice_change_pk = _apply(alice)
    toml_after_alice = two_user_app["config_path"].read_text(encoding="utf-8")
    assert f"{CFG_NEW}" in toml_after_alice

    r = bob.post(f"/api/config/revert/{alice_change_pk}")
    assert 400 <= r.status_code < 500, (
        f"Bob's revert on Alice's change_pk must be refused; got "
        f"{r.status_code}: {r.text}"
    )

    # And the TOML on disk must still carry Alice's applied value —
    # Bob's revert must not have rewritten anything.
    assert two_user_app["config_path"].read_text(encoding="utf-8") == toml_after_alice


def test_bob_cannot_read_alices_config_history(two_user_app):
    """`GET /api/config/history` returned every user's rows. Alice's key,
    values, source and note (her own words about her own change) were
    visible to every authenticated caller."""
    alice = _login(two_user_app["app"], ALICE_EMAIL, ALICE_PW)
    bob = _login(two_user_app["app"], BOB_EMAIL, BOB_PW)

    _apply(alice)

    r = bob.get("/api/config/history")
    assert r.status_code == 200, r.text
    rows = r.json()
    # Bob has made no changes of his own, so the list must be empty for him.
    assert rows == [], (
        f"GET /api/config/history returned Alice's rows to Bob: {rows}"
    )

    # And Alice still sees her own.
    r = alice.get("/api/config/history")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["key"] == CFG_KEY


def test_alice_can_revert_her_own_change_and_it_writes_the_toml_back(two_user_app):
    """Regression guard: the fix must not break the legitimate path.
    Alice applies then reverts her own change — the TOML on disk must
    match the pre-apply state (or the apply must never have written it
    in the first place)."""
    alice = _login(two_user_app["app"], ALICE_EMAIL, ALICE_PW)
    alice_pk = _apply(alice)
    assert f"{CFG_NEW}" in two_user_app["config_path"].read_text(encoding="utf-8")

    r = alice.post(f"/api/config/revert/{alice_pk}")
    assert r.status_code == 200, r.text
    revert_row = r.json()
    assert revert_row["key"] == CFG_KEY
    # After Alice's revert, the TOML must hold CFG_ORIG for this specific
    # key. Read via load_config rather than by grepping bytes — the TOML
    # has dozens of `= <int>` lines and a naive substring match hits
    # unrelated defaults.
    from driverdna.config import config_snapshot, load_config
    got = config_snapshot(load_config(two_user_app["config_path"]))
    assert got[CFG_KEY] == CFG_ORIG, (
        f"revert did not restore {CFG_KEY}: got {got[CFG_KEY]!r}"
    )
