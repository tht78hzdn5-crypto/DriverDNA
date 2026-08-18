"""M7b: deterministic eligibility, ranking, and gap-band tone.

Pure function of the Driver Model's own downstream data — detector trigger
rates (M2), `cumulative_loss` (M3), vs-self findings (M3), and per-corner
metric values (M2) — plus the ontology (M7a). No AI anywhere in this
module; two runs on the same evidence + `ONTOLOGY_VERSION` always produce
the identical eligible/ranked/banded set (docs/COACHING.md's M7
done-criteria).

coach-onto-v2 (SPEC.md A42): `same_lap_twice`'s MetricCVGate now uses
per-unit normalized pooling — each metric's raw CV divided by its unit's
typical scale (config.model.consistency_unit_reference_cv), then mean within
each unit, then mean across units — instead of a flat mean of raw CVs. This
is the coaching-layer analogue of dm-v2's fix for the identical issue in
SPEC.md A21: five '% lap' metrics with tiny natural CVs would dilute one
'count' metric's genuine high-CV signal in a flat mean, making a
demonstrably inconsistent corner appear negligible.

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
from driverdna.metrics.technique import METRIC_DEFS
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


def _normalized_pooled_cv(
    metric_table: dict,
    corner_id: str,
    metric_names: tuple[str, ...],
    unit_reference: dict[str, float],
) -> float | None:
    """Per-unit normalized CV pooling for same_lap_twice (SPEC.md A42).

    Coaching-layer analogue of dm-v2's _consistency_component: each metric's
    raw CV is divided by its unit's typical scale before pooling, then pooled
    two levels — mean within each unit, then mean across units — so no unit
    dominates purely by having many contributing metrics (e.g. five '% lap'
    metrics each with tiny natural CV would swamp one 'count' metric with large
    natural CV under a flat mean, making a genuinely inconsistent count look
    consistent). Returns None when no metric has a computable CV."""
    by_unit: dict[str, list[float]] = {}
    for name in metric_names:
        values = metric_table.get(corner_id, {}).get(name, [])
        raw_cv = _cv(values)
        if raw_cv is None:
            continue
        unit = METRIC_DEFS[name][0]
        normalized = raw_cv / unit_reference.get(unit, 1.0)
        by_unit.setdefault(unit, []).append(normalized)
    if not by_unit:
        return None
    unit_means = [float(np.mean(vals)) for vals in by_unit.values()]
    return float(np.mean(unit_means))


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
                    unit_reference=config.model.consistency_unit_reference_cv,
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
    unit_reference: dict[str, float],
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
        if gate.metric == "*":
            # per-unit normalized pooling (A42) — same two-level logic as dm-v2's
            # _consistency_component: prevents any unit dominating by metric count
            cv = _normalized_pooled_cv(metric_table, corner_id, metric_names, unit_reference)
        else:
            raw_cvs = [
                _cv(metric_table.get(corner_id, {}).get(name, []))
                for name in metric_names
            ]
            valid = [c for c in raw_cvs if c is not None]
            cv = float(np.mean(valid)) if valid else None
        if cv is None:
            return None
        n = sum(
            len(metric_table.get(corner_id, {}).get(name, []))
            for name in metric_names
            if _cv(metric_table.get(corner_id, {}).get(name, [])) is not None
        )
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
        # A52: no longer restricted to seconds-banded principles. The old
        # rule made `same_lap_twice` permanently incapable of headlining, so
        # the Driver Model could name `consistency` the driver's weakest
        # fundamental while the coaching layer structurally could not tell
        # them to work on it. Comparing the two units is `_severity`'s job.
        headline_eligible=band in ("notable", "major"),
    )


@dataclass(frozen=True)
class CoachingStrength:
    """One (principle, corner) the driver is CLEARING on real evidence.

    Deliberately not a `CoachingCandidate` with an inverted flag: a strength
    carries no gap band and no magnitude, because there is no gap to band —
    giving it those fields would invite a renderer to print "major strength"
    and turn an absence of loss into a fabricated quantity.
    """

    principle_id: str
    signal_status: SignalStatus
    corner_id: str
    n: int
    observed: float  # trigger rate, CV, or opportunity seconds — the value that stayed under its floor
    observed_kind: str
    evidence_ids: tuple[str, ...]


def _corner_strength(
    db, principle, corner_id, *, driver, car, track,
    detector_table, metric_table, findings_by_corner_phase,
    cfg, min_trigger_rate, unit_reference: dict[str, float],
) -> CoachingStrength | None:
    """The strict complement of `_corner_candidate`: a record where there IS
    evidence and the gate did NOT clear.

    Reuses that function's own thresholds rather than defining a second set,
    so a strength and a fault can never both be claimed for one
    (principle, corner) — `test_a_strength_and_a_candidate_never_claim_the
    _same_corner` pins exactly that.

    The evidence bar is deliberately HIGHER than a candidate's: a candidate
    merely flags `thin_evidence`, while a strength is a positive claim about
    the driver and is withheld entirely below the same floor.
    """
    gate = principle.gate
    if isinstance(gate, DetectorGate):
        triggered, total = detector_table.get(corner_id, {}).get(gate.detector, (0, 0))
        if total == 0 or (triggered / total) >= min_trigger_rate:
            return None
        n, observed, kind = total, triggered / total, "trigger_rate"
        evidence_ids = _detector_evidence_ids(
            db, driver=driver, car=car, track=track, corner_id=corner_id,
            detector=gate.detector,
        )
    elif isinstance(gate, MetricCVGate):
        metric_names = _ALL_MEASURED_METRICS if gate.metric == "*" else (gate.metric,)
        if gate.metric == "*":
            cv = _normalized_pooled_cv(metric_table, corner_id, metric_names, unit_reference)
        else:
            valid = [
                c for c in (
                    _cv(metric_table.get(corner_id, {}).get(name, []))
                    for name in metric_names
                ) if c is not None
            ]
            cv = float(np.mean(valid)) if valid else None
        if cv is None or cv >= getattr(cfg, gate.floor_key):
            return None
        n = sum(
            len(metric_table.get(corner_id, {}).get(name, []))
            for name in metric_names
            if _cv(metric_table.get(corner_id, {}).get(name, [])) is not None
        )
        observed, kind = cv, "coefficient_of_variation"
        evidence_ids = _metric_evidence_ids(
            db, driver=driver, car=car, track=track, corner_id=corner_id,
            metric_names=metric_names,
        )
    elif isinstance(gate, FindingGate):
        finding = findings_by_corner_phase.get((corner_id, gate.phase))
        # "no effect" is the ranker's own words for "the evidence gates
        # passed AND the fast/slow laps do not differ here" — the one
        # suppression reason that means competence rather than ignorance.
        # Read off its string rather than re-deriving the test, the same
        # discipline census.py uses.
        if finding is None or finding.shown:
            return None
        if not (finding.gate_reason or "").startswith("no effect"):
            return None
        n, observed, kind = finding.n, finding.seconds or 0.0, "seconds_lost"
        evidence_ids = finding.evidence_ids
    else:  # AlwaysEligible — no_signal only, never a strength
        return None

    if n < cfg.thin_evidence_floor_n:
        return None
    return CoachingStrength(
        principle_id=principle.id, signal_status=principle.signal_status,
        corner_id=corner_id, n=n, observed=round(observed, 4),
        observed_kind=kind, evidence_ids=tuple(evidence_ids),
    )


def eligible_strengths(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig,
) -> list[CoachingStrength]:
    """Every (principle, corner) the driver is clearing on real evidence.

    Same shape and same tables as `eligible_principles`, walked for the
    opposite outcome. Pure function of DB state + config — deterministic,
    no AI.
    """
    windows_by_corner = _cohort_windows_by_corner(db, car, track)
    if not windows_by_corner:
        return []

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

    strengths: list[CoachingStrength] = []
    for principle in PRINCIPLES.values():
        if principle.signal_status is SignalStatus.NO_SIGNAL:
            continue
        for corner_id in sorted(windows_by_corner):
            found = _corner_strength(
                db, principle, corner_id, driver=driver, car=car, track=track,
                detector_table=detector_table, metric_table=metric_table,
                findings_by_corner_phase=findings_by_corner_phase,
                cfg=cfg, min_trigger_rate=config.detectors.min_trigger_rate,
                unit_reference=config.model.consistency_unit_reference_cv,
            )
            if found is not None:
                strengths.append(found)
    return strengths


#: Louder band always outranks a more severe instance of a quieter one.
_BAND_RANK = {"major": 2, "notable": 1, "moderate": 0, "negligible": -1}


def _severity(candidate: CoachingCandidate, cfg) -> float:
    """How far into its OWN scale this candidate sits — its magnitude as a
    multiple of the `major` floor for its own `magnitude_kind`.

    Unit-free by construction, which is the only way seconds and a
    coefficient of variation can share one ranking. Deliberately a private
    sort key and never a payload field: it has no unit, so surfacing it would
    put a meaningless number in front of the driver and — worse — into the
    grounding validator's number pool, where the AI could cite it.
    """
    if candidate.magnitude is None:
        return 0.0
    if candidate.magnitude_kind == "seconds_lost":
        ceiling = cfg.gap_band_major_s
    else:
        ceiling = cfg.cv_band_major
    return candidate.magnitude / ceiling if ceiling > 0 else 0.0


def select_coaching(
    candidates: list[CoachingCandidate],
    strengths: list[CoachingStrength] | None = None,
    *,
    config: DriverDNAConfig | None = None,
) -> dict:
    """Group candidates into headline / secondary / silent(count) / self_checks
    — the delivery-tone grouping docs/COACHING.md describes. Deterministic:
    ties broken by (principle_id, corner_id) for reproducibility."""
    cfg = (config or DriverDNAConfig()).coaching
    # Band first, then severity within it (A52). Ranking on raw `magnitude`
    # across kinds would compare seconds against a coefficient of variation
    # and always pick the CV — not because it is worse, but because CVs are
    # bigger numbers than seconds. Sorted rather than `max` so ties break on
    # ids the same way `secondary` below already does: deterministic, and
    # independent of input order.
    headline_pool = sorted(
        (c for c in candidates if c.headline_eligible),
        key=lambda c: (
            # `gap_band` is None only for no_signal candidates, which are
            # never headline_eligible and so never reach here — `or ""` keeps
            # that unreachable case ranking last instead of raising.
            -_BAND_RANK.get(c.gap_band or "", 0),
            -_severity(c, cfg),
            c.principle_id,
            c.corner_id or "",
        ),
    )
    headline = headline_pool[0] if headline_pool else None
    secondary = sorted(
        (
            c for c in candidates
            if c.gap_band in ("moderate", "notable", "major") and c is not headline
        ),
        key=lambda c: (-(c.magnitude or 0.0), c.principle_id, c.corner_id or ""),
    )
    silent_count = sum(1 for c in candidates if c.gap_band == "negligible")
    self_checks = [c for c in candidates if c.signal_status is SignalStatus.NO_SIGNAL]

    # Ranked by breadth — a principle cleared at more corners is a more
    # established strength. Never by `observed`: trigger rates, CVs and
    # seconds are three different units and ordering across them would be
    # comparing unlike quantities.
    by_principle: dict[str, list[CoachingStrength]] = {}
    for s in strengths or []:
        by_principle.setdefault(s.principle_id, []).append(s)
    ranked_strengths = sorted(
        by_principle.values(), key=lambda g: (-len(g), g[0].principle_id),
    )

    return {
        "headline": headline,
        "headline_reason": None if headline else (
            "insufficient data for the headline slot: nothing clears the "
            "notable gap band yet"
        ),
        "secondary": secondary,
        "silent_count": silent_count,
        "self_checks": self_checks,
        # A51. Note this does NOT repurpose `silent_count`: that still counts
        # `negligible` candidates, which are faults that cost little, not
        # things done well.
        "strengths": ranked_strengths,
    }
