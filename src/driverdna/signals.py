"""Shared numeric helpers for detection code (M1+).

Small, tested primitives so segmentation, metrics, and detectors share one
implementation of smoothing and run/mask logic instead of re-deriving them.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

from driverdna.config import SmoothingConfig


def smooth(x: np.ndarray, cfg: SmoothingConfig) -> np.ndarray:
    """Savitzky-Golay smoothing, degrading gracefully on short arrays."""
    window = min(cfg.window_samples, len(x))
    if window % 2 == 0:
        window -= 1
    if window <= cfg.polyorder:
        return x.astype(np.float64, copy=True)
    return savgol_filter(x.astype(np.float64), window, cfg.polyorder)


def runs_of(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True runs as half-open [start, end) index pairs."""
    if len(mask) == 0:
        return []
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return [(int(edges[i]), int(edges[i + 1])) for i in range(0, len(edges), 2)]


def close_gaps(mask: np.ndarray, max_gap: int) -> np.ndarray:
    """Fill False gaps of at most max_gap samples between True runs."""
    out = mask.astype(bool).copy()
    spans = runs_of(out)
    for (_, prev_end), (next_start, _) in zip(spans, spans[1:]):
        if next_start - prev_end <= max_gap:
            out[prev_end:next_start] = True
    return out


def drop_short_runs(mask: np.ndarray, min_len: int) -> np.ndarray:
    """Remove True runs shorter than min_len samples."""
    out = mask.astype(bool).copy()
    for start, end in runs_of(out):
        if end - start < min_len:
            out[start:end] = False
    return out


def first_sustained_run(
    mask: np.ndarray, min_len: int, start: int = 0, end: int | None = None
) -> int | None:
    """Index where the first True run of at least min_len begins, in [start, end)."""
    end = len(mask) if end is None else end
    for run_start, run_end in runs_of(mask[start:end]):
        if run_end - run_start >= max(1, min_len):
            return start + run_start
    return None
