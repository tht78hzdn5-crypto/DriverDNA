"""A52: a CV-banded principle can reach the headline.

`headline_eligible` was `magnitude_kind == "seconds_lost" and band in
(notable, major)`. Repeatability is banded by coefficient of variation, so
`same_lap_twice` was excluded from the headline pool **by construction,
permanently** — no matter how bad it got. On the owner's real corpus that
meant the Driver Model named `consistency` the weakest fundamental (34.3, the
lowest measured score, firing at 16 corners) while the coaching layer was
structurally incapable of ever telling them to work on it.

Lifting the restriction exposes the reason it existed: the ranker picked
`max(..., key=magnitude)`, which compares 0.591 seconds against a CV of 2.724
and takes the CV every time — not because it is worse, but because CVs are
bigger numbers than seconds. A unit-free key is what makes the pool
comparable.
"""

import pytest

from driverdna.coaching.engine import CoachingCandidate, _severity, select_coaching
from driverdna.config import DriverDNAConfig
from driverdna.model.taxonomy import SignalStatus

CONFIG = DriverDNAConfig()
COACH = CONFIG.coaching


def _c(principle_id, kind, magnitude, band, corner="C01"):
    return CoachingCandidate(
        principle_id=principle_id, signal_status=SignalStatus.MEASURED,
        corner_id=corner, gap_band=band, magnitude=magnitude,
        magnitude_kind=kind, n=40, thin_evidence=False, evidence_ids=(),
        headline_eligible=band in ("notable", "major"),
    )


SECONDS = "seconds_lost"
CV = "coefficient_of_variation"


# --- eligibility -----------------------------------------------------------


def test_a_cv_banded_principle_can_now_be_headline_eligible():
    assert _c("cp.repeatability.same_lap_twice", CV, 2.724, "major").headline_eligible


def test_a_negligible_candidate_is_still_never_headline_eligible():
    assert not _c("cp.repeatability.same_lap_twice", CV, 1.0, "negligible").headline_eligible
    assert not _c("cp.coasting.always_working", SECONDS, 0.01, "negligible").headline_eligible


# --- the unit-free ranking key --------------------------------------------


def test_severity_expresses_each_magnitude_against_its_own_major_threshold():
    """Seconds and CV live on different scales; the ratio to each kind's own
    'major' floor is what makes them comparable at all."""
    assert _severity(_c("x", SECONDS, COACH.gap_band_major_s, "major"), COACH) == pytest.approx(1.0)
    assert _severity(_c("x", CV, COACH.cv_band_major, "major"), COACH) == pytest.approx(1.0)


def test_a_bigger_cv_number_no_longer_beats_a_worse_seconds_loss():
    """The bug a naive lift would have introduced: 2.724 > 0.591 as raw
    numbers, but 0.591 s is 1.7x its major floor while CV 2.724 is 1.36x
    its own."""
    seconds = _c("cp.turn_in.one_commitment", SECONDS, 0.591, "major", "C14")
    cv = _c("cp.repeatability.same_lap_twice", CV, 2.724, "major", "C02")
    selection = select_coaching([cv, seconds])
    assert selection["headline"] is seconds


def test_a_genuinely_worse_cv_does_take_the_headline():
    """The restriction is lifted, not merely re-hidden behind the ranking."""
    seconds = _c("cp.turn_in.one_commitment", SECONDS, 0.36, "major", "C14")
    cv = _c("cp.repeatability.same_lap_twice", CV, 3.6, "major", "C02")
    assert select_coaching([cv, seconds])["headline"] is cv


def test_band_outranks_severity_so_a_major_always_beats_a_notable():
    notable_but_extreme = _c("cp.repeatability.same_lap_twice", CV, 1.99, "notable")
    major_but_marginal = _c("cp.coasting.always_working", SECONDS, 0.36, "major")
    assert select_coaching([notable_but_extreme, major_but_marginal])["headline"] is major_but_marginal


def test_headline_selection_is_deterministic_on_ties():
    a = _c("cp.coasting.always_working", SECONDS, 0.70, "major", "C03")
    b = _c("cp.turn_in.one_commitment", SECONDS, 0.70, "major", "C01")
    assert select_coaching([a, b])["headline"] is a  # principle_id order
    assert select_coaching([b, a])["headline"] is a  # input order is irrelevant


# --- the key must never become a reported number ---------------------------


def test_severity_never_leaks_into_the_payload():
    """It is a sort key, not a measurement. If it reached the payload it
    would be a number with no unit that the grounding validator would then
    happily let the AI cite."""
    from driverdna.coaching.payload import _candidate_dict

    d = _candidate_dict(_c("cp.repeatability.same_lap_twice", CV, 2.724, "major"))
    assert "severity" not in d
    assert set(d) & {"severity", "severity_ratio", "rank_key"} == set()
