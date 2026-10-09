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

**Era recurrence (A55, Stage 1).** Each fault pattern is also annotated
with `eras_fired` / `eras_total` / `tendency_state`: in how many of the
driver's eras — A36's date-ordered, equal-count lap buckets, reused
verbatim — the pattern's principle fired at all, running the existing
per-cohort eligibility on each era's laps alone. The pooled pattern
above is untouched by this; the annotation is a second, longitudinal
reading of the same evidence, and where there is no dated-era evidence
it states nothing (`tendency_state` None) rather than guessing. Stage 1
annotates fault patterns only; strengths keep their A51 shape, and the
strength-complement half of `resolved` detection is Stage 2.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from typing import Any, Callable

from driverdna.coaching.engine import eligible_principles, eligible_strengths
from driverdna.coaching.ontology import ONTOLOGY_VERSION, PRINCIPLES
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.history import _equal_count_chunks
from driverdna.model.taxonomy import SignalStatus

#: The annotation's own shape version, per SPEC.md A55 — a computed
#: projection like A36's SERIES_VERSION, not a persisted model (Stage 2's
#: driver_tendencies table is what will carry it across computations).
TENDENCY_MODEL_VERSION = "tendency-v1"


def _driver_cohorts(db: Database, driver: str) -> list[tuple[str, str]]:
    rows = db.conn.execute(
        """SELECT DISTINCT car, track FROM laps
           WHERE role='self' AND driver=? AND owner_user_pk=?
           ORDER BY car, track""",
        (driver, db.user_pk),
    ).fetchall()
    return [(r["car"], r["track"]) for r in rows]


def _era_lap_buckets(
    db: Database, driver: str, config: DriverDNAConfig,
) -> list[frozenset[int]]:
    """The driver's eras: A36's date-ordered, equal-count buckets of dated
    laps (`model/history.py`'s chunker and config, reused — a second
    bucketing with its own opinion would be one more thing to keep in
    agreement).

    Two degradations, both stated rather than silent:

    - Below A36's own availability floor (`history_buckets` x
      `trend_min_laps_per_bucket` dated laps) a multi-era split is not
      honest yet, so the whole dated history is ONE era. A single era can
      only ever read `new` — it cannot manufacture a longitudinal claim.
    - Undated laps are in no era at all. An era is a claim about WHEN;
      an undated lap has no when, so it contributes to the pooled
      pattern (as it always has) and to no era.
    """
    dated = db.dated_self_laps(driver)
    if not dated:
        return []
    n_buckets = max(1, config.model.history_buckets)
    floor = config.model.trend_min_laps_per_bucket
    if len(dated) < n_buckets * floor:
        return [frozenset(pk for pk, _ in dated)]
    chunks = _equal_count_chunks([pk for pk, _ in dated], n_buckets)
    return [frozenset(chunk) for chunk in chunks]


def _tendency_state(
    fired_eras: AbstractSet[int], eras_total: int, *,
    persistent_min_share: float,
) -> str | None:
    """A pattern's longitudinal state from the eras it fired in.

    The partition, for a nonempty fired set F within `eras_total` eras
    (latest era = eras_total - 1):

    - latest not in F -> `resolved`: it fired before and has stopped —
      the absence IS the finding, and it can only be stated because the
      earlier firing is on record.
    - F == {latest} -> `new`: never seen before the most recent era.
    - latest in F and |F| / eras_total >= `persistent_min_share` ->
      `persistent`: the habit, not a corner.
    - otherwise -> `recurring`: at least two eras including the latest,
      below the persistent share.

    No dated-era evidence (F empty — including a corpus with no dated
    laps) -> None: no longitudinal claim is made. A55's `improving` and
    `dormant` states are not computed in Stage 1: `improving` needs a
    per-era band trend in the principle's own magnitude_kind, and
    `dormant` shades `resolved` by era distance — both Stage 2.
    """
    if eras_total <= 0 or not fired_eras:
        return None
    latest = eras_total - 1
    if latest not in fired_eras:
        return "resolved"
    if fired_eras == {latest}:
        return "new"
    if len(fired_eras) / eras_total >= persistent_min_share:
        return "persistent"
    return "recurring"


def _era_firing(
    db: Database, *, driver: str, cohorts: list[tuple[str, str]],
    eras: list[frozenset[int]], config: DriverDNAConfig,
) -> dict[str, set[int]]:
    """principle_id -> the era indices in which it fired in at least one
    cohort, running the existing eligibility per (era, cohort) on that
    era's laps alone. A candidate of any band counts as firing — the
    pooled rollup's own instances are band-blind the same way."""
    fired: dict[str, set[int]] = {}
    for era_idx, era_pks in enumerate(eras):
        for car, track in cohorts:
            for c in eligible_principles(
                db, driver=driver, car=car, track=track, config=config,
                lap_pks=era_pks,
            ):
                if c.signal_status is SignalStatus.NO_SIGNAL:
                    continue
                fired.setdefault(c.principle_id, set()).add(era_idx)
    return fired


def _group(
    instances: list[dict[str, Any]], config: DriverDNAConfig,
    *, era_firing: dict[str, set[int]] | None = None, eras_total: int = 0,
) -> list[dict[str, Any]]:
    """Group per-cohort instances by principle, gate on track breadth, rank.

    With `era_firing` given (the fault patterns), each pattern also
    carries its A55 era annotation. Strengths are grouped without it —
    Stage 1 annotates faults only (see the module docstring)."""
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
        if era_firing is not None:
            fired = era_firing.get(principle_id, set())
            pattern["eras_fired"] = len(fired)
            pattern["eras_total"] = eras_total
            pattern["tendency_state"] = _tendency_state(
                fired, eras_total,
                persistent_min_share=config.coaching.tendency_persistent_min_share,
            )
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

    eras = _era_lap_buckets(db, driver, config)
    era_firing = (
        _era_firing(db, driver=driver, cohorts=cohorts, eras=eras, config=config)
        if eras else {}
    )

    return {
        "ontology_version": ONTOLOGY_VERSION,
        "tendency_version": TENDENCY_MODEL_VERSION,
        "n_cohorts": len(cohorts),
        "min_tracks": config.gates.min_tracks_for_rollup,
        "patterns": _group(
            faults, config, era_firing=era_firing, eras_total=len(eras),
        ),
        "strengths": _group(wins, config),
    }
