"""M7a: the coaching ontology must reference real taxonomy techniques,
detectors, and metrics only — no invented ids, no drift from M6's own
signal_status per technique."""

from driverdna.coaching.ontology import (
    PRINCIPLES,
    AlwaysEligible,
    DetectorGate,
    FindingGate,
    MetricCVGate,
    principles_for_fundamental,
)
from driverdna.metrics.detectors import run_detectors
from driverdna.metrics.technique import METRIC_DEFS
from driverdna.model.taxonomy import FUNDAMENTALS, TECHNIQUES, SignalStatus
from driverdna.config import DriverDNAConfig


def _real_detector_names() -> set[str]:
    class _Landmarks:
        brake_release = 100
        turn_in = 110

    class _Span:
        landmarks = _Landmarks()

    metrics = {
        "throttle_brake_overlap_s": 0.1,
        "steering_corrections": 0.0,
        "throttle_modulation_count": 0.0,
        "coast_s": 0.1,
    }
    results = run_detectors(None, _Span(), metrics, DriverDNAConfig())
    return {r.detector for r in results}


def test_every_principle_references_a_real_technique():
    for p in PRINCIPLES.values():
        assert p.technique in TECHNIQUES, p.id


def test_every_principle_fundamental_matches_its_technique():
    for p in PRINCIPLES.values():
        assert TECHNIQUES[p.technique].fundamental == p.fundamental, p.id


def test_every_principle_signal_status_matches_its_technique():
    for p in PRINCIPLES.values():
        assert TECHNIQUES[p.technique].signal_status == p.signal_status, p.id


def test_detector_gates_reference_real_detectors():
    real = _real_detector_names()
    for p in PRINCIPLES.values():
        if isinstance(p.gate, DetectorGate):
            assert p.gate.detector in real, p.id


def test_detector_gates_reference_the_techniques_own_detector():
    for p in PRINCIPLES.values():
        if isinstance(p.gate, DetectorGate):
            assert p.gate.detector in TECHNIQUES[p.technique].detectors, p.id


def test_metric_cv_gates_reference_real_metrics_or_wildcard():
    for p in PRINCIPLES.values():
        if isinstance(p.gate, MetricCVGate):
            assert p.gate.metric == "*" or p.gate.metric in METRIC_DEFS, p.id


def test_band_phase_is_a_real_fundamental_phase_or_none():
    for p in PRINCIPLES.values():
        if p.band_phase is not None:
            assert p.band_phase in FUNDAMENTALS[p.fundamental].phases, p.id


def test_no_signal_principles_carry_self_check_never_expression_or_drill():
    for p in PRINCIPLES.values():
        if p.signal_status is SignalStatus.NO_SIGNAL:
            assert p.self_check is not None, p.id
            assert p.coaching_expression is None, p.id
            assert p.drill is None, p.id
            assert isinstance(p.gate, AlwaysEligible), p.id
            assert p.band_phase is None, p.id
            assert p.evidence_binding == (), p.id


def test_measured_and_proxy_principles_carry_expression_and_drill_never_self_check():
    for p in PRINCIPLES.values():
        if p.signal_status is not SignalStatus.NO_SIGNAL:
            assert p.coaching_expression, p.id
            assert p.drill, p.id
            assert p.self_check is None, p.id


def test_finding_gate_phase_is_real():
    for p in PRINCIPLES.values():
        if isinstance(p.gate, FindingGate):
            assert p.gate.phase in FUNDAMENTALS[p.fundamental].phases, p.id


def test_ids_are_unique_and_namespaced_by_technique():
    for tid, p in PRINCIPLES.items():
        assert tid == p.id
        assert p.id.startswith(f"cp.{p.technique}.")


def test_principles_for_fundamental():
    vision = principles_for_fundamental("vision")
    assert {p.id for p in vision} == {"cp.eye_line.look_further"}
    rotation = principles_for_fundamental("rotation")
    assert {p.id for p in rotation} == {
        "cp.turn_in.one_commitment",
        "cp.coasting.always_working",
        "cp.rotation_efficiency.carry_the_middle",
    }


def test_nine_seed_principles():
    assert len(PRINCIPLES) == 9
