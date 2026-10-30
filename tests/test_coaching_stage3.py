"""Stage 3 (A61): narration + session dimension.

- Coach/chat prompts gain exactly one tendency-acknowledgment instruction
  class (coach-v5, chat-v4); the validator is unchanged — narratable
  tendencies are exactly the payload section, nothing else.
- `focus_history` leaves the coach payload; accepted outputs stay
  observable via `db.coach_history` (see test_coach.py's rewritten test).
- The session dimension is a SECOND partition alongside eras:
  early/late within a session, first-visit/return-visit across sessions
  at a track. It is state-changing (tendency-v3), not annotation-only.
- Session-dimension definition (A61):
  - A session is a dated self lap's `session_key` group; a session's
    date is its earliest lap date; sessions order by (date, min lap_pk).
  - Position: laps inside a session order by (lap_date, lap_pk);
    early = the first ceil(n/2), late = the rest.
  - Visit: a session is first_visit iff its date equals the track's
    first session date; later sessions at that track are return_visit.
    A session never splits across visit classes (its date is its first
    lap date, so a midnight-crossing session keeps one class).
  - Excluded from the dimension: undated laps, laps with no session_key,
    and laps in undated sessions (none exist in practice — a session
    with no dated lap has no date to order by).
- Slice summaries freeze at era close (a `slices` key in summary_json,
  evidence lists stripped to counts); pre-Stage-3 closed eras gain the
  key on first v3 refresh, nothing else in the summary moving.
"""

import json

from driverdna.chat.session import (
    CHAT_PROMPT_VERSION,
    CHAT_SYSTEM_PROMPT,
    build_chat_bundle,
)
from driverdna.coach.payload import build_coach_payload
from driverdna.coach.provider import PROMPT_VERSION, SYSTEM_PROMPT
from driverdna.coaching.eras import (
    TENDENCY_MODEL_VERSION,
    read_tendencies,
    refresh_eras,
    refresh_tendencies,
    session_slices,
    set_era_size,
)
from driverdna.coaching.ontology import PRINCIPLES
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.report.payload import (
    PAYLOAD_VERSION,
    build_cohort_payload,
    build_driver_payload,
    to_normalized_json,
)
from synth import run_synthetic_lap, track_lap, warp_time

SMOOTH = "cp.steering_smoothness.smooth_hands"
CARRY = "cp.rotation_efficiency.carry_the_middle"
SLICES = ("early", "late", "first_visit", "return_visit")


def _config():
    return DriverDNAConfig()


def _add_laps(db, session_key, lap_date, kinds, prefix, cfg):
    """One session's laps, in order: kinds is a list of "fast"/"slow"."""
    for i, kind in enumerate(kinds):
        lap = track_lap(src=f"{prefix}-{i}.csv")
        if kind == "slow":
            lap = warp_time(lap, (0.19, 0.22), 0.4)
        run_synthetic_lap(
            db, lap, driver="owner", car="TestCar", track="TrackA",
            session_key=session_key, lap_date=lap_date, config=cfg,
        )


def _slice_db():
    """3 eras x 24 laps. Era 0 sessions are MIX throughout (moderate
    smooth_hands band); era 1/2 sessions are fast-early / slow-late, so
    the early and late slices drop a full band rank (negligible) while
    the full era stays MIX (moderate). Return-visit sessions mirror the
    full era, so return_visit stays persistent like the full state."""
    db = Database.open(":memory:")
    cfg = _config()
    mix_half = ("fast", "slow") * 3  # 6 laps: 3 fast + 3 slow
    _add_laps(db, "s1", "2026-01-05", list(mix_half) + list(mix_half), "e0s1", cfg)
    _add_laps(db, "s2", "2026-01-06", list(mix_half) + list(mix_half), "e0s2", cfg)
    for sess, date, prefix in (
        ("s3", "2026-01-07", "e1s3"), ("s4", "2026-01-08", "e1s4"),
        ("s5", "2026-01-09", "e2s5"), ("s6", "2026-01-10", "e2s6"),
    ):
        _add_laps(
            db, sess, date,
            ["fast"] * 6 + ["slow"] * 6, prefix, cfg,
        )
    set_era_size(db, "owner", 24)
    return db, cfg


def _row(rows, pid, side):
    return next(r for r in rows if r["principle_id"] == pid and r["side"] == side)


# --- versions ------------------------------------------------------------------


def test_stage3_versions():
    # A61 bumps: coach-v5, chat-v4, tendency-v3, payload v14; v6 moves the
    # prompt pins only (coach-v6, chat-v5).
    assert PROMPT_VERSION == "coach-v6"
    assert CHAT_PROMPT_VERSION == "chat-v5"
    assert TENDENCY_MODEL_VERSION == "tendency-v3"
    assert PAYLOAD_VERSION == 14


# --- the one new instruction class ----------------------------------------------


def _flat(prompt):
    # The prompt wraps lines; the rule is one sentence across the wrap.
    return " ".join(prompt.split())


def test_coach_prompt_has_exactly_one_tendency_instruction_class():
    assert SYSTEM_PROMPT.lower().count("tendencies") == 1
    assert SYSTEM_PROMPT.count("session_states") == 1
    assert "payload.tendencies.principles" in SYSTEM_PROMPT
    assert ("Never claim a tendency, recurrence, or progress not present"
            " in that section." in _flat(SYSTEM_PROMPT))


def test_chat_prompt_has_exactly_one_tendency_instruction_class():
    assert CHAT_SYSTEM_PROMPT.lower().count("tendencies") == 1
    assert CHAT_SYSTEM_PROMPT.count("session_states") == 1
    assert "bundle.tendencies.principles" in CHAT_SYSTEM_PROMPT
    assert ("Never claim a tendency, recurrence, or progress not present"
            " in that section." in _flat(CHAT_SYSTEM_PROMPT))


# --- focus_history removal -------------------------------------------------------


def test_coach_payload_has_tendencies_and_no_focus_history():
    db, cfg = _slice_db()
    refresh_tendencies(db, "owner", cfg)
    payload = build_coach_payload(
        db, driver="owner", car="TestCar", track="TrackA", config=cfg,
    )
    assert "focus_history" not in payload
    assert payload["tendencies"]["tendency_version"] == "tendency-v3"
    row = _row(payload["tendencies"]["principles"], SMOOTH, "fault")
    assert set(row["session_states"]) == set(SLICES)
    for entry in row["session_states"].values():
        assert set(entry) == {"state", "eras_fired", "eras_total"}


def test_chat_bundle_has_tendencies_section():
    db, cfg = _slice_db()
    refresh_tendencies(db, "owner", cfg)
    bundle = build_chat_bundle(
        db, driver="owner", car="TestCar", track="TrackA", config=cfg,
    )
    assert bundle["tendencies"]["tendency_version"] == "tendency-v3"
    row = _row(bundle["tendencies"]["principles"], SMOOTH, "fault")
    assert set(row["session_states"]) == set(SLICES)


def test_driver_payload_tendencies_carry_session_states():
    db, cfg = _slice_db()
    payload = build_driver_payload(db, cfg)
    row = _row(payload["tendencies"]["principles"], SMOOTH, "fault")
    assert set(row["session_states"]) == set(SLICES)


def test_per_cohort_coaching_tendencies_carry_session_states():
    db, cfg = _slice_db()
    refresh_tendencies(db, "owner", cfg)
    cohort = build_cohort_payload(
        db, driver="owner", car="TestCar", track="TrackA", config=cfg,
    )
    row = _row(cohort["coaching"]["tendencies"], SMOOTH, "fault")
    assert set(row["session_states"]) == set(SLICES)


# --- the narratable set is exactly the projection ---------------------------------


def test_payload_tendencies_are_exactly_the_projection():
    """The AI may narrate what the section states and nothing else: the
    coach section is the persisted projection, minus the two fields the
    payload never carries (computed_at, evidence)."""
    db, cfg = _slice_db()
    refresh_tendencies(db, "owner", cfg)
    payload = build_coach_payload(
        db, driver="owner", car="TestCar", track="TrackA", config=cfg,
    )
    projected = {
        (r["principle_id"], r["side"]) for r in read_tendencies(db, "owner")
    }
    section = {
        (r["principle_id"], r["side"])
        for r in payload["tendencies"]["principles"]
    }
    assert section == projected
    # Absence is representable: some ontology principle has no row, so a
    # claim about it would have no payload backing.
    missing = [
        pid for pid in PRINCIPLES
        if pid not in {r["principle_id"] for r in read_tendencies(db, "owner")}
    ]
    assert missing
    assert all(pid not in {r["principle_id"]
                          for r in payload["tendencies"]["principles"]}
               for pid in missing)


def test_coach_payload_deterministic_with_tendencies():
    db, cfg = _slice_db()
    refresh_tendencies(db, "owner", cfg)
    first = to_normalized_json(build_coach_payload(
        db, driver="owner", car="TestCar", track="TrackA", config=cfg,
    ))
    second = to_normalized_json(build_coach_payload(
        db, driver="owner", car="TestCar", track="TrackA", config=cfg,
    ))
    assert first == second


# --- session dimension definition --------------------------------------------------


def test_session_slices_definition():
    """Positions split each session at ceil(n/2); visits follow the
    track's first session date, with same-day later sessions still
    first-visit; undated and sessionless laps get no slice."""
    db = Database.open(":memory:")
    cfg = _config()
    _add_laps(db, "s1", "2026-01-05", ["fast"] * 5, "d-s1", cfg)
    _add_laps(db, "s2", "2026-01-05", ["fast"] * 4, "d-s2", cfg)
    _add_laps(db, "s3", "2026-01-06", ["fast"] * 3, "d-s3", cfg)
    # Undated lap (no date, no key) and dated-but-sessionless lap.
    run_synthetic_lap(db, track_lap(src="d-undated.csv"), driver="owner",
                      car="TestCar", track="TrackA", config=cfg)
    run_synthetic_lap(db, track_lap(src="d-nosess.csv"), driver="owner",
                      car="TestCar", track="TrackA", lap_date="2026-01-07",
                      config=cfg)
    slices = session_slices(db, "owner")
    by_session = {}
    for row in db.conn.execute(
        "SELECT lap_pk, session_key FROM laps"
        " WHERE owner_user_pk=? AND driver=? AND session_key IS NOT NULL"
        " ORDER BY lap_pk",
        (db.user_pk, "owner"),
    ).fetchall():
        by_session.setdefault(row["session_key"], []).append(row["lap_pk"])
    assert [slices[pk]["position"] for pk in by_session["s1"]] == [
        "early", "early", "early", "late", "late",
    ]
    assert [slices[pk]["position"] for pk in by_session["s2"]] == [
        "early", "early", "late", "late",
    ]
    assert all(slices[pk]["visit"] == "first_visit"
               for pk in by_session["s1"] + by_session["s2"])
    assert all(slices[pk]["visit"] == "return_visit"
               for pk in by_session["s3"])
    excluded = {
        row["lap_pk"] for row in db.conn.execute(
            "SELECT lap_pk FROM laps WHERE owner_user_pk=? AND driver=?"
            " AND (lap_date IS NULL OR session_key IS NULL)",
            (db.user_pk, "owner"),
        ).fetchall()
    }
    assert excluded and not (set(slices) & excluded)


def test_undated_and_sessionless_only_db_has_no_session_dimension():
    db = Database.open(":memory:")
    cfg = _config()
    run_synthetic_lap(db, track_lap(src="u1.csv"), driver="owner",
                      car="TestCar", track="TrackA", config=cfg)
    run_synthetic_lap(db, track_lap(src="u2.csv"), driver="owner",
                      car="TestCar", track="TrackA", lap_date="2026-01-07",
                      config=cfg)
    assert session_slices(db, "owner") == {}
    assert refresh_tendencies(db, "owner", cfg) == []


# --- state-changing semantics --------------------------------------------------------


def test_session_dimension_changes_some_states_and_not_others():
    """smooth_hands on the 3-era DB: the full-era state is persistent
    (moderate band throughout). The early and late slices drop a full
    band rank after era 0 (moderate -> negligible -> negligible), so
    they read improving — a state that exists only because of the
    session dimension. The first-visit slice fires only in era 0, so it
    reads new. The return-visit slice mirrors the full era, so it stays
    persistent — a state the dimension does not change."""
    db, cfg = _slice_db()
    rows = refresh_tendencies(db, "owner", cfg)
    row = _row(rows, SMOOTH, "fault")
    assert row["state"] == "persistent"
    assert row["eras_fired"] == 3
    states = row["session_states"]
    assert states["early"]["state"] == "improving"
    assert states["late"]["state"] == "improving"
    assert states["first_visit"]["state"] == "new"
    assert states["return_visit"]["state"] == "persistent"
    assert states["return_visit"]["eras_fired"] == 3
    # CARRY still fires in every full era; the dimension does not invent
    # or erase full-era states.
    carry = _row(rows, CARRY, "fault")
    assert carry["eras_fired"] == 3


def test_slice_summaries_frozen_at_close_and_backfilled():
    """Closed-era summaries carry a `slices` key from close time. A
    pre-Stage-3 closed summary (slices stripped) gains exactly that key
    on refresh — every other field byte-identical."""
    db, cfg = _slice_db()
    refresh_tendencies(db, "owner", cfg)
    eras = refresh_eras(db, "owner", cfg)
    assert all(e["status"] == "closed" for e in eras)
    original = eras[0]["summary"]
    assert set(original["slices"]) == set(SLICES)
    stripped = {k: v for k, v in original.items() if k != "slices"}
    db.conn.execute(
        "UPDATE tendency_eras SET summary_json=? WHERE owner_user_pk=?"
        " AND driver=? AND era_index=0",
        (json.dumps(stripped, sort_keys=True), db.user_pk, "owner"),
    )
    db.conn.commit()
    refresh_tendencies(db, "owner", cfg)
    refilled = next(
        e for e in refresh_eras(db, "owner", cfg) if e["era_index"] == 0
    )["summary"]
    assert set(refilled["slices"]) == set(SLICES)
    assert {k: v for k, v in refilled.items() if k != "slices"} == stripped


# --- migration 020 ---------------------------------------------------------------------


def test_migration_020_adds_session_states_column():
    db = Database.open(":memory:")
    columns = {
        row["name"] for row in db.conn.execute(
            "PRAGMA table_info(driver_tendencies)"
        ).fetchall()
    }
    assert "session_states_json" in columns
