"""The fail-closed `--host` interlock (docs/DEPLOY-SPEC.md track H1, item 1).

> Add `--host`, and make the command **refuse to bind a non-loopback address
> unless authentication is configured**, with an error that names what's
> missing. A misconfiguration must not be able to publish an unauthenticated
> instrument to the internet.

The flag shipped for the container deployment; this interlock did not, so
`Dockerfile`'s `--host 0.0.0.0` has been publishing an unguarded API behind
nothing but a Cloud Run IAM flag.
"""

import pytest
from typer.testing import CliRunner

from driverdna.cli import _is_loopback, app
from driverdna.ui import auth

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_token(monkeypatch):
    """Every test states its own token situation; none inherits the shell's."""
    monkeypatch.delenv(auth.ACCESS_TOKEN_ENV, raising=False)


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


def test_binding_a_routable_address_without_a_passphrase_is_refused(tmp_path):
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code != 0
    assert auth.ACCESS_TOKEN_ENV in result.output
    # The error has to say what to do, not merely that something is wrong.
    assert "0.0.0.0" in result.output


def test_the_refusal_happens_before_a_server_is_started(tmp_path, monkeypatch):
    """Refusing after uvicorn has bound the socket would still have exposed
    the port."""
    started = []
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append((a, k)))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code != 0
    assert started == []


def test_a_routable_address_with_a_passphrase_is_allowed(tmp_path, monkeypatch):
    started = []
    import uvicorn

    monkeypatch.setenv(auth.ACCESS_TOKEN_ENV, "a-long-random-passphrase")
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


def test_a_blank_passphrase_does_not_satisfy_the_interlock(tmp_path, monkeypatch):
    """An env var set to empty is a misconfiguration — commonly an unset
    variable expanded by a shell — and must not read as "auth configured"."""
    monkeypatch.setenv(auth.ACCESS_TOKEN_ENV, "   ")
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code != 0
    assert auth.ACCESS_TOKEN_ENV in result.output


def test_the_passphrase_is_never_printed(tmp_path, monkeypatch):
    secret = "correct-horse-battery-staple"
    started = []
    import uvicorn

    monkeypatch.setenv(auth.ACCESS_TOKEN_ENV, secret)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
    result = runner.invoke(
        app, ["ui", "--host", "0.0.0.0", "--db", str(tmp_path / "x.db")]
    )
    assert result.exit_code == 0, result.output
    assert secret not in result.output
