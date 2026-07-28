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

import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse, RedirectResponse
from pydantic import BaseModel

from driverdna.chat.session import ChatProvider, ChatSession
from driverdna.chat.tools import execute_tool
from driverdna.config import ConfigStore, config_snapshot, describe_key, load_config
from driverdna.db import Database
from driverdna.store import missing_reason
from driverdna.ui import auth
from driverdna.report.payload import (
    build_cohort_payload,
    build_driver_payload,
    cohort_slug,
    list_cohorts,
    to_normalized_json,
)

TRACE_POINTS = 800  # transport downsampling only — layout math, not measurement


class AnnotateBody(BaseModel):
    status: str  # acknowledged | intentional
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
PUBLIC_API_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/google/login",
    "/api/auth/google/callback",
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
) -> FastAPI:
    """`chat_provider_factory` defaults to the real `ClaudeChatProvider`
    (env-only `ANTHROPIC_API_KEY`, lazy-imported so nothing else needs the
    SDK installed); tests inject a mocked provider here, same pattern as
    the CLI's `chat` command — no test ever calls a live model.

    `access_token` is the single-driver passphrase (docs/DEPLOY-SPEC.md H1),
    injected the same way rather than read from the environment here, so tests
    never depend on process state. **None means auth is not configured and
    every route is open** — which is the local `driverdna ui` experience on
    loopback, and what keeps this change additive rather than a rewrite. The
    CLI supplies it from `DRIVERDNA_ACCESS_TOKEN` and refuses to bind a
    non-loopback address without it.
    """
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
    )
    chat_sessions: dict[str, dict[str, Any]] = {}

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

    def _is_https(request: Request) -> bool:
        """Cloud Run terminates TLS and forwards `X-Forwarded-Proto`, and
        uvicorn only trusts that header from `forwarded_allow_ips` (which does
        not include a Cloud Run front end). Read it directly rather than
        shipping an unmarked session cookie over a real HTTPS deployment."""
        forwarded = request.headers.get("x-forwarded-proto", "")
        if forwarded:
            return forwarded.split(",")[0].strip() == "https"
        return request.url.scheme == "https"

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        """Exchange credentials for a signed, expiring session cookie."""
        if session_secret is None:
            raise HTTPException(400, detail=f"auth not configured - set {auth.SESSION_SECRET_ENV}")
        
        key = _client_key(request)
        locked = throttle.locked_for(key)
        if locked:
            raise HTTPException(429, detail=f"too many failed attempts — try again in {locked}s")
            
        from datetime import datetime
        session_epoch = datetime.utcnow().isoformat()
        
        with open_db(request) as db:
            row = db.conn.execute("SELECT user_pk, password_hash FROM users WHERE email=?", (body.email,)).fetchone()
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
        
        with open_db(request) as db:
            row = db.conn.execute("SELECT user_pk FROM users WHERE email=?", (body.email,)).fetchone()
            if row:
                user_pk = row["user_pk"]
                with db.conn:
                    db.conn.execute(
                        "INSERT INTO password_resets (user_pk, reset_token_hash, expires_at) VALUES (?, ?, ?)",
                        (user_pk, token_hash, expires_at)
                    )
        
                from driverdna.ui.email import send_reset_email
                reset_link = f"{str(request.base_url).rstrip('/')}/reset-password?token={token}"
                send_reset_email(smtp_host, int(smtp_port), smtp_user, smtp_password, body.email, reset_link)

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
            
        import urllib.parse
        url_obj = request.url_for("google_callback")
        if _is_https(request):
            url_obj = url_obj.replace(scheme="https")
            
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": google_client_id,
            "redirect_uri": str(url_obj),
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "online",
        })
        return RedirectResponse(url)

    @app.get("/api/auth/google/callback")
    def google_callback(code: str, request: Request) -> Response:
        if not google_client_id or not google_client_secret or not session_secret:
            raise HTTPException(400, "Google OAuth not configured")
            
        import urllib.request
        import urllib.parse
        
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
            raise HTTPException(400, f"failed to exchange token: {e.read().decode('utf-8')}")
            
        id_token = token_res.get("id_token")
        if not id_token:
            raise HTTPException(400, "no id_token returned")
            
        verify_req = urllib.request.Request(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}")
        try:
            with urllib.request.urlopen(verify_req) as f:
                claims = json.loads(f.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise HTTPException(400, f"failed to verify id_token: {e.read().decode('utf-8')}")
            
        if claims.get("aud") != google_client_id:
            raise HTTPException(400, "token audience mismatch")
            
        email = claims.get("email")
        if not email:
            raise HTTPException(400, "no email in id_token")
            
        with open_db(request) as db:
            row = db.conn.execute("SELECT user_pk FROM users WHERE email=?", (email,)).fetchone()
            if row:
                user_pk = row["user_pk"]
            else:
                count = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                if count == 0:
                    from datetime import datetime
                    user_pk = db.conn.execute(
                        "INSERT INTO users (email, password_hash, session_epoch) VALUES (?, ?, ?) RETURNING user_pk",
                        (email, "", datetime.utcnow().isoformat())
                    ).fetchone()["user_pk"]
                else:
                    raise HTTPException(403, "registration is closed")
            
            session_epoch = db.conn.execute("SELECT session_epoch FROM users WHERE user_pk=?", (user_pk,)).fetchone()["session_epoch"]
            
        ttl = load_config(config_path).auth.session_ttl_hours * 3600
        
        response = RedirectResponse("/")
        response.set_cookie(
            auth.SESSION_COOKIE,
            auth.issue_session(user_pk, session_epoch, session_secret, ttl_seconds=ttl),
            max_age=ttl,
            httponly=True,
            samesite="lax",
            secure=_is_https(request),
            path="/",
        )
        return response

    @app.post("/api/auth/logout")
    def logout(response: Response) -> dict[str, Any]:
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return {"authenticated": False}

    @app.get("/api/auth/status")
    def auth_status(request: Request) -> dict[str, bool]:
        """What the SPA asks before drawing anything, so it can show the login
        gate instead of ten failed panels. Deliberately says only whether a
        sign-in is required and whether this caller has one."""
        return {
            "required": session_secret is not None,
            "authenticated": authenticated(request),
        }

    def make_chat_provider() -> ChatProvider:
        if chat_provider_factory is not None:
            return chat_provider_factory()
        from driverdna.chat.session import ClaudeChatProvider

        cfg = load_config(config_path)
        return ClaudeChatProvider(cfg.coach.model, cfg.coach.max_tokens)

    def open_db(request: Request | None = None, *, check_same_thread: bool = True) -> Database:
        # A hosted store has no file to stat and creates its schema on
        # connect, so "not there yet" is reported by `missing_reason` only
        # for the SQLite case; an empty hosted store surfaces as the normal
        # no-cohorts empty state instead.
        reason = missing_reason(db_path)
        if reason:
            raise HTTPException(404, detail=f"{reason} — run `driverdna import` first")
        user_pk = request.state.user_pk if hasattr(getattr(request, "state", None), "user_pk") else 1
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

    # --- reads --------------------------------------------------------------

    @app.get("/api/driver")
    def driver(request: Request) -> Response:
        with open_db(request) as db:
            return normalized(build_driver_payload(db, load_config(config_path)))

    @app.get("/api/cohorts")
    def cohorts(request: Request) -> list[dict[str, str]]:
        with open_db(request) as db:
            return [
                c | {"slug": cohort_slug(c["car"], c["track"])}
                for c in list_cohorts(db)
            ]

    @app.get("/api/cohorts/{slug}/payload")
    def cohort_payload(slug: str, request: Request) -> Response:
        with open_db(request) as db:
            cohort = resolve(db, slug)
            return normalized(
                build_cohort_payload(db, **cohort, config=load_config(config_path))
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
    ) -> dict[str, Any]:
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
        is missing — never silently skipped."""
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

        config = load_config(config_path)
        results: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as tmp:
            with Database.open(db_path, user_pk=request.state.user_pk if hasattr(getattr(request, "state", None), "user_pk") else 1) as db:
                for upload, file_car, file_track, auto_detected in resolved:
                    # Original filename preserved (not a random temp name):
                    # parse_lap's Garage61 lap-ID regex reads it, same as a
                    # real directory import.
                    dest = Path(tmp) / (upload.filename or "upload.csv")
                    dest.write_bytes(await upload.read())
                    result = import_lap_file(
                        db, dest, config=config, driver="owner", car=file_car,
                        track=file_track, role=role, session_key=session, lap_date=date,
                    )
                    matched = sum(1 for a in result.assigned if a)
                    results.append({
                        "filename": upload.filename,
                        "car": file_car,
                        "track": file_track,
                        # True when this file's car and/or track came from its
                        # filename -- with a one-field override, part of the
                        # pair can be given and the rest detected. The resolved
                        # car/track above are what was actually used.
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
                    })
                evicted = db.enforce_retention(config.retention.raw_laps_per_cohort)
        return {"results": results, "evicted": evicted}

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

    @app.get("/api/config/history")
    def config_history(request: Request) -> list[dict[str, Any]]:
        with open_db(request) as db:
            return [
                dict(r)
                for r in db.conn.execute(
                    "SELECT * FROM config_history ORDER BY change_pk"
                )
            ]

    # --- writes (wrappers over the audited paths only) ----------------------

    @app.post("/api/findings/{finding_id}/annotate")
    def annotate(finding_id: str, body: AnnotateBody, request: Request) -> dict[str, Any]:
        if body.status not in ("acknowledged", "intentional"):
            raise HTTPException(422, detail="status must be acknowledged or intentional")
        with open_db(request) as db:
            config = load_config(config_path)
            known = {
                f["finding_id"]
                for c in list_cohorts(db)
                for f in build_cohort_payload(db, **c, config=config)["findings"]
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

    @app.post("/api/sync")
    def sync(request: Request, body: SyncBody | None = None) -> list[dict[str, Any]]:
        """Wraps `sync_driver` (UI-SPEC U6 condition 1). `Garage61Client()` is
        constructed here, straight from the environment (`GARAGE61_TOKEN`) —
        this endpoint never reads a token out of the request body. Mirrors
        `driverdna sync`'s own order: the client is constructed, and its
        missing-token RuntimeError can surface, before the DB is ever opened —
        an unset token writes nothing."""
        from driverdna.garage61.client import Garage61Client
        from driverdna.garage61.sync import sync_driver

        try:
            client = Garage61Client()
        except RuntimeError as e:
            raise HTTPException(400, detail=str(e)) from None

        config = load_config(config_path)
        with open_db(request) as db:
            summaries = sync_driver(
                db, client, driver="owner", config=config,
                car=body.car if body else None, track=body.track if body else None,
            )
            # Same conditional as the CLI: retention only runs once there is
            # something to enforce it over (an empty discovery skips it too).
            if summaries:
                db.enforce_retention(config.retention.raw_laps_per_cohort)
            return [_cohort_sync_dict(s) for s in summaries]

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

    def _touch_chat_session(session_id: str) -> dict[str, Any]:
        entry = chat_sessions.get(session_id)
        if entry is None:
            raise HTTPException(404, detail=f"unknown chat session: {session_id}")
        entry["touched"] = time.monotonic()
        return entry

    @app.post("/api/chat/sessions")
    def create_chat_session(body: ChatCreateBody) -> dict[str, Any]:
        # check_same_thread=False: this connection outlives the request that
        # opens it (kept in `chat_sessions` for follow-up messages/confirm),
        # and FastAPI dispatches sync endpoints/StreamingResponse generators
        # to a thread pool — later calls on this session can legitimately
        # land on a different worker thread. Access stays sequential (one
        # request completes before the next starts), never concurrent.
        db = open_db(check_same_thread=False)
        try:
            cohort = resolve(db, body.cohort)
            try:
                provider = make_chat_provider()
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
        chat_sessions[session_id] = {
            "session": session, "db": db, "touched": time.monotonic(),
        }
        _evict_chat_sessions()
        return {
            "session_id": session_id,
            "cohort": body.cohort,
            "bundle_version": session.bundle["bundle_version"],
        }

    def _get_session(session_id: str) -> ChatSession:
        return _touch_chat_session(session_id)["session"]

    @app.post("/api/chat/sessions/{session_id}/messages")
    def chat_message(session_id: str, body: ChatMessageBody, request: Request) -> StreamingResponse:
        session = _get_session(session_id)

        def events():
            # SSE progress states (UI-SPEC decision 4): thinking ->
            # consulting_tool* -> validating -> response|error. No text
            # streams token-by-token — the validated reply arrives whole in
            # the terminal "response" event, or "error" replaces it, never
            # retracted partial text.
            for event in session.ask_stream(body.text):
                yield f"data: {json.dumps(event, sort_keys=True)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/chat/sessions/{session_id}/confirm/{index}")
    def chat_confirm(session_id: str, index: int) -> dict[str, Any]:
        session = _get_session(session_id)
        try:
            return session.confirm(index)
        except IndexError as e:
            raise HTTPException(404, detail=str(e)) from None

    return app
