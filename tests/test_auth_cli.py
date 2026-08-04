"""The `--host` auth interlock (docs/DEPLOY-SPEC.md track H1, item 1).

A non-loopback bind always has auth ON. If no session secret is configured,
the server generates an ephemeral one (sessions won't persist across
restarts) and warns — so the container starts and Cloud Run's startup probe
succeeds. The server is never unauthenticated on a routable address.
"""

import pytest
from typer.testing import CliRunner

from driverdna.cli import _is_loopback, app
from driverdna.ui import auth

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_token(monkeypatch):
    """Every test states its own token situation; none inherits the shell's."""
    monkeypatch.delenv(auth.SESSION_SECRET_ENV, raising=False)


# --- what counts as loopback ---------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.5", "::1", "localhost"])
def test_loopback_addresses_are_recognised(host):
    assert _is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "10.0.0.1"])
def test_routable_addresses_are_not_loopback(host):
    assert _is_loopback(host) is False


def test_an_unresolvable_host_fails_closed():
    """A name this cannot parse is treated as exposed, not as safe. Guessing
    the other way is how an instrument ends up on the internet."""
    assert _is_loopback("cockpit.example.com") is False
    assert _is_loopback("") is False


# --- the interlock --------------------------------------------------------


def test_binding_a_routable_address_without_a_passphrase_uses_ephemeral_secret(
    tmp_path, monkeypatch
):
    """Without a configured secret the server starts with an ephemeral one
    (auth still on) and warns — so Cloud Run's container starts."""
    started = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert auth.SESSION_SECRET_ENV in result.output
    assert "ephemeral" in result.output
    assert started and started[0]["host"] == "0.0.0.0"


def test_ephemeral_secret_enables_auth(tmp_path, monkeypatch):
    """With no configured secret the ephemeral path still enables auth
    (auth='yes' in the startup banner) — the server is never unauthenticated."""
    started = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append((a, k)))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert "auth=yes" in result.output
    assert started != []


def test_a_routable_address_with_a_passphrase_is_allowed(tmp_path, monkeypatch):
    started = []
    import uvicorn

    monkeypatch.setenv(auth.SESSION_SECRET_ENV, "a-long-random-passphrase")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert started and started[0]["host"] == "0.0.0.0"


def test_loopback_still_needs_no_passphrase(tmp_path, monkeypatch):
    """The local instrument is unchanged: `driverdna ui` on loopback with no
    secret configured still just works, with no login."""
    started = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(app, ["ui", "--db", str(tmp_path / "x.db")])
    assert result.exit_code == 0, result.output
    assert started and started[0]["host"] == "127.0.0.1"


def test_a_blank_passphrase_uses_ephemeral_secret(tmp_path, monkeypatch):
    """An env var set to empty triggers the ephemeral-secret path, same as
    unset — the server still starts, auth still on."""
    started = []
    import uvicorn

    monkeypatch.setenv(auth.SESSION_SECRET_ENV, "   ")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert "ephemeral" in result.output
    assert started and started[0]["host"] == "0.0.0.0"


def test_the_passphrase_is_never_printed(tmp_path, monkeypatch):
    secret = "correct-horse-battery-staple"
    started = []
    import uvicorn

    monkeypatch.setenv(auth.SESSION_SECRET_ENV, secret)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert secret not in result.output
