"""Deterministic report payload — the single assembly everything renders from.

The JSON report IS this payload, normalized (sorted keys, fixed float
precision, no wall-clock timestamps). Markdown and HTML render from it; the
coach payload (M4) and chat context bundle (M5) extend it. One assembly,
versioned, so a given question is always answered against a known,
inspectable state.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import numpy as np

from driverdna.attribution.engine import PHASES, baseline
from driverdna.attribution.ranker import (
    cumulative_loss,
    vs_principle_findings,
    vs_reference_findings,
    vs_self_findings,
)
from driverdna.coaching.payload import coaching_section
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.metrics.technique import METRIC_DEFS, summarize
from driverdna.model.scoring import SCORING_MODEL_VERSION, compute_all_beliefs
from driverdna.model.taxonomy import TAXONOMY_VERSION
from driverdna.pipeline import phase_windows_from_stored

PAYLOAD_VERSION = 4  # +incidents

UNAVAILABLE_FUNDAMENTALS = (
    "tire slip/utilization — no slip channel in the source; never inferred",
    "vision/eye-line — not measurable from telemetry; never inferred",
    "fuel load, weather, lap validity, stint index — absent from the source "
    "contract; controls degrade with stated caveats instead",
)


def cohort_slug(car: str, track: str) -> str:
    """URL/file-safe cohort identifier, shared by report filenames and the API."""
    import re

    return re.sub(r"[^A-Za-z0-9]+", "-", f"{car}-{track}").strip("-").lower()


def list_cohorts(db: Database) -> list[dict[str, str]]:
    rows = db.conn.execute(
        """SELECT DISTINCT driver, car, track FROM laps WHERE role='self'
           ORDER BY driver, car, track"""
    ).fetchall()
    return [dict(r) for r in rows]


def driver_model_section(db: Database, *, driver: str, config: DriverDNAConfig) -> dict[str, Any]:
    """Per-fundamental beliefs (M6, dm-v1) — driver-level, pooled across ALL
    of the driver's cohorts, so it is identical across every cohort payload
    for the same driver (computed once here, reused by build_driver_payload
    rather than recomputed per cohort).

    Coach/chat get this "for free": it's just another dict of numbers in the
    payload they already consume, checked by the same numeric-grounding
    validator as findings (docs/SPEC.md, M6 "AI role" bullet — no new
    validator code needed). AI may explain a score; it never adjusts one.
    """
    beliefs = compute_all_beliefs(db, driver=driver, config=config)
    return {
        "driver": driver,
        "scoring_model_version": SCORING_MODEL_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "note": (
            "model estimate, not a measurement of truth — confidence and "
            "evidence count say how much to trust it; more laps (more "
            "sessions, tracks, cars) sharpen it"
        ),
        "beliefs": {
            fid: {
                "signal_status": b.signal_status.value,
                "score": b.score,
                "confidence": b.confidence,
                "evidence_count": b.evidence_count,
                "trend": b.trend,
                "insufficient_reason": b.insufficient_reason,
            }
            for fid, b in beliefs.items()
        },
    }


def incidents_section(
    db: Database, *, driver: str, car: str, track: str
) -> dict[str, Any]:
    """Detected incidents for this cohort's self laps. Each is a single event
    (N=1) — characterised, never generalised into a trait; a repeated pattern
    would need N and go through the finding gates like everything else."""
    from driverdna.incidents.coaching import eligible_principle_for

    events = db.incidents_for_cohort(driver=driver, car=car, track=track)
    for e in events:
        # Deterministic: the engine decides eligibility, never the AI.
        e["coaching_principle_id"] = eligible_principle_for(e["classification"])
    return {
        "n": len(events),
        "events": events,
        "note": (
            "Incidents are single events (N=1): this lap did X, decomposable "
            "to the trace. Not a driver trait, and never priced as recoverable "
            "time. An 'unclassified' incident is detected but its cause was "
            "not clean enough to name — stated, not guessed."
        ),
    }


def build_cohort_payload(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig
) -> dict[str, Any]:
    loaded = db.load_corner_map(car=car, track=track)
    map_pk, corner_map = loaded if loaded else (None, None)
    stored_windows = db.load_corner_windows(map_pk) if map_pk else {}
    windows_by_corner = {
        cid: phase_windows_from_stored(w) for cid, w in sorted(stored_windows.items())
    }
    classes = db.corner_classes(car=car, track=track)

    laps = db.conn.execute(
        """SELECT lap_pk, lap_id, duration_s, session_key, quality_flags
           FROM laps WHERE role='self' AND driver=? AND car=? AND track=?
           ORDER BY lap_pk""",
        (driver, car, track),
    ).fetchall()
    flag_counts: dict[str, int] = {}
    for r in laps:
        for flag in json.loads(r["quality_flags"]):
            flag_counts[flag["code"]] = flag_counts.get(flag["code"], 0) + 1
    sessions = {r["session_key"] for r in laps if r["session_key"] is not None}

    metric_table = db.self_metric_table(driver=driver, car=car, track=track)
    metrics = {
        corner_id: {
            name: asdict(summarize(values))
            for name, values in sorted(metric_table[corner_id].items())
            if summarize(values) is not None
        }
        for corner_id in sorted(metric_table)
    }

    phase_baselines: dict[str, dict[str, Any]] = {}
    for corner_id, windows in windows_by_corner.items():
        for phase in PHASES:
            if windows.window(phase) is None:
                continue
            history = db.phase_history(
                car=car, track=track, corner_id=corner_id, phase=phase,
                role="self", driver=driver,
            )
            base = baseline([h["time_s"] for h in history], config.attribution)
            if base is not None:
                phase_baselines.setdefault(corner_id, {})[phase] = asdict(base)

    findings = (
        vs_self_findings(db, driver=driver, car=car, track=track,
                         windows_by_corner=windows_by_corner, config=config)
        + vs_principle_findings(db, driver=driver, car=car, track=track, config=config)
        + vs_reference_findings(db, driver=driver, car=car, track=track,
                                windows_by_corner=windows_by_corner, config=config)
    )
    # Driver annotations suppress priority framing but never delete the
    # measurement — the finding stays, carrying its annotation.
    annotations = db.annotations()
    finding_dicts = [
        asdict(f) | {"annotation": annotations.get(f.finding_id)} for f in findings
    ]

    caveats = [
        "lap validity has no source channel: statistical outlier screening "
        "with counts, never silent exclusion",
    ]
    if not sessions:
        caveats.append(
            "no session metadata for these laps: session-gated findings are "
            "suppressed and stint-position control is unavailable"
        )

    return {
        "payload_version": PAYLOAD_VERSION,
        "cohort": {
            "driver": driver, "car": car, "track": track,
            "n_laps": len(laps), "n_sessions": len(sessions),
            "lap_durations_s": [round(float(r["duration_s"]), 4) for r in laps],
            # Deltas computed here, not in any renderer: the UI renders what
            # the engine computed, it never derives a new number.
            "lap_delta_s": [
                round(float(r["duration_s"]) - min(float(x["duration_s"]) for x in laps), 4)
                for r in laps
            ] if laps else [],
        },
        "quality": {"flag_counts": flag_counts, "n_laps_flagged": sum(
            1 for r in laps if json.loads(r["quality_flags"])
        )},
        "corner_map": [
            {
                "corner_id": c.corner_id,
                "class": classes.get(c.corner_id),
                "apex_pct": round(c.lap_dist * 100, 2),
                "windows": stored_windows.get(c.corner_id),
            }
            for c in (corner_map.corners if corner_map else ())
        ],
        "metrics": metrics,
        "metric_definitions": {k: {"unit": u, "description": d}
                               for k, (u, d) in METRIC_DEFS.items()},
        "phase_baselines": phase_baselines,
        "cumulative_loss": cumulative_loss(
            db, driver=driver, car=car, track=track,
            windows_by_corner=windows_by_corner, config=config,
        ) if windows_by_corner else {"per_corner": {}, "by_phase": {},
                                     "by_class": {}, "outliers_screened": {}},
        "findings": finding_dicts,
        "unavailable_fundamentals": list(UNAVAILABLE_FUNDAMENTALS),
        "driver_model": driver_model_section(db, driver=driver, config=config),
        "coaching": coaching_section(db, driver=driver, car=car, track=track, config=config),
        "incidents": incidents_section(db, driver=driver, car=car, track=track),
        "caveats": caveats,
    }


def build_driver_payload(db: Database, config: DriverDNAConfig) -> dict[str, Any]:
    """Cross-cohort rollup. Cross-track aggregation only within car + class,
    and only with enough tracks (gated, stated)."""
    cohorts = list_cohorts(db)
    payloads = [build_cohort_payload(db, **c, config=config) for c in cohorts]

    by_car_class: dict[str, dict[str, Any]] = {}
    for p in payloads:
        car = p["cohort"]["car"]
        classes = {c["corner_id"]: c["class"] for c in p["corner_map"]}
        for corner_id, phases in p["cumulative_loss"]["per_corner"].items():
            cls = classes.get(corner_id) or "unclassified"
            entry = by_car_class.setdefault(car, {}).setdefault(
                cls, {"loss_s": 0.0, "tracks": set()}
            )
            entry["loss_s"] += sum(phases.values())
            entry["tracks"].add(p["cohort"]["track"])

    rollups = []
    for car in sorted(by_car_class):
        for cls in sorted(by_car_class[car]):
            entry = by_car_class[car][cls]
            n_tracks = len(entry["tracks"])
            shown = n_tracks >= config.gates.min_tracks_for_rollup
            rollups.append({
                "car": car, "class": cls,
                "loss_s": round(entry["loss_s"], 4),
                "n_tracks": n_tracks,
                "shown": shown,
                "gate_reason": None if shown else (
                    f"insufficient data: {n_tracks} track(s) < "
                    f"{config.gates.min_tracks_for_rollup}"
                ),
            })

    return {
        "payload_version": PAYLOAD_VERSION,
        "cohorts": [p["cohort"] for p in payloads],
        "cross_track_rollups": rollups,
        # Driver-level, so identical across every cohort payload for the
        # same driver — take it from the first rather than recompute.
        "driver_model": payloads[0]["driver_model"] if payloads else None,
        "note": "cross-car claims are computed but never reported in v1",
    }


def _round_floats(obj: Any, ndigits: int = 6) -> Any:
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v, ndigits) for v in obj]
    return obj


def to_normalized_json(payload: dict[str, Any]) -> str:
    """The deterministic serialization: sorted keys, fixed precision, no
    wall-clock anywhere in the payload body."""
    return json.dumps(_round_floats(payload), sort_keys=True, indent=1)
