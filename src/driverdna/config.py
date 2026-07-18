"""Typed configuration with a documented default for every threshold.

Growing incrementally: each milestone adds the section its thresholds live
in. Loading merges a user TOML file over the typed defaults; unknown keys
fail loudly (a misspelled threshold must not silently fall back to default).

The full ConfigStore write path — versioned, reversible parameter changes
recorded in the DB, shared by the CLI and confirmed chat proposals — lands
with persistence in M2. Nothing outside this module may define a tunable
threshold; docs/SPEC.md, "CLI and configuration".
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SmoothingConfig(_Section):
    """Light smoothing applied before any derivative-based detection.

    Savitzky-Golay: preserves peak shapes and timing far better than a plain
    moving average at these window sizes.
    """

    window_samples: int = Field(
        default=7,
        description="Savitzky-Golay window in samples (~0.12 s at 60 Hz); odd.",
    )
    polyorder: int = Field(
        default=2, description="Savitzky-Golay polynomial order."
    )


class SegmentationConfig(_Section):
    """Corner detection and phase-landmark thresholds (M1)."""

    brake_on: float = Field(
        default=0.05,
        description="Pedal fraction above which the driver counts as braking.",
    )
    brake_off: float = Field(
        default=0.03,
        description="Pedal fraction below which the brake counts as released "
        "(hysteresis below brake_on).",
    )
    steering_active_deg: float = Field(
        default=10.0,
        description="Absolute steering-wheel angle (degrees) above which "
        "steering counts as corner activity; also the turn-in and "
        "steering-release threshold.",
    )
    merge_gap_s: float = Field(
        default=0.6,
        description="Activity gaps shorter than this merge into one corner "
        "(joins chicane elements and S-curve sign changes).",
    )
    min_corner_duration_s: float = Field(
        default=0.7,
        description="Activity spans shorter than this are discarded as noise.",
    )
    debounce_s: float = Field(
        default=0.10,
        description="A threshold crossing must persist this long to count "
        "(suppresses single-sample noise).",
    )
    throttle_pickup_level: float = Field(
        default=0.10,
        description="Throttle fraction whose upward crossing after the "
        "in-corner minimum marks throttle pickup.",
    )
    full_throttle_level: float = Field(
        default=0.95,
        description="Throttle fraction counted as full throttle.",
    )
    full_throttle_sustain_s: float = Field(
        default=0.3,
        description="Full throttle must be held this long to mark the "
        "full-throttle landmark.",
    )
    apex_min_separation_s: float = Field(
        default=1.0,
        description="Minimum spacing between distinct speed minima for a "
        "multi-apex complex.",
    )
    apex_prominence_ms: float = Field(
        default=1.0,
        description="Minimum speed-dip prominence (m/s) for an additional "
        "apex to count in a multi-apex complex.",
    )
    pickup_search_margin_s: float = Field(
        default=2.0,
        description="Throttle-pickup search may extend this far past the "
        "activity span (never into the next corner) — pickup belongs to "
        "this corner, not to the next corner's entry lift.",
    )
    pickup_lift_candidacy_margin_s: float = Field(
        default=0.5,
        description="A throttle lift qualifies as the corner's final lift "
        "(whose end is the pickup) only if it starts no later than this "
        "after the last apex; later dips are exit-phase stabs for the "
        "detectors, not a new pickup.",
    )


class IdentityConfig(_Section):
    """Corner-identity matching against the frozen per-cohort corner map (M1)."""

    match_radius_m: float = Field(
        default=75.0,
        description="An observed corner matches a frozen identity when any "
        "of its apexes lies within this many meters of the identity's GPS "
        "center (GPS is the primary key).",
    )
    dist_pct_fallback_radius: float = Field(
        default=0.01,
        description="When GPS is degraded, fall back to matching on lap "
        "distance: apex within this fraction of a lap (circular) of the "
        "identity's center.",
    )
    min_laps_for_admission: int = Field(
        default=3,
        description="A consistently unmatched corner must appear on at least "
        "this many laps before it is admitted to the frozen map (admission "
        "is explicit and surfaced, never silent).",
    )


class ClassificationConfig(_Section):
    """Speed-band corner classes per corner identity (M1)."""

    slow_max_kmh: float = Field(
        default=90.0,
        description="Corners with median minimum speed below this are slow.",
    )
    fast_min_kmh: float = Field(
        default=150.0,
        description="Corners with median minimum speed at or above this are "
        "fast; between the bands is medium.",
    )
    hysteresis_margin_kmh: float = Field(
        default=5.0,
        description="An already-classified corner changes class only when "
        "its median moves this far past the band edge; every change is a "
        "reported event, never silent.",
    )


class DriverDNAConfig(_Section):
    """Root configuration. One TOML file; sections per subsystem."""

    smoothing: SmoothingConfig = Field(default_factory=SmoothingConfig)
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)


def load_config(path: Path | None = None) -> DriverDNAConfig:
    """Defaults, with an optional TOML file merged over them.

    Unknown keys anywhere in the file raise — a misspelled threshold must
    fail loudly, never silently fall back to a default.
    """
    if path is None:
        return DriverDNAConfig()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return DriverDNAConfig.model_validate(data)
