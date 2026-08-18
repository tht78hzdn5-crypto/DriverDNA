"""Driver-level coaching (A51).

M7's coaching is computed per (car, track). That left driver home — the page
a driver actually opens first — with no coaching content at all: tiles, a
loss chart, corpus readiness and a Sync button. To learn what to work on, the
driver had to open each cohort and merge the answers themselves.

The organising idea, and the reason this is worth aggregating rather than
just listing: **a principle that fires at more than one track is the driver,
not the track.** One corner at Spa might be a corner you have not learned;
the same fault at Spa and at Laguna Seca is a habit you carry with you.

Two deliberate constraints:

- **The gate is `gates.min_tracks_for_rollup`, reused.** `cross_track_rollups`
  already answers "how many tracks before a cross-track claim is fair" and a
  second threshold with its own opinion would be one more thing to keep in
  agreement. Below the gate a pattern is listed and suppressed with its
  reason, never dropped.

- **No magnitude is combined across cohorts.** A principle's instances are
  banded in seconds, in trigger rate, or in coefficient of variation
  depending on its gate; summing or averaging across them would produce a
  number with no unit and no meaning, and would be the engine inventing a
  measurement rather than reporting one. Every instance keeps its own car,
  track, corner and value — the same 1:1 discipline the SPA's
  `CoachingInstances` follows within a cohort.
"""

from __future__ import annotations

from typing import Any, Callable

from driverdna.coaching.engine import eligible_principles, eligible_strengths
from driverdna.coaching.ontology import ONTOLOGY_VERSION, PRINCIPLES
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus


def _driver_cohorts(db: Database, driver: str) -> list[tuple[str, str]]:
    rows = db.conn.execute(
        """SELECT DISTINCT car, track FROM laps
           WHERE role='self' AND driver=? AND owner_user_pk=?
           ORDER BY car, track""",
        (driver, db.user_pk),
    ).fetchall()
    return [(r["car"], r["track"]) for r in rows]


def _group(instances: list[dict[str, Any]], config: DriverDNAConfig) -> list[dict[str, Any]]:
    """Group per-cohort instances by principle, gate on track breadth, rank."""
    by_principle: dict[str, list[dict[str, Any]]] = {}
    for inst in instances:
        by_principle.setdefault(inst["coaching_principle_id"], []).append(inst)

    floor = config.gates.min_tracks_for_rollup
    patterns = []
    for principle_id, group in by_principle.items():
        principle = PRINCIPLES[principle_id]
        tracks = {i["track"] for i in group}
        cohorts = {(i["car"], i["track"]) for i in group}
        shown = len(tracks) >= floor
        patterns.append({
            "coaching_principle_id": principle_id,
            "fundamental": principle.fundamental,
            "technique": principle.technique,
            "signal_status": principle.signal_status.value,
            "coaching_expression": principle.coaching_expression,
            "strength_expression": principle.strength_expression,
            "driving_principle": principle.driving_principle,
            "drill": principle.drill,
            "n_tracks": len(tracks),
            "n_cohorts": len(cohorts),
            "n_instances": len(group),
            "shown": shown,
            "gate_reason": None if shown else (
                f"insufficient breadth: {len(tracks)} track(s) < {floor} — "
                "seen at one track only, so it may be the track rather than "
                "the driver"
            ),
            # Each instance keeps its own unit. Nothing here is combined.
            "instances": sorted(
                group, key=lambda i: (i["car"], i["track"], i["corner_id"] or ""),
            ),
        })
    return sorted(
        patterns,
        key=lambda p: (-p["n_tracks"], -p["n_cohorts"], p["coaching_principle_id"]),
    )


def build_coaching_rollup(
    db: Database, *, driver: str, config: DriverDNAConfig,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Aggregate every cohort's coaching into driver-level patterns.

    Calls `eligible_principles`/`eligible_strengths` per cohort directly
    rather than reusing `build_cohort_payload`'s rollup mode — that path
    returns early with only cohort/corner_map/cumulative_loss and carries no
    coaching at all.
    """
    cohorts = _driver_cohorts(db, driver)
    faults: list[dict[str, Any]] = []
    wins: list[dict[str, Any]] = []

    for i, (car, track) in enumerate(cohorts):
        if on_progress is not None:
            on_progress({
                "type": "progress", "index": i, "total": len(cohorts),
                "cohort": f"{car} @ {track}",
            })
        for c in eligible_principles(db, driver=driver, car=car, track=track, config=config):
            # A no_signal self-check is always eligible everywhere, so it
            # would "fire at every track" and top the ranking on breadth
            # while measuring nothing at all.
            if c.signal_status is SignalStatus.NO_SIGNAL:
                continue
            faults.append({
                "coaching_principle_id": c.principle_id,
                "car": car, "track": track, "corner_id": c.corner_id,
                "gap_band": c.gap_band, "magnitude": c.magnitude,
                "magnitude_kind": c.magnitude_kind, "n": c.n,
            })
        for s in eligible_strengths(db, driver=driver, car=car, track=track, config=config):
            wins.append({
                "coaching_principle_id": s.principle_id,
                "car": car, "track": track, "corner_id": s.corner_id,
                "observed": s.observed, "observed_kind": s.observed_kind, "n": s.n,
            })

    return {
        "ontology_version": ONTOLOGY_VERSION,
        "n_cohorts": len(cohorts),
        "min_tracks": config.gates.min_tracks_for_rollup,
        "patterns": _group(faults, config),
        "strengths": _group(wins, config),
    }
