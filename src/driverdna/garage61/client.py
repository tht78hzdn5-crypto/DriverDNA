"""Garage61Client: token auth, lap listing/filtering, CSV fetch.

Built from M0b's observed behavior plus Garage61's own OpenAPI specification
(docs/garage61-api.md) — nothing here assumes anything neither source states.
`GARAGE61_TOKEN` is read from the environment only (never persisted, printed,
or logged); a `transport` can be injected for testing so no test ever calls
the live API.

Confirmed capabilities this client relies on:
  - Base URL `https://garage61.net/api/v1`, `Authorization: Bearer <token>`.
  - `/laps` requires an explicit `tracks` filter and is NOT owner-scoped by
    default — it returns laps from many drivers for that track/car.
  - `/laps/{id}` and `/laps/{id}/csv` return 200 for this account's own laps;
    a lap owned by someone else returns 403 `forbidden_lap` — confirmed NOT
    fetchable with this token/plan. This client makes no attempt to fetch
    other-driver laps; reference laps stay on the manual `import` path.
  - Pagination is `limit`/`offset` with a `total` field in every list
    response; `limit`'s maximum and default are both 1000 (spec).

Per-spec filtering (A28), none of it live-verified — see the "spec-sourced,
not observed" caveat in docs/garage61-api.md:
  - `group=none` returns ALL laps. The default, `group=driver`, returns one
    personal-best lap per driver — which is what M0b measured and wrongly
    concluded was the endpoint's fixed shape.
  - `drivers=me` scopes the search server-side. This is an optimisation, NOT
    a trust boundary: the client-side `driver.id == /me` filter below is kept
    unconditionally, because reference-lap isolation is a non-negotiable and
    must not rest on an unverified query parameter.
  - `after` (RFC3339 datetime) and `age` (days; negative = seasons) are the
    real date filters. M0b tried `start`/`end`, which this API silently
    ignores along with every other unrecognised name.
  - `lapTypes` defaults to normal (full) laps only, which is exactly what
    M0a's single-lap contract requires — in/out laps are not requested.
  - `unclean=true` asks for laps flagged not-clean. DriverDNA wants these:
    a spin or an off is measured, not filtered (A19). Laps whose telemetry
    is unusable (`missing`/`incomplete`) are dropped by `sync`, after the
    fact, on the lap's own flags rather than by asking the API for less.
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

#: `group=none` — "Return all laps" (spec). The API's own default is
#: `driver`, "Personal best laps per driver", which is what M0b's census
#: measured as "at most one lap per driver per cohort".
GROUP_ALL_LAPS = "none"
#: `limit`'s documented maximum AND default (spec). M0b observed values above
#: this silently falling back rather than erroring, which matches a cap.
MAX_PAGE_SIZE = 1000


def _bool_param(value: bool) -> str:
    """Lower-case `true`/`false`. Python's `str(True)` is `"True"`, which is
    accepted by Go's ParseBool but is not what the spec writes — send the
    documented spelling rather than relying on a lenient parser."""
    return "true" if value else "false"


@dataclass(frozen=True)
class LapListing:
    """One cohort's self-laps, plus what it took to find them.

    `rows_scanned`/`foreign_rows` exist so `sync` can report whether the
    server-side `drivers=me` scope actually applied: if `foreign_rows` is
    non-zero, other drivers' rows were paged through and discarded locally,
    meaning the parameter did not take effect. Correctness is unaffected
    either way — only the cost of the listing, and what we can honestly
    claim about the API.
    """

    laps: list[dict[str, Any]]
    rows_scanned: int
    foreign_rows: int


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
        self,
        *,
        track_id: int,
        car_id: int | None = None,
        page_size: int = MAX_PAGE_SIZE,
        group: str = GROUP_ALL_LAPS,
        unclean: bool = True,
        after: str | None = None,
        max_age_days: int | None = None,
    ) -> LapListing:
        """Every one of THIS account's laps for one (track[, car]).

        `group` defaults to `none` ("return all laps") rather than the API's
        own `driver` default ("personal best laps per driver") — the whole
        point of A28. `unclean=True` keeps incident laps in the result set.

        `/laps` is not owner-scoped by default (M0b), so `drivers=me` is sent
        AND every page is still filtered client-side on `driver.id == /me`'s
        id. The redundancy is deliberate: `drivers=me` is spec-sourced and
        never live-verified here, and this API silently ignores query names
        it does not recognise, so a typo or a rename would degrade to "all
        drivers" with no error. The client-side filter is what actually
        guarantees no other driver's lap is ever returned; the returned
        `foreign_rows` count reports whether the server-side scope did
        anything, instead of assuming it did.
        """
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(
                f"page_size must be 1..{MAX_PAGE_SIZE} (the API's documented "
                f"limit maximum); got {page_size}"
            )
        me_id = self.me()["id"]
        laps: list[dict[str, Any]] = []
        rows_scanned = 0
        foreign_rows = 0
        offset = 0
        while True:
            params: dict[str, Any] = {
                "tracks": track_id,
                "limit": page_size,
                "offset": offset,
                "group": group,
                "drivers": "me",
                "unclean": _bool_param(unclean),
                "after": after,
                "age": max_age_days,
            }
            if car_id is not None:
                params["cars"] = car_id
            page = self._get("/laps", params)
            items = page.get("items", [])
            for item in items:
                if item.get("driver", {}).get("id") == me_id:
                    laps.append(item)
                else:
                    foreign_rows += 1
            rows_scanned += len(items)
            offset += len(items)
            if not items or offset >= page.get("total", 0):
                break
        return LapListing(laps=laps, rows_scanned=rows_scanned, foreign_rows=foreign_rows)

    def lap_csv(self, lap_id: str) -> bytes:
        """Raw CSV bytes for one lap. Raises Garage61ForbiddenError (403,
        `forbidden_lap`) if this token doesn't own the lap — by design, this
        client is never called with anything but this account's own lap ids
        (see `list_own_laps`'s self-filter)."""
        status, body = self._transport.get(f"/laps/{lap_id}/csv", None)
        _raise_for_status(status, body, context=f"GET /laps/{lap_id}/csv")
        return body
