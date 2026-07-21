"""Ingest pipeline: file -> parse -> segment -> identify -> measure -> store (M2).

One lap in, everything derived from it persisted, every map/class change
surfaced in the result — the single orchestration path used by
`driverdna import` and the tests. First data for a (car, track) cohort
builds and freezes the corner map; every later lap is matched against it.
Corner classes are re-derived after each import from self-lap medians with
hysteresis; changes are returned as events, never applied silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from driverdna.attribution.engine import PhaseWindows, derive_windows
from driverdna.attribution.engine import phase_times as compute_phase_times
from driverdna.config import DriverDNAConfig
from driverdna.corners.classify import (
    MS_TO_KMH,
    CornerClass,
    classify_with_hysteresis,
)
from driverdna.corners.identity import _gps_ok, _meters, build_corner_map
from driverdna.corners.segmenter import segment_lap
from driverdna.db import Database, landmark_positions
from driverdna.incidents import scan_incidents
from driverdna.ingest.parser import TelemetryLap, parse_lap
from driverdna.metrics.detectors import run_detectors
from driverdna.metrics.technique import compute_corner_metrics


def phase_windows_from_stored(stored: dict) -> PhaseWindows:
    return PhaseWindows(
        entry_start=stored["entry_start"],
        turn_in=stored["turn_in"],
        apex=stored["apex"],
        exit_end=stored["exit_end"],
    )


@dataclass
class ImportResult:
    lap_pk: int
    status: str  # "imported" | "exists" | "duplicate"
    assigned: list[str | None] = field(default_factory=list)
    admitted: list[str] = field(default_factory=list)  # corners added to the map
    class_changes: list[tuple[str, str, str]] = field(default_factory=list)
    # ^ (corner_id, old_class, new_class) — surfaced, never silent

    @property
    def was_new(self) -> bool:
        return self.status == "imported"


def import_lap_file(
    db: Database,
    path: Path,
    *,
    driver: str,
    car: str,
    track: str,
    role: str = "self",
    session_key: str | None = None,
    imported_at: str | None = None,
    lap_date: str | None = None,
    config: DriverDNAConfig,
) -> ImportResult:
    """`lap_date` (optional) mirrors what `sync` writes from the API's
    startTime — set it (via `driverdna import --date`, or a manifest
    entry's `date`) to make manually-imported laps eligible for M6 trend,
    the same as synced ones."""
    lap = parse_lap(path)
    return import_parsed_lap(
        db, lap, driver=driver, car=car, track=track, role=role,
        session_key=session_key, imported_at=imported_at, lap_date=lap_date,
        config=config,
    )


def import_parsed_lap(
    db: Database,
    lap: TelemetryLap,
    *,
    driver: str,
    car: str,
    track: str,
    role: str = "self",
    session_key: str | None = None,
    run_index: int | None = None,
    imported_at: str | None = None,
    lap_date: str | None = None,
    config: DriverDNAConfig,
) -> ImportResult:
    """Store + measure an already-parsed lap.

    `import_lap_file` (file path -> `parse_lap` -> here) is the manual-import
    entry point; `sync` (M0b+) calls this directly with a lap parsed from an
    in-memory API CSV fetch (`parse_lap_text`), plus real session/run/date
    metadata the API supplies that a bare CSV file cannot.
    """
    lap_pk, status = db.import_lap(
        lap, driver=driver, car=car, track=track, role=role,
        session_key=session_key, run_index=run_index, imported_at=imported_at,
        lap_date=lap_date,
    )
    if status != "imported":
        return ImportResult(lap_pk=lap_pk, status=status)

    spans = segment_lap(lap, config)
    loaded = db.load_corner_map(car=car, track=track)
    if loaded is None:
        corner_map = build_corner_map([(lap, spans)], config.identity)
        map_pk = db.store_corner_map(
            corner_map, car=car, track=track, built_from_n_laps=1
        )
        # Freeze canonical phase windows alongside the map (F1): every later
        # lap is measured over these identical spans, never its own landmarks.
        for span, corner_id in zip(
            spans, corner_map.match_lap(lap, spans, config.identity)
        ):
            if corner_id is None:
                continue
            windows = derive_windows([landmark_positions(lap, span.landmarks)])
            if windows is not None:
                db.store_corner_windows(
                    db.corner_pk(map_pk, corner_id),
                    entry_start=windows.entry_start, turn_in=windows.turn_in,
                    apex=windows.apex, exit_end=windows.exit_end,
                )
    else:
        map_pk, corner_map = loaded

    stored_windows = db.load_corner_windows(map_pk)
    assigned = corner_map.match_lap(lap, spans, config.identity)
    for span, corner_id in zip(spans, assigned):
        metrics = compute_corner_metrics(lap, span, config)
        results = run_detectors(lap, span, metrics, config)
        obs_pk = db.store_observation(
            lap=lap,
            lap_pk=lap_pk,
            span=span,
            corner_pk=db.corner_pk(map_pk, corner_id) if corner_id else None,
            metrics=metrics,
            detector_results=results,
        )
        if corner_id and corner_id in stored_windows:
            times = compute_phase_times(
                lap.lap_dist, lap.elapsed_s,
                phase_windows_from_stored(stored_windows[corner_id]),
            )
            if times:
                db.store_phase_times(obs_pk, times)

    admitted = db.admit_pending_candidates(car=car, track=track, cfg=config.identity)
    for corner_id in admitted:
        _freeze_windows_for_admitted(db, map_pk, corner_id)
    class_changes = _reclassify(db, driver=driver, car=car, track=track, config=config)

    # Incident scan (deterministic): self laps only — reference laps are never
    # scanned into self incident records. Corner positions (post-admission)
    # label an incident's location; detection itself needs only the trace.
    if role == "self":
        incidents = scan_incidents(
            lap,
            corner_positions=db.corner_positions(car=car, track=track),
            config=config.incidents,
        )
        if incidents:
            db.store_incidents(lap_pk, incidents)
    return ImportResult(
        lap_pk=lap_pk,
        status="imported",
        assigned=assigned,
        admitted=admitted,
        class_changes=class_changes,
    )


def _freeze_windows_for_admitted(db: Database, map_pk: int, corner_id: str) -> None:
    """An admitted corner gets its windows from its candidate observations'
    median landmark positions, then backfilled phase times from whatever raw
    blobs are still within retention (missing blobs are skipped — landmark
    positions are compact, but time interpolation needs the raw arrays)."""
    corner_pk = db.corner_pk(map_pk, corner_id)
    windows = derive_windows(db.observation_positions(corner_pk))
    if windows is None:
        return
    db.store_corner_windows(
        corner_pk, entry_start=windows.entry_start, turn_in=windows.turn_in,
        apex=windows.apex, exit_end=windows.exit_end,
    )
    rows = db.conn.execute(
        "SELECT obs_pk, lap_pk FROM corner_observations WHERE corner_pk=?",
        (corner_pk,),
    ).fetchall()
    for row in rows:
        arrays = db.load_lap_arrays(int(row["lap_pk"]))
        if arrays is None:
            continue
        times = compute_phase_times(arrays["lap_dist"], arrays["elapsed_s"], windows)
        if times:
            db.store_phase_times(int(row["obs_pk"]), times)


def _reclassify(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig
) -> list[tuple[str, str, str]]:
    """Re-derive classes from self-lap medians, hysteresis-sticky.

    Classification is a self statistic: reference laps never move a class.
    """
    loaded = db.load_corner_map(car=car, track=track)
    if loaded is None:
        return []
    map_pk, corner_map = loaded
    changes: list[tuple[str, str, str]] = []
    for identity in corner_map.corners:
        history = db.self_metric_history(
            driver=driver, car=car, track=track,
            corner_id=identity.corner_id, metric="min_speed_kmh",
        )
        if not history:
            continue
        row = db.conn.execute(
            "SELECT corner_pk, class FROM corners WHERE map_pk=? AND corner_id=?",
            (map_pk, identity.corner_id),
        ).fetchone()
        previous = CornerClass(row["class"]) if row["class"] else None
        new_class, changed = classify_with_hysteresis(
            float(np.median(history)), previous, config.classification
        )
        if previous is None or changed:
            db.set_corner_class(int(row["corner_pk"]), new_class.value)
        if changed:
            changes.append((identity.corner_id, previous.value, new_class.value))
    return changes


# --- rebuild-map: in-place refreeze of a frozen cohort map (SPEC.md A22) ----


@dataclass
class CornerRebuild:
    corner_id: str
    centroid_shift_m: float | None  # meters the centroid moved; None if GPS-degraded
    window_changed: bool
    laps_remeasured: int
    laps_cleared: list[int] = field(default_factory=list)  # blob-evicted lap_pks


@dataclass
class RebuildResult:
    car: str
    track: str
    existed: bool  # False when there was no map for this cohort to rebuild
    corners: list[CornerRebuild] = field(default_factory=list)
    admitted: list[str] = field(default_factory=list)
    class_changes: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def total_cleared(self) -> int:
        return sum(len(c.laps_cleared) for c in self.corners)


def _windows_differ(old: dict, new: PhaseWindows) -> bool:
    def diff(a: float | None, b: float | None) -> bool:
        if a is None or b is None:
            return (a is None) != (b is None)  # None <-> value is a change
        return abs(a - b) > 1e-9

    return (
        diff(old.get("entry_start"), new.entry_start)
        or diff(old.get("turn_in"), new.turn_in)
        or diff(old.get("apex"), new.apex)
        or diff(old.get("exit_end"), new.exit_end)
    )


def rebuild_cohort_map(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig
) -> RebuildResult:
    """In-place refreeze of a cohort's frozen corner map (SPEC.md A22).

    Recomputes every existing corner's centroid + canonical windows from the
    cohort's FULL current observation set (not just the laps that originally
    froze the map), re-measures phase times for every observation whose raw
    blob still survives retention, and DELETEs + reports phase times for any
    whose blob was evicted (a lap that can't be honestly re-interpolated
    against the new windows is never left silently stale — philosophy #7).

    In-place, not versioned: `corner_pk` / `corner_id` never change, so every
    evidence ID that resolves through a corner stays valid; existing
    observations keep their corner assignment (the centroid is recomputed FROM
    those assignments, so the two stay consistent by construction — no
    re-matching). New geometry still enters through the existing admission
    path; classes are re-derived after, hysteresis-sticky, self-only.
    """
    loaded = db.load_corner_map(car=car, track=track)
    if loaded is None:
        return RebuildResult(car=car, track=track, existed=False)
    map_pk, corner_map = loaded
    old_windows = db.load_corner_windows(map_pk)

    corner_results: list[CornerRebuild] = []
    for identity in corner_map.corners:
        corner_pk = db.corner_pk(map_pk, identity.corner_id)

        # (a) centroid — median apex position of the corner's own observations.
        apexes = db.corner_apex_positions(corner_pk)
        shift_m: float | None = None
        if apexes:
            new_lat = float(np.nanmedian([a[0] for a in apexes]))
            new_lon = float(np.nanmedian([a[1] for a in apexes]))
            new_dist = float(np.median([a[2] for a in apexes]))
            if _gps_ok(identity.lat, identity.lon) and _gps_ok(new_lat, new_lon):
                shift_m = _meters(identity.lat, identity.lon, new_lat, new_lon)
            db.update_corner_centroid(
                corner_pk, lat=new_lat, lon=new_lon, lap_dist=new_dist
            )

        # (b) canonical windows — from every observation's landmark positions.
        window_changed = False
        new_windows = derive_windows(db.observation_positions(corner_pk))
        if new_windows is not None:
            window_changed = _windows_differ(
                old_windows.get(identity.corner_id, {}), new_windows
            )
            db.store_corner_windows(
                corner_pk, entry_start=new_windows.entry_start,
                turn_in=new_windows.turn_in, apex=new_windows.apex,
                exit_end=new_windows.exit_end,
            )

        # (c) re-measure phase times against the new window; a lap whose raw
        #     blob was evicted can't be honestly re-interpolated — clear it and
        #     report, never leave a number measured against a retired window.
        remeasured = 0
        cleared: list[int] = []
        if new_windows is not None:
            for obs_pk, lap_pk in db.observations_of_corner(corner_pk):
                arrays = db.load_lap_arrays(lap_pk)
                if arrays is None:
                    db.delete_phase_times(obs_pk)
                    cleared.append(lap_pk)
                    continue
                times = compute_phase_times(
                    arrays["lap_dist"], arrays["elapsed_s"], new_windows
                )
                if times:
                    db.store_phase_times(obs_pk, times)
                    remeasured += 1

        corner_results.append(CornerRebuild(
            corner_id=identity.corner_id, centroid_shift_m=shift_m,
            window_changed=window_changed, laps_remeasured=remeasured,
            laps_cleared=cleared,
        ))

    # Genuinely new geometry (unmatched candidates) enters through the same
    # audited admission path a normal import uses — never silently.
    admitted = db.admit_pending_candidates(car=car, track=track, cfg=config.identity)
    for corner_id in admitted:
        _freeze_windows_for_admitted(db, map_pk, corner_id)
    class_changes = _reclassify(db, driver=driver, car=car, track=track, config=config)

    return RebuildResult(
        car=car, track=track, existed=True, corners=corner_results,
        admitted=admitted, class_changes=class_changes,
    )
