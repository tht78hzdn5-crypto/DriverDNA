
"""Tests for multi-user auth."""

import pytest

from driverdna.ui import auth

SECRET = "a-long-random-secret-key-for-sessions"
HOUR = 3600
USER_PK = 42
EPOCH = "2026-07-28T00:00:00"


# --- password hashing -----------------------------------------------------

def test_password_hashing():
    password = "correct horse battery staple"
    hashed = auth.hash_password(password)
    assert auth.verify_password(password, hashed) is True
    assert auth.verify_password("wrong", hashed) is False

def test_verify_password_rejects_malformed_hashes():
    assert auth.verify_password("password", "invalidhash") is False
    assert auth.verify_password("password", "") is False
    assert auth.verify_password("password", "salt:notb64") is False


# --- issuing and verifying a session --------------------------------------

def test_a_freshly_issued_session_verifies():
    value = auth.issue_session(USER_PK, EPOCH, SECRET, ttl_seconds=HOUR)
    result = auth.verify_session(value, SECRET)
    assert result is not None
    assert result == (USER_PK, EPOCH)


def test_a_session_expires():
    value = auth.issue_session(USER_PK, EPOCH, SECRET, ttl_seconds=HOUR, now=1_000_000)
    assert auth.verify_session(value, SECRET, now=1_000_000 + HOUR - 1) == (USER_PK, EPOCH)
    assert auth.verify_session(value, SECRET, now=1_000_000 + HOUR + 1) is None


def test_a_session_signed_with_a_different_secret_is_rejected():
    value = auth.issue_session(USER_PK, EPOCH, SECRET, ttl_seconds=HOUR)
    assert auth.verify_session(value, "a-different-secret") is None


def test_a_tampered_payload_is_rejected():
    value = auth.issue_session(USER_PK, EPOCH, SECRET, ttl_seconds=HOUR, now=1_000_000)
    payload, signature = value.split(".")
    forged_payload = auth._b64(f"99:{EPOCH}:2000000000".encode("ascii"))
    assert auth.verify_session(f"{forged_payload}.{signature}", SECRET) is None


def test_a_tampered_signature_is_rejected():
    value = auth.issue_session(USER_PK, EPOCH, SECRET, ttl_seconds=HOUR)
    payload, signature = value.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    assert auth.verify_session(f"{payload}.{flipped}", SECRET) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "nodot",
        "too.many.dots",
        "!!!.!!!",
        "aGk.",
        ".aGk",
        "bm90LWEtbnVtYmVy.aGk",
    ],
)
def test_a_malformed_session_is_rejected_and_never_raises(value):
    assert auth.verify_session(value, SECRET) is None


def test_two_sessions_issued_in_the_same_second_are_identical():
    a = auth.issue_session(USER_PK, EPOCH, SECRET, ttl_seconds=HOUR, now=1_000_000)
    b = auth.issue_session(USER_PK, EPOCH, SECRET, ttl_seconds=HOUR, now=1_000_000)
    assert a == b


def test_session_secret_from_env_reads_the_documented_variable(monkeypatch):
    monkeypatch.setenv("DRIVERDNA_SESSION_SECRET", SECRET)
    assert auth.session_secret_from_env() == SECRET


def test_an_unset_or_blank_variable_means_secret_is_not_configured(monkeypatch):
    monkeypatch.delenv("DRIVERDNA_SESSION_SECRET", raising=False)
    assert auth.session_secret_from_env() is None
    monkeypatch.setenv("DRIVERDNA_SESSION_SECRET", "   ")
    assert auth.session_secret_from_env() is None


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
    throttle = auth.LoginThrottle(max_attempts=1, lockout_seconds=10)
    for i in range(auth.MAX_THROTTLE_KEYS + 50):
        throttle.record_failure(f"10.0.0.{i}", now=0)
    assert len(throttle._failures) <= auth.MAX_THROTTLE_KEYS

