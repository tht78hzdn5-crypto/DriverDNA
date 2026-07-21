"""Ranker and findings: vs-self, vs-principle, vs-reference — never blended (M3).

Every finding carries N, spread, source tag, evidence IDs (obs:<pk> rows the
number stands on), and its gate status. A finding below its confidence gate
is still produced — marked suppressed with the reason stated — because
"insufficient data" is an answer, not an omission.

vs-self (the primary practice signal): laps split into faster/slower
terciles by lap time; opportunity = median phase-time difference between
terciles; repeatability = fraction of sessions (with >= 2 laps) whose
within-session faster/slower-half difference keeps the overall sign; ranked
by opportunity x repeatability, both factors always reported.

vs-principle: a detector becomes a finding when it triggers on enough of a
corner's laps (detectors flag form; they are never priced in seconds).

vs-reference: self vs reference envelope, labeled "gap to reference" —
context, never "recoverable time".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from driverdna.attribution.engine import (
    PHASES,
    PhaseWindows,
    baseline,
    reference_envelope,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database


@dataclass(frozen=True)
class Finding:
    finding_id: str  # deterministic; annotations and chat cite this
    source: str  # vs-self | vs-principle | vs-reference
    car: str
    track: str
    corner_id: str
    phase: str | None
    kind: str
    description: str
    seconds: float | None  # priced quantity where applicable
    n: int
    spread: float | None
    evidence_ids: tuple[str, ...]
    shown: bool  # False = suppressed by a confidence gate
    gate_reason: str | None  # stated whenever suppressed
    details: dict[str, Any] = field(default_factory=dict)


def _finding_id(source: str, car: str, track: str, corner: str, phase: str | None, kind: str) -> str:
    return ":".join([source, car, track, corner, phase or "-", kind]).replace(" ", "_")


def _gate(
    n_samples: int, n_sessions: int, config: DriverDNAConfig
) -> tuple[bool, str | None]:
    g = config.gates
    if n_samples < g.min_phase_samples:
        return False, f"insufficient data: {n_samples} phase samples < {g.min_phase_samples}"
    if n_sessions < g.min_sessions:
        return False, f"insufficient data: {n_sessions} session(s) < {g.min_sessions}"
    return True, None


def _sessions_of(history: list[dict]) -> int:
    return len({h["session_key"] for h in history if h["session_key"] is not None})


def _evidence(history: list[dict]) -> tuple[str, ...]:
    return tuple(f"obs:{h['obs_pk']}" for h in history)


def vs_self_findings(
    db: Database, *, driver: str, car: str, track: str,
    windows_by_corner: dict[str, PhaseWindows], config: DriverDNAConfig,
) -> list[Finding]:
    laps = db.conn.execute(
        """SELECT lap_pk, duration_s, session_key FROM laps
           WHERE role='self' AND driver=? AND car=? AND track=?
           ORDER BY duration_s""",
        (driver, car, track),
    ).fetchall()
    n_laps = len(laps)
    third = max(1, n_laps // 3)
    fast_laps = {r["lap_pk"] for r in laps[:third]}
    slow_laps = {r["lap_pk"] for r in laps[-third:]} if n_laps >= 2 else set()
    session_of = {r["lap_pk"]: r["session_key"] for r in laps}
    duration_of = {r["lap_pk"]: r["duration_s"] for r in laps}

    findings: list[Finding] = []
    for corner_id, windows in sorted(windows_by_corner.items()):
        for phase in PHASES:
            if windows.window(phase) is None:
                continue
            history = db.phase_history(
                car=car, track=track, corner_id=corner_id, phase=phase,
                role="self", driver=driver,
            )
            if not history:
                continue
            fast = [h["time_s"] for h in history if h["lap_pk"] in fast_laps]
            slow = [h["time_s"] for h in history if h["lap_pk"] in slow_laps]
            opportunity = (
                float(np.median(slow) - np.median(fast)) if fast and slow and n_laps >= 3 else None
            )
            repeatability = _repeatability(history, session_of, duration_of, opportunity)

            n_samples = len(history)
            n_sessions = _sessions_of(history)
            shown, reason = _gate(n_samples, n_sessions, config)
            if shown and (opportunity is None or opportunity < config.attribution.min_effect_s):
                shown, reason = False, (
                    "no effect: faster and slower laps do not differ here"
                    if opportunity is not None
                    else "insufficient data: too few laps for tercile split"
                )
            score = (
                opportunity * repeatability
                if opportunity is not None and repeatability is not None
                else None
            )
            spread = float(np.std([h["time_s"] for h in history], ddof=1)) if n_samples > 1 else 0.0
            findings.append(
                Finding(
                    finding_id=_finding_id("vs-self", car, track, corner_id, phase, "opportunity"),
                    source="vs-self",
                    car=car, track=track, corner_id=corner_id, phase=phase,
                    kind="opportunity",
                    description=(
                        f"{corner_id} {phase}: slower laps lose "
                        f"{opportunity:.3f} s here vs faster laps"
                        if opportunity is not None
                        else f"{corner_id} {phase}: insufficient laps to compare"
                    ),
                    seconds=opportunity,
                    n=n_samples,
                    spread=spread,
                    evidence_ids=_evidence(history),
                    shown=shown,
                    gate_reason=reason,
                    details={
                        "opportunity_s": opportunity,
                        "repeatability": repeatability,
                        "rank_score": score,
                        "n_sessions": n_sessions,
                    },
                )
            )
    return findings


def _repeatability(
    history: list[dict],
    session_of: dict[int, str | None],
    duration_of: dict[int, float],
    overall_opportunity: float | None,
) -> float | None:
    """Fraction of sessions (>= 2 laps) whose within-session faster/slower
    half difference keeps the sign of the overall opportunity."""
    if overall_opportunity is None or overall_opportunity == 0:
        return None
    by_session: dict[str, list[dict]] = {}
    for h in history:
        key = session_of.get(h["lap_pk"])
        if key is not None:
            by_session.setdefault(key, []).append(h)
    agreements = []
    for entries in by_session.values():
        laps = sorted({e["lap_pk"] for e in entries}, key=lambda pk: duration_of[pk])
        if len(laps) < 2:
            continue
        half = len(laps) // 2
        fast_set, slow_set = set(laps[:half]), set(laps[-half:])
        fast = [e["time_s"] for e in entries if e["lap_pk"] in fast_set]
        slow = [e["time_s"] for e in entries if e["lap_pk"] in slow_set]
        if not fast or not slow:
            continue
        diff = float(np.median(slow) - np.median(fast))
        agreements.append(np.sign(diff) == np.sign(overall_opportunity))
    if not agreements:
        return None
    return float(np.mean(agreements))


def vs_principle_findings(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig
) -> list[Finding]:
    table = db.self_detector_table(driver=driver, car=car, track=track)
    findings: list[Finding] = []
    for corner_id in sorted(table):
        for detector, (triggered, total) in sorted(table[corner_id].items()):
            rate = triggered / total if total else 0.0
            rows = db.conn.execute(
                """SELECT d.obs_pk, d.rationale FROM detector_results d
                   JOIN corner_observations o ON o.obs_pk = d.obs_pk
                   JOIN corners c ON c.corner_pk = o.corner_pk
                   JOIN laps l ON l.lap_pk = o.lap_pk
                   WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
                     AND c.corner_id=? AND d.detector=? AND d.triggered=1
                   ORDER BY d.obs_pk""",
                (driver, car, track, corner_id, detector),
            ).fetchall()
            sessions = db.conn.execute(
                """SELECT COUNT(DISTINCT l.session_key) n FROM detector_results d
                   JOIN corner_observations o ON o.obs_pk = d.obs_pk
                   JOIN corners c ON c.corner_pk = o.corner_pk
                   JOIN laps l ON l.lap_pk = o.lap_pk
                   WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
                     AND c.corner_id=? AND d.detector=? AND l.session_key IS NOT NULL""",
                (driver, car, track, corner_id, detector),
            ).fetchone()["n"]
            shown, reason = _gate(total, int(sessions), config)
            if shown and rate < config.detectors.min_trigger_rate:
                shown, reason = False, (
                    f"below pattern floor: triggers on {triggered}/{total} laps"
                )
            rationale = rows[0]["rationale"] if rows else ""
            findings.append(
                Finding(
                    finding_id=_finding_id("vs-principle", car, track, corner_id, None, detector),
                    source="vs-principle",
                    car=car, track=track, corner_id=corner_id, phase=None,
                    kind=detector,
                    description=f"{corner_id}: {detector} on {triggered}/{total} laps. {rationale}",
                    seconds=None,  # detectors flag form; they are never priced
                    n=total,
                    spread=None,
                    evidence_ids=tuple(f"obs:{r['obs_pk']}" for r in rows),
                    shown=shown,
                    gate_reason=reason,
                    details={"trigger_rate": rate, "triggered": triggered},
                )
            )
    return findings


def vs_reference_findings(
    db: Database, *, driver: str, car: str, track: str,
    windows_by_corner: dict[str, PhaseWindows], config: DriverDNAConfig,
) -> list[Finding]:
    findings: list[Finding] = []
    for corner_id, windows in sorted(windows_by_corner.items()):
        for phase in PHASES:
            if windows.window(phase) is None:
                continue
            ref = db.phase_history(
                car=car, track=track, corner_id=corner_id, phase=phase, role="reference"
            )
            envelope = reference_envelope([h["time_s"] for h in ref])
            if envelope is None:
                continue
            history = db.phase_history(
                car=car, track=track, corner_id=corner_id, phase=phase,
                role="self", driver=driver,
            )
            base = baseline([h["time_s"] for h in history], config.attribution)
            if base is None:
                continue
            gap_median = base.median_s - envelope.median_s
            gap_best = base.single_best_s - envelope.best_s
            n_samples = len(history)
            n_sessions = _sessions_of(history)
            shown, reason = _gate(n_samples, n_sessions, config)
            findings.append(
                Finding(
                    finding_id=_finding_id("vs-reference", car, track, corner_id, phase, "gap"),
                    source="vs-reference",
                    car=car, track=track, corner_id=corner_id, phase=phase,
                    kind="gap",
                    description=(
                        f"{corner_id} {phase}: gap to reference {gap_median:+.3f} s "
                        f"(typical vs typical; best vs best {gap_best:+.3f} s). "
                        "Gap is context, not recoverable time."
                    ),
                    seconds=gap_median,
                    n=n_samples,
                    spread=base.spread_s,
                    evidence_ids=_evidence(history) + _evidence(ref),
                    shown=shown,
                    gate_reason=reason,
                    details={
                        "gap_median_s": gap_median,
                        "gap_best_s": gap_best,
                        "reference_n": envelope.n,
                    },
                )
            )
    return findings


def cumulative_loss(
    db: Database, *, driver: str, car: str, track: str,
    windows_by_corner: dict[str, PhaseWindows], config: DriverDNAConfig,
    lap_pks: frozenset[int] | None = None,
) -> dict[str, Any]:
    """Median per-lap seconds lost vs the robust baseline, per corner/phase,
    rolled up by phase and by corner class. Phase is the technique-area tag
    for priced loss in v1 (detector findings carry form, unpriced).

    `per_corner_phase_n` carries the sample size (post outlier-screening
    baseline, pre-screening history count) behind each corner/phase loss
    figure — M6b's opportunity component needs it to weight/gate a
    fundamental's evidence_count without re-querying phase_history itself.

    `lap_pks` (M6 trend only) restricts the history to a date-bucket's laps;
    the robust baseline is then that bucket's own best — an intentionally
    era-relative reference (see model/scoring.py's _trend caveat).
    """
    classes = db.corner_classes(car=car, track=track)
    per_corner: dict[str, dict[str, float]] = {}
    per_corner_phase_n: dict[str, dict[str, int]] = {}
    outlier_counts: dict[str, int] = {}
    for corner_id, windows in sorted(windows_by_corner.items()):
        for phase in PHASES:
            if windows.window(phase) is None:
                continue
            history = db.phase_history(
                car=car, track=track, corner_id=corner_id, phase=phase,
                role="self", driver=driver, lap_pks=lap_pks,
            )
            times = [h["time_s"] for h in history]
            base = baseline(times, config.attribution)
            if base is None:
                continue
            deltas = [t - base.robust_best_s for t in times]
            per_corner.setdefault(corner_id, {})[phase] = float(np.median(deltas))
            per_corner_phase_n.setdefault(corner_id, {})[phase] = len(times)
            if base.n_outliers:
                outlier_counts[f"{corner_id}:{phase}"] = base.n_outliers
    by_phase: dict[str, float] = {}
    by_class: dict[str, float] = {}
    for corner_id, phases in per_corner.items():
        for phase, loss in phases.items():
            by_phase[phase] = by_phase.get(phase, 0.0) + loss
            cls = classes.get(corner_id) or "unclassified"
            by_class[cls] = by_class.get(cls, 0.0) + loss
    return {
        "per_corner": per_corner,
        "per_corner_total": {
            cid: float(sum(phases.values())) for cid, phases in per_corner.items()
        },
        "per_corner_phase_n": per_corner_phase_n,
        "by_phase": by_phase,
        "by_class": by_class,
        "outliers_screened": outlier_counts,
    }
