"""Stage 2: the tendency layer's persistence (docs/SPEC.md A59).

Stage 1 annotated rollup patterns with era states computed from A36's
re-cut date buckets. Stage 2 replaces that with fixed eras and a persisted
projection:

- `driver_tendencies` (migration 019): owner-scoped, versioned by
  TENDENCY_MODEL_VERSION, storing the projection AND `first_seen` — the
  deliberate departure from `driver_beliefs`' upsert-amnesia.
- Fixed eras: lap blocks of a per-driver size (config default 500), set
  once, never re-cut. A closed era's summary is frozen; only the open era
  is computed live. Tendency computation reads summaries, never
  reprocesses old laps.
- New states: `improving` (full band drop sustained across 2 eras),
  `dormant` (1 era of absence, K=2), `regression` (full band rise
  sustained across 2 eras, defined here), and `resolved` via the strength
  complement (clearing as a strength or below gate for K=2 consecutive
  eras). K is anchored on the owner corpus in A59: with 2 eras of dated
  history, K=2 is the smallest "larger K" that yields a resolved state
  within one more era cycle; K=3 would need 4 eras (~2000 laps).
- Payload `tendencies` section (payload v13, additive) in the driver
  payload and per-cohort coaching payloads, with per-era REFERENCES
  (corners, cohorts, evidence count) — not raw evidence IDs: the full
  IDs measure 44,668 ids / 546KB on the owner corpus, 35% of the whole
  payload, so A59 switches the wire format to references while the DB
  rows and frozen summaries keep the full lists.
"""

from __future__ import annotations

import pytest

from driverdna.coaching.eras import (
    TENDENCY_MODEL_VERSION,
    EraPrincipleRecord,
    fault_tendency_state,
    get_era_size,
    read_tendencies,
    refresh_eras,
    refresh_tendencies,
    set_era_size,
    strength_tendency_state,
)
from driverdna.coaching.ontology import (
    ONTOLOGY_VERSION,
    strength_tendency_line,
    tendency_line,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import MIGRATIONS, Database
from driverdna.report.builder import render_driver_html, render_driver_markdown
from driverdna.report.payload import (
    PAYLOAD_VERSION,
    build_cohort_payload,
    build_driver_payload,
    to_normalized_json,
)
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
CARRY = "cp.rotation_efficiency.carry_the_middle"

# An era needs >= gates.min_phase_samples (10) laps and >= 2 sessions in a
# cohort before a vs-self finding can be shown in it, hence 12 laps/era.
MIX = ("fast",) * 6 + ("slow",) * 6
FAST = ("fast",) * 12


def _config() -> DriverDNAConfig:
    return CONFIG.model_copy(deep=True)


def _era_db(eras, *, tracks=("TrackA",), dated=True, config=None):
    """One car, the given tracks; each era is a tuple of lap kinds, all
    sharing one lap_date per era so date order == ingestion order."""
    cfg = config or CONFIG
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
                    config=cfg,
                )
    return db


def _rec(fired, band=None, strength=False, evaluated=True):
    rank = {"major": 2, "notable": 1, "moderate": 0, "negligible": -1}.get(band)
    return EraPrincipleRecord(
        fired=fired, band=band, band_rank=rank,
        strength=strength, evaluated=evaluated,
    )


def _fault_records(fired_eras, total, bands=None, clearing=None):
    """Build era records for a fault partition test. `bands` maps era ->
    band for fired eras; `clearing` maps era -> strength flag for clearing
    eras (default: below-gate clearing, evaluated, no strength)."""
    bands = bands or {}
    clearing = clearing or {}
    records = []
    for era in range(total):
        if era in fired_eras:
            records.append(_rec(True, bands.get(era, "notable")))
        elif era in clearing:
            records.append(_rec(False, strength=clearing[era]))
        else:
            records.append(_rec(False, strength=False, evaluated=True))
    return records


# --- versions ------------------------------------------------------------


def test_tendency_version_is_v3_and_ontology_is_v9_and_payload_is_v14():
    # A60 moves the ontology pin v7 → v8. A61 moves tendency v2 → v3
    # (session dimension is state-changing) and payload v13 → v14
    # (tendencies rows gain session_states; coach payload and chat
    # bundle gain tendencies; coach payload drops focus_history).
    # A62 moves the ontology pin v8 → v9; tendency and payload pins
    # are unchanged by this tranche.
    assert TENDENCY_MODEL_VERSION == "tendency-v3"
    assert ONTOLOGY_VERSION == "coach-onto-v9"
    assert PAYLOAD_VERSION == 14


# --- migration 019 ---------------------------------------------------------


def test_migration_019_creates_tendency_tables():
    db = Database.open(":memory:")
    assert db.schema_version == len(MIGRATIONS) == 20
    tables = {
        r["name"] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for table in (
        "driver_tendencies",
        "tendency_eras",
        "tendency_era_laps",
        "driver_tendency_settings",
    ):
        assert table in tables


def test_migration_from_018_applies_cleanly(tmp_path, monkeypatch):
    """An existing DB at 018 migrates to 019 with prior rows intact."""
    db_path = tmp_path / "v018.db"
    monkeypatch.setattr("driverdna.db.MIGRATIONS", MIGRATIONS[:18])
    with Database.open(db_path) as db:
        assert db.schema_version == 18
        with db.conn:
            db.conn.execute(
                "INSERT INTO driver_beliefs (owner_user_pk, driver, fundamental,"
                " signal_status, score, confidence, evidence_count, trend,"
                " scoring_model_version, taxonomy_version)"
                " VALUES (1, 'owner', 'braking', 'measured', 50.0, 0.9, 10,"
                " 'stable', 'dm-v3', 'v1')"
            )
    monkeypatch.undo()
    with Database.open(db_path) as db:
        assert db.schema_version == 20
        row = db.conn.execute(
            "SELECT fundamental FROM driver_beliefs WHERE driver='owner'"
        ).fetchone()
        assert row["fundamental"] == "braking"
        tables = {
            r["name"] for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "driver_tendencies" in tables


def test_tendency_tables_are_owner_scoped(tmp_path):
    """Two users sharing one DB file never see each other's eras or rows."""
    db_path = tmp_path / "scoped.db"
    with Database.open(db_path) as db:
        with db.conn:
            alice = db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?) "
                "RETURNING user_pk",
                ("alice@example.com", "hash-a"),
            ).fetchone()["user_pk"]
            bob = db.conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?) "
                "RETURNING user_pk",
                ("bob@example.com", "hash-b"),
            ).fetchone()["user_pk"]
    cfg = _config()
    with Database.open(db_path, user_pk=alice) as db:
        for ei, kinds in enumerate([MIX, MIX]):
            for i, kind in enumerate(kinds):
                src = f"alice-e{ei}-{kind}{i}.csv"
                lap = (
                    warp_time(track_lap(src=src), (0.19, 0.22), 0.4)
                    if kind == "slow" else track_lap(src=src)
                )
                run_synthetic_lap(
                    db, lap, driver="owner", car="TestCar", track="TrackA",
                    session_key=f"s{i % 3}",
                    lap_date=f"2026-{ei + 1:02d}-15", config=cfg,
                )
        set_era_size(db, "owner", 12)
        refresh_tendencies(db, "owner", cfg)
        alice_eras = refresh_eras(db, "owner", cfg)
        alice_rows = read_tendencies(db, "owner")
    assert len(alice_eras) == 2
    assert alice_rows
    with Database.open(db_path, user_pk=bob) as db:
        assert refresh_eras(db, "owner", cfg) == []
        assert read_tendencies(db, "owner") == []


# --- the state partition, v2 (pure) ---------------------------------------


@pytest.mark.parametrize("fired,total,bands,clearing,expected", [
    (frozenset(), 0, {}, {}, None),                    # no eras at all
    (frozenset(), 3, {}, {}, None),                    # eras, no firing
    (frozenset({0}), 1, {}, {}, "new"),                # single era: new
    (frozenset({2}), 3, {}, {}, "new"),                # only latest
    (frozenset({0, 1, 2}), 3, {}, {}, "persistent"),   # 3/3
    (frozenset({0, 2}), 3, {}, {}, "persistent"),      # 2/3 >= 0.5
    (frozenset({1, 3}), 4, {}, {}, "persistent"),      # exactly at share
    (frozenset({0, 4}), 5, {}, {}, "recurring"),       # 2/5 < 0.5
    (frozenset({0}), 2, {}, {}, "dormant"),            # 1 absent era < K
    (frozenset({0}), 3, {}, {}, "resolved"),           # 2 clearing >= K
    (frozenset({0, 1}), 3, {}, {}, "dormant"),         # streak 1
    (frozenset({0, 1}), 4, {}, {}, "resolved"),        # streak 2
    (frozenset({0, 1, 2}), 3, {0: "major", 1: "notable", 2: "moderate"},
     {}, "improving"),                                 # full drop, held
    (frozenset({0, 1, 2}), 3, {0: "notable", 1: "moderate", 2: "moderate"},
     {}, "improving"),                                 # drop then flat below
    (frozenset({0, 1, 2}), 3, {0: "major", 1: "notable", 2: "major"},
     {}, "persistent"),                                # drop not sustained
    (frozenset({0, 1, 2}), 3, {0: "moderate", 1: "notable", 2: "major"},
     {}, "regression"),                                # full rise, held
    (frozenset({0, 1, 2}), 3, {0: "moderate", 1: "notable", 2: "notable"},
     {}, "regression"),                                # rise then held
    (frozenset({0, 1, 2}), 3, {0: "moderate", 1: "major", 2: "moderate"},
     {}, "persistent"),                                # rise not sustained
    (frozenset({0, 2}), 3, {0: "major", 2: "notable"},
     {}, "persistent"),                                # gap breaks the run
])
def test_fault_state_partition_v2(fired, total, bands, clearing, expected):
    records = _fault_records(fired, total, bands, clearing)
    outcome = fault_tendency_state(
        records, persistent_min_share=0.5, resolved_min_eras=2,
    )
    assert outcome.state == expected
    assert outcome.eras_fired == len(fired)
    assert outcome.eras_total == total


def test_fault_state_resolved_min_eras_is_config_driven():
    records = _fault_records(frozenset({0}), 3)
    assert fault_tendency_state(
        records, persistent_min_share=0.5, resolved_min_eras=3,
    ).state == "dormant"
    assert fault_tendency_state(
        records, persistent_min_share=0.5, resolved_min_eras=2,
    ).state == "resolved"


def test_fault_state_clearing_as_strength_counts_toward_resolved():
    # Fired era 0, then two eras clearing as a strength (not below gate).
    records = _fault_records(frozenset({0}), 3, clearing={1: True, 2: True})
    outcome = fault_tendency_state(
        records, persistent_min_share=0.5, resolved_min_eras=2,
    )
    assert outcome.state == "resolved"
    assert outcome.clearing_streak == 2


def test_fault_state_trailing_thin_era_carries_no_signal():
    # Fired eras 0-1, era 2 thin (no adequately-sized cohort): the state
    # is decided over the substantive eras, not by the thin era.
    records = [
        _rec(True, "notable"),
        _rec(True, "notable"),
        _rec(False, strength=False, evaluated=False),
    ]
    outcome = fault_tendency_state(
        records, persistent_min_share=0.5, resolved_min_eras=2,
    )
    assert outcome.state == "persistent"
    assert outcome.eras_total == 3


def test_fault_state_first_and_last_seen():
    records = _fault_records(frozenset({1, 3}), 4)
    outcome = fault_tendency_state(
        records, persistent_min_share=0.5, resolved_min_eras=2,
    )
    assert outcome.first_seen_era == 1
    assert outcome.last_seen_era == 3


@pytest.mark.parametrize("strength_eras,total,expected", [
    (frozenset(), 3, None),
    (frozenset({2}), 3, "new"),
    (frozenset({0, 1, 2}), 3, "persistent"),
    (frozenset({0, 2}), 3, "persistent"),
    (frozenset({0, 4}), 5, "recurring"),
    (frozenset({0, 1}), 3, "lapsed"),
    (frozenset({0}), 3, "lapsed"),
])
def test_strength_state_partition(strength_eras, total, expected):
    records = [
        _rec(False, strength=(era in strength_eras)) for era in range(total)
    ]
    outcome = strength_tendency_state(records, persistent_min_share=0.5)
    assert outcome.state == expected


def test_strength_state_trailing_thin_era_carries_no_signal():
    records = [
        _rec(False, strength=True),
        _rec(False, strength=False, evaluated=True),
        _rec(False, strength=False, evaluated=False),
    ]
    outcome = strength_tendency_state(records, persistent_min_share=0.5)
    assert outcome.state == "lapsed"


# --- ontology words for the new states -------------------------------------


def test_tendency_line_words_for_new_states():
    assert tendency_line(state="improving", eras_fired=3, eras_total=3,
                         current_band="moderate", current_band_corners=4,
                         band_before="major") == (
        "Fired in 3 of 3 eras, including the most recent — but the band "
        "fell from major to moderate and held there. Currently moderate "
        "at 4 corners."
    )
    assert tendency_line(state="dormant", eras_fired=1, eras_total=2) == (
        "Fired in 1 of 2 eras, but not in the most recent — quiet "
        "lately, not yet resolved."
    )
    assert tendency_line(state="regression", eras_fired=3, eras_total=3,
                         current_band="major", current_band_corners=2,
                         band_before="moderate") == (
        "Fired in 3 of 3 eras, including the most recent — and the band "
        "rose from moderate to major and held there. Currently major "
        "at 2 corners."
    )
    assert tendency_line(state="resolved", eras_fired=1, eras_total=3,
                         clearing_streak=2) == (
        "Fired in 1 of 3 eras, clear for the last 2 eras — it has "
        "stopped firing."
    )


def test_strength_tendency_line_words():
    assert strength_tendency_line(state="persistent", eras_fired=3,
                                  eras_total=3) == (
        "Clear in 3 of 3 eras, including the most recent — holding up."
    )
    assert strength_tendency_line(state="lapsed", eras_fired=2,
                                  eras_total=3) == (
        "Clear in 2 of 3 eras, but not in the most recent — it has "
        "slipped lately."
    )
    assert strength_tendency_line(state=None, eras_fired=0,
                                  eras_total=0) is None


# --- fixed eras ------------------------------------------------------------


def test_fixed_eras_close_and_freeze():
    """12-lap eras: 36 dated laps close eras 0-2; later laps never rewrite
    a closed era's frozen summary."""
    db = _era_db([MIX, MIX, MIX])
    cfg = _config()
    set_era_size(db, "owner", 12)
    eras = refresh_eras(db, "owner", cfg)
    assert [(e["era_index"], e["status"]) for e in eras] == [
        (0, "closed"), (1, "closed"), (2, "closed"),
    ]
    assert all(e["summary"] is not None for e in eras)
    assert eras[0]["summary"]["principles"][CARRY]["fired"] is True
    frozen_summary = eras[0]["summary"]
    frozen_members = eras[0]["lap_pks"]
    # 12 more laps open (and close) a new era; era 0 must not move.
    for i, _kind in enumerate(FAST):
        src = f"extra-fast{i}.csv"
        lap = track_lap(src=src)
        run_synthetic_lap(
            db, lap, driver="owner", car="TestCar", track="TrackA",
            session_key=f"s{i % 3}", lap_date="2026-04-15", config=cfg,
        )
    eras = refresh_eras(db, "owner", cfg)
    assert [(e["era_index"], e["status"]) for e in eras] == [
        (0, "closed"), (1, "closed"), (2, "closed"), (3, "closed"),
    ]
    assert eras[0]["summary"] == frozen_summary
    assert eras[0]["lap_pks"] == frozen_members


def test_backdated_laps_never_recut_closed_eras():
    """Laps dated before closed eras land in the open era; closed era
    membership is append-only."""
    db = _era_db([MIX, MIX])
    cfg = _config()
    set_era_size(db, "owner", 12)
    eras = refresh_eras(db, "owner", cfg)
    assert [e["status"] for e in eras] == ["closed", "closed"]
    era0_members = eras[0]["lap_pks"]
    for i in range(6):
        lap = track_lap(src=f"backdated{i}.csv")
        run_synthetic_lap(
            db, lap, driver="owner", car="TestCar", track="TrackA",
            session_key=f"s{i % 3}", lap_date="2025-12-01", config=cfg,
        )
    eras = refresh_eras(db, "owner", cfg)
    assert [(e["era_index"], e["status"]) for e in eras] == [
        (0, "closed"), (1, "closed"), (2, "open"),
    ]
    assert eras[0]["lap_pks"] == era0_members
    assert len(eras[2]["lap_pks"]) == 6


def test_per_driver_era_size():
    """Era size is a per-driver setting: the same DB, two drivers, two
    era counts. The unset driver takes the config default."""
    db = Database.open(":memory:")
    cfg = _config()
    for driver in ("owner", "other"):
        for ei, kinds in enumerate([MIX, MIX]):
            for i, kind in enumerate(kinds):
                src = f"{driver}-e{ei}-{kind}{i}.csv"
                lap = (
                    warp_time(track_lap(src=src), (0.19, 0.22), 0.4)
                    if kind == "slow" else track_lap(src=src)
                )
                run_synthetic_lap(
                    db, lap, driver=driver, car="TestCar", track="TrackA",
                    session_key=f"s{i % 3}",
                    lap_date=f"2026-{ei + 1:02d}-15", config=cfg,
                )
    set_era_size(db, "owner", 12)
    assert get_era_size(db, "owner", cfg) == 12
    assert get_era_size(db, "other", cfg) == cfg.coaching.tendency_era_size_laps
    assert len(refresh_eras(db, "owner", cfg)) == 2
    assert len(refresh_eras(db, "other", cfg)) == 1
    assert refresh_eras(db, "other", cfg)[0]["status"] == "open"


def test_era_size_change_applies_at_next_boundary():
    """The open era keeps the size it was created with; a new setting
    takes effect only at the next era boundary. Closed eras never change
    size."""
    db = _era_db([MIX, MIX])
    cfg = _config()
    set_era_size(db, "owner", 12)
    eras = refresh_eras(db, "owner", cfg)
    assert [(e["era_index"], e["era_size_laps"]) for e in eras] == [
        (0, 12), (1, 12),
    ]
    set_era_size(db, "owner", 500)
    for i, _kind in enumerate(FAST):
        lap = track_lap(src=f"e2-fast{i}.csv")
        run_synthetic_lap(
            db, lap, driver="owner", car="TestCar", track="TrackA",
            session_key=f"s{i % 3}", lap_date="2026-03-15", config=cfg,
        )
    eras = refresh_eras(db, "owner", cfg)
    assert eras[2]["era_size_laps"] == 500
    assert eras[2]["status"] == "open"
    # Shrink the setting mid-era: the open era still keeps its own size.
    set_era_size(db, "owner", 24)
    for i, _kind in enumerate(FAST):
        lap = track_lap(src=f"e2b-fast{i}.csv")
        run_synthetic_lap(
            db, lap, driver="owner", car="TestCar", track="TrackA",
            session_key=f"s{i % 3}", lap_date="2026-04-15", config=cfg,
        )
    eras = refresh_eras(db, "owner", cfg)
    assert eras[2]["era_size_laps"] == 500
    assert eras[2]["status"] == "open"
    assert len(eras[2]["lap_pks"]) == 24


def test_first_seen_retained_and_dormant_becomes_resolved():
    """A principle fired in era 0, then absent: dormant after 1 clearing
    era, resolved after K=2 — with first_seen pinned at 0 throughout."""
    db = _era_db([MIX, FAST])
    cfg = _config()
    set_era_size(db, "owner", 12)
    rows = refresh_tendencies(db, "owner", cfg)
    row = next(r for r in rows if r["principle_id"] == CARRY
               and r["side"] == "fault")
    assert row["state"] == "dormant"
    assert row["first_seen_era"] == 0
    assert row["last_seen_era"] == 0
    assert row["clearing_streak"] == 1
    for i, _kind in enumerate(FAST):
        lap = track_lap(src=f"e2-fast{i}.csv")
        run_synthetic_lap(
            db, lap, driver="owner", car="TestCar", track="TrackA",
            session_key=f"s{i % 3}", lap_date="2026-03-15", config=cfg,
        )
    rows = refresh_tendencies(db, "owner", cfg)
    row = next(r for r in rows if r["principle_id"] == CARRY
               and r["side"] == "fault")
    assert row["state"] == "resolved"
    assert row["first_seen_era"] == 0
    assert row["last_seen_era"] == 0
    assert row["clearing_streak"] == 2


def test_refresh_is_idempotent():
    """A second refresh rewrites nothing: closed summaries and rows are
    identical (excluding the wall-clock computed_at column)."""
    db = _era_db([MIX, MIX])
    cfg = _config()
    set_era_size(db, "owner", 12)
    rows_first = refresh_tendencies(db, "owner", cfg)
    eras_first = refresh_eras(db, "owner", cfg)
    rows_second = refresh_tendencies(db, "owner", cfg)
    eras_second = refresh_eras(db, "owner", cfg)

    def _strip(rows):
        return [
            {k: v for k, v in r.items() if k != "computed_at"} for r in rows
        ]

    assert _strip(rows_first) == _strip(rows_second)
    assert [e["summary"] for e in eras_first] == [
        e["summary"] for e in eras_second
    ]


# --- payload ---------------------------------------------------------------


def test_driver_payload_tendencies_section():
    db = _era_db([MIX, FAST])
    cfg = _config()
    set_era_size(db, "owner", 12)
    payload = build_driver_payload(db, cfg)
    assert payload["payload_version"] == 14
    section = payload["tendencies"]
    assert section["tendency_version"] == "tendency-v3"
    assert section["era_size_laps"] == 12
    assert [(e["era_index"], e["status"], e["n_laps"]) for e in section["eras"]] == [
        (0, "closed", 12), (1, "closed", 12),
    ]
    row = next(r for r in section["principles"]
               if r["principle_id"] == CARRY and r["side"] == "fault")
    assert row["state"] == "dormant"
    assert row["eras_fired"] == 1
    assert row["eras_total"] == 2
    assert row["first_seen_era"] == 0
    assert row["last_seen_era"] == 0
    assert row["per_era"]["0"]["fired"] is True
    assert row["per_era"]["1"]["fired"] is False
    # Per-era references, not raw IDs: corners where it fired, the
    # cohort, and how many evidence observations sit behind the era.
    assert row["per_era"]["0"]["corners"]
    assert row["per_era"]["0"]["evidence_count"] > 0
    assert row["per_era"]["1"]["corners"] == []
    assert row["per_era"]["1"]["evidence_count"] == 0
    # The payload strips the raw per-observation ID lists (A59
    # measurement: 546KB on the owner corpus); the DB rows keep them.
    assert "evidence" not in row
    # Bespoke variants exist for persistent/resolved only; a dormant
    # row carries the key with None — the generic state line speaks.
    assert "variant" in row and row["variant"] is None


def test_persisted_rows_keep_full_evidence_ids():
    """The DB projection keeps what the payload strips: full
    per-observation evidence ID lists, per era, per side."""
    db = _era_db([MIX, FAST])
    cfg = _config()
    set_era_size(db, "owner", 12)
    refresh_tendencies(db, "owner", cfg)
    row = next(r for r in read_tendencies(db, "owner")
               if r["principle_id"] == CARRY and r["side"] == "fault")
    assert row["evidence"]["0"]
    assert row["evidence"]["1"] == []
    assert all(e.startswith("obs:") for e in row["evidence"]["0"])


def test_cohort_payload_tendencies_section_is_a_subset():
    """Per-cohort tendencies carry only principles with candidates or
    strengths in that cohort: CARRY fires on TrackA (MIX) and never on
    TrackB (FAST only)."""
    db = Database.open(":memory:")
    cfg = _config()
    for track, eras in (("TrackA", [MIX, FAST]), ("TrackB", [FAST, FAST])):
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
                    lap_date=f"2026-{ei + 1:02d}-15", config=cfg,
                )
    set_era_size(db, "owner", 12)
    build_driver_payload(db, cfg)  # refreshes the projection
    cohort_a = build_cohort_payload(
        db, driver="owner", car="TestCar", track="TrackA", config=cfg,
    )
    cohort_b = build_cohort_payload(
        db, driver="owner", car="TestCar", track="TrackB", config=cfg,
    )
    pairs_a = {(r["principle_id"], r["side"])
               for r in cohort_a["coaching"]["tendencies"]}
    pairs_b = {(r["principle_id"], r["side"])
               for r in cohort_b["coaching"]["tendencies"]}
    # The fault row for CARRY belongs to TrackA only; TrackB's FAST laps
    # never produce a CARRY candidate (a strength row there would not
    # contradict this — the filter is per (principle, side)).
    assert (CARRY, "fault") in pairs_a
    assert (CARRY, "fault") not in pairs_b


# --- determinism + rendering -------------------------------------------------


def test_driver_payload_byte_deterministic_with_tendency_stage2():
    db = _era_db([MIX, FAST])
    cfg = _config()
    set_era_size(db, "owner", 12)
    first = to_normalized_json(build_driver_payload(db, cfg))
    second = to_normalized_json(build_driver_payload(db, cfg))
    assert first == second


def test_report_renders_variant_and_followup_for_persistent_pattern():
    """A persistent pattern renders its tendency-framed variant and its
    escalated second assignment in both report surfaces."""
    db = _era_db([MIX, MIX], tracks=("TrackA", "TrackB"))
    cfg = _config()
    set_era_size(db, "owner", 12)
    payload = build_driver_payload(db, cfg)
    rollup = payload["coaching_rollup"]
    pattern = next(p for p in rollup["patterns"]
                   if p["coaching_principle_id"] == CARRY)
    assert pattern["shown"]
    assert pattern["tendency_state"] == "persistent"
    assert pattern["tendency_variant"]
    assert pattern["drill_followup"]
    md = render_driver_markdown(payload)
    html_out = render_driver_html(payload)
    assert pattern["tendency_variant"] in md
    assert pattern["tendency_variant"] in html_out
    assert pattern["drill_followup"] in md
    assert pattern["drill_followup"] in html_out


def test_shown_strengths_carry_tendency_annotation():
    """Strengths gain era annotation from the same machinery; a shown
    strength renders its strength tendency line in both surfaces."""
    db = _era_db([MIX, MIX], tracks=("TrackA", "TrackB"))
    cfg = _config()
    set_era_size(db, "owner", 12)
    payload = build_driver_payload(db, cfg)
    rollup = payload["coaching_rollup"]
    shown = [s for s in rollup["strengths"] if s["shown"]]
    assert shown, "expected at least one shown strength in a 2-track MIX DB"
    for s in shown:
        assert s["tendency_state"] in (
            None, "new", "recurring", "persistent", "lapsed",
        )
        assert s["eras_total"] == 4
    md = render_driver_markdown(payload)
    html_out = render_driver_html(payload)
    for s in shown:
        if s["tendency_state"] is not None:
            line = strength_tendency_line(
                state=s["tendency_state"], eras_fired=s["eras_fired"],
                eras_total=s["eras_total"],
            )
            assert line in md
            assert line in html_out
