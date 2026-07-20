"""Synthetic TelemetryLap factory for landmark/detector tests.

Builds laps directly as arrays (bypassing the CSV parser, which has its own
tests) so segmentation tests can shape exact speed/brake/steering profiles.
"""

import hashlib
from pathlib import Path

import numpy as np

from driverdna.ingest.parser import TelemetryLap


def _content_marker(src: str) -> float:
    """A deterministic, imperceptible per-lap value so two synthetic laps with
    different source names are never byte-identical — mirroring real 60 Hz
    laps (which never are) so content-dedup doesn't collapse distinct test
    laps. Written into vert_accel, which no metric/detector/attribution reads."""
    return int(hashlib.md5(src.encode()).hexdigest(), 16) % 100_000 * 1e-9


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
    lat: np.ndarray | None = None,
    lon: np.ndarray | None = None,
    src: str = "synthetic.csv",
) -> TelemetryLap:
    zeros = np.zeros(n)
    return TelemetryLap(
        source_path=Path(src),
        lap_id=None,
        n_samples=n,
        duration_s=n / 60,
        elapsed_s=np.arange(n) / 60,
        lap_dist=np.linspace(0.0, 1.0, n),
        lap_dist_pct_raw=np.linspace(0.0, 1.0, n),
        speed=speed if speed is not None else np.full(n, 50.0),
        lat=lat if lat is not None else np.full(n, 36.58),
        lon=lon if lon is not None else np.full(n, -121.75),
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
        vert_accel=np.full(n, 9.8 + _content_marker(src)),
        yaw=zeros.copy(),
        yaw_rate=zeros.copy(),
        position_type=np.full(n, 3, dtype=np.int64),
        quality_flags=[],
    )


# A synthetic "track" for identity/pipeline tests: ~1113 m of latitude over
# one lap, so corners 0.1 of a lap apart sit ~111 m apart — well beyond the
# default 75 m match radius.
TRACK_N = 3600
TRACK_LAT = 36.5 + 0.01 * np.linspace(0.0, 1.0, TRACK_N)
TRACK_LON = np.full(TRACK_N, -121.75)
CORNER_WINDOWS = [(700, 850), (1700, 1850), (2900, 3050)]


def track_lap(
    windows=CORNER_WINDOWS,
    lat: np.ndarray | None = None,
    lon: np.ndarray | None = None,
    src: str = "synthetic.csv",
) -> TelemetryLap:
    """A lap of the synthetic track: steering-only corners at `windows`."""
    steering = np.zeros(TRACK_N)
    speed = np.full(TRACK_N, 50.0)
    for start, end in windows:
        steering[start:end] = 20.0
        mid = (start + end) // 2
        ramp(speed, start, mid, 50.0, 30.0)
        ramp(speed, mid, end, 30.0, 50.0)
    return make_lap(
        TRACK_N,
        speed=speed,
        steering_deg=steering,
        lat=lat if lat is not None else TRACK_LAT.copy(),
        lon=lon if lon is not None else TRACK_LON.copy(),
        src=src,
    )


def warp_time(lap: TelemetryLap, window: tuple[float, float], extra_s: float) -> TelemetryLap:
    """Make the lap spend `extra_s` more (or less) time crossing the given
    lap-dist window, by warping elapsed_s — the physically meaningful lever
    for attribution tests. Lap duration changes by the same amount."""
    mask = (lap.lap_dist >= window[0]) & (lap.lap_dist < window[1])
    dt = np.full(lap.n_samples, 1.0 / 60.0)
    dt[mask] += extra_s / max(1, int(mask.sum()))
    lap.elapsed_s = np.cumsum(dt) - dt[0]
    lap.duration_s = float(lap.duration_s + extra_s)
    return lap


def run_synthetic_lap(
    db,
    lap: TelemetryLap,
    *,
    driver: str = "owner",
    car: str = "TestCar",
    track: str = "SynthRing",
    role: str = "self",
    session_key: str | None = None,
    config=None,
):
    """Run the full import pipeline on an in-memory synthetic lap directly
    (no file on disk needed — `import_parsed_lap` takes an already-parsed
    lap, the same entry point `sync` uses for API-fetched laps)."""
    from driverdna.config import DriverDNAConfig
    from driverdna.pipeline import import_parsed_lap

    return import_parsed_lap(
        db, lap, driver=driver, car=car, track=track, role=role,
        session_key=session_key, config=config or DriverDNAConfig(),
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
