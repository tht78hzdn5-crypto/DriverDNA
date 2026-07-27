"""Single-driver auth (docs/DEPLOY-SPEC.md, track H1).

A shared secret in the environment, exchanged for a signed, expiring session
value that rides in an HttpOnly cookie. Stdlib only — `hmac`, `hashlib`,
`base64` — so nothing here adds a dependency, and no third-party origin is
involved at either the browser or the process level. That is what leaves
UI-SPEC trust gates 5a and 5b (`tests/test_offline.py`) untouched.

Three properties are deliberate and load-bearing:

**Single-tenant by construction.** There is no user table, no registration and
no second identity (DEPLOY-SPEC.md's framing). This module authenticates *the
driver* against one passphrase; it never establishes *which* driver, because
there is only ever one. `laps.driver` stays what it always was — a data label,
unrelated to who is logged in.

**Stateless.** The session value carries an expiry and its signature, nothing
else: no session table, no server-side store, no nonce. It therefore verifies
on any process, after any restart, on any instance — which matters because the
hosted deployment (Cloud Run) can run more than one.

**Revocable by rotation.** The signing key is derived from the passphrase, so
changing `DRIVERDNA_ACCESS_TOKEN` invalidates every outstanding session. That
is the whole revocation story, and it is why there is no "log out everywhere".

This module is pure: it imports no FastAPI and opens no database, so the
cryptographic half of auth is testable without standing anything up.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

#: The passphrase. Env-only, exactly like `GARAGE61_TOKEN` and
#: `ANTHROPIC_API_KEY` — never persisted, never written to config, never
#: logged, and never accepted from a request body.
ACCESS_TOKEN_ENV = "DRIVERDNA_ACCESS_TOKEN"

#: Cookie name. `__Host-` prefixes were considered and rejected: they require
#: Secure, which would break plain-http loopback development, and the local
#: path is a first-class way to run this instrument.
SESSION_COOKIE = "driverdna_session"

#: Domain-separates the signing key from any other use of the same passphrase,
#: and versions the scheme: bumping this string invalidates every session.
_SIGNING_INFO = b"driverdna-session-v1|"

#: Cap on the throttle's in-process table. An unauthenticated endpoint keyed by
#: client address is otherwise a memory target.
MAX_THROTTLE_KEYS = 1024


def _now() -> float:
    return time.time()


def access_token_from_env() -> str | None:
    """The configured passphrase, or None when auth is not configured.

    A blank or whitespace-only value reads as *not configured* rather than as
    a blank password — an empty env var is a misconfiguration, and treating it
    as a valid credential would authenticate everyone.
    """
    token = os.environ.get(ACCESS_TOKEN_ENV, "").strip()
    return token or None


def _signing_key(token: str) -> bytes:
    return hashlib.sha256(_SIGNING_INFO + token.encode("utf-8")).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def check_token(supplied: str, token: str) -> bool:
    """Constant-time credential check (`hmac.compare_digest`, never `==`).

    `==` on strings short-circuits at the first differing byte, which leaks the
    length of a correct prefix to anyone who can time the login endpoint.
    """
    return hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8"))


def issue_session(token: str, *, ttl_seconds: int, now: float | None = None) -> str:
    """A signed session value: `base64url(expiry) "." base64url(hmac-sha256)`."""
    expiry = int((_now() if now is None else now) + ttl_seconds)
    payload = str(expiry).encode("ascii")
    signature = hmac.new(_signing_key(token), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def verify_session(value: str, token: str, *, now: float | None = None) -> bool:
    """True when `value` was signed by `token` and has not expired.

    Total by design: a cookie is attacker-controlled input, so every malformed
    shape returns False rather than raising. An exception here would be a 500
    on a public endpoint where a 401 belongs.
    """
    try:
        payload_b64, _, signature_b64 = value.partition(".")
        if not payload_b64 or not signature_b64:
            return False
        payload = _unb64(payload_b64)
        signature = _unb64(signature_b64)
    except (ValueError, TypeError):
        return False

    expected = hmac.new(_signing_key(token), payload, hashlib.sha256).digest()
    # Signature first, then expiry: an unsigned value's expiry is meaningless,
    # and checking it first would answer questions about forged payloads.
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        expiry = int(payload)
    except ValueError:
        return False
    return (_now() if now is None else now) < expiry


class LoginThrottle:
    """Failed-login limiter for the one unauthenticated endpoint.

    Keyed by caller-supplied string (the client address in practice), so the
    policy is testable and the key choice stays in the API layer.

    Two honest limits, neither of which this is trying to solve:

    - **It is in-process.** With more than one instance, each has its own
      table. `docs/DEPLOY-SPEC.md` H1.4 already requires a single worker for
      chat's sake; the same constraint covers this.
    - **A distributed source bypasses a per-key limit**, and a global limit
      would let anyone lock the driver out of their own instrument. The real
      defence is passphrase entropy; this stops trivial scanning and makes
      an online guessing attack impractical rather than impossible.
    """

    def __init__(self, *, max_attempts: int, lockout_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        # key -> (failure count, epoch of the most recent failure)
        self._failures: dict[str, tuple[int, float]] = {}

    def locked_for(self, key: str, *, now: float | None = None) -> int:
        """Seconds remaining on the lockout; 0 when attempts are allowed."""
        record = self._failures.get(key)
        if record is None:
            return 0
        count, last = record
        if count < self.max_attempts:
            return 0
        remaining = int(last + self.lockout_seconds - (_now() if now is None else now))
        if remaining <= 0:
            self._failures.pop(key, None)
            return 0
        return remaining

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        moment = _now() if now is None else now
        count, _ = self._failures.get(key, (0, moment))
        self._failures[key] = (count + 1, moment)
        self._evict(moment)

    def reset(self, key: str) -> None:
        """Called on a successful login — the driver got in, forget the misses."""
        self._failures.pop(key, None)

    def _evict(self, now: float) -> None:
        if len(self._failures) <= MAX_THROTTLE_KEYS:
            return
        # Drop entries whose lockout has lapsed first; if that is not enough
        # (a burst of distinct keys inside one window), drop the oldest.
        for key, (_, last) in list(self._failures.items()):
            if now - last >= self.lockout_seconds:
                del self._failures[key]
        while len(self._failures) > MAX_THROTTLE_KEYS:
            oldest = min(self._failures, key=lambda k: self._failures[k][1])
            del self._failures[oldest]
