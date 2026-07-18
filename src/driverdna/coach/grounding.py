"""Numeric-claim validation — shared by coach (M4) and chat (M5).

The mechanical half of the grounding contract: any number-with-unit in
model prose must exist in the supplied payload (within a tight tolerance),
otherwise the response is rejected. Bare integers ("3 drills") are not
checked — units are what turn a number into a measurement claim.

Honest caveat, by design: mechanical enforcement of natural language is
approximate; the tests define exactly which violations are guaranteed
caught, and that set is the contract.
"""

from __future__ import annotations

import re
from typing import Any

_CLAIM = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(s\b|sec\b|seconds\b|km/h|kmh\b|deg\b|°|m/s\b|%)",
    re.IGNORECASE,
)


def numeric_claims(text: str) -> list[tuple[float, str]]:
    return [(float(m.group(1)), m.group(2).lower()) for m in _CLAIM.finditer(text)]


def number_pool(obj: Any, pool: set[float] | None = None) -> set[float]:
    """Every numeric value present in the payload (recursive)."""
    if pool is None:
        pool = set()
    if isinstance(obj, bool):
        return pool
    if isinstance(obj, (int, float)):
        pool.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            number_pool(v, pool)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            number_pool(v, pool)
    return pool


def _matches(claim: float, pool: set[float]) -> bool:
    tolerance = abs(claim) * 0.005 + 0.006
    return any(abs(claim - v) <= tolerance for v in pool)


def unsupported_claims(text: str, pool: set[float]) -> list[str]:
    """Claims in `text` that no payload number supports."""
    violations = []
    for value, unit in numeric_claims(text):
        if not _matches(value, pool):
            violations.append(f"{value} {unit}")
    return violations
