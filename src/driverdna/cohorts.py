"""Cohort-label drift detection (SPEC.md A27).

`car` and `track` are cohort keys. Everything longitudinal — baselines, the
vs-self ranker, M6 trend, consistency — is computed per cohort, so two labels
for one real cohort silently halve the evidence behind every number, without
producing a single error. This module finds label pairs that look like the
same cohort spelled two ways.

It reports; it never merges. Which of two labels is correct, or whether they
are genuinely different track configurations, is not something the engine can
know from the strings alone — and a cohort key is load-bearing for evidence
IDs, so guessing wrong would be worse than saying nothing. "Insufficient data
over guessing" applies to metadata exactly as it does to measurements.

The motivating case is real and structural, not hypothetical: `sync` builds
its track label from the API's own `name` + `variant`
(`garage61/sync.py:_track_label` -> "Summit Point Raceway (Shenandoah)"),
while a manual import takes whatever the export filename states, which carries
no variant at all ("Summit Point Raceway"). A driver who does both — which is
the documented workflow, since the API returns only one lap per cohort — gets
two cohorts for one car and track.

Deliberately NOT flagged: two labels with *different* parenthesised variants.
"Track variants are distinct cohorts" is the spec's own rule, so
"Summit Point (Shenandoah)" vs "Summit Point (Main)" is correct behavior, not
drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A trailing parenthesised qualifier — the API's track `variant`.
_VARIANT_RE = re.compile(r"^(?P<base>.*?)\s*\((?P<variant>[^()]*)\)\s*$")


def _canon(label: str) -> str:
    """Case- and punctuation-insensitive form, for comparison only.

    Never stored, never shown as a label, and never used as a cohort key —
    collapsing "Spa-Francorchamps" and "Spa Francorchamps" is exactly the
    kind of guess that must not reach the data itself.
    """
    return " ".join(re.sub(r"[^a-z0-9]+", " ", label.casefold()).split())


def _split_variant(label: str) -> tuple[str, str | None]:
    m = _VARIANT_RE.match(label)
    return (m.group("base"), m.group("variant")) if m else (label, None)


def _similarity(a: str, b: str) -> str | None:
    """Why two labels look like one thing spelled twice, or None."""
    if a == b:
        return None
    if _canon(a) == _canon(b):
        return "differ only by case or punctuation"
    base_a, var_a = _split_variant(a)
    base_b, var_b = _split_variant(b)
    if _canon(base_a) == _canon(base_b) and (var_a is None) != (var_b is None):
        # The sync-vs-import signature. Two *different* variants are left
        # alone: distinct configurations are distinct cohorts by design.
        return "one names a variant/configuration and the other does not"
    return None


@dataclass(frozen=True)
class DriftPair:
    """Two cohorts of one driver that look like the same real cohort."""

    driver: str
    left: tuple[str, str]  # (car, track)
    right: tuple[str, str]
    car_reason: str | None
    track_reason: str | None

    def describe(self) -> str:
        parts = []
        if self.car_reason:
            parts.append(f"car labels {self.car_reason}")
        if self.track_reason:
            parts.append(f"track labels {self.track_reason}")
        return "; ".join(parts)


def find_label_drift(cohorts: list[dict[str, str]]) -> list[DriftPair]:
    """Cohort pairs that look like one cohort under two labels.

    `cohorts` is what `report.payload.list_cohorts` returns: dicts carrying
    `driver`, `car`, `track`. Output is deterministically ordered.
    """
    keyed = sorted(
        {(c["driver"], c["car"], c["track"]) for c in cohorts}
    )
    pairs: list[DriftPair] = []
    for i, (driver_a, car_a, track_a) in enumerate(keyed):
        for driver_b, car_b, track_b in keyed[i + 1:]:
            if driver_a != driver_b:
                continue
            car_reason = _similarity(car_a, car_b)
            track_reason = _similarity(track_a, track_b)
            # Each axis must be either identical or suspiciously similar; a
            # genuinely different car is a genuinely different cohort.
            if car_a != car_b and car_reason is None:
                continue
            if track_a != track_b and track_reason is None:
                continue
            if car_reason is None and track_reason is None:
                continue  # identical on both axes: not two cohorts at all
            pairs.append(DriftPair(
                driver=driver_a,
                left=(car_a, track_a),
                right=(car_b, track_b),
                car_reason=car_reason,
                track_reason=track_reason,
            ))
    return pairs
