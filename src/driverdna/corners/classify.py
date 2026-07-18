"""CornerClassifier: speed-band class per corner identity, with hysteresis (M1).

Class comes from the median minimum corner speed across laps (never a single
lap). Once assigned, a class changes only when the median moves
hysteresis_margin_kmh past the band edge, and the change is returned as an
event for the caller to surface — a corner near a boundary must not
flip-flop as laps accumulate. Raw min speeds are kept by the caller so bands
can always be re-derived. Thresholds: config.ClassificationConfig.
"""

from __future__ import annotations

from enum import StrEnum

from driverdna.config import ClassificationConfig

MS_TO_KMH = 3.6


class CornerClass(StrEnum):
    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"


def classify_speed(median_kmh: float, cfg: ClassificationConfig) -> CornerClass:
    """Raw band assignment, no history."""
    if median_kmh < cfg.slow_max_kmh:
        return CornerClass.SLOW
    if median_kmh < cfg.fast_min_kmh:
        return CornerClass.MEDIUM
    return CornerClass.FAST


def classify_with_hysteresis(
    median_kmh: float,
    previous: CornerClass | None,
    cfg: ClassificationConfig,
) -> tuple[CornerClass, bool]:
    """(class, changed): sticky around band edges once a class exists.

    ``changed`` is True only when an existing class actually flips — the
    caller reports it as an event, never silently.
    """
    raw = classify_speed(median_kmh, cfg)
    if previous is None or raw == previous:
        return raw, False

    # Sticky up to and including edge±margin; a flip requires moving beyond it.
    m = cfg.hysteresis_margin_kmh
    still_previous = {
        CornerClass.SLOW: median_kmh <= cfg.slow_max_kmh + m,
        CornerClass.MEDIUM: cfg.slow_max_kmh - m <= median_kmh <= cfg.fast_min_kmh + m,
        CornerClass.FAST: median_kmh >= cfg.fast_min_kmh - m,
    }[previous]
    if still_previous:
        return previous, False
    return raw, True
