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
# A second, genuinely different lap — content_hash dedup means two laps with
# identical telemetry collapse into one, so a "many laps per cohort" test
# needs real distinct traces, not the same fixture twice.
FIXTURE_CSV_2 = (Path(__file__).parent / "fixtures" / "Garage_61_HKWPXX.csv").read_bytes()

ME = {"id": "me-01", "slug": "owner"}
CAR = {"id": 8, "name": "Mazda MX-5"}
TRACK = {"id": 69, "name": "Laguna Seca", "variant": ""}
TRACK_VARIANT = {"id": 70, "name": "Spa", "variant": "Grand Prix"}


def _json(status: int, obj) -> tuple[int, bytes]:
    return status, json.dumps(obj).encode("utf-8")


def _lap(lap_id: str, *, driver_id: str = ME["id"], run: int = 0, session: int = 0,
         missing: bool = False, incomplete: bool = False, clean: bool = True,
         offtrack: bool = False, can_view_telemetry: bool | None = None,
         start: str = "2026-07-01T00:00:00Z") -> dict:
    lap = {
        "id": lap_id, "driver": {"id": driver_id}, "event": "ev-1",
        "session": session, "run": run, "startTime": start,
        "clean": clean, "missing": missing, "incomplete": incomplete,
        "offtrack": offtrack, "discontinuity": False, "pitlane": False,
    }
    if can_view_telemetry is not None:
        lap["canViewTelemetry"] = can_view_telemetry
    return lap


class FakeTransport:
    def __init__(self, *, statistics, cars, tracks, laps_by_track,
                 csv_by_id=None, csv_errors=None):
        self._statistics = statistics
        self._cars = cars
        self._tracks = tracks
        self._laps_by_track = laps_by_track
        self._csv_by_id = csv_by_id or {}
        self._csv_errors = csv_errors or {}
        self.csv_calls: list[str] = []
        self.lap_params: list[dict] = []

    def get(self, path, params):
        if path == "/laps":
            self.lap_params.append(dict(params))
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
            if lap_id in self._csv_errors:
                status = self._csv_errors[lap_id]
                return status, json.dumps({"error": f"status {status}"}).encode()
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
        {"car_id": 8, "track_id": 69, "car": "Mazda MX-5", "track": "Laguna Seca",
         "last_driven": ""}
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


def test_sync_imports_many_laps_from_one_cohort(db):
    """A28, the actual unlock: before `group=none`, `/laps` returned one
    personal-best lap per driver per cohort, so a cohort could never yield
    more than one lap through sync — which is why M6's per-cohort trend
    needed dated manual import. Two distinct laps in one cohort now both
    land."""
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 2}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [
            _lap("L1", start="2026-06-15T10:00:00Z"),
            _lap("L2", start="2026-06-15T10:02:00Z"),
        ]},
        csv_by_id={"L1": FIXTURE_CSV, "L2": FIXTURE_CSV_2},
    )
    client = Garage61Client(transport=transport)
    summaries = sync_driver(db, client, driver="owner", config=DriverDNAConfig())

    assert summaries[0].laps_seen == 2
    assert summaries[0].laps_new == 2
    dates = [
        r["lap_date"] for r in db.conn.execute(
            "SELECT lap_date FROM laps ORDER BY lap_date"
        ).fetchall()
    ]
    assert dates == ["2026-06-15T10:00:00Z", "2026-06-15T10:02:00Z"]


def test_sync_requests_unclean_laps_by_default_and_imports_them(db):
    """A19 is binding on the sync path too: an off is measured, not filtered.
    A lap the API flags unclean/offtrack is imported like any other."""
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [_lap("L-off", clean=False, offtrack=True)]},
    )
    client = Garage61Client(transport=transport)
    summaries = sync_driver(db, client, driver="owner", config=DriverDNAConfig())
    assert transport.lap_params[0]["unclean"] == "true"
    assert summaries[0].laps_new == 1
    assert transport.csv_calls == ["L-off"]


def test_sync_clean_only_asks_the_api_for_clean_laps(db):
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK], laps_by_track={69: [_lap("L1")]},
    )
    client = Garage61Client(transport=transport)
    sync_driver(db, client, driver="owner", config=DriverDNAConfig(), unclean=False)
    assert transport.lap_params[0]["unclean"] == "false"


def test_sync_passes_date_filters_through_to_the_api(db):
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK], laps_by_track={69: [_lap("L1")]},
    )
    client = Garage61Client(transport=transport)
    sync_driver(
        db, client, driver="owner", config=DriverDNAConfig(),
        after="2026-06-01T00:00:00Z", max_age_days=14,
    )
    assert transport.lap_params[0]["after"] == "2026-06-01T00:00:00Z"
    assert transport.lap_params[0]["age"] == 14


def test_sync_skips_laps_whose_telemetry_is_not_viewable(db):
    """`seeTelemetry` is documented as requiring a Pro plan, and each lap
    carries `canViewTelemetry`. A lap we cannot fetch is reported as such,
    never turned into a 403 storm and never silently dropped."""
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 2}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [
            _lap("L-ok", can_view_telemetry=True),
            _lap("L-locked", can_view_telemetry=False),
        ]},
    )
    client = Garage61Client(transport=transport)
    s = sync_driver(db, client, driver="owner", config=DriverDNAConfig())[0]
    assert s.laps_without_telemetry == 1
    assert ("L-locked", "telemetry not viewable") in s.laps_skipped
    assert transport.csv_calls == ["L-ok"]  # never spent a call we'd get 403 on


def test_sync_does_not_treat_a_missing_telemetry_flag_as_no_access(db):
    """Only an explicit `false` blocks a fetch — an absent field must not
    silently drop a lap that would have imported fine."""
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [_lap("L1")]},  # no canViewTelemetry key at all
    )
    client = Garage61Client(transport=transport)
    s = sync_driver(db, client, driver="owner", config=DriverDNAConfig())[0]
    assert s.laps_without_telemetry == 0
    assert s.laps_new == 1


def test_sync_reports_when_server_side_self_scoping_did_not_apply(db):
    """`drivers=me` is spec-sourced and never live-verified, and this API
    ignores query names it does not recognise. If other drivers' rows come
    back anyway, that is surfaced as a count rather than assumed away."""
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [_lap("L-mine"), _lap("L-other", driver_id="someone-else")]},
    )
    client = Garage61Client(transport=transport)
    s = sync_driver(db, client, driver="owner", config=DriverDNAConfig())[0]
    assert s.rows_scanned == 2
    assert s.foreign_rows == 1
    assert s.laps_seen == 1


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


def test_sync_skips_lap_on_csv_404_and_continues(db):
    """A30: on a free plan, non-PB laps listed by group=none may 404 on CSV
    fetch. Sync must skip and continue, not abort the whole cohort."""
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 3}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [
            _lap("L1", start="2026-06-15T10:00:00Z"),
            _lap("L-gone", start="2026-06-15T10:01:00Z"),
            _lap("L3", start="2026-06-15T10:02:00Z"),
        ]},
        csv_by_id={"L1": FIXTURE_CSV, "L3": FIXTURE_CSV_2},
        csv_errors={"L-gone": 404},
    )
    client = Garage61Client(transport=transport)
    summaries = sync_driver(db, client, driver="owner", config=DriverDNAConfig())
    s = summaries[0]
    assert s.laps_new == 2
    assert s.laps_csv_not_found == 1
    assert ("L-gone", "csv not found (404)") in s.laps_skipped
    assert set(transport.csv_calls) == {"L1", "L-gone", "L3"}


def test_sync_skips_lap_on_csv_403_and_continues(db):
    """A30: a 403 on CSV fetch (permission denied despite listing) is
    counted separately from 404 (telemetry absent)."""
    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 2}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [
            _lap("L-ok", start="2026-06-15T10:00:00Z"),
            _lap("L-denied", start="2026-06-15T10:01:00Z"),
        ]},
        csv_errors={"L-denied": 403},
    )
    client = Garage61Client(transport=transport)
    summaries = sync_driver(db, client, driver="owner", config=DriverDNAConfig())
    s = summaries[0]
    assert s.laps_new == 1
    assert s.laps_csv_forbidden == 1
    assert ("L-denied", "csv forbidden (403)") in s.laps_skipped


def test_sync_auth_error_still_aborts(db):
    """401 and 500 must propagate — the guard catches only 404/403."""
    from driverdna.garage61.client import Garage61AuthError

    transport = FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 1}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [_lap("L1")]},
        csv_errors={"L1": 401},
    )
    client = Garage61Client(transport=transport)
    with pytest.raises(Garage61AuthError):
        sync_driver(db, client, driver="owner", config=DriverDNAConfig())


# ---------------------------------------------------------------------------
# Cohort cap + newest-first ordering (SPEC.md A49)
# ---------------------------------------------------------------------------

CARS_MANY = [CAR, {"id": 9, "name": "Porsche 911"}]
TRACKS_MANY = [TRACK, TRACK_VARIANT, {"id": 71, "name": "Okayama", "variant": ""}]


def _cfg(**sync_kwargs) -> DriverDNAConfig:
    return DriverDNAConfig.model_validate({"sync": sync_kwargs})


def test_sync_max_cohorts_default_is_40():
    """SPEC.md A53 (adopted 2026-08-18, applied here): the default was
    raised from 10 to 40 because a veteran with 25-40 accumulated cohorts
    hit the cap on day one, and an older cohort past the window does not
    sync unless re-driven (A49 skips it by name, does not backfill).
    Pinned so a future change is deliberate — this is not a threshold
    that should drift silently. Not a model version bump: SyncConfig is
    ingest scope and says so."""
    assert DriverDNAConfig().sync.max_cohorts == 40


def test_discover_cohorts_orders_newest_driven_first():
    """The cap takes a prefix of this list, so the order is load-bearing."""
    transport = FakeTransport(
        statistics=[
            {"car": 8, "track": 69, "lapsDriven": 2, "day": "2026-01-05"},
            {"car": 9, "track": 71, "lapsDriven": 2, "day": "2026-07-30"},
            {"car": 8, "track": 70, "lapsDriven": 2, "day": "2026-03-14"},
        ],
        cars=CARS_MANY, tracks=TRACKS_MANY, laps_by_track={},
    )
    cohorts = discover_cohorts(Garage61Client(transport=transport))
    assert [(c["car"], c["track"]) for c in cohorts] == [
        ("Porsche 911", "Okayama"),
        ("Mazda MX-5", "Spa (Grand Prix)"),
        ("Mazda MX-5", "Laguna Seca"),
    ]


def test_discover_cohorts_last_driven_is_the_newest_day_across_rows():
    """/me/statistics is per (day, car, track, sessionType) — one cohort spans
    many rows, and the newest of them is what orders it."""
    transport = FakeTransport(
        statistics=[
            {"car": 8, "track": 69, "lapsDriven": 1, "day": "2026-01-05"},
            {"car": 8, "track": 69, "lapsDriven": 1, "day": "2026-06-20"},
            {"car": 8, "track": 69, "lapsDriven": 1, "day": "2026-02-11"},
        ],
        cars=CARS_MANY, tracks=TRACKS_MANY, laps_by_track={},
    )
    cohorts = discover_cohorts(Garage61Client(transport=transport))
    assert cohorts[0]["last_driven"] == "2026-06-20"


def test_discover_cohorts_ties_stay_alphabetical():
    """Guards the two-pass stable sort: a single reverse=True over a
    (day, car, track) tuple would flip same-day cohorts to Z->A."""
    transport = FakeTransport(
        statistics=[
            {"car": 9, "track": 71, "lapsDriven": 1, "day": "2026-05-01"},
            {"car": 8, "track": 69, "lapsDriven": 1, "day": "2026-05-01"},
        ],
        cars=CARS_MANY, tracks=TRACKS_MANY, laps_by_track={},
    )
    cohorts = discover_cohorts(Garage61Client(transport=transport))
    assert [c["car"] for c in cohorts] == ["Mazda MX-5", "Porsche 911"]


def _three_cohort_transport() -> FakeTransport:
    return FakeTransport(
        statistics=[
            {"car": 8, "track": 69, "lapsDriven": 1, "day": "2026-01-05"},
            {"car": 9, "track": 71, "lapsDriven": 1, "day": "2026-07-30"},
            {"car": 8, "track": 70, "lapsDriven": 1, "day": "2026-03-14"},
        ],
        cars=CARS_MANY, tracks=TRACKS_MANY,
        laps_by_track={
            69: [_lap("L-old")],
            70: [_lap("L-mid")],
            71: [_lap("L-new")],
        },
        csv_by_id={"L-old": FIXTURE_CSV, "L-mid": FIXTURE_CSV_2, "L-new": FIXTURE_CSV},
    )


def test_max_cohorts_syncs_only_the_most_recent(db):
    client = Garage61Client(transport=_three_cohort_transport())
    summaries = sync_driver(db, client, driver="owner", config=_cfg(max_cohorts=1))
    assert [(s.car, s.track) for s in summaries] == [("Porsche 911", "Okayama")]


def test_max_cohorts_reports_the_skipped_ones_by_name_and_date(db):
    """Counted is not enough: the ordering rests on the API's `day`, whose
    format is unverified, so a wrong order has to be visible."""
    events: list[dict] = []
    client = Garage61Client(transport=_three_cohort_transport())
    sync_driver(db, client, driver="owner", config=_cfg(max_cohorts=1),
                on_progress=events.append)
    discovering = next(e for e in events if e["type"] == "discovering")
    assert discovering["cohorts"] == 1
    assert discovering["cohorts_total"] == 3
    assert discovering["cohorts_skipped"] == [
        {"car": "Mazda MX-5", "track": "Spa (Grand Prix)", "last_driven": "2026-03-14"},
        {"car": "Mazda MX-5", "track": "Laguna Seca", "last_driven": "2026-01-05"},
    ]


def test_max_cohorts_zero_syncs_everything(db):
    client = Garage61Client(transport=_three_cohort_transport())
    summaries = sync_driver(db, client, driver="owner", config=_cfg(max_cohorts=0))
    assert len(summaries) == 3


def test_max_cohorts_never_overrides_an_explicit_car_track_filter(db):
    """The cap runs after --car/--track, so an explicitly requested cohort is
    never capped out from under the driver."""
    client = Garage61Client(transport=_three_cohort_transport())
    summaries = sync_driver(
        db, client, driver="owner", config=_cfg(max_cohorts=1),
        car="Mazda MX-5", track="Laguna Seca",
    )
    assert [(s.car, s.track) for s in summaries] == [("Mazda MX-5", "Laguna Seca")]


def test_cap_is_refused_when_no_cohort_carries_a_date(db):
    """Without `day` the order is arbitrary, so capping would shed cohorts at
    random — insufficient data over guessing."""
    transport = FakeTransport(
        statistics=[
            {"car": 8, "track": 69, "lapsDriven": 1},
            {"car": 9, "track": 71, "lapsDriven": 1},
            {"car": 8, "track": 70, "lapsDriven": 1},
        ],
        cars=CARS_MANY, tracks=TRACKS_MANY,
        laps_by_track={
            69: [_lap("L-a")], 70: [_lap("L-b")], 71: [_lap("L-c")],
        },
        csv_by_id={"L-a": FIXTURE_CSV, "L-b": FIXTURE_CSV_2, "L-c": FIXTURE_CSV},
    )
    events: list[dict] = []
    summaries = sync_driver(db, Garage61Client(transport=transport), driver="owner",
                            config=_cfg(max_cohorts=1), on_progress=events.append)
    assert len(summaries) == 3
    assert next(e for e in events if e["type"] == "discovering")["cohorts_skipped"] == []


# ---------------------------------------------------------------------------
# Pit-lane laps: counted always, skipped only on request
# ---------------------------------------------------------------------------

def _pitlane_transport() -> FakeTransport:
    pit = _lap("L-pit")
    pit["pitlane"] = True
    return FakeTransport(
        statistics=[{"car": 8, "track": 69, "lapsDriven": 2, "day": "2026-05-01"}],
        cars=[CAR], tracks=[TRACK],
        laps_by_track={69: [pit, _lap("L-clean")]},
        csv_by_id={"L-pit": FIXTURE_CSV, "L-clean": FIXTURE_CSV_2},
    )


def test_pitlane_laps_are_counted_but_imported_by_default(db):
    """Default off: the field's meaning is unverified, so sync measures how
    often it would have fired rather than dropping laps on a guess."""
    transport = _pitlane_transport()
    s = sync_driver(db, Garage61Client(transport=transport), driver="owner",
                    config=DriverDNAConfig())[0]
    assert s.laps_pitlane == 1
    assert s.laps_new == 2
    assert "L-pit" in transport.csv_calls
    assert not any(reason == "pit-lane start" for _, reason in s.laps_skipped)


def test_pitlane_laps_are_skipped_before_any_fetch_when_enabled(db):
    transport = _pitlane_transport()
    s = sync_driver(db, Garage61Client(transport=transport), driver="owner",
                    config=_cfg(skip_pitlane_laps=True))[0]
    assert s.laps_pitlane == 1
    assert s.laps_new == 1
    assert ("L-pit", "pit-lane start") in s.laps_skipped
    assert "L-pit" not in transport.csv_calls


def test_sync_driver_cleans_up_memory_between_cohorts(db, monkeypatch):
    """Memory guard (BUG-037): sync_driver triggers explicit garbage collection
    at the end of each cohort to prevent memory exhaustion on constrained hosts."""
    import gc
    gc_calls = 0
    real_collect = gc.collect

    def _mock_collect(*args, **kwargs):
        nonlocal gc_calls
        gc_calls += 1
        return real_collect(*args, **kwargs)

    monkeypatch.setattr(gc, "collect", _mock_collect)

    client = Garage61Client(transport=_three_cohort_transport())
    summaries = sync_driver(db, client, driver="owner", config=_cfg(max_cohorts=3))
    assert len(summaries) == 3
    # Called at least once per cohort
    assert gc_calls >= 3

