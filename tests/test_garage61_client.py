"""Garage61Client tests (M0b+): mocked transport only, never the live API.

Every canned response shape here matches what docs/garage61-api.md recorded
as observed behavior — required `tracks` filter, unscoped `/laps` results
filtered client-side on driver id, 401/403/404 error shapes, pagination via
limit/offset + total.
"""

from __future__ import annotations

import json

import pytest

from driverdna.garage61.client import (
    Garage61AuthError,
    Garage61Client,
    Garage61ForbiddenError,
    Garage61NotFoundError,
    Garage61RequestError,
)

ME = {"id": "me-01", "slug": "owner", "firstName": "O", "lastName": "W"}


def _json(status: int, obj) -> tuple[int, bytes]:
    return status, json.dumps(obj).encode("utf-8")


class FakeTransport:
    def __init__(self, routes: dict[str, callable]):
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, path: str, params):
        self.calls.append((path, params))
        if path not in self.routes:
            raise AssertionError(f"unexpected path {path}")
        return self.routes[path](params)


def _lap(lap_id: str, driver_id: str = ME["id"]) -> dict:
    return {
        "id": lap_id,
        "driver": {"id": driver_id, "slug": "someone"},
        "event": "ev-1", "session": 0, "run": 0,
        "startTime": "2026-07-01T00:00:00Z",
        "clean": True, "missing": False, "incomplete": False,
        "offtrack": False, "discontinuity": False, "pitlane": False,
    }


def test_requires_token_without_transport(monkeypatch):
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GARAGE61_TOKEN"):
        Garage61Client()


def test_me_is_cached_after_first_call():
    transport = FakeTransport({"/me": lambda p: _json(200, ME)})
    client = Garage61Client(transport=transport)
    assert client.me() == ME
    assert client.me() == ME
    assert len(transport.calls) == 1


def test_list_own_laps_requires_tracks_and_filters_self():
    other = _lap("L-OTHER", driver_id="not-me")
    mine = _lap("L-MINE")

    def laps(params):
        assert params["tracks"] == 69
        return _json(200, {"items": [other, mine], "total": 2})

    transport = FakeTransport({"/me": lambda p: _json(200, ME), "/laps": laps})
    client = Garage61Client(transport=transport)
    result = client.list_own_laps(track_id=69)
    assert [lap["id"] for lap in result] == ["L-MINE"]


def test_list_own_laps_paginates_until_total_reached():
    page1 = [_lap("A"), _lap("B")]
    page2 = [_lap("C")]

    def laps(params):
        if params["offset"] == 0:
            return _json(200, {"items": page1, "total": 3})
        if params["offset"] == 2:
            return _json(200, {"items": page2, "total": 3})
        raise AssertionError(f"unexpected offset {params['offset']}")

    transport = FakeTransport({"/me": lambda p: _json(200, ME), "/laps": laps})
    client = Garage61Client(transport=transport)
    result = client.list_own_laps(track_id=69, page_size=2)
    assert [lap["id"] for lap in result] == ["A", "B", "C"]


def test_list_own_laps_passes_car_filter_when_given():
    seen = {}

    def laps(params):
        seen.update(params)
        return _json(200, {"items": [], "total": 0})

    transport = FakeTransport({"/me": lambda p: _json(200, ME), "/laps": laps})
    Garage61Client(transport=transport).list_own_laps(track_id=69, car_id=8)
    assert seen["cars"] == 8


def test_lap_csv_returns_raw_bytes():
    transport = FakeTransport({"/laps/L1/csv": lambda p: (200, b"Speed,LapDistPct\n1,0.1\n")})
    client = Garage61Client(transport=transport)
    assert client.lap_csv("L1") == b"Speed,LapDistPct\n1,0.1\n"


def test_401_raises_auth_error():
    transport = FakeTransport({
        "/me": lambda p: _json(401, {"message": "Bad authentication: invalid token."})
    })
    with pytest.raises(Garage61AuthError, match="Bad authentication"):
        Garage61Client(transport=transport).me()


def test_403_on_other_driver_lap_raises_forbidden_with_code():
    transport = FakeTransport({
        "/laps/L1/csv": lambda p: _json(
            403, {"message": "No permission to view this lap.", "code": "forbidden_lap"}
        )
    })
    with pytest.raises(Garage61ForbiddenError, match="forbidden_lap"):
        Garage61Client(transport=transport).lap_csv("L1")


def test_404_raises_not_found():
    transport = FakeTransport({
        "/laps/nope/csv": lambda p: _json(404, {"message": "Lap not found"})
    })
    with pytest.raises(Garage61NotFoundError, match="Lap not found"):
        Garage61Client(transport=transport).lap_csv("nope")


def test_400_missing_required_param_raises_request_error():
    transport = FakeTransport({
        "/laps": lambda p: _json(
            400,
            {"error_message": 'operation FindLaps: decode params: query: '
                               '"tracks": query parameter "tracks" not set'},
        ),
        "/me": lambda p: _json(200, ME),
    })
    with pytest.raises(Garage61RequestError, match="tracks"):
        Garage61Client(transport=transport).list_own_laps(track_id=69)
