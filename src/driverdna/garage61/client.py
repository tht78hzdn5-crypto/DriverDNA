"""Garage61Client: token auth, lap listing/filtering, CSV fetch.

Built from M0b's observed behavior (docs/garage61-api.md) — nothing here
assumes anything not confirmed there. `GARAGE61_TOKEN` is read from the
environment only (never persisted, printed, or logged); a `transport` can be
injected for testing so no test ever calls the live API.

Confirmed capabilities this client relies on:
  - Base URL `https://garage61.net/api/v1`, `Authorization: Bearer <token>`.
  - `/laps` requires an explicit `tracks` filter and is NOT owner-scoped —
    it returns laps from many drivers for that track/car, so every result is
    filtered client-side on `driver.id == /me`'s id.
  - `/laps/{id}` and `/laps/{id}/csv` return 200 for this account's own laps;
    a lap owned by someone else returns 403 `forbidden_lap` — confirmed NOT
    fetchable with this token/plan. This client makes no attempt to fetch
    other-driver laps; reference laps stay on the manual `import` path.
  - Pagination is `limit`/`offset` with a `total` field in every list
    response.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

BASE_URL = "https://garage61.net/api/v1"


class Garage61Error(Exception):
    """Base class for all Garage61 API errors."""


class Garage61AuthError(Garage61Error):
    """401 — missing or invalid token."""


class Garage61ForbiddenError(Garage61Error):
    """403 — observed (M0b) as `forbidden_lap`: a real lap this token has no
    permission to view (i.e. it belongs to a different driver)."""


class Garage61NotFoundError(Garage61Error):
    """404 — the API does not distinguish "id doesn't exist" from "id exists
    but isn't visible to this token" (M0b); both return this shape."""


class Garage61RequestError(Garage61Error):
    """400 or any other unexpected status; carries the raw error body."""


class Transport(Protocol):
    def get(self, path: str, params: dict[str, Any] | None) -> tuple[int, bytes]: ...


@dataclass
class _UrllibTransport:
    """Real HTTP transport — stdlib only, no new dependency for one client."""

    token: str
    base_url: str = BASE_URL
    timeout_s: float = 20.0

    def get(self, path: str, params: dict[str, Any] | None) -> tuple[int, bytes]:
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}, doseq=True
            )
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()


def _raise_for_status(status: int, body: bytes, *, context: str) -> None:
    if status < 400:
        return
    message = body.decode("utf-8", "replace")
    code = None
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            message = parsed.get("message") or parsed.get("error_message") or message
            code = parsed.get("code")
    except json.JSONDecodeError:
        pass
    suffix = f" ({code})" if code else ""
    if status == 401:
        raise Garage61AuthError(f"{context}: {message}{suffix}")
    if status == 403:
        raise Garage61ForbiddenError(f"{context}: {message}{suffix}")
    if status == 404:
        raise Garage61NotFoundError(f"{context}: {message}{suffix}")
    raise Garage61RequestError(f"{context}: HTTP {status}: {message}{suffix}")


class Garage61Client:
    """Thin, observed-behavior-only wrapper over the Garage61 API v1."""

    def __init__(self, *, token: str | None = None, transport: Transport | None = None):
        if transport is None:
            token = token or os.environ.get("GARAGE61_TOKEN")
            if not token:
                raise RuntimeError(
                    "GARAGE61_TOKEN is not set. `sync` requires it (env only; "
                    "never persisted or logged). Manual `import` works without it."
                )
            transport = _UrllibTransport(token=token)
        self._transport = transport
        self._me: dict[str, Any] | None = None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        status, body = self._transport.get(path, params)
        _raise_for_status(status, body, context=f"GET {path}")
        return json.loads(body)

    def me(self) -> dict[str, Any]:
        if self._me is None:
            self._me = self._get("/me")
        return self._me

    def statistics(self) -> list[dict[str, Any]]:
        """Per-(day, car, track, sessionType) driving-activity rows — used to
        discover which (car, track) cohorts this account has actually driven,
        since `/laps` has no unscoped "everything" listing (M0b)."""
        return self._get("/me/statistics").get("drivingStatistics", [])

    def cars(self) -> list[dict[str, Any]]:
        return self._get("/cars").get("items", [])

    def tracks(self) -> list[dict[str, Any]]:
        return self._get("/tracks").get("items", [])

    def list_own_laps(
        self, *, track_id: int, car_id: int | None = None, page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        """Every one of THIS account's laps for one (track[, car]).

        `/laps` is not owner-scoped by default (M0b) — every page is fetched
        in full and filtered client-side on `driver.id == /me`'s id. Never
        fetches or returns another driver's lap metadata beyond what the
        listing itself already exposes.
        """
        me_id = self.me()["id"]
        laps: list[dict[str, Any]] = []
        offset = 0
        while True:
            params: dict[str, Any] = {
                "tracks": track_id, "limit": page_size, "offset": offset,
            }
            if car_id is not None:
                params["cars"] = car_id
            page = self._get("/laps", params)
            items = page.get("items", [])
            laps.extend(
                item for item in items if item.get("driver", {}).get("id") == me_id
            )
            offset += len(items)
            if not items or offset >= page.get("total", 0):
                break
        return laps

    def lap_csv(self, lap_id: str) -> bytes:
        """Raw CSV bytes for one lap. Raises Garage61ForbiddenError (403,
        `forbidden_lap`) if this token doesn't own the lap — by design, this
        client is never called with anything but this account's own lap ids
        (see `list_own_laps`'s self-filter)."""
        status, body = self._transport.get(f"/laps/{lap_id}/csv", None)
        _raise_for_status(status, body, context=f"GET /laps/{lap_id}/csv")
        return body
