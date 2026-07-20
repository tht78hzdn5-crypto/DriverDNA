"""`sync_driver` tests (M0b+): a fake Garage61Client (real client, fake
transport) feeding real CSV bytes through the real import pipeline. Never
touches the live API.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.garage61.client import Garage61Client
from driverdna.garage61.sync import discover_cohorts, sync_driver

FIXTURE_CSV = (Path(__file__).parent / "fixtures" / "Garage_61_RH11X7.csv").read_bytes()

ME = {"id": "me-01", "slug": "owner"}
CAR = {"id": 8, "name": "Mazda MX-5"}
TRACK = {"id": 69, "name": "Laguna Seca", "variant": ""}
TRACK_VARIANT = {"id": 70, "name": "Spa", "variant": "Grand Prix"}


def _json(status: int, obj) -> tuple[int, bytes]:
    return status, json.dumps(obj).encode("utf-8")


def _lap(lap_id: str, *, driver_id: str = ME["id"], run: int = 0, session: int = 0,
         missing: bool = False, incomplete: bool = False,
         start: str = "2026-07-01T00:00:00Z") -> dict:
    return {
        "id": lap_id, "driver": {"id": driver_id}, "event": "ev-1",
        "session": session, "run": run, "startTime": start,
        "clean": True, "missing": missing, "incomplete": incomplete,
        "offtrack": False, "discontinuity": False, "pitlane": False,
    }


class FakeTransport:
    def __init__(self, *, statistics, cars, tracks, laps_by_track, csv_by_id=None):
        self._statistics = statistics
        self._cars = cars
        self._tracks = tracks
        self._laps_by_track = laps_by_track
        self._csv_by_id = csv_by_id or {}
        self.csv_calls: list[str] = []

    def get(self, path, params):
        if path == "/me":
            return _json(200, ME)
        if path == "/me/statistics":
            return _json(200, {"drivingStatistics": self._statistics})
        if path == "/cars":
            return _json(200, {"items": self._cars})
        if path == "/tracks":
            return _json(200, {"items": self._tracks})
        if path == "/laps":
            items = self._laps_by_track.get(params["tracks"], [])
            return _json(200, {"items": items, "total": len(items)})
        if path.endswith("/csv"):
            lap_id = path.split("/")[2]
            self.csv_calls.append(lap_id)
            return 200, self._csv_by_id.get(lap_id, FIXTURE_CSV)
        raise AssertionError(f"unexpected path {path}")


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def test_discover_cohorts_uses_statistics_and_skips_zero_laps():
    transport = FakeTransport(
        statistics=[
            {"car": 8, "track": 69, "lapsDriven": 3},
            {"car": 8, "track": 69, "lapsDriven": 1},  # duplicate cohort, dedup'd
            {"car": 8, "track": 999, "lapsDriven": 0},  # never drove -> skipped
            {"car": 777, "track": 69, "lapsDriven": 2},  # unresolvable car -> skipped
        ],
        cars=[CAR], tracks=[TRACK], laps_by_track={},
    )
    client = Garage61Client(transport=transport)
    cohorts = discover_cohorts(client)
    assert cohorts == [
        {"car_id": 8, "track_id": 69, "car": "Mazda MX-5", "track": "Laguna Seca"}
    ]


def test_discover_cohorts_folds_variant_into_track_label():
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 70, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK_VARIANT], laps_by_track={},
    )
    cohorts = discover_cohorts(Garage61Client(transport=transport))
    assert cohorts[0]["track"] == "Spa (Grand Prix)"


def test_sync_imports_new_laps_with_real_session_run_date(db):
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [_lap("L1", run=3, session=2, start="2026-06-15T10:00:00Z")]},
    )
    client = Garage61Client(transport=transport)
    summaries = sync_driver(db, client, driver="owner", config=DriverDNAConfig())

    assert len(summaries) == 1
    s = summaries[0]
    assert s.car == "Mazda MX-5" and s.track == "Laguna Seca"
    assert s.laps_seen == 1
    assert s.laps_new == 1

    row = db.conn.execute("SELECT * FROM laps WHERE source_file=?",
                           ("garage61-api:L1",)).fetchone()
    assert row is not None
    assert row["session_key"] == "ev-1:2"
    assert row["run_index"] == 3
    assert row["lap_date"] == "2026-06-15T10:00:00Z"
    assert row["role"] == "self"


def test_sync_is_idempotent_and_never_refetches_csv(db):
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [_lap("L1")]},
    )
    client = Garage61Client(transport=transport)
    sync_driver(db, client, driver="owner", config=DriverDNAConfig())
    assert transport.csv_calls == ["L1"]

    summaries = sync_driver(db, client, driver="owner", config=DriverDNAConfig())
    assert summaries[0].laps_new == 0
    assert summaries[0].laps_seen == 1
    assert transport.csv_calls == ["L1"]  # no second CSV fetch


def test_sync_skips_missing_and_incomplete_laps_without_fetching_csv(db):
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 2}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [
            _lap("L-missing", missing=True),
            _lap("L-incomplete", incomplete=True),
        ]},
    )
    client = Garage61Client(transport=transport)
    summaries = sync_driver(db, client, driver="owner", config=DriverDNAConfig())
    s = summaries[0]
    assert s.laps_new == 0
    assert sorted(s.laps_skipped) == [("L-incomplete", "incomplete"), ("L-missing", "missing")]
    assert transport.csv_calls == []


def test_sync_records_sync_state(db):
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [_lap("L1")]},
    )
    client = Garage61Client(transport=transport)
    sync_driver(db, client, driver="owner", config=DriverDNAConfig())
    states = db.sync_states("owner")
    assert len(states) == 1
    assert states[0]["car"] == "Mazda MX-5"
    assert states[0]["laps_seen"] == 1
    assert states[0]["laps_new"] == 1
    assert states[0]["last_synced_at"] is not None


def test_sync_car_track_filters_restrict_cohorts(db):
    transport = FakeTransport(
        statistics=[
            {"car": 8, "track": 69, "lapsDriven": 1},
            {"car": 8, "track": 70, "lapsDriven": 1},
        ],
        cars=[CAR], tracks=[TRACK, TRACK_VARIANT],
        laps_by_track={69: [_lap("L1")], 70: [_lap("L2")]},
    )
    client = Garage61Client(transport=transport)
    summaries = sync_driver(
        db, client, driver="owner", config=DriverDNAConfig(), track="Laguna Seca"
    )
    assert [s.track for s in summaries] == ["Laguna Seca"]


def test_reference_laps_are_never_fetchable_via_sync(db):
    """M0b's finding, mechanically enforced: sync only ever calls
    list_own_laps (self-filtered), so another driver's lap can never reach
    the import pipeline through this path — it stays on manual `import`."""
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [_lap("L-mine"), _lap("L-other", driver_id="someone-else")]},
    )
    client = Garage61Client(transport=transport)
    sync_driver(db, client, driver="owner", config=DriverDNAConfig())
    roles = {r["role"] for r in db.conn.execute("SELECT role FROM laps").fetchall()}
    assert roles == {"self"}
    assert transport.csv_calls == ["L-mine"]
