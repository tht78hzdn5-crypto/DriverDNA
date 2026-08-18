"""A51: the driver-level coaching rollup.

Coaching was computed per (car, track) and had no driver-level form at all,
so the page a driver opens first — driver home — carried no coaching content
whatever. The organising idea here: a principle that fires at more than one
TRACK is the driver, not the track.

The rules under test are the ones that keep the aggregate honest:

  1. the cross-track gate is the existing `min_tracks_for_rollup`, reused,
     not a second threshold with its own opinion;
  2. below the gate a pattern is listed and suppressed WITH its reason,
     exactly like `cross_track_rollups` — never dropped;
  3. magnitudes are NEVER combined across cohorts. Seconds, trigger rates
     and CVs are different units, and a "total" over them would be a number
     the engine invented.
"""

import pytest

from driverdna.coaching.rollup import build_coaching_rollup
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()


@pytest.fixture()
def demo():
    """One driver, one car, TWO tracks — the minimum shape in which "is this
    the driver or the track?" is even a question.

    Built from synth rather than a machine-local database so the suite stays
    runnable on a bare `git clone` (AGENTS.md's testing rules). The second
    track gets a distinct lap mix, so some principles fire at both tracks
    (cross-track, shown) and some at one only (suppressed, with reason).
    """
    db = Database.open(":memory:")
    try:
        for track, n_slow in (("TrackA", 6), ("TrackB", 3)):
            for i in range(6):
                run_synthetic_lap(
                    db, track_lap(src=f"{track}-fast{i}.csv"),
                    driver="owner", car="TestCar", track=track,
                    session_key=f"s{i % 2 + 1}", config=CONFIG,
                )
            for i in range(n_slow):
                lap = warp_time(track_lap(src=f"{track}-slow{i}.csv"), (0.19, 0.22), 0.4)
                run_synthetic_lap(
                    db, lap, driver="owner", car="TestCar", track=track,
                    session_key=f"s{i % 2 + 1}", config=CONFIG,
                )
        yield db
    finally:
        db.close()


def test_rollup_reports_patterns_and_states_the_gate(demo):
    r = build_coaching_rollup(demo, driver="owner", config=CONFIG)
    assert r["min_tracks"] == CONFIG.gates.min_tracks_for_rollup
    assert r["patterns"], "no coaching patterns aggregated at all"


def test_a_single_track_pattern_is_suppressed_with_its_reason(demo):
    """Not dropped — the same discipline `cross_track_rollups` follows."""
    r = build_coaching_rollup(demo, driver="owner", config=CONFIG)
    suppressed = [p for p in r["patterns"] if not p["shown"]]
    assert suppressed, "expected at least one single-track pattern here"
    for p in suppressed:
        assert p["gate_reason"]
        assert str(p["n_tracks"]) in p["gate_reason"]


def test_no_magnitude_is_ever_summed_across_cohorts(demo):
    """Each instance keeps its own corner, magnitude and unit. A combined
    figure over seconds + CV + trigger rate would be meaningless AND would be
    the engine inventing a measurement."""
    r = build_coaching_rollup(demo, driver="owner", config=CONFIG)
    for p in r["patterns"]:
        assert "total" not in p and "sum" not in p
        for inst in p["instances"]:
            assert {"car", "track", "corner_id"} <= set(inst)


def test_shown_patterns_clear_the_track_gate(demo):
    r = build_coaching_rollup(demo, driver="owner", config=CONFIG)
    for p in r["patterns"]:
        if p["shown"]:
            assert p["n_tracks"] >= CONFIG.gates.min_tracks_for_rollup
            assert p["gate_reason"] is None


def test_rollup_is_deterministic(demo):
    a = build_coaching_rollup(demo, driver="owner", config=CONFIG)
    b = build_coaching_rollup(demo, driver="owner", config=CONFIG)
    assert a == b


def test_patterns_rank_by_breadth_then_id(demo):
    r = build_coaching_rollup(demo, driver="owner", config=CONFIG)
    keys = [(-p["n_tracks"], -p["n_cohorts"], p["coaching_principle_id"])
            for p in r["patterns"] if p["shown"]]
    assert keys == sorted(keys)


def test_strengths_roll_up_the_same_way(demo):
    """A principle held across several tracks is a durable strength, gated
    the same way a fault pattern is."""
    r = build_coaching_rollup(demo, driver="owner", config=CONFIG)
    assert "strengths" in r
    for s in r["strengths"]:
        if s["shown"]:
            assert s["n_tracks"] >= CONFIG.gates.min_tracks_for_rollup


def test_driver_with_no_cohorts_returns_an_empty_stated_rollup(tmp_path):
    db = Database.open(str(tmp_path / "empty.db"))
    try:
        r = build_coaching_rollup(db, driver="nobody", config=CONFIG)
        assert r["patterns"] == [] and r["strengths"] == []
        assert r["n_cohorts"] == 0
    finally:
        db.close()
