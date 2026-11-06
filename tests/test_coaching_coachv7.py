"""Coach-v7 tests: no bare percentages in model prose.

Two live coach-v6 runs for Navarra (gemini-3.6-flash, 2026-11-06) were
rejected by the mechanical grounding validator. The tripwire both times:
the model wrote "a single, uninterrupted squeeze to 100%" for full
throttle. "100%" is ordinary coaching language, not a measurement — but
the validator treats any number+unit as a measurement claim, and 100.0
is not in the payload number pool, so the whole plan is rejected. The
first attempt also invented "27.26% of braking time", a number that is
not in the data at all — a genuine catch by the same rule.

The fix is prompt-side only: the prompt now says pedal positions are
words, never numbers ("full throttle", never "100%"), and never write a
percentage unless that number appears in the payload. The validator is
untouched — it was right both times. This file pins the rule's wording
and the validator behavior on both sides of it: words for pedal
positions pass, the bare "100%" is still rejected.

The "100%" rejection test uses the real fixture cohort (GR86/Spa), not
the synthetic laps: the synthetic payload's driver-model beliefs score
exactly 100.0, so "100%" passes against it — the live Navarra payload
has no 100 in its pool, and neither does the fixture cohort's.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driverdna.chat.session import CHAT_PROMPT_VERSION, CHAT_SYSTEM_PROMPT
from driverdna.cli import app as cli_app
from driverdna.coach.payload import build_coach_payload
from driverdna.coach.provider import PROMPT_VERSION, SYSTEM_PROMPT
from driverdna.coach.validate import CoachValidationError, validate_coach_output
from driverdna.coaching.eras import TENDENCY_MODEL_VERSION
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.report.payload import PAYLOAD_VERSION
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}
FIXTURE_COHORT = {"driver": "owner", "car": "GR86", "track": "Spa-Francorchamps"}
C01_WARP_WINDOW = (0.19, 0.22)

PEDAL_RULE = "Pedal positions are words, never numbers"
NO_SIGNAL_PRINCIPLE = "cp.eye_line.look_further"


def _flat(prompt):
    # The prompt wraps lines; the rule is one sentence across the wrap.
    return " ".join(prompt.split())


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


@pytest.fixture()
def payload(db):
    return build_coach_payload(db, **COHORT, config=CONFIG)


@pytest.fixture(scope="module")
def fixture_payload(tmp_path_factory):
    # Real fixture telemetry (GR86/Spa, 11 laps), the cohort the live
    # acceptance runs used. Its number pool contains no 100.0, so the
    # exact live "squeeze to 100%" phrasing is rejected against it.
    root = tmp_path_factory.mktemp("coachv7-fixture")
    db_path = root / "c.db"
    assert CliRunner().invoke(
        cli_app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)]
    ).exit_code == 0
    with Database.open(str(db_path)) as database:
        yield build_coach_payload(database, **FIXTURE_COHORT, config=CONFIG)


def _shown_finding(payload):
    return next(f for f in payload["report"]["findings"] if f["shown"])


def _base_output(payload, plan_action):
    f = _shown_finding(payload)
    return {
        "measured_priorities": [
            {
                "finding_id": f["finding_id"],
                "evidence_ids": list(f["evidence_ids"][:2]),
                "why": "The exit here varies more lap to lap than anywhere else on the lap.",
            }
        ],
        "coaching_priorities": [
            {
                "coaching_principle_id": NO_SIGNAL_PRINCIPLE,
                "corner_id": None,
                "expression": "Say out loud where you're looking the instant you turn in.",
                "why": "Coaching hypothesis, not a measurement — we can't see your eyes.",
                "evidence_ids": [],
            }
        ],
        "coaching_plan": [
            {
                "title": "Commit to one exit",
                "focus": "One uninterrupted throttle application out of the corner.",
                "actions": [plan_action],
            }
        ],
        "hypotheses": [
            {
                "statement": "The inconsistency may come from a moving brake point.",
                "basis": "pattern across the flagged laps",
                "confidence": "medium",
                "evidence_ids": [f["finding_id"]],
            }
        ],
        "incident_explanations": [],
    }


def _fixture_output(payload, plan_action):
    # A valid output built from the fixture payload's own data: a shown
    # finding and the cohort's own headline coaching principle.
    f = _shown_finding(payload)
    headline = payload["report"]["coaching"]["headline"]
    return {
        "measured_priorities": [
            {
                "finding_id": f["finding_id"],
                "evidence_ids": list(f["evidence_ids"][:2]),
                "why": f"Slower laps lose {f['seconds']:.3f} s here; the "
                       "spread supports focusing on it first.",
            }
        ],
        "coaching_priorities": [
            {
                "coaching_principle_id": headline["coaching_principle_id"],
                "corner_id": None,
                "expression": headline["coaching_expression"],
                "why": "The coast windows repeat across the flagged laps.",
                "evidence_ids": list(headline["evidence_ids"][:2]),
            }
        ],
        "coaching_plan": [
            {
                "title": "Commit to one exit",
                "focus": "One uninterrupted throttle application out of the corner.",
                "actions": [plan_action],
            }
        ],
        "hypotheses": [
            {
                "statement": "The inconsistency may come from a moving brake point.",
                "basis": "pattern across the flagged laps",
                "confidence": "medium",
                "evidence_ids": [f["finding_id"]],
            }
        ],
        "incident_explanations": [],
    }


def _validate(payload, output):
    return validate_coach_output(json.dumps(output), payload["report"])


# --- versions: prompts bump, everything else pinned ----------------------------


def test_coachv7_versions():
    # Coach-v7 / chat-v6 bump; payload, tendency, scoring, ontology untouched.
    assert PROMPT_VERSION == "coach-v7"
    assert CHAT_PROMPT_VERSION == "chat-v6"
    assert PAYLOAD_VERSION == 14
    assert TENDENCY_MODEL_VERSION == "tendency-v3"


# --- prompt wording --------------------------------------------------------------


def test_coach_prompt_pedal_rule():
    flat = _flat(SYSTEM_PROMPT)
    assert flat.count(PEDAL_RULE) == 1
    assert '"full throttle", never "100%"' in flat
    assert '"full brake", never "100% brake"' in flat


def test_chat_prompt_pedal_rule():
    flat = _flat(CHAT_SYSTEM_PROMPT)
    assert flat.count(PEDAL_RULE) == 1
    assert '"full throttle", never "100%"' in flat
    assert '"full brake", never "100% brake"' in flat


# --- validator behavior, both sides of the rule ---------------------------------


def test_plan_action_full_throttle_words_pass(fixture_payload):
    output = _fixture_output(
        fixture_payload,
        "Count throttle applications aloud out of the corner to ensure a "
        "single, uninterrupted squeeze to full throttle.",
    )
    _validate(fixture_payload, output)


def test_plan_action_bare_percentage_rejected(fixture_payload):
    # The exact live phrasing, against a payload whose number pool holds
    # no 100.0 — the validator must still reject it.
    output = _fixture_output(
        fixture_payload,
        "Count throttle applications aloud out of the corner to ensure a "
        "single, uninterrupted squeeze to 100%.",
    )
    with pytest.raises(CoachValidationError) as excinfo:
        _validate(fixture_payload, output)
    assert any("100.0 %" in v for v in excinfo.value.violations)


def test_invented_percentage_rejected(payload):
    # The other live-run tripwire: a percentage that is not in the data
    # at all. Same rule, genuine catch.
    output = _base_output(payload, "Pick one brake marker and keep it for a session.")
    output["measured_priorities"][0]["why"] = (
        "The car spends 27.26% of braking time above the target pressure."
    )
    with pytest.raises(CoachValidationError) as excinfo:
        _validate(payload, output)
    assert any("27.26 %" in v for v in excinfo.value.violations)
