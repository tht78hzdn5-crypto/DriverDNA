"""Per-corner readable slices of a stored lap (`driverdna lap-digest`).

A lap is ~10,000 samples across 20 channels. Nobody reads that, which is why
"analyze these laps" has always meant "read what the engine said about them".
The digest makes the trace itself reviewable: one small CSV per lap per
corner, at a stated sample stride, spanning the corner's canonical window.

**It measures nothing.** The only transforms are row selection (window +
stride) and column selection. No aggregation, no derived columns, no unit
conversion. Two reasons, and the second is the load-bearing one:

1. Computing a measurement outside the engine is exactly what this project
   forbids of the UI, and a digest is a view like any other.
2. The digest is the shared evidence base for two independent raters. A bug
   in a derived column would corrupt both readings identically, and the
   disagreement that is supposed to catch it would never appear.

Purity is relative to `load_lap_arrays()` — the arrays the engine itself
analyzes — not the source CSV. The parser's documented normalizations
(radians -> degrees, LapDistPct unwrap, pedal clipping) are locked by
`tests/test_schema_lock.py`; a rater should see precisely what the engine
saw, so any disagreement is about interpretation and not about parsing.

`stride` and `margin` are function/CLI parameters rather than ConfigStore
thresholds on purpose: they change which samples are *displayed* and no
value the engine computes, so they are not the versioned-and-reversible
kind of number that rule governs.

Reference laps are never digested — `role='self'` only, the same isolation
every other read surface enforces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from driverdna.db import Database

#: Bumped when the on-disk shape changes in a way a reader would notice.
DIGEST_VERSION = 1

SAMPLE_RATE_HZ = 60

#: Stored units, restated for whoever reads a slice. This is the single most
#: valuable line in the manifest: speed is m/s (not km/h) and steering is
#: degrees (despite the source contract delivering radians), and a rater who
#: assumes otherwise will be confidently wrong about every number they quote.
UNITS: dict[str, str] = {
    "elapsed_s": "s",
    "lap_dist": "lap fraction, unwrapped to be continuous over the lap",
    "lap_dist_pct_raw": "lap fraction, raw (wraps at the start/finish line)",
    "speed": "m/s",
    "lat": "degrees",
    "lon": "degrees",
    "brake": "pedal fraction 0-1",
    "throttle": "pedal fraction 0-1",
    "rpm": "rpm",
    "steering_deg": "degrees (converted from the source contract's radians)",
    "gear": "gear number",
    "clutch": "pedal fraction 0-1",
    "abs_active": "0 or 1",
    "drs_active": "0 or 1",
    "lat_accel": "m/s^2",
    "long_accel": "m/s^2",
    "vert_accel": "m/s^2",
    "yaw": "rad",
    "yaw_rate": "rad/s",
    "position_type": "3 on track, 4 off track",
}

#: Emission order. Fixed here rather than taken from the npz key order so the
#: output is deterministic, and covering *every* stored channel rather than a
#: chosen subset so the tool never pre-decides what is worth looking at.
CHANNELS: tuple[str, ...] = tuple(UNITS)


class NoFrozenMap(RuntimeError):
    """No frozen corner map for the requested cohort, so nothing can be cut.

    Refusing beats emitting whole-lap dumps: a slice's meaning comes from the
    corner it belongs to.
    """


@dataclass(frozen=True)
class DigestReport:
    cohorts: tuple[str, ...]
    laps_written: int
    corners_written: int
    #: Laps whose raw trace could not be read here (evicted by retention, or
    #: imported on another machine). Named, never silently omitted.
    unavailable_laps: tuple[str, ...]
    #: "<dir>/<corner_id>: reason" for corners that produced no slice.
    skipped: tuple[str, ...]


def format_cell(value) -> str:
    """One stored sample as text: formatting only, never a conversion.

    `repr` of a float is the shortest string that reads back as the identical
    double, so a digest cell round-trips exactly. NaN becomes an empty field
    rather than the string "nan", so a gap in the trace reads as a gap.
    """
    if isinstance(value, (bool, np.bool_)):
        return "1" if value else "0"
    f = float(value)
    return "" if np.isnan(f) else repr(f)


def _lap_coord(lap_dist: np.ndarray, pos: float) -> float:
    """A canonical mod-1 position in this lap's continuous coordinate.

    Mirrors `attribution.engine.time_at` exactly, so a slice lines up with
    the span the engine measures over rather than approximating it.
    """
    p = pos % 1.0
    if p < lap_dist[0]:
        p += 1.0
    return min(max(p, float(lap_dist[0])), float(lap_dist[-1]))


def _row_indices(
    lap_dist: np.ndarray, start: float, end: float, margin: float, stride: int
) -> range:
    """Sample indices covering [start, end] widened by `margin`, every `stride`.

    The margin is applied in the continuous coordinate, after mapping — not to
    the mod-1 positions. Widening first would send a corner sitting just past
    the start/finish line backwards across the seam to ~0.99.
    """
    span = (end - start) % 1.0 if end != start else 0.0
    lo = _lap_coord(lap_dist, start)
    hi = min(lo + span, float(lap_dist[-1]))
    lo = max(float(lap_dist[0]), lo - margin)
    hi = min(float(lap_dist[-1]), hi + margin)
    i0 = int(np.searchsorted(lap_dist, lo, side="left"))
    i1 = int(np.searchsorted(lap_dist, hi, side="right"))
    return range(i0, min(i1, len(lap_dist)), stride)


def _corner_span(w: dict[str, float | None]) -> tuple[float, float]:
    """The corner's full extent from its frozen window, with fallbacks.

    A corner with no braking has no `entry_start`, and one where the driver
    never reaches full throttle has no `exit_end`; both are legitimate, so
    each end falls back toward the apex rather than skipping the corner.
    """
    start = w["entry_start"]
    if start is None:
        start = w["turn_in"]
    if start is None:
        start = w["apex"]
    end = w["exit_end"]
    if end is None:
        end = w["apex"]
    return float(start), float(end)


def build_digest(
    db: Database,
    *,
    out_dir: Path,
    driver: str | None = None,
    car: str | None = None,
    track: str | None = None,
    stride: int = 6,
    margin: float = 0.01,
) -> DigestReport:
    """Write per-lap, per-corner slices under `out_dir`, plus a manifest."""
    if stride < 1:
        raise ValueError("stride must be >= 1")

    sql = (
        "SELECT DISTINCT driver, car, track FROM laps "
        "WHERE role='self' AND owner_user_pk=?"
    )
    params: list = [db.user_pk]
    for column, value in (("driver", driver), ("car", car), ("track", track)):
        if value is not None:
            sql += f" AND {column}=?"
            params.append(value)
    cohorts = db.conn.execute(sql + " ORDER BY driver, car, track", params).fetchall()
    if not cohorts:
        raise NoFrozenMap(
            "no self laps for that cohort — nothing to slice "
            f"(driver={driver!r}, car={car!r}, track={track!r})"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_cohorts: list[dict] = []
    labels: list[str] = []
    unavailable: list[str] = []
    skipped: list[str] = []
    laps_written = corners_written = 0

    for c in cohorts:
        c_driver, c_car, c_track = c["driver"], c["car"], c["track"]
        loaded = db.load_corner_map(car=c_car, track=c_track)
        if loaded is None:
            raise NoFrozenMap(
                f"{c_car} @ {c_track} has no frozen corner map — import laps first"
            )
        map_pk, _ = loaded
        windows = db.load_corner_windows(map_pk)
        if not windows:
            raise NoFrozenMap(f"{c_car} @ {c_track} has a map but no frozen windows")

        labels.append(f"{c_car} @ {c_track}")
        lap_rows = db.conn.execute(
            "SELECT lap_pk, lap_id, session_key FROM laps "
            "WHERE role='self' AND driver=? AND car=? AND track=? AND owner_user_pk=? "
            "ORDER BY lap_pk",
            (c_driver, c_car, c_track, db.user_pk),
        ).fetchall()

        lap_entries: list[dict] = []
        for lap in lap_rows:
            lap_pk = lap["lap_pk"]
            name = lap["lap_id"] or f"lap-{lap_pk}"
            arrays = db.load_lap_arrays(lap_pk)
            if arrays is None:
                unavailable.append(name)
                continue

            lap_dist = arrays["lap_dist"]
            present = [ch for ch in CHANNELS if ch in arrays]
            lap_dir = out_dir / name
            files: list[str] = []
            for corner_id in sorted(windows):
                start, end = _corner_span(windows[corner_id])
                rows = _row_indices(lap_dist, start, end, margin, stride)
                if len(rows) == 0:
                    skipped.append(f"{name}/{corner_id}: window covers no samples")
                    continue
                lap_dir.mkdir(parents=True, exist_ok=True)
                lines = ["row," + ",".join(present)]
                for i in rows:
                    lines.append(
                        f"{i}," + ",".join(format_cell(arrays[ch][i]) for ch in present)
                    )
                (lap_dir / f"{corner_id}.csv").write_text("\n".join(lines) + "\n")
                files.append(f"{name}/{corner_id}.csv")
                corners_written += 1

            if files:
                laps_written += 1
                # Deliberately no lap time here: it would tell a blind reader
                # which laps are the slow ones, which is the judgment the read
                # is supposed to produce from the trace.
                lap_entries.append(
                    {
                        "dir": name,
                        "lap_pk": lap_pk,
                        "lap_id": lap["lap_id"],
                        "session_key": lap["session_key"],
                        "n_samples": int(len(lap_dist)),
                        "files": files,
                    }
                )

        manifest_cohorts.append(
            {
                "driver": c_driver,
                "car": c_car,
                "track": c_track,
                "corners": {
                    cid: {k: windows[cid][k] for k in
                          ("entry_start", "turn_in", "apex", "exit_end")}
                    for cid in sorted(windows)
                },
                "laps": lap_entries,
            }
        )

    manifest = {
        "digest_version": DIGEST_VERSION,
        "stride": stride,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "effective_hz": SAMPLE_RATE_HZ / stride,
        "margin_lap_fraction": margin,
        "row_column": "index into the lap's full stored sample array",
        "corner_positions": "lap fraction, 0-1, from the cohort's frozen map",
        "channels": list(CHANNELS),
        "units": dict(UNITS),
        "cohorts": manifest_cohorts,
        "unavailable_laps": sorted(unavailable),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    )

    return DigestReport(
        cohorts=tuple(labels),
        laps_written=laps_written,
        corners_written=corners_written,
        unavailable_laps=tuple(sorted(unavailable)),
        skipped=tuple(skipped),
    )
