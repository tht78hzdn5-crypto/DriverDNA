"""M7b: deterministic eligibility, ranking, and gap-band tone.

Pure function of the Driver Model's own downstream data — detector trigger
rates (M2), `cumulative_loss` (M3), vs-self findings (M3), and per-corner
metric values (M2) — plus the ontology (M7a). No AI anywhere in this
module; two runs on the same evidence + `ONTOLOGY_VERSION` always produce
the identical eligible/ranked/banded set (docs/COACHING.md's M7
done-criteria).

Resolved ambiguity, flagged (2026-07-20): docs/COACHING.md's "Gap bands —
mechanics" says both "moderate -> quiet... never the headline" AND "if
nothing clears moderate -> insufficient data for the headline slot too,"
which read together as a small inconsistency about whether moderate can
ever lead. This implementation takes the more specific, more repeated rule
(moderate is never the headline) as binding: the headline pool is
notable/major only. A driver whose best item is moderate-or-below gets
"insufficient data for the headline slot" exactly as the second bullet
says — it just means that threshold is notable, not moderate. Flag this if
the intended reading differs.

Second resolved ambiguity: gap band controls volume (silent/quiet/loud);
`signal_status` (measured/proxy) independently controls conviction
(commit vs. tentative), per "Conviction where measured..." A `proxy`
principle (trust_the_proxy) can still win the headline slot on magnitude,
but callers must keep phrasing it tentatively regardless of band — the
candidate carries `signal_status` precisely so that stays enforceable
downstream (validator, artifact, AI prompt), not silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from driverdna.attribution.ranker import cumulative_loss, vs_self_findings
from driverdna.coaching.ontology import (
    PRINCIPLES,
    AlwaysEligible,
    DetectorGate,
    FindingGate,
    MetricCVGate,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.taxonomy import TECHNIQUES, SignalStatus
from driverdna.pipeline import phase_windows_from_stored

GAP_BANDS = ("negligible", "moderate", "notable", "major")

_ALL_MEASURED_METRICS: tuple[str, ...] = tuple(sorted({
    m for t in TECHNIQUES.values()
    if t.signal_status is SignalStatus.MEASURED
    for m in t.metrics
}))


@dataclass(frozen=True)
class CoachingCandidate:
    principle_id: str
    signal_status: SignalStatus
    corner_id: str | None  # None for no_signal (cohort-wide, never per-corner)
    gap_band: str | None  # None only for no_signal (no band at all)
    magnitude: float | None
    magnitude_kind: str | None  # "seconds_lost" | "coefficient_of_variation" | None
    n: int
    thin_evidence: bool
    evidence_ids: tuple[str, ...]
    headline_eligible: bool  # seconds-banded AND notable/major — the only pool that can lead


def _cohort_windows_by_corner(db: Database, car: str, track: str) -> dict:
    loaded = db.load_corner_map(car=car, track=track)
    if loaded is None:
        return {}
    map_pk, _ = loaded
    stored = db.load_corner_windows(map_pk)
    return {cid: phase_windows_from_stored(w) for cid, w in stored.items()}


def _cv(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    arr = np.asarray(values, dtype=float)
    mean = float(np.mean(arr))
    if mean == 0:
        return None
    return float(np.std(arr, ddof=1) / abs(mean))


def _seconds_band(seconds: float, cfg) -> str:
    if seconds >= cfg.gap_band_major_s:
        return "major"
    if seconds >= cfg.gap_band_notable_s:
        return "notable"
    if seconds >= cfg.gap_band_moderate_s:
        return "moderate"
    return "negligible"


def _cv_band(cv: float, cfg) -> str:
    if cv >= cfg.cv_band_major:
        return "major"
    if cv >= cfg.cv_band_notable:
        return "notable"
    if cv >= cfg.cv_band_moderate:
        return "moderate"
    return "negligible"


def _detector_evidence_ids(
    db: Database, *, driver: str, car: str, track: str, corner_id: str, detector: str,
) -> tuple[str, ...]:
    rows = db.conn.execute(
        """SELECT d.obs_pk FROM detector_results d
           JOIN corner_observations o ON o.obs_pk = d.obs_pk
           JOIN corners c ON c.corner_pk = o.corner_pk
           JOIN laps l ON l.lap_pk = o.lap_pk
           WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
             AND c.corner_id=? AND d.detector=? AND d.triggered=1
           ORDER BY d.obs_pk""",
        (driver, car, track, corner_id, detector),
    ).fetchall()
    return tuple(f"obs:{r['obs_pk']}" for r in rows)


def _metric_evidence_ids(
    db: Database, *, driver: str, car: str, track: str, corner_id: str,
    metric_names: tuple[str, ...],
) -> tuple[str, ...]:
    if not metric_names:
        return ()
    placeholders = ",".join("?" * len(metric_names))
    rows = db.conn.execute(
        f"""SELECT DISTINCT mv.obs_pk FROM metric_values mv
            JOIN corner_observations o ON o.obs_pk = mv.obs_pk
            JOIN corners c ON c.corner_pk = o.corner_pk
            JOIN laps l ON l.lap_pk = o.lap_pk
            WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
              AND c.corner_id=? AND mv.name IN ({placeholders}) AND mv.value IS NOT NULL
            ORDER BY mv.obs_pk""",
        [driver, car, track, corner_id, *metric_names],
    ).fetchall()
    return tuple(f"obs:{r['obs_pk']}" for r in rows)


def eligible_principles(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig,
) -> list[CoachingCandidate]:
    """Every (principle, corner) pair whose gate clears, banded and ranked.
    Pure function of DB state + config — deterministic, no AI."""
    windows_by_corner = _cohort_windows_by_corner(db, car, track)
    candidates: list[CoachingCandidate] = []

    if windows_by_corner:
        loss = cumulative_loss(
            db, driver=driver, car=car, track=track,
            windows_by_corner=windows_by_corner, config=config,
        )
        detector_table = db.self_detector_table(driver=driver, car=car, track=track)
        metric_table = db.self_metric_table(driver=driver, car=car, track=track)
        findings_by_corner_phase = {
            (f.corner_id, f.phase): f
            for f in vs_self_findings(
                db, driver=driver, car=car, track=track,
                windows_by_corner=windows_by_corner, config=config,
            )
            if f.kind == "opportunity"
        }
        cfg = config.coaching

        for principle in PRINCIPLES.values():
            if principle.signal_status is SignalStatus.NO_SIGNAL:
                continue
            for corner_id in sorted(windows_by_corner):
                candidate = _corner_candidate(
                    db, principle, corner_id, driver=driver, car=car, track=track,
                    detector_table=detector_table, metric_table=metric_table,
                    findings_by_corner_phase=findings_by_corner_phase,
                    loss=loss, cfg=cfg, min_trigger_rate=config.detectors.min_trigger_rate,
                )
                if candidate is not None:
                    candidates.append(candidate)

    for principle in PRINCIPLES.values():
        if principle.signal_status is SignalStatus.NO_SIGNAL:
            assert isinstance(principle.gate, AlwaysEligible)
            candidates.append(CoachingCandidate(
                principle_id=principle.id, signal_status=principle.signal_status,
                corner_id=None, gap_band=None, magnitude=None, magnitude_kind=None,
                n=0, thin_evidence=False, evidence_ids=(), headline_eligible=False,
            ))

    return candidates


def _corner_candidate(
    db, principle, corner_id, *, driver, car, track,
    detector_table, metric_table, findings_by_corner_phase, loss, cfg, min_trigger_rate,
) -> CoachingCandidate | None:
    gate = principle.gate
    if isinstance(gate, DetectorGate):
        triggered, total = detector_table.get(corner_id, {}).get(gate.detector, (0, 0))
        if total == 0 or (triggered / total) < min_trigger_rate:
            return None
        n = total
        evidence_ids = _detector_evidence_ids(
            db, driver=driver, car=car, track=track, corner_id=corner_id,
            detector=gate.detector,
        )
    elif isinstance(gate, FindingGate):
        finding = findings_by_corner_phase.get((corner_id, gate.phase))
        if finding is None or not finding.shown:
            return None
        n = finding.n
        evidence_ids = finding.evidence_ids
    elif isinstance(gate, MetricCVGate):
        metric_names = _ALL_MEASURED_METRICS if gate.metric == "*" else (gate.metric,)
        cvs, n = [], 0
        for name in metric_names:
            values = metric_table.get(corner_id, {}).get(name, [])
            cv = _cv(values)
            if cv is not None:
                cvs.append(cv)
                n += len(values)
        if not cvs:
            return None
        cv = float(np.mean(cvs))
        floor = getattr(cfg, gate.floor_key)
        if cv < floor:
            return None
        evidence_ids = _metric_evidence_ids(
            db, driver=driver, car=car, track=track, corner_id=corner_id,
            metric_names=metric_names,
        )
    else:  # pragma: no cover - AlwaysEligible only used for no_signal, handled elsewhere
        return None

    if principle.band_phase is not None:
        magnitude = loss["per_corner"].get(corner_id, {}).get(principle.band_phase)
        if magnitude is None:
            return None
        band = _seconds_band(magnitude, cfg)
        magnitude_kind = "seconds_lost"
    else:
        magnitude = cv  # only reachable via MetricCVGate with band_phase=None (same_lap_twice)
        band = _cv_band(magnitude, cfg)
        magnitude_kind = "coefficient_of_variation"

    return CoachingCandidate(
        principle_id=principle.id, signal_status=principle.signal_status,
        corner_id=corner_id, gap_band=band, magnitude=round(magnitude, 4),
        magnitude_kind=magnitude_kind, n=n, thin_evidence=n < cfg.thin_evidence_floor_n,
        evidence_ids=evidence_ids,
        headline_eligible=(magnitude_kind == "seconds_lost" and band in ("notable", "major")),
    )


def select_coaching(candidates: list[CoachingCandidate]) -> dict:
    """Group candidates into headline / secondary / silent(count) / self_checks
    — the delivery-tone grouping docs/COACHING.md describes. Deterministic:
    ties broken by (principle_id, corner_id) for reproducibility."""
    headline_pool = [c for c in candidates if c.headline_eligible]
    headline = max(
        headline_pool, key=lambda c: (c.magnitude, c.principle_id, c.corner_id or ""),
        default=None,
    )
    secondary = sorted(
        (
            c for c in candidates
            if c.gap_band in ("moderate", "notable", "major") and c is not headline
        ),
        key=lambda c: (-(c.magnitude or 0.0), c.principle_id, c.corner_id or ""),
    )
    silent_count = sum(1 for c in candidates if c.gap_band == "negligible")
    self_checks = [c for c in candidates if c.signal_status is SignalStatus.NO_SIGNAL]

    return {
        "headline": headline,
        "headline_reason": None if headline else (
            "insufficient data for the headline slot: nothing clears the "
            "notable gap band yet"
        ),
        "secondary": secondary,
        "silent_count": silent_count,
        "self_checks": self_checks,
    }
