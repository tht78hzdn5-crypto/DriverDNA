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
from driverdna.corners.identity import build_corner_map
from driverdna.corners.segmenter import segment_lap
from driverdna.db import Database, landmark_positions
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
