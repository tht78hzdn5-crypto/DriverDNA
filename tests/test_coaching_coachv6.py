"""Coach-v6 tests: history narration rewritten, anti-repetition + anti-filler
rules, and the validator's mechanical repetition check.

Bob's 2026-10-30 direct statement supersedes the plan §9.3 premise
("shorter beats more descriptive"): he wants descriptive, detailed
coaching prose with concrete scenarios and mental models. Length alone is
not a defect; repetition and generic filler are. This file pins that:
the descriptive style instruction stays verbatim, the history rule drops
the "one short clause" bound, and the validator rejects repeated
model-authored sentences — never a length cap, and never quoted engine
text (identical coaching expressions and drills across corners are
legitimate repeats and must pass).
"""

import json

import pytest

from driverdna.chat.session import CHAT_PROMPT_VERSION, CHAT_SYSTEM_PROMPT
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
C01_WARP_WINDOW = (0.19, 0.22)

STYLE = ("Adopt an encouraging, engaging, and highly descriptive coaching "
         "style. Don't sound like a generic robot—sound like a seasoned, "
         "enthusiastic race engineer giving tailored, actionable advice. "
         "Provide concrete scenarios and detailed mental models for the "
         "driver to visualize.")
HISTORY_MARKER = "State each principle's history once, in full"
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


def _shown_finding(payload):
    return next(f for f in payload["report"]["findings"] if f["shown"])


def _base_output(payload):
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
                "title": "Commit to one entry",
                "focus": "Stabilize the corner that costs the most.",
                "actions": ["Pick one brake marker and keep it for a session."],
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


def test_coachv6_versions():
    # Coach-v6 / chat-v5 bump; payload, tendency, scoring, ontology untouched.
    assert PROMPT_VERSION == "coach-v6"
    assert CHAT_PROMPT_VERSION == "chat-v5"
    assert PAYLOAD_VERSION == 14
    assert TENDENCY_MODEL_VERSION == "tendency-v3"


# --- prompt wording --------------------------------------------------------------


def test_coach_prompt_style_instruction_unchanged():
    # The descriptive style predates v6 and stays verbatim; v6 adds no
    # descriptive instruction on top.
    assert STYLE in _flat(SYSTEM_PROMPT)
    assert STYLE in _flat(CHAT_SYSTEM_PROMPT)


def test_coach_prompt_history_rule_rewritten():
    assert _flat(SYSTEM_PROMPT).count(HISTORY_MARKER) == 1
    assert "one short clause" not in SYSTEM_PROMPT


def test_chat_prompt_history_rule_rewritten():
    assert _flat(CHAT_SYSTEM_PROMPT).count(HISTORY_MARKER) == 1
    assert "one short clause" not in CHAT_SYSTEM_PROMPT


def test_coach_prompt_anti_repetition_and_filler():
    flat = _flat(SYSTEM_PROMPT)
    assert flat.count("Each entry must add something the others do not") == 1
    assert flat.count("no named-driver anecdotes") == 1


def test_chat_prompt_anti_repetition_and_filler():
    flat = _flat(CHAT_SYSTEM_PROMPT)
    assert flat.count("Each turn must add something earlier turns did not") == 1
    assert flat.count("no named-driver anecdotes") == 1


def test_prompt_tendency_counts_preserved():
    # v6 adds no new "tendencies"/"session_states" mention: the Stage 3
    # exactly-one-instruction-class counts still hold on both prompts.
    assert SYSTEM_PROMPT.lower().count("tendencies") == 1
    assert SYSTEM_PROMPT.count("session_states") == 1
    assert CHAT_SYSTEM_PROMPT.lower().count("tendencies") == 1
    assert CHAT_SYSTEM_PROMPT.count("session_states") == 1


# --- validator: repetition check ---------------------------------------------------


def test_repeated_why_sentence_rejected(payload):
    output = _base_output(payload)
    repeated = "This has been persistent across both eras."
    output["coaching_priorities"].append(
        {
            "coaching_principle_id": NO_SIGNAL_PRINCIPLE,
            "corner_id": None,
            "expression": "A different engine expression for the second entry.",
            "why": f"Something else entirely. {repeated}",
            "evidence_ids": [],
        }
    )
    output["coaching_priorities"][0]["why"] = (
        f"Coaching hypothesis, not a measurement. {repeated}"
    )
    with pytest.raises(CoachValidationError, match="repeated sentence"):
        _validate(payload, output)


def test_repeated_hypothesis_statement_rejected(payload):
    output = _base_output(payload)
    output["hypotheses"].append(
        {
            "statement": "The inconsistency may come from a moving brake point.",
            "basis": "a second, distinct basis for the duplicate statement",
            "confidence": "low",
            "evidence_ids": output["hypotheses"][0]["evidence_ids"],
        }
    )
    with pytest.raises(CoachValidationError, match="repeated sentence"):
        _validate(payload, output)


def test_repeated_plan_focus_rejected(payload):
    output = _base_output(payload)
    output["coaching_plan"].append(
        {
            "title": "A second step",
            "focus": "Stabilize the corner that costs the most.",
            "actions": ["A distinct action for the second step."],
        }
    )
    with pytest.raises(CoachValidationError, match="repeated sentence"):
        _validate(payload, output)


def test_repeated_sentence_within_one_field_rejected(payload):
    output = _base_output(payload)
    output["measured_priorities"][0]["why"] = (
        "The exit here varies more lap to lap than anywhere else on the lap. "
        "The exit here varies more lap to lap than anywhere else on the lap."
    )
    with pytest.raises(CoachValidationError, match="repeated sentence"):
        _validate(payload, output)


def test_long_nonrepetitive_output_passes(payload):
    output = _base_output(payload)
    output["measured_priorities"][0]["why"] = (
        "The exit here varies more lap to lap than anywhere else on the lap, "
        "and the spread across the session is wide enough that the pattern "
        "reads as a habit rather than a single mistake. The mid-corner "
        "traces show the same shape lap after lap, which points at the "
        "entry rather than the exit itself."
    )
    output["coaching_priorities"][0]["why"] = (
        "Coaching hypothesis, not a measurement, offered with its self-check "
        "because no channel in the telemetry can show where the eyes point. "
        "The check itself takes one lap and needs no equipment at all."
    )
    output["hypotheses"][0]["statement"] = (
        "The inconsistency may come from a brake point that moves with "
        "traffic rather than from the chosen line through the corner."
    )
    assert _validate(payload, output)


def test_repeated_engine_expression_not_rejected(payload):
    # Scoping proof: identical ENGINE text across entries is legitimate.
    # The check targets model-authored fields only, never expressions.
    output = _base_output(payload)
    shared_expression = "Say out loud where you're looking the instant you turn in."
    output["coaching_priorities"].append(
        {
            "coaching_principle_id": NO_SIGNAL_PRINCIPLE,
            "corner_id": None,
            "expression": shared_expression,
            "why": "A wholly different reason, written for the second entry alone.",
            "evidence_ids": [],
        }
    )
    output["coaching_priorities"][0]["expression"] = shared_expression
    assert _validate(payload, output)


def test_repeated_drill_action_not_rejected(payload):
    # Scoping proof: identical plan actions (quoted engine drills) across
    # steps are legitimate; only model-authored focus text is checked.
    output = _base_output(payload)
    output["coaching_plan"].append(
        {
            "title": "A second step",
            "focus": "Hold the same marker through a full stint of laps.",
            "actions": ["Pick one brake marker and keep it for a session."],
        }
    )
    assert _validate(payload, output)


def test_entertainment_flag_sentence_not_rejected(payload):
    # The required entertainment flag is boilerplate, not model repetition:
    # two guesses carrying it must still pass.
    beliefs = payload["report"]["driver_model"]["beliefs"]
    no_signal = next(
        fid for fid, b in beliefs.items() if b["signal_status"] == "no_signal"
    )
    flag = ("This is a guess for entertainment purposes - additional data "
            "is needed for concrete grounding.")
    output = _base_output(payload)
    output["fundamental_guesses"] = [
        {"fundamental_id": no_signal,
         "guess": f"{flag} The eyes may arrive at the exit later than the hands need."},
        {"fundamental_id": no_signal,
         "guess": f"{flag} The gaze may fix on the apex instead of through it."},
    ]
    assert _validate(payload, output)


def test_short_fragment_not_rejected(payload):
    # The guard drops fragments under four words: shared two-word
    # fragments are not repetition.
    output = _base_output(payload)
    output["measured_priorities"][0]["why"] = (
        "On exit. The lap-to-lap spread here is the widest on the lap."
    )
    output["coaching_priorities"][0]["why"] = (
        "On exit. Coaching hypothesis, not a measurement."
    )
    assert _validate(payload, output)
