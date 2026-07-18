"""Source-contract lock for Garage61 telemetry CSV exports (M0a).

The single place that knows what a raw export looks like. The schema-lock
tests and the `driverdna schema-report` artifact both consume
``collect_facts``; the M1 parser imports the header and rate constants.
Facts are computed with plain csv reading, deliberately independent of the
real parser, so the contract lock cannot inherit a parser bug.

Contract details and their provenance: docs/SPEC.md, "Source contract".
"""

from __future__ import annotations

import csv
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SAMPLE_RATE_HZ = 60

EXPECTED_HEADER: tuple[str, ...] = (
    "Speed",
    "LapDistPct",
    "Lat",
    "Lon",
    "Brake",
    "Throttle",
    "RPM",
    "SteeringWheelAngle",
    "Gear",
    "Clutch",
    "ABSActive",
    "DRSActive",
    "LatAccel",
    "LongAccel",
    "VertAccel",
    "Yaw",
    "YawRate",
    "PositionType",
)

# Channels confirmed absent from the export (no fuel, weather, lap validity,
# or stint/run information). Locked as a test so a future silent addition is
# noticed and adopted consciously rather than assumed away.
FORBIDDEN_COLUMN_NAMES: frozenset[str] = frozenset(
    {
        "Fuel",
        "FuelLevel",
        "FuelLevelPct",
        "FuelUsePerHour",
        "AirTemp",
        "TrackTemp",
        "TrackTempCrew",
        "WeatherType",
        "Skies",
        "WindDir",
        "WindVel",
        "Precipitation",
        "LapCompleted",
        "LapInvalidated",
        "LapValid",
        "OnPitRoad",
        "PlayerTrackSurface",
        "SessionNum",
        "SessionTime",
        "Stint",
        "Run",
    }
)

# A LapDistPct drop larger than this between consecutive samples counts as a
# start/finish wrap; smaller jitter does not.
_WRAP_DROP = 0.5


@dataclass(frozen=True)
class LapFileFacts:
    """Observed facts about one raw export file."""

    path: Path
    header: tuple[str, ...]
    n_rows: int
    duration_s: float
    wrap_count: int
    speed_min: float
    speed_max: float
    lat_mean: float
    lon_mean: float
    steering_abs_max: float
    throttle_over: int  # samples > 1
    throttle_under: int  # samples < 0
    brake_over: int
    brake_under: int
    gear0_samples: int
    clutch_values: tuple[str, ...]
    abs_values: tuple[str, ...]
    drs_values: tuple[str, ...]
    position_type_values: tuple[str, ...]


def collect_facts(path: Path) -> LapFileFacts:
    """Read one export and compute the facts the contract locks.

    Requires every expected channel to be present; a divergent header raises
    with the missing names (the header-equality test fails first and loudest).
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = tuple(next(reader))
        rows = list(reader)

    missing = [c for c in EXPECTED_HEADER if c not in header]
    if missing:
        raise ValueError(f"{path.name}: expected channels missing from header: {missing}")

    idx = {name: i for i, name in enumerate(header)}

    def floats(name: str) -> list[float]:
        i = idx[name]
        return [float(row[i]) for row in rows]

    def distinct(name: str) -> tuple[str, ...]:
        i = idx[name]
        return tuple(sorted({row[i] for row in rows}))

    n = len(rows)
    speed = floats("Speed")
    lat = floats("Lat")
    lon = floats("Lon")
    ldp = floats("LapDistPct")
    steering = floats("SteeringWheelAngle")
    throttle = floats("Throttle")
    brake = floats("Brake")
    gear_i = idx["Gear"]

    return LapFileFacts(
        path=path,
        header=header,
        n_rows=n,
        duration_s=n / SAMPLE_RATE_HZ,
        wrap_count=sum(1 for i in range(1, n) if ldp[i] < ldp[i - 1] - _WRAP_DROP),
        speed_min=min(speed),
        speed_max=max(speed),
        lat_mean=sum(lat) / n,
        lon_mean=sum(lon) / n,
        steering_abs_max=max(abs(v) for v in steering),
        throttle_over=sum(1 for v in throttle if v > 1),
        throttle_under=sum(1 for v in throttle if v < 0),
        brake_over=sum(1 for v in brake if v > 1),
        brake_under=sum(1 for v in brake if v < 0),
        gear0_samples=sum(1 for row in rows if int(float(row[gear_i])) == 0),
        clutch_values=distinct("Clutch"),
        abs_values=distinct("ABSActive"),
        drs_values=distinct("DRSActive"),
        position_type_values=distinct("PositionType"),
    )


def load_fixture_manifest(fixtures_dir: Path) -> list[dict[str, Any]]:
    """Load the fixture identity manifest (tests/fixtures/manifest.toml)."""
    with open(fixtures_dir / "manifest.toml", "rb") as f:
        return tomllib.load(f)["fixtures"]


def build_schema_report(fixtures_dir: Path) -> str:
    """Render docs/schema-report.md from the fixtures and their manifest.

    Deterministic by design: no wall-clock timestamps, facts only.
    """
    entries = load_fixture_manifest(fixtures_dir)
    lines: list[str] = [
        "# Schema report — Garage61 export contract (M0a)",
        "",
        "Generated by `driverdna schema-report` from the fixtures in "
        "`tests/fixtures/`. Facts below are locked by `tests/test_schema_lock.py`;",
        "any future export that diverges fails there, consciously. Contract "
        "provenance: docs/SPEC.md, \"Source contract\".",
        "",
        "Header (exact, in order): `" + ", ".join(EXPECTED_HEADER) + "`",
        "",
        "Confirmed absent (locked): fuel, weather, lap-validity, and stint/run "
        "channels.",
        "",
    ]
    for entry in entries:
        facts = collect_facts(fixtures_dir / entry["file"])
        dur_err_ms = abs(facts.duration_s - entry["lap_time_s"]) * 1000
        lines += [
            f"## {entry['file']} — {entry['car']} @ {entry['track']}",
            "",
            f"- Role: `{entry['role']}` · lap ID `{entry['lap_id']}` (filename "
            "carries the lap ID only; identity is manifest-anchored)",
            f"- Rows: {facts.n_rows} → {facts.duration_s:.4f} s at "
            f"{SAMPLE_RATE_HZ} Hz vs known lap time {entry['lap_time_s']:.3f} s "
            f"(Δ {dur_err_ms:.1f} ms)",
            f"- `LapDistPct` wraps: {facts.wrap_count} (single-lap file)",
            f"- Speed: {facts.speed_min:.2f}–{facts.speed_max:.2f} m/s "
            f"(peak {facts.speed_max * 3.6:.1f} km/h)",
            f"- GPS mean: {facts.lat_mean:.3f}, {facts.lon_mean:.3f} "
            f"(expected ≈ {entry['expected_lat']}, {entry['expected_lon']})",
            f"- Steering |max|: {facts.steering_abs_max:.3f} rad (radians confirmed)",
            f"- Pedal excursions — throttle >1: {facts.throttle_over}, <0: "
            f"{facts.throttle_under}; brake >1: {facts.brake_over}, <0: "
            f"{facts.brake_under} (parser clips to [0,1], quality-flagged)",
            f"- Gear-0 samples: {facts.gear0_samples} (excluded from corner "
            "detection)",
            f"- Clutch distinct values: {list(facts.clutch_values)} (uninformative, "
            "build nothing on it)",
            f"- ABSActive values: {list(facts.abs_values)} · DRSActive values: "
            f"{list(facts.drs_values)} (string booleans)",
            f"- PositionType values: {list(facts.position_type_values)} "
            "(constant; stored, not depended on)",
            "",
        ]
    return "\n".join(lines)
