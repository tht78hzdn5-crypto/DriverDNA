"""A55 Stage 1: era recurrence in the driver rollup — the tendency
annotation (docs/SPEC.md A55; docs/COACHING-FUNDAMENTALS-REVIEW.md §5).

Stage 1 is annotation only: each rollup pattern gains `eras_fired`,
`eras_total` and `tendency_state`. No existing score, metric,
threshold or pooled eligibility outcome moves — the additive test below
pins that on identical lap content with and without dates.

A59 Stage 2 supersedes the Stage 1 machinery this file originally
pinned: the state partition moved to `coaching/eras.py`
(`fault_tendency_state`, with improving/dormant/regression and the
strength-complement resolved rule) and A36's re-cut buckets were
replaced by fixed eras (see tests/test_coaching_tendency_stage2.py
for the partition and fixed-era tests). What remains here pins the
integration behavior through the Stage 2 machinery: annotation on real
rollups, rendering, and determinism. The superseded tests were replaced,
not edited to pass, per the amendment rule.
"""

from __future__ import annotations

import html

import pytest

from driverdna.attribution.ranker import vs_self_findings
from driverdna.coaching.engine import eligible_principles
from driverdna.coaching.eras import set_era_size
from driverdna.coaching.ontology import tendency_line
from driverdna.coaching.rollup import (
    TENDENCY_MODEL_VERSION,
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
    # A59: resolved now means a clearing streak at K, not any absence.
    assert tendency_line(state="resolved", eras_fired=2, eras_total=4,
                         clearing_streak=2) == (
        "Fired in 2 of 4 eras, clear for the last 2 eras — it has "
        "stopped firing."
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
    cfg = CONFIG
    db = _era_db([MIX, MIX, MIX], config=cfg)
    set_era_size(db, "owner", 12)
    try:
        r = build_coaching_rollup(db, driver="owner", config=cfg)
        assert r["tendency_version"] == TENDENCY_MODEL_VERSION
        p = _pattern(r)
        assert (p["eras_fired"], p["eras_total"], p["tendency_state"]) == (
            3, 3, "persistent")
    finally:
        db.close()


def test_pattern_absent_from_the_latest_era_is_dormant():
    # A59: one clearing era is dormant, not resolved (K=2); the
    # resolved-at-K case is pinned in test_coaching_tendency_stage2.py.
    cfg = CONFIG
    db = _era_db([MIX, MIX, FAST], config=cfg)
    set_era_size(db, "owner", 12)
    try:
        p = _pattern(build_coaching_rollup(db, driver="owner", config=cfg))
        assert (p["eras_fired"], p["eras_total"], p["tendency_state"]) == (
            2, 3, "dormant")
    finally:
        db.close()


def test_pattern_firing_only_in_the_latest_era_is_new():
    cfg = CONFIG
    db = _era_db([FAST, FAST, MIX], config=cfg)
    set_era_size(db, "owner", 12)
    try:
        p = _pattern(build_coaching_rollup(db, driver="owner", config=cfg))
        assert (p["eras_fired"], p["eras_total"], p["tendency_state"]) == (
            1, 3, "new")
    finally:
        db.close()


def test_pattern_in_a_minority_of_eras_including_the_latest_is_recurring():
    cfg = CONFIG
    db = _era_db([FAST, FAST, FAST, MIX, MIX], config=cfg)
    set_era_size(db, "owner", 12)
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
    pre-A55 field of every pattern and strength must be identical;
    only the annotation fields (and the rollup's tendency_version) may
    appear. A59 extends the annotation set: strengths are annotated too,
    and fault patterns carry first/last seen eras, clearing streak,
    band history, variant and followup."""
    cfg = CONFIG
    dated = _era_db([MIX, MIX, FAST], dated=True, config=cfg)
    set_era_size(dated, "owner", 12)
    undated = _era_db([MIX, MIX, FAST], dated=False, config=cfg)
    try:
        a = build_coaching_rollup(dated, driver="owner", config=cfg)
        b = build_coaching_rollup(undated, driver="owner", config=cfg)
        assert len(a["patterns"]) == len(b["patterns"])
        assert len(a["strengths"]) == len(b["strengths"])
        annotation = (
            "eras_fired", "eras_total", "tendency_state",
            "first_seen_era", "last_seen_era", "clearing_streak",
            "band_before", "current_band", "tendency_variant",
            "drill_followup",
        )
        for pa, pb in zip(a["patterns"], b["patterns"], strict=True):
            assert {k: v for k, v in pa.items() if k not in annotation} == \
                   {k: v for k, v in pb.items() if k not in annotation}
            # The undated build's annotation is present but empty — the
            # fields are unconditional; only their content is earned.
            assert (pb["eras_fired"], pb["eras_total"],
                    pb["tendency_state"]) == (0, 0, None)
        for sa, sb in zip(a["strengths"], b["strengths"], strict=True):
            assert {k: v for k, v in sa.items() if k not in annotation} == \
                   {k: v for k, v in sb.items() if k not in annotation}
            assert (sb["eras_fired"], sb["eras_total"],
                    sb["tendency_state"]) == (0, 0, None)
    finally:
        dated.close()
        undated.close()


# --- rendering + determinism ---------------------------------------------------


@pytest.fixture(scope="module")
def two_track_persistent():
    cfg = CONFIG
    db = _era_db([MIX, MIX, MIX], tracks=("TrackA", "TrackB"), config=cfg)
    set_era_size(db, "owner", 12)
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
