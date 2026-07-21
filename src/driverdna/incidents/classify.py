"""Layer 2 — incident characterization: name the mechanism from the
telemetry at onset, confidence-qualified, decomposable to the channels.

Deliberately conservative: only a clean, well-separated signature earns a
named mechanism; anything ambiguous stays 'unclassified'. A spin the engine
cannot confidently explain is never given a guessed cause — "insufficient
data over guessing" applied one level down. Confidence is a coarse word
(high/medium/low), never a percentage that would launder an inference into a
measurement (the M7 binding rule).

The rationale is phrased as a single event ("this lap, at onset ..."), never
as a generalization about the driver — one incident is N=1.
"""

from __future__ import annotations

import numpy as np

from driverdna.config import IncidentConfig
from driverdna.incidents.detector import Incident
from driverdna.ingest.contract import SAMPLE_RATE_HZ
from driverdna.ingest.parser import TelemetryLap

_G = 9.81  # 1 g in m/s^2; VertAccel sits near this in steady state


def _window_mean(arr, start: int, count: int) -> float:
    lo = max(0, start)
    hi = min(len(arr), start + count)
    return float(np.mean(arr[lo:hi])) if hi > lo else 0.0


def classify_incident(
    lap: TelemetryLap, incident: Incident, config: IncidentConfig
) -> Incident:
    onset = incident.onset
    k = max(1, int(0.10 * SAMPLE_RATE_HZ))  # ~0.1 s onset window
    pre = max(1, int(0.15 * SAMPLE_RATE_HZ))  # ~0.15 s look-back for lift-off

    brake = _window_mean(lap.brake, onset, k)
    throttle = _window_mean(lap.throttle, onset, k)
    throttle_before = _window_mean(lap.throttle, onset - pre, pre)
    steer_mag = float(np.max(np.abs(lap.steering_deg[onset : onset + k]))) if k else 0.0
    vert_dev = abs(_window_mean(lap.vert_accel, onset, k) - _G)
    has_spin = "spin" in incident.kinds
    off_track = "off_track" in incident.kinds

    classification, confidence, why = "unclassified", "low", ""

    if has_spin and brake > config.classify_brake_floor:
        classification, confidence = "trail_brake_oversteer", "high"
        why = (
            f"still braking ({brake:.2f}) as the car snapped — the rear stepped "
            "out under trailing brake into the corner."
        )
    elif has_spin and throttle_before - throttle >= config.classify_throttle_drop:
        classification, confidence = "lift_off_oversteer", "medium"
        why = (
            f"throttle lifted ({throttle_before:.2f} to {throttle:.2f}) just "
            "before the snap — a mid-corner lift unloaded the rear."
        )
    elif has_spin and throttle > config.classify_throttle_floor:
        classification, confidence = "power_on_oversteer", "medium"
        why = (
            f"throttle on ({throttle:.2f}) while still steered when the car "
            "snapped — power overwhelmed rear grip on the way out."
        )
    elif off_track and not has_spin and incident.peak_yaw_rate < config.spin_yaw_rate_min:
        classification, confidence = "understeer_off", "medium"
        why = (
            f"steering loaded ({steer_mag:.0f} deg) but the car barely rotated "
            f"(peak yaw {incident.peak_yaw_rate:.2f} rad/s) before running off — "
            "the front washed out."
        )
    elif vert_dev >= config.classify_vert_accel_spike:
        classification, confidence = "external", "medium"
        why = (
            f"a vertical-load spike ({vert_dev:.1f} m/s^2 off 1 g) at onset — "
            "likely a kerb or bump, possibly not a driver input."
        )
    else:
        why = "the input picture at onset is not clean enough to name a cause."

    kinds = "+".join(incident.kinds)
    rationale = (
        f"This lap: {kinds} at "
        f"{'corner ' + incident.corner_id if incident.corner_id else 'a non-corner point'}"
        f", min speed {incident.min_speed_kmh:.0f} km/h, peak yaw "
        f"{incident.peak_yaw_rate:.2f} rad/s. {why}"
    )

    return Incident(
        span_start=incident.span_start,
        span_end=incident.span_end,
        kinds=incident.kinds,
        corner_id=incident.corner_id,
        onset=incident.onset,
        min_speed_kmh=incident.min_speed_kmh,
        peak_yaw_rate=incident.peak_yaw_rate,
        classification=classification,
        confidence=confidence,
        rationale=rationale,
        detail={
            "brake_at_onset": round(brake, 3),
            "throttle_at_onset": round(throttle, 3),
            "throttle_before": round(throttle_before, 3),
            "steer_mag_deg_at_onset": round(steer_mag, 1),
            "vert_accel_dev": round(vert_dev, 2),
            "duration_s": round(incident.duration_s, 3),
        },
    )
