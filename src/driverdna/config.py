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

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class IncidentConfig(_Section):
    """Incident detection + characterization thresholds (deterministic, like
    the principle detectors). Every value is a documented default, tunable
    through ConfigStore. Detection finds an incident window; characterization
    names the mechanism from the telemetry at onset, confidence-qualified,
    and returns 'unclassified' whenever the signature is ambiguous — a spin
    the engine cannot confidently explain is never given a guessed cause."""

    # --- Detection (Layer 1) ---
    offtrack_position_value: int = Field(
        default=4,
        description="PositionType value meaning off-track surface (iRacing "
        "TrackSurface; 3=on-track, 4=off). Stored-not-depended-on per A13 — "
        "used only as a corroborating signal, never as the sole trigger.",
    )
    offtrack_min_s: float = Field(
        default=0.20,
        description="Off-track surface sustained at least this long is an "
        "incident signal (a single stray sample is not).",
    )
    near_stop_speed_kmh: float = Field(
        default=25.0,
        description="Speed below this, sustained, mid-lap and out of the pits "
        "is a near-stop: below any road-course racing corner (Spa's slowest, "
        "La Source, apexes ~45-50 km/h). Retune for tracks with genuine "
        "sub-25 km/h corners.",
    )
    near_stop_min_s: float = Field(
        default=0.50,
        description="Near-stop speed sustained at least this long before it "
        "counts — brief dips at a hairpin exit do not.",
    )
    spin_window_s: float = Field(
        default=0.35,
        description="Window over which a steering reversal (full sign flip, "
        "large magnitude both sides) is looked for — the opposite-lock catch "
        "of a slide happens within this long.",
    )
    spin_steering_reversal_deg: float = Field(
        default=60.0,
        description="A steering reversal counts as a spin/snap signal only if "
        "the wheel swings past +/- this magnitude on both sides of zero "
        "within spin_window_s (catching a slide), not the gentle "
        "unwind of a normal corner.",
    )
    spin_yaw_rate_min: float = Field(
        default=0.30,
        description="Peak |yaw rate| (rad/s) that must accompany a steering "
        "reversal for it to read as a genuine snap rather than a tidy "
        "hand-over-hand on a slow hairpin.",
    )
    merge_gap_s: float = Field(
        default=0.60,
        description="Incident signals (off-track, near-stop, spin) closer "
        "than this merge into one incident event — a spin, its excursion, and "
        "its recovery stop are one incident, not three.",
    )
    # --- Characterization (Layer 2) ---
    classify_brake_floor: float = Field(
        default=0.20,
        description="Brake application at onset above this reads the snap as "
        "trail-brake / entry oversteer (still braking into rotation).",
    )
    classify_throttle_floor: float = Field(
        default=0.20,
        description="Throttle at onset above this, with the car past the apex "
        "and not braking, reads as power-on oversteer.",
    )
    classify_throttle_drop: float = Field(
        default=0.30,
        description="A throttle drop of at least this in the moment before "
        "onset reads as lift-off oversteer.",
    )
    classify_vert_accel_spike: float = Field(
        default=4.0,
        description="Vertical acceleration deviation (m/s^2) from ~1 g at "
        "onset above this reads the disturbance as external (kerb/bump) — "
        "possibly-not-driver, flagged so, never blamed on technique.",
    )


class RetentionConfig(_Section):
    """Raw-sample retention (M2). Compact summaries are permanent."""

    raw_laps_per_cohort: int = Field(
        default=100,
        description="Newest N raw lap blobs kept per driver/car/track cohort; "
        "eviction deletes blobs only and can never touch summaries, trends, "
        "or findings.",
    )


class ModelConfig(_Section):
    """Driver Model deterministic scoring (M6, model `dm-v1`).

    A fundamental's score is a weighted aggregation of principle-adherence
    rate, normalized vs-self opportunity, and consistency
    (ARCHITECTURE_VISION.md's Scoring Contract; SPEC.md Milestone 6). When a
    fundamental has no evidence for one of the three components (e.g.
    vehicle_management has no detector, so it has no adherence component),
    that component's weight redistributes across the components that do have
    evidence — never a fabricated neutral value.
    """

    weight_adherence: float = Field(
        default=0.40,
        description="Score weight for principle-adherence rate (1 - detector "
        "trigger rate) among the fundamental's mapped detectors.",
    )
    weight_opportunity: float = Field(
        default=0.35,
        description="Score weight for normalized vs-self opportunity (seconds "
        "lost, from cumulative_loss, in the fundamental's mapped phases).",
    )
    weight_consistency: float = Field(
        default=0.25,
        description="Score weight for consistency (coefficient of variation "
        "of the fundamental's metrics across laps).",
    )
    opportunity_ceiling_s: float = Field(
        default=1.0,
        description="Cumulative per-lap loss (seconds) in a fundamental's "
        "mapped phases considered maximal (scores 0); scaled linearly from 0 "
        "loss (scores 100) to this ceiling.",
    )
    consistency_cv_ceiling: float = Field(
        default=0.5,
        description="Coefficient of variation (std/|mean|, unitless — keeps "
        "the consistency component comparable across metrics in different "
        "units) considered maximally inconsistent (scores 0); scaled "
        "linearly from CV 0 (scores 100) to this ceiling.",
    )
    min_evidence_for_score: int = Field(
        default=5,
        description="A measured/proxy fundamental needs at least this many "
        "distinct contributing laps before it emits a numeric score; below "
        "it, insufficient data — never a noisy score from a handful of laps.",
    )
    proxy_confidence_cap: float = Field(
        default=0.5,
        description="A proxy fundamental's confidence is capped here even "
        "with abundant evidence — a weak, indirect signal stays labeled "
        "low-confidence by construction, not just by data volume "
        "(ARCHITECTURE_VISION.md: 'a weak proxy gets a low-confidence score "
        "that says so').",
    )
    confidence_evidence_floor: int = Field(
        default=50,
        description="Distinct contributing laps at which the volume half of "
        "confidence saturates (reaches 1.0).",
    )
    confidence_session_floor: int = Field(
        default=6,
        description="Distinct sessions at which the session-breadth third of "
        "confidence's breadth half saturates.",
    )
    confidence_track_floor: int = Field(
        default=3,
        description="Distinct tracks at which the track-breadth third of "
        "confidence's breadth half saturates.",
    )
    confidence_car_floor: int = Field(
        default=2,
        description="Distinct cars at which the car-breadth third of "
        "confidence's breadth half saturates.",
    )
    trend_min_laps_per_bucket: int = Field(
        default=4,
        description="Trend needs at least this many dated laps (lap_date set, "
        "e.g. from sync) in EACH of the earlier/recent halves before a "
        "direction is computed; below 2x this in dated laps total, trend is "
        "'unavailable' — never a direction inferred from one or two laps.",
    )
    trend_delta_points: float = Field(
        default=5.0,
        description="A fundamental's recent-minus-earlier score (on the 0-100 "
        "scale) must move more than this many points to read as "
        "improving/declining; within +/- this band it is 'stable'. Guards "
        "against calling ordinary noise a trend.",
    )

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "ModelConfig":
        total = self.weight_adherence + self.weight_opportunity + self.weight_consistency
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"model weights must sum to 1.0, got {total} "
                f"(adherence={self.weight_adherence}, "
                f"opportunity={self.weight_opportunity}, "
                f"consistency={self.weight_consistency})"
            )
        return self


class CoachingConfig(_Section):
    """Coaching Intelligence eligibility/ranking/gap-band thresholds (M7,
    ontology `coach-onto-v1`; docs/COACHING.md).

    Detector-gated principles reuse `detectors.min_trigger_rate` — one floor
    for "is this a pattern," not duplicated here. `commitment_cv_floor` and
    `consistency_cv_floor` gate the two principles with no detector
    (trust_the_proxy, same_lap_twice): a coefficient of variation (same
    definition as ModelConfig's) crossing the floor is their trigger.

    Gap bands are absolute, versioned thresholds, never invented per-call
    (docs/COACHING.md, "Gap bands — mechanics"): seconds-based bands score
    the phase's `cumulative_loss` for every principle that maps to a phase;
    `same_lap_twice` has no phase (consistency is cross-cutting, per
    taxonomy.py) and bands on its own CV instead — the CV-band thresholds
    exist for that one principle. Below the moderate floor is negligible
    (silent, never surfaced); moderate is quiet (mentioned only if asked);
    notable/major are loud (the headline candidate pool).
    """

    gap_band_moderate_s: float = Field(
        default=0.05,
        description="Phase cumulative-loss seconds at/above which a "
        "principle's tone rises from negligible (silent) to moderate "
        "(quiet, secondary only).",
    )
    gap_band_notable_s: float = Field(
        default=0.15,
        description="Phase cumulative-loss seconds at/above which a "
        "principle's tone rises to notable (loud, headline-eligible).",
    )
    gap_band_major_s: float = Field(
        default=0.35,
        description="Phase cumulative-loss seconds at/above which a "
        "principle's tone rises to major (loud, headline-eligible).",
    )
    cv_band_moderate: float = Field(
        default=0.15,
        description="same_lap_twice's own coefficient-of-variation floor for "
        "moderate tone (no phase exists for consistency to band on instead).",
    )
    cv_band_notable: float = Field(
        default=0.30,
        description="same_lap_twice's coefficient-of-variation floor for "
        "notable tone.",
    )
    cv_band_major: float = Field(
        default=0.50,
        description="same_lap_twice's coefficient-of-variation floor for "
        "major tone.",
    )
    commitment_cv_floor: float = Field(
        default=0.15,
        description="trust_the_proxy's trigger: brake_point_dist_pct's "
        "coefficient of variation for this corner must reach this floor "
        "before the entry-commitment proxy principle is eligible.",
    )
    consistency_cv_floor: float = Field(
        default=0.15,
        description="same_lap_twice's trigger: a corner's own measured "
        "metrics' pooled coefficient of variation must reach this floor "
        "before the principle is eligible. Known v1 limitation, flagged not "
        "silently accepted: the pool mixes metrics of very different "
        "natural scale/type (continuous percentages, rates, small integer "
        "counts) with no per-metric normalization beyond CV itself — a "
        "low-mean count metric (e.g. throttle_modulation_count, often 0) "
        "can produce an outsized CV that dominates the unweighted average, "
        "same underlying issue as ModelConfig's cross-cohort pooling "
        "caveat, one level down (per-corner instead of per-driver).",
    )
    thin_evidence_floor_n: int = Field(
        default=8,
        description="Below this many contributing laps, an eligible "
        "principle is still shown at its earned gap band but flagged "
        "thin-evidence — confidence_floor's tempering signal "
        "(docs/COACHING.md: 'softens phrasing when the measured evidence "
        "itself is thin,' never the gap band itself).",
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
    incidents: IncidentConfig = Field(default_factory=IncidentConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    coaching: CoachingConfig = Field(default_factory=CoachingConfig)


def load_config(path: Path | None = None) -> DriverDNAConfig:
    """Defaults, with an optional TOML file merged over them.

    Unknown keys anywhere in the file raise — a misspelled threshold must
    fail loudly, never silently fall back to a default.
    """
    if path is None or not Path(path).exists():
        return DriverDNAConfig()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return DriverDNAConfig.model_validate(data)


def config_snapshot(config: DriverDNAConfig) -> dict[str, object]:
    """Flat {dotted key: value} view of every threshold in force."""
    snapshot: dict[str, object] = {}
    for section, model in config:
        for key, value in model:
            snapshot[f"{section}.{key}"] = value
    return snapshot


def describe_key(key: str) -> str | None:
    """The documented description of a dotted config key, if it exists."""
    section, _, field_name = key.partition(".")
    section_field = DriverDNAConfig.model_fields.get(section)
    if section_field is None or not field_name:
        return None
    section_cls = section_field.annotation
    field = section_cls.model_fields.get(field_name) if section_cls else None
    return None if field is None else field.description


class ConfigStore:
    """The single write path for parameter changes — CLI or a confirmed chat
    proposal. Every change is validated against the typed schema, written to
    the TOML file, and recorded in config_history: versioned and reversible.
    Nothing retunes a threshold silently."""

    def __init__(self, path: Path, db):
        self.path = Path(path)
        self.db = db

    def current(self) -> DriverDNAConfig:
        return load_config(self.path)

    def get(self, key: str):
        snapshot = config_snapshot(self.current())
        if key not in snapshot:
            raise KeyError(f"unknown config key: {key}")
        return snapshot[key]

    def propose(self, key: str, new_value) -> dict:
        """Validate and stage a change WITHOUT applying it."""
        old_value = self.get(key)  # raises on unknown key
        self._validated_data(key, new_value)  # raises on type-invalid value
        return {"key": key, "old_value": old_value, "new_value": new_value,
                "description": describe_key(key)}

    def apply(self, proposal: dict, *, source: str, note: str | None = None) -> int:
        """Write a staged proposal through: TOML + history row."""
        data = self._validated_data(proposal["key"], proposal["new_value"])
        self._write_toml(data)
        return self.db.record_config_change(
            key=proposal["key"],
            old_value=str(proposal["old_value"]),
            new_value=str(proposal["new_value"]),
            source=source,
            note=note,
        )

    def revert(self, change_pk: int, *, note: str | None = None) -> int:
        """Apply a recorded change's old value back (as a new change)."""
        row = self.db.conn.execute(
            "SELECT * FROM config_history WHERE change_pk=?", (change_pk,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no config change #{change_pk}")
        current = self.get(row["key"])
        old_typed = self._coerce_like(row["key"], row["old_value"])
        proposal = {"key": row["key"], "old_value": current, "new_value": old_typed}
        return self.apply(
            proposal, source=row["source"],
            note=note or f"revert of change #{change_pk}",
        )

    def _coerce_like(self, key: str, text: str):
        current = self.get(key)
        if isinstance(current, bool):
            return text == "True"
        return type(current)(text)

    def _validated_data(self, key: str, new_value) -> dict:
        section, _, field_name = key.partition(".")
        config = self.current()
        data = config.model_dump()
        if section not in data or field_name not in data[section]:
            raise KeyError(f"unknown config key: {key}")
        data[section][field_name] = new_value
        DriverDNAConfig.model_validate(data)  # type/shape check, loud
        return data

    def _write_toml(self, data: dict) -> None:
        lines = []
        for section in sorted(data):
            lines.append(f"[{section}]")
            for field_name, value in sorted(data[section].items()):
                if isinstance(value, bool):
                    rendered = "true" if value else "false"
                elif isinstance(value, str):
                    rendered = f'"{value}"'
                else:
                    rendered = repr(value)
                lines.append(f"{field_name} = {rendered}")
            lines.append("")
        self.path.write_text("\n".join(lines))
