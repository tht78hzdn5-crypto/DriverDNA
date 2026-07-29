"""`driverdna verify-observations` — mechanical grounding for a lap reading.

The lap-analysis protocol (docs/LAP-ANALYSIS-PROTOCOL.md) puts a cheap agent
to work reading raw traces. The whole arrangement only pays off if a claim
that sounds plausible but isn't in the data gets caught by a machine rather
than by a careful human read — a careful human read is the expensive thing
the arrangement exists to avoid spending.

So the same bargain the coach and chat layers already make applies here:
prose is free, numbers are not. Every quoted sample must equal the digest at
the row it cites, and every numeral in the claim must be one of those quoted
samples. Reuses `coach.grounding`'s tolerance so "does this number match"
means one thing in this repository, not two.

What this does NOT do is judge whether an observation is *interesting* or
*correct as driving analysis*. It checks that the numbers are real. Judgment
stays with the reviewer, and the point of the check is that the reviewer
never spends attention on a fabricated number.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from driverdna.analysis.digest import build_digest
from driverdna.analysis.verify import (
    ObservationError,
    verify_observations,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from synth import run_synthetic_lap as _run
from synth import track_lap

CONFIG = DriverDNAConfig()


@pytest.fixture()
def digest(tmp_path):
    """A real digest to check observations against."""
    out = tmp_path / "blind"
    with Database.open(":memory:") as db:
        for i in range(4):
            _run(db, track_lap(src=f"syn-{i}.csv"), car="TestCar", track="SynthRing",
                 session_key=f"s{i // 2}", config=CONFIG)
        build_digest(db, out_dir=out)
    return out


@pytest.fixture()
def sample(digest):
    """A real (lap dir, corner, row, channel, value) drawn from the digest."""
    manifest = json.loads((digest / "manifest.json").read_text())
    lap = manifest["cohorts"][0]["laps"][0]
    csv_path = digest / lap["files"][0]
    header = csv_path.read_text().splitlines()[0].split(",")
    row = csv_path.read_text().splitlines()[3].split(",")
    channel = header[1 + header[1:].index("speed")]
    return {
        "lap_dir": lap["dir"],
        "corner_id": Path(lap["files"][0]).stem,
        "row": int(row[0]),
        "channel": channel,
        "value": float(row[header.index(channel)]),
    }


def _obs(sample, **overrides):
    o = {
        "obs_id": "T-001",
        "lap": sample["lap_dir"],
        "corner_id": sample["corner_id"],
        "phase": "mid",
        "class": "phenomenon",
        "claim": "the car is still carrying speed here",
        "quoted": [
            {
                "row": sample["row"],
                "channel": sample["channel"],
                "value": sample["value"],
            }
        ],
        "confidence": "likely",
    }
    o.update(overrides)
    return o


def _write(tmp_path, *observations) -> Path:
    p = tmp_path / "obs.jsonl"
    p.write_text("\n".join(json.dumps(o) for o in observations) + "\n")
    return p


# --- the quoted sample must actually be in the trace ------------------------


def test_a_faithfully_quoted_observation_passes(digest, sample, tmp_path):
    report = verify_observations(_write(tmp_path, _obs(sample)), digest)
    assert report.passed == 1 and report.failed == 0
    assert report.results[0].ok


def test_a_fabricated_value_is_rejected(digest, sample, tmp_path):
    """The failure this whole mechanism exists for: a number that reads
    plausibly and is not in the data."""
    obs = _obs(sample)
    obs["quoted"][0]["value"] = sample["value"] + 17.5
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.failed == 1
    assert "does not match" in " ".join(report.results[0].problems).lower()


def test_a_quote_from_a_row_outside_the_slice_is_rejected(digest, sample, tmp_path):
    obs = _obs(sample)
    obs["quoted"][0]["row"] = 10_000_000
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.failed == 1
    assert any("row" in p for p in report.results[0].problems)


def test_a_quote_from_an_unknown_channel_is_rejected(digest, sample, tmp_path):
    obs = _obs(sample)
    obs["quoted"][0]["channel"] = "tyre_temp"
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.failed == 1
    assert any("channel" in p for p in report.results[0].problems)


def test_an_unknown_lap_or_corner_is_rejected(digest, sample, tmp_path):
    report = verify_observations(_write(tmp_path, _obs(sample, lap="NOPE")), digest)
    assert report.failed == 1
    report = verify_observations(
        _write(tmp_path, _obs(sample, corner_id="C99")), digest
    )
    assert report.failed == 1


def test_honest_rounding_is_accepted(digest, sample, tmp_path):
    """A rater writing 43.5 for 43.489... is being readable, not inventing.
    Rejecting that would train the rater to paste noise."""
    obs = _obs(sample)
    obs["quoted"][0]["value"] = round(sample["value"], 1)
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.passed == 1, report.results[0].problems


# --- every numeral in the prose must be one of the quoted samples -----------


def test_a_number_in_the_claim_that_is_not_quoted_is_rejected(digest, sample, tmp_path):
    obs = _obs(sample, claim="brake pressure peaks at 0.93 before turn-in")
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.failed == 1
    assert any("0.93" in p for p in report.results[0].problems)


def test_a_number_in_the_claim_that_is_quoted_passes(digest, sample, tmp_path):
    obs = _obs(sample, claim=f"speed is still {sample['value']:.1f} here")
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.passed == 1, report.results[0].problems


def test_prose_with_no_numbers_passes(digest, sample, tmp_path):
    obs = _obs(sample, claim="the throttle comes back on smoothly, no stabs")
    assert verify_observations(_write(tmp_path, obs), digest).passed == 1


# --- the explicit null answer ----------------------------------------------


def test_nothing_notable_needs_no_quote(digest, sample, tmp_path):
    """A rater must be able to say 'nothing here' — and must say it, so that
    silence is never mistaken for an unread corner."""
    obs = _obs(sample, **{"class": "nothing_notable", "claim": "", "quoted": []})
    assert verify_observations(_write(tmp_path, obs), digest).passed == 1


def test_a_substantive_class_must_quote_something(digest, sample, tmp_path):
    obs = _obs(sample, quoted=[])
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.failed == 1


# --- malformed input fails loudly, never silently -------------------------


def test_a_malformed_line_is_reported_not_skipped(digest, tmp_path):
    p = tmp_path / "obs.jsonl"
    p.write_text('{"obs_id": "T-1", not json\n')
    with pytest.raises(ObservationError):
        verify_observations(p, digest)


def test_a_missing_required_field_is_rejected(digest, sample, tmp_path):
    obs = _obs(sample)
    del obs["corner_id"]
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.failed == 1


def test_an_unknown_class_is_rejected(digest, sample, tmp_path):
    obs = _obs(sample, **{"class": "definitely_a_problem"})
    report = verify_observations(_write(tmp_path, obs), digest)
    assert report.failed == 1


def test_duplicate_obs_ids_are_rejected(digest, sample, tmp_path):
    report = verify_observations(_write(tmp_path, _obs(sample), _obs(sample)), digest)
    assert report.failed >= 1


# --- the report is the thing a reviewer reads ------------------------------


def test_report_renders_and_separates_passed_from_failed(digest, sample, tmp_path):
    bad = _obs(sample, obs_id="T-002", claim="peaks at 0.93")
    report = verify_observations(_write(tmp_path, _obs(sample), bad), digest)
    md = report.to_markdown()
    assert "T-001" in md and "T-002" in md
    assert "0.93" in md
    assert report.passed == 1 and report.failed == 1
