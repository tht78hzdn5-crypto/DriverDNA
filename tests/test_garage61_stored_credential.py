"""Stored-credential path for `driverdna sync` (explicit opt-in only).

The CLI sync can resolve the Garage61 token from the Muse vault surrogate
instead of `GARAGE61_TOKEN`, but only when the caller passes
`use_stored_credential=True` (CLI: `--use-stored-credential`). Every other
construction path stays env-only. That default matters: the existing
requires-token tests keep passing on hosts with no credential configured
and, critically, on hosts WITH one — a test run must never turn into live
API calls because a stored credential happens to exist.

The resolver never raises and never logs a value: any failure (no authd
socket, non-200, malformed JSON, missing entry, wrong placement, a
non-surrogate value) degrades to None, and the caller raises its usual
"no token" error. The surrogate itself is not a credential: it resolves to
the real key only on approved egress to garage61.net, so it is carried in
memory only, like any other bearer value, and never written anywhere.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import driverdna.garage61.client as garage61_client
from driverdna.garage61.client import Garage61Client
from driverdna.cli import app


class _FakeSocket:
    """Canned unix-socket peer for the authd surrogate endpoint."""

    def __init__(self, response: bytes, sent: list, fail: Exception | None = None):
        self._response = response
        self._sent = sent
        self._fail = fail
        self.connected_path: str | None = None

    def settimeout(self, timeout):
        pass

    def connect(self, path):
        if self._fail is not None:
            raise self._fail
        self.connected_path = path

    def sendall(self, data):
        self._sent.append(data)

    def recv(self, size):
        if self._response:
            chunk, self._response = self._response, b""
            return chunk
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_response(status: int, payload) -> bytes:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    reason = "OK" if status == 200 else "Error"
    return (
        f"HTTP/1.1 {status} {reason}\r\nContent-Length: {len(body)}\r\n\r\n"
    ).encode() + body


def _surrogate_entry(surrogate="hsurr:FAKE", placement="bearer_header"):
    return {"credentials": [{"name": "access_token", "surrogate": surrogate, "placement": placement}]}


def _install_fake_socket(monkeypatch, response: bytes, sent: list, fail=None):
    fake_holder: dict = {}

    def factory(*args, **kwargs):
        fake = _FakeSocket(response, sent, fail)
        fake_holder["fake"] = fake
        return fake

    monkeypatch.setattr(garage61_client.socket, "socket", factory)
    return fake_holder


def test_resolver_returns_surrogate_on_valid_entry(monkeypatch):
    sent: list = []
    holder = _install_fake_socket(
        monkeypatch, _http_response(200, _surrogate_entry()), sent
    )
    assert garage61_client._request_stored_token() == "hsurr:FAKE"
    assert b"custom.garage61" in sent[0]
    assert holder["fake"].connected_path == "/run/hatch/auth/authd.sock"


def test_resolver_honours_socket_path_override(monkeypatch, tmp_path):
    sent: list = []
    holder = _install_fake_socket(
        monkeypatch, _http_response(200, _surrogate_entry()), sent
    )
    monkeypatch.setenv("JARVIS_AUTHD_SOCK", str(tmp_path / "authd.sock"))
    assert garage61_client._request_stored_token() == "hsurr:FAKE"
    assert holder["fake"].connected_path == str(tmp_path / "authd.sock")


def test_resolver_refuses_wrong_placement(monkeypatch):
    sent: list = []
    _install_fake_socket(
        monkeypatch,
        _http_response(200, _surrogate_entry(placement={"query_param": "api_key"})),
        sent,
    )
    assert garage61_client._request_stored_token() is None


def test_resolver_refuses_non_surrogate_value(monkeypatch):
    sent: list = []
    _install_fake_socket(
        monkeypatch, _http_response(200, _surrogate_entry(surrogate="real-token-value")), sent
    )
    assert garage61_client._request_stored_token() is None


def test_resolver_returns_none_on_missing_entry(monkeypatch):
    sent: list = []
    _install_fake_socket(
        monkeypatch, _http_response(200, {"credentials": [{"name": "other"}]}), sent
    )
    assert garage61_client._request_stored_token() is None


def test_resolver_returns_none_on_non_200(monkeypatch):
    sent: list = []
    _install_fake_socket(monkeypatch, _http_response(403, {"error": "nope"}), sent)
    assert garage61_client._request_stored_token() is None


def test_resolver_returns_none_on_malformed_response(monkeypatch):
    sent: list = []
    _install_fake_socket(monkeypatch, b"not-http-at-all", sent)
    assert garage61_client._request_stored_token() is None


def test_resolver_returns_none_when_socket_missing(monkeypatch):
    sent: list = []
    _install_fake_socket(monkeypatch, b"", sent, fail=OSError("no socket"))
    assert garage61_client._request_stored_token() is None


def test_explicit_token_beats_env_and_stored(monkeypatch):
    monkeypatch.setenv("GARAGE61_TOKEN", "env-token")
    monkeypatch.setattr(
        garage61_client, "_request_stored_token", lambda: "hsurr:STORED"
    )
    client = Garage61Client(token="explicit", use_stored_credential=True)
    assert client._transport.token == "explicit"


def test_env_beats_stored(monkeypatch):
    monkeypatch.setenv("GARAGE61_TOKEN", "env-token")
    monkeypatch.setattr(
        garage61_client, "_request_stored_token", lambda: "hsurr:STORED"
    )
    client = Garage61Client(use_stored_credential=True)
    assert client._transport.token == "env-token"


def test_stored_used_when_flag_on_and_nothing_else(monkeypatch):
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    monkeypatch.setattr(
        garage61_client, "_request_stored_token", lambda: "hsurr:STORED"
    )
    client = Garage61Client(use_stored_credential=True)
    assert client._transport.token == "hsurr:STORED"


def test_stored_not_attempted_when_flag_off(monkeypatch):
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    calls: list = []
    monkeypatch.setattr(
        garage61_client, "_request_stored_token", lambda: calls.append(1) or "hsurr:STORED"
    )
    with pytest.raises(RuntimeError, match="GARAGE61_TOKEN"):
        Garage61Client()
    assert calls == []


def test_error_message_never_carries_surrogate(monkeypatch):
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    sent: list = []
    _install_fake_socket(monkeypatch, b"", sent, fail=OSError("no socket"))
    with pytest.raises(RuntimeError) as exc_info:
        Garage61Client(use_stored_credential=True)
    assert "hsurr" not in str(exc_info.value)
    assert "GARAGE61_TOKEN" in str(exc_info.value)


def test_cli_sync_flag_passes_stored_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    recorded: dict = {}

    class _DummyClient:
        def __init__(self, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr(garage61_client, "Garage61Client", _DummyClient)
    monkeypatch.setattr(
        "driverdna.garage61.sync.sync_driver", lambda *a, **k: []
    )
    result = CliRunner().invoke(
        app, ["sync", "--db", str(tmp_path / "t.db"), "--use-stored-credential"]
    )
    assert result.exit_code == 0, result.output
    assert "no cohorts found" in result.output
    assert recorded.get("use_stored_credential") is True
