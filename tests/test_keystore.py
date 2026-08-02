"""SPEC.md A35: per-user AI key encryption at rest (BYOK)."""

from __future__ import annotations

import pytest

from driverdna.coach.keystore import decrypt_api_key, encrypt_api_key, fingerprint


def test_round_trip():
    ciphertext, nonce = encrypt_api_key("AIzaSyD-realistic-fake-key-1234", session_secret="s3cr3t")
    assert decrypt_api_key(ciphertext, nonce, session_secret="s3cr3t") == "AIzaSyD-realistic-fake-key-1234"


def test_ciphertext_never_contains_the_plaintext():
    plaintext = "AIzaSyD-realistic-fake-key-1234"
    ciphertext, nonce = encrypt_api_key(plaintext, session_secret="s3cr3t")
    assert plaintext not in ciphertext
    assert plaintext.encode() not in ciphertext.encode()


def test_wrong_secret_fails_to_decrypt():
    ciphertext, nonce = encrypt_api_key("real-key", session_secret="correct-secret")
    with pytest.raises(ValueError, match="cannot decrypt"):
        decrypt_api_key(ciphertext, nonce, session_secret="wrong-secret")


def test_encryption_is_nondeterministic_but_decrypts_the_same():
    """A fresh random nonce each time (never a fixed IV) -- two encryptions
    of the same plaintext must not produce identical ciphertext."""
    c1, n1 = encrypt_api_key("same-key", session_secret="s")
    c2, n2 = encrypt_api_key("same-key", session_secret="s")
    assert (c1, n1) != (c2, n2)
    assert decrypt_api_key(c1, n1, session_secret="s") == "same-key"
    assert decrypt_api_key(c2, n2, session_secret="s") == "same-key"


def test_fingerprint_never_equals_the_key_but_hints_at_it():
    key = "AIzaSyD-realistic-fake-key-1234"
    hint = fingerprint(key)
    assert hint != key
    assert key not in hint
    assert hint.startswith("AIza") and hint.endswith("1234")


def test_fingerprint_masks_short_keys_entirely():
    assert fingerprint("short") == "*****"
