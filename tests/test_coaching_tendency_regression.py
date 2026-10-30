"""A55 Stage 1 regression pins (SPEC.md A55; PR #57), kept through
A59 Stage 2.

The feature tests in tests/test_coaching_tendency.py and
tests/test_coaching_tendency_stage2.py cover the state partition,
fixed eras, and the annotation on individual patterns.
These pins exist so a later change cannot silently regress the
tendency layer's contract with the payload:

- the payload version the era fields shipped in (a literal pin, not a
  round-trip, so a revert of the version bump fails loudly);
- every pattern entry in a real payload carries the three annotation
  fields (not just the one pattern the feature tests inspect);
- the tendency_version label is the literal string downstream readers
  key on, not just whatever the constant currently holds;
- the exact-share boundary holds through the full era machinery
  (bucketing + eligibility + state), not just the pure partition
  function, which already pins it in isolation.
"""

from __future__ import annotations

from driverdna.coaching.eras import set_era_size
from driverdna.coaching.rollup import build_coaching_rollup
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.report.payload import PAYLOAD_VERSION, build_driver_payload
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
CARRY = "cp.rotation_efficiency.carry_the_middle"

MIX = ("fast",) * 6 + ("slow",) * 6
FAST = ("fast",) * 12


def _era_db(eras, *, config):
    """One car, one track; each era is a tuple of lap kinds sharing one
    lap_date, so date order == ingestion order. Mirrors the helper in
    tests/test_coaching_tendency.py."""
    db = Database.open(":memory:")
    for ei, kinds in enumerate(eras):
        for i, kind in enumerate(kinds):
            src = f"TrackA-e{ei}-{kind}{i}.csv"
            lap = (
                warp_time(track_lap(src=src), (0.19, 0.22), 0.4)
                if kind == "slow" else track_lap(src=src)
            )
            run_synthetic_lap(
                db, lap, driver="owner", car="TestCar", track="TrackA",
                session_key=f"s{i % 3}",
                lap_date=f"2026-{ei + 1:02d}-15",
                config=config,
            )
    return db


def test_payload_version_is_14():
    # v14 is the payload that carries session_states on tendencies rows
    # and a top-level tendencies section on the coach payload and chat
    # bundle, with focus_history removed from the coach payload (A61),
    # on top of the tendencies section (A59), tendency era fields
    # (A55), trend_reason (A56) and speculative_guess (BUG-046). Same
    # reasoning as the scoring regression pin: a literal, not a
    # round-trip, so a silent revert fails loudly.
    assert PAYLOAD_VERSION == 14


def test_payload_carries_era_fields_on_every_pattern():
    cfg = CONFIG
    db = _era_db([MIX, MIX, MIX], config=cfg)
    set_era_size(db, "owner", 12)
    try:
        payload = build_driver_payload(db, cfg)
        patterns = payload["coaching_rollup"]["patterns"]
        assert patterns, "no patterns: the pin would be vacuous"
        for p in patterns:
            assert "eras_fired" in p, p
            assert "eras_total" in p, p
            assert "tendency_state" in p, p
            assert isinstance(p["eras_fired"], int)
            assert isinstance(p["eras_total"], int)
            assert p["tendency_state"] in (
                None, "new", "recurring", "persistent", "improving",
                "dormant", "regression", "resolved")
    finally:
        db.close()


def test_tendency_version_label_is_literal():
    cfg = CONFIG
    db = _era_db([MIX, MIX, MIX], config=cfg)
    set_era_size(db, "owner", 12)
    try:
        payload = build_driver_payload(db, cfg)
        assert payload["coaching_rollup"]["tendency_version"] == "tendency-v3"
    finally:
        db.close()


def test_exact_share_boundary_through_the_rollup():
    """A pattern firing in exactly persistent_min_share of eras,
    latest included, must read persistent through the real machinery:
    4 eras, MIX (fires) in eras 1 and 3 only, 2/4 == the 0.5 default."""
    cfg = CONFIG
    db = _era_db([FAST, MIX, FAST, MIX], config=cfg)
    set_era_size(db, "owner", 12)
    try:
        rollup = build_coaching_rollup(db, driver="owner", config=cfg)
        for p in rollup["patterns"]:
            if p["coaching_principle_id"] == CARRY:
                assert (p["eras_fired"], p["eras_total"],
                        p["tendency_state"]) == (2, 4, "persistent")
                return
        raise AssertionError(
            f"{CARRY} not in patterns: "
            f"{[p['coaching_principle_id'] for p in rollup['patterns']]}")
    finally:
        db.close()
