"""dm-v1: the deterministic, versioned per-fundamental scoring model (M6b).

A pure function of a driver's accumulated evidence (already persisted by
M1-M5) to (score 0-100, confidence 0-1, evidence_count, trend) per
fundamental. Same evidence + same `SCORING_MODEL_VERSION` -> same belief,
always (docs/ARCHITECTURE_VISION.md, the Scoring Contract; docs/SPEC.md,
Milestone 6). No AI anywhere in this module.

Evidence pools across ALL of a driver's cohorts (car x track), not one at a
time - that pooling is the Driver Model's whole point (a belief about the
driver, not the lap). See SPEC.md decision-of-record #6's 2026-07-20
clarification: this is distinct from, and not blocked by, the finding
layer's per-car reporting restriction.

Three components, each 0-1, each backed by a distinct evidence source and
weighted per `config.model`:

  adherence   - 1 - trigger rate on the fundamental's own detectors
                (vs-principle signal: how often the flagged pattern occurs).
  opportunity - normalized median seconds lost vs the robust per-corner
                baseline, on the fundamental's own phases (vs-self signal).
  consistency - normalized coefficient of variation on the fundamental's own
                metrics (lap-to-lap repeatability of the same technique).
                The "consistency" fundamental itself has no metrics of its
                own by design (module docstring, taxonomy.py) - it pools
                every MEASURED technique's metrics instead, matching its
                description ("pooled across every measured technique").

A fundamental with no detectors, or no phases, has that component silently
absent - the weight is never applied by force, it is redistributed
proportionally across whichever components DO have evidence, renormalized
to sum to 1 (never a fabricated neutral fill-in for missing evidence). If
NO component has evidence, or evidence is thinner than
`config.model.min_evidence_for_score` laps, the belief reads "insufficient
data" - never a guessed number, per constitution philosophy #3.

`no_signal` fundamentals (taxonomy.SignalStatus.NO_SIGNAL) never reach the
component math at all: score and confidence are None/0.0 unconditionally,
matching docs/COACHING.md's "a confidence value never launders an
unmeasured inference" - the same rule stated at the coaching layer.
`proxy` fundamentals reach the math but their confidence is capped
(`config.model.proxy_confidence_cap`) - real signal, honestly bounded.

Trend: SPEC.md's Milestone 6 requires `trend` to always be present but
allows "unavailable" until real lap dates exist. `sync` (M0b+) is now the
first ingestion path that sets `laps.lap_date` (from the Garage61 API's
startTime); manual `import` still does not. dm-v1 nonetheless still always
reports "unavailable" here, deliberately: _trend()'s date-bucketing/
direction logic is a self-contained addition, not yet built, not a
side-effect of sync landing. The field is never dropped in the meantime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from driverdna.attribution.ranker import cumulative_loss
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import (
    FUNDAMENTALS,
    TAXONOMY_VERSION,
    TECHNIQUES,
    SignalStatus,
    fundamental_detectors,
    fundamental_metrics,
)
from driverdna.pipeline import phase_windows_from_stored

SCORING_MODEL_VERSION = "dm-v1"


@dataclass(frozen=True)
class Belief:
    fundamental: str
    signal_status: SignalStatus
    score: float | None
    confidence: float
    evidence_count: int
    trend: str
    insufficient_reason: str | None
    scoring_model_version: str
    taxonomy_version: str


@dataclass(frozen=True)
class _Component:
    value: float | None  # 0-1, normalized; None = no evidence for this component
    n: int  # observation count backing it, for inspection/debugging only


def _driver_cohorts(db: Database, driver: str) -> list[tuple[str, str]]:
    rows = db.conn.execute(
        """SELECT DISTINCT car, track FROM laps WHERE role='self' AND driver=?
           ORDER BY car, track""",
        (driver,),
    ).fetchall()
    return [(r["car"], r["track"]) for r in rows]


def _cohort_windows_by_corner(db: Database, car: str, track: str) -> dict[str, Any]:
    loaded = db.load_corner_map(car=car, track=track)
    if loaded is None:
        return {}
    map_pk, _ = loaded
    stored = db.load_corner_windows(map_pk)
    return {cid: phase_windows_from_stored(w) for cid, w in stored.items()}


def _scoring_metric_names(fundamental_id: str) -> tuple[str, ...]:
    """Metrics that count as evidence for this fundamental's score.

    "consistency" is deliberately cross-cutting (see taxonomy.py) and maps
    to no metrics of its own; here it pools every MEASURED technique's
    metrics, matching `_consistency_component`'s own definition below so
    evidence_count and the component it counts never disagree.
    """
    if fundamental_id == "consistency":
        return tuple(sorted({
            m for t in TECHNIQUES.values()
            if t.signal_status is SignalStatus.MEASURED
            for m in t.metrics
        }))
    return fundamental_metrics(fundamental_id)


def _adherence_component(
    db: Database, driver: str, cohorts: list[tuple[str, str]],
    detector_names: tuple[str, ...],
) -> _Component:
    if not detector_names:
        return _Component(None, 0)
    triggered_total = 0
    n_total = 0
    for car, track in cohorts:
        table = db.self_detector_table(driver=driver, car=car, track=track)
        for detectors in table.values():
            for detector, (triggered, total) in detectors.items():
                if detector in detector_names:
                    triggered_total += triggered
                    n_total += total
    if n_total == 0:
        return _Component(None, 0)
    return _Component(1.0 - triggered_total / n_total, n_total)


def _opportunity_component(
    db: Database, driver: str, cohorts: list[tuple[str, str]],
    phases: tuple[str, ...], config: DriverDNAConfig,
) -> _Component:
    if not phases:
        return _Component(None, 0)
    losses: list[float] = []
    n_total = 0
    for car, track in cohorts:
        windows_by_corner = _cohort_windows_by_corner(db, car, track)
        if not windows_by_corner:
            continue
        loss = cumulative_loss(
            db, driver=driver, car=car, track=track,
            windows_by_corner=windows_by_corner, config=config,
        )
        for corner_id, phase_losses in loss["per_corner"].items():
            for phase, seconds in phase_losses.items():
                if phase not in phases:
                    continue
                losses.append(seconds)
                n_total += loss["per_corner_phase_n"][corner_id][phase]
    if not losses:
        return _Component(None, 0)
    avg_loss_s = float(np.mean(losses))
    ceiling = config.model.opportunity_ceiling_s
    normalized = max(0.0, min(1.0, 1.0 - avg_loss_s / ceiling)) if ceiling > 0 else 0.0
    return _Component(normalized, n_total)


def _consistency_component(
    db: Database, driver: str, cohorts: list[tuple[str, str]],
    fundamental_id: str, config: DriverDNAConfig,
) -> _Component:
    metric_names = _scoring_metric_names(fundamental_id)
    if not metric_names:
        return _Component(None, 0)
    cvs: list[float] = []
    n_total = 0
    for car, track in cohorts:
        table = db.self_metric_table(driver=driver, car=car, track=track)
        for metrics in table.values():
            for metric, values in metrics.items():
                if metric not in metric_names or len(values) < 2:
                    continue
                arr = np.asarray(values, dtype=float)
                mean = float(np.mean(arr))
                if mean == 0:
                    continue  # CV is undefined at a zero mean; skip, don't fabricate
                cvs.append(float(np.std(arr, ddof=1) / abs(mean)))
                n_total += len(values)
    if not cvs:
        return _Component(None, 0)
    avg_cv = float(np.mean(cvs))
    ceiling = config.model.consistency_cv_ceiling
    normalized = max(0.0, min(1.0, 1.0 - avg_cv / ceiling)) if ceiling > 0 else 0.0
    return _Component(normalized, n_total)


def _weighted_score(
    components: dict[str, _Component], config: DriverDNAConfig
) -> float | None:
    weights = {
        "adherence": config.model.weight_adherence,
        "opportunity": config.model.weight_opportunity,
        "consistency": config.model.weight_consistency,
    }
    available = {k: c for k, c in components.items() if c.value is not None}
    if not available:
        return None
    total_w = sum(weights[k] for k in available)
    return sum(c.value * weights[k] for k, c in available.items()) / total_w * 100.0


def _confidence(
    db: Database, driver: str, cohorts: list[tuple[str, str]],
    evidence_count: int, signal_status: SignalStatus, config: DriverDNAConfig,
) -> float:
    m = config.model
    n_sessions = db.driver_session_count(driver)
    n_tracks = len({track for _, track in cohorts})
    n_cars = len({car for car, _ in cohorts})
    ratios = [
        min(1.0, evidence_count / m.confidence_evidence_floor),
        min(1.0, n_sessions / m.confidence_session_floor),
        min(1.0, n_tracks / m.confidence_track_floor),
        min(1.0, n_cars / m.confidence_car_floor),
    ]
    confidence = float(np.mean(ratios))
    if signal_status is SignalStatus.PROXY:
        confidence = min(confidence, m.proxy_confidence_cap)
    return confidence


def _trend(db: Database, driver: str) -> str:
    # See module docstring: lap_date is now populated by sync, but the
    # date-bucketing/direction logic itself isn't built yet. Always
    # "unavailable" today, by design, not by omission.
    return "unavailable"


def _no_signal_belief(fundamental_id: str) -> Belief:
    return Belief(
        fundamental=fundamental_id, signal_status=SignalStatus.NO_SIGNAL,
        score=None, confidence=0.0, evidence_count=0, trend="unavailable",
        insufficient_reason=(
            "no telemetry channel for this fundamental — never inferred "
            "(docs/COACHING.md's tri-state signal rule)"
        ),
        scoring_model_version=SCORING_MODEL_VERSION, taxonomy_version=TAXONOMY_VERSION,
    )


def _insufficient_belief(
    fundamental_id: str, signal_status: SignalStatus, evidence_count: int, reason: str,
) -> Belief:
    return Belief(
        fundamental=fundamental_id, signal_status=signal_status,
        score=None, confidence=0.0, evidence_count=evidence_count, trend="unavailable",
        insufficient_reason=reason,
        scoring_model_version=SCORING_MODEL_VERSION, taxonomy_version=TAXONOMY_VERSION,
    )


def compute_belief(
    db: Database, *, driver: str, fundamental_id: str, config: DriverDNAConfig,
) -> Belief:
    """Deterministic belief for one (driver, fundamental) — pure function of
    the evidence currently persisted plus SCORING_MODEL_VERSION."""
    fundamental = FUNDAMENTALS[fundamental_id]
    signal_status = fundamental.signal_status

    if signal_status is SignalStatus.NO_SIGNAL:
        return _no_signal_belief(fundamental_id)

    cohorts = _driver_cohorts(db, driver)
    metric_names = _scoring_metric_names(fundamental_id)
    detector_names = fundamental_detectors(fundamental_id)
    evidence_count = db.fundamental_evidence_lap_count(
        driver=driver, metric_names=metric_names, detector_names=detector_names,
    )

    floor = config.model.min_evidence_for_score
    if evidence_count < floor:
        return _insufficient_belief(
            fundamental_id, signal_status, evidence_count,
            f"insufficient evidence: {evidence_count} lap(s) < minimum {floor}",
        )

    components = {
        "adherence": _adherence_component(db, driver, cohorts, detector_names),
        "opportunity": _opportunity_component(db, driver, cohorts, fundamental.phases, config),
        "consistency": _consistency_component(db, driver, cohorts, fundamental_id, config),
    }
    score = _weighted_score(components, config)
    if score is None:
        # Reachable in principle (a lap could carry a metric value without
        # ever clearing the >=2-samples-per-corner bar every component
        # needs) — still an honest "insufficient", not a crash or a guess.
        return _insufficient_belief(
            fundamental_id, signal_status, evidence_count,
            "insufficient evidence: no scorable component had data",
        )

    confidence = _confidence(db, driver, cohorts, evidence_count, signal_status, config)
    return Belief(
        fundamental=fundamental_id, signal_status=signal_status,
        score=round(score, 2), confidence=round(confidence, 4),
        evidence_count=evidence_count, trend=_trend(db, driver),
        insufficient_reason=None,
        scoring_model_version=SCORING_MODEL_VERSION, taxonomy_version=TAXONOMY_VERSION,
    )


def compute_all_beliefs(
    db: Database, *, driver: str, config: DriverDNAConfig,
) -> dict[str, Belief]:
    return {
        fid: compute_belief(db, driver=driver, fundamental_id=fid, config=config)
        for fid in sorted(FUNDAMENTALS)
    }


def store_all_beliefs(
    db: Database, *, driver: str, config: DriverDNAConfig,
    computed_at: str | None = None,
) -> dict[str, Belief]:
    """Recompute and persist every fundamental's current belief for `driver`."""
    beliefs = compute_all_beliefs(db, driver=driver, config=config)
    for belief in beliefs.values():
        db.store_belief(
            driver=driver, fundamental=belief.fundamental,
            signal_status=belief.signal_status.value, score=belief.score,
            confidence=belief.confidence, evidence_count=belief.evidence_count,
            trend=belief.trend, insufficient_reason=belief.insufficient_reason,
            scoring_model_version=belief.scoring_model_version,
            taxonomy_version=belief.taxonomy_version, computed_at=computed_at,
        )
    return beliefs
