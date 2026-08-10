"""A36: score history (dm-hist-v1) — model/history.py's score_history()
generalizes M6 trend's own earlier/recent bucket machinery from 2 buckets
to N, reusing _bucket_score/_CohortCache verbatim. Two things are load-
bearing and tested directly: a 2-bucket run must reproduce _trend's own
two scores exactly (proof the generalization didn't drift), and a bucket
with no scorable evidence must render as a stated gap, never a guessed or
interpolated number (SPEC.md A36's binding rule)."""

from __future__ import annotations

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.history import SERIES_VERSION, score_history
from driverdna.model.scoring import SCORING_MODEL_VERSION, _bucket_score
from driverdna.model.taxonomy import FUNDAMENTALS, SignalStatus
from synth import one_corner_lap, ramp
from synth import run_synthetic_lap as _run

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}

_VARIED_PEAKS = [0.1, 0.3, 0.5, 0.7, 0.9]
_FLAT_PEAKS = [0.9, 0.9, 0.9, 0.9, 0.9]


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def run_synthetic_lap(db, lap, **kw):
    kw.setdefault("driver", COHORT["driver"])
    kw.setdefault("car", COHORT["car"])
    kw.setdefault("track", COHORT["track"])
    kw.setdefault("config", CONFIG)
    return _run(db, lap, **kw)


def _brake_peak_lap(i, peak):
    lap = one_corner_lap()
    lap.source_path = lap.source_path.with_name(f"hbp{i}.csv")
    lap.vert_accel[:] = 9.8 + i * 1e-6
    lap.brake[:] = 0.0
    ramp(lap.brake, 600, 630, 0.0, peak)
    lap.brake[630:690] = peak
    ramp(lap.brake, 690, 720, peak, 0.0)
    return lap


def _dated_brake_cohort(db, peaks, *, dated=True):
    for i, peak in enumerate(peaks):
        date = f"2026-01-{i + 1:02d}" if dated else None
        run_synthetic_lap(db, _brake_peak_lap(i, peak), session_key=f"s{i % 2}", lap_date=date)


def test_history_unavailable_without_enough_dated_laps(db):
    # 6 dated laps < history_buckets(6) x trend_min_laps_per_bucket(4) = 24.
    _dated_brake_cohort(db, [0.4, 0.5, 0.6, 0.7, 0.8, 0.8])
    result = score_history(db, driver="owner", config=CONFIG)
    assert result["series_version"] == SERIES_VERSION
    assert result["scoring_model_version"] == SCORING_MODEL_VERSION
    assert result["x_axis"]["kind"] == "unavailable"
    assert result["x_axis"]["labels"] == []
    assert result["series"] == {}
    assert result["caveats"]  # the two _trend limitations still travel with the payload


def test_history_two_buckets_reproduce_trend_exactly(db):
    # 11 dated laps (odd, like the owner's real 25) — proves the
    # generalized bucketer's odd-remainder convention matches _trend's own
    # (the extra lap goes to the LATER bucket), not just that the two
    # counts happen to agree on an even split.
    peaks = _VARIED_PEAKS + _FLAT_PEAKS + [0.5]
    _dated_brake_cohort(db, peaks)
    assert len(peaks) % 2 == 1

    two_bucket_config = CONFIG.model_copy(deep=True)
    two_bucket_config.model.history_buckets = 2
    two_bucket_config.model.trend_min_laps_per_bucket = 4  # 11 >= 2*4, available

    result = score_history(db, driver="owner", config=two_bucket_config)
    assert result["x_axis"]["kind"] == "date_bucket"
    assert result["x_axis"]["bucket_lap_counts"] == [5, 6]  # floor, then ceil — same as _trend

    dated = db.dated_self_lap_pks("owner")
    half = len(dated) // 2
    earlier, recent = frozenset(dated[:half]), frozenset(dated[half:])
    cohorts = [(COHORT["car"], COHORT["track"])]

    for fundamental_id, fundamental in FUNDAMENTALS.items():
        if fundamental.signal_status is SignalStatus.NO_SIGNAL:
            assert fundamental_id not in result["series"]
            continue
        expected_earlier = _bucket_score(
            db, "owner", fundamental_id, cohorts, two_bucket_config, earlier
        )
        expected_recent = _bucket_score(
            db, "owner", fundamental_id, cohorts, two_bucket_config, recent
        )
        points = result["series"][fundamental_id]["points"]
        assert points[0]["score"] == (
            None if expected_earlier is None else round(expected_earlier, 2)
        )
        assert points[1]["score"] == (
            None if expected_recent is None else round(expected_recent, 2)
        )


def test_history_bucket_with_no_evidence_is_a_stated_gap_not_interpolated(db):
    # A driver with dated braking evidence but nothing else: braking scores
    # every bucket; a fundamental with no matching evidence anywhere scores
    # None with a reason in every bucket, never a fabricated number.
    _dated_brake_cohort(db, [0.5] * 24)  # 24 = 6 buckets x 4 laps, exactly at the floor
    result = score_history(db, driver="owner", config=CONFIG)
    assert result["x_axis"]["kind"] == "date_bucket"
    assert len(result["x_axis"]["labels"]) == 6
    assert sum(result["x_axis"]["bucket_lap_counts"]) == 24

    braking_points = result["series"]["braking"]["points"]
    assert all(p["score"] is not None for p in braking_points)

    # vehicle_management's ABS-modulation detector never triggers on a lap
    # with no ABS activity in this fixture — insufficient evidence, stated.
    vm_points = result["series"]["vehicle_management"]["points"]
    for p in vm_points:
        if p["score"] is None:
            assert p["reason"] == "no scorable evidence in this bucket"


def test_history_is_deterministic(db):
    _dated_brake_cohort(db, _VARIED_PEAKS + _FLAT_PEAKS + [0.5])
    first = score_history(db, driver="owner", config=CONFIG)
    second = score_history(db, driver="owner", config=CONFIG)
    assert first == second


def _sse_payload(response):
    """Extract the 'complete' event's payload from an SSE response."""
    import json
    for frame in response.text.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        for line in frame.split("\n"):
            if line.startswith("data: "):
                event = json.loads(line[len("data: "):])
                if event.get("type") == "complete":
                    return event["payload"]
    return None


def test_score_history_endpoint_passes_through_unchanged(tmp_path):
    """UI-SPEC decision 2: payload endpoints are pass-throughs, no
    aggregation or recomputation in api.py. Uses a real file-backed DB
    (TestClient needs a db_path, unlike the in-memory fixture above)."""
    from fastapi.testclient import TestClient

    from driverdna.ui.api import create_app

    db_path = tmp_path / "history.db"
    config_path = tmp_path / "config.toml"
    with Database.open(db_path) as database:
        _dated_brake_cohort(database, _VARIED_PEAKS + _FLAT_PEAKS + [0.5])

    client = TestClient(create_app(db_path, config_path))
    response = client.get("/api/driver/score-history")
    assert response.status_code == 200
    payload = _sse_payload(response)
    assert payload is not None

    with Database.open(db_path) as database:
        expected = score_history(database, driver="owner", config=CONFIG)
    assert payload == expected


def test_score_history_endpoint_cold_start_matches_unavailable_shape(tmp_path):
    """No cohorts yet -> the same unavailable shape score_history() itself
    returns for too-few-dated-laps, not a distinct cold-start error the
    chart would need a second branch to handle."""
    from fastapi.testclient import TestClient

    from driverdna.ui.api import create_app

    db_path = tmp_path / "empty.db"
    with Database.open(db_path):
        pass  # migrate the schema, admit zero laps

    client = TestClient(create_app(db_path, tmp_path / "config.toml"))
    response = client.get("/api/driver/score-history")
    assert response.status_code == 200
    body = _sse_payload(response)
    assert body["x_axis"]["kind"] == "unavailable"
    assert body["series"] == {}
