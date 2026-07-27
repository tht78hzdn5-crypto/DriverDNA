"""Session primitives for single-driver auth (docs/DEPLOY-SPEC.md track H1).

These test `driverdna.ui.auth` on its own — no FastAPI, no client, no browser.
The module is deliberately pure so the cryptographic part of auth is provable
without standing anything up; the wiring is tested separately in
`test_auth_api.py`.
"""

import pytest

from driverdna.ui import auth

TOKEN = "a-long-random-passphrase-for-one-driver"
HOUR = 3600


# --- the credential check -------------------------------------------------


def test_check_token_accepts_the_configured_passphrase():
    assert auth.check_token(TOKEN, TOKEN) is True


@pytest.mark.parametrize(
    "supplied",
    [
        "",
        "wrong",
        TOKEN[:-1],  # a prefix must not pass
        TOKEN + "x",  # nor an extension
        TOKEN.upper(),  # nor a case variant
    ],
)
def test_check_token_rejects_anything_else(supplied):
    assert auth.check_token(supplied, TOKEN) is False


def test_check_token_is_constant_time():
    """`hmac.compare_digest`, not `==`. Asserted structurally rather than by
    timing, which would be flaky in CI: a timing test on a shared runner
    measures the runner, not the comparison."""
    import hmac
    import inspect

    source = inspect.getsource(auth.check_token)
    assert "compare_digest" in source
    assert hmac.compare_digest is not None


# --- issuing and verifying a session --------------------------------------


def test_a_freshly_issued_session_verifies():
    value = auth.issue_session(TOKEN, ttl_seconds=HOUR)
    assert auth.verify_session(value, TOKEN) is True


def test_a_session_expires():
    value = auth.issue_session(TOKEN, ttl_seconds=HOUR, now=1_000_000)
    assert auth.verify_session(value, TOKEN, now=1_000_000 + HOUR - 1) is True
    assert auth.verify_session(value, TOKEN, now=1_000_000 + HOUR + 1) is False


def test_a_session_signed_with_a_different_passphrase_is_rejected():
    """This is the whole revocation story: the signing key is derived from the
    passphrase, so rotating `DRIVERDNA_ACCESS_TOKEN` invalidates every
    outstanding session without any server-side session store."""
    value = auth.issue_session(TOKEN, ttl_seconds=HOUR)
    assert auth.verify_session(value, "a-different-passphrase") is False


def test_a_tampered_expiry_is_rejected():
    """Forging a later expiry is the obvious attack on a stateless cookie."""
    value = auth.issue_session(TOKEN, ttl_seconds=HOUR, now=1_000_000)
    payload, signature = value.split(".")
    forged_payload = auth._b64(str(2_000_000_000).encode("ascii"))
    assert auth.verify_session(f"{forged_payload}.{signature}", TOKEN) is False


def test_a_tampered_signature_is_rejected():
    value = auth.issue_session(TOKEN, ttl_seconds=HOUR)
    payload, signature = value.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    assert auth.verify_session(f"{payload}.{flipped}", TOKEN) is False


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "nodot",
        "too.many.dots",
        "!!!.!!!",  # not base64
        "aGk.",  # empty signature
        ".aGk",  # empty payload
        "bm90LWEtbnVtYmVy.aGk",  # payload is not an integer
    ],
)
def test_a_malformed_session_is_rejected_and_never_raises(value):
    """A cookie is attacker-controlled input. Anything that raises here is a
    500 on a public endpoint instead of a clean 401."""
    assert auth.verify_session(value, TOKEN) is False


def test_two_sessions_issued_in_the_same_second_are_identical():
    """Deliberate: the session carries an expiry and nothing else — no nonce,
    no counter, no server-side state. That is what lets it verify on any
    instance after any restart (Cloud Run scales to N instances)."""
    a = auth.issue_session(TOKEN, ttl_seconds=HOUR, now=1_000_000)
    b = auth.issue_session(TOKEN, ttl_seconds=HOUR, now=1_000_000)
    assert a == b


def test_a_session_value_carries_no_trace_of_the_passphrase():
    """The cookie goes to the browser; the secret must not ride along."""
    value = auth.issue_session(TOKEN, ttl_seconds=HOUR, now=1_000_000)
    assert TOKEN not in value
    # The payload is the expiry and nothing else.
    assert auth._unb64(value.split(".")[0]) == b"1003600"


# --- reading the secret from the environment ------------------------------


def test_access_token_from_env_reads_the_documented_variable(monkeypatch):
    monkeypatch.setenv("DRIVERDNA_ACCESS_TOKEN", TOKEN)
    assert auth.access_token_from_env() == TOKEN


def test_an_unset_or_blank_variable_means_auth_is_not_configured(monkeypatch):
    monkeypatch.delenv("DRIVERDNA_ACCESS_TOKEN", raising=False)
    assert auth.access_token_from_env() is None
    # A blank value is a misconfiguration, not a blank password.
    monkeypatch.setenv("DRIVERDNA_ACCESS_TOKEN", "   ")
    assert auth.access_token_from_env() is None


# --- login throttle -------------------------------------------------------


def test_a_run_of_failures_locks_further_attempts():
    throttle = auth.LoginThrottle(max_attempts=3, lockout_seconds=300)
    for _ in range(2):
        throttle.record_failure("1.2.3.4", now=0)
    assert throttle.locked_for("1.2.3.4", now=0) == 0
    throttle.record_failure("1.2.3.4", now=0)
    assert throttle.locked_for("1.2.3.4", now=0) == 300


def test_a_lockout_expires():
    throttle = auth.LoginThrottle(max_attempts=1, lockout_seconds=300)
    throttle.record_failure("1.2.3.4", now=0)
    assert throttle.locked_for("1.2.3.4", now=299) == 1
    assert throttle.locked_for("1.2.3.4", now=300) == 0


def test_a_lockout_is_per_key():
    throttle = auth.LoginThrottle(max_attempts=1, lockout_seconds=300)
    throttle.record_failure("1.2.3.4", now=0)
    assert throttle.locked_for("1.2.3.4", now=0) == 300
    assert throttle.locked_for("5.6.7.8", now=0) == 0


def test_a_successful_login_clears_the_record():
    throttle = auth.LoginThrottle(max_attempts=2, lockout_seconds=300)
    throttle.record_failure("1.2.3.4", now=0)
    throttle.reset("1.2.3.4")
    throttle.record_failure("1.2.3.4", now=0)
    assert throttle.locked_for("1.2.3.4", now=0) == 0


def test_the_throttle_does_not_grow_without_bound():
    """An in-process dict keyed by client address is a memory target on a
    public endpoint. Old entries are evicted rather than accumulated."""
    throttle = auth.LoginThrottle(max_attempts=1, lockout_seconds=10)
    for i in range(auth.MAX_THROTTLE_KEYS + 50):
        throttle.record_failure(f"10.0.0.{i}", now=0)
    assert len(throttle._failures) <= auth.MAX_THROTTLE_KEYS
