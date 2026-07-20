"""M6a: the taxonomy must account for every real metric and detector — no
orphans, nothing invented. Cross-checked against the actual engine, not a
copy of it."""

from driverdna.config import DriverDNAConfig
from driverdna.metrics.detectors import run_detectors
from driverdna.metrics.technique import METRIC_DEFS
from driverdna.model.taxonomy import (
    FUNDAMENTALS,
    TECHNIQUES,
    SignalStatus,
    detector_fundamentals,
    fundamental_detectors,
    fundamental_metrics,
    fundamental_techniques,
    metric_fundamentals,
)


def _real_detector_names() -> set[str]:
    # Drive the real dispatcher (run_detectors) so this stays true to the
    # engine rather than reimplementing its logic. Supply every input every
    # detector needs so none short-circuits to None.
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


def test_every_metric_maps_to_at_least_one_technique():
    mapped = {m for t in TECHNIQUES.values() for m in t.metrics}
    missing = set(METRIC_DEFS) - mapped
    assert not missing, f"metrics with no technique: {missing}"


def test_every_technique_metric_is_real():
    invented = {m for t in TECHNIQUES.values() for m in t.metrics} - set(METRIC_DEFS)
    assert not invented, f"taxonomy references metrics that don't exist: {invented}"


def test_every_detector_maps_to_a_technique():
    real = _real_detector_names()
    assert real, "sanity: detector name extraction found nothing"
    mapped = {d for t in TECHNIQUES.values() for d in t.detectors}
    assert real <= mapped, f"detectors with no technique: {real - mapped}"


def test_every_technique_detector_is_real():
    real = _real_detector_names()
    invented = {d for t in TECHNIQUES.values() for d in t.detectors} - real
    assert not invented, f"taxonomy references detectors that don't exist: {invented}"


def test_every_technique_belongs_to_a_declared_fundamental():
    for technique in TECHNIQUES.values():
        assert technique.fundamental in FUNDAMENTALS, technique.id


def test_fundamental_techniques_reference_back_correctly():
    for fid, fundamental in FUNDAMENTALS.items():
        for tid in fundamental.techniques:
            assert TECHNIQUES[tid].fundamental == fid


def test_no_signal_techniques_carry_no_metrics_or_detectors():
    # The whole point: a no_signal technique must have nothing to point to,
    # or "no signal" would be a lie.
    for technique in TECHNIQUES.values():
        if technique.signal_status is SignalStatus.NO_SIGNAL:
            assert not technique.metrics and not technique.detectors, technique.id


def test_vision_and_tire_signal_status_match_unavailable_fundamentals():
    # These two are named explicitly in report/payload.py's
    # UNAVAILABLE_FUNDAMENTALS and ARCHITECTURE_VISION.md as never-measured.
    assert TECHNIQUES["eye_line"].signal_status is SignalStatus.NO_SIGNAL
    assert TECHNIQUES["tire_utilization"].signal_status is SignalStatus.NO_SIGNAL
    assert FUNDAMENTALS["vision"].signal_status is SignalStatus.NO_SIGNAL


def test_vehicle_management_is_proxy_not_measured_or_no_signal():
    # Real signal (ABS rate) but most of its techniques are no_signal — the
    # exact case the fundamental-level derivation exists to handle.
    assert FUNDAMENTALS["vehicle_management"].signal_status is SignalStatus.PROXY


def test_commitment_is_proxy():
    assert FUNDAMENTALS["commitment"].signal_status is SignalStatus.PROXY


def test_fully_measured_fundamentals():
    for fid in ("braking", "rotation", "corner_exit", "consistency"):
        assert FUNDAMENTALS[fid].signal_status is SignalStatus.MEASURED, fid


def test_metric_fundamentals_lookup():
    assert "braking" in metric_fundamentals("brake_point_dist_pct")
    assert "commitment" in metric_fundamentals("brake_point_dist_pct")
    assert metric_fundamentals("min_speed_kmh") == ("rotation",)


def test_detector_fundamentals_lookup():
    assert detector_fundamentals("coast-window") == ("rotation",)
    assert detector_fundamentals("throttle-monotonic") == ("corner_exit",)


def test_fundamental_metrics_and_detectors_helpers():
    assert set(fundamental_metrics("braking")) == {
        "brake_point_dist_pct", "brake_application_rate", "brake_peak",
        "brake_release_duration_s", "trail_brake_overlap_s", "throttle_brake_overlap_s",
    }
    assert set(fundamental_detectors("braking")) == {
        "brake-release-taper", "throttle-brake-overlap",
    }
    assert fundamental_metrics("vision") == ()
    assert fundamental_detectors("vision") == ()


def test_fundamental_techniques_helper_returns_technique_objects():
    techs = fundamental_techniques("corner_exit")
    assert {t.id for t in techs} == {
        "throttle_pickup", "throttle_modulation", "exit_acceleration",
    }
