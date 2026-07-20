"""M4 coach tests: payload, mocked-provider contract, validation rejections."""

import json

import pytest

from driverdna.coach.grounding import number_pool, unsupported_claims
from driverdna.coach.payload import build_coach_payload, evidence_universe
from driverdna.coach.validate import (
    CoachValidationError,
    render_plan_markdown,
    validate_coach_output,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}
C01_WARP_WINDOW = (0.19, 0.22)


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


def _valid_output(payload):
    f = _shown_finding(payload)
    return {
        "measured_priorities": [
            {
                "finding_id": f["finding_id"],
                "evidence_ids": list(f["evidence_ids"][:2]),
                "why": f"Slower laps lose {f['seconds']:.3f} s here; the "
                       "spread supports focusing on it first.",
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
                "statement": "The inconsistency may come from a moving "
                             "brake point rather than the line.",
                "basis": "pattern across the flagged laps",
                "confidence": "medium",
                "evidence_ids": [f["finding_id"]],
            }
        ],
    }


def test_payload_carries_report_and_history(db, payload):
    assert payload["prompt_version"] == "coach-v1"
    assert payload["report"]["cohort"]["n_laps"] == 12
    assert payload["focus_history"] == []
    shown, evidence = evidence_universe(payload["report"])
    assert shown and evidence


def test_driver_model_beliefs_are_citable_numbers_no_new_validator_needed(payload):
    # SPEC.md M6: beliefs are grounded "by the existing numeric-grounding
    # validator — a belief is just another payload number." Prove it: a
    # belief's own score/confidence values must already be in the pool the
    # unsupported-claims check validates prose against.
    dm = payload["report"]["driver_model"]
    scored = next(
        b for b in dm["beliefs"].values() if b["score"] is not None
    )
    pool = number_pool(payload["report"])
    assert scored["score"] in pool
    assert scored["confidence"] in pool
    # And an invented number that matches nothing (not even a belief) is
    # still rejected, same as any other unsupported claim.
    assert unsupported_claims("Vision is 42.7% confident.", pool)


def test_valid_output_accepted_and_rendered(payload):
    output = validate_coach_output(json.dumps(_valid_output(payload)), payload["report"])
    md = render_plan_markdown(output, payload["report"]["cohort"])
    assert "Measured priorities" in md and "Hypotheses (labeled" in md


def test_fenced_json_tolerated(payload):
    raw = "```json\n" + json.dumps(_valid_output(payload)) + "\n```"
    assert validate_coach_output(raw, payload["report"])


def test_unknown_evidence_id_rejected(payload):
    output = _valid_output(payload)
    output["measured_priorities"][0]["evidence_ids"] = ["obs:99999"]
    with pytest.raises(CoachValidationError, match="unknown evidence ID"):
        validate_coach_output(json.dumps(output), payload["report"])


def test_suppressed_finding_cannot_be_a_priority(payload):
    suppressed = next(
        f for f in payload["report"]["findings"] if not f["shown"]
    )
    output = _valid_output(payload)
    output["measured_priorities"][0]["finding_id"] = suppressed["finding_id"]
    with pytest.raises(CoachValidationError, match="not a shown finding"):
        validate_coach_output(json.dumps(output), payload["report"])


def test_invented_number_rejected(payload):
    output = _valid_output(payload)
    output["measured_priorities"][0]["why"] = "You lose 1.85 s at C01 every lap."
    with pytest.raises(CoachValidationError, match="1.85"):
        validate_coach_output(json.dumps(output), payload["report"])


def test_hypothesis_without_confidence_rejected(payload):
    output = _valid_output(payload)
    del output["hypotheses"][0]["confidence"]
    with pytest.raises(CoachValidationError, match="confidence"):
        validate_coach_output(json.dumps(output), payload["report"])


def test_malformed_json_rejected(payload):
    with pytest.raises(CoachValidationError, match="not valid JSON"):
        validate_coach_output("here is your plan!", payload["report"])


def test_accepted_output_enters_focus_history(db, payload):
    output = validate_coach_output(json.dumps(_valid_output(payload)), payload["report"])
    db.store_coach_output(
        **COHORT, payload_version=payload["report"]["payload_version"],
        prompt_version="coach-v1", model="mock", output_json=json.dumps(output),
    )
    payload2 = build_coach_payload(db, **COHORT, config=CONFIG)
    assert payload2["focus_history"] == [
        {"output_pk": 1, "plan_titles": ["Commit to one entry"]}
    ]


def test_numeric_validator_units_only():
    pool = number_pool({"a": 0.4, "b": {"c": 12}})
    assert unsupported_claims("lose 0.4 s in C01 over 3 drills", pool) == []
    assert unsupported_claims("about 0.9 s lost", pool) == ["0.9 s"]
    assert unsupported_claims("no numbers here", pool) == []


def test_coach_cli_requires_key(tmp_path, monkeypatch):
    from pathlib import Path

    from typer.testing import CliRunner

    from driverdna.cli import app

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_path = tmp_path / "c.db"
    runner = CliRunner()
    runner.invoke(
        app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)]
    )
    result = runner.invoke(
        app, ["coach", "--db", str(db_path), "--cohort", "GR86:Spa-Francorchamps"]
    )
    assert result.exit_code == 2
    assert "ANTHROPIC_API_KEY" in result.output
