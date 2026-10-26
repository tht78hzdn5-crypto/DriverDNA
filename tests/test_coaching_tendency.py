"""A55 Stage 1: era recurrence in the driver rollup — the tendency
annotation (docs/SPEC.md A55; docs/COACHING-FUNDAMENTALS-REVIEW.md §5).

Stage 1 is annotation only: each rollup pattern gains `eras_fired`,
`eras_total` and `tendency_state`, computed by running the EXISTING
eligibility machinery per era, where eras are A36's own date-ordered,
equal-count lap buckets (model/history.py). No existing score, metric,
threshold or pooled eligibility outcome moves — the additive test below
pins that on identical lap content with and without dates.

State partition (rollup._tendency_state), for a pattern whose fired-era
set F is nonempty within E eras, latest era = E-1:

  latest not in F            -> "resolved"   (fired before, absent lately)
  F == {latest}              -> "new"        (only ever the most recent era)
  latest in F, |F|/E >= share-> "persistent" (share = config)
  otherwise                  -> "recurring"

F empty (no dated-era evidence — including a corpus with no dated laps
at all) -> state None: no longitudinal claim is made, exactly the
constitution's "insufficient data over guessing".
"""

from __future__ import annotations

import html

import pytest

from driverdna.attribution.ranker import vs_self_findings
from driverdna.coaching.engine import eligible_principles
from driverdna.coaching.ontology import tendency_line
from driverdna.coaching.rollup import (
    TENDENCY_MODEL_VERSION,
    _era_lap_buckets,
    _tendency_state,
    build_coaching_rollup,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.report.builder import render_driver_html, render_driver_markdown
from driverdna.report.payload import build_driver_payload, to_normalized_json
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
CARRY = "cp.rotation_efficiency.carry_the_middle"

# An era needs >= gates.min_phase_samples (10) laps and >= 2 sessions in a
# cohort before a vs-self finding can be shown in it, hence 12 laps/era.
MIX = ("fast",) * 6 + ("slow",) * 6
FAST = ("fast",) * 12


def _config(buckets: int) -> DriverDNAConfig:
    cfg = CONFIG.model_copy(deep=True)
    cfg.model.history_buckets = buckets
    cfg.model.trend_min_laps_per_bucket = 2
    return cfg


def _era_db(eras, *, tracks=("TrackA",), dated=True, config=CONFIG):
    """One car, the given tracks; each era is a tuple of lap kinds, all
    sharing one lap_date per era so date order == ingestion order."""
    db = Database.open(":memory:")
    for track in tracks:
        for ei, kinds in enumerate(eras):
            for i, kind in enumerate(kinds):
                src = f"{track}-e{ei}-{kind}{i}.csv"
                lap = (
                    warp_time(track_lap(src=src), (0.19, 0.22), 0.4)
                    if kind == "slow" else track_lap(src=src)
                )
                run_synthetic_lap(
                    db, lap, driver="owner", car="TestCar", track=track,
                    session_key=f"s{i % 3}",
                    lap_date=f"2026-{ei + 1:02d}-15" if dated else None,
                    config=config,
                )
    return db


def _pattern(rollup, principle_id=CARRY):
    for p in rollup["patterns"]:
        if p["coaching_principle_id"] == principle_id:
            return p
    raise AssertionError(f"{principle_id} not in patterns: "
                         f"{[p['coaching_principle_id'] for p in rollup['patterns']]}")


# --- the state partition (pure) -------------------------------------------


@pytest.mark.parametrize("fired,total,expected", [
    (frozenset(), 0, None),          # no eras exist at all
    (frozenset(), 3, None),          # eras exist, no dated-era evidence
    (frozenset({0}), 1, "new"),      # a single era can only ever be new
    (frozenset({2}), 3, "new"),      # only the most recent era
    (frozenset({0, 1, 2}), 3, "persistent"),
    (frozenset({0, 2}), 3, "persistent"),   # 2/3 >= 0.5, latest included
    (frozenset({1, 3}), 4, "persistent"),   # exactly at the share boundary
    (frozenset({3, 4}), 5, "recurring"),    # 2/5 < 0.5, latest included
    (frozenset({0, 4}), 5, "recurring"),
    (frozenset({0, 1}), 3, "resolved"),     # absent from the most recent era
    (frozenset({0}), 3, "resolved"),
])
def test_tendency_state_partition(fired, total, expected):
    assert _tendency_state(fired, total, persistent_min_share=0.5) == expected


def test_tendency_state_share_is_config_driven():
    fired = frozenset({0, 2})
    assert _tendency_state(fired, 3, persistent_min_share=0.9) == "recurring"
    assert _tendency_state(fired, 3, persistent_min_share=0.5) == "persistent"


# --- era bucketing (A36 rules, reused) -------------------------------------


def _insert_lap(db, *, lap_date, i):
    db.conn.execute(
        """INSERT INTO laps (owner_user_pk, source_file, driver, car, track,
                             role, n_samples, duration_s, quality_flags, lap_date)
           VALUES (1, ?, 'owner', 'TestCar', 'TrackA', 'self', 10, 60.0, '[]', ?)""",
        (f"bucket{i}.csv", lap_date),
    )
    db.conn.commit()


@pytest.fixture()
def lap_db():
    with Database.open(":memory:") as db:
        yield db


def test_era_buckets_empty_without_dated_laps(lap_db):
    _insert_lap(lap_db, lap_date=None, i=0)
    assert _era_lap_buckets(lap_db, "owner", _config(3)) == []


def test_era_buckets_single_era_below_the_a36_floor(lap_db):
    # 5 dated laps < history_buckets(3) x floor(2) = 6: the multi-era split
    # is not honest yet, so the whole dated history is ONE era — it can
    # only ever support "new", never a longitudinal claim.
    for i in range(5):
        _insert_lap(lap_db, lap_date=f"2026-01-{i + 1:02d}", i=i)
    buckets = _era_lap_buckets(lap_db, "owner", _config(3))
    assert len(buckets) == 1
    assert len(buckets[0]) == 5


def test_era_buckets_equal_count_remainder_at_tail(lap_db):
    # 7 dated laps, 3 buckets: A36's chunker puts the extra lap in the
    # LAST bucket (the convention that makes 2 buckets reproduce _trend).
    for i in range(7):
        _insert_lap(lap_db, lap_date=f"2026-01-{i + 1:02d}", i=i)
    buckets = _era_lap_buckets(lap_db, "owner", _config(3))
    assert [len(b) for b in buckets] == [2, 2, 3]
    dated_pks = [pk for pk, _ in lap_db.dated_self_laps("owner")]
    assert buckets == [
        frozenset(dated_pks[0:2]), frozenset(dated_pks[2:4]),
        frozenset(dated_pks[4:7]),
    ]


# --- ontology words ----------------------------------------------------------


def test_tendency_line_words_live_in_the_ontology():
    assert tendency_line(state=None, eras_fired=0, eras_total=0) is None
    assert tendency_line(state="persistent", eras_fired=6, eras_total=6,
                         current_band="notable", current_band_corners=9) == (
        "Fired in 6 of 6 eras, including the most recent — this is the "
        "habit, not a corner, and it isn't fixed yet. "
        "Currently notable at 9 corners."
    )
    assert tendency_line(state="recurring", eras_fired=2, eras_total=5) == (
        "Fired in 2 of 5 eras, including the most recent — "
        "it keeps coming back."
    )
    assert tendency_line(state="new", eras_fired=1, eras_total=3) == (
        "First fired in the most recent era (1 of 3 eras) — "
        "new, not yet a habit."
    )
    assert tendency_line(state="resolved", eras_fired=2, eras_total=3,
                         current_band="moderate", current_band_corners=1) == (
        "Fired in 2 of 3 eras, but not in the most recent — "
        "it has stopped firing lately. Currently moderate at 1 corner."
    )


# --- lap_pks plumbing: restriction to the full set changes nothing ----------


def test_lap_pks_plumbing_is_identity_at_the_full_set():
    """The era machinery's only new reach into existing code is an
    optional lap_pks on eligible_principles / vs_self_findings. Pinned:
    restricting to the cohort's full lap set returns exactly the
    unrestricted result — the default path cannot drift."""
    db = _era_db([MIX], dated=False)
    try:
        all_pks = frozenset(
            r["lap_pk"] for r in db.conn.execute(
                "SELECT lap_pk FROM laps WHERE role='self'").fetchall()
        )
        plain = eligible_principles(db, driver="owner", car="TestCar",
                                    track="TrackA", config=CONFIG)
        restricted = eligible_principles(db, driver="owner", car="TestCar",
                                         track="TrackA", config=CONFIG,
                                         lap_pks=all_pks)
        assert restricted == plain
        assert eligible_principles(db, driver="owner", car="TestCar",
                                    track="TrackA", config=CONFIG,
                                    lap_pks=frozenset()) == [
            c for c in plain if c.corner_id is None
        ]  # an empty era has no evidence: only the no_signal self-check

        from driverdna.pipeline import phase_windows_from_stored
        loaded = db.load_corner_map(car="TestCar", track="TrackA")
        stored = db.load_corner_windows(loaded[0])
        windows = {cid: phase_windows_from_stored(w) for cid, w in stored.items()}
        f_plain = vs_self_findings(db, driver="owner", car="TestCar",
                                   track="TrackA", windows_by_corner=windows,
                                   config=CONFIG)
        f_restricted = vs_self_findings(db, driver="owner", car="TestCar",
                                        track="TrackA", windows_by_corner=windows,
                                        config=CONFIG, lap_pks=all_pks)
        assert f_restricted == f_plain
    finally:
        db.close()


# --- integration: annotation on real rollups ---------------------------------


def test_pattern_firing_every_era_is_persistent():
    cfg = _config(3)
    db = _era_db([MIX, MIX, MIX], config=cfg)
    try:
        r = build_coaching_rollup(db, driver="owner", config=cfg)
        assert r["tendency_version"] == TENDENCY_MODEL_VERSION
        p = _pattern(r)
        assert (p["eras_fired"], p["eras_total"], p["tendency_state"]) == (
            3, 3, "persistent")
    finally:
        db.close()


def test_pattern_absent_from_the_latest_era_is_resolved():
    cfg = _config(3)
    db = _era_db([MIX, MIX, FAST], config=cfg)
    try:
        p = _pattern(build_coaching_rollup(db, driver="owner", config=cfg))
        assert (p["eras_fired"], p["eras_total"], p["tendency_state"]) == (
            2, 3, "resolved")
    finally:
        db.close()


def test_pattern_firing_only_in_the_latest_era_is_new():
    cfg = _config(3)
    db = _era_db([FAST, FAST, MIX], config=cfg)
    try:
        p = _pattern(build_coaching_rollup(db, driver="owner", config=cfg))
        assert (p["eras_fired"], p["eras_total"], p["tendency_state"]) == (
            1, 3, "new")
    finally:
        db.close()


def test_pattern_in_a_minority_of_eras_including_the_latest_is_recurring():
    cfg = _config(5)
    db = _era_db([FAST, FAST, FAST, MIX, MIX], config=cfg)
    try:
        p = _pattern(build_coaching_rollup(db, driver="owner", config=cfg))
        assert (p["eras_fired"], p["eras_total"], p["tendency_state"]) == (
            2, 5, "recurring")
    finally:
        db.close()


def test_undated_corpus_makes_no_longitudinal_claim():
    db = _era_db([MIX, MIX, FAST], dated=False)
    try:
        p = _pattern(build_coaching_rollup(db, driver="owner", config=CONFIG))
        assert (p["eras_fired"], p["eras_total"], p["tendency_state"]) == (
            0, 0, None)
    finally:
        db.close()


def test_annotation_is_additive_over_identical_content():
    """Same laps, same source names — once dated, once not. Every
    pre-A55 field of every pattern (and the whole strengths list) must be
    identical; only the three annotation fields (and the rollup's
    tendency_version) may appear."""
    cfg = _config(3)
    dated = _era_db([MIX, MIX, FAST], dated=True, config=cfg)
    undated = _era_db([MIX, MIX, FAST], dated=False, config=cfg)
    try:
        a = build_coaching_rollup(dated, driver="owner", config=cfg)
        b = build_coaching_rollup(undated, driver="owner", config=cfg)
        assert a["strengths"] == b["strengths"]
        assert len(a["patterns"]) == len(b["patterns"])
        annotation = ("eras_fired", "eras_total", "tendency_state")
        for pa, pb in zip(a["patterns"], b["patterns"], strict=True):
            assert {k: v for k, v in pa.items() if k not in annotation} == \
                   {k: v for k, v in pb.items() if k not in annotation}
            # The undated build's annotation is present but empty — the
            # fields are unconditional; only their content is earned.
            assert (pb["eras_fired"], pb["eras_total"],
                    pb["tendency_state"]) == (0, 0, None)
    finally:
        dated.close()
        undated.close()


# --- rendering + determinism ---------------------------------------------------


@pytest.fixture(scope="module")
def two_track_persistent():
    cfg = _config(3)
    db = _era_db([MIX, MIX, MIX], tracks=("TrackA", "TrackB"), config=cfg)
    yield db, cfg
    db.close()


def test_tendency_line_renders_in_the_driver_report(two_track_persistent):
    db, cfg = two_track_persistent
    payload = build_driver_payload(db, cfg)
    p = _pattern(payload["coaching_rollup"])
    assert p["shown"] and p["tendency_state"] == "persistent"
    line = tendency_line(
        state=p["tendency_state"], eras_fired=p["eras_fired"],
        eras_total=p["eras_total"],
    )
    assert line is not None and "isn't fixed yet" in line
    assert line in render_driver_markdown(payload)
    assert html.escape(line) in render_driver_html(payload)


def test_driver_payload_is_byte_deterministic_with_tendency(two_track_persistent):
    db, cfg = two_track_persistent
    a = to_normalized_json(build_driver_payload(db, cfg))
    b = to_normalized_json(build_driver_payload(db, cfg))
    assert a == b
