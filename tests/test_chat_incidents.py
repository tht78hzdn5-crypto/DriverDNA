"""Track B3 (docs/UI-V3-PLAN.md): chat sees incidents, additively.

Before this, chat/session.py's build_chat_bundle stripped the incidents
section entirely (M5-era boundary, tested by test_incidents.py). Now a
classified incident (coaching_principle_id not null) is citable, and an
unclassified/external one is not — structurally absent from
ChatSession._known_ids, so citing it is rejected the same way an unknown
finding ID already is. This file proves the change is strictly additive:
new IDs become citable; nothing that was rejected before is now accepted.
"""

import numpy as np
import pytest

from driverdna.chat.session import CHAT_PROMPT_VERSION, ChatSession, build_chat_bundle
from driverdna.config import ConfigStore, DriverDNAConfig
from driverdna.db import Database
from synth import run_synthetic_lap, track_lap

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


class MockProvider:
    def __init__(self, steps):
        self.steps = list(steps)

    def chat_step(self, system, messages, tools):
        step = self.steps.pop(0)
        return {"text": step.get("text"), "tool_calls": step.get("tool_calls", []),
                "raw_content": None}


def _lap_with_classified_spin(src):
    """Trail-brake oversteer: still braking (0.8) as the car snaps —
    classify_incident's clean brake-floor signature (incidents/classify.py)."""
    lap = track_lap(src=src)
    at = 720
    lap.steering_deg[at : at + 12] = np.linspace(-80.0, 80.0, 12)
    lap.yaw_rate[at : at + 12] = 1.0
    lap.speed[at : at + 20] = 5.0
    lap.brake[at : at + 12] = 0.8
    return lap


def _lap_with_unclassified_spin(src):
    """Same rotation/speed signature, but no clean pedal signature (brake
    off, throttle near zero and unchanged) — ambiguous, stays unclassified
    (mirrors test_incidents.py::test_ambiguous_snap_stays_unclassified)."""
    lap = track_lap(src=src)
    at = 720
    lap.steering_deg[at : at + 12] = np.linspace(-80.0, 80.0, 12)
    lap.yaw_rate[at : at + 12] = 1.0
    lap.speed[at : at + 20] = 5.0
    lap.brake[at : at + 12] = 0.0
    lap.throttle[at - 10 : at + 12] = 0.1
    return lap


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        run_synthetic_lap(database, _lap_with_classified_spin("classified.csv"), session_key="s1")
        run_synthetic_lap(database, _lap_with_unclassified_spin("unclassified.csv"), session_key="s2")
        yield database


def make_session(db, tmp_path, steps):
    store = ConfigStore(tmp_path / "config.toml", db)
    return ChatSession(
        db=db, store=store, provider=MockProvider(steps), **COHORT,
        config=CONFIG, session_id="testsession",
    )


def _incident_ids(bundle):
    events = bundle["report"]["incidents"]["events"]
    classified = [e["incident_id"] for e in events if e.get("coaching_principle_id")]
    unclassified = [e["incident_id"] for e in events if not e.get("coaching_principle_id")]
    return classified, unclassified


def test_bundle_carries_incidents_and_prompt_version_bumped(db):
    bundle = build_chat_bundle(db, **COHORT, config=CONFIG)
    assert bundle["prompt_version"] == CHAT_PROMPT_VERSION == "chat-v3"
    assert bundle["report"]["incidents"]["n"] >= 2
    classified, unclassified = _incident_ids(bundle)
    assert classified and unclassified, "fixture must produce both kinds"


def test_classified_incident_is_citable(db, tmp_path):
    bundle = build_chat_bundle(db, **COHORT, config=CONFIG)
    classified, _ = _incident_ids(bundle)
    incident_id = classified[0]
    session = make_session(db, tmp_path, [
        {"text": f"You had a trail-brake oversteer moment [{incident_id}] — "
                 "try releasing the brake a touch earlier next time."},
    ])
    result = session.ask("what happened with that spin?")
    assert "error" not in result
    assert incident_id in result["evidence"]


def test_unclassified_incident_is_not_citable(db, tmp_path):
    """The engine named no cause for this one, so the model can't cite it
    at all — a stricter, mechanically simpler bar than trying to detect
    'did the model guess a cause' in free text."""
    bundle = build_chat_bundle(db, **COHORT, config=CONFIG)
    _, unclassified = _incident_ids(bundle)
    incident_id = unclassified[0]
    session = make_session(db, tmp_path, [
        {"text": f"That was understeer [{incident_id}]."},
        {"text": f"Insufficient data to say what caused [{incident_id}]."},
    ])
    result = session.ask("what happened with that other one?")
    assert "error" in result
    assert "unknown evidence ID" in result["error"]


def test_fabricated_incident_id_still_rejected(db, tmp_path):
    """Baseline sanity: an incident_id that doesn't exist at all was
    already rejected before this change and must still be."""
    session = make_session(db, tmp_path, [
        {"text": "You spun at [incident:999999]."},
        {"text": "You spun at [incident:999999], for real this time."},
    ])
    result = session.ask("did I spin?")
    assert "error" in result
    assert "unknown evidence ID" in result["error"]
