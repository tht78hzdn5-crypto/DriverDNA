"""Known-defect pins for the dm-v2 consistency saturation (BUG-042/BUG-043).

These tests do NOT assert the current behaviour is correct. Each is marked
``xfail(strict=True)`` and asserts the behaviour the constitution requires;
while the defect stands they xfail, and the day a fix lands (a SPEC
amendment + dm-v3, per AGENTS.md's engine-numbers rule) the strict xpass
turns the suite red and forces the fix's author to retire the pin and
close the BUG-LOG entry. That tripwire is the point: on 2026-10-08 the
owner's real 282-lap corpus scored `consistency` 0.0 at 100% confidence
and `vehicle_management` 0.0 with trend "improving", and no existing test
noticed — the suite was green throughout.

Evidence base (measured 2026-10-08 from the owner's live corpus, engine
run against a copy of the live DB; see docs/BUG-LOG.md BUG-042):

- consistency component: pooled normalized CV = 2.3898 vs
  `consistency_cv_ceiling` = 2.0, so `1 - pooled/ceiling` clamps to
  exactly 0.0. Unit means: '% lap' 6.77, 'km/h' 3.14, 'm/s^2' 2.68,
  'rad/s' 2.36, 's' 1.72, 'count' 1.51, 'fraction/s' 1.19, 'fraction'
  1.15, 'deg/s^2' 0.99 — saturation is broad-based, not one outlier.
- vehicle_management: pooled = 2.0252 over its single metric
  (`abs_active_ratio`) — barely past the same ceiling, same clamp.
"""

import pytest

from driverdna.config import DriverDNAConfig
from driverdna.model.scoring import _consistency_component, compute_belief

CONFIG = DriverDNAConfig()


class _StubMetricDB:
    """The stub pattern from test_scoring.py: `_consistency_component`
    only calls `self_metric_table`."""

    def __init__(self, tables):
        self._tables = tables

    def self_metric_table(self, *, driver, car, track, lap_pks=None):
        return self._tables.get((car, track), {})


@pytest.mark.xfail(
    strict=True,
    reason="BUG-042: consistency component clamps to exactly 0.0 whenever "
    "the pooled normalized CV reaches consistency_cv_ceiling (2.0); at "
    "the live corpus's measured profile (pooled 2.39) the belief is an "
    "unqualified 0.0 at full confidence. Fix requires a SPEC amendment "
    "and a dm-v3 bump (AGENTS.md), deliberately not done here.",
)
def test_consistency_component_does_not_saturate_at_live_corpus_profile():
    # One metric per unit, five units, raw spreads chosen so each unit's
    # normalized CV lands near the live corpus's measured unit means
    # ('% lap' ~6.8, 'km/h' ~3.1, 's' ~1.8, 'fraction' ~1.1, 'count'
    # ~1.4; pooled ~2.9 — the same side of the ceiling as the measured
    # 2.39, from realistic per-corner variation, not a pathological
    # input). A driver this variable is badly inconsistent; they are not
    # indistinguishable from the worst driver the scale can express,
    # which is what an exact 0.0 claims.
    db = _StubMetricDB({
        ("CarX", "TrackX"): {
            "C01": {
                "turn_in_dist_pct": [47.0, 48.5, 50.0, 51.5, 53.0],
                "min_speed_kmh": [60.0, 70.0, 80.0, 90.0, 100.0],
                "coast_s": [0.0, 0.3, 0.7, 1.3, 2.7],
                "brake_peak": [0.15, 0.35, 0.6, 0.85, 1.0],
                "steering_corrections": [0.0, 0.0, 0.0, 2.0, 3.0],
            },
        },
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "consistency", CONFIG,
    )
    assert component.value is not None and component.value > 0.0


# --- BUG-043: trend can assert a direction for a saturated 0.0 belief -----

_EARLIER = frozenset({1, 2, 3, 4})
_RECENT = frozenset({5, 6, 7, 8})
# Zero-heavy earlier half: raw CV 2.0 on abs_active_ratio (normalized
# 3.77) — that bucket saturates to a 0.0 bucket score. Tight recent half:
# raw CV ~0.12 (normalized 0.23) — bucket score ~88. The union's raw CV
# (~1.28, normalized 2.42) still saturates, so the full-history score is
# 0.0 while the bucket delta (+88) clears trend_delta_points (5) and the
# trend reads "improving". These are the live corpus's actual proportions
# (earlier pooled 2.56, recent pooled 1.84, full pooled 2.03).
_EARLIER_VALS = [0.0, 0.0, 0.0, 0.40]
_RECENT_VALS = [0.10, 0.12, 0.09, 0.11]


class _TrendStubDB:
    """Minimal Database surface `compute_belief` touches, with the metric
    table scoped by lap_pks the way the real one is: a trend bucket sees
    only its own laps' values."""

    def fundamental_evidence_lap_count(self, *, driver, metric_names, detector_names):
        return 282

    def self_detector_table(self, *, driver, car, track, lap_pks=None):
        return {}

    def self_metric_table(self, *, driver, car, track, lap_pks=None):
        if lap_pks is None:
            vals = _EARLIER_VALS + _RECENT_VALS
        elif lap_pks == _EARLIER:
            vals = _EARLIER_VALS
        else:
            vals = _RECENT_VALS
        return {"C01": {"abs_active_ratio": vals}}

    def load_corner_map(self, *, car, track):
        return None

    def driver_session_count(self, driver):
        return 53

    def dated_self_lap_pks(self, driver):
        return list(range(1, 9))


@pytest.mark.xfail(
    strict=True,
    reason="BUG-043: trend is scored on independent date-halves, so a "
    "belief saturated at exactly 0.0 can still report trend 'improving' "
    "(live corpus, 2026-10-08: vehicle_management 0.0 / improving). "
    "The pair asserts a direction the headline number cannot support.",
)
def test_vehicle_management_trend_never_improves_a_zero_score():
    belief = compute_belief(
        _TrendStubDB(), driver="owner", fundamental_id="vehicle_management",
        config=CONFIG, cohorts=[("CarX", "TrackX")],
    )
    assert not (belief.score == 0.0 and belief.trend == "improving")
