"""PrincipleDetectors: canonical technique checks, source-tagged vs-principle (M2).

Each detector compares one deterministic metric against a configurable
threshold and carries a plain-language rationale — the canonical principle it
encodes — in its output. A detector returns None when its inputs don't exist
on a corner (no braking -> no release check): absence of data is never a
finding. Detectors flag; they do not rank — attribution (M3) prices findings
in seconds, separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from driverdna.config import DriverDNAConfig
from driverdna.corners.segmenter import CornerSpan
from driverdna.ingest.contract import SAMPLE_RATE_HZ
from driverdna.ingest.parser import TelemetryLap

SOURCE_TAG = "vs-principle"


@dataclass(frozen=True)
class DetectorResult:
    detector: str  # slug, stable across versions
    triggered: bool
    value: float  # the measured quantity the threshold applies to
    threshold: float  # the configured limit in force when evaluated
    unit: str
    rationale: str  # plain language: the principle and what was seen
    source: str = SOURCE_TAG


def _release_taper(lap, span, metrics, cfg) -> DetectorResult | None:
    lm = span.landmarks
    if lm.brake_release is None or lm.turn_in is None:
        return None
    gap_s = (lm.turn_in - lm.brake_release) / SAMPLE_RATE_HZ
    return DetectorResult(
        detector="brake-release-taper",
        triggered=gap_s > cfg.release_gap_max_s,
        value=gap_s,
        threshold=cfg.release_gap_max_s,
        unit="s",
        rationale=(
            "Brake release should taper through turn-in; finishing the release "
            f"{gap_s:.2f} s before turning in gives up the front grip and "
            "rotation the brakes were buying."
            if gap_s > 0
            else "Brake release tapers into turn-in (trail braking present)."
        ),
    )


def _throttle_brake_overlap(lap, span, metrics, cfg) -> DetectorResult | None:
    value = metrics.get("throttle_brake_overlap_s")
    if value is None:
        return None
    return DetectorResult(
        detector="throttle-brake-overlap",
        triggered=value > cfg.overlap_max_s,
        value=value,
        threshold=cfg.overlap_max_s,
        unit="s",
        rationale=(
            "Throttle and brake should not work against each other; "
            f"{value:.2f} s of overlap in this corner wastes both."
        ),
    )


def _one_steering_input(lap, span, metrics, cfg) -> DetectorResult | None:
    value = metrics.get("steering_corrections")
    if value is None:
        return None
    return DetectorResult(
        detector="one-steering-input",
        triggered=value > cfg.max_corrections,
        value=value,
        threshold=float(cfg.max_corrections),
        unit="count",
        rationale=(
            "One committed steering input entry to apex; "
            f"{value:.0f} correction(s) beyond the jitter floor suggest the "
            "entry (speed, line, or vision) wasn't settled."
        ),
    )


def _throttle_monotonic(lap, span, metrics, cfg) -> DetectorResult | None:
    value = metrics.get("throttle_modulation_count")
    if value is None:
        return None
    return DetectorResult(
        detector="throttle-monotonic",
        triggered=value > cfg.max_modulations,
        value=value,
        threshold=float(cfg.max_modulations),
        unit="count",
        rationale=(
            "Once picked up, throttle should build monotonically to full; "
            f"{value:.0f} lift(s)/stab(s) before full throttle mean the pickup "
            "came earlier than the car could take."
        ),
    )


def _coast_window(lap, span, metrics, cfg) -> DetectorResult | None:
    value = metrics.get("coast_s")
    if value is None:
        return None
    return DetectorResult(
        detector="coast-window",
        triggered=value > cfg.coast_max_s,
        value=value,
        threshold=cfg.coast_max_s,
        unit="s",
        rationale=(
            "Between brake release and throttle pickup the car should be "
            f"working, not coasting; {value:.2f} s with neither pedal is time "
            "the corner gives nobody."
        ),
    )


_DETECTORS = (
    _release_taper,
    _throttle_brake_overlap,
    _one_steering_input,
    _throttle_monotonic,
    _coast_window,
)


def run_detectors(
    lap: TelemetryLap,
    span: CornerSpan,
    metrics: dict[str, float | None],
    config: DriverDNAConfig,
) -> list[DetectorResult]:
    """Evaluate every principle detector on one corner of one lap.

    Returns results in a fixed order; detectors whose inputs are absent on
    this corner are omitted (never fabricated).
    """
    cfg = config.detectors
    results = []
    for fn in _DETECTORS:
        result = fn(lap, span, metrics, cfg)
        if result is not None:
            results.append(result)
    return results
