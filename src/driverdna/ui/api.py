"""U0 — the API layer (docs/UI-SPEC.md, decision 2 and 3).

Read endpoints are pass-throughs: the payload endpoints return the SAME
normalized bytes as `driverdna report` JSON files (contract-tested), and
everything else is an existing DB read. Write endpoints wrap the audited
paths (`db.annotate_finding`, `ConfigStore.propose/apply`) and return the
audit record they created. No aggregation, statistics, or ranking happens
here — the SPA gets exactly what the engine computed.

Chat endpoints land with U3 alongside their SSE display contract (recorded
deviation from the spec's U0 wording: shipping a chat API before the
validated-display client exists would invite unvalidated rendering).
"""

from __future__ import annotations

import base64
import gc
import json
import logging
import queue
import secrets
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from driverdna.attribution.engine import PHASES, reference_envelope
from driverdna.chat.session import ChatProvider, ChatSession
from driverdna.chat.tools import execute_tool
from driverdna.coach import keystore
from driverdna.config import ConfigStore, config_snapshot, describe_key, load_config
from driverdna.explain import METHODOLOGY
from driverdna.blobs import open_blob_store
from driverdna.db import Database, open_postgres_pool
from driverdna.store import is_postgres_url, missing_reason
from driverdna.ui import auth
from driverdna.report.payload import (
    build_cohort_payload,
    build_driver_payload,
    cohort_slug,
    list_cohorts,
    to_normalized_json,
)

logger = logging.getLogger(__name__)

TRACE_POINTS = 800  # transport downsampling only — layout math, not measurement

# A34. Phrased for the browser, where this is the whole explanation the driver
# gets — the CLI's own wording is in cli.py's import pre-flight.
_REFERENCE_FIRST_LAP_DETAIL = (
    "a reference lap cannot be the first lap in its cohort. The first lap "
    "builds the corner map — every corner's position and every phase window — "
    "and a map built from another driver's line becomes the coordinate system "
    "your own laps are measured in. Upload one of your own laps in this "
    "car/track first."
)


class AnnotateBody(BaseModel):
    status: str  # acknowledged | intentional
    note: str | None = None


class ExcludeReferenceBody(BaseModel):
    note: str | None = None


class ProposeBody(BaseModel):
    key: str
    new_value: Any


class ApplyBody(BaseModel):
    proposal: dict[str, Any]
    note: str | None = None


class SyncBody(BaseModel):
    car: str | None = None
    track: str | None = None


class ChatCreateBody(BaseModel):
    cohort: str  # cohort slug, as returned by GET /api/cohorts
    driver: str = "owner"


class ChatMessageBody(BaseModel):
    text: str


class ApiKeyBody(BaseModel):
    provider: str  # "claude" | "gemini"
    key: str


class RegisterBody(BaseModel):
    email: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


class ForgotPasswordBody(BaseModel):
    email: str


class ResetPasswordBody(BaseModel):
    token: str
    new_password: str


#: Reachable without a session: the login exchange itself, and the status probe
#: the SPA uses to decide whether to draw the login gate. The static shell is
#: also public — it is a `StaticFiles` mount rather than a route, so the guard
#: never sees it, which is correct: the shell is what renders the login screen.
#: `/health` is the liveness probe — it carries no session cookie, and
#: must answer even while the store is unreachable or still migrating.
PUBLIC_API_PATHS = frozenset({
    "/health",
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/google/login",
    "/api/auth/google/callback",
    "/api/auth/garage61/login",
    "/api/auth/garage61/callback",
    "/api/auth/register",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
})


#: Bounds on live chat sessions. Each one pins a database connection for its
#: lifetime, so these are what stop abandoned browser tabs from exhausting a
#: hosted store's connection limit. Kept comfortably below any sane pool size.
MAX_CHAT_SESSIONS = 8
CHAT_SESSION_TTL_S = 60 * 60


def create_app(
    db_path: Path | str,
    config_path: Path,
    *,
    chat_provider_factory: Callable[[], ChatProvider] | None = None,
    session_secret: str | None = None,
    google_client_id: str | None = None,
    google_client_secret: str | None = None,
    smtp_config: dict[str, str] | None = None,
    garage61_client_id: str | None = None,
    garage61_client_secret: str | None = None,
    behind_proxy: bool = False,
) -> FastAPI:
    """`chat_provider_factory` defaults to `chat.session.make_chat_provider`
    (Claude or Gemini per `config.coach.provider`, env-only API key,
    lazy-imported so nothing else needs either SDK installed); tests inject
    a mocked provider here, same pattern as the CLI's `chat` command — no
    test ever calls a live model.

    `session_secret` is the single-driver passphrase / session-signing key
    (docs/DEPLOY-SPEC.md H1), injected the same way rather than read from the
    environment here, so tests never depend on process state. **None means
    auth is not configured and every route is open** — which is the local
    `driverdna ui` experience on loopback, and what keeps this change
    additive rather than a rewrite. The CLI supplies it from
    `DRIVERDNA_SESSION_SECRET` and refuses to bind a non-loopback address
    without it.

    `behind_proxy` (SPEC.md A41, docs/VM-MIGRATION.md §3.1/§3.3) says a
    reverse proxy on the same host sits in front of this process — the CLI
    sets it from `--behind-proxy`/`$DRIVERDNA_BEHIND_PROXY` and, when true,
    also wires uvicorn's `ProxyHeadersMiddleware` to trust `X-Forwarded-*`
    only from `127.0.0.1`. That trust boundary is what this flag lets the
    app rely on: `_is_https` trusts the already-resolved
    `request.url.scheme` instead of re-reading the header itself (which has
    no trust boundary at the app layer). It does not change `_client_key` —
    that already reads the ASGI-level `scope["client"]`, which the
    middleware itself rewrites, with no app-layer code involved.
    """
    _pool = None
    _is_pg = is_postgres_url(db_path)
    _pg_blobs = open_blob_store(db_path) if _is_pg else None

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        nonlocal _pool
        if _is_pg:
            try:
                _pool = open_postgres_pool(str(db_path))
                app.state.pool = _pool
            except Exception as exc:
                import sys
                print(f"WARNING: database pool failed: {exc}", file=sys.stderr)
        yield
        if _pool is not None:
            _pool.close()
            _pool = None

    # The throttle holds state, so its policy is fixed when the app is built:
    # changing login_max_attempts/login_lockout_seconds takes effect on
    # restart. Ordinary for a rate limiter, and stated rather than discovered.
    # The session TTL is read per login, like every other config value here.
    _startup = load_config(config_path)
    throttle = auth.LoginThrottle(
        max_attempts=_startup.auth.login_max_attempts,
        lockout_seconds=_startup.auth.login_lockout_seconds,
    )
    chat_limiter = auth.RateLimiter(limit=_startup.api.chat_requests_per_minute)
    _warned_unproxied_forward = False

    smtp_host = smtp_config.get("host") if smtp_config else None
    smtp_port = smtp_config.get("port") if smtp_config else None
    smtp_user = smtp_config.get("user") if smtp_config else None
    smtp_password = smtp_config.get("password") if smtp_config else None

    def authenticated(request: Request) -> bool:
        if session_secret is None:
            request.state.user_pk = 1
            # Do not set session_epoch here; open_db will skip the epoch check
            return True
        cookie = request.cookies.get(auth.SESSION_COOKIE)
        if not cookie:
            return False
        result = auth.verify_session(cookie, session_secret)
        if not result:
            return False
        user_pk, session_epoch = result
        request.state.user_pk = user_pk
        request.state.session_epoch = session_epoch
        return True

    def guard(request: Request) -> None:
        """The whole auth surface: one app-level dependency.

        Attached via `FastAPI(dependencies=[...])` rather than per route, so a
        route added later is guarded by default instead of by remembering —
        DEPLOY-SPEC's done-criterion is a test that enumerates `app.routes`
        precisely because the opposite is so easy to get wrong.

        It raises before the endpoint's own parameters are solved, so an
        unauthenticated request never reaches body validation or the database.
        """
        nonlocal _warned_unproxied_forward
        if (
            session_secret is None
            and not behind_proxy
            and not _warned_unproxied_forward
            and (
                request.headers.get("x-forwarded-for")
                or request.headers.get("x-forwarded-proto")
            )
        ):
            # docs/VM-MIGRATION.md §3.1 option (c), downgraded to a warning
            # per its own reasoning: a hard refusal here would be a
            # confusing failure mode. But this exact combination — no
            # secret, no --behind-proxy, yet forwarded headers arriving
            # anyway — is precisely how a loopback-bound instance ends up
            # reachable by the whole internet with no login at all: the
            # interlock keys off bind address, which a reverse proxy in
            # front of a loopback bind defeats silently. Once per app
            # instance, so a legitimate proxy setup doesn't spam the log.
            _warned_unproxied_forward = True
            logger.warning(
                "request arrived with X-Forwarded-* headers, but no %s is "
                "configured and --behind-proxy was not set. If a reverse "
                "proxy really is in front of this process, EVERY request is "
                "currently authenticated as the owner with no login. Set "
                "%s and pass --behind-proxy, or remove the proxy.",
                auth.SESSION_SECRET_ENV, auth.SESSION_SECRET_ENV,
            )
        if request.url.path in PUBLIC_API_PATHS or authenticated(request):
            _rate_limit(request)
            return
        raise HTTPException(401, detail="not authenticated")

    def _rate_limit(request: Request) -> None:
        """Only `/api/chat/*` — the one family of endpoints that reaches a
        metered third-party model (DEPLOY-SPEC H1.3). Reading your own
        findings is never throttled."""
        if not request.url.path.startswith("/api/chat/"):
            return
        if not chat_limiter.allow(_client_key(request)):
            raise HTTPException(
                429, detail="chat rate limit reached — wait a moment and retry"
            )

    app = FastAPI(
        title="DriverDNA",
        docs_url=None,
        redoc_url=None,
        dependencies=[Depends(guard)],
        # FastAPI registers its schema with `add_route`, not `add_api_route`,
        # so app-level dependencies never see it — it answered 200 on a live
        # server with a passphrase set, publishing every endpoint and request
        # model to anyone who asked. Disabled here and re-declared below as an
        # ordinary route, which the guard does see.
        openapi_url=None,
        lifespan=_lifespan,
    )
    chat_sessions: dict[str, dict[str, Any]] = {}

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Anything not already an HTTPException (a DB timeout, a connection
        # refusal, a bad query) would otherwise surface as a bare, unlogged
        # "Internal Server Error" with no trace of what happened.
        logger.exception("unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @app.get("/health")
    def health() -> dict[str, Any]:
        # No DB access: this is the liveness probe, and it must answer even
        # while the store is unreachable or still migrating. `store` and
        # `auth` are the two non-secret deployment facts (SPEC.md A41,
        # docs/VM-MIGRATION.md §3.7.3) that turn a misconfiguration into a
        # visible fact instead of an inferred one — never the DSN, never any
        # secret value, both already known at app-build time so this adds no
        # new DB access.
        return {
            "status": "ok",
            "store": "postgres" if _is_pg else "sqlite",
            "auth": session_secret is not None,
        }

    @app.get("/openapi.json", include_in_schema=False)
    def openapi_schema() -> dict[str, Any]:
        """The schema, for the signed-in driver only. Kept rather than removed
        because with no passphrase configured this stays available exactly as
        before, so local tooling and readiness probes are unaffected."""
        return app.openapi()

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        """`no-store` on every API response (DEPLOY-SPEC H1.3).

        Two reasons, both real: a cached finding is a wrong number shown as a
        current one (UI-SPEC's service-worker rule), and these responses are
        session-bearing. Static assets are left cacheable — they are hashed by
        Vite and carry no data.
        """
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # --- auth (DEPLOY-SPEC H1) ----------------------------------------------

    def _client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _google_error_redirect(message: str) -> Response:
        import urllib.parse
        safe = urllib.parse.quote(message[:200], safe="")
        return RedirectResponse(f"/?auth_error={safe}", status_code=302)

    def _is_https(request: Request) -> bool:
        """Two deployment shapes, two trust sources — never both at once.

        `behind_proxy=True`: uvicorn's own `ProxyHeadersMiddleware` (wired by
        the CLI to trust `X-Forwarded-*` only from `127.0.0.1`, the proxy's
        own address) has already resolved `request.url.scheme` before the
        app ever sees the request. Trust that — re-reading the header here
        too would have no trust boundary at the app layer and would believe
        anyone who could reach the port at all.

        `behind_proxy=False` (e.g. a managed platform whose front end
        forwards `X-Forwarded-Proto` from an address outside uvicorn's
        `forwarded_allow_ips`): the middleware never rewrites the scheme.
        Read the header directly — the only way to avoid shipping an
        unmarked session cookie over a real HTTPS deployment there.
        """
        if behind_proxy:
            return request.url.scheme == "https"
        forwarded = request.headers.get("x-forwarded-proto", "")
        if forwarded:
            return forwarded.split(",")[0].strip() == "https"
        return request.url.scheme == "https"

    @app.post("/api/auth/register")
    def register(body: RegisterBody, request: Request, response: Response) -> dict[str, Any]:
        """Create a new account and return a signed session cookie."""
        if session_secret is None:
            raise HTTPException(400, detail=f"auth not configured - set {auth.SESSION_SECRET_ENV}")

        key = _client_key(request)
        locked = throttle.locked_for(key)
        if locked:
            raise HTTPException(429, detail=f"too many attempts — try again in {locked}s")

        if not body.email or not body.email.strip():
            raise HTTPException(400, detail="email is required")
        if len(body.password) < 8:
            raise HTTPException(400, detail="password must be at least 8 characters")

        email = body.email.strip().lower()
        from datetime import datetime
        session_epoch = datetime.utcnow().isoformat()
        password_hash = auth.hash_password(body.password)

        with open_db(request) as db:
            existing = db.conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
            if existing:
                throttle.record_failure(key)
                raise HTTPException(409, detail="an account with this email already exists")

            with db.conn:
                user_pk = db.conn.execute(
                    "INSERT INTO users (email, password_hash, session_epoch, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) RETURNING user_pk",
                    (email, password_hash, session_epoch,
                     datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
                ).fetchone()["user_pk"]

        ttl = load_config(config_path).auth.session_ttl_hours * 3600
        response.set_cookie(
            auth.SESSION_COOKIE,
            auth.issue_session(user_pk, session_epoch, session_secret, ttl_seconds=ttl),
            max_age=ttl,
            httponly=True,
            samesite="lax",
            secure=_is_https(request),
            path="/",
        )
        return {"authenticated": True, "user_pk": user_pk}

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        """Exchange credentials for a signed, expiring session cookie.

        BUG-034 (SPEC.md A53): the lookup normalizes the typed email the
        same way `register` does (`strip().lower()`). Text columns are
        `COLLATE "C"` (A23), so Postgres does not case-fold either — a
        user who registered as `User@Example.com` was permanently locked
        out because the stored row was `user@example.com` and login
        queried the raw string. Reset had the same bug (BUG-034 covers
        `forgot-password` and the Google callback lookup too).
        """
        if session_secret is None:
            raise HTTPException(400, detail=f"auth not configured - set {auth.SESSION_SECRET_ENV}")

        key = _client_key(request)
        locked = throttle.locked_for(key)
        if locked:
            raise HTTPException(429, detail=f"too many failed attempts — try again in {locked}s")

        from datetime import datetime
        session_epoch = datetime.utcnow().isoformat()
        email = (body.email or "").strip().lower()

        with open_db(request) as db:
            row = db.conn.execute("SELECT user_pk, password_hash FROM users WHERE email=?", (email,)).fetchone()
            if not row or not auth.verify_password(body.password, row["password_hash"]):
                throttle.record_failure(key)
                raise HTTPException(401, detail="incorrect email or password")
                
            user_pk = row["user_pk"]
            with db.conn:
                db.conn.execute(
                    "UPDATE users SET session_epoch=? WHERE user_pk=?", 
                    (session_epoch, user_pk)
                )

        throttle.reset(key)
        ttl = load_config(config_path).auth.session_ttl_hours * 3600
        
        response.set_cookie(
            auth.SESSION_COOKIE,
            auth.issue_session(user_pk, session_epoch, session_secret, ttl_seconds=ttl),
            max_age=ttl,
            httponly=True,
            samesite="lax",
            secure=_is_https(request),
            path="/",
        )
        return {"authenticated": True, "user_pk": user_pk}

    @app.post("/api/auth/forgot-password")
    def forgot_password(body: ForgotPasswordBody, request: Request) -> dict[str, str]:
        if not all([smtp_host, smtp_port, smtp_user, smtp_password]):
            raise HTTPException(400, detail="SMTP is not configured")

        import secrets
        import hashlib
        from datetime import datetime, timedelta

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = (datetime.utcnow() + timedelta(minutes=15)).isoformat()
        # BUG-034: normalize before both the lookup and the outgoing
        # email. Sending to the caller's original spelling would leak
        # the anti-enumeration property when normalization changed the
        # match — and would let a mistyped-case entry bounce.
        email = (body.email or "").strip().lower()

        with open_db(request) as db:
            row = db.conn.execute("SELECT user_pk FROM users WHERE email=?", (email,)).fetchone()
            if row:
                user_pk = row["user_pk"]
                with db.conn:
                    db.conn.execute(
                        "INSERT INTO password_resets (user_pk, reset_token_hash, expires_at) VALUES (?, ?, ?)",
                        (user_pk, token_hash, expires_at)
                    )

                from driverdna.ui.email import send_reset_email
                reset_link = f"{str(request.base_url).rstrip('/')}/reset-password?token={token}"
                send_reset_email(smtp_host, int(smtp_port), smtp_user, smtp_password, email, reset_link)

        # Always return 200 to prevent email enumeration
        return {"status": "ok"}

    @app.post("/api/auth/reset-password")
    def reset_password(body: ResetPasswordBody, request: Request) -> dict[str, str]:
        import hashlib
        from datetime import datetime
        
        token_hash = hashlib.sha256(body.token.encode()).hexdigest()
        now = datetime.utcnow().isoformat()
        
        with open_db(request) as db:
            row = db.conn.execute(
                "SELECT user_pk, expires_at FROM password_resets WHERE reset_token_hash=?", 
                (token_hash,)
            ).fetchone()
            
            if not row or row["expires_at"] < now:
                raise HTTPException(400, detail="invalid or expired token")
                
            user_pk = row["user_pk"]
            new_password_hash = auth.hash_password(body.new_password)
            
            with db.conn:
                db.conn.execute("UPDATE users SET password_hash=? WHERE user_pk=?", (new_password_hash, user_pk))
                db.conn.execute("DELETE FROM password_resets WHERE user_pk=?", (user_pk,))
                
        return {"status": "ok"}

    @app.get("/api/auth/google/login")
    def google_login(request: Request) -> Response:
        if not google_client_id:
            raise HTTPException(400, "Google OAuth not configured")
        if not session_secret:
            raise HTTPException(400, "session secret required for Google OAuth")

        import urllib.parse

        url_obj = request.url_for("google_callback")
        if _is_https(request):
            url_obj = url_obj.replace(scheme="https")

        state = secrets.token_urlsafe(32)
        from driverdna.coach.keystore import encrypt_api_key
        ct, nonce = encrypt_api_key(state, session_secret=session_secret)
        state_cookie = f"{ct}.{nonce}"

        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": google_client_id,
            "redirect_uri": str(url_obj),
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
            "state": state,
        })
        response = RedirectResponse(url)
        response.set_cookie(
            "_google_oauth_state", state_cookie,
            max_age=600, httponly=True, samesite="lax",
            secure=_is_https(request), path="/api/auth/google/callback",
        )
        return response

    @app.get("/api/auth/google/callback")
    def google_callback(code: str, state: str, request: Request) -> Response:
        if not google_client_id or not google_client_secret or not session_secret:
            raise HTTPException(400, "Google OAuth not configured")

        import urllib.request
        import urllib.parse

        state_cookie = request.cookies.get("_google_oauth_state")
        if not state_cookie:
            return _google_error_redirect("missing state cookie — try again")
        try:
            ct, nonce = state_cookie.rsplit(".", 1)
            from driverdna.coach.keystore import decrypt_api_key
            expected_state = decrypt_api_key(ct, nonce, session_secret=session_secret)
        except Exception:
            return _google_error_redirect("invalid state cookie — try again")

        if not secrets.compare_digest(state, expected_state):
            return _google_error_redirect("state mismatch — possible CSRF")

        try:
            url_obj = request.url_for("google_callback")
            if _is_https(request):
                url_obj = url_obj.replace(scheme="https")

            data = urllib.parse.urlencode({
                "client_id": google_client_id,
                "client_secret": google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": str(url_obj),
            }).encode("utf-8")

            req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
            try:
                with urllib.request.urlopen(req) as f:
                    token_res = json.loads(f.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                return _google_error_redirect(f"token exchange failed: {body}")

            id_token = token_res.get("id_token")
            if not id_token:
                return _google_error_redirect("no id_token in response")

            verify_req = urllib.request.Request(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}")
            try:
                with urllib.request.urlopen(verify_req) as f:
                    claims = json.loads(f.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                return _google_error_redirect(f"token verification failed: {body}")

            if claims.get("aud") != google_client_id:
                return _google_error_redirect("token audience mismatch")

            email = claims.get("email")
            if not email:
                return _google_error_redirect("no email in token")
            email = email.strip().lower()

            from datetime import datetime
            session_epoch = datetime.utcnow().isoformat()

            with open_db(request) as db:
                row = db.conn.execute("SELECT user_pk FROM users WHERE email=?", (email,)).fetchone()
                if row:
                    user_pk = row["user_pk"]
                    with db.conn:
                        db.conn.execute(
                            "UPDATE users SET session_epoch=? WHERE user_pk=?",
                            (session_epoch, user_pk),
                        )
                else:
                    now = session_epoch
                    with db.conn:
                        user_pk = db.conn.execute(
                            "INSERT INTO users (email, password_hash, session_epoch, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?) RETURNING user_pk",
                            (email, "", now, now, now),
                        ).fetchone()["user_pk"]

            ttl = load_config(config_path).auth.session_ttl_hours * 3600

            response = Response(
                content="<!doctype html><html><head><meta charset='utf-8'>"
                "<meta http-equiv='refresh' content='0;url=/'>"
                "</head><body><script>window.location.replace('/');</script>"
                "</body></html>",
                media_type="text/html",
            )
            response.set_cookie(
                auth.SESSION_COOKIE,
                auth.issue_session(user_pk, session_epoch, session_secret, ttl_seconds=ttl),
                max_age=ttl,
                httponly=True,
                samesite="lax",
                secure=_is_https(request),
                path="/",
            )
            response.delete_cookie(
                "_google_oauth_state", path="/api/auth/google/callback",
            )
            return response

        except HTTPException:
            raise
        except Exception as exc:
            return _google_error_redirect(str(exc))

    # --- Garage61 OAuth (PKCE, public client — no client_secret) -----------

    def _garage61_error_redirect(message: str) -> Response:
        import urllib.parse
        safe = urllib.parse.quote(message[:200], safe="")
        return RedirectResponse(f"/?auth_error={safe}", status_code=302)

    @app.get("/api/auth/garage61/login")
    def garage61_login(request: Request) -> Response:
        if not garage61_client_id:
            raise HTTPException(400, "Garage61 OAuth not configured")
        if not session_secret:
            raise HTTPException(400, "session secret required for Garage61 OAuth")

        import hashlib
        import urllib.parse

        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("ascii")).digest()
            )
            .decode("ascii")
            .rstrip("=")
        )

        url_obj = request.url_for("garage61_callback")
        if _is_https(request):
            url_obj = url_obj.replace(scheme="https")

        state = secrets.token_urlsafe(32)
        # Store verifier+state in a short-lived signed cookie so the
        # callback can retrieve them without server-side session state.
        import json as _json
        pkce_payload = _json.dumps({"v": code_verifier, "s": state})
        from driverdna.coach.keystore import encrypt_api_key
        ct, nonce = encrypt_api_key(pkce_payload, session_secret=session_secret)
        pkce_cookie = f"{ct}.{nonce}"

        url = "https://garage61.net/app/account/oauth?" + urllib.parse.urlencode({
            "client_id": garage61_client_id,
            "redirect_uri": str(url_obj),
            "response_type": "code",
            "scope": "openid profile driving_data",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        })
        response = RedirectResponse(url)
        response.set_cookie(
            "_g61_pkce", pkce_cookie,
            max_age=600, httponly=True, samesite="lax",
            secure=_is_https(request), path="/api/auth/garage61/callback",
        )
        return response

    @app.get("/api/auth/garage61/callback")
    def garage61_callback(code: str, state: str, request: Request) -> Response:
        if not garage61_client_id or not session_secret:
            raise HTTPException(400, "Garage61 OAuth not configured")

        import urllib.request
        import urllib.parse

        # Recover PKCE verifier from the cookie
        pkce_cookie = request.cookies.get("_g61_pkce")
        if not pkce_cookie:
            return _garage61_error_redirect("missing PKCE cookie — try again")
        try:
            ct, nonce = pkce_cookie.rsplit(".", 1)
            from driverdna.coach.keystore import decrypt_api_key
            import json as _json
            pkce_data = _json.loads(decrypt_api_key(ct, nonce, session_secret=session_secret))
            code_verifier = pkce_data["v"]
            expected_state = pkce_data["s"]
        except Exception:
            return _garage61_error_redirect("invalid PKCE cookie — try again")

        if not secrets.compare_digest(state, expected_state):
            return _garage61_error_redirect("state mismatch — possible CSRF")

        try:
            url_obj = request.url_for("garage61_callback")
            if _is_https(request):
                url_obj = url_obj.replace(scheme="https")

            # Token exchange — PKCE + client_secret when available
            token_params = {
                "client_id": garage61_client_id,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": str(url_obj),
                "code_verifier": code_verifier,
            }
            if garage61_client_secret:
                token_params["client_secret"] = garage61_client_secret
            data = urllib.parse.urlencode(token_params).encode("utf-8")

            req = urllib.request.Request(
                "https://garage61.net/api/oauth/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                with urllib.request.urlopen(req) as f:
                    token_res = json.loads(f.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                return _garage61_error_redirect(f"token exchange failed: {body}")

            access_token = token_res.get("access_token")
            if not access_token:
                return _garage61_error_redirect("no access_token in response")
            refresh_token = token_res.get("refresh_token")
            scopes = token_res.get("scope", "")

            # Fetch Garage61 user info for display/identity
            g61_user_id = None
            try:
                me_req = urllib.request.Request(
                    "https://garage61.net/api/v1/me",
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                )
                with urllib.request.urlopen(me_req) as f:
                    me_data = json.loads(f.read().decode("utf-8"))
                g61_user_id = str(me_data.get("id", ""))
            except Exception:
                pass  # non-fatal — we have the token regardless

            # Encrypt and store the tokens
            from driverdna.coach.keystore import encrypt_api_key
            access_ct, access_nonce = encrypt_api_key(access_token, session_secret=session_secret)
            refresh_ct, refresh_nonce = (None, None)
            if refresh_token:
                refresh_ct, refresh_nonce = encrypt_api_key(refresh_token, session_secret=session_secret)

            user_pk = getattr(request.state, "user_pk", None)
            now = datetime.now(UTC).isoformat()

            # If the user is already authenticated, store against their user_pk.
            # If not (first visit via Garage61), create/find a user by the G61 id.
            if user_pk is None and session_secret is not None:
                # Not logged in — auto-create or find user by garage61 id
                if not g61_user_id:
                    return _garage61_error_redirect("could not identify Garage61 account")
                with open_db(request) as db:
                    row = db.conn.execute(
                        "SELECT owner_user_pk FROM garage61_tokens WHERE garage61_user_id=?",
                        (g61_user_id,),
                    ).fetchone()
                    if row:
                        user_pk = row["owner_user_pk"]
                    else:
                        session_epoch = now
                        with db.conn:
                            user_pk = db.conn.execute(
                                "INSERT INTO users (email, password_hash, session_epoch, created_at, updated_at) "
                                "VALUES (?, ?, ?, ?, ?) RETURNING user_pk",
                                (f"garage61:{g61_user_id}", "", now, now, now),
                            ).fetchone()["user_pk"]

            if user_pk is None:
                return _garage61_error_redirect("not authenticated — sign in first")

            with open_db(request) as db:
                with db.conn:
                    db.conn.execute(
                        "INSERT INTO garage61_tokens "
                        "(owner_user_pk, garage61_user_id, access_ciphertext, access_nonce, "
                        " refresh_ciphertext, refresh_nonce, scopes, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (owner_user_pk) DO UPDATE SET "
                        "garage61_user_id=excluded.garage61_user_id, "
                        "access_ciphertext=excluded.access_ciphertext, "
                        "access_nonce=excluded.access_nonce, "
                        "refresh_ciphertext=excluded.refresh_ciphertext, "
                        "refresh_nonce=excluded.refresh_nonce, "
                        "scopes=excluded.scopes, "
                        "created_at=excluded.created_at",
                        (user_pk, g61_user_id, access_ct, access_nonce,
                         refresh_ct, refresh_nonce, scopes, now),
                    )

            # Issue a session cookie if the caller doesn't already have one
            ttl = load_config(config_path).auth.session_ttl_hours * 3600
            session_epoch = now

            with open_db(request) as db:
                with db.conn:
                    db.conn.execute(
                        "UPDATE users SET session_epoch=? WHERE user_pk=?",
                        (session_epoch, user_pk),
                    )

            response = Response(
                content="<!doctype html><html><head><meta charset='utf-8'>"
                "<meta http-equiv='refresh' content='0;url=/'>"
                "</head><body><script>window.location.replace('/');</script>"
                "</body></html>",
                media_type="text/html",
            )
            response.set_cookie(
                auth.SESSION_COOKIE,
                auth.issue_session(user_pk, session_epoch, session_secret, ttl_seconds=ttl),
                max_age=ttl,
                httponly=True, samesite="lax",
                secure=_is_https(request), path="/",
            )
            response.delete_cookie("_g61_pkce", path="/api/auth/garage61/callback")
            return response

        except HTTPException:
            raise
        except Exception as exc:
            return _garage61_error_redirect(str(exc))

    @app.post("/api/auth/logout")
    def logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return {"authenticated": False}

    @app.get("/api/auth/status")
    def auth_status(request: Request) -> dict[str, bool]:
        """What the SPA asks before drawing anything, so it can show the login
        gate instead of ten failed panels. Deliberately says only whether a
        sign-in is required, whether this caller has one, and whether the
        Google button has anything to call — never the client secret."""
        is_auth = authenticated(request)
        garage61_linked = False
        if is_auth:
            try:
                with open_db(request) as db:
                    row = db.conn.execute("SELECT 1 FROM garage61_tokens WHERE owner_user_pk=?", (db.user_pk,)).fetchone()
                    garage61_linked = row is not None
            except Exception:
                pass

        return {
            "required": session_secret is not None,
            "authenticated": is_auth,
            "google_enabled": google_client_id is not None,
            "garage61_enabled": garage61_client_id is not None,
            "garage61_linked": garage61_linked,
        }

    def make_chat_provider(*, api_key: str | None = None) -> ChatProvider:
        """`chat_provider_factory` defaults to `chat.session.make_chat_provider`
        (Claude or Gemini per `config.coach.provider`); tests inject a
        mocked provider here, same pattern as the CLI's `chat` command.
        `api_key`, given (SPEC.md A37, BYOK), is the caller's own decrypted
        key, resolved by the caller from `user_api_keys` — never read from
        a request body here."""
        if chat_provider_factory is not None:
            return chat_provider_factory()
        from driverdna.chat.session import make_chat_provider as _make_chat_provider

        cfg = load_config(config_path)
        return _make_chat_provider(cfg, api_key=api_key)

    def _resolve_byok_key(db: Database, provider_name: str) -> str | None:
        """This account's own decrypted key for `provider_name` (SPEC.md
        A37), or None to fall through to the server-side env key/error —
        the exact meaning `api_key=None` already carries in every provider
        class. None (not an exception) whenever BYOK genuinely isn't
        available here: no session_secret configured, no key set, or a
        stored row that fails to decrypt (a rotated secret) — the driver
        can always re-set their key from #/config; this must never hard-fail
        a chat session that the server's own env key could still serve."""
        if session_secret is None:
            return None
        row = db.get_user_api_key(provider=provider_name)
        if row is None:
            return None
        try:
            return keystore.decrypt_api_key(
                row["ciphertext"], row["nonce"], session_secret=session_secret
            )
        except ValueError:
            logger.warning(
                "stored BYOK key for provider=%s could not be decrypted "
                "(rotated secret?) — falling back to the server key",
                provider_name,
            )
            return None

    def open_db(request: Request | None = None, *, check_same_thread: bool = True) -> Database:
        if _is_pg and _pool is None:
            raise HTTPException(503, detail="database unavailable — check server logs")
        # A hosted store has no file to stat and creates its schema on
        # connect, so "not there yet" is reported by `missing_reason` only
        # for the SQLite case; an empty hosted store surfaces as the normal
        # no-cohorts empty state instead.
        reason = missing_reason(db_path)
        if reason:
            raise HTTPException(404, detail=f"{reason} — run `driverdna import` first")
        user_pk = request.state.user_pk if hasattr(getattr(request, "state", None), "user_pk") else 1
        if _pool is not None:
            db = Database.from_pool(_pool, _pg_blobs, user_pk=user_pk)
        else:
            db = Database.open(db_path, check_same_thread=check_same_thread, user_pk=user_pk)

        if request and hasattr(request.state, "session_epoch"):
            # Ensure the session epoch hasn't been rotated
            expected = db.conn.execute("SELECT session_epoch FROM users WHERE user_pk=?", (user_pk,)).fetchone()
            if not expected or request.state.session_epoch != expected["session_epoch"]:
                db.close()
                raise HTTPException(401, detail="session invalid or expired")

        return db

    def resolve(db: Database, slug: str) -> dict[str, str]:
        for cohort in list_cohorts(db):
            if cohort_slug(cohort["car"], cohort["track"]) == slug:
                return cohort
        raise HTTPException(404, detail=f"unknown cohort: {slug}")

    def normalized(payload: dict) -> Response:
        return Response(content=to_normalized_json(payload), media_type="application/json")

    def _json_default(obj: Any) -> Any:
        if isinstance(obj, set):
            return sorted(obj)
        if isinstance(obj, float):
            return round(obj, 6)
        raise TypeError(f"not JSON serializable: {type(obj)}")

    def _drain_sse(
        q: "queue.Queue[dict[str, Any]]",
        worker: threading.Thread,
        heartbeat: float,
    ):
        """Yield queued events as SSE frames, with a heartbeat while silent.

        The worker announces a phase and then computes — `driver_model` and
        `census` each run for minutes on a real cohort count with nothing to
        report in between. A bare blocking `q.get()` emits nothing during that
        window, and a reverse proxy cannot tell a working stream from a dead
        one: Cloudflare's ~100 s idle timeout closed `/api/driver` mid-compute
        in production (BUG-026). An SSE *comment* (`: …`) keeps the connection
        warm and is ignored by EventSource, so no client code has to know.
        """
        while True:
            try:
                event = q.get(timeout=heartbeat)
            except queue.Empty:
                if not worker.is_alive():
                    # Died without posting a terminal event — say so rather
                    # than heartbeat forever against a thread that is gone.
                    yield ('data: {"type": "error", "detail": '
                           '"stream worker stopped without completing"}\n\n')
                    return
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(event, sort_keys=True, default=_json_default)}\n\n"
            if event["type"] in ("complete", "error"):
                return

    # --- reads --------------------------------------------------------------

    @app.get("/api/driver/summary")
    def driver_summary(request: Request) -> dict[str, Any]:
        """Lightweight summary for instant first paint — no engine computation,
        just DB counts.  The Driver page renders this immediately while the
        full ``/api/driver`` SSE stream is still computing."""
        with open_db(request) as db:
            cohorts_list = list_cohorts(db)
            lap_counts = {
                (r["car"], r["track"]): {"self": r["n_self"], "reference": r["n_ref"]}
                for r in db.conn.execute(
                    """SELECT car, track,
                              SUM(CASE WHEN role='self' THEN 1 ELSE 0 END) n_self,
                              SUM(CASE WHEN role='reference' THEN 1 ELSE 0 END) n_ref
                       FROM laps WHERE owner_user_pk=?
                       GROUP BY car, track""",
                    (db.user_pk,),
                )
            }
            driver_name = cohorts_list[0]["driver"] if cohorts_list else None
            sync_rows = {}
            if driver_name:
                for r in db.sync_states(driver_name):
                    sync_rows[(r["car"], r["track"])] = r.get("last_synced_at")

            cohort_summaries = []
            for c in cohorts_list:
                key = (c["car"], c["track"])
                counts = lap_counts.get(key, {"self": 0, "reference": 0})
                cohort_summaries.append({
                    "car": c["car"], "track": c["track"],
                    "n_laps": counts["self"],
                    "n_reference_laps": counts["reference"],
                    "last_synced_at": sync_rows.get(key),
                })
            return {
                "n_cohorts": len(cohorts_list),
                "n_self_laps": sum(s["n_laps"] for s in cohort_summaries),
                "n_reference_laps": sum(s["n_reference_laps"] for s in cohort_summaries),
                "cohorts": cohort_summaries,
                "last_synced_at": max(
                    (v for v in sync_rows.values() if v), default=None
                ),
            }

    @app.get("/api/driver")
    def driver(request: Request) -> StreamingResponse:
        """Streams the driver payload via SSE so the UI can show per-cohort
        progress instead of hanging on 'loading...' for 30+ seconds."""
        open_db(request).close()
        user_pk = request.state.user_pk if hasattr(getattr(request, "state", None), "user_pk") else 1
        config = load_config(config_path)

        def _driver_events():
            q: queue.Queue[dict[str, Any]] = queue.Queue()
            
            with Database.open(db_path, user_pk=user_pk) as db:
                from driverdna.report.payload import PAYLOAD_VERSION
                cached_json = db.get_driver_payload_cache(PAYLOAD_VERSION)
                if cached_json is not None:
                    import json
                    payload = json.loads(cached_json)
                    yield f"data: {json.dumps({'type': 'complete', 'payload': payload})}\n\n"
                    return

            def run() -> None:
                try:
                    with Database.open(db_path, user_pk=user_pk) as db:
                        def on_progress(evt: dict[str, Any]) -> None:
                            q.put(evt)
                        payload = build_driver_payload(db, config, on_progress=on_progress)
                        from driverdna.report.payload import PAYLOAD_VERSION
                        import json
                        import datetime
                        db.set_driver_payload_cache(
                            PAYLOAD_VERSION,
                            json.dumps(payload),
                            datetime.datetime.now(datetime.UTC).isoformat()
                        )
                        q.put({"type": "complete", "payload": payload})
                except Exception as exc:
                    q.put({"type": "error", "detail": str(exc)})

            t = threading.Thread(target=run, daemon=True)
            t.start()
            yield from _drain_sse(q, t, config.api.sse_heartbeat_seconds)
            t.join()

        return StreamingResponse(_driver_events(), media_type="text/event-stream")

    @app.get("/api/driver/score-history")
    def driver_score_history(request: Request) -> StreamingResponse:
        """Streams score_history via SSE so the Model page shows progress."""
        from driverdna.model.history import CAVEATS, SERIES_VERSION, score_history
        from driverdna.model.scoring import SCORING_MODEL_VERSION

        open_db(request).close()
        user_pk = request.state.user_pk if hasattr(getattr(request, "state", None), "user_pk") else 1
        config = load_config(config_path)

        def _history_events():
            q: queue.Queue[dict[str, Any]] = queue.Queue()

            def run() -> None:
                try:
                    with Database.open(db_path, user_pk=user_pk) as db:
                        cohorts_list = list_cohorts(db)
                        driver_name = cohorts_list[0]["driver"] if cohorts_list else None
                        if driver_name is None:
                            q.put({"type": "complete", "payload": {
                                "series_version": SERIES_VERSION,
                                "scoring_model_version": SCORING_MODEL_VERSION,
                                "x_axis": {"kind": "unavailable", "labels": [], "bucket_lap_counts": []},
                                "series": {},
                                "caveats": list(CAVEATS),
                            }})
                            return
                        q.put({"type": "progress", "message": "Computing score history…"})
                        result = score_history(db, driver=driver_name, config=config)
                        q.put({"type": "complete", "payload": result})
                except Exception as exc:
                    q.put({"type": "error", "detail": str(exc)})

            t = threading.Thread(target=run, daemon=True)
            t.start()
            yield from _drain_sse(q, t, config.api.sse_heartbeat_seconds)
            t.join()

        return StreamingResponse(_history_events(), media_type="text/event-stream")

    @app.get("/api/cohorts")
    def cohorts(request: Request) -> list[dict[str, Any]]:
        with open_db(request) as db:
            cohorts_list = list_cohorts(db)
            lap_counts = {
                (r["car"], r["track"]): {"self": r["n_self"], "reference": r["n_ref"]}
                for r in db.conn.execute(
                    """SELECT car, track,
                              SUM(CASE WHEN role='self' THEN 1 ELSE 0 END) n_self,
                              SUM(CASE WHEN role='reference' THEN 1 ELSE 0 END) n_ref
                       FROM laps WHERE owner_user_pk=?
                       GROUP BY car, track""",
                    (db.user_pk,),
                )
            }
            driver_name = cohorts_list[0]["driver"] if cohorts_list else None
            sync_rows: dict[tuple[str, str], str | None] = {}
            if driver_name:
                for r in db.sync_states(driver_name):
                    sync_rows[(r["car"], r["track"])] = r.get("last_synced_at")
            return [
                c | {
                    "slug": cohort_slug(c["car"], c["track"]),
                    "n_laps": lap_counts.get((c["car"], c["track"]), {"self": 0})["self"],
                    "n_reference_laps": lap_counts.get((c["car"], c["track"]), {"reference": 0}).get("reference", 0),
                    "last_synced_at": sync_rows.get((c["car"], c["track"])),
                }
                for c in cohorts_list
            ]

    @app.get("/api/cohorts/{slug}/payload")
    def cohort_payload(slug: str, request: Request) -> Response:
        with open_db(request) as db:
            cohort = resolve(db, slug)
            return normalized(
                build_cohort_payload(db, driver=cohort["driver"], car=cohort["car"], track=cohort["track"], config=load_config(config_path))
            )

    @app.get("/api/cohorts/{slug}/corners")
    def corners(slug: str, request: Request) -> list[dict[str, Any]]:
        with open_db(request) as db:
            cohort = resolve(db, slug)
            loaded = db.load_corner_map(car=cohort["car"], track=cohort["track"])
            if loaded is None:
                return []
            map_pk, corner_map = loaded
            classes = db.corner_classes(car=cohort["car"], track=cohort["track"])
            windows = db.load_corner_windows(map_pk)
            return [
                {
                    "corner_id": c.corner_id,
                    "lat": c.lat,
                    "lon": c.lon,
                    "lap_dist": c.lap_dist,
                    "class": classes.get(c.corner_id),
                    "windows": windows.get(c.corner_id),
                }
                for c in corner_map.corners
            ]

    @app.get("/api/cohorts/{slug}/corners/{corner_id}/reference-phases")
    def corner_reference_phases(slug: str, corner_id: str, request: Request) -> dict[str, Any]:
        """Reference phase-time distributions for one corner (R2, SPEC.md
        A39), beside the self baselines the cohort payload already carries
        -- the same `db.phase_history(role='reference')` +
        `reference_envelope` vs_reference_findings is built from, exposed
        directly so the corner drill can show it without recomputing
        anything. A lap R3 curation has excluded is already filtered out by
        `phase_history` itself, so this always reflects the active pool."""
        with open_db(request) as db:
            cohort = resolve(db, slug)
            result: dict[str, Any] = {}
            for phase in PHASES:
                history = db.phase_history(
                    car=cohort["car"], track=cohort["track"], corner_id=corner_id,
                    phase=phase, role="reference",
                )
                envelope = reference_envelope([h["time_s"] for h in history])
                result[phase] = asdict(envelope) if envelope else None
            return result

    @app.get("/api/cohorts/{slug}/track-trace")
    def track_trace(slug: str, request: Request) -> dict[str, Any]:
        """Lat/Lon of the newest retained self lap, downsampled for transport
        — the outline the cohort view draws (UI-SPEC view 2)."""
        with open_db(request) as db:
            cohort = resolve(db, slug)
            
            # Fast path: use cached outline if M009 migration populated it.
            # Survives blob eviction naturally.
            row = db.conn.execute(
                "SELECT track_outline_json FROM corner_maps WHERE car=? AND track=? AND owner_user_pk=?",
                (cohort["car"], cohort["track"], db.user_pk)
            ).fetchone()
            if row and row["track_outline_json"]:
                import json
                return json.loads(row["track_outline_json"])

            # Raw blobs live on local disk, so "which lap still has one" is a
            # filesystem question, not a join. Walk newest-first and take the
            # first lap whose trace is actually readable here.
            rows = db.conn.execute(
                """SELECT l.lap_pk, l.lap_id FROM laps l
                   WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=? AND l.owner_user_pk=?
                   ORDER BY l.lap_pk DESC""",
                (cohort["driver"], cohort["car"], cohort["track"], db.user_pk),
            ).fetchall()
            arrays = None
            chosen = None
            for row in rows:
                arrays = db.load_lap_arrays(int(row["lap_pk"]))
                if arrays is not None:
                    chosen = row
                    break
            if arrays is None:
                raise HTTPException(
                    404, detail="no raw lap within retention for this cohort"
                )
            rows = [chosen]
            step = max(1, len(arrays["lat"]) // TRACE_POINTS)
            return {
                "lap_id": rows[0]["lap_id"],
                "lat": [round(float(v), 6) for v in arrays["lat"][::step]],
                "lon": [round(float(v), 6) for v in arrays["lon"][::step]],
                "lap_dist": [round(float(v), 5) for v in arrays["lap_dist"][::step]],
            }

    @app.get("/api/laps")
    def laps(cohort: str, request: Request) -> list[dict[str, Any]]:
        with open_db(request) as db:
            c = resolve(db, cohort)
            rows = db.conn.execute(
                """SELECT lap_pk, lap_id, driver, role, duration_s, session_key,
                          quality_flags
                   FROM laps WHERE car=? AND track=? AND owner_user_pk=? ORDER BY lap_pk""",
                (c["car"], c["track"], db.user_pk),
            ).fetchall()
            incident_counts = db.incident_counts_by_lap([r["lap_pk"] for r in rows])
            return [
                {
                    "lap_pk": r["lap_pk"],
                    "lap_id": r["lap_id"],
                    "driver": r["driver"],
                    "role": r["role"],
                    "duration_s": r["duration_s"],
                    "session_key": r["session_key"],
                    "quality_flags": json.loads(r["quality_flags"]),
                    "incidents": incident_counts.get(r["lap_pk"], 0),
                    # A filesystem check, not a row check: a lap imported on
                    # another machine has every summary row here and no blob,
                    # which reads the same as "evicted by retention".
                    "raw_retained": db.has_raw(int(r["lap_pk"])),
                }
                for r in rows
            ]

    def _parse_lap_date(value: str) -> str:
        """Same shape `driverdna import --date` accepts (YYYY-MM-DD or a
        full ISO8601 timestamp); rejected loudly, never silently accepted —
        M6 trend sorts laps on this string. Pure input-shape validation
        (same class as the annotate endpoint's status check), not business
        logic — the CLI's own `_validate_lap_date` can't be reused directly
        since it reports failure via typer.Exit, not an HTTP error."""
        from datetime import date as _date, datetime as _datetime

        try:
            _date.fromisoformat(value)
            return value
        except ValueError:
            pass
        try:
            _datetime.fromisoformat(value)
            return value
        except ValueError:
            raise HTTPException(
                422, detail=f"date {value!r} is not valid (expected YYYY-MM-DD "
                "or a full ISO8601 timestamp)",
            ) from None

    @app.post("/api/laps/upload")
    async def upload_laps(request: Request,
        files: list[UploadFile] = File(...),
        car: str | None = Form(None),
        track: str | None = Form(None),
        role: str = Form("self"),
        date: str | None = Form(None),
        session: str | None = Form(None),
        driver: str | None = Form(None),
    ) -> StreamingResponse:
        """Wraps `import_lap_file` — the exact function `driverdna import`
        calls per file (UI-SPEC decision 3: no business logic here). Unlike
        every read endpoint, this one does NOT require the DB to already
        exist: `Database.open` creates + migrates a fresh file, the same as
        pointing the CLI at a new --db path, so this is a genuine cold-start
        path — a driver can go from nothing to a populated cockpit without
        ever touching the CLI.

        `car`/`track` are independently optional, and either one on its own is
        a working manual override: a field that is given applies to every file,
        a field that is blank is auto-detected per file from either newer
        Garage61 export filename shape (`ingest/parser.py`'s
        `parse_garage61_filename`) — mirrors `driverdna import`'s own per-file
        auto-detect. So a future filename rename never strands the driver:
        filling just the box the filename no longer states is enough. A file
        still missing a field after that (old filename shape, nothing given) is
        rejected before anything is imported, listed by name with the field it
        is missing — never silently skipped.

        Returns SSE: one ``progress`` event per file processed, then a
        terminal ``complete`` event carrying the same ``{results, evicted}``
        shape the old JSON response had."""
        if role not in ("self", "reference"):
            raise HTTPException(422, detail="role must be self or reference")
        if date is not None:
            date = _parse_lap_date(date)

        # Hardening (DEPLOY-SPEC H1.3). Both checks run over the whole batch
        # before the database is opened, listing every offending file — the
        # same "never partially import" promise the car/track check below
        # already makes. Refusing half a batch is worse than refusing it all.
        api_limits = load_config(config_path).api
        refused = [
            u.filename or "(unnamed file)"
            for u in files
            if not (u.filename or "").lower().endswith(".csv")
        ]
        if refused:
            raise HTTPException(
                422,
                detail="only Garage61 CSV exports are accepted — refused: "
                + ", ".join(refused),
            )
        cap = api_limits.max_upload_mb * 1024 * 1024
        # `UploadFile.size` is the count Starlette's multipart parser actually
        # read, not a Content-Length the client asserted. Honest limitation:
        # the body has necessarily been received by the time it can be
        # measured — Starlette spools it to disk, so what this bounds is what
        # gets parsed and imported, not what crosses the wire.
        oversized = [
            f"{u.filename or '(unnamed file)'} ({(u.size or 0) / 1048576:.1f}MB)"
            for u in files
            if (u.size or 0) > cap
        ]
        if oversized:
            raise HTTPException(
                413,
                detail=f"over the {api_limits.max_upload_mb}MB per-file limit: "
                + ", ".join(oversized),
            )

        from driverdna.ingest.parser import parse_garage61_filename
        from driverdna.pipeline import import_lap_file

        car = (car or "").strip() or None
        track = (track or "").strip() or None
        # Same default the CLI's own --driver flag has. Reference laps are
        # the case this matters for: without it, every uploaded reference
        # lap would read as "owner" too, indistinguishable from the
        # driver's own laps (R2, SPEC.md A39) — self uploads keep the same
        # "owner" default they always had.
        driver = (driver or "").strip() or "owner"
        # (upload, car, track, auto_detected)
        resolved: list[tuple[UploadFile, str, str, bool]] = []
        unresolved: list[str] = []
        for upload in files:
            file_car, file_track = car, track
            detected = (
                parse_garage61_filename(upload.filename or "")
                if file_car is None or file_track is None
                else None
            )
            if detected:
                file_car = file_car or detected["car"]
                file_track = file_track or detected["track"]
            if file_car is None or file_track is None:
                missing = " and ".join(
                    n for n, v in (("car", file_car), ("track", file_track)) if v is None
                )
                unresolved.append(
                    f"{upload.filename or '(unnamed file)'} (missing {missing})"
                )
                continue
            resolved.append((upload, file_car, file_track, detected is not None))
        if unresolved:
            raise HTTPException(
                422,
                detail="could not resolve car/track for: "
                f"{', '.join(unresolved)}. Auto-detect reads a Garage61 export "
                "filename shaped 'Garage 61 - <driver> - <car> - <track> - "
                "<laptime> - <id>.csv' or 'Garage_61__<driver>__<car>__<track>__"
                "<laptime>__<id>.csv'; otherwise fill in the missing field, "
                "which is then applied to every file.",
            )

        # A34: a reference lap can never be the first lap in its cohort — the
        # first lap builds the corner map. Checked before the store is opened
        # when there is no SQLite store at all (a cold start has no map by
        # definition), so a refused upload never leaves a database behind. A
        # hosted store has no file to stat and creates its schema on connect,
        # so it falls through to the per-cohort check below — same verdict.
        if role != "self" and missing_reason(db_path):
            raise HTTPException(422, detail=_REFERENCE_FIRST_LAP_DETAIL)

        # Read all file bytes before entering the generator so UploadFile
        # objects are consumed while the request context is still active.
        file_data: list[tuple[str | None, bytes, str, str, bool]] = []
        for upload, file_car, file_track, auto_detected in resolved:
            raw = await upload.read()
            file_data.append((upload.filename, raw, file_car, file_track, auto_detected))

        # Reference-orphan check (needs DB open briefly for the corner-map
        # query). Runs before the stream starts so it can raise HTTPException.
        user_pk = request.state.user_pk if hasattr(getattr(request, "state", None), "user_pk") else 1
        if role != "self":
            with Database.open(db_path, user_pk=user_pk) as db:
                orphans = sorted(
                    {
                        f"{c} @ {t}"
                        for _fn, _raw, c, t, _d in file_data
                        if db.load_corner_map(car=c, track=t) is None
                    }
                )
                if orphans:
                    raise HTTPException(
                        422,
                        detail=f"{_REFERENCE_FIRST_LAP_DETAIL} No laps of your "
                        f"own yet in: {', '.join(orphans)}. Nothing was imported.",
                    )

        config = load_config(config_path)
        total = len(file_data)

        def _upload_events():
            results: list[dict[str, Any]] = []
            with tempfile.TemporaryDirectory() as tmp:
                with Database.open(db_path, user_pk=user_pk) as db:
                    for i, (filename, raw, file_car, file_track, auto_detected) in enumerate(file_data):
                        dest = Path(tmp) / (filename or "upload.csv")
                        dest.write_bytes(raw)
                        result = import_lap_file(
                            db, dest, config=config, driver=driver, car=file_car,
                            track=file_track, role=role, session_key=session, lap_date=date,
                        )
                        matched = sum(1 for a in result.assigned if a)
                        entry = {
                            "filename": filename,
                            "car": file_car,
                            "track": file_track,
                            "auto_detected": auto_detected,
                            "status": result.status,
                            "lap_pk": result.lap_pk,
                            "corners_matched": matched,
                            "corners_total": len(result.assigned),
                            "admitted": result.admitted,
                            "class_changes": [
                                {"corner_id": c, "old": o, "new": n}
                                for c, o, n in result.class_changes
                            ],
                        }
                        results.append(entry)
                        yield f"data: {json.dumps({'type': 'progress', 'index': i, 'total': total, 'result': entry}, sort_keys=True)}\n\n"
                    evicted = db.enforce_retention(config.retention.raw_laps_per_cohort)
            yield f"data: {json.dumps({'type': 'complete', 'results': results, 'evicted': evicted}, sort_keys=True)}\n\n"

        return StreamingResponse(_upload_events(), media_type="text/event-stream")

    @app.get("/api/metrics/{corner_id}/{metric}/distribution")
    def metric_distribution(corner_id: str, metric: str, cohort: str, request: Request) -> dict[str, Any]:
        with open_db(request) as db:
            c = resolve(db, cohort)
            result = execute_tool(
                db=db, store=ConfigStore(config_path, db), cohort=c,
                bundle={"report": {"findings": []}}, staged=[],
                name="metric_distribution",
                args={"corner_id": corner_id, "metric": metric},
            )
            if "error" in result:
                raise HTTPException(404, detail=result["error"])
            return result

    @app.get("/api/config")
    def config_view() -> dict[str, dict[str, Any]]:
        config = load_config(config_path)
        return {
            key: {"value": value, "description": describe_key(key)}
            for key, value in sorted(config_snapshot(config).items())
        }

    @app.get("/api/explain")
    def explain_view() -> dict[str, str]:
        """The methodology text behind the v3 disclosure pattern (SPEC.md
        A35) — a static dict, no DB, no computation; same shape as
        /api/config's pass-through of describe_key."""
        return dict(sorted(METHODOLOGY.items()))

    @app.get("/api/config/history")
    def config_history(request: Request) -> list[dict[str, Any]]:
        """This user's config history only (BUG-032a, SPEC.md A53).

        `config_history` has carried `owner_user_pk` since migration 009,
        so the audit trail *looked* per-user while this read returned
        every user's rows — worse than plainly global, because it
        contradicted the guarantee the write side spelled out. Now
        matches: the row this caller wrote is the row this caller reads.
        """
        with open_db(request) as db:
            return [
                dict(r)
                for r in db.conn.execute(
                    "SELECT * FROM config_history WHERE owner_user_pk=? "
                    "ORDER BY change_pk",
                    (db.user_pk,),
                )
            ]

    # --- per-user AI keys (SPEC.md A37, BYOK) --------------------------------
    #
    # A user's own provider key, encrypted at rest (coach/keystore.py).
    # Write-only in one direction: PUT accepts the raw key over HTTPS, once;
    # GET returns only a fingerprint, never the key, matching the U6
    # precedent for GARAGE61_TOKEN ("secrets never transit the browser") —
    # narrowed here (SPEC.md A37) for exactly the case where the secret is
    # by definition supplied by the browser, but it is still NEVER echoed
    # back by a read endpoint. BYOK requires a configured
    # DRIVERDNA_SESSION_SECRET (the key-encryption key's source); the local,
    # no-auth `driverdna ui` path has none, and these endpoints say so
    # rather than falling back to an insecure default.

    _BYOK_PROVIDERS = ("claude", "gemini")

    def _require_byok_secret() -> str:
        if session_secret is None:
            raise HTTPException(
                400,
                detail="BYOK requires a configured DRIVERDNA_SESSION_SECRET "
                       "(the key-encryption key's source) — not available on "
                       "the local, no-auth driverdna ui path.",
            )
        return session_secret

    @app.put("/api/settings/ai-key")
    def set_api_key(body: ApiKeyBody, request: Request) -> dict[str, Any]:
        if body.provider not in _BYOK_PROVIDERS:
            raise HTTPException(422, detail=f"provider must be one of {_BYOK_PROVIDERS}")
        if not body.key.strip():
            raise HTTPException(422, detail="key must not be empty")
        secret = _require_byok_secret()
        ciphertext, nonce = keystore.encrypt_api_key(body.key.strip(), session_secret=secret)
        hint = keystore.fingerprint(body.key.strip())
        with open_db(request) as db:
            db.store_user_api_key(
                provider=body.provider, ciphertext=ciphertext, nonce=nonce,
                fingerprint=hint, created_at=datetime.now(UTC).isoformat(),
            )
        return {"provider": body.provider, "configured": True, "fingerprint": hint}

    @app.get("/api/settings/ai-key")
    def get_api_key_status(provider: str, request: Request) -> dict[str, Any]:
        if provider not in _BYOK_PROVIDERS:
            raise HTTPException(422, detail=f"provider must be one of {_BYOK_PROVIDERS}")
        with open_db(request) as db:
            row = db.get_user_api_key(provider=provider)
        if row is None:
            return {"provider": provider, "configured": False}
        return {
            "provider": provider, "configured": True,
            "fingerprint": row["fingerprint"], "set_at": row["created_at"],
        }

    @app.delete("/api/settings/ai-key")
    def delete_api_key(provider: str, request: Request) -> dict[str, Any]:
        if provider not in _BYOK_PROVIDERS:
            raise HTTPException(422, detail=f"provider must be one of {_BYOK_PROVIDERS}")
        with open_db(request) as db:
            if db.get_user_api_key(provider=provider) is None:
                raise HTTPException(404, detail=f"no key configured for {provider}")
            db.delete_user_api_key(provider=provider)
        return {"provider": provider, "configured": False}

    # --- writes (wrappers over the audited paths only) ----------------------

    @app.post("/api/findings/{finding_id}/annotate")
    def annotate(finding_id: str, body: AnnotateBody, request: Request) -> dict[str, Any]:
        if body.status not in ("acknowledged", "intentional"):
            raise HTTPException(422, detail="status must be acknowledged or intentional")
        with open_db(request) as db:
            config = load_config(config_path)
            cohorts = list_cohorts(db)
            known = {
                f["finding_id"]
                for c in cohorts
                for f in build_cohort_payload(db, driver=c["driver"], car=c["car"], track=c["track"], config=config)["findings"]
            }
            if finding_id not in known:
                raise HTTPException(404, detail=f"unknown finding: {finding_id}")
            db.annotate_finding(finding_id=finding_id, status=body.status, note=body.note)
            return {
                "annotated": finding_id,
                "annotation": db.annotations()[finding_id],
                "effect": "suppressed from future priority framing; the "
                          "measurement itself is kept",
            }

    @app.delete("/api/findings/{finding_id}/annotate")
    def clear_annotation(finding_id: str, request: Request) -> dict[str, Any]:
        """Undo an annotation — driver sovereignty cuts both ways. The finding
        returns to normal framing; no measurement was ever touched."""
        with open_db(request) as db:
            if finding_id not in db.annotations():
                raise HTTPException(404, detail=f"no annotation on {finding_id}")
            db.clear_annotation(finding_id)
            return {"cleared": finding_id}

    @app.post("/api/laps/{lap_pk}/exclude")
    def exclude_reference_lap(
        lap_pk: int, request: Request, body: ExcludeReferenceBody | None = None,
    ) -> dict[str, Any]:
        """R3 curation (SPEC.md A39): the audited-annotations pattern applied
        to a reference lap. `db.exclude_reference_lap` itself validates that
        `lap_pk` is this account's and is role='reference' — a self lap has
        no exclusion concept — so the same ValueError covers both "unknown
        lap" and "not a reference lap", both reported as 404 (unknown/
        inapplicable identifier), same family as the annotate endpoint's own
        unknown-finding 404."""
        with open_db(request) as db:
            try:
                db.exclude_reference_lap(
                    lap_pk=lap_pk, note=body.note if body else None,
                    created_at=datetime.now(UTC).isoformat(),
                )
            except ValueError as e:
                raise HTTPException(404, detail=str(e)) from None
            return {
                "excluded": lap_pk,
                "exclusion": db.reference_exclusions()[lap_pk],
                "effect": "removed from the reference envelope and every "
                          "vs-reference finding; the lap and its measurements "
                          "are kept",
            }

    @app.delete("/api/laps/{lap_pk}/exclude")
    def include_reference_lap(lap_pk: int, request: Request) -> dict[str, Any]:
        """Undo an exclusion — never touches the lap or its measurements.
        Rejects a lap_pk that isn't currently excluded rather than silently
        no-op-ing, same discipline as `clear_annotation`."""
        with open_db(request) as db:
            if lap_pk not in db.reference_exclusions():
                raise HTTPException(404, detail=f"lap {lap_pk} is not excluded")
            db.include_reference_lap(lap_pk)
            return {"included": lap_pk}

    @app.post("/api/config/propose")
    def config_propose(body: ProposeBody, request: Request) -> dict[str, Any]:
        with open_db(request) as db:
            try:
                return ConfigStore(config_path, db).propose(body.key, body.new_value)
            except (KeyError, ValueError) as e:
                raise HTTPException(422, detail=str(e)) from None

    @app.post("/api/config/apply")
    def config_apply(body: ApplyBody, request: Request) -> dict[str, Any]:
        with open_db(request) as db:
            store = ConfigStore(config_path, db)
            try:
                # Re-validate rather than trusting the client's proposal.
                proposal = store.propose(
                    body.proposal["key"], body.proposal["new_value"]
                )
                change_pk = store.apply(proposal, source="ui", note=body.note)
            except (KeyError, ValueError) as e:
                raise HTTPException(422, detail=str(e)) from None
            row = db.conn.execute(
                "SELECT * FROM config_history WHERE change_pk=?", (change_pk,)
            ).fetchone()
            return dict(row)

    @app.post("/api/config/revert/{change_pk}")
    def config_revert(change_pk: int, request: Request) -> dict[str, Any]:
        """Revert a recorded change (applies its old value back as a new,
        audited change) — the reversibility the philosophy requires."""
        with open_db(request) as db:
            try:
                new_pk = ConfigStore(config_path, db).revert(change_pk)
            except KeyError as e:
                raise HTTPException(404, detail=str(e)) from None
            row = db.conn.execute(
                "SELECT * FROM config_history WHERE change_pk=?", (new_pk,)
            ).fetchone()
            return dict(row)

    # --- cockpit actions (U6): sync + rebuild-map, wrappers only ------------
    # Both rewrite real state (new laps; refrozen geometry) through the exact
    # audited functions `driverdna sync` / `driverdna rebuild-map` call — no
    # endpoint here recomputes or aggregates a number the engine didn't.

    def _cohort_sync_dict(s: Any) -> dict[str, Any]:
        return {
            "car": s.car,
            "track": s.track,
            "laps_seen": s.laps_seen,
            "laps_new": s.laps_new,
            "laps_pitlane": s.laps_pitlane,
            "laps_skipped": [
                {"lap_id": lap_id, "reason": reason} for lap_id, reason in s.laps_skipped
            ],
            "results": [
                {
                    "lap_pk": r.lap_pk,
                    "status": r.status,
                    "admitted": r.admitted,
                    "class_changes": [
                        {"corner_id": c, "old": o, "new": n} for c, o, n in r.class_changes
                    ],
                }
                for r in s.results
            ],
        }

    def _resolve_garage61_token(request: Request) -> str | None:
        """Try the stored OAuth token for this user, then fall back to env."""
        if session_secret is not None:
            user_pk = getattr(request.state, "user_pk", None)
            if user_pk is not None:
                try:
                    with open_db(request) as db:
                        row = db.conn.execute(
                            "SELECT access_ciphertext, access_nonce FROM garage61_tokens "
                            "WHERE owner_user_pk=?", (user_pk,),
                        ).fetchone()
                    if row:
                        from driverdna.coach.keystore import decrypt_api_key
                        return decrypt_api_key(
                            row["access_ciphertext"], row["access_nonce"],
                            session_secret=session_secret,
                        )
                except Exception:
                    logger.warning("failed to decrypt stored Garage61 token, falling back to env")
        return None

    @app.get("/api/garage61/status")
    def garage61_token_status(request: Request) -> dict[str, Any]:
        """Whether the current user has a stored Garage61 OAuth token.

        BUG-033 (SPEC.md A53): the env `GARAGE61_TOKEN` is invisible to
        authenticated callers here. Reporting it as `connected: true` used to
        tell a beta user they had a Garage61 connection when they did not,
        which is precisely the misleading state that invited `/api/sync`'s
        env-fallback leak. The env fallback stays only for the no-auth
        loopback mode — the single-user local cockpit it was written for.
        """
        if session_secret is None:
            import os
            return {"connected": bool(os.environ.get("GARAGE61_TOKEN", "").strip())}
        user_pk = getattr(request.state, "user_pk", None)
        if user_pk is None:
            return {"connected": False}
        with open_db(request) as db:
            row = db.conn.execute(
                "SELECT garage61_user_id, created_at FROM garage61_tokens WHERE owner_user_pk=?",
                (user_pk,),
            ).fetchone()
        if row:
            return {"connected": True, "garage61_user_id": row["garage61_user_id"], "since": row["created_at"]}
        return {"connected": False}

    @app.delete("/api/garage61/disconnect")
    def garage61_disconnect(request: Request) -> dict[str, Any]:
        """Remove the stored Garage61 OAuth token for the current user."""
        user_pk = getattr(request.state, "user_pk", None)
        if user_pk is None:
            raise HTTPException(401, detail="not authenticated")
        with open_db(request) as db:
            with db.conn:
                db.conn.execute("DELETE FROM garage61_tokens WHERE owner_user_pk=?", (user_pk,))
        return {"disconnected": True}

    @app.post("/api/sync")
    def sync(request: Request, body: SyncBody | None = None) -> StreamingResponse:
        """Wraps `sync_driver` (UI-SPEC U6 condition 1).

        Token resolution — critical since BUG-033 (SPEC.md A53):

        - **Auth on**: only the user's stored OAuth token is used. If they
          have none, this returns HTTP 400 telling them to connect their
          Garage61 account. Falling back to `GARAGE61_TOKEN` here would
          import the owner's laps into a beta user's tenant — the env var
          belongs to the process (set by `deploy/driverdna.service`), not
          to the requesting user.
        - **Auth off (local loopback)**: the env fallback stays. That is
          the single-user cockpit the flag was written for, and the two
          existing "missing token" tests in this file cover it.

        This endpoint never reads a token out of the request body.

        Returns SSE: progress events as cohorts are discovered and laps
        imported, then a terminal ``complete`` event with the full result
        list. Keeps data flowing so a reverse proxy (Cloudflare) does not
        time out on a slow multi-cohort sync."""
        from driverdna.garage61.client import Garage61Client
        from driverdna.garage61.sync import sync_driver

        stored_token = _resolve_garage61_token(request)
        if session_secret is not None and stored_token is None:
            # BUG-033: no cross-tenant env fallback for authenticated users.
            raise HTTPException(
                400,
                detail="Garage61 not connected — sign in with Garage61 first. "
                "The sync endpoint never uses a shared token.",
            )
        try:
            client = Garage61Client(token=stored_token) if stored_token else Garage61Client()
        except RuntimeError as e:
            raise HTTPException(400, detail=str(e)) from None

        reason = missing_reason(db_path)
        if reason:
            raise HTTPException(404, detail=f"{reason} — run `driverdna import` first")

        config = load_config(config_path)
        sync_car = body.car if body else None
        sync_track = body.track if body else None
        user_pk = request.state.user_pk if hasattr(getattr(request, "state", None), "user_pk") else 1

        def _sync_events():
            q: queue.Queue[dict[str, Any]] = queue.Queue()
            # The cohort cap is a property of the run, not of any cohort, so it
            # rides the `discovering` event. Repeated on `complete` so the SPA
            # can render it without holding progress state across the stream.
            discovery: dict[str, Any] = {}

            def _forward(evt: dict[str, Any]) -> None:
                if evt.get("type") == "discovering":
                    discovery.update(evt)
                q.put(evt)

            def run() -> None:
                from driverdna.garage61.client import Garage61AuthError
                try:
                    with Database.open(db_path, user_pk=user_pk) as db:
                        summaries = sync_driver(
                            db, client, driver="owner", config=config,
                            car=sync_car, track=sync_track,
                            on_progress=_forward,
                        )
                        if summaries:
                            db.enforce_retention(config.retention.raw_laps_per_cohort)
                        db.invalidate_driver_payload_cache()
                        gc.collect()
                        q.put({
                            "type": "complete",
                            "results": [_cohort_sync_dict(s) for s in summaries],
                            "cohorts_total": discovery.get(
                                "cohorts_total", len(summaries)
                            ),
                            "cohorts_skipped": discovery.get("cohorts_skipped", []),
                            "max_cohorts": config.sync.max_cohorts,
                        })
                except Garage61AuthError:
                    q.put({
                        "type": "error",
                        "detail": "Garage61 sign-in expired — reconnect at Import › Connect Garage61.",
                        "auth_expired": True,
                    })
                except Exception as exc:
                    q.put({"type": "error", "detail": str(exc)})

            t = threading.Thread(target=run, daemon=True)
            t.start()
            yield from _drain_sse(q, t, config.api.sse_heartbeat_seconds)
            t.join()

        return StreamingResponse(_sync_events(), media_type="text/event-stream")

    @app.post("/api/cohorts/{slug}/rebuild-map")
    def rebuild_map(slug: str, request: Request) -> dict[str, Any]:
        """Wraps `rebuild_cohort_map` (UI-SPEC U6 condition 2): in-place
        refreeze of a cohort's frozen corner map from its full current lap
        set. It rewrites frozen geometry, so the UI gates the call behind its
        own explicit confirm (decision 5) — same division of responsibility
        as `config_apply`, which likewise trusts the UI's confirm gate rather
        than re-implementing staging here."""
        from driverdna.pipeline import rebuild_cohort_map

        with open_db(request) as db:
            cohort = resolve(db, slug)
            config = load_config(config_path)
            result = rebuild_cohort_map(
                db, driver=cohort["driver"], car=cohort["car"], track=cohort["track"],
                config=config,
            )
            if not result.existed:
                raise HTTPException(
                    404,
                    detail=f"no corner map for {cohort['car']} @ {cohort['track']} "
                    "— nothing to rebuild",
                )
            return {
                "car": result.car,
                "track": result.track,
                "corners": [
                    {
                        "corner_id": c.corner_id,
                        "centroid_shift_m": c.centroid_shift_m,
                        "window_changed": c.window_changed,
                        "laps_remeasured": c.laps_remeasured,
                        "laps_cleared": c.laps_cleared,
                    }
                    for c in result.corners
                ],
                "admitted": result.admitted,
                "class_changes": [
                    {"corner_id": c, "old": o, "new": n} for c, o, n in result.class_changes
                ],
                "total_cleared": result.total_cleared,
            }

    # --- chat (U3) ------------------------------------------------------------
    # A ChatSession is stateful (in-memory conversation + staged proposals,
    # UI-SPEC decision 5) and keeps its own DB connection open for the
    # session's lifetime — unlike every other endpoint's per-request
    # `with open_db(request) as db:`.
    #
    # That deviation used to come with "a local, single-user tool doesn't need
    # session eviction machinery". Against a local file that was true: an
    # abandoned browser tab leaked a file handle. Against a hosted store it is
    # not — every live session pins a server connection, and enough abandoned
    # tabs exhaust the connection limit and take out every other endpoint. So
    # sessions are now bounded and idle-expired; an evicted session's next
    # request gets the existing 404 "unknown chat session", which the SPA
    # already handles.

    def _evict_chat_sessions() -> None:
        now = time.monotonic()
        for sid, entry in list(chat_sessions.items()):
            if now - entry["touched"] > CHAT_SESSION_TTL_S:
                _close_chat_session(sid)
        while len(chat_sessions) > MAX_CHAT_SESSIONS:
            oldest = min(chat_sessions, key=lambda s: chat_sessions[s]["touched"])
            _close_chat_session(oldest)

    def _close_chat_session(session_id: str) -> None:
        entry = chat_sessions.pop(session_id, None)
        if entry is not None:
            entry["db"].close()

    def _touch_chat_session(session_id: str, request: Request) -> dict[str, Any]:
        entry = chat_sessions.get(session_id)
        if entry is None:
            raise HTTPException(404, detail=f"unknown chat session: {session_id}")
        user_pk = getattr(request.state, "user_pk", 1)
        if entry.get("user_pk") is not None and entry["user_pk"] != user_pk:
            raise HTTPException(404, detail=f"unknown chat session: {session_id}")
        entry["touched"] = time.monotonic()
        return entry

    @app.post("/api/chat/sessions")
    def create_chat_session(body: ChatCreateBody, request: Request) -> dict[str, Any]:
        # check_same_thread=False: this connection outlives the request that
        # opens it (kept in `chat_sessions` for follow-up messages/confirm),
        # and FastAPI dispatches sync endpoints/StreamingResponse generators
        # to a thread pool — later calls on this session can legitimately
        # land on a different worker thread. Access stays sequential (one
        # request completes before the next starts), never concurrent.
        #
        # request is passed through so the session's connection is scoped to
        # the signed-in driver's own user_pk — without it every chat session
        # would silently read/write against user_pk 1 regardless of who
        # signed in, a cross-tenant leak once more than one user exists.
        db = open_db(request, check_same_thread=False)
        try:
            cohort = resolve(db, body.cohort)
            try:
                cfg = load_config(config_path)
                byok_key = _resolve_byok_key(db, cfg.coach.provider)
                provider = make_chat_provider(api_key=byok_key)
            except RuntimeError as e:
                raise HTTPException(503, detail=str(e)) from None
            session_id = uuid.uuid4().hex[:12]
            session = ChatSession(
                db=db, store=ConfigStore(config_path, db), provider=provider,
                driver=body.driver, car=cohort["car"], track=cohort["track"],
                config=load_config(config_path), session_id=session_id,
            )
        except Exception:
            db.close()
            raise
        user_pk = getattr(request.state, "user_pk", None)
        chat_sessions[session_id] = {
            "session": session, "db": db, "touched": time.monotonic(),
            "user_pk": user_pk,
        }
        _evict_chat_sessions()
        return {
            "session_id": session_id,
            "cohort": body.cohort,
            "bundle_version": session.bundle["bundle_version"],
        }

    def _get_session(session_id: str, request: Request) -> ChatSession:
        return _touch_chat_session(session_id, request)["session"]

    @app.post("/api/chat/sessions/{session_id}/messages")
    def chat_message(session_id: str, body: ChatMessageBody, request: Request) -> StreamingResponse:
        session = _get_session(session_id, request)

        def events():
            for event in session.ask_stream(body.text):
                yield f"data: {json.dumps(event, sort_keys=True)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/chat/sessions/{session_id}/confirm/{index}")
    def chat_confirm(session_id: str, index: int, request: Request) -> dict[str, Any]:
        session = _get_session(session_id, request)
        try:
            return session.confirm(index)
        except IndexError as e:
            raise HTTPException(404, detail=str(e)) from None

    return app
