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
from typing import Any, Callable

from driverdna.attribution.engine import PHASES, baseline, reference_envelope
from driverdna.attribution.ranker import (
    cumulative_loss,
    vs_principle_findings,
    vs_reference_findings,
    vs_self_findings,
)
from driverdna.coaching.payload import coaching_section
from driverdna.coaching.rollup import build_coaching_rollup
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.metrics.technique import METRIC_DEFS, summarize
from driverdna.model.reading import build_reading
from driverdna.model.scoring import (
    SCORING_MODEL_VERSION,
    _effective_weights,
    compute_all_beliefs,
)
from driverdna.model.taxonomy import FUNDAMENTALS, TAXONOMY_VERSION
from driverdna.pipeline import phase_windows_from_stored

PAYLOAD_VERSION = 9  # +driver_model.{reading,beliefs[].components,basis_reason} (A51)

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
        """SELECT DISTINCT driver, car, track FROM laps WHERE role='self' AND owner_user_pk=?
           ORDER BY driver, car, track""",
        (db.user_pk,),
    ).fetchall()
    return [dict(r) for r in rows]


def _components_dict(belief, config: DriverDNAConfig) -> dict[str, Any]:
    """A51: the score, decomposed, plus why the basis is narrow when it is.

    A14 requires a composite score to be "always decomposable to the
    sources". These three were computed inside scoring.py and dropped, so
    `score` reached the driver as an opaque number with no way to open it
    up. `weight` is the share the component actually carried AFTER
    redistribution — value x weight, summed, is the score.
    """
    effective = _effective_weights(belief.components, config)
    return {
        "components": {
            name: {
                "value": None if c.value is None else round(c.value, 4),
                "n": c.n,
                "weight": round(effective[name], 4),
            }
            for name, c in sorted(belief.components.items())
        },
        "basis_reason": belief.basis_reason,
    }


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
        # A51: which fundamentals are this driver's strength and weakness.
        # Rank-only and measured-only — see model/reading.py for why a proxy
        # never takes a verdict slot.
        "reading": build_reading(beliefs, config),
        "note": (
            "model estimate, not a measurement of truth — confidence and "
            "evidence count say how much to trust it; more laps (more "
            "sessions, tracks, cars) sharpen it"
        ),
        "beliefs": {
            fid: {
                # The engine owns the driver-facing name (A46), the same
                # reasoning as explain.py owning methodology text: the SPA
                # and the static reports must not each keep their own
                # spelling of "Corner exit" and drift apart.
                "label": FUNDAMENTALS[fid].label,
                "signal_status": b.signal_status.value,
                "score": b.score,
                "confidence": b.confidence,
                "evidence_count": b.evidence_count,
                "trend": b.trend,
                "insufficient_reason": b.insufficient_reason,
                **_components_dict(b, config),
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
    from driverdna.coaching.ontology import PRINCIPLES
    from driverdna.incidents.coaching import eligible_principle_for

    events = db.incidents_for_cohort(driver=driver, car=car, track=track)
    for e in events:
        # Deterministic: the engine decides eligibility, never the AI.
        principle_id = eligible_principle_for(e["classification"])
        e["coaching_principle_id"] = principle_id
        # The SPA can't import coaching/ontology.py (Python-only), so a
        # newcomer-legible mechanism/drill needs to travel through the
        # payload itself — same principle text `coaching.headline` etc.
        # already surface for findings, just also attached here, once,
        # deterministically (Track B, docs/UI-V3-PLAN.md). unclassified/
        # external incidents (principle_id is None) get none of this: the
        # engine itself named no cause, so there is nothing to coach.
        principle = PRINCIPLES.get(principle_id) if principle_id else None
        e["coaching_expression"] = principle.coaching_expression if principle else None
        e["drill"] = principle.drill if principle else None
        e["driving_principle"] = principle.driving_principle if principle else None
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


def references_section(db: Database, *, car: str, track: str) -> dict[str, Any]:
    """Reference-pool identity and depth (R2, SPEC.md A39): who is in the
    envelope, how many, and the lap-time envelope (n/median/best) their
    laps add up to — reusing `reference_envelope` (built for per-corner
    phase times) over whole-lap `duration_s` instead. One aggregated pool,
    not split per contributor (SPEC.md A39): the honest default when
    identity comes from the existing `driver` column rather than a
    dedicated label.

    A lap R3 curation has excluded stays listed here, flagged — curation
    marks, it never hides — but never counts toward `n` or the envelope,
    which only ever reflects the active pool `phase_history` itself already
    filters to."""
    contributors = db.reference_laps_for_cohort(car=car, track=track)
    active = [c for c in contributors if not c["excluded"] and not c["incomplete"]]
    envelope = reference_envelope([c["duration_s"] for c in active])
    return {
        "n": len(active),
        "n_excluded": len(contributors) - len(active),
        "envelope": asdict(envelope) if envelope else None,
        "contributors": contributors,
    }


def build_cohort_payload(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig,
    _for_driver_rollup: bool = False,
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
           FROM laps WHERE role='self' AND driver=? AND car=? AND track=? AND owner_user_pk=?
           ORDER BY lap_pk""",
        (driver, car, track, db.user_pk),
    ).fetchall()
    sessions = {r["session_key"] for r in laps if r["session_key"] is not None}

    incomplete = [
        any(f["code"] == "incomplete_lap" for f in json.loads(r["quality_flags"]))
        for r in laps
    ]
    complete_durations = [
        float(r["duration_s"]) for r, inc in zip(laps, incomplete, strict=True) if not inc
    ]
    best_complete = min(complete_durations) if complete_durations else None

    cohort_dict = {
        "driver": driver, "car": car, "track": track,
        "n_laps": len(laps), "n_sessions": len(sessions),
        "lap_durations_s": [round(float(r["duration_s"]), 4) for r in laps],
        "lap_ids": [r["lap_id"] for r in laps],
        "lap_incomplete": incomplete,
        "lap_delta_s": [
            None if inc else round(float(r["duration_s"]) - best_complete, 4)
            for r, inc in zip(laps, incomplete, strict=True)
        ] if laps and best_complete is not None else [],
    }

    corner_map_list = [
        {
            "corner_id": c.corner_id,
            "class": classes.get(c.corner_id),
            "apex_pct": round(c.lap_dist * 100, 2),
            "windows": stored_windows.get(c.corner_id),
        }
        for c in (corner_map.corners if corner_map else ())
    ]

    loss = cumulative_loss(
        db, driver=driver, car=car, track=track,
        windows_by_corner=windows_by_corner, config=config,
    ) if windows_by_corner else {"per_corner": {}, "by_phase": {},
                                 "by_class": {}, "outliers_screened": {}}

    if _for_driver_rollup:
        return {
            "cohort": cohort_dict,
            "corner_map": corner_map_list,
            "cumulative_loss": loss,
        }

    flag_counts: dict[str, int] = {}
    for r in laps:
        for flag in json.loads(r["quality_flags"]):
            flag_counts[flag["code"]] = flag_counts.get(flag["code"], 0) + 1

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
        "cohort": cohort_dict,
        "quality": {"flag_counts": flag_counts, "n_laps_flagged": sum(
            1 for r in laps if json.loads(r["quality_flags"])
        )},
        "corner_map": corner_map_list,
        "metrics": metrics,
        "metric_definitions": {k: {"unit": u, "description": d}
                               for k, (u, d) in METRIC_DEFS.items()},
        "phase_baselines": phase_baselines,
        "cumulative_loss": loss,
        "findings": finding_dicts,
        "unavailable_fundamentals": list(UNAVAILABLE_FUNDAMENTALS),
        "driver_model": driver_model_section(db, driver=driver, config=config),
        "coaching": coaching_section(db, driver=driver, car=car, track=track, config=config),
        "incidents": incidents_section(db, driver=driver, car=car, track=track),
        "references": references_section(db, car=car, track=track),
        "caveats": caveats,
    }


def build_driver_payload(
    db: Database, config: DriverDNAConfig, *, _include_census: bool = True,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Cross-cohort rollup. Cross-track aggregation only within car + class,
    and only with enough tracks (gated, stated).

    _include_census: internal sentinel used by census._suppression_section to
    break the recursion (census calls build_driver_payload for rollup reasons,
    which must not trigger another census build). Never set by callers.

    on_progress: optional callback for SSE streaming — called once per cohort
    rollup so the UI can show "Computing cohort 3 of 25..."."""
    def _progress(evt: dict[str, Any]) -> None:
        if on_progress is not None:
            on_progress(evt)

    cohorts = list_cohorts(db)
    rollup_payloads = []
    for i, c in enumerate(cohorts):
        _progress({
            "type": "progress", "index": i, "total": len(cohorts),
            "cohort": f"{c['car']} @ {c['track']}",
        })
        rollup_payloads.append(
            build_cohort_payload(db, **c, config=config, _for_driver_rollup=True)
        )

    by_car_class: dict[str, dict[str, Any]] = {}
    for p in rollup_payloads:
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

    driver_name = cohorts[0]["driver"] if cohorts else None
    _progress({"type": "progress_phase", "phase": "driver_model"})
    driver_model = driver_model_section(db, driver=driver_name, config=config) if driver_name else None

    # A51: driver-level coaching. Until now coaching existed only per
    # (car, track), so driver home had none at all.
    _progress({"type": "progress_phase", "phase": "coaching_rollup"})
    coaching_rollup = (
        build_coaching_rollup(db, driver=driver_name, config=config, on_progress=on_progress)
        if driver_name else None
    )

    census_data = None
    if _include_census and driver_name:
        _progress({"type": "progress_phase", "phase": "census"})
        from driverdna.census import build_census, census_to_dict
        try:
            census_data = census_to_dict(build_census(db, config, driver=driver_name))
        except ValueError:
            pass  # no self laps

    return {
        "payload_version": PAYLOAD_VERSION,
        "cohorts": [p["cohort"] for p in rollup_payloads],
        "cross_track_rollups": rollups,
        "driver_model": driver_model,
        "coaching_rollup": coaching_rollup,
        "census": census_data,
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
