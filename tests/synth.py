"""Synthetic TelemetryLap factory for landmark/detector tests.

Builds laps directly as arrays (bypassing the CSV parser, which has its own
tests) so segmentation tests can shape exact speed/brake/steering profiles.
"""

from pathlib import Path

import numpy as np

from driverdna.ingest.parser import TelemetryLap


def ramp(a: np.ndarray, i0: int, i1: int, v0: float, v1: float) -> None:
    """Fill a[i0:i1] with a linear ramp from v0 to v1 (slice only; the
    caller sets any plateau explicitly)."""
    a[i0:i1] = np.linspace(v0, v1, i1 - i0)


def make_lap(
    n: int = 1800,
    *,
    speed: np.ndarray | None = None,
    brake: np.ndarray | None = None,
    throttle: np.ndarray | None = None,
    steering_deg: np.ndarray | None = None,
    gear: np.ndarray | None = None,
) -> TelemetryLap:
    zeros = np.zeros(n)
    return TelemetryLap(
        source_path=Path("synthetic.csv"),
        lap_id=None,
        n_samples=n,
        duration_s=n / 60,
        elapsed_s=np.arange(n) / 60,
        lap_dist=np.linspace(0.0, 1.0, n),
        lap_dist_pct_raw=np.linspace(0.0, 1.0, n),
        speed=speed if speed is not None else np.full(n, 50.0),
        lat=np.full(n, 36.58),
        lon=np.full(n, -121.75),
        brake=brake if brake is not None else zeros.copy(),
        throttle=throttle if throttle is not None else np.ones(n),
        rpm=np.full(n, 5000.0),
        steering_deg=steering_deg if steering_deg is not None else zeros.copy(),
        gear=gear if gear is not None else np.full(n, 4, dtype=np.int64),
        clutch=np.ones(n),
        abs_active=np.zeros(n, dtype=np.bool_),
        drs_active=np.zeros(n, dtype=np.bool_),
        lat_accel=zeros.copy(),
        long_accel=zeros.copy(),
        vert_accel=np.full(n, 9.8),
        yaw=zeros.copy(),
        yaw_rate=zeros.copy(),
        position_type=np.full(n, 3, dtype=np.int64),
        quality_flags=[],
    )


def one_corner_lap(n: int = 1800) -> TelemetryLap:
    """A single canonical corner with every landmark present.

    Approximate expected sample indices:
      brake_start ~602, peak_brake ~630, turn_in ~672, brake_release ~719,
      apex ~750, throttle_pickup ~766, full_throttle ~817, exit ~876.
    """
    speed = np.full(n, 50.0)
    ramp(speed, 600, 750, 50.0, 25.0)
    ramp(speed, 750, 960, 25.0, 50.0)

    brake = np.zeros(n)
    ramp(brake, 600, 630, 0.0, 0.8)
    brake[630:690] = 0.8
    ramp(brake, 690, 720, 0.8, 0.0)

    steering = np.zeros(n)
    ramp(steering, 660, 690, 0.0, 25.0)
    steering[690:840] = 25.0
    ramp(steering, 840, 900, 25.0, 0.0)

    throttle = np.ones(n)
    ramp(throttle, 580, 600, 1.0, 0.0)
    throttle[600:760] = 0.0
    ramp(throttle, 760, 820, 0.0, 1.0)
    throttle[820:] = 1.0

    return make_lap(n, speed=speed, brake=brake, throttle=throttle, steering_deg=steering)
