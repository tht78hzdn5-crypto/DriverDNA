"""U6 (cockpit actions) write-path tests for `POST /api/sync` and
`POST /api/cohorts/{slug}/rebuild-map` (UI-SPEC decision 3 + U6 conditions of
done): both wrap existing audited paths (`sync_driver`, `rebuild_cohort_map`)
with no business logic of their own, so their DB effects must be identical to
the CLI equivalents (`driverdna sync` / `driverdna rebuild-map`) on an
equivalent starting DB -- the same shape `tests/test_upload_api.py` uses for
`/api/laps/upload`. The sync parity test drives a mocked `Garage61Client`
(canned lap listing + CSV bytes) on both sides -- never a live API, never a
real token.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.blobs import default_blob_root
from driverdna.cli import app as cli_app
from driverdna.db import Database
from driverdna.garage61.client import Garage61Client
from driverdna.report.payload import cohort_slug
from driverdna.ui.api import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
ONE_LAP = FIXTURES_DIR / "Garage_61_HKWPXX.csv"  # GR86 @ Spa-Francorchamps
SPA_SLUG = cohort_slug("GR86", "Spa-Francorchamps")

ME = {"id": "me-01", "slug": "owner"}
CAR = {"id": 8, "name": "GR86"}
TRACK = {"id": 69, "name": "Spa-Francorchamps", "variant": ""}


def _parse_sse(response):
    """Parse an SSE response into a list of event dicts."""
    events = []
    for frame in response.text.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        for line in frame.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
    return events


def _sse_complete(response):
    """Parse SSE and return the terminal 'complete' event."""
    events = _parse_sse(response)
    complete = [e for e in events if e["type"] == "complete"]
    assert len(complete) == 1, f"expected 1 complete event, got {len(complete)}"
    return complete[0]


def _resp(status: int, obj) -> tuple[int, bytes]:
    return status, json.dumps(obj).encode("utf-8")


def _lap_item(lap_id: str, *, run: int = 0, session: int = 0,
              start: str = "2026-07-01T00:00:00Z") -> dict:
    return {
        "id": lap_id, "driver": {"id": ME["id"]}, "event": "ev-1",
        "session": session, "run": run, "startTime": start,
        "clean": True, "missing": False, "incomplete": False,
        "offtrack": False, "discontinuity": False, "pitlane": False,
    }


class FakeTransport:
    """Mirrors test_garage61_sync.py's fake transport -- canned data only,
    never the live API. One (car, track) cohort is enough for these tests;
    the underlying sync_driver/discover_cohorts behavior is already covered
    by test_garage61_sync.py, so this only needs to exercise the wiring."""

    def __init__(self, *, laps: list[dict], csv_bytes: bytes):
        self._laps = laps
        self._csv_bytes = csv_bytes
        self.csv_calls: list[str] = []

    def get(self, path: str, params):
        if path == "/me":
            return _resp(200, ME)
        if path == "/me/statistics":
            return _resp(200, {"drivingStatistics": [
                {"car": 8, "track": 69, "lapsDriven": len(self._laps)}
            ]})
        if path == "/cars":
            return _resp(200, {"items": [CAR]})
        if path == "/tracks":
            return _resp(200, {"items": [TRACK]})
        if path == "/laps":
            return _resp(200, {"items": self._laps, "total": len(self._laps)})
        if path.endswith("/csv"):
            self.csv_calls.append(path.split("/")[2])
            return 200, self._csv_bytes
        raise AssertionError(f"unexpected path {path}")


def _mock_garage61_client(monkeypatch: pytest.MonkeyPatch, transport: FakeTransport) -> None:
    """Both `driverdna sync` and `POST /api/sync` construct `Garage61Client()`
    with no arguments straight from `driverdna.garage61.client` (a lazy
    import, done fresh per call) -- there is deliberately no DI seam in
    api.py for this (UI-SPEC U6 condition 1: the endpoint never reads a
    token from the request). Patching the class where it's defined redirects
    both call sites at once, through the exact `transport=` seam
    `Garage61Client` documents itself for testing -- never the live API."""
    monkeypatch.setattr(
        "driverdna.garage61.client.Garage61Client",
        lambda *a, **k: Garage61Client(transport=transport),
    )


def _fresh_db(path: Path) -> None:
    with Database.open(path):
        pass  # migrated, empty -- sync (like every write endpoint but upload) requires one to exist


# --- POST /api/sync -----------------------------------------------------


def test_sync_missing_token_returns_directive_error_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    db_path = tmp_path / "sync.db"
    app = create_app(db_path, tmp_path / "cfg.toml")

    r = TestClient(app).post("/api/sync")

    assert 400 <= r.status_code < 500
    assert "GARAGE61_TOKEN" in r.json()["detail"]
    assert not db_path.exists()  # never opened -- the client is built before any DB access


def test_sync_missing_token_ignores_a_car_track_body_too(tmp_path, monkeypatch):
    """The token is never read from the request under any body shape."""
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    db_path = tmp_path / "sync.db"
    app = create_app(db_path, tmp_path / "cfg.toml")

    r = TestClient(app).post("/api/sync", json={"car": "GR86", "track": "Spa-Francorchamps"})

    assert 400 <= r.status_code < 500
    assert not db_path.exists()


def test_sync_requires_an_existing_db_like_every_other_write_endpoint(tmp_path, monkeypatch):
    _mock_garage61_client(monkeypatch, FakeTransport(laps=[_lap_item("L1")], csv_bytes=b""))
    db_path = tmp_path / "sync.db"
    app = create_app(db_path, tmp_path / "cfg.toml")

    r = TestClient(app).post("/api/sync")

    assert r.status_code == 404
    assert "no DB at" in r.json()["detail"]


def test_sync_car_track_body_scopes_discovery(tmp_path, monkeypatch):
    """Optional body {car?, track?} (U6 condition 1) reaches sync_driver's
    own filters -- proven by restricting to a cohort absent from the canned
    data, same effect as the CLI's --car/--track flags."""
    _mock_garage61_client(monkeypatch, FakeTransport(laps=[_lap_item("L1")], csv_bytes=ONE_LAP.read_bytes()))
    db_path = tmp_path / "sync.db"
    _fresh_db(db_path)
    app = create_app(db_path, tmp_path / "cfg.toml")

    r = TestClient(app).post("/api/sync", json={"car": "Nope"})

    assert r.status_code == 200
    complete = _sse_complete(r)
    assert complete["results"] == []
    with Database.open(db_path) as db:
        assert db.conn.execute("SELECT COUNT(*) n FROM laps").fetchone()["n"] == 0


def test_sync_effects_identical_to_cli_sync(tmp_path, monkeypatch):
    """The decision-3 / condition-3 requirement: the same canned Garage61
    listing, synced via the API vs the CLI to independent fresh DBs, produces
    byte-identical lap rows, corner-observation counts, and sync-state rows
    (timestamps excluded, same as test_upload_api's own `imported_at`
    exclusion -- those are wall-clock, never asserted equal)."""
    _mock_garage61_client(
        monkeypatch,
        FakeTransport(laps=[_lap_item("L1", run=3, session=2)], csv_bytes=ONE_LAP.read_bytes()),
    )

    api_db = tmp_path / "api.db"
    _fresh_db(api_db)
    app = create_app(api_db, tmp_path / "api-cfg.toml")
    r = TestClient(app).post("/api/sync")
    assert r.status_code == 200
    complete = _sse_complete(r)
    assert complete["results"] == [{
        "car": "GR86", "track": "Spa-Francorchamps",
        "laps_seen": 1, "laps_new": 1, "laps_pitlane": 0, "laps_skipped": [],
        "results": [{"lap_pk": 1, "status": "imported", "admitted": [], "class_changes": []}],
    }]

    cli_db = tmp_path / "cli.db"
    _fresh_db(cli_db)
    result = CliRunner().invoke(cli_app, ["sync", "--db", str(cli_db)])
    assert result.exit_code == 0, result.output

    def snapshot(db_path):
        with Database.open(db_path) as db:
            lap = dict(db.conn.execute(
                """SELECT car, track, role, session_key, run_index, lap_date,
                          n_samples, duration_s, quality_flags FROM laps"""
            ).fetchone())
            obs = db.conn.execute("SELECT COUNT(*) n FROM corner_observations").fetchone()["n"]
            sync_state = [
                dict(row) for row in db.conn.execute(
                    """SELECT driver, car, track, laps_seen, laps_new
                       FROM garage61_sync_state"""
                )
            ]
            return lap, obs, sync_state

    assert snapshot(api_db) == snapshot(cli_db)


def test_sync_never_refetches_a_lap_already_synced(tmp_path, monkeypatch):
    """Idempotency (garage61/sync.py's own dedup) survives the HTTP wrapper:
    a second call sees the lap but imports nothing new."""
    transport = FakeTransport(laps=[_lap_item("L1")], csv_bytes=ONE_LAP.read_bytes())
    _mock_garage61_client(monkeypatch, transport)
    db_path = tmp_path / "sync.db"
    _fresh_db(db_path)
    app = create_app(db_path, tmp_path / "cfg.toml")
    client = TestClient(app)

    first = _sse_complete(client.post("/api/sync"))
    assert first["results"][0]["laps_new"] == 1
    second = _sse_complete(client.post("/api/sync"))

    assert second["results"][0] == {
        "car": "GR86", "track": "Spa-Francorchamps",
        "laps_seen": 1, "laps_new": 0, "laps_pitlane": 0,
        "laps_skipped": [], "results": [],
    }
    assert transport.csv_calls == ["L1"]  # never re-fetched
    with Database.open(db_path) as db:
        assert db.conn.execute("SELECT COUNT(*) n FROM laps").fetchone()["n"] == 1


def test_sync_emits_progress_events(tmp_path, monkeypatch):
    """Sync streams per-cohort progress before the terminal complete event."""
    _mock_garage61_client(
        monkeypatch,
        FakeTransport(laps=[_lap_item("L1")], csv_bytes=ONE_LAP.read_bytes()),
    )
    db_path = tmp_path / "sync.db"
    _fresh_db(db_path)
    app = create_app(db_path, tmp_path / "cfg.toml")

    r = TestClient(app).post("/api/sync")
    events = _parse_sse(r)
    types = [e["type"] for e in events]
    assert "discovering" in types
    assert "cohort_start" in types
    assert "cohort_done" in types
    assert types[-1] == "complete"


# --- POST /api/cohorts/{slug}/rebuild-map --------------------------------


def test_rebuild_map_unknown_cohort_404s(tmp_path):
    db_path = tmp_path / "rb.db"
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    app = create_app(db_path, tmp_path / "cfg.toml")

    r = TestClient(app).post("/api/cohorts/no-such-cohort/rebuild-map")

    assert r.status_code == 404
    assert "unknown cohort" in r.json()["detail"]


def test_rebuild_map_known_cohort_without_a_frozen_map_404s(tmp_path):
    """A cohort can resolve (it has a self lap row) yet have no corner_maps
    row -- condition 2's 404 branch, distinct from the unknown-slug branch
    above. Inserted directly rather than through the pipeline so the map is
    genuinely absent instead of merely small."""
    db_path = tmp_path / "rb.db"
    with Database.open(db_path) as db:
        db.conn.execute(
            """INSERT INTO laps (lap_id, source_file, driver, car, track, role,
                                  n_samples, duration_s, quality_flags, owner_user_pk)
               VALUES ('X1', 'x1.csv', 'owner', 'Ghost', 'NoMap', 'self', 10, 90.0, '[]', ?)""",
            (db.user_pk,)
        )
        db.conn.commit()
    app = create_app(db_path, tmp_path / "cfg.toml")
    slug = cohort_slug("Ghost", "NoMap")

    r = TestClient(app).post(f"/api/cohorts/{slug}/rebuild-map")

    assert r.status_code == 404
    assert "nothing to rebuild" in r.json()["detail"]


def test_rebuild_map_effects_identical_to_cli(tmp_path):
    """Condition 3's binding rebuild-map requirement: endpoint vs CLI on two
    copies of one real fixture cohort produce identical corners /
    corner_windows / phase_times rows."""
    source_db = tmp_path / "source.db"
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(source_db)])
    assert result.exit_code == 0, result.output

    api_db = tmp_path / "api.db"
    cli_db = tmp_path / "cli.db"
    shutil.copy(source_db, api_db)
    shutil.copy(source_db, cli_db)
    # A23 moved raw blobs from inside SQLite to <db>.blobs/ on disk
    source_blobs = Path(default_blob_root(source_db))
    if source_blobs.is_dir():
        shutil.copytree(source_blobs, Path(default_blob_root(api_db)))
        shutil.copytree(source_blobs, Path(default_blob_root(cli_db)))

    app = create_app(api_db, tmp_path / "api-cfg.toml")
    r = TestClient(app).post(f"/api/cohorts/{SPA_SLUG}/rebuild-map")
    assert r.status_code == 200
    body = r.json()
    assert body["car"] == "GR86" and body["track"] == "Spa-Francorchamps"
    assert {c["corner_id"] for c in body["corners"]}
    assert body["total_cleared"] == 0  # fixtures are well under the retention keep count

    result = CliRunner().invoke(
        cli_app,
        ["rebuild-map", "--car", "GR86", "--track", "Spa-Francorchamps", "--db", str(cli_db)],
    )
    assert result.exit_code == 0, result.output

    def snapshot(db_path):
        with Database.open(db_path) as db:
            map_pk, _ = db.load_corner_map(car="GR86", track="Spa-Francorchamps")
            corners = [
                dict(row) for row in db.conn.execute(
                    """SELECT corner_id, lat, lon, lap_dist, class FROM corners
                       WHERE map_pk=? ORDER BY corner_id""",
                    (map_pk,),
                )
            ]
            windows = db.load_corner_windows(map_pk)
            phase_times = [
                dict(row) for row in db.conn.execute(
                    """SELECT o.lap_pk, o.corner_pk, p.phase, p.time_s
                       FROM phase_times p JOIN corner_observations o ON o.obs_pk = p.obs_pk
                       ORDER BY o.lap_pk, o.corner_pk, p.phase"""
                )
            ]
            return corners, windows, phase_times

    assert snapshot(api_db) == snapshot(cli_db)


def test_rebuild_map_response_includes_cleared_stale_phase_notice(tmp_path):
    """The UI's cleared-stale-phase notice needs `total_cleared` and each
    corner's `laps_cleared` populated when a raw blob has been evicted past
    retention -- forced here the same way test_rebuild_map.py's own
    `test_rebuild_clears_and_reports_phase_times_when_blob_evicted` does."""
    from synth import CORNER_WINDOWS, run_synthetic_lap, track_lap

    from driverdna.config import DriverDNAConfig

    db_path = tmp_path / "synth.db"
    with Database.open(db_path) as db:
        for i in range(5):
            run_synthetic_lap(
                db, track_lap(src=f"lap{i}.csv"), config=DriverDNAConfig(),
                driver="owner", car="TestCar", track="SynthRing",
            )
        evicted = db.enforce_retention(keep=2)
        assert evicted == 3
        db.conn.commit()

    slug = cohort_slug("TestCar", "SynthRing")
    app = create_app(db_path, tmp_path / "cfg.toml")
    r = TestClient(app).post(f"/api/cohorts/{slug}/rebuild-map")

    assert r.status_code == 200
    body = r.json()
    # 3 evicted laps x 3 corners each observed at -- total_cleared is a
    # phase-time-record count (matches RebuildResult.total_cleared exactly,
    # not deduplicated by lap); the set of cleared lap_pks is the 3 laps.
    assert len(CORNER_WINDOWS) == len(body["corners"])
    assert body["total_cleared"] == 3 * len(CORNER_WINDOWS)
    cleared_lap_pks = {pk for c in body["corners"] for pk in c["laps_cleared"]}
    assert len(cleared_lap_pks) == 3


# --- GET /api/driver/summary -----------------------------------------------


def test_driver_summary_returns_counts_without_engine_computation(tmp_path):
    """The summary endpoint returns cohort/lap counts from cheap DB queries,
    not the full engine pipeline."""
    db_path = tmp_path / "summary.db"
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    app = create_app(db_path, tmp_path / "cfg.toml")
    client = TestClient(app)

    r = client.get("/api/driver/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["n_cohorts"] == 2
    assert body["n_self_laps"] > 0
    assert isinstance(body["cohorts"], list)
    assert len(body["cohorts"]) == 2
    for c in body["cohorts"]:
        assert "car" in c and "track" in c and "n_laps" in c


def test_driver_summary_404s_without_a_db(tmp_path):
    app = create_app(tmp_path / "nope.db", tmp_path / "cfg.toml")
    r = TestClient(app).get("/api/driver/summary")
    assert r.status_code == 404


# --- GET /api/driver (SSE) --------------------------------------------------


def test_driver_sse_streams_progress_then_complete(tmp_path):
    """The SSE driver endpoint emits progress events per cohort then a
    terminal complete event with the full payload."""
    db_path = tmp_path / "sse.db"
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    app = create_app(db_path, tmp_path / "cfg.toml")
    client = TestClient(app)

    r = client.get("/api/driver")
    assert r.status_code == 200
    events = _parse_sse(r)
    types = [e["type"] for e in events]
    assert "progress" in types
    assert types[-1] == "complete"
    payload = events[-1]["payload"]
    assert "cross_track_rollups" in payload
    assert "driver_model" in payload


# --- GET /api/cohorts (enriched) --------------------------------------------


def test_cohorts_include_lap_counts_and_sync_dates(tmp_path):
    """The enriched /api/cohorts response includes n_laps, n_reference_laps,
    and last_synced_at per cohort."""
    db_path = tmp_path / "enriched.db"
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    app = create_app(db_path, tmp_path / "cfg.toml")
    client = TestClient(app)

    r = client.get("/api/cohorts")
    assert r.status_code == 200
    cohorts = r.json()
    assert len(cohorts) == 2
    for c in cohorts:
        assert "n_laps" in c
        assert "n_reference_laps" in c
        assert "last_synced_at" in c
        assert c["n_laps"] > 0


# --- cohort cap surfaces through the sync SSE stream (SPEC.md A49) --------

TWO_LAP = FIXTURES_DIR / "Garage_61_RH11X7.csv"
CAR_B = {"id": 9, "name": "Mustang GT4"}
TRACK_B = {"id": 71, "name": "Okayama", "variant": ""}


class MultiCohortTransport:
    """Two cohorts with different last-driven dates, so the cap has something
    to shed. Separate from FakeTransport above, which is deliberately
    single-cohort -- the cap's own logic is covered in test_garage61_sync.py;
    this only proves it reaches the stream."""

    def __init__(self) -> None:
        self.csv_calls: list[str] = []

    def get(self, path: str, params):
        if path == "/me":
            return _resp(200, ME)
        if path == "/me/statistics":
            return _resp(200, {"drivingStatistics": [
                {"car": 8, "track": 69, "lapsDriven": 1, "day": "2026-01-05"},
                {"car": 9, "track": 71, "lapsDriven": 1, "day": "2026-07-30"},
            ]})
        if path == "/cars":
            return _resp(200, {"items": [CAR, CAR_B]})
        if path == "/tracks":
            return _resp(200, {"items": [TRACK, TRACK_B]})
        if path == "/laps":
            lap_id = "L-spa" if params["tracks"] == 69 else "L-oka"
            return _resp(200, {"items": [_lap_item(lap_id)], "total": 1})
        if path.endswith("/csv"):
            lap_id = path.split("/")[2]
            self.csv_calls.append(lap_id)
            return 200, (ONE_LAP if lap_id == "L-spa" else TWO_LAP).read_bytes()
        raise AssertionError(f"unexpected path {path}")


def test_sync_complete_event_names_the_cohorts_the_cap_skipped(tmp_path, monkeypatch):
    """The driver has to be able to see which cohorts went unsynced, and when
    each was last driven -- a silent cap would hide a wrong ordering."""
    transport = MultiCohortTransport()
    _mock_garage61_client(monkeypatch, transport)
    db_path = tmp_path / "sync.db"
    _fresh_db(db_path)
    (tmp_path / "cfg.toml").write_text("[sync]\nmax_cohorts = 1\n")
    app = create_app(db_path, tmp_path / "cfg.toml")

    complete = _sse_complete(TestClient(app).post("/api/sync"))

    assert complete["cohorts_total"] == 2
    assert complete["max_cohorts"] == 1
    assert complete["cohorts_skipped"] == [
        {"car": "GR86", "track": "Spa-Francorchamps", "last_driven": "2026-01-05"}
    ]
    # Newest-first: only Okayama synced, and Spa never cost a CSV fetch.
    assert [r["car"] for r in complete["results"]] == ["Mustang GT4"]
    assert transport.csv_calls == ["L-oka"]


def test_sync_complete_event_reports_no_skips_when_under_the_cap(tmp_path, monkeypatch):
    _mock_garage61_client(
        monkeypatch,
        FakeTransport(laps=[_lap_item("L1")], csv_bytes=ONE_LAP.read_bytes()),
    )
    db_path = tmp_path / "sync.db"
    _fresh_db(db_path)
    app = create_app(db_path, tmp_path / "cfg.toml")

    complete = _sse_complete(TestClient(app).post("/api/sync"))

    assert complete["cohorts_skipped"] == []
    assert complete["cohorts_total"] == 1


def test_sync_results_carry_the_pitlane_count(tmp_path, monkeypatch):
    """Counted whether or not it was skipped -- with skip_pitlane_laps off by
    default this is the evidence for deciding whether skipping is right."""
    pit = _lap_item("L1")
    pit["pitlane"] = True
    _mock_garage61_client(
        monkeypatch, FakeTransport(laps=[pit], csv_bytes=ONE_LAP.read_bytes())
    )
    db_path = tmp_path / "sync.db"
    _fresh_db(db_path)
    app = create_app(db_path, tmp_path / "cfg.toml")

    complete = _sse_complete(TestClient(app).post("/api/sync"))

    assert complete["results"][0]["laps_pitlane"] == 1
    assert complete["results"][0]["laps_new"] == 1  # counted, not dropped
