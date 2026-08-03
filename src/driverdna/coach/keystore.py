"""Per-user AI provider keys, encrypted at rest (SPEC.md A37, "BYOK").

Reverses the env-only-secrets non-negotiable for exactly this one case, by
owner decision, recorded there rather than left implied: a *user-supplied*
provider key may be persisted, encrypted, scoped to one account. Every
server-side secret (GARAGE61_TOKEN, ANTHROPIC_API_KEY, GEMINI_API_KEY,
DRIVERDNA_DATABASE_URL, DRIVERDNA_SESSION_SECRET) stays env-only, unchanged
— this module never reads or writes any of those.

AES-256-GCM (the `cryptography` package — stdlib ships no AEAD, and hand-
rolling encryption would be strictly worse than the one well-reviewed
dependency this justifies, SPEC.md A37's own recorded reasoning). The
key-encryption key is derived from `DRIVERDNA_SESSION_SECRET` via
`hashlib.scrypt` — the same primitive `ui/auth.py` already uses for
passwords, with its own fixed domain-separation salt so this derived key
can never collide with `ui/auth.py`'s own session-signing key even though
both start from the same secret. A fixed (not random) salt is correct here:
this is a KDF over one shared secret, not a password hash, and it must be
deterministic across restarts or every previously-encrypted key becomes
undecryptable.

BYOK is meaningless without a configured `DRIVERDNA_SESSION_SECRET` — the
local, no-auth `driverdna ui` path has no secret to derive a
key-encryption key from, and this module never falls back to an insecure
default. Callers must check for that case themselves (api.py returns a
directive error, never silently encrypts with a predictable key).
"""

from __future__ import annotations

import hashlib
import secrets

from driverdna.ui.auth import _b64, _unb64

_KDF_SALT = b"driverdna-byok-kek-v1"


def _derive_key(session_secret: str) -> bytes:
    return hashlib.scrypt(
        session_secret.encode("utf-8"), salt=_KDF_SALT, n=16384, r=8, p=1, dklen=32
    )


def encrypt_api_key(plaintext: str, *, session_secret: str) -> tuple[str, str]:
    """(ciphertext_b64, nonce_b64) — both safe to store in the DB as-is."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _derive_key(session_secret)
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _b64(ciphertext), _b64(nonce)


def decrypt_api_key(ciphertext_b64: str, nonce_b64: str, *, session_secret: str) -> str:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _derive_key(session_secret)
    try:
        plaintext = AESGCM(key).decrypt(_unb64(nonce_b64), _unb64(ciphertext_b64), None)
    except InvalidTag:
        # Wrong session_secret (rotated) or corrupted row -- never guess,
        # never return garbage bytes as if they were the key.
        raise ValueError("cannot decrypt stored API key: wrong secret or corrupted row") from None
    return plaintext.decode("utf-8")


def fingerprint(plaintext: str) -> str:
    """A non-secret display hint (e.g. 'AIza...7f3c') -- never enough to
    reconstruct the key, shown so the driver can confirm which key is set
    without it ever being echoed back in full."""
    if len(plaintext) <= 8:
        return "*" * len(plaintext)
    return f"{plaintext[:4]}...{plaintext[-4:]}"
