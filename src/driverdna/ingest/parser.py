"""Garage61Parser: one CSV export -> typed TelemetryLap.

Built in M1, against the verified source contract in docs/SPEC.md: exact
18-column header, 60 Hz with no time column (elapsed = index/60), single
LapDistPct wrap, m/s speeds, radian steering -> degrees, string-boolean
ABS/DRS, real GPS, filename carrying a lap ID only.

Admission policy: every parseable lap is admitted, carrying structured
quality flags for anything unusual. Nothing is silently repaired except
pedal clipping to [0, 1], which is flagged with per-channel counts.
Malformed numeric values become NaN (flagged, counted); malformed booleans
become False (flagged); malformed integer channels become 0 (flagged — for
Gear this collides with neutral, which is why the flag records the count).
A file with no header or no data rows is not a lap and raises ParseError.
Channels beyond the contract header are ignored here; the M0a schema lock is
what notices contract drift on the fixtures.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

from driverdna.ingest.contract import EXPECTED_HEADER, SAMPLE_RATE_HZ


class FlagCode(StrEnum):
    """Structured quality-flag codes (docs/SPEC.md, M1)."""

    MISSING_CHANNEL = "missing_channel"
    MALFORMED_VALUES = "malformed_values"
    CLIPPED_PEDAL = "clipped_pedal"
    UNEXPECTED_WRAP_COUNT = "unexpected_wrap_count"  # 2+ wraps: a multi-lap file
    INCOMPLETE_LAP = "incomplete_lap"  # single lap, but covers < a full lap
    METADATA_FAILURE = "metadata_failure"
    INFERRED_UNITS = "inferred_units"
    API_LAP_METADATA = "api_lap_metadata"  # sync only (M0b): Garage61's own
    # clean/offtrack/discontinuity/pitlane flags for this lap — metadata the
    # API carries that the CSV channel contract does not (docs/garage61-api.md).


@dataclass(frozen=True)
class QualityFlag:
    code: FlagCode
    detail: dict[str, Any]


class ParseError(ValueError):
    """The file cannot be admitted at all (no header, or no data rows)."""


_FILENAME_RE = re.compile(r"Garage_61_([A-Za-z0-9]+)\.csv$")

# A newer Garage61 export filename shape embeds driver/car/track/laptime/
# lap-id directly, double-underscore delimited:
#   Garage_61__<driver>__<car>__<track>__<M.SS.mmm laptime>__<ULID>.csv
# unlike the older Garage_61_<ID>.csv form, which carries only an opaque ID.
# Store, don't depend on the shape persisting (A13's own caution about
# filename-derived metadata) -- parse_garage61_filename() below is optional,
# additive, and every caller falls back to an explicit --car/--track or
# manifest entry when it returns None, never guesses past that.
_NEW_FILENAME_RE = re.compile(
    r"^Garage_61__(?P<driver>[^_].*?)__(?P<car>.+?)__(?P<track>.+?)__"
    r"(?P<laptime>\d+\.\d+\.\d+)__(?P<lap_id>[A-Za-z0-9]+)\.csv$"
)


def parse_garage61_filename(name: str) -> dict[str, str] | None:
    """Car/track (and lap_id) auto-detected from the newer Garage61 export
    filename shape. Underscores within a field are the export tool's own
    word-separator, not data -- decoded to spaces for a human-readable
    label. Returns None for the older Garage_61_<ID>.csv form or anything
    else that doesn't match, so callers can fall back to an explicit
    --car/--track or manifest entry."""
    m = _NEW_FILENAME_RE.match(name)
    if not m:
        return None
    return {
        "car": m.group("car").replace("_", " "),
        "track": m.group("track").replace("_", " "),
        "lap_id": m.group("lap_id"),
    }

# A LapDistPct drop larger than this between consecutive samples is a
# start/finish crossing. A single lap has 0 or 1 crossings depending on where
# the file boundary falls relative to the line (a line-to-line sample wraps
# zero times; a sample starting just past the line wraps once); 2+ means a
# multi-lap file.
_WRAP_DROP = 0.5

# A complete lap's unwrapped distance spans very nearly the whole [0, 1]. Less
# coverage than this means a partial lap, flagged rather than silently used.
_MIN_LAP_COVERAGE = 0.97


@dataclass
class TelemetryLap:
    """One lap, normalized and typed.

    Units are SI as delivered (Speed m/s, accelerations m/s^2, YawRate rad/s)
    except ``steering_deg``, converted from the contract's radians. ``lap_dist``
    is LapDistPct with start/finish wraps unwrapped into a continuous,
    non-decreasing coordinate (a full single-lap file spans ~[0, 1+epsilon]);
    the raw channel is kept alongside. ``elapsed_s`` is reconstructed at 60 Hz.
    Pedals are clipped to [0, 1] (the only permitted repair, quality-flagged).
    """

    source_path: Path
    lap_id: str | None
    n_samples: int
    duration_s: float
    elapsed_s: np.ndarray
    lap_dist: np.ndarray
    lap_dist_pct_raw: np.ndarray
    speed: np.ndarray
    lat: np.ndarray
    lon: np.ndarray
    brake: np.ndarray
    throttle: np.ndarray
    rpm: np.ndarray
    steering_deg: np.ndarray
    gear: np.ndarray
    clutch: np.ndarray
    abs_active: np.ndarray
    drs_active: np.ndarray
    lat_accel: np.ndarray
    long_accel: np.ndarray
    vert_accel: np.ndarray
    yaw: np.ndarray
    yaw_rate: np.ndarray
    position_type: np.ndarray
    quality_flags: list[QualityFlag] = field(default_factory=list)

    def has_flag(self, code: FlagCode) -> bool:
        return any(f.code == code for f in self.quality_flags)

    def flag(self, code: FlagCode) -> QualityFlag | None:
        return next((f for f in self.quality_flags if f.code == code), None)


def _float_column(
    raw: list[str], channel: str, malformed: dict[str, int]
) -> np.ndarray:
    """Vectorized str->float; malformed values become NaN and are counted."""
    try:
        return np.asarray(raw, dtype=np.float64)
    except ValueError:
        values = np.empty(len(raw), dtype=np.float64)
        bad = 0
        for i, v in enumerate(raw):
            try:
                values[i] = float(v)
            except ValueError:
                values[i] = np.nan
                bad += 1
        malformed[channel] = bad
        return values


def _int_column(raw: list[str], channel: str, malformed: dict[str, int]) -> np.ndarray:
    values = _float_column(raw, channel, malformed)
    return np.nan_to_num(values, nan=0.0).astype(np.int64)


def _bool_column(raw: list[str], channel: str, malformed: dict[str, int]) -> np.ndarray:
    bad = sum(1 for v in raw if v not in ("true", "false"))
    if bad:
        malformed[channel] = bad
    return np.asarray([v == "true" for v in raw], dtype=np.bool_)


def _unwrap(lap_dist_pct: np.ndarray) -> tuple[np.ndarray, int]:
    """Resolve start/finish wraps into a continuous distance coordinate."""
    drops = np.where(np.diff(lap_dist_pct) < -_WRAP_DROP)[0]
    unwrapped = lap_dist_pct.astype(np.float64).copy()
    for d in drops:
        unwrapped[d + 1 :] += 1.0
    return unwrapped, len(drops)


def parse_lap(path: Path) -> TelemetryLap:
    """Parse one Garage61 export per the source contract."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise ParseError(f"{path.name}: empty file") from None
        rows = [row for row in reader if row]
    match = _FILENAME_RE.search(path.name)
    if match:
        lap_id = match.group(1)
    else:
        new_format = parse_garage61_filename(path.name)
        lap_id = new_format["lap_id"] if new_format else None
    return _parse_rows(header, rows, label=path.name, source_path=path, lap_id=lap_id)


def parse_lap_text(text: str, *, source_label: str, lap_id: str | None) -> TelemetryLap:
    """Parse an in-memory CSV export (the `sync` path, M0b) per the same
    source contract as `parse_lap`. `lap_id` is supplied by the caller — the
    API's own lap id — rather than parsed from a filename: M0b found the
    manual-download filename code and the API's lap id are unrelated ID
    spaces, so `sync` must never try to derive one from the other.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ParseError(f"{source_label}: empty file") from None
    rows = [row for row in reader if row]
    return _parse_rows(
        header, rows, label=source_label, source_path=Path(source_label), lap_id=lap_id
    )


def _parse_rows(
    header: list[str],
    rows: list[list[str]],
    *,
    label: str,
    source_path: Path,
    lap_id: str | None,
) -> TelemetryLap:
    if not rows:
        raise ParseError(f"{label}: header but no data rows")

    flags: list[QualityFlag] = []
    idx = {name: i for i, name in enumerate(header)}
    missing = [c for c in EXPECTED_HEADER if c not in idx]
    if missing:
        flags.append(QualityFlag(FlagCode.MISSING_CHANNEL, {"channels": missing}))

    n = len(rows)
    blank = [""] * n  # missing channels parse to NaN/0/False and are flagged above

    def raw(channel: str) -> list[str]:
        if channel not in idx:
            return blank
        i = idx[channel]
        return [row[i] for row in rows]

    malformed: dict[str, int] = {}
    speed = _float_column(raw("Speed"), "Speed", malformed)
    lap_dist_pct = _float_column(raw("LapDistPct"), "LapDistPct", malformed)
    lat = _float_column(raw("Lat"), "Lat", malformed)
    lon = _float_column(raw("Lon"), "Lon", malformed)
    brake = _float_column(raw("Brake"), "Brake", malformed)
    throttle = _float_column(raw("Throttle"), "Throttle", malformed)
    rpm = _float_column(raw("RPM"), "RPM", malformed)
    steering_rad = _float_column(raw("SteeringWheelAngle"), "SteeringWheelAngle", malformed)
    gear = _int_column(raw("Gear"), "Gear", malformed)
    clutch = _float_column(raw("Clutch"), "Clutch", malformed)
    abs_active = _bool_column(raw("ABSActive"), "ABSActive", malformed)
    drs_active = _bool_column(raw("DRSActive"), "DRSActive", malformed)
    lat_accel = _float_column(raw("LatAccel"), "LatAccel", malformed)
    long_accel = _float_column(raw("LongAccel"), "LongAccel", malformed)
    vert_accel = _float_column(raw("VertAccel"), "VertAccel", malformed)
    yaw = _float_column(raw("Yaw"), "Yaw", malformed)
    yaw_rate = _float_column(raw("YawRate"), "YawRate", malformed)
    position_type = _int_column(raw("PositionType"), "PositionType", malformed)

    # Missing channels register as fully malformed by construction; report only
    # genuinely present channels with bad values.
    malformed = {c: k for c, k in malformed.items() if c in idx and k > 0}
    if malformed:
        flags.append(QualityFlag(FlagCode.MALFORMED_VALUES, {"counts": malformed}))

    lap_dist, wrap_count = _unwrap(lap_dist_pct)
    if wrap_count >= 2:
        flags.append(
            QualityFlag(FlagCode.UNEXPECTED_WRAP_COUNT, {"observed": wrap_count})
        )
    coverage = float(np.nanmax(lap_dist) - np.nanmin(lap_dist)) if n else 0.0
    if coverage < _MIN_LAP_COVERAGE:
        flags.append(
            QualityFlag(FlagCode.INCOMPLETE_LAP, {"coverage": round(coverage, 4)})
        )

    clip_counts = {
        "throttle_over": int(np.sum(throttle > 1)),
        "throttle_under": int(np.sum(throttle < 0)),
        "brake_over": int(np.sum(brake > 1)),
        "brake_under": int(np.sum(brake < 0)),
    }
    if any(clip_counts.values()):
        flags.append(QualityFlag(FlagCode.CLIPPED_PEDAL, clip_counts))
    throttle = np.clip(throttle, 0.0, 1.0)
    brake = np.clip(brake, 0.0, 1.0)

    return TelemetryLap(
        source_path=source_path,
        lap_id=lap_id,
        n_samples=n,
        duration_s=n / SAMPLE_RATE_HZ,
        elapsed_s=np.arange(n, dtype=np.float64) / SAMPLE_RATE_HZ,
        lap_dist=lap_dist,
        lap_dist_pct_raw=lap_dist_pct,
        speed=speed,
        lat=lat,
        lon=lon,
        brake=brake,
        throttle=throttle,
        rpm=rpm,
        steering_deg=np.degrees(steering_rad),
        gear=gear,
        clutch=clutch,
        abs_active=abs_active,
        drs_active=drs_active,
        lat_accel=lat_accel,
        long_accel=long_accel,
        vert_accel=vert_accel,
        yaw=yaw,
        yaw_rate=yaw_rate,
        position_type=position_type,
        quality_flags=flags,
    )
