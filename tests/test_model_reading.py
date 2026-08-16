"""A51 read-v1: the strongest/weakest reading.

Half the stated product goal is "make it obvious what the driver's strengths
are", and nothing in the engine represented a strength at all — the word did
not appear anywhere in `src/`. This is that reading: rank-only, measured-only,
and gated rather than guessed.

The three rules under test are the ones that keep it honest:

  1. verdict from MEASURED fundamentals only — `vehicle_management` scores 0.0
     off a single proxy component and would otherwise be named the driver's
     greatest weakness on the least-supported number in the system;
  2. no absolute bands — the 0-100 scores are not calibrated against any
     driver population, so "strong" is a rank, never an assertion;
  3. a gate that fails states why, never a shrugged verdict.
"""

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.model.reading import READING_VERSION, build_reading
from driverdna.model.scoring import Belief
from driverdna.model.taxonomy import SignalStatus

CONFIG = DriverDNAConfig()


def _belief(fid, score, status=SignalStatus.MEASURED, confidence=0.6, basis=None):
    return Belief(
        fundamental=fid, signal_status=status, score=score, confidence=confidence,
        evidence_count=12, trend="unavailable", insufficient_reason=None,
        scoring_model_version="dm-v2", taxonomy_version="pyramid-v1",
        components={}, basis_reason=basis,
    )


def _real_corpus():
    """The bundled 12-lap demo corpus's actual beliefs (2026-08-16)."""
    return {
        "braking": _belief("braking", 80.52),
        "corner_exit": _belief("corner_exit", 65.19),
        "rotation": _belief("rotation", 60.17),
        "consistency": _belief("consistency", 34.31, basis="Scored on consistency alone."),
        "commitment": _belief("commitment", 56.10, SignalStatus.PROXY, 0.5),
        "vehicle_management": _belief("vehicle_management", 0.0, SignalStatus.PROXY, 0.5),
        "vision": _belief("vision", None, SignalStatus.NO_SIGNAL, 0.0),
    }


def test_reading_on_the_real_corpus_names_braking_and_consistency():
    """The answer a coach would actually give for this driver."""
    r = build_reading(_real_corpus(), CONFIG)
    assert r["strongest"]["fundamental"] == "braking"
    assert r["weakest"]["fundamental"] == "consistency"
    assert r["verdict_reason"] is None
    assert r["reading_version"] == READING_VERSION


def test_a_proxy_is_never_the_verdict_even_when_it_is_the_lowest_score():
    """vehicle_management's 0.0 rests on one indirect component. Naming it
    the driver's weakness would headline the least-supported number here."""
    r = build_reading(_real_corpus(), CONFIG)
    assert r["weakest"]["fundamental"] != "vehicle_management"
    assert "vehicle_management" in r["excluded_proxy"]


def test_proxies_still_appear_in_the_ordering():
    """Excluded from the verdict is not excluded from the page."""
    r = build_reading(_real_corpus(), CONFIG)
    ranked = [e["fundamental"] for e in r["ordering"]]
    assert "vehicle_management" in ranked and "commitment" in ranked
    assert ranked == sorted(
        ranked, key=lambda f: -_real_corpus()[f].score,
    )


def test_no_signal_fundamental_never_enters_the_ordering():
    r = build_reading(_real_corpus(), CONFIG)
    assert "vision" not in [e["fundamental"] for e in r["ordering"]]


def test_narrow_basis_travels_with_the_verdict():
    """consistency is scored on one component of three — the driver is told
    that at the moment it is named their weakness, not a click away."""
    r = build_reading(_real_corpus(), CONFIG)
    assert r["weakest"]["basis_reason"] is not None


def test_too_few_measured_fundamentals_states_why_and_gives_no_verdict():
    beliefs = {
        "braking": _belief("braking", 80.0),
        "rotation": _belief("rotation", 20.0),
        "commitment": _belief("commitment", 50.0, SignalStatus.PROXY),
    }
    r = build_reading(beliefs, CONFIG)
    assert r["strongest"] is None and r["weakest"] is None
    assert "2 measured" in r["verdict_reason"]


def test_scores_too_close_together_give_no_verdict():
    beliefs = {
        "braking": _belief("braking", 62.0),
        "rotation": _belief("rotation", 60.0),
        "corner_exit": _belief("corner_exit", 61.0),
    }
    r = build_reading(beliefs, CONFIG)
    assert r["strongest"] is None
    assert "separation" in r["verdict_reason"]


def test_reading_is_deterministic_and_breaks_ties_by_name():
    beliefs = {
        "rotation": _belief("rotation", 70.0),
        "braking": _belief("braking", 70.0),
        "corner_exit": _belief("corner_exit", 20.0),
    }
    first = build_reading(beliefs, CONFIG)
    assert first == build_reading(beliefs, CONFIG)
    assert first["strongest"]["fundamental"] == "braking"  # tie -> name order


def test_reading_states_no_absolute_band(*_):
    """Rank-only is the owner's decision (A51). A band word here would be an
    uncalibrated absolute claim."""
    r = build_reading(_real_corpus(), CONFIG)
    assert r["basis"] == "rank_within_driver"
    flat = repr(r).lower()
    for banned in ("excellent", "poor", "strong for", "world class", "average"):
        assert banned not in flat


@pytest.mark.parametrize("scores", [{}, {"braking": None}])
def test_empty_or_unscored_model_gives_no_verdict(scores):
    beliefs = {k: _belief(k, v) for k, v in scores.items()}
    r = build_reading(beliefs, CONFIG)
    assert r["strongest"] is None
    assert r["verdict_reason"]
