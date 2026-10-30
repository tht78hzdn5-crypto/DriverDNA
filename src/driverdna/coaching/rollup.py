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

**Era recurrence (A59, Stage 2).** Each fault pattern and each strength
is also annotated with `eras_fired` / `eras_total` / `tendency_state`
from the persisted tendency projection (`coaching/eras.py`): fixed eras
— per-driver lap blocks, never re-cut, with frozen summaries for closed
eras — replace Stage 1's A36 re-cut buckets. The pooled pattern above
is untouched by this; the annotation is a second, longitudinal reading
of the same evidence, and where there is no dated-era evidence it
states nothing (`tendency_state` None) rather than guessing. Fault
patterns additionally carry their bespoke tendency variant (when the
principle has one for the state) and, when persistent, their escalated
`drill_followup`.
"""

from __future__ import annotations

from typing import Any, Callable

from driverdna.coaching.engine import (
    _measured_verdict_corners,
    _proxy_presentable,
    eligible_principles,
    eligible_strengths,
)
from driverdna.coaching.eras import (
    TENDENCY_MODEL_VERSION,
    era_count,
    refresh_tendencies,
)
from driverdna.coaching.ontology import ONTOLOGY_VERSION, PRINCIPLES
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import SignalStatus

#: Re-exported for the Stage 1 import sites: the tendency projection's
#: shape version (SPEC.md A59), owned by `coaching/eras.py`.
__all__ = ["TENDENCY_MODEL_VERSION", "build_coaching_rollup"]


def _driver_cohorts(db: Database, driver: str) -> list[tuple[str, str]]:
    rows = db.conn.execute(
        """SELECT DISTINCT car, track FROM laps
           WHERE role='self' AND driver=? AND owner_user_pk=?
           ORDER BY car, track""",
        (driver, db.user_pk),
    ).fetchall()
    return [(r["car"], r["track"]) for r in rows]


def _group(
    instances: list[dict[str, Any]], config: DriverDNAConfig,
    *, tendency_rows: dict[tuple[str, str], dict[str, Any]] | None = None,
    tendency_side: str = "fault", eras_total: int = 0,
) -> list[dict[str, Any]]:
    """Group per-cohort instances by principle, gate on track breadth, rank.

    With `tendency_rows` given (the persisted projection keyed by
    (principle_id, side)), each pattern also carries its A59 tendency
    annotation: state, era counts, first/last seen eras, and — for fault
    patterns — the bespoke variant and the persistent-only followup.
    A pattern with no projection row (its evidence is undated, or its
    eras are all thin) states nothing: `tendency_state` None, era counts
    zero, `eras_total` the era count.
    """
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
        pattern: dict[str, Any] = {
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
        }
        if tendency_rows is not None:
            row = tendency_rows.get((principle_id, tendency_side))
            pattern["eras_total"] = eras_total
            if row is None:
                pattern["eras_fired"] = 0
                pattern["tendency_state"] = None
                pattern["first_seen_era"] = None
                pattern["last_seen_era"] = None
                pattern["clearing_streak"] = 0
                pattern["band_before"] = None
                pattern["current_band"] = None
                pattern["tendency_variant"] = None
                pattern["drill_followup"] = None
            else:
                pattern["eras_fired"] = row["eras_fired"]
                pattern["tendency_state"] = row["state"]
                pattern["first_seen_era"] = row["first_seen_era"]
                pattern["last_seen_era"] = row["last_seen_era"]
                pattern["clearing_streak"] = row["clearing_streak"]
                pattern["band_before"] = row["band_before"]
                pattern["current_band"] = row["current_band"]
                pattern["tendency_variant"] = row["variant"]
                pattern["drill_followup"] = row["drill_followup"]
        patterns.append(pattern)
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
        cohort_candidates = eligible_principles(
            db, driver=driver, car=car, track=track, config=config,
        )
        cohort_strengths = eligible_strengths(
            db, driver=driver, car=car, track=track, config=config,
        )
        # A57: the same measured-over-proxy presentation precedence as
        # select_coaching — where the measured brake-point principle has
        # a verdict at a corner in this cohort, the proxy's instance for
        # that corner is not listed here either.
        covered = _measured_verdict_corners(cohort_candidates, cohort_strengths)
        for c in cohort_candidates:
            # A no_signal self-check is always eligible everywhere, so it
            # would "fire at every track" and top the ranking on breadth
            # while measuring nothing at all.
            if c.signal_status is SignalStatus.NO_SIGNAL:
                continue
            if not _proxy_presentable(c.principle_id, c.corner_id, covered):
                continue
            faults.append({
                "coaching_principle_id": c.principle_id,
                "car": car, "track": track, "corner_id": c.corner_id,
                "gap_band": c.gap_band, "magnitude": c.magnitude,
                "magnitude_kind": c.magnitude_kind, "n": c.n,
            })
        for s in cohort_strengths:
            if not _proxy_presentable(s.principle_id, s.corner_id, covered):
                continue
            wins.append({
                "coaching_principle_id": s.principle_id,
                "car": car, "track": track, "corner_id": s.corner_id,
                "observed": s.observed, "observed_kind": s.observed_kind, "n": s.n,
            })

    # Stage 2 refresh-on-read: assigning and closing eras and upserting
    # the projection happens here, so the driver payload (which builds
    # this rollup) is always fresh; cohort payloads read the last
    # refresh without recomputing.
    rows = refresh_tendencies(db, driver, config)
    tendency_rows = {(r["principle_id"], r["side"]): r for r in rows}
    eras_total = era_count(db, driver)

    return {
        "ontology_version": ONTOLOGY_VERSION,
        "tendency_version": TENDENCY_MODEL_VERSION,
        "n_cohorts": len(cohorts),
        "min_tracks": config.gates.min_tracks_for_rollup,
        "patterns": _group(
            faults, config, tendency_rows=tendency_rows,
            tendency_side="fault", eras_total=eras_total,
        ),
        "strengths": _group(
            wins, config, tendency_rows=tendency_rows,
            tendency_side="strength", eras_total=eras_total,
        ),
    }
