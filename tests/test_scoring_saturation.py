"""Fix-verification tests for the dm-v2 consistency saturation defects
(BUG-042/BUG-043/BUG-044), landed as dm-v3 (SPEC.md A56).

History: this module began as two ``xfail(strict=True)`` pins asserting
the behaviour the constitution requires while dm-v2 clamped the owner's
real 282-lap corpus to exactly 0.0. The dm-v3 fix (absolute robust
dispersion — scaled MAD against per-metric reference anchors — in place
of coefficient of variation) retires the pins: the original assertions
now run as genuine passes, unchanged. The BUG-044 statistic tests and
the BUG-043 trend-gate test were added with the fix.

Evidence base (measured 2026-10-08 from the owner's live corpus; see
docs/BUG-LOG.md BUG-042):

- dm-v2 consistency component: pooled normalized CV = 2.3898 vs
  `consistency_cv_ceiling` = 2.0, so `1 - pooled/ceiling` clamped to
  exactly 0.0.
- vehicle_management under dm-v2: pooled = 2.0252 over its single metric
  (`abs_active_ratio`) — barely past the same ceiling, same clamp.
"""

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


# --- BUG-044: CV was the wrong statistic for '% lap' position metrics ---


def test_brake_point_near_origin_is_not_a_dispersion_explosion():
    # Brands Hatch C10's real brake points (BUG-044): absolute scatter
    # under half a percentage point (std 0.44), but the landmark sits at
    # 0.57% of lap, so dm-v2's CV read 0.77 raw / ~110x normalized and
    # the sample alone could zero a unit mean. Absolute dispersion reads
    # the scatter itself: scaled MAD 0.089 points against the metric's
    # 0.414-point anchor -> normalized ~0.21, a *repeatable* landmark.
    db = _StubMetricDB({
        ("CarX", "TrackX"): {
            "C10": {"brake_point_dist_pct": [0.24, 0.24, 0.30, 0.76, 1.27]},
        },
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "braking", CONFIG,
    )
    assert component.value is not None and component.value > 0.85


def test_wrap_around_sample_cannot_manufacture_a_corner_verdict():
    # Silverstone C18's real apex positions (BUG-044): three laps agree
    # within ~5 points and one lap's landmark sits at the lap origin
    # (0.013 — a wrap-around/segmentation edge case, not driving).
    # dm-v2's CV turned that one sample into a normalized ~95, enough to
    # crush a unit mean by itself. Under scaled MAD the sample reads
    # ~8.6x its metric's typical dispersion — this corner's apex
    # placement genuinely is loose — but bounded: pooled with nine
    # typical corners it cannot zero the component.
    corners = {
        f"C{i:02d}": {"apex_dist_pct": [50.0, 50.3, 49.7, 50.1]}
        for i in range(1, 10)
    }
    corners["C18"] = {"apex_dist_pct": [99.0, 98.4, 0.013, 93.9]}
    db = _StubMetricDB({("CarX", "TrackX"): corners})
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "rotation", CONFIG,
    )
    assert component.value is not None and component.value > 0.4


def test_bimodal_brake_points_read_as_poor_not_absurd():
    # Brands Hatch C01's real brake points (BUG-044): two distinct
    # braking zones, [0.81, 9.27, 1.13, 1.52, 10.92]. CV reads ~1.0
    # regardless of cluster tightness (~143x normalized under dm-v2).
    # Scaled MAD (1.05 points, ~2.5x the metric anchor) reads what is
    # true: poor repeatability, honestly measured — neither the worst
    # the scale can express nor a pass.
    db = _StubMetricDB({
        ("CarX", "TrackX"): {
            "C01": {"brake_point_dist_pct": [0.81, 9.27, 1.13, 1.52, 10.92]},
        },
    })
    component = _consistency_component(
        db, "owner", [("CarX", "TrackX")], "braking", CONFIG,
    )
    assert component.value is not None and 0.05 < component.value < 0.35


# --- BUG-043: trend asserted a direction for a saturated 0.0 belief ------

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


def test_vehicle_management_trend_never_improves_a_zero_score():
    belief = compute_belief(
        _TrendStubDB(), driver="owner", fundamental_id="vehicle_management",
        config=CONFIG, cohorts=[("CarX", "TrackX")],
    )
    assert not (belief.score == 0.0 and belief.trend == "improving")


# The gate case: engineered so the dm-v3 statistic itself still clamps.
# Earlier half alternates 0/1 (scaled MAD 0.741, ~3.9x the abs_active_ratio
# anchor -> bucket score 0.0); recent half alternates 0.2/0.8 (scaled MAD
# 0.445, ~2.4x -> bucket score ~21); the union's scaled MAD is 0.593
# (~3.2x), past consistency_dispersion_ceiling, so the headline score is
# exactly 0.0 while the raw bucket delta (+21) clears trend_delta_points.
# Without the BUG-043 gate this pair ships as (0.0, "improving").
_GATE_EARLIER = frozenset({1, 2, 3, 4, 5, 6})
_GATE_RECENT = frozenset({7, 8, 9, 10, 11, 12})
_GATE_EARLIER_VALS = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
_GATE_RECENT_VALS = [0.2, 0.8, 0.2, 0.8, 0.2, 0.8]


class _GateStubDB(_TrendStubDB):
    def self_metric_table(self, *, driver, car, track, lap_pks=None):
        if lap_pks is None:
            vals = _GATE_EARLIER_VALS + _GATE_RECENT_VALS
        elif lap_pks == _GATE_EARLIER:
            vals = _GATE_EARLIER_VALS
        else:
            vals = _GATE_RECENT_VALS
        return {"C01": {"abs_active_ratio": vals}}

    def dated_self_lap_pks(self, driver):
        return list(range(1, 13))


def test_trend_is_suppressed_with_reason_when_headline_score_is_clamped():
    belief = compute_belief(
        _GateStubDB(), driver="owner", fundamental_id="vehicle_management",
        config=CONFIG, cohorts=[("CarX", "TrackX")],
    )
    assert belief.score == 0.0
    assert belief.trend == "unavailable"
    assert belief.trend_reason is not None and "0.0" in belief.trend_reason
