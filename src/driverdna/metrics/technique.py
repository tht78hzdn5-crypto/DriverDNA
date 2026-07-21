"""TechniqueAnalyzer: deterministic per-corner/per-lap metrics (M2).

Every number the product ever shows about technique originates here (or in
the attribution engine, M3). Each metric is defined once in METRIC_DEFS with
its unit and a plain-language description; compute_corner_metrics returns
{name: value} with None for anything not computable on that corner (a
steering-only corner has no braking metrics — "insufficient data" beats
guessing, at metric granularity).

Explicitly unavailable and never inferred: tire slip/utilization, vision.
Cross-lap aggregation (median/spread/N per corner identity) lives in
summarize(); lap-to-lap variance of any metric is its consistency signal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from driverdna.config import DriverDNAConfig
from driverdna.corners.segmenter import CornerSpan
from driverdna.ingest.contract import SAMPLE_RATE_HZ
from driverdna.ingest.parser import TelemetryLap
from driverdna.signals import smooth

MS_TO_KMH = 3.6

#: name -> (unit, plain-language description)
METRIC_DEFS: dict[str, tuple[str, str]] = {
    "brake_point_dist_pct": ("% lap", "Where braking for the corner begins."),
    "brake_application_rate": ("fraction/s", "How fast the pedal rises from first application to peak."),
    "brake_peak": ("fraction", "Maximum brake pedal reached in the corner."),
    "brake_release_duration_s": ("s", "Time taken to release the brake: from last near-peak pressure to off."),
    "trail_brake_overlap_s": ("s", "Time spent braking while steering (trail braking)."),
    "throttle_brake_overlap_s": ("s", "Time with throttle and brake applied together."),
    "turn_in_dist_pct": ("% lap", "Where sustained steering for the corner begins."),
    "steering_corrections": ("count", "Steering-rate sign reversals between turn-in and apex beyond the jitter floor."),
    "steering_smoothness_dps2": ("deg/s^2", "RMS steering acceleration turn-in to apex; lower is smoother."),
    "yaw_peak_rate": ("rad/s", "Peak yaw rate in the corner (rotation actually achieved)."),
    "min_speed_kmh": ("km/h", "Minimum corner speed at the primary apex."),
    "apex_dist_pct": ("% lap", "Where the minimum-speed point sits."),
    "coast_s": ("s", "Time between brake release and throttle pickup with neither pedal working."),
    "throttle_pickup_dist_pct": ("% lap", "Where throttle is first picked up after the corner's final lift."),
    "throttle_modulation_count": ("count", "Throttle lifts/stabs between pickup and full throttle."),
    "full_throttle_dist_pct": ("% lap", "Where sustained full throttle begins."),
    "exit_accel_ms2": ("m/s^2", "Mean longitudinal acceleration from apex to full throttle."),
    "abs_active_ratio": ("fraction", "Share of braking time with ABS active."),
}


def _pos_pct(lap: TelemetryLap, index: int | None) -> float | None:
    if index is None:
        return None
    return (float(lap.lap_dist[index]) % 1.0) * 100.0


def _count_sign_reversals(rate: np.ndarray, floor: float) -> int:
    signs = np.sign(rate)
    signs[np.abs(rate) < floor] = 0
    nonzero = signs[signs != 0]
    if len(nonzero) < 2:
        return 0
    return int(np.sum(nonzero[1:] != nonzero[:-1]))


def _count_drops(values: np.ndarray, min_drop: float) -> int:
    """Falls (local max -> local min) of at least min_drop."""
    if len(values) < 2:
        return 0
    count = 0
    peak = values[0]
    falling_from = None
    for v in values[1:]:
        if v > peak:
            peak = v
            falling_from = None
        elif falling_from is None and peak - v >= min_drop:
            count += 1
            falling_from = peak
            peak = v
        elif falling_from is not None and v < peak:
            peak = min(peak, v)
    return count


def compute_corner_metrics(
    lap: TelemetryLap, span: CornerSpan, config: DriverDNAConfig
) -> dict[str, float | None]:
    """All technique metrics for one corner on one lap. Deterministic."""
    fs = SAMPLE_RATE_HZ
    seg_cfg = config.segmentation
    m_cfg = config.metrics
    lm = span.landmarks
    s, e = span.start, span.end

    out: dict[str, float | None] = {name: None for name in METRIC_DEFS}

    # Braking
    out["brake_point_dist_pct"] = _pos_pct(lap, lm.brake_start)
    if lm.brake_start is not None and lm.peak_brake is not None:
        out["brake_peak"] = float(lap.brake[lm.brake_start : e].max())
        dt = (lm.peak_brake - lm.brake_start) / fs
        if dt > 0:
            rise = float(lap.brake[lm.peak_brake] - lap.brake[lm.brake_start])
            out["brake_application_rate"] = rise / dt
        if lm.brake_release is not None:
            # From the end of near-peak pressure (a held plateau is not
            # "releasing") to fully released.
            peak_value = out["brake_peak"] or 0.0
            near_peak = (
                lap.brake[lm.peak_brake : lm.brake_release]
                >= m_cfg.release_from_peak_fraction * peak_value
            )
            hold = np.flatnonzero(near_peak)
            release_from = lm.peak_brake + (int(hold[-1]) if len(hold) else 0)
            out["brake_release_duration_s"] = (lm.brake_release - release_from) / fs

    steer_smooth = smooth(lap.steering_deg, config.smoothing)
    braking_mask = lap.brake[s:e] > seg_cfg.brake_on
    steering_mask = np.abs(steer_smooth[s:e]) > seg_cfg.steering_active_deg
    if lm.brake_start is not None:
        out["trail_brake_overlap_s"] = float(np.sum(braking_mask & steering_mask)) / fs

    overlap = (lap.throttle[s:e] > m_cfg.overlap_floor) & (
        lap.brake[s:e] > m_cfg.overlap_floor
    )
    out["throttle_brake_overlap_s"] = float(np.sum(overlap)) / fs

    # Rotation
    out["turn_in_dist_pct"] = _pos_pct(lap, lm.turn_in)
    if lm.turn_in is not None and lm.apex > lm.turn_in + 2:
        window = steer_smooth[lm.turn_in : lm.apex + 1]
        rate = np.diff(window) * fs  # deg/s
        out["steering_corrections"] = float(
            _count_sign_reversals(rate, m_cfg.correction_floor_dps)
        )
        accel = np.diff(window, n=2) * fs * fs  # deg/s^2
        if len(accel):
            out["steering_smoothness_dps2"] = float(np.sqrt(np.mean(accel**2)))
    out["yaw_peak_rate"] = float(np.abs(lap.yaw_rate[s:e]).max())
    out["min_speed_kmh"] = span.min_speed(lap) * MS_TO_KMH
    out["apex_dist_pct"] = _pos_pct(lap, lm.apex)

    # Exit
    out["throttle_pickup_dist_pct"] = _pos_pct(lap, lm.throttle_pickup)
    out["full_throttle_dist_pct"] = _pos_pct(lap, lm.full_throttle)
    if lm.brake_release is not None and lm.throttle_pickup is not None:
        out["coast_s"] = max(0.0, (lm.throttle_pickup - lm.brake_release) / fs)
    if lm.throttle_pickup is not None:
        mod_end = lm.full_throttle if lm.full_throttle is not None else e
        if mod_end > lm.throttle_pickup:
            out["throttle_modulation_count"] = float(
                _count_drops(
                    lap.throttle[lm.throttle_pickup : mod_end], m_cfg.modulation_min_drop
                )
            )
    accel_end = lm.full_throttle if lm.full_throttle is not None else e
    if accel_end > lm.apex:
        out["exit_accel_ms2"] = float(np.mean(lap.long_accel[lm.apex : accel_end]))

    # Vehicle management (acceleration/ABS proxies only — no slip channel).
    if braking_mask.any():
        out["abs_active_ratio"] = float(lap.abs_active[s:e][braking_mask].mean())

    return out


@dataclass(frozen=True)
class MetricSummary:
    """Cross-lap aggregate of one metric for one corner identity."""

    n: int
    median: float
    mean: float
    spread: float  # sample standard deviation (ddof=1); 0.0 when n == 1


def summarize(values: list[float]) -> MetricSummary | None:
    """Aggregate one metric's per-lap values (None entries excluded upstream)."""
    if not values:
        return None
    arr = np.asarray(values, dtype=np.float64)
    return MetricSummary(
        n=len(arr),
        median=float(np.median(arr)),
        mean=float(np.mean(arr)),
        spread=float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
    )
