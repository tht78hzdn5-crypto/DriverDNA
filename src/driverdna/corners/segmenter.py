"""CornerSegmenter: per-lap corner spans and phase landmarks (M1).

Detection: a sample is corner-active when the driver is braking
(brake > brake_on) or steering (smoothed |steering| > steering_active_deg),
outside gear-0 spans. Gaps shorter than merge_gap_s are closed (joining
chicane elements and S-curve sign changes into one complex — the multi-apex
policy), then spans shorter than min_corner_duration_s are dropped.
Every threshold is injected from config with a documented default.

Landmarks per corner, as sample indices (None where genuinely absent, e.g.
brake landmarks in a steering-only corner):

  entry            first sustained activity (min of brake_start / turn_in)
  brake_start      first sustained brake application in the span
  peak_brake       maximum brake in the span
  brake_release    first sustained drop below brake_off after the peak
  turn_in          first sustained steering above threshold
  apex(es)         speed minima; multi-apex complexes carry every minimum
                   separated by apex_min_separation_s with prominence
                   >= apex_prominence_ms, primary = global minimum
  throttle_pickup  first rise through throttle_pickup_level after the
                   in-corner throttle minimum (the minimum itself when the
                   driver never lifted below the level)
  full_throttle    first sustained full throttle after pickup (search may
                   extend past the span, up to the next corner)
  exit             end of sustained steering activity (span end when the
                   corner is brake-only)

Cross-lap consistency of the resulting shapes outranks any particular
representation choice; the frozen corner map (identity.py) is what verifies
it. See docs/SPEC.md, Milestone 1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from driverdna.config import DriverDNAConfig
from driverdna.ingest.contract import SAMPLE_RATE_HZ
from driverdna.ingest.parser import TelemetryLap
from driverdna.signals import (
    close_gaps,
    drop_short_runs,
    first_sustained_run,
    runs_of,
    smooth,
)


@dataclass(frozen=True)
class Landmarks:
    """Phase landmarks as sample indices into the lap's channel arrays."""

    entry: int
    brake_start: int | None
    peak_brake: int | None
    brake_release: int | None
    turn_in: int | None
    apex: int
    apexes: tuple[int, ...]
    throttle_pickup: int | None
    full_throttle: int | None
    exit: int


@dataclass(frozen=True)
class CornerSpan:
    """One detected corner: activity span [start, end) plus landmarks."""

    start: int
    end: int
    landmarks: Landmarks

    def min_speed(self, lap: TelemetryLap) -> float:
        return float(lap.speed[self.landmarks.apex])

    def apex_lap_dist(self, lap: TelemetryLap) -> float:
        return float(lap.lap_dist[self.landmarks.apex])

    def apex_gps(self, lap: TelemetryLap) -> tuple[float, float]:
        i = self.landmarks.apex
        return float(lap.lat[i]), float(lap.lon[i])


def _find_apexes(
    speed_smooth: np.ndarray, start: int, end: int, cfg, fs: int
) -> tuple[int, ...]:
    segment = speed_smooth[start:end]
    minima, _ = find_peaks(
        -segment,
        distance=max(1, int(cfg.apex_min_separation_s * fs)),
        prominence=cfg.apex_prominence_ms,
    )
    if len(minima) == 0:
        return (start + int(np.argmin(segment)),)
    return tuple(start + int(i) for i in minima)


def _landmarks_for_span(
    lap: TelemetryLap,
    steer_abs: np.ndarray,
    speed_smooth: np.ndarray,
    start: int,
    end: int,
    search_end: int,
    cfg,
) -> Landmarks:
    fs = SAMPLE_RATE_HZ
    debounce = max(1, int(cfg.debounce_s * fs))

    braking = lap.brake > cfg.brake_on
    steering = steer_abs > cfg.steering_active_deg

    brake_start = first_sustained_run(braking, debounce, start, end)
    turn_in = first_sustained_run(steering, debounce, start, end)

    peak_brake = brake_release = None
    if brake_start is not None:
        peak_brake = brake_start + int(np.argmax(lap.brake[brake_start:end]))
        released = lap.brake < cfg.brake_off
        brake_release = first_sustained_run(released, debounce, peak_brake, search_end)

    apexes = _find_apexes(speed_smooth, start, end, cfg, fs)
    apex = apexes[int(np.argmin([speed_smooth[i] for i in apexes]))]

    # Throttle pickup: the rise out of the corner's FINAL lift — the last
    # below-level throttle run that starts by (last apex + candidacy margin).
    # Later dips are exit-phase stabs (detector material), not a new pickup.
    # The search window is bounded to this corner's neighborhood so a flat
    # corner can never inherit the next corner's entry lift as its "pickup".
    pickup_from = turn_in if turn_in is not None else start
    pickup_end = min(search_end, end + int(cfg.pickup_search_margin_s * fs))
    candidacy_end = apexes[-1] + int(cfg.pickup_lift_candidacy_margin_s * fs)
    below = lap.throttle <= cfg.throttle_pickup_level
    lifts = [
        (pickup_from + s, pickup_from + e)
        for s, e in runs_of(below[pickup_from:pickup_end])
        if pickup_from + s <= candidacy_end
    ]
    throttle_pickup: int | None
    if lifts:
        last_lift_end = lifts[-1][1]
        throttle_pickup = last_lift_end if last_lift_end < pickup_end else None
    else:
        # Never lifted below the level (flat-ish corner): the deepest
        # modulation point in the bounded window stands in for pickup.
        throttle_pickup = pickup_from + int(
            np.argmin(lap.throttle[pickup_from:pickup_end])
        )

    full_throttle = None
    if throttle_pickup is not None:
        full = lap.throttle >= cfg.full_throttle_level
        full_throttle = first_sustained_run(
            full,
            max(1, int(cfg.full_throttle_sustain_s * fs)),
            throttle_pickup,
            search_end,
        )

    steering_runs = [r for r in runs_of(steering[start:end]) if r[1] - r[0] >= debounce]
    exit_idx = start + steering_runs[-1][1] - 1 if steering_runs else end - 1

    candidates = [i for i in (brake_start, turn_in) if i is not None]
    entry = min(candidates) if candidates else start

    return Landmarks(
        entry=entry,
        brake_start=brake_start,
        peak_brake=peak_brake,
        brake_release=brake_release,
        turn_in=turn_in,
        apex=apex,
        apexes=apexes,
        throttle_pickup=throttle_pickup,
        full_throttle=full_throttle,
        exit=exit_idx,
    )


def segment_lap(lap: TelemetryLap, config: DriverDNAConfig) -> list[CornerSpan]:
    """Detect corners and their landmarks on one lap."""
    cfg = config.segmentation
    fs = SAMPLE_RATE_HZ

    steer_abs = np.abs(smooth(lap.steering_deg, config.smoothing))
    speed_smooth = smooth(lap.speed, config.smoothing)

    active = (lap.brake > cfg.brake_on) | (steer_abs > cfg.steering_active_deg)
    active &= lap.gear != 0

    mask = close_gaps(active, max_gap=int(cfg.merge_gap_s * fs))
    mask = drop_short_runs(mask, min_len=max(1, int(cfg.min_corner_duration_s * fs)))

    spans = runs_of(mask)
    corners: list[CornerSpan] = []
    for i, (start, end) in enumerate(spans):
        search_end = spans[i + 1][0] if i + 1 < len(spans) else lap.n_samples
        landmarks = _landmarks_for_span(
            lap, steer_abs, speed_smooth, start, end, search_end, cfg
        )
        corners.append(CornerSpan(start=start, end=end, landmarks=landmarks))
    return corners
