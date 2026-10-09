"""The deterministic, versioned per-fundamental scoring model (M6b).

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
  consistency - robust absolute dispersion on the fundamental's own
                metrics (lap-to-lap repeatability of the same technique):
                each metric's scaled MAD, divided by that metric's own
                reference dispersion
                (config.model.consistency_metric_reference_dispersion)
                before pooling - see "Absolute robust dispersion (dm-v3)"
                below. (dm-v1/dm-v2 used the coefficient of variation
                here instead.) The "consistency" fundamental itself has
                no metrics of its own by design (module docstring,
                taxonomy.py) - it pools every MEASURED technique's metrics
                instead, matching its description ("pooled across every
                measured technique").

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

Trend (built 2026-07-20; dated manual import 2026-07-21): a fundamental's
`trend` is the direction of its own score between an earlier and a recent
bucket of the driver's dated laps (`_trend`). Dated self-laps (lap_date set
— `sync` sets it from the API's startTime; `driverdna import --date` or a
manifest entry's own `date` field sets it too, since the Garage61 API caps
`/laps` at ~1 saved lap per driver per cohort, so a real per-cohort trend
needs the driver's own exported history) are ordered by (lap_date, lap_pk)
and split by count at the midpoint; the same scoring function runs on each
half, and the recent-minus-earlier delta is
banded against `config.model.trend_delta_points`. It stays "unavailable"
when there are too few dated laps (`trend_min_laps_per_bucket` per half) or
a bucket lacks scorable evidence — so on today's undated fixtures it still
reads "unavailable", by honest gap, not omission. Completing this field
does not change dm-v1's score/confidence for any evidence set, so
SCORING_MODEL_VERSION is unchanged (the field was always specified; dated
evidence never existed under the old code path). See `_trend` for the
flagged era-relative-baseline limitation on the opportunity component.

Per-unit consistency normalization (dm-v2, built 2026-07-21): dm-v1's
`consistency` component pooled every metric's *raw* CV (std/mean) with a
plain average. This was documented as a cross-*cohort* raw-magnitude issue,
but investigation against real multi-cohort telemetry (GR86/Spa +
Mustang/Summit Point + Mustang/Laguna) showed each CV was already computed
from one cohort's own values - the actual mechanism was cross-*metric-type*:
a "% lap" landmark position metric has a naturally tiny CV (~0.01) while a
small-integer "count" metric (e.g. steering corrections) has a naturally
huge one (~1.0) for equally repeatable driving, and a plain average let the
naturally-high-CV metrics dominate regardless of the driver's actual
consistency. `_consistency_component` now divides each raw CV by its own
unit's typical scale (`config.model.consistency_unit_reference_cv`, keyed by
metrics/technique.py's METRIC_DEFS units), then pools in two levels - mean
within each unit, then mean across units - rather than one flat mean, so a
unit with many contributing metrics/corners cannot dominate purely by sample
count either (see `_consistency_component`'s own docstring for both
rejected alternatives: a flat mean, and a median at either level). This is a
real formula change for the same evidence, so SCORING_MODEL_VERSION bumps
dm-v1 -> dm-v2 per the Scoring Contract
(ARCHITECTURE_VISION.md condition 2); see SPEC.md's Milestone 6 amendment
for the full record, including the correction to the original (inaccurate)
"cross-cohort" diagnosis. The separate, structurally similar M7 coaching-
layer note (`same_lap_twice` / `CoachingConfig.consistency_cv_floor`,
SPEC.md's Milestone 7 section) is a different code path and is NOT resolved
by this change.

Absolute robust dispersion (dm-v3, built 2026-10-08): two defects in the
dm-v2 statistic, both measured on the owner's real 282-lap corpus
(BUG-042/BUG-044). First, CV divides a sample's dispersion by that
sample's own mean, so for a *position* metric it measures where the
landmark sits as much as how much it moves: Brands Hatch C10's brake
points scatter under half a percentage point, but the landmark sits at
0.57% of lap, so the normalized value read ~110x; one wrap-around apex
sample at Silverstone C18 (0.013 among ~94-99) manufactured a normalized
~95 from a single lap. Second, against anchors that were medians of a
smaller 2026-07-21 sample, a realistic multi-car corpus pooled 2.3898
against the 2.0 ceiling, so `consistency` and `vehicle_management` both
clamped to exactly 0.0 - the value the scale assigns the worst driver
it can express, reported at 100% confidence. dm-v3 removes the sample
mean from the statistic entirely: each (corner, metric) sample
contributes its scaled MAD (1.4826 * median absolute deviation from the
sample median - a robust estimator, so one anomalous landmark moves a
sample's reading by a bounded amount, never by orders of magnitude;
with a resolution floor for majority-tied samples, whose MAD is exactly
0 despite visible variation - see `_scaled_mad`), normalized by that metric's own reference dispersion
(`config.model.consistency_metric_reference_dispersion`: the metric's
typical scaled MAD, measured 2026-10-08 from the same 282-lap corpus,
per-metric because metrics sharing a unit differ in natural magnitude;
per-unit fallback in `consistency_unit_reference_dispersion`). The
two-level pooling is unchanged. The ceiling is re-anchored to
`consistency_dispersion_ceiling` (3.0) so the reference-typical driver
(pooled 1.0) scores 0.667 and the floor requires three times typical
dispersion in every unit at once. On the corpus that exposed the
defects, the consistency component moves 0.0 -> 0.56 and
vehicle_management's 0.0 -> 0.69, with per-cohort pooled dispersion
spreading 1.09-1.65 - the statistic discriminates again. A real formula
change for the same evidence, so SCORING_MODEL_VERSION bumps
dm-v2 -> dm-v3 (SPEC.md A56). The coaching layer's `same_lap_twice`
gates keep the dm-v2 normalized-CV statistic - a different code path,
deferred exactly as the dm-v2 change deferred it, and recorded in A56.

Trend saturation gate (dm-v3, BUG-043): under dm-v2 a belief whose
headline score was clamped at exactly 0.0 could still report trend
"improving", because `_trend`'s date-halves straddled the clamp (bucket
scores 0.0 and 7.88; headline 0.0). A number pinned at a scale bound
cannot express a direction. `compute_belief` now suppresses a
directional trend whenever the headline score sits at a bound (0.0 or
100.0), reporting trend "unavailable" with the reason on the belief
(`trend_reason`, payload-visible) instead of asserting the direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from driverdna.attribution.ranker import cumulative_loss
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.metrics.technique import METRIC_DEFS
from driverdna.model.taxonomy import (
    FUNDAMENTALS,
    TAXONOMY_VERSION,
    TECHNIQUES,
    SignalStatus,
    fundamental_detectors,
    fundamental_metrics,
)
from driverdna.pipeline import phase_windows_from_stored

SCORING_MODEL_VERSION = "dm-v3"


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
    #: The three components the score was built from (A51). Computed here all
    #: along and discarded before this — which left `score` an opaque number,
    #: against A14's "always decomposable to the sources". Empty for a belief
    #: that never scored.
    components: dict[str, "_Component"] = field(default_factory=dict)
    #: Set when the score rests on fewer than all three components, naming
    #: which are missing AND why. Distinct from `insufficient_reason`, which
    #: means there is no score at all; this one accompanies a real number.
    basis_reason: str | None = None
    #: Set when a directional trend was suppressed because the headline
    #: score is pinned at a scale bound (BUG-043, dm-v3): the trend reads
    #: "unavailable" and this says why, in the payload next to the trend.
    #: None whenever the trend stands as computed (or was unavailable for
    #: the ordinary too-few-dated-laps reason).
    trend_reason: str | None = None


@dataclass(frozen=True)
class _Component:
    value: float | None  # 0-1, normalized; None = no evidence for this component
    n: int  # observation count backing it, for inspection/debugging only


def _driver_cohorts(db: Database, driver: str) -> list[tuple[str, str]]:
    rows = db.conn.execute(
        """SELECT DISTINCT car, track FROM laps WHERE role='self' AND driver=? AND owner_user_pk=?
           ORDER BY car, track""",
        (driver, db.user_pk),
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
    lap_pks: frozenset[int] | None = None,
    cache: "_CohortCache | None" = None,
) -> _Component:
    if not detector_names:
        return _Component(None, 0)
    triggered_total = 0
    n_total = 0
    reusable = cache is not None and cache.lap_pks == lap_pks
    for car, track in cohorts:
        if reusable and (car, track) in cache.detectors:
            table = cache.detectors[(car, track)]
        else:
            table = db.self_detector_table(driver=driver, car=car, track=track, lap_pks=lap_pks)
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
    lap_pks: frozenset[int] | None = None,
    cache: "_CohortCache | None" = None,
) -> _Component:
    if not phases:
        return _Component(None, 0)
    losses: list[float] = []
    n_total = 0
    # Windows are the frozen corner map's geometry, independent of which
    # laps are in scope — reusable regardless of lap_pks, unlike the other
    # two caches below (a bucket's cache is still worth building once and
    # sharing across a bucket's 7 fundamentals, since windows are looked up
    # per fundamental too).
    windows_reusable = cache is not None
    loss_reusable = cache is not None and cache.lap_pks == lap_pks
    for car, track in cohorts:
        if windows_reusable and (car, track) in cache.windows:
            windows_by_corner = cache.windows[(car, track)]
        else:
            windows_by_corner = _cohort_windows_by_corner(db, car, track)
        if not windows_by_corner:
            continue
        if loss_reusable and (car, track) in cache.losses:
            loss = cache.losses[(car, track)]
        else:
            loss = cumulative_loss(
                db, driver=driver, car=car, track=track,
                windows_by_corner=windows_by_corner, config=config, lap_pks=lap_pks,
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


#: 1.4826 makes the median absolute deviation a consistent estimator of
#: the standard deviation for normally distributed data - the constant is
#: what lets a scaled MAD be read in the same "spread" terms as a std
#: without inheriting std's sensitivity to a single extreme sample.
_MAD_CONSISTENCY_CONSTANT = 1.4826


def _scaled_mad(values: Any) -> float:
    """Robust absolute dispersion of one (corner, metric) sample, in the
    metric's native units: scaled median absolute deviation from the
    sample median. No division by the sample's own location - the
    property BUG-044 showed the dm-v2 statistic (CV) lacked.

    Resolution floor: when the MAD is exactly 0 but the sample is not
    constant - possible when a majority of laps share the median value
    exactly (zero-inflated metrics; exactly-repeated synthetic laps) -
    the dispersion is the sample's smallest nonzero absolute deviation,
    scaled by the same constant. Reporting exactly 0 there would claim
    perfect repeatability for a sample that visibly varies; the floor
    is the finest dispersion the sample itself can express."""
    arr = np.asarray(values, dtype=float)
    median = float(np.median(arr))
    deviations = np.abs(arr - median)
    mad = float(np.median(deviations))
    if mad == 0.0:
        nonzero = deviations[deviations > 0]
        if nonzero.size:
            mad = float(np.min(nonzero))
    return _MAD_CONSISTENCY_CONSTANT * mad


def _consistency_component(
    db: Database, driver: str, cohorts: list[tuple[str, str]],
    fundamental_id: str, config: DriverDNAConfig,
    lap_pks: frozenset[int] | None = None,
    cache: "_CohortCache | None" = None,
) -> _Component:
    """dm-v3: each (corner, metric) sample contributes its scaled MAD -
    a robust absolute dispersion in the metric's native units - divided
    by that metric's own reference dispersion
    (`config.model.consistency_metric_reference_dispersion`, the metric's
    typical scaled MAD; module docstring, "Absolute robust dispersion"),
    so a metric's reading never depends on where its values happen to
    sit (BUG-044: CV divided by the sample mean, so a brake point at
    0.57% of lap with sub-point scatter read ~110x typical) and one
    anomalous sample cannot dominate (a median-based estimator moves by
    a bounded amount when a single lap's landmark wraps to the origin).

    Pooling is two-level - mean within each unit, then mean across
    units - not a single flat mean over every (corner, metric) sample,
    retained from dm-v2: a flat mean lets a unit with many contributing
    corners/metrics (e.g. "% lap", with 5 metrics per corner) dominate
    purely by sample count. Giving each unit equal weight keeps one
    corner's real signal inside its own unit's average instead of
    overwhelming every other unit's. A median (within or across units)
    was also tried and rejected under dm-v2: with as few as one corner's
    worth of metrics in a pool, the median just selects whichever metric
    ranks middle, which need not be the one actually varying - mean
    keeps every sample proportionally represented."""
    metric_names = _scoring_metric_names(fundamental_id)
    if not metric_names:
        return _Component(None, 0)
    metric_reference = config.model.consistency_metric_reference_dispersion
    unit_reference = config.model.consistency_unit_reference_dispersion
    by_unit: dict[str, list[float]] = {}
    n_total = 0
    reusable = cache is not None and cache.lap_pks == lap_pks
    for car, track in cohorts:
        if reusable and (car, track) in cache.metrics:
            table = cache.metrics[(car, track)]
        else:
            table = db.self_metric_table(driver=driver, car=car, track=track, lap_pks=lap_pks)
        for metrics in table.values():
            for metric, values in metrics.items():
                if metric not in metric_names or len(values) < 2:
                    continue
                if not np.any(np.asarray(values, dtype=float)):
                    # An all-zero sample records that the measured event
                    # never occurred on any lap (e.g. ABS never active):
                    # the repeatability of an event that never happened
                    # is not measurable, so the sample carries no
                    # dispersion evidence. (dm-v2 skipped the same
                    # samples as a side effect of CV's mean denominator;
                    # dm-v3 keeps the skip on evidence grounds, stated
                    # here rather than inherited silently.)
                    continue
                unit = METRIC_DEFS[metric][0]
                reference = metric_reference.get(
                    metric, unit_reference.get(unit, 0.0))
                if reference <= 0:
                    # No measured anchor for this metric (or its unit):
                    # skip the sample rather than normalize against a
                    # guess (philosophy #3).
                    continue
                normalized = _scaled_mad(values) / reference
                by_unit.setdefault(unit, []).append(normalized)
                n_total += len(values)
    if not by_unit:
        return _Component(None, 0)
    unit_means = [float(np.mean(values)) for values in by_unit.values()]
    pooled = float(np.mean(unit_means))
    ceiling = config.model.consistency_dispersion_ceiling
    normalized = max(0.0, min(1.0, 1.0 - pooled / ceiling)) if ceiling > 0 else 0.0
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


def _effective_weights(
    components: dict[str, _Component], config: DriverDNAConfig
) -> dict[str, float]:
    """The share of the score each component ACTUALLY carried, after
    `_weighted_score`'s redistribution — 0.0 for one with no value.

    Deliberately a second expression of the same rule rather than a
    refactor of `_weighted_score`: that function's exact arithmetic order
    produces every committed number, and reassociating it risks moving a
    last digit for no gain. `test_effective_weights_agree_with_weighted_score`
    pins the two together instead, so they cannot drift.
    """
    weights = {
        "adherence": config.model.weight_adherence,
        "opportunity": config.model.weight_opportunity,
        "consistency": config.model.weight_consistency,
    }
    available = {k for k, c in components.items() if c.value is not None}
    total_w = sum(weights[k] for k in available)
    return {
        k: (weights[k] / total_w if k in available and total_w > 0 else 0.0)
        for k in weights
    }


def _oxford(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _basis_reason(
    fundamental_id: str, components: dict[str, _Component]
) -> str | None:
    """Why this score rests on fewer than three components — None when it
    rests on all three.

    The distinction this function exists to preserve: a component is absent
    either STRUCTURALLY (the fundamental owns no detectors, or no phase
    windows — no quantity of laps will ever populate it) or because its
    evidence has not arrived YET. Wording them the same way would tell a
    driver that more laps will widen a basis that can never widen.
    """
    absent = sorted(k for k, c in components.items() if c.value is None)
    if not absent:
        return None

    fundamental = FUNDAMENTALS[fundamental_id]
    structural: list[str] = []
    pending: list[str] = []
    for name in absent:
        no_detectors = name == "adherence" and not fundamental_detectors(fundamental_id)
        no_phases = name == "opportunity" and not fundamental.phases
        (structural if (no_detectors or no_phases) else pending).append(name)

    present = sorted(k for k, c in components.items() if c.value is not None)
    parts = [f"Scored on {_oxford(present)} alone." if present else "Not scored."]

    if structural:
        why = []
        if "adherence" in structural:
            why.append("no detectors")
        if "opportunity" in structural:
            why.append("no phase windows")
        parts.append(
            f"This fundamental has {_oxford(why)} of its own, so "
            f"{_oxford(structural)} can never be measured for it."
        )
    if pending:
        parts.append(f"No {_oxford(pending)} evidence yet — more laps will add it.")

    # A proxy technique IS observed, just indirectly — only no_signal is
    # genuinely unobservable. Counting proxy as unobservable told the driver
    # "0 of its 1 techniques carries a telemetry signal" about `commitment`,
    # a fundamental that had just scored 56.1 off real opportunity evidence.
    techniques = [t for t in TECHNIQUES.values() if t.fundamental == fundamental_id]
    blind = sorted(
        t.id for t in techniques if t.signal_status is SignalStatus.NO_SIGNAL
    )
    if blind:
        parts.append(
            f"Only {len(techniques) - len(blind)} of its {len(techniques)} techniques "
            f"carries a telemetry signal — {_oxford(blind)} cannot be observed."
        )
    return " ".join(parts)


@dataclass(frozen=True)
class ConfidenceTerm:
    """One of the four evidence-breadth terms behind a belief's confidence.

    Exposed rather than computed inline so `driverdna census` can report
    have-vs-floor per term without forking the formula: the mean of these
    ratios *is* the confidence, pinned by tests/test_census.py. Nothing here
    changes a number — the terms, their order, and their capping are exactly
    what `_confidence` computed before the extraction.
    """

    label: str
    have: int
    floor: int

    @property
    def ratio(self) -> float:
        return min(1.0, self.have / self.floor)


def confidence_terms(
    db: Database, driver: str, cohorts: list[tuple[str, str]],
    evidence_count: int, config: DriverDNAConfig,
) -> list[ConfidenceTerm]:
    """Evidence volume, then the three breadth terms. Order is load-bearing
    only in that it must stay stable for report output; the mean is
    order-independent."""
    m = config.model
    return [
        ConfidenceTerm("evidence laps", evidence_count, m.confidence_evidence_floor),
        ConfidenceTerm(
            "sessions", db.driver_session_count(driver), m.confidence_session_floor
        ),
        ConfidenceTerm(
            "tracks", len({track for _, track in cohorts}), m.confidence_track_floor
        ),
        ConfidenceTerm(
            "cars", len({car for car, _ in cohorts}), m.confidence_car_floor
        ),
    ]


def confidence_from_terms(terms: list[ConfidenceTerm]) -> float:
    return float(np.mean([t.ratio for t in terms]))


def _confidence(
    db: Database, driver: str, cohorts: list[tuple[str, str]],
    evidence_count: int, signal_status: SignalStatus, config: DriverDNAConfig,
) -> float:
    confidence = confidence_from_terms(
        confidence_terms(db, driver, cohorts, evidence_count, config)
    )
    if signal_status is SignalStatus.PROXY:
        confidence = min(confidence, config.model.proxy_confidence_cap)
    return confidence


class _CohortCache:
    """Pre-fetched per-cohort query results, shared across fundamentals.

    `lap_pks` records which evidence scope this instance was built for
    (None = full history; a frozenset = one date-bucket, M6 trend / A36
    score history). The three component functions above only reuse
    `detectors`/`metrics`/`losses` from a cache whose `lap_pks` matches the
    call's own `lap_pks` exactly — a cache built for one bucket must never
    silently answer a different bucket's (or the full-history's) query, or
    every fundamental after the first would read stale evidence and the
    resulting score would be a plausible-looking flat line instead of a
    real per-bucket number (tests/test_scoring.py's cache-equivalence
    test guards exactly this). `windows` has no such scoping — canonical
    windows are the frozen corner map's geometry, not lap data, so they're
    valid to reuse regardless of `lap_pks`.
    """
    __slots__ = ("detectors", "metrics", "losses", "windows", "lap_pks")

    def __init__(self, lap_pks: frozenset[int] | None = None):
        self.detectors: dict[tuple[str, str], dict] = {}
        self.metrics: dict[tuple[str, str], dict] = {}
        self.losses: dict[tuple[str, str], dict] = {}
        self.windows: dict[tuple[str, str], dict] = {}
        self.lap_pks = lap_pks

    @classmethod
    def build(cls, db: Database, driver: str, cohorts: list[tuple[str, str]],
              config: DriverDNAConfig,
              lap_pks: frozenset[int] | None = None) -> "_CohortCache":
        cache = cls(lap_pks)
        for car, track in cohorts:
            cache.detectors[(car, track)] = db.self_detector_table(
                driver=driver, car=car, track=track, lap_pks=lap_pks)
            cache.metrics[(car, track)] = db.self_metric_table(
                driver=driver, car=car, track=track, lap_pks=lap_pks)
            wbc = _cohort_windows_by_corner(db, car, track)
            cache.windows[(car, track)] = wbc
            if wbc:
                cache.losses[(car, track)] = cumulative_loss(
                    db, driver=driver, car=car, track=track,
                    windows_by_corner=wbc, config=config, lap_pks=lap_pks,
                )
        return cache


def _score_components(
    db: Database, driver: str, fundamental_id: str,
    cohorts: list[tuple[str, str]], config: DriverDNAConfig,
    lap_pks: frozenset[int] | None = None,
    cache: _CohortCache | None = None,
) -> dict[str, _Component]:
    """The three score components for one fundamental. `lap_pks` (M6 trend,
    A36 score history) restricts the evidence to a date-bucket's laps; None
    = full history. `cache`, if given, must have been built for this same
    `lap_pks` scope (or be windows-only-reusable — see `_CohortCache`) —
    each component function checks `cache.lap_pks == lap_pks` itself rather
    than trusting the caller, so passing a mismatched cache degrades to an
    uncached (correct, just slower) query instead of a wrong answer."""
    fundamental = FUNDAMENTALS[fundamental_id]
    detector_names = fundamental_detectors(fundamental_id)
    return {
        "adherence": _adherence_component(
            db, driver, cohorts, detector_names, lap_pks, cache=cache,
        ),
        "opportunity": _opportunity_component(
            db, driver, cohorts, fundamental.phases, config, lap_pks, cache=cache,
        ),
        "consistency": _consistency_component(
            db, driver, cohorts, fundamental_id, config, lap_pks, cache=cache,
        ),
    }


def _bucket_score(
    db: Database, driver: str, fundamental_id: str,
    cohorts: list[tuple[str, str]], config: DriverDNAConfig, lap_pks: frozenset[int],
    cache: _CohortCache | None = None,
) -> float | None:
    """This fundamental's score computed over one date-bucket's laps only —
    same machinery as the full-history score, just lap-pk-filtered. `cache`
    is optional (M6's `_trend`, computing exactly two buckets, doesn't
    bother); A36's score history builds one `_CohortCache` per bucket and
    reuses it across all 7 fundamentals' calls for that bucket, which is
    what turns N buckets x 7 fundamentals from N*7 uncached per-cohort query
    sets into just N."""
    return _weighted_score(
        _score_components(db, driver, fundamental_id, cohorts, config, lap_pks, cache=cache),
        config,
    )


def _trend(
    db: Database, driver: str, fundamental_id: str,
    cohorts: list[tuple[str, str]], config: DriverDNAConfig,
    earlier_cache: _CohortCache | None = None,
    recent_cache: _CohortCache | None = None,
) -> str:
    """Direction of this fundamental's score between an earlier and a recent
    bucket of the driver's dated laps (SPEC.md M6; ARCHITECTURE_VISION.md
    Scoring Contract condition 5).

    Deterministic: dated self-laps are ordered by (lap_date, lap_pk) and
    split by count at the midpoint into earlier/recent halves; the same
    scoring function runs on each. `improving`/`declining` require the recent
    score to move more than `trend_delta_points`; otherwise `stable`.
    `unavailable` when there are too few dated laps, or a bucket has no
    scorable evidence for this fundamental — an honest gap, never a guessed
    direction.

    Two known v1 limitations, flagged not silently accepted (both in the
    era-windowing territory A17 recorded as deferred, PROJECT-BRIEF.md):
      1. The opportunity component's robust baseline is recomputed within
         each bucket, so it is era-relative — a driver who got uniformly
         faster is measured against their own faster recent best, which can
         mute an opportunity trend. Adherence and consistency, being
         baseline-free, carry the signal cleanly.
      2. Buckets pool across cohorts (the Driver Model's whole point is a
         belief about the driver, not the lap). When a driver's dated laps
         are spread thinly across many cars/tracks, the earlier and recent
         buckets can hold *different* cohorts, so a direction partly reflects
         which cars/tracks fell in each half, not skill-over-time alone. The
         signal sharpens as multiple dated laps accumulate per cohort.
    """
    dated = db.dated_self_lap_pks(driver)
    k = config.model.trend_min_laps_per_bucket
    if len(dated) < 2 * k:
        return "unavailable"
    half = len(dated) // 2
    earlier = frozenset(dated[:half])
    recent = frozenset(dated[half:])
    earlier_score = _bucket_score(db, driver, fundamental_id, cohorts, config, earlier, cache=earlier_cache)
    recent_score = _bucket_score(db, driver, fundamental_id, cohorts, config, recent, cache=recent_cache)
    if earlier_score is None or recent_score is None:
        return "unavailable"
    delta = recent_score - earlier_score
    threshold = config.model.trend_delta_points
    if delta > threshold:
        return "improving"
    if delta < -threshold:
        return "declining"
    return "stable"


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
    cohorts: list[tuple[str, str]] | None = None,
    cache: _CohortCache | None = None,
    earlier_cache: _CohortCache | None = None,
    recent_cache: _CohortCache | None = None,
) -> Belief:
    """Deterministic belief for one (driver, fundamental) — pure function of
    the evidence currently persisted plus SCORING_MODEL_VERSION."""
    fundamental = FUNDAMENTALS[fundamental_id]
    signal_status = fundamental.signal_status

    if signal_status is SignalStatus.NO_SIGNAL:
        return _no_signal_belief(fundamental_id)

    if cohorts is None:
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

    components = _score_components(db, driver, fundamental_id, cohorts, config, cache=cache)
    score = _weighted_score(components, config)
    if score is None:
        return _insufficient_belief(
            fundamental_id, signal_status, evidence_count,
            "insufficient evidence: no scorable component had data",
        )

    confidence = _confidence(db, driver, cohorts, evidence_count, signal_status, config)
    rounded_score = round(score, 2)
    trend = _trend(db, driver, fundamental_id, cohorts, config, earlier_cache=earlier_cache, recent_cache=recent_cache)
    trend_reason = None
    if trend in ("improving", "declining") and rounded_score in (0.0, 100.0):
        # BUG-043: a headline score pinned at a scale bound is a clamp,
        # not a measurement with room to move - the bucket delta that
        # produced a direction straddles the bound (one bucket clamped,
        # the other not) and asserts a trajectory the headline number
        # cannot express. Suppress the direction and say so, in the
        # payload, rather than emitting the pair (0.0, "improving").
        trend_reason = (
            f"trend suppressed: the headline score is pinned at the scale "
            f"bound ({rounded_score}), so no direction is asserted"
        )
        trend = "unavailable"
    return Belief(
        fundamental=fundamental_id, signal_status=signal_status,
        score=rounded_score, confidence=round(confidence, 4),
        evidence_count=evidence_count,
        trend=trend,
        insufficient_reason=None,
        scoring_model_version=SCORING_MODEL_VERSION, taxonomy_version=TAXONOMY_VERSION,
        components=components,
        basis_reason=_basis_reason(fundamental_id, components),
        trend_reason=trend_reason,
    )


def compute_all_beliefs(
    db: Database, *, driver: str, config: DriverDNAConfig,
) -> dict[str, Belief]:
    cohorts = _driver_cohorts(db, driver)
    cache = _CohortCache.build(db, driver, cohorts, config)
    
    dated = db.dated_self_lap_pks(driver)
    k = config.model.trend_min_laps_per_bucket
    earlier_cache = recent_cache = None
    if len(dated) >= 2 * k:
        half = len(dated) // 2
        earlier_cache = _CohortCache.build(
            db, driver, cohorts, config, lap_pks=frozenset(dated[:half]))
        recent_cache = _CohortCache.build(
            db, driver, cohorts, config, lap_pks=frozenset(dated[half:]))

    return {
        fid: compute_belief(
            db, driver=driver, fundamental_id=fid, config=config,
            cohorts=cohorts, cache=cache,
            earlier_cache=earlier_cache, recent_cache=recent_cache,
        )
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
