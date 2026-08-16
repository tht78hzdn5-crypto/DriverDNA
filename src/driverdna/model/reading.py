"""The strongest/weakest reading (A51, `read-v1`).

Half of what this product exists to say is "here is what you are good at",
and until now the engine had no representation of a strength at all — it
rendered seven bare scores and left the driver to do the comparison. This
module does that comparison, deterministically, and states its own gates
when it declines to.

It computes NO measurement: it orders beliefs `scoring.py` already produced
and reports the order. That keeps it engine-side (the UI deriving "your
strength is braking" from scores would be the UI computing a measurement,
which the binding render rule forbids) while adding no new kind of number.

Three rules keep it honest, each learned from the real corpus:

1. **The verdict pool is MEASURED only.** `vehicle_management` scores 0.0 off
   a single proxy component — three of its four techniques have no telemetry
   signal at all. Ranked naively it is the driver's "greatest weakness", which
   would headline the least-supported number in the system. Proxies stay in
   the ordering, marked, and never in the verdict slots.

2. **Rank, never an absolute band.** The 0-100 scores are not calibrated
   against any driver population, so "your braking is strong" would be
   asserted rather than earned. "Braking is your strongest" is a statement
   about this driver's own numbers and cannot be wrong. (Owner decision,
   2026-08-16; revisit only if a calibration corpus ever exists.)

3. **A gate that fails says why.** Too few scored fundamentals, or too little
   separation between top and bottom, produces a stated reason and no
   verdict — never a shrugged one.
"""

from __future__ import annotations

from typing import Any

from driverdna.config import DriverDNAConfig

READING_VERSION = "read-v1"


def _entry(belief) -> dict[str, Any]:
    """One ranked fundamental. `basis_reason` travels with it so a narrow
    basis is disclosed at the moment the fundamental is named, not a click
    away — `consistency` is named this corpus's weakness on one component of
    three, and the driver should see that in the same breath."""
    return {
        "fundamental": belief.fundamental,
        "score": belief.score,
        "confidence": belief.confidence,
        "signal_status": belief.signal_status.value,
        "evidence_count": belief.evidence_count,
        "basis_reason": belief.basis_reason,
    }


def _result(ordered, *, strongest=None, weakest=None, reason=None, pool=()) -> dict[str, Any]:
    return {
        "reading_version": READING_VERSION,
        "basis": "rank_within_driver",
        "strongest": _entry(strongest) if strongest else None,
        "weakest": _entry(weakest) if weakest else None,
        "separation_points": (
            round(strongest.score - weakest.score, 2) if strongest and weakest else None
        ),
        "ordering": [_entry(b) for b in ordered],
        "verdict_reason": reason,
        # The verdict is qualified by the confidence of the beliefs behind
        # it, never suppressed for low confidence — 60% is this corpus's
        # ceiling, and suppressing there would mean the feature never fires.
        "min_confidence": min((b.confidence for b in pool), default=None),
        "excluded_proxy": [
            b.fundamental for b in ordered if b.signal_status.value == "proxy"
        ],
    }


def build_reading(
    beliefs: dict[str, Any], config: DriverDNAConfig
) -> dict[str, Any]:
    """Rank `beliefs` and name a strongest and weakest, or state why not.

    Deterministic: ordered by descending score then fundamental id, so a tie
    resolves by name and two runs over the same beliefs are byte-identical.
    """
    ordered = sorted(
        (b for b in beliefs.values() if b.score is not None),
        key=lambda b: (-b.score, b.fundamental),
    )
    pool = [b for b in ordered if b.signal_status.value == "measured"]

    floor = config.model.reading_min_scored
    if len(pool) < floor:
        return _result(ordered, reason=(
            f"insufficient data: {len(pool)} measured fundamental(s) scored "
            f"< minimum {floor}"
        ))

    strongest, weakest = pool[0], pool[-1]
    separation = strongest.score - weakest.score
    if separation < config.model.reading_min_separation:
        return _result(ordered, reason=(
            f"no clear separation: {separation:.1f} points between the highest "
            f"and lowest measured fundamental < minimum "
            f"{config.model.reading_min_separation}"
        ))

    return _result(ordered, strongest=strongest, weakest=weakest, pool=pool)
