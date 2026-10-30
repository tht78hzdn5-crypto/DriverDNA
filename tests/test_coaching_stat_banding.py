"""SPEC.md A62: stat banding via the None dispatch.

`band_phase=None` means "band by the gate's own statistic, not by
seconds." The engine implemented that meaning for dispersion gates
only and crashed for stat gates (a legal principle configuration —
a stat gate on a phaseless fundamental — raised UnboundLocalError
at report time; BUG-052). The A62 dispatch completes it: dispersion
gate + None keeps dispersion banding, stat gate + None bands on its
own statistic with magnitude_kind "gate_statistic", and any other
gate + None raises a loud ValueError instead of the latent crash.

These tests pin the dispatch and the band scale. They do not touch
the invariant test in test_coaching_ontology.py: it sweeps all of
PRINCIPLES and passes unchanged with a None-banded stat principle,
because it constrains only non-None values.
"""

import types

import pytest

from driverdna.coaching.engine import (
    _corner_candidate,
    _severity,
    _stat_band,
    CoachingCandidate,
)
from driverdna.coaching.ontology import (
    PRINCIPLES,
    CoachingPrinciple,
    DetectorGate,
    MetricStatGate,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus

CONFIG = DriverDNAConfig()
COACH = CONFIG.coaching


def _above_gate():
    return MetricStatGate(
        metric="abs_active_ratio", stat="median", direction="above",
        floor_key="abs_active_ratio_floor",
    )


def _below_gate():
    return MetricStatGate(
        metric="exit_accel_ms2", stat="median", direction="below",
        floor_key="exit_accel_floor_ms2",
    )


# --- the band scale ------------------------------------------------------------


def test_stat_band_above_direction():
    """Multiples of the floor (1.5 notable, 2.0 major), boundaries
    inclusive — the ABS floor is 0.25, so 0.375 is notable and 0.5
    is major."""
    gate = _above_gate()
    assert _stat_band(0.25, gate, COACH) == "moderate"
    assert _stat_band(0.374, gate, COACH) == "moderate"
    assert _stat_band(0.375, gate, COACH) == "notable"
    assert _stat_band(0.499, gate, COACH) == "notable"
    assert _stat_band(0.5, gate, COACH) == "major"
    assert _stat_band(1.0, gate, COACH) == "major"


def test_stat_band_below_direction():
    """Direction-aware: below-floor statistics invert the ratio
    (floor/stat), so a smaller statistic is a louder band. The exit
    floor is 1.25: 0.625 is exactly 2.0x, major."""
    gate = _below_gate()
    assert _stat_band(1.25, gate, COACH) == "moderate"
    assert _stat_band(0.9, gate, COACH) == "moderate"
    assert _stat_band(0.8, gate, COACH) == "notable"
    assert _stat_band(0.625, gate, COACH) == "major"
    assert _stat_band(0.1, gate, COACH) == "major"


def test_stat_band_below_direction_zero_statistic_is_major():
    """A zero statistic under a below-direction gate is the maximal
    fault — major directly, with no division by zero."""
    assert _stat_band(0.0, _below_gate(), COACH) == "major"


def test_stat_band_degenerate_floor_falls_back_to_moderate():
    """A floor at or below zero defines no scale: any firing value
    reads moderate, documented, never a crash or an invented band."""
    cfg = types.SimpleNamespace(
        abs_active_ratio_floor=0.0,
        stat_band_notable_multiple=1.5,
        stat_band_major_multiple=2.0,
    )
    assert _stat_band(0.9, _above_gate(), cfg) == "moderate"


def test_stat_band_firing_implies_at_least_moderate():
    """Firing implies the statistic crossed its floor, so the ratio
    is >= 1.0 in both directions — a stat-banded candidate is never
    negligible, unlike a seconds-banded one with tiny loss."""
    assert _stat_band(0.25, _above_gate(), COACH) != "negligible"
    assert _stat_band(1.25, _below_gate(), COACH) != "negligible"


# --- the dispatch --------------------------------------------------------------


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def _detector_principle_none_banded():
    return CoachingPrinciple(
        id="cp.test.detector_none_banded",
        technique="brake_release", fundamental="braking",
        signal_status=SignalStatus.MEASURED,
        driving_principle="fabricated for the dispatch contract",
        gate=DetectorGate(detector="test-detector"),
        band_phase=None,
    )


def test_none_band_with_detector_gate_raises_loudly(db):
    """The old code read an unbound `dispersion` here (latent
    UnboundLocalError). The dispatch replaces it with a contract
    error naming the principle. No shipped principle occupies this
    state — detector principles all carry a set band_phase — so
    this test fabricates one rather than mutating PRINCIPLES."""
    principle = _detector_principle_none_banded()
    with pytest.raises(ValueError, match="cp.test.detector_none_banded"):
        _corner_candidate(
            db, principle, "C01", driver="owner", car="TestCar",
            track="SynthRing",
            detector_table={"C01": {"test-detector": (5, 5)}},
            metric_table={}, findings_by_corner_phase={},
            loss={"per_corner": {}}, cfg=CONFIG, min_trigger_rate=0.5,
            metric_reference={}, unit_reference={},
        )


def test_stat_gate_none_band_has_nonzero_floor_pin():
    """Shipped-principle pin: every MetricStatGate principle banded
    on None must have a nonzero config floor, or the degenerate
    moderate fallback would be its shipped behavior instead of a
    user-config edge."""
    pinned = [
        p for p in PRINCIPLES.values()
        if isinstance(p.gate, MetricStatGate) and p.band_phase is None
    ]
    assert pinned, "at least the ABS principle must occupy this state"
    for p in pinned:
        assert getattr(COACH, p.gate.floor_key) > 0, p.id


def test_gate_statistic_flows_through_severity_unchanged():
    """_severity is unchanged by A62: its else branch already covers
    non-seconds kinds, dividing by the dispersion major floor. A
    gate_statistic candidate therefore ranks at magnitude / 2.0 —
    the acknowledged cross-kind approximation the design states,
    pinned so a future change cannot silently alter it."""
    c = CoachingCandidate(
        principle_id="cp.abs_usage.stay_off_the_abs",
        signal_status=SignalStatus.MEASURED,
        corner_id="C01", gap_band="major", magnitude=0.5,
        magnitude_kind="gate_statistic", n=20, thin_evidence=False,
        evidence_ids=(), headline_eligible=True,
    )
    assert _severity(c, COACH) == pytest.approx(0.5 / COACH.dispersion_band_major)
