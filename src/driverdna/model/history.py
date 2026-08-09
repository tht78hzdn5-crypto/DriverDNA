"""A36: score history (`dm-hist-v1`) — each Driver Model fundamental's own
score across N contiguous, date-ordered buckets of a driver's dated laps.

This is the UI's score-over-time chart's engine source (SPEC.md A36,
docs/UI-V3-PLAN.md Track A4). It reuses `model/scoring.py`'s
`_bucket_score`/`_CohortCache` — the exact machinery M6's `_trend` already
uses for its own two buckets — generalized from 2 buckets to
`config.model.history_buckets`. Deliberately produces **no new kind of
number**: no formula or weight changes, so `SCORING_MODEL_VERSION` is
untouched; only this series' own shape gets a version (`SERIES_VERSION`).

Binding (A36): a bucket with no scorable evidence for a fundamental is a
null with a stated reason — never interpolated, never averaged into a
smooth line that didn't happen. A no_signal fundamental (the engine never
scores it, M6 rule) has no series entry at all, same as it has no score
anywhere else in the payload.

Performance note: one `_CohortCache` is built per bucket and shared across
every fundamental's `_bucket_score` call for that bucket — turning what
would otherwise be `n_buckets x len(FUNDAMENTALS)` uncached per-cohort query
sets into just `n_buckets` (see `_CohortCache`'s own docstring for the
scoping rule that makes this safe rather than a plausible-looking flat line).
"""

from __future__ import annotations

from typing import Any

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.scoring import (
    SCORING_MODEL_VERSION,
    _CohortCache,
    _bucket_score,
    _driver_cohorts,
)
from driverdna.model.taxonomy import FUNDAMENTALS, SignalStatus

SERIES_VERSION = "dm-hist-v1"

# Verbatim from `_trend`'s own docstring (model/scoring.py) — a chart makes
# these limitations more visible, not less true, so they travel with every
# score-history payload rather than living only in one function's comment.
CAVEATS: tuple[str, ...] = (
    "The opportunity component's robust baseline is recomputed within each "
    "bucket, so it is era-relative — a driver who got uniformly faster is "
    "measured against their own faster recent best, which can mute an "
    "opportunity-driven shift. Adherence and consistency, being "
    "baseline-free, carry the signal cleanly.",
    "Buckets pool across cohorts (the Driver Model's whole point is a "
    "belief about the driver, not the lap). When a driver's dated laps are "
    "spread thinly across many cars/tracks, different buckets can hold "
    "different cohorts, so a shift partly reflects which cars/tracks fell "
    "in each bucket, not skill-over-time alone. The signal sharpens as "
    "multiple dated laps accumulate per cohort.",
)


def _equal_count_chunks(items: list[Any], n: int) -> list[list[Any]]:
    """Split `items` into `n` contiguous chunks, as equal in size as
    possible — the LAST `len(items) % n` chunks get the one extra item
    each, not the first. This isn't an arbitrary choice: `_trend`'s own
    2-way split (`half = len(dated) // 2; earlier = dated[:half]; recent =
    dated[half:]`) always gives its *recent* bucket the extra lap on an odd
    count. Putting the remainder at the tail here, not the head, is what
    makes `score_history(..., n_buckets=2)` reproduce `_trend`'s own two
    scores exactly on an odd-length dated history (tested) — the owner's
    real dated history is 25 laps, an odd count."""
    length = len(items)
    base, extra = divmod(length, n)
    chunks = []
    start = 0
    for i in range(n):
        size = base + (1 if i >= n - extra else 0)
        chunks.append(items[start : start + size])
        start += size
    return chunks


def score_history(db: Database, *, driver: str, config: DriverDNAConfig) -> dict[str, Any]:
    """Each measured/proxy fundamental's score across N date-ordered
    buckets of `driver`'s dated laps. `x_axis.kind` is `"unavailable"`
    (with empty `series`) when there are too few dated laps in total to
    honestly fill `config.model.history_buckets` buckets at
    `config.model.trend_min_laps_per_bucket` laps each — the same
    per-bucket floor M6 trend already uses, generalized rather than
    duplicated with a new threshold."""
    dated = db.dated_self_laps(driver)
    n_buckets = max(1, config.model.history_buckets)
    floor = config.model.trend_min_laps_per_bucket

    if len(dated) < n_buckets * floor:
        return {
            "series_version": SERIES_VERSION,
            "scoring_model_version": SCORING_MODEL_VERSION,
            "x_axis": {"kind": "unavailable", "labels": [], "bucket_lap_counts": []},
            "series": {},
            "caveats": list(CAVEATS),
        }

    lap_pks = [pk for pk, _ in dated]
    dates = [d for _, d in dated]
    bucket_pk_lists = _equal_count_chunks(lap_pks, n_buckets)
    bucket_date_lists = _equal_count_chunks(dates, n_buckets)

    labels = [
        bd[0] if bd[0] == bd[-1] else f"{bd[0]} .. {bd[-1]}" for bd in bucket_date_lists
    ]
    bucket_lap_counts = [len(bp) for bp in bucket_pk_lists]

    cohorts = _driver_cohorts(db, driver)
    bucket_pk_sets = [frozenset(bp) for bp in bucket_pk_lists]
    caches = [
        _CohortCache.build(db, driver, cohorts, config, lap_pks=pks)
        for pks in bucket_pk_sets
    ]

    series: dict[str, Any] = {}
    for fundamental_id, fundamental in sorted(FUNDAMENTALS.items()):
        if fundamental.signal_status is SignalStatus.NO_SIGNAL:
            continue  # never scored anywhere in the payload; no chart line either
        points = []
        for i, (pks, cache) in enumerate(zip(bucket_pk_sets, caches, strict=True)):
            score = _bucket_score(db, driver, fundamental_id, cohorts, config, pks, cache=cache)
            points.append({
                "x": i,
                "score": None if score is None else round(score, 2),
                "n": len(pks),
                "reason": None if score is not None else "no scorable evidence in this bucket",
            })
        series[fundamental_id] = {
            "signal_status": fundamental.signal_status.value,
            "points": points,
        }

    return {
        "series_version": SERIES_VERSION,
        "scoring_model_version": SCORING_MODEL_VERSION,
        "x_axis": {
            "kind": "date_bucket",
            "labels": labels,
            "bucket_lap_counts": bucket_lap_counts,
        },
        "series": series,
        "caveats": list(CAVEATS),
    }
