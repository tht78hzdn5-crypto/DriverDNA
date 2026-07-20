"""The pyramid, made explicit: observable -> technique -> fundamental (M6).

Versioned, static data — not computed, not inferred. Every one of the 18
metrics (metrics/technique.py METRIC_DEFS) and 5 detectors
(metrics/detectors.py) maps to exactly one technique. `signal_status` on a
technique states plainly whether it has real telemetry behind it:

  measured  - a real detector/metric drives it directly.
  proxy     - a real but weak/indirect stand-in (labeled wherever shown).
  no_signal - no telemetry channel exists at all (matches
              report/payload.py's UNAVAILABLE_FUNDAMENTALS: tire
              slip/utilization, vision/eye-line). Never inferred, never
              scored, at any confidence — see docs/COACHING.md, "Conviction
              where measured, silence or self-check where not," which
              states the same rule for the coaching layer one level up.

A fundamental's own signal_status is the best status among its techniques
(if even one technique is measured or proxy, the fundamental isn't fully
unmeasurable) - `vehicle_management` is the clearest case: real signal from
ABS activation rate, but tire utilization / weight transfer / slip
management are no_signal, so the fundamental is `proxy` overall.

`phases` (a subset of PHASES from attribution/engine.py) is the separate
mapping used for the "opportunity" score component (M6b): cumulative loss is
only ever computed per corner PHASE (entry/mid/exit), not per metric, so a
fundamental's attributable seconds-lost comes from its mapped phases, not
its mapped metrics. `consistency` is deliberately unmapped to phases/
detectors - its own component is enough; braking/rotation/corner_exit
already have their own consistency signal, and it's not a technique
correctness check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SignalStatus(StrEnum):
    MEASURED = "measured"
    PROXY = "proxy"
    NO_SIGNAL = "no_signal"


@dataclass(frozen=True)
class Technique:
    id: str
    fundamental: str
    signal_status: SignalStatus
    description: str
    metrics: tuple[str, ...] = ()
    detectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fundamental:
    id: str
    description: str
    techniques: tuple[str, ...]
    phases: tuple[str, ...] = ()  # for the M6b opportunity component

    @property
    def signal_status(self) -> SignalStatus:
        """Not "best of its techniques" - one measured technique among three
        no_signal ones (vehicle_management) is not a fully measured
        fundamental. MEASURED requires every technique to be measured;
        NO_SIGNAL requires every technique to have nothing; anything mixed
        (including all-proxy, or measured+no_signal together) is PROXY - real
        but partial signal, exactly what "proxy" is for.
        """
        statuses = {TECHNIQUES[t].signal_status for t in self.techniques}
        if statuses == {SignalStatus.NO_SIGNAL}:
            return SignalStatus.NO_SIGNAL
        if statuses == {SignalStatus.MEASURED}:
            return SignalStatus.MEASURED
        return SignalStatus.PROXY


TAXONOMY_VERSION = "pyramid-v1"

TECHNIQUES: dict[str, Technique] = {
    t.id: t
    for t in (
        # --- braking ---------------------------------------------------
        Technique(
            id="brake_point_selection", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            description="Where braking for the corner begins.",
            metrics=("brake_point_dist_pct",),
        ),
        Technique(
            id="brake_application", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            description="How the pedal is applied from first touch to peak.",
            metrics=("brake_application_rate", "brake_peak"),
        ),
        Technique(
            id="brake_release", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            description="Whether the release tapers into rotation or is dropped.",
            metrics=("brake_release_duration_s",),
            detectors=("brake-release-taper",),
        ),
        Technique(
            id="trail_braking", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            description="Overlap of braking and steering into the corner.",
            metrics=("trail_brake_overlap_s",),
        ),
        Technique(
            id="pedal_overlap", fundamental="braking",
            signal_status=SignalStatus.MEASURED,
            description="Throttle and brake working against each other.",
            metrics=("throttle_brake_overlap_s",),
            detectors=("throttle-brake-overlap",),
        ),
        # --- rotation ----------------------------------------------------
        Technique(
            id="turn_in", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            description="Where and how committed the turn-in is.",
            metrics=("turn_in_dist_pct",),
            detectors=("one-steering-input",),
        ),
        Technique(
            id="steering_smoothness", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            description="Correction count and smoothness entry to apex.",
            metrics=("steering_corrections", "steering_smoothness_dps2"),
        ),
        Technique(
            id="rotation_efficiency", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            description="Rotation actually achieved: yaw response and apex speed.",
            metrics=("yaw_peak_rate", "min_speed_kmh", "apex_dist_pct"),
        ),
        Technique(
            id="coasting", fundamental="rotation",
            signal_status=SignalStatus.MEASURED,
            description="Time with neither pedal working mid-corner.",
            metrics=("coast_s",),
            detectors=("coast-window",),
        ),
        # --- corner_exit ---------------------------------------------------
        Technique(
            id="throttle_pickup", fundamental="corner_exit",
            signal_status=SignalStatus.MEASURED,
            description="Where and how throttle is picked up after the apex.",
            metrics=("throttle_pickup_dist_pct",),
            detectors=("throttle-monotonic",),
        ),
        Technique(
            id="throttle_modulation", fundamental="corner_exit",
            signal_status=SignalStatus.MEASURED,
            description="Lifts/stabs between pickup and full throttle.",
            metrics=("throttle_modulation_count",),
        ),
        Technique(
            id="exit_acceleration", fundamental="corner_exit",
            signal_status=SignalStatus.MEASURED,
            description="Full-throttle point and acceleration achieved.",
            metrics=("full_throttle_dist_pct", "exit_accel_ms2"),
        ),
        # --- vehicle_management -------------------------------------------
        Technique(
            id="abs_usage", fundamental="vehicle_management",
            signal_status=SignalStatus.MEASURED,
            description="Share of braking time with ABS active.",
            metrics=("abs_active_ratio",),
        ),
        Technique(
            id="tire_utilization", fundamental="vehicle_management",
            signal_status=SignalStatus.NO_SIGNAL,
            description="No slip/utilization channel in the source contract.",
        ),
        Technique(
            id="weight_transfer", fundamental="vehicle_management",
            signal_status=SignalStatus.NO_SIGNAL,
            description="No load-transfer channel in the source contract.",
        ),
        Technique(
            id="slip_management", fundamental="vehicle_management",
            signal_status=SignalStatus.NO_SIGNAL,
            description="No slip channel in the source contract.",
        ),
        # --- consistency (cross-cutting; see module docstring) -------------
        Technique(
            id="repeatability", fundamental="consistency",
            signal_status=SignalStatus.MEASURED,
            description="Lap-to-lap variance across every measured technique.",
        ),
        # --- commitment (weak proxy) ----------------------------------
        Technique(
            id="entry_commitment", fundamental="commitment",
            signal_status=SignalStatus.PROXY,
            description="Brake-point timing as a weak, indirect stand-in for "
            "entry commitment - not a direct measurement (ARCHITECTURE_VISION.md).",
            metrics=("brake_point_dist_pct",),
        ),
        # --- vision (no signal) -----------------------------------------
        Technique(
            id="eye_line", fundamental="vision",
            signal_status=SignalStatus.NO_SIGNAL,
            description="No eye-tracking channel exists; never inferred.",
        ),
    )
}

FUNDAMENTALS: dict[str, Fundamental] = {
    "braking": Fundamental(
        id="braking",
        description="Brake point, application, release, and trail braking.",
        techniques=(
            "brake_point_selection", "brake_application", "brake_release",
            "trail_braking", "pedal_overlap",
        ),
        phases=("entry",),
    ),
    "rotation": Fundamental(
        id="rotation",
        description="Turn-in, steering smoothness, and mid-corner speed.",
        techniques=("turn_in", "steering_smoothness", "rotation_efficiency", "coasting"),
        phases=("mid",),
    ),
    "corner_exit": Fundamental(
        id="corner_exit",
        description="Throttle pickup, modulation, and exit acceleration.",
        techniques=("throttle_pickup", "throttle_modulation", "exit_acceleration"),
        phases=("exit",),
    ),
    "vehicle_management": Fundamental(
        id="vehicle_management",
        description="ABS usage (real signal); tire utilization, weight "
        "transfer, and slip management have no telemetry channel.",
        techniques=("abs_usage", "tire_utilization", "weight_transfer", "slip_management"),
    ),
    "consistency": Fundamental(
        id="consistency",
        description="How repeatable the driver's technique is, lap to lap, "
        "pooled across every measured technique.",
        techniques=("repeatability",),
    ),
    "commitment": Fundamental(
        id="commitment",
        description="Entry commitment - proxy only, via brake-point timing.",
        techniques=("entry_commitment",),
        phases=("entry",),
    ),
    "vision": Fundamental(
        id="vision",
        description="Eye-line / vision - no telemetry channel, ever.",
        techniques=("eye_line",),
    ),
}


def metric_fundamentals(metric_name: str) -> tuple[str, ...]:
    """Fundamental IDs any technique maps this metric into (may be >1)."""
    return tuple(
        sorted({t.fundamental for t in TECHNIQUES.values() if metric_name in t.metrics})
    )


def detector_fundamentals(detector_name: str) -> tuple[str, ...]:
    return tuple(
        sorted({t.fundamental for t in TECHNIQUES.values() if detector_name in t.detectors})
    )


def fundamental_techniques(fundamental_id: str) -> tuple[Technique, ...]:
    return tuple(TECHNIQUES[t] for t in FUNDAMENTALS[fundamental_id].techniques)


def fundamental_metrics(fundamental_id: str) -> tuple[str, ...]:
    return tuple(
        sorted({m for t in fundamental_techniques(fundamental_id) for m in t.metrics})
    )


def fundamental_detectors(fundamental_id: str) -> tuple[str, ...]:
    return tuple(
        sorted({d for t in fundamental_techniques(fundamental_id) for d in t.detectors})
    )
