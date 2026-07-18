"""AttributionEngine: time-at-distance deltas over canonical phase windows (M3).

The correctness core: per-lap landmarks move lap to lap — that movement IS
the driving signal — so phase times are NEVER measured between a lap's own
landmarks. Each corner gets canonical windows, frozen from the median
landmark positions of the laps that built (or admitted) it:

    entry = brake_start -> turn_in
    mid   = turn_in -> apex
    exit  = apex -> min(full_throttle, corner exit)

Every lap is measured across those identical track spans via interpolated
t(lap_dist), so a phase delta is a true time difference over the same piece
of road. Windows are part of the frozen corner map: stable, inspectable,
never silently re-derived.

Baselines are robust because no lap-validity channel exists: phase times are
screened with a median±k·MAD outlier fence, the primary baseline is the
median of the top-k screened executions, and the single best is shown but
labeled. The composite (sum of robust bests) is labeled theoretical.
Reference laps produce a separate envelope, reported as "gap to reference" —
never "recoverable time".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from driverdna.config import AttributionConfig

PHASES = ("entry", "mid", "exit")

#: Technique metrics associated with each phase (tagging for findings).
PHASE_METRICS: dict[str, tuple[str, ...]] = {
    "entry": (
        "brake_point_dist_pct", "brake_application_rate", "brake_peak",
        "brake_release_duration_s", "trail_brake_overlap_s",
        "throttle_brake_overlap_s", "turn_in_dist_pct",
    ),
    "mid": (
        "steering_corrections", "steering_smoothness_dps2", "yaw_peak_rate",
        "min_speed_kmh", "apex_dist_pct", "coast_s",
    ),
    "exit": (
        "throttle_pickup_dist_pct", "throttle_modulation_count",
        "full_throttle_dist_pct", "exit_accel_ms2",
    ),
}


@dataclass(frozen=True)
class PhaseWindows:
    """Canonical, frozen phase boundaries for one corner (lap-dist mod 1)."""

    entry_start: float | None  # median brake_start; None = no braking corner
    turn_in: float | None
    apex: float
    exit_end: float | None

    def window(self, phase: str) -> tuple[float, float] | None:
        """[start, end) positions for a phase, or None if undefined."""
        if phase == "entry":
            if self.entry_start is None or self.turn_in is None:
                return None
            start, end = self.entry_start, self.turn_in
        elif phase == "mid":
            if self.turn_in is None:
                return None
            start, end = self.turn_in, self.apex
        elif phase == "exit":
            if self.exit_end is None:
                return None
            start, end = self.apex, self.exit_end
        else:
            raise ValueError(f"unknown phase {phase!r}")
        span = _circular_span(start, end)
        # Zero span: landmarks collapsed (flat kink). Span > half a lap: the
        # boundaries are inverted (e.g. turn-in before brake start — a legit
        # style in which this phase, as defined, does not exist).
        if span <= 0 or span > 0.5:
            return None
        return start, end


def _circular_span(start: float, end: float) -> float:
    """Forward distance start -> end on the lap circle (0 when equal)."""
    return (end - start) % 1.0 if end != start else 0.0


def _median_or_none(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return float(np.median(present)) if present else None


def derive_windows(position_records: list[dict]) -> PhaseWindows | None:
    """Freeze canonical windows from observations' landmark positions.

    Positions near the start/finish line can straddle the 0/1 seam; medians
    are taken in a coordinate frame unwrapped around the apex to keep them
    meaningful there.
    """
    apexes = [r.get("apex") for r in position_records if r.get("apex") is not None]
    if not apexes:
        return None
    ref = float(apexes[0])

    def unwrap(v: float | None) -> float | None:
        if v is None:
            return None
        # Map into (ref-0.5, ref+0.5] so the seam never splits a corner.
        return v + round(ref - v)

    def med(name: str) -> float | None:
        vals = [unwrap(r.get(name)) for r in position_records]
        m = _median_or_none(vals)
        return None if m is None else m % 1.0

    apex = med("apex")
    assert apex is not None
    entry_start = med("brake_start")
    turn_in = med("turn_in")
    full = med("full_throttle")
    exit_pos = med("exit")
    if full is not None and exit_pos is not None:
        exit_end = full if _circular_span(apex, full) <= _circular_span(apex, exit_pos) else exit_pos
    else:
        exit_end = full if full is not None else exit_pos
    return PhaseWindows(
        entry_start=entry_start, turn_in=turn_in, apex=apex, exit_end=exit_end
    )


def time_at(lap_dist: np.ndarray, elapsed_s: np.ndarray, pos: float) -> float:
    """Interpolated elapsed time at a canonical position (mod-1), mapped into
    this lap's continuous distance coordinate and clamped to its span."""
    p = pos % 1.0
    if p < lap_dist[0]:
        p += 1.0
    p = min(max(p, float(lap_dist[0])), float(lap_dist[-1]))
    return float(np.interp(p, lap_dist, elapsed_s))


def phase_times(
    lap_dist: np.ndarray, elapsed_s: np.ndarray, windows: PhaseWindows
) -> dict[str, float]:
    """This lap's time across each canonical window that is defined."""
    out: dict[str, float] = {}
    for phase in PHASES:
        w = windows.window(phase)
        if w is None:
            continue
        start, end = w
        t0 = time_at(lap_dist, elapsed_s, start)
        end_pos = start + _circular_span(start, end)  # keep end after start
        t1 = time_at(lap_dist, elapsed_s, end_pos)
        if t1 > t0:
            out[phase] = t1 - t0
    return out


@dataclass(frozen=True)
class PhaseBaseline:
    """Robust self-baseline for one corner phase."""

    n: int  # screened samples the baseline stands on
    n_outliers: int  # screened out (caveated, never silently dropped)
    robust_best_s: float  # median of top-k screened executions (primary)
    single_best_s: float  # fastest screened execution (shown, labeled)
    median_s: float  # typical execution
    spread_s: float  # sample std of screened times


def screen_outliers(times: list[float], k: float) -> tuple[list[float], int]:
    """Median ± k·MAD fence. Returns (kept, n_screened)."""
    if len(times) < 4:
        return list(times), 0  # too few points to call anything an outlier
    arr = np.asarray(times, dtype=np.float64)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    if mad == 0.0:
        return list(times), 0
    keep = np.abs(arr - med) <= k * mad
    return [float(v) for v in arr[keep]], int(np.sum(~keep))


def baseline(times: list[float], cfg: AttributionConfig) -> PhaseBaseline | None:
    if not times:
        return None
    kept, screened = screen_outliers(times, cfg.outlier_mad_k)
    arr = np.sort(np.asarray(kept, dtype=np.float64))
    top = arr[: max(1, min(cfg.baseline_top_k, len(arr)))]
    return PhaseBaseline(
        n=len(arr),
        n_outliers=screened,
        robust_best_s=float(np.median(top)),
        single_best_s=float(arr[0]),
        median_s=float(np.median(arr)),
        spread_s=float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
    )


@dataclass(frozen=True)
class ReferenceEnvelope:
    """Reference-lap phase times for one corner phase. Deltas against this
    are 'gap to reference' — context, never 'recoverable time'."""

    n: int
    median_s: float
    best_s: float


def reference_envelope(times: list[float]) -> ReferenceEnvelope | None:
    if not times:
        return None
    arr = np.asarray(times, dtype=np.float64)
    return ReferenceEnvelope(
        n=len(arr), median_s=float(np.median(arr)), best_s=float(arr.min())
    )
