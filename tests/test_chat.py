"""M5 chat tests: the spec's chat acceptance gates, on a mocked provider."""

import pytest

from driverdna.chat.session import ChatSession, build_chat_bundle
from driverdna.chat.tools import execute_tool
from driverdna.coach.payload import evidence_universe
from driverdna.config import ConfigStore, DriverDNAConfig, load_config
from driverdna.db import Database
from driverdna.report.payload import build_cohort_payload
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}
C01_WARP_WINDOW = (0.19, 0.22)


class MockProvider:
    """Scripted provider: each entry is one chat_step return value."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0

    def chat_step(self, system, messages, tools):
        self.calls += 1
        step = self.steps.pop(0)
        return {"text": step.get("text"), "tool_calls": step.get("tool_calls", []),
                "raw_content": None}


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        for i in range(6):
            run_synthetic_lap(
                database, track_lap(src=f"fast{i}.csv"), session_key=f"s{i % 2 + 1}"
            )
        for i in range(6):
            lap = warp_time(track_lap(src=f"slow{i}.csv"), C01_WARP_WINDOW, 0.4)
            run_synthetic_lap(database, lap, session_key=f"s{i % 2 + 1}")
        yield database


def make_session(db, tmp_path, steps):
    store = ConfigStore(tmp_path / "config.toml", db)
    return ChatSession(
        db=db, store=store, provider=MockProvider(steps), **COHORT,
        config=CONFIG, session_id="testsession",
    )


def shown_finding_id(db):
    payload = build_cohort_payload(db, **COHORT, config=CONFIG)
    return next(f["finding_id"] for f in payload["findings"] if f["shown"])


# --- Grounding gates --------------------------------------------------------


def test_unknown_evidence_id_rejected_then_regenerated(db, tmp_path):
    good_id = shown_finding_id(db)
    session = make_session(db, tmp_path, [
        {"text": "Your biggest loss is C01 [obs:99999]."},
        {"text": f"Your biggest loss is C01 [{good_id}]."},
    ])
    result = session.ask("where do I lose the most?")
    assert "error" not in result
    assert good_id in result["evidence"]
    turns = db.chat_session_turns("testsession")
    assert [t["role"] for t in turns] == ["driver", "assistant"]


def test_double_violation_surfaces_error_not_response(db, tmp_path):
    session = make_session(db, tmp_path, [
        {"text": "C01 costs you 77.77 s per lap."},
        {"text": "Believe me, it is 77.77 s."},
    ])
    result = session.ask("how bad is C01?")
    assert "rejected by the grounding contract" in result["error"]
    turns = db.chat_session_turns("testsession")
    assert turns[-1]["role"] == "system-event"
    assert "77.77" in turns[-1]["content"]


def test_numbers_from_tool_results_are_allowed(db, tmp_path):
    session = make_session(db, tmp_path, [
        {"tool_calls": [{"id": "t1", "name": "metric_distribution",
                         "args": {"corner_id": "C01", "metric": "min_speed_kmh"}}]},
        {"text": "C01's median minimum speed is 108.0 km/h across your laps."},
    ])
    result = session.ask("how fast am I through C01?")
    assert "error" not in result
    assert "108.0" in result["text"]


def test_unmeasured_metric_tool_says_not_measured(db, tmp_path):
    store = ConfigStore(tmp_path / "c.toml", db)
    bundle = build_chat_bundle(db, **COHORT, config=CONFIG)
    result = execute_tool(
        db=db, store=store, cohort=COHORT, bundle=bundle, staged=[],
        name="metric_distribution",
        args={"corner_id": "C01", "metric": "tire_slip"},
    )
    assert "error" in result and "not measured" in result["error"]
    assert "inferred" in result["error"]


# --- Config proposals: staged, then explicitly confirmed --------------------


def test_unconfirmed_proposal_changes_nothing(db, tmp_path):
    config_path = tmp_path / "config.toml"
    session = make_session(db, tmp_path, [
        {"tool_calls": [{"id": "t1", "name": "propose_config_change",
                         "args": {"key": "detectors.max_corrections",
                                  "new_value": 2,
                                  "reason": "bumpy track"}}]},
        {"text": "Staged: detectors.max_corrections 1 -> 2. Confirm to apply."},
    ])
    result = session.ask("your one-correction rule is too strict here")
    assert "error" not in result
    assert result["staged"] and result["staged"][0]["key"] == "detectors.max_corrections"
    # NOTHING applied yet:
    assert not config_path.exists()
    assert load_config(config_path).detectors.max_corrections == 1
    assert db.conn.execute("SELECT COUNT(*) n FROM config_history").fetchone()["n"] == 0


def test_confirmed_proposal_applies_and_is_reversible(db, tmp_path):
    config_path = tmp_path / "config.toml"
    session = make_session(db, tmp_path, [
        {"tool_calls": [{"id": "t1", "name": "propose_config_change",
                         "args": {"key": "detectors.max_corrections",
                                  "new_value": 2, "reason": "bumpy track"}}]},
        {"text": "Staged the change; confirm to apply."},
    ])
    session.ask("relax the correction rule")
    effects = session.confirm(1)
    assert load_config(config_path).detectors.max_corrections == 2
    change_pk = effects["config_applied"]["change_pk"]
    row = db.conn.execute(
        "SELECT * FROM config_history WHERE change_pk=?", (change_pk,)
    ).fetchone()
    assert row["source"] == "chat" and row["new_value"] == "2"
    # Reversible through the same store:
    session.store.revert(change_pk)
    assert load_config(config_path).detectors.max_corrections == 1
    # And the audit trail shows both changes:
    assert db.conn.execute("SELECT COUNT(*) n FROM config_history").fetchone()["n"] == 2


def test_invalid_proposal_is_an_error_not_a_stage(db, tmp_path):
    store = ConfigStore(tmp_path / "c.toml", db)
    bundle = build_chat_bundle(db, **COHORT, config=CONFIG)
    staged = []
    result = execute_tool(
        db=db, store=store, cohort=COHORT, bundle=bundle, staged=staged,
        name="propose_config_change",
        args={"key": "detectors.nonsense", "new_value": 1, "reason": "?"},
    )
    assert "error" in result and staged == []


# --- Annotations: suppress framing, keep the measurement --------------------


def test_annotation_suppresses_priority_framing_not_data(db, tmp_path):
    finding_id = shown_finding_id(db)
    session = make_session(db, tmp_path, [
        {"tool_calls": [{"id": "t1", "name": "annotate_finding",
                         "args": {"finding_id": finding_id,
                                  "status": "intentional",
                                  "note": "I lift there on purpose"}}]},
        {"text": "Noted as intentional; it stays measured but won't be framed "
                 "as a priority."},
    ])
    result = session.ask("I lift there on purpose — stop flagging it")
    assert result["effects"]["annotations"] == [finding_id]

    payload = build_cohort_payload(db, **COHORT, config=CONFIG)
    annotated = next(f for f in payload["findings"] if f["finding_id"] == finding_id)
    assert annotated["annotation"]["status"] == "intentional"
    assert annotated["shown"]  # the measurement is intact, still visible
    priorities, evidence = evidence_universe(payload)
    assert finding_id not in priorities  # no longer priority-eligible
    assert finding_id in evidence  # still citable evidence


# --- Bundle and audit -------------------------------------------------------


def test_bundle_is_deterministic_and_carries_state(db, tmp_path):
    a = build_chat_bundle(db, **COHORT, config=CONFIG)
    b = build_chat_bundle(db, **COHORT, config=CONFIG)
    assert a == b
    assert a["config"]["detectors.max_corrections"] == 1
    assert a["latest_coach_plan"] is None
    assert a["report"]["findings"]


def test_bundle_carries_coaching_section(db, tmp_path):
    bundle = build_chat_bundle(db, **COHORT, config=CONFIG)
    coaching = bundle["report"]["coaching"]
    assert coaching["self_checks"]
    assert coaching["self_checks"][0]["coaching_principle_id"] == (
        "cp.eye_line.look_further"
    )


def test_unknown_coaching_principle_rejected_then_regenerated(db, tmp_path):
    session = make_session(db, tmp_path, [
        {"text": "Work on cp.invented.not_real this session."},
        {"text": "Say out loud where you're looking at turn-in "
                  "[cp.eye_line.look_further]."},
    ])
    result = session.ask("what should I work on?")
    assert "error" not in result
    assert "cp.eye_line.look_further" in result["evidence"]


def test_no_signal_principle_with_percentage_rejected(db, tmp_path):
    session = make_session(db, tmp_path, [
        {"text": "I'm 30% confident about your vision "
                  "[cp.eye_line.look_further]."},
        {"text": "Say out loud where you're looking at turn-in "
                  "[cp.eye_line.look_further]."},
    ])
    result = session.ask("how's my vision?")
    assert "error" not in result
    assert "%" not in result["text"]


def test_no_signal_principle_double_violation_surfaces_error(db, tmp_path):
    session = make_session(db, tmp_path, [
        {"text": "I'm 30% confident [cp.eye_line.look_further]."},
        {"text": "Still 40% confident [cp.eye_line.look_further]."},
    ])
    result = session.ask("how's my vision?")
    assert "confidence" in result["error"] or "percentage" in result["error"]


def test_transcript_records_bundle_version_evidence_effects(db, tmp_path):
    good_id = shown_finding_id(db)
    session = make_session(db, tmp_path, [
        {"text": f"C01 is the priority [{good_id}]."},
    ])
    session.ask("what should I work on?")
    turns = db.chat_session_turns("testsession")
    assert all(t["bundle_version"] == session.bundle["bundle_version"] for t in turns)
    assert turns[-1]["evidence_cited"] == [good_id]
