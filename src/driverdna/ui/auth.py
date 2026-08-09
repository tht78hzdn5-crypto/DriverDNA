
"""Multi-user auth.

A shared secret in the environment (DRIVERDNA_SESSION_SECRET), exchanged for a 
signed, expiring session value that rides in an HttpOnly cookie.

Stateless. The session value carries an expiry, user_pk, session_epoch, and its 
signature, nothing else.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

SESSION_SECRET_ENV = "DRIVERDNA_SESSION_SECRET"
_ACCESS_TOKEN_ENV = "DRIVERDNA_ACCESS_TOKEN"
GOOGLE_CLIENT_ID_ENV = "GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET_ENV = "GOOGLE_CLIENT_SECRET"
GARAGE61_CLIENT_ID_ENV = "GARAGE61_CLIENT_ID"
GARAGE61_CLIENT_SECRET_ENV = "GARAGE61_CLIENT_SECRET"
SMTP_HOST_ENV = "SMTP_HOST"
SMTP_PORT_ENV = "SMTP_PORT"
SMTP_USER_ENV = "SMTP_USER"
SMTP_PASSWORD_ENV = "SMTP_PASSWORD"

SESSION_COOKIE = "driverdna_session"
_SIGNING_INFO = b"driverdna-session-v2|"
MAX_THROTTLE_KEYS = 1024

def _now() -> float:
    return time.time()

def session_secret_from_env() -> str | None:
    token = os.environ.get(SESSION_SECRET_ENV, "").strip()
    if not token:
        token = os.environ.get(_ACCESS_TOKEN_ENV, "").strip()
    return token or None

def google_client_id_from_env() -> str | None:
    return os.environ.get(GOOGLE_CLIENT_ID_ENV, "").strip() or None

def google_client_secret_from_env() -> str | None:
    return os.environ.get(GOOGLE_CLIENT_SECRET_ENV, "").strip() or None

def garage61_client_id_from_env() -> str | None:
    return os.environ.get(GARAGE61_CLIENT_ID_ENV, "").strip() or None

def garage61_client_secret_from_env() -> str | None:
    return os.environ.get(GARAGE61_CLIENT_SECRET_ENV, "").strip() or None

def smtp_config_from_env() -> dict[str, str] | None:
    host = os.environ.get(SMTP_HOST_ENV, "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": os.environ.get(SMTP_PORT_ENV, "587").strip(),
        "user": os.environ.get(SMTP_USER_ENV, "").strip(),
        "password": os.environ.get(SMTP_PASSWORD_ENV, "").strip(),
    }

def _signing_key(secret: str) -> bytes:
    return hashlib.sha256(_SIGNING_INFO + secret.encode("utf-8")).digest()

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"{_b64(salt)}:{_b64(key)}"

def verify_password(password: str, hashed: str) -> bool:
    try:
        salt_b64, key_b64 = hashed.split(":")
        salt = _unb64(salt_b64)
        expected_key = _unb64(key_b64)
    except ValueError:
        return False
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return hmac.compare_digest(key, expected_key)

def issue_session(user_pk: int, session_epoch: str, secret: str, *, ttl_seconds: int, now: float | None = None) -> str:
    expiry = int((_now() if now is None else now) + ttl_seconds)
    payload_str = f"{user_pk}|{session_epoch}|{expiry}"
    payload = payload_str.encode("ascii")
    signature = hmac.new(_signing_key(secret), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"

def verify_session(value: str, secret: str, *, now: float | None = None) -> tuple[int, str] | None:
    try:
        payload_b64, _, signature_b64 = value.partition(".")
        if not payload_b64 or not signature_b64:
            return None
        payload = _unb64(payload_b64)
        signature = _unb64(signature_b64)
    except (ValueError, TypeError):
        return None

    expected = hmac.new(_signing_key(secret), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
        
    try:
        payload_str = payload.decode("ascii")
        user_pk_str, session_epoch, expiry_str = payload_str.split("|")
        user_pk = int(user_pk_str)
        expiry = int(expiry_str)
    except ValueError:
        return None
        
    if (_now() if now is None else now) >= expiry:
        return None
        
    return (user_pk, session_epoch)

class LoginThrottle:
    def __init__(self, *, max_attempts: int, lockout_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._failures: dict[str, tuple[int, float]] = {}

    def locked_for(self, key: str, *, now: float | None = None) -> int:
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
        self._failures.pop(key, None)

    def _evict(self, now: float) -> None:
        if len(self._failures) <= MAX_THROTTLE_KEYS:
            return
        for key, (_, last) in list(self._failures.items()):
            if now - last >= self.lockout_seconds:
                del self._failures[key]
        while len(self._failures) > MAX_THROTTLE_KEYS:
            oldest = min(self._failures, key=lambda k: self._failures[k][1])
            del self._failures[oldest]

class RateLimiter:
    def __init__(self, *, limit: int, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, *, now: float | None = None) -> bool:
        moment = _now() if now is None else now
        start, count = self._windows.get(key, (moment, 0))
        if moment - start >= self.window_seconds:
            start, count = moment, 0
        if count >= self.limit:
            return False
        self._windows[key] = (start, count + 1)
        self._evict(moment)
        return True

    def _evict(self, now: float) -> None:
        if len(self._windows) <= MAX_THROTTLE_KEYS:
            return
        for key, (start, _) in list(self._windows.items()):
            if now - start >= self.window_seconds:
                del self._windows[key]
        while len(self._windows) > MAX_THROTTLE_KEYS:
            oldest = min(self._windows, key=lambda k: self._windows[k][0])
            del self._windows[oldest]

