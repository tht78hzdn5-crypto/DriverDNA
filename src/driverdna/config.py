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


class MetricsConfig(_Section):
    """Deterministic technique-metric parameters (M2)."""

    correction_floor_dps: float = Field(
        default=15.0,
        description="Steering-rate magnitude (deg/s) below which a derivative "
        "sign reversal is jitter, not a correction.",
    )
    modulation_min_drop: float = Field(
        default=0.05,
        description="A throttle drop between pickup and full throttle must "
        "exceed this fraction to count as a lift/stab.",
    )
    overlap_floor: float = Field(
        default=0.05,
        description="Throttle and brake must each exceed this fraction for a "
        "sample to count as throttle-brake overlap.",
    )
    release_from_peak_fraction: float = Field(
        default=0.95,
        description="Brake-release duration is measured from the last sample "
        "at or above this fraction of peak brake (so a held plateau doesn't "
        "count as 'releasing') to fully released.",
    )


class DetectorsConfig(_Section):
    """Principle-detector thresholds (M2); every finding is vs-principle."""

    release_gap_max_s: float = Field(
        default=0.3,
        description="Brake release completed more than this long before "
        "turn-in flags the no-taper detector.",
    )
    overlap_max_s: float = Field(
        default=0.75,
        description="Total throttle-brake overlap in a corner beyond this "
        "flags the overlap detector. Heel-toe downshift blips are legitimate "
        "overlap (~0.1-0.2 s per downshift; observed 0.2-0.9 s per corner in "
        "the manual-gearbox fixture), and v1 cannot separate blips from "
        "dragging without RPM correlation — the default accommodates typical "
        "heel-toe; retune per car.",
    )
    max_corrections: int = Field(
        default=1,
        description="Steering corrections entry->apex beyond this flag the "
        "one-input detector.",
    )
    max_modulations: int = Field(
        default=0,
        description="Throttle lifts/stabs between pickup and full throttle "
        "beyond this flag the monotonic-throttle detector.",
    )
    coast_max_s: float = Field(
        default=0.5,
        description="Coasting (no brake, no throttle) between brake release "
        "and throttle pickup beyond this flags the coast detector.",
    )
    min_trigger_rate: float = Field(
        default=0.5,
        description="A principle detector becomes a finding only when it "
        "triggers on at least this share of a corner's laps — one bad lap is "
        "an event, not a pattern.",
    )


class AttributionConfig(_Section):
    """Time-at-distance attribution (M3)."""

    outlier_mad_k: float = Field(
        default=3.5,
        description="Phase times beyond median ± k·MAD are screened as "
        "outliers before baseline selection (no lap-validity channel exists; "
        "one invalid lap must never become the yardstick). Screened values "
        "are counted and caveated, never silently dropped from history.",
    )
    baseline_top_k: int = Field(
        default=3,
        description="The robust baseline is the median of the k fastest "
        "screened executions of a corner phase; the single fastest is still "
        "shown, labeled. ",
    )
    min_effect_s: float = Field(
        default=0.05,
        description="vs-self opportunities smaller than this are noise, not "
        "findings.",
    )


class GatesConfig(_Section):
    """Confidence gates (M3): a finding below its gate is suppressed, and
    the suppression is stated — never silent."""

    min_phase_samples: int = Field(
        default=10,
        description="Minimum corner-phase samples before a finding is shown.",
    )
    min_sessions: int = Field(
        default=2,
        description="Minimum distinct sessions before a finding is shown.",
    )
    min_tracks_for_rollup: int = Field(
        default=2,
        description="Cross-track rollups (within car, within class) require "
        "at least this many tracks.",
    )


class CoachConfig(_Section):
    """AI coaching layer (M4 coach, M5 chat). On-demand only; env-only key."""

    model: str = Field(
        default="claude-sonnet-5",
        description="Claude model used for coach and chat runs.",
    )
    max_tokens: int = Field(
        default=4000, description="Response token budget per provider call."
    )
    include_raw_traces: bool = Field(
        default=False,
        description="Include raw channel arrays in AI payloads. Default off; "
        "the deterministic findings are the ground truth the AI works from.",
    )


class RetentionConfig(_Section):
    """Raw-sample retention (M2). Compact summaries are permanent."""

    raw_laps_per_cohort: int = Field(
        default=100,
        description="Newest N raw lap blobs kept per driver/car/track cohort; "
        "eviction deletes blobs only and can never touch summaries, trends, "
        "or findings.",
    )


class DriverDNAConfig(_Section):
    """Root configuration. One TOML file; sections per subsystem."""

    smoothing: SmoothingConfig = Field(default_factory=SmoothingConfig)
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    detectors: DetectorsConfig = Field(default_factory=DetectorsConfig)
    attribution: AttributionConfig = Field(default_factory=AttributionConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    coach: CoachConfig = Field(default_factory=CoachConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)


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
