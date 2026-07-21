"""Layer 1 — incident detection: a lap-level scan for incident windows.

Unlike the principle detectors (metrics/detectors.py), which run per
corner-span and price form as a trigger-rate, this scans the whole lap trace
for events — a near-stop, an off-track excursion, a snap/spin — merges
overlapping signals into one incident window, and associates it to a frozen
corner when it overlaps one. Detection is deterministic and config-thresholded;
the mechanism is named separately (classify.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from driverdna.config import IncidentConfig
from driverdna.ingest.contract import SAMPLE_RATE_HZ
from driverdna.ingest.parser import TelemetryLap

_MS_TO_KMH = 3.6


@dataclass(frozen=True)
class Incident:
    """One detected incident on one lap. `kinds` are the raw detection
    signals that fired (near_stop / off_track / spin); `span` is the sample
    range (inclusive start, exclusive end). Classification (mechanism,
    confidence, rationale) is filled by classify.py. Every field decomposes
    to the samples in `span`."""

    span_start: int
    span_end: int
    kinds: tuple[str, ...]
    corner_id: str | None
    onset: int  # sample where the incident begins (drives classification)
    min_speed_kmh: float
    peak_yaw_rate: float
    classification: str = "unclassified"
    confidence: str = "low"
    rationale: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return (self.span_end - self.span_start) / SAMPLE_RATE_HZ


def _runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Contiguous True runs in `mask` at least `min_len` samples long,
    as (start, end) with end exclusive."""
    if not mask.any():
        return []
    edges = np.diff(mask.astype(np.int8))
    starts = list(np.where(edges == 1)[0] + 1)
    ends = list(np.where(edges == -1)[0] + 1)
    if mask[0]:
        starts.insert(0, 0)
    if mask[-1]:
        ends.append(len(mask))
    return [(s, e) for s, e in zip(starts, ends) if e - s >= min_len]


def _near_stop_runs(lap: TelemetryLap, cfg: IncidentConfig) -> list[tuple[int, int]]:
    kmh = lap.speed * _MS_TO_KMH
    min_len = max(1, int(cfg.near_stop_min_s * SAMPLE_RATE_HZ))
    return _runs(kmh < cfg.near_stop_speed_kmh, min_len)


def _off_track_runs(lap: TelemetryLap, cfg: IncidentConfig) -> list[tuple[int, int]]:
    min_len = max(1, int(cfg.offtrack_min_s * SAMPLE_RATE_HZ))
    return _runs(lap.position_type == cfg.offtrack_position_value, min_len)


def _spin_runs(lap: TelemetryLap, cfg: IncidentConfig) -> list[tuple[int, int]]:
    """A snap/spin: within a short sliding window the steering wheel swings
    fully across zero, past +/- the reversal magnitude on both sides (the
    opposite-lock catch of a slide), accompanied by an elevated yaw rate —
    not the tidy unwind of a normal corner."""
    n = lap.n_samples
    w = max(2, int(cfg.spin_window_s * SAMPLE_RATE_HZ))
    steer = lap.steering_deg
    yaw = np.abs(lap.yaw_rate)
    thr = cfg.spin_steering_reversal_deg
    hits = np.zeros(n, dtype=bool)
    for i in range(n - w):
        seg = steer[i : i + w]
        if seg.max() >= thr and seg.min() <= -thr and yaw[i : i + w].max() >= cfg.spin_yaw_rate_min:
            hits[i : i + w] = True
    return _runs(hits, 1)


def _corner_at(lap: TelemetryLap, sample: int, corner_positions: dict[str, float]) -> str | None:
    """Nearest frozen corner (by apex lap-distance fraction) to a sample,
    within a small tolerance — an incident 'at' a corner, not lap-wide."""
    if not corner_positions:
        return None
    pos = float(lap.lap_dist[sample])
    cid, dist = min(
        ((c, abs(pos - p)) for c, p in corner_positions.items()), key=lambda kv: kv[1]
    )
    return cid if dist <= 0.03 else None  # within ~3% of lap distance


def scan_incidents(
    lap: TelemetryLap,
    *,
    corner_positions: dict[str, float] | None,
    config: IncidentConfig,
) -> list[Incident]:
    """Detect and classify every incident on one lap. `corner_positions` maps
    corner_id -> apex lap-distance fraction (0-1) from the frozen map, used
    only to label an incident's location; pass None/{} when no map exists."""
    from driverdna.incidents.classify import classify_incident

    corner_positions = corner_positions or {}
    tagged: list[tuple[int, int, str]] = []
    for s, e in _near_stop_runs(lap, config):
        tagged.append((s, e, "near_stop"))
    for s, e in _off_track_runs(lap, config):
        tagged.append((s, e, "off_track"))
    for s, e in _spin_runs(lap, config):
        tagged.append((s, e, "spin"))
    if not tagged:
        return []

    tagged.sort()
    merge_gap = int(config.merge_gap_s * SAMPLE_RATE_HZ)
    merged: list[list] = []  # [start, end, {kinds}]
    for s, e, kind in tagged:
        if merged and s - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], e)
            merged[-1][2].add(kind)
        else:
            merged.append([s, e, {kind}])

    incidents: list[Incident] = []
    for start, end, kinds in merged:
        seg_speed = lap.speed[start:end] * _MS_TO_KMH
        # A spin's causal onset is where the rotation *begins* — the first
        # sample the yaw diverges — not the peak-yaw moment, by which point
        # the driver is already reacting (opposite lock, throttle stab) and
        # the inputs that caused it are gone. A near-stop / off has no snap,
        # so its onset is where it begins.
        if "spin" in kinds:
            diverged = np.where(np.abs(lap.yaw_rate[start:end]) >= config.spin_yaw_rate_min)[0]
            onset = start + int(diverged[0]) if len(diverged) else start
        else:
            onset = start
        inc = Incident(
            span_start=start,
            span_end=end,
            kinds=tuple(sorted(kinds)),
            corner_id=_corner_at(lap, onset, corner_positions),
            onset=onset,
            min_speed_kmh=float(seg_speed.min()) if len(seg_speed) else 0.0,
            peak_yaw_rate=float(np.abs(lap.yaw_rate[start:end]).max()),
        )
        incidents.append(classify_incident(lap, inc, config))
    return incidents
