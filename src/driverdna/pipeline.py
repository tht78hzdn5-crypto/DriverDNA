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

from driverdna.config import DriverDNAConfig
from driverdna.corners.classify import (
    MS_TO_KMH,
    CornerClass,
    classify_with_hysteresis,
)
from driverdna.corners.identity import build_corner_map
from driverdna.corners.segmenter import segment_lap
from driverdna.db import Database
from driverdna.ingest.parser import parse_lap
from driverdna.metrics.detectors import run_detectors
from driverdna.metrics.technique import compute_corner_metrics


@dataclass
class ImportResult:
    lap_pk: int
    was_new: bool
    assigned: list[str | None] = field(default_factory=list)
    admitted: list[str] = field(default_factory=list)  # corners added to the map
    class_changes: list[tuple[str, str, str]] = field(default_factory=list)
    # ^ (corner_id, old_class, new_class) — surfaced, never silent


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
    config: DriverDNAConfig,
) -> ImportResult:
    lap = parse_lap(path)
    lap_pk, was_new = db.import_lap(
        lap, driver=driver, car=car, track=track, role=role,
        session_key=session_key, imported_at=imported_at,
    )
    if not was_new:
        return ImportResult(lap_pk=lap_pk, was_new=False)

    spans = segment_lap(lap, config)
    loaded = db.load_corner_map(car=car, track=track)
    if loaded is None:
        corner_map = build_corner_map([(lap, spans)], config.identity)
        map_pk = db.store_corner_map(
            corner_map, car=car, track=track, built_from_n_laps=1
        )
    else:
        map_pk, corner_map = loaded

    assigned = corner_map.match_lap(lap, spans, config.identity)
    for span, corner_id in zip(spans, assigned):
        metrics = compute_corner_metrics(lap, span, config)
        results = run_detectors(lap, span, metrics, config)
        db.store_observation(
            lap=lap,
            lap_pk=lap_pk,
            span=span,
            corner_pk=db.corner_pk(map_pk, corner_id) if corner_id else None,
            metrics=metrics,
            detector_results=results,
        )

    admitted = db.admit_pending_candidates(car=car, track=track, cfg=config.identity)
    class_changes = _reclassify(db, driver=driver, car=car, track=track, config=config)
    return ImportResult(
        lap_pk=lap_pk,
        was_new=True,
        assigned=assigned,
        admitted=admitted,
        class_changes=class_changes,
    )


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
