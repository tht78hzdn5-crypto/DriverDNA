"""The `--host` auth interlock (docs/DEPLOY-SPEC.md track H1, item 1).

A non-loopback bind requires a configured session secret. It used to fall
back to an ephemeral, process-local one so a container would still start;
that fallback is retired (SPEC.md A41, owner-confirmed 2026-08-05) because on
a restart-prone host — a VM reboot, a `systemctl restart`, a new container
revision — a silently-rotating signing key means every session is signed out
with no explanation, and there is no log line pointing at why. The server now
refuses to start rather than start unauthenticatable-across-restarts; the
fix is to configure the secret, not to paper over its absence.
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


def test_binding_a_routable_address_without_a_passphrase_refuses_to_start(
    tmp_path, monkeypatch
):
    """No configured secret + a non-loopback bind: refuse outright. Never
    start unauthenticatable-across-restarts, and never touch uvicorn."""
    started = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 2, result.output
    assert auth.SESSION_SECRET_ENV in result.output
    assert started == [], "must not start the server on refusal"


def test_a_routable_address_with_a_passphrase_is_allowed(tmp_path, monkeypatch):
    started = []
    import uvicorn

    monkeypatch.setenv(auth.SESSION_SECRET_ENV, "a-long-random-passphrase")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert "auth=yes" in result.output
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


def test_a_blank_passphrase_refuses_too(tmp_path, monkeypatch):
    """A whitespace-only env var counts as unset, same as absent — refuses,
    it does not fall back to an ephemeral secret."""
    started = []
    import uvicorn

    monkeypatch.setenv(auth.SESSION_SECRET_ENV, "   ")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 2, result.output
    assert started == []


# --- --behind-proxy (SPEC.md A41, docs/VM-MIGRATION.md §3.1) --------------


def test_behind_proxy_on_loopback_without_a_passphrase_refuses_to_start(
    tmp_path, monkeypatch
):
    """The interlock keys off bind address alone, so a reverse proxy in
    front of a loopback-bound instance defeats it silently: the bind looks
    safe, `authenticated()` returns True unconditionally with no secret
    configured, and the whole internet reaches the cockpit through the
    proxy with no login. --behind-proxy makes the interlock apply
    regardless of bind address."""
    started = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--behind-proxy", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 2, result.output
    assert auth.SESSION_SECRET_ENV in result.output
    assert started == []


def test_behind_proxy_env_var_has_the_same_effect(tmp_path, monkeypatch):
    started = []
    import uvicorn

    monkeypatch.setenv("DRIVERDNA_BEHIND_PROXY", "1")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(app, ["ui", "--db", str(tmp_path / "x.db")])
    assert result.exit_code == 2, result.output
    assert started == []


def test_behind_proxy_on_loopback_with_a_passphrase_starts_and_trusts_the_proxy(
    tmp_path, monkeypatch
):
    """With the secret configured, --behind-proxy starts, and explicitly
    wires uvicorn to trust X-Forwarded-* only from 127.0.0.1 — the proxy's
    own address, never a wildcard."""
    started = []
    import uvicorn

    monkeypatch.setenv(auth.SESSION_SECRET_ENV, "a-long-random-passphrase")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--behind-proxy", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert "behind_proxy=yes" in result.output
    assert started and started[0]["proxy_headers"] is True
    assert started[0]["forwarded_allow_ips"] == "127.0.0.1"


def test_without_behind_proxy_forwarded_headers_are_not_trusted(tmp_path, monkeypatch):
    """The default (no flag) must not silently trust forwarded headers from
    anywhere — that trust is opt-in, not a library default relied on
    implicitly."""
    started = []
    import uvicorn

    monkeypatch.setenv(auth.SESSION_SECRET_ENV, "a-long-random-passphrase")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert "behind_proxy=no" in result.output
    assert started and started[0]["proxy_headers"] is False


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
