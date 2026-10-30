"""Stage 2 (docs/SPEC.md A59): fixed eras, frozen era summaries, and the
persisted tendency projection.

Stage 1 annotated rollup patterns with era states computed from A36's
re-cut date buckets. Stage 2 replaces that with fixed eras:

- Eras are lap blocks of a per-driver size (config default 500 laps),
  assigned in (lap_date, lap_pk) order, set once, never re-cut. A new era
  starts only when the previous one fills; the open era is created lazily
  on the first lap that needs it, so no empty era ever exists.
- When an era fills it closes: a frozen summary is computed once, from
  that era's laps alone, and stored. Tendency computation reads summaries
  for closed eras and computes only the open era live — it never
  reprocesses old laps.
- Era size changes apply at the next era boundary: closed eras keep the
  size they were built with, and the open era keeps its creation size.
- Backdated laps (dated before closed eras) cannot join a frozen era;
  they land in the open era. Closed-era membership is append-only.
- `driver_tendencies` persists the projection, versioned by
  TENDENCY_MODEL_VERSION, with one deliberate departure from
  `driver_beliefs`: it stores the projection AND `first_seen`. Beliefs
  upsert away history; tendencies must not — an upsert preserves the
  existing `first_seen_era`.

Raw laps are never deleted here (A59 leaves the retention tier
undecided); summaries are computed from era laps, and the laps stay.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from driverdna.coaching.engine import (
    _BAND_RANK,
    eligible_principles,
    eligible_strengths,
)
from driverdna.coaching.ontology import PRINCIPLES, tendency_variant
from driverdna.config import DriverDNAConfig
from driverdna.db import Database

TENDENCY_MODEL_VERSION = "tendency-v2"


@dataclass(frozen=True)
class EraPrincipleRecord:
    """One principle's era fact, from a frozen summary (closed era) or
    live computation (open era). `evaluated` means the era had at least
    one cohort with enough laps for gates to run (see
    `_compute_era_summary`); a principle in an unevaluated era carries
    no signal either way."""

    fired: bool
    band: str | None  # loudest gap band this era, None if not fired
    band_rank: int | None
    strength: bool  # showed as a strength this era
    evaluated: bool


@dataclass(frozen=True)
class TendencyOutcome:
    state: str | None
    eras_fired: int
    eras_total: int
    first_seen_era: int | None
    last_seen_era: int | None
    clearing_streak: int  # trailing clearing eras (fault) / trailing
    # non-strength eras (strength); 0 when the latest era fires/clears
    band_before: str | None  # band two eras ago (improving/regression)
    current_band: str | None  # band in the latest era, if fired


def _is_clearing(record: EraPrincipleRecord) -> bool:
    """A clearing era: the principle did not fire, and either showed as
    a strength or was evaluated below its gate. An unevaluated era is
    not clearing — absence of evidence is not evidence of a fix."""
    return not record.fired and (record.strength or record.evaluated)


def _none_outcome(eras_total: int) -> TendencyOutcome:
    return TendencyOutcome(
        state=None, eras_fired=0, eras_total=eras_total,
        first_seen_era=None, last_seen_era=None, clearing_streak=0,
        band_before=None, current_band=None,
    )


def fault_tendency_state(
    records: list[EraPrincipleRecord], *, persistent_min_share: float,
    resolved_min_eras: int,
) -> TendencyOutcome:
    """The Stage 2 fault partition (A59), exclusive, in precedence order.

    Trailing thin eras (not fired, not clearing) are stripped first —
    they carry no signal, so the state is decided over substantive eras
    while `eras_total` still counts every era. Then: a trailing run of
    clearing eras gives `resolved` at >= K or `dormant` below it; a fired
    latest era with three consecutive fired eras gives `improving` (band
    down a full rank from two eras ago, held) or `regression` (the
    mirror); otherwise `new` (fired only in the latest era),
    `persistent` (share >= threshold), or `recurring`.
    """
    eras_total = len(records)
    substantive = records
    while substantive and not substantive[-1].fired \
            and not _is_clearing(substantive[-1]):
        substantive = substantive[:-1]
    fired_idx = [i for i, r in enumerate(substantive) if r.fired]
    if not fired_idx:
        return _none_outcome(eras_total)
    latest = len(substantive) - 1
    streak = 0
    i = latest
    while i >= 0 and _is_clearing(substantive[i]):
        streak += 1
        i -= 1
    first_seen, last_seen = fired_idx[0], fired_idx[-1]
    current_band = substantive[latest].band if substantive[latest].fired else None
    if streak > 0:
        state = "resolved" if streak >= resolved_min_eras else "dormant"
        return TendencyOutcome(
            state=state, eras_fired=len(fired_idx), eras_total=eras_total,
            first_seen_era=first_seen, last_seen_era=last_seen,
            clearing_streak=streak, band_before=None, current_band=None,
        )
    # Latest substantive era fired (anything else was stripped above).
    band_before: str | None = None
    if len(substantive) >= 3:
        r2, r1, r0 = substantive[-3], substantive[-2], substantive[-1]
        if r2.fired and r1.fired and r0.fired \
                and r2.band_rank is not None \
                and r1.band_rank is not None \
                and r0.band_rank is not None:
            band_before = r2.band
            trend_state: str | None = None
            if r1.band_rank <= r2.band_rank - 1 \
                    and r0.band_rank <= r2.band_rank - 1:
                trend_state = "improving"
            elif r1.band_rank >= r2.band_rank + 1 \
                    and r0.band_rank >= r2.band_rank + 1:
                trend_state = "regression"
            if trend_state is not None:
                return TendencyOutcome(
                    state=trend_state, eras_fired=len(fired_idx),
                    eras_total=eras_total, first_seen_era=first_seen,
                    last_seen_era=last_seen, clearing_streak=0,
                    band_before=band_before, current_band=current_band,
                )
    if fired_idx == [latest]:
        state = "new"
    elif len(fired_idx) / eras_total >= persistent_min_share:
        state = "persistent"
    else:
        state = "recurring"
    return TendencyOutcome(
        state=state, eras_fired=len(fired_idx), eras_total=eras_total,
        first_seen_era=first_seen, last_seen_era=last_seen,
        clearing_streak=0, band_before=None, current_band=current_band,
    )


def strength_tendency_state(
    records: list[EraPrincipleRecord], *, persistent_min_share: float,
) -> TendencyOutcome:
    """The strength partition (A59): same share rule as faults, with
    `lapsed` in place of dormant/resolved — a strength that cleared
    before but not in the most recent substantive era. Trailing thin
    eras (neither strength nor evaluated) are stripped first."""
    eras_total = len(records)
    substantive = records
    while substantive and not substantive[-1].strength \
            and not substantive[-1].evaluated:
        substantive = substantive[:-1]
    strength_idx = [i for i, r in enumerate(substantive) if r.strength]
    if not strength_idx:
        return _none_outcome(eras_total)
    latest = len(substantive) - 1
    streak = 0
    i = latest
    while i >= 0 and not substantive[i].strength:
        streak += 1
        i -= 1
    first_seen, last_seen = strength_idx[0], strength_idx[-1]
    if streak > 0:
        state = "lapsed"
    elif strength_idx == [latest]:
        state = "new"
    elif len(strength_idx) / eras_total >= persistent_min_share:
        state = "persistent"
    else:
        state = "recurring"
    return TendencyOutcome(
        state=state, eras_fired=len(strength_idx), eras_total=eras_total,
        first_seen_era=first_seen, last_seen_era=last_seen,
        clearing_streak=streak, band_before=None, current_band=None,
    )


# --- per-driver era size ---------------------------------------------------


def get_era_size(db: Database, driver: str, config: DriverDNAConfig) -> int:
    """The driver's era size: their settings row, else the config
    default. The setting sizes only eras created after it is set."""
    row = db.conn.execute(
        "SELECT era_size_laps FROM driver_tendency_settings"
        " WHERE owner_user_pk=? AND driver=?",
        (db.user_pk, driver),
    ).fetchone()
    if row is not None:
        return int(row["era_size_laps"])
    return int(config.coaching.tendency_era_size_laps)


def set_era_size(db: Database, driver: str, size: int) -> None:
    """Upsert a driver's era size. Applies at the next era boundary;
    closed eras and the open era keep their creation sizes."""
    if size < 1:
        raise ValueError(f"era size must be >= 1, got {size}")
    with db.conn:
        db.conn.execute(
            "INSERT INTO driver_tendency_settings"
            " (owner_user_pk, driver, era_size_laps) VALUES (?, ?, ?)"
            " ON CONFLICT(owner_user_pk, driver) DO UPDATE"
            " SET era_size_laps=excluded.era_size_laps",
            (db.user_pk, driver, size),
        )


# --- era storage -------------------------------------------------------------


def _era_rows(db: Database, driver: str) -> list[dict[str, Any]]:
    rows = db.conn.execute(
        "SELECT era_index, era_size_laps, status, summary_json"
        " FROM tendency_eras WHERE owner_user_pk=? AND driver=?"
        " ORDER BY era_index",
        (db.user_pk, driver),
    ).fetchall()
    return [
        {
            "era_index": int(r["era_index"]),
            "era_size_laps": int(r["era_size_laps"]),
            "status": str(r["status"]),
            "summary": json.loads(r["summary_json"])
            if r["summary_json"] is not None else None,
        }
        for r in rows
    ]


def _era_lap_pks(db: Database, driver: str, era_index: int) -> frozenset[int]:
    rows = db.conn.execute(
        "SELECT lap_pk FROM tendency_era_laps"
        " WHERE owner_user_pk=? AND driver=? AND era_index=?",
        (db.user_pk, driver, era_index),
    ).fetchall()
    return frozenset(int(r["lap_pk"]) for r in rows)


def _lap_cohorts(db: Database, driver: str) -> dict[int, tuple[str, str]]:
    """lap_pk -> (car, track) for the driver's self laps, one query."""
    rows = db.conn.execute(
        "SELECT lap_pk, car, track FROM laps"
        " WHERE role='self' AND driver=? AND owner_user_pk=?",
        (driver, db.user_pk),
    ).fetchall()
    return {int(r["lap_pk"]): (str(r["car"]), str(r["track"])) for r in rows}


def _compute_era_summary(
    db: Database, *, driver: str, era_lap_pks: frozenset[int],
    lap_cohorts: dict[int, tuple[str, str]], config: DriverDNAConfig,
) -> dict[str, Any]:
    """One era's frozen summary, from that era's laps alone: per
    principle, fired, loudest band in the principle's own magnitude_kind,
    strength side, cohorts and corners where it fired, evidence
    references. `evaluated` is era-level — any cohort with at least
    `gates.min_phase_samples` laps — the same floor the eligibility
    machinery needs before a finding can be shown; a principle in an
    era with no such cohort is thin, not clearing. This errs toward
    clearing only in the narrow case where a cohort is large enough for
    some gates but not the specific data one principle's gate needs;
    the K-consecutive requirement bounds that over-claim."""
    by_cohort: dict[tuple[str, str], list[int]] = {}
    for lap_pk in sorted(era_lap_pks):
        cohort = lap_cohorts.get(lap_pk)
        if cohort is not None:
            by_cohort.setdefault(cohort, []).append(lap_pk)
    evaluated = any(
        len(pks) >= config.gates.min_phase_samples
        for pks in by_cohort.values()
    )
    principles: dict[str, dict[str, Any]] = {}
    for (car, track), pks in sorted(by_cohort.items()):
        cohort_pks = frozenset(pks)
        candidates = eligible_principles(
            db, driver=driver, car=car, track=track, config=config,
            lap_pks=cohort_pks,
        )
        strengths = eligible_strengths(
            db, driver=driver, car=car, track=track, config=config,
            lap_pks=cohort_pks,
        )
        for cand in candidates:
            if cand.signal_status.value == "no_signal":
                continue
            entry = principles.setdefault(cand.principle_id, {
                "fired": False, "band": None, "magnitude_kind": None,
                "strength": False, "evaluated": evaluated,
                "fault_cohorts": set(), "fault_corners": set(),
                "strength_cohorts": set(), "strength_corners": set(),
                "evidence": set(), "strength_evidence": set(),
            })
            entry["fired"] = True
            rank = _BAND_RANK.get(cand.gap_band or "", -1)
            current_rank = _BAND_RANK.get(entry["band"] or "", -1) \
                if entry["band"] else -2
            if rank > current_rank:
                entry["band"] = cand.gap_band
                entry["magnitude_kind"] = cand.magnitude_kind
            if cand.corner_id is not None:
                entry["fault_corners"].add(cand.corner_id)
            entry["fault_cohorts"].add((car, track))
            entry["evidence"].update(cand.evidence_ids)
        for strength in strengths:
            entry = principles.setdefault(strength.principle_id, {
                "fired": False, "band": None, "magnitude_kind": None,
                "strength": False, "evaluated": evaluated,
                "fault_cohorts": set(), "fault_corners": set(),
                "strength_cohorts": set(), "strength_corners": set(),
                "evidence": set(), "strength_evidence": set(),
            })
            entry["strength"] = True
            if strength.corner_id is not None:
                entry["strength_corners"].add(strength.corner_id)
            entry["strength_cohorts"].add((car, track))
            entry["strength_evidence"].update(strength.evidence_ids)
    return {
        "principles": {
            pid: {
                "fired": entry["fired"],
                "band": entry["band"],
                "magnitude_kind": entry["magnitude_kind"],
                "strength": entry["strength"],
                "evaluated": entry["evaluated"],
                "fault_cohorts": sorted(
                    [list(c) for c in entry["fault_cohorts"]]),
                "fault_corners": sorted(entry["fault_corners"]),
                "strength_cohorts": sorted(
                    [list(c) for c in entry["strength_cohorts"]]),
                "strength_corners": sorted(entry["strength_corners"]),
                "evidence": sorted(entry["evidence"]),
                "strength_evidence": sorted(entry["strength_evidence"]),
            }
            for pid, entry in sorted(principles.items())
        },
    }


def era_count(db: Database, driver: str) -> int:
    """Number of eras for a driver. Eras are never empty (the open era
    is created lazily on its first lap) and never deleted, so this is
    also the `eras_total` the rollup reports."""
    row = db.conn.execute(
        "SELECT COUNT(*) AS n FROM tendency_eras"
        " WHERE owner_user_pk=? AND driver=?",
        (db.user_pk, driver),
    ).fetchone()
    return int(row["n"])


def refresh_eras(
    db: Database, driver: str, config: DriverDNAConfig,
) -> list[dict[str, Any]]:
    """Assign unassigned dated laps to eras (append-only, in
    (lap_date, lap_pk) order), closing eras as they fill with a frozen
    summary each. Returns every era with membership and summary
    (None for the open era). Idempotent: a second call with no new laps
    writes nothing and returns the same eras."""
    setting_size = get_era_size(db, driver, config)
    dated = db.dated_self_laps(driver)
    assigned = {
        int(r["lap_pk"]) for r in db.conn.execute(
            "SELECT lap_pk FROM tendency_era_laps"
            " WHERE owner_user_pk=? AND driver=?",
            (db.user_pk, driver),
        ).fetchall()
    }
    unassigned = [pk for pk, _ in dated if pk not in assigned]
    rows = _era_rows(db, driver)
    open_era = next((r for r in rows if r["status"] == "open"), None)
    next_index = (max((r["era_index"] for r in rows), default=-1) + 1)
    counts: dict[int, int] = {
        r["era_index"]: len(_era_lap_pks(db, driver, r["era_index"]))
        for r in rows
    }
    lap_cohorts = _lap_cohorts(db, driver)
    with db.conn:
        for lap_pk in unassigned:
            if open_era is None:
                open_era = {
                    "era_index": next_index,
                    "era_size_laps": setting_size,
                    "status": "open",
                    "summary": None,
                }
                db.conn.execute(
                    "INSERT INTO tendency_eras (owner_user_pk, driver,"
                    " era_index, era_size_laps, status, summary_json)"
                    " VALUES (?, ?, ?, ?, 'open', NULL)",
                    (db.user_pk, driver, next_index, setting_size),
                )
                counts[next_index] = 0
                next_index += 1
            era_index = open_era["era_index"]
            db.conn.execute(
                "INSERT INTO tendency_era_laps"
                " (owner_user_pk, driver, era_index, lap_pk)"
                " VALUES (?, ?, ?, ?)",
                (db.user_pk, driver, era_index, lap_pk),
            )
            counts[era_index] += 1
            if counts[era_index] >= open_era["era_size_laps"]:
                member_pks = _era_lap_pks(db, driver, era_index)
                summary = _compute_era_summary(
                    db, driver=driver, era_lap_pks=member_pks,
                    lap_cohorts=lap_cohorts, config=config,
                )
                db.conn.execute(
                    "UPDATE tendency_eras SET status='closed',"
                    " summary_json=? WHERE owner_user_pk=? AND driver=?"
                    " AND era_index=?",
                    (json.dumps(summary, sort_keys=True),
                     db.user_pk, driver, era_index),
                )
                open_era = None
    eras = _era_rows(db, driver)
    for era in eras:
        era["lap_pks"] = _era_lap_pks(db, driver, era["era_index"])
        era["n_laps"] = len(era["lap_pks"])
    return eras


# --- the persisted projection -------------------------------------------------


def _era_records(
    eras: list[dict[str, Any]], summaries: dict[int, dict[str, Any]],
) -> dict[str, list[EraPrincipleRecord]]:
    """Per-principle era records from per-era summaries (frozen for
    closed eras, live for the open era — the caller computes each once
    and passes them in)."""
    records: dict[str, list[EraPrincipleRecord]] = {
        pid: [] for pid in PRINCIPLES
    }
    for era in eras:
        principles = summaries[era["era_index"]]["principles"]
        for pid in PRINCIPLES:
            entry = principles.get(pid)
            if entry is None:
                records[pid].append(EraPrincipleRecord(
                    fired=False, band=None, band_rank=None,
                    strength=False, evaluated=False,
                ))
            else:
                band = entry["band"]
                records[pid].append(EraPrincipleRecord(
                    fired=bool(entry["fired"]), band=band,
                    band_rank=_BAND_RANK.get(band) if band else None,
                    strength=bool(entry["strength"]),
                    evaluated=bool(entry["evaluated"]),
                ))
    return records


def _row_dict(
    *, principle_id: str, side: str, outcome: TendencyOutcome,
    per_era: dict[str, dict[str, Any]], evidence: dict[str, list[str]],
    computed_at: str | None,
) -> dict[str, Any]:
    principle = PRINCIPLES[principle_id]
    variant = tendency_variant(
        principle, state=outcome.state, eras_fired=outcome.eras_fired,
        eras_total=outcome.eras_total,
        first_seen_era=outcome.first_seen_era,
        last_seen_era=outcome.last_seen_era,
        clearing_streak=outcome.clearing_streak,
    )
    return {
        "principle_id": principle_id,
        "side": side,
        "state": outcome.state,
        "eras_fired": outcome.eras_fired,
        "eras_total": outcome.eras_total,
        "first_seen_era": outcome.first_seen_era,
        "last_seen_era": outcome.last_seen_era,
        "clearing_streak": outcome.clearing_streak,
        "band_before": outcome.band_before,
        "current_band": outcome.current_band,
        "per_era": per_era,
        "evidence": evidence,
        "variant": variant,
        "drill_followup": principle.drill_followup
        if outcome.state == "persistent" else None,
        "tendency_version": TENDENCY_MODEL_VERSION,
        "computed_at": computed_at,
    }


def refresh_tendencies(
    db: Database, driver: str, config: DriverDNAConfig,
) -> list[dict[str, Any]]:
    """Refresh-on-read for the tendency projection: assign and close
    eras, recompute states from summaries plus the open era live, and
    upsert `driver_tendencies` preserving `first_seen_era`. Returns the
    projection rows (same shape as `read_tendencies`)."""
    eras = refresh_eras(db, driver, config)
    if not eras:
        return []
    lap_cohorts = _lap_cohorts(db, driver)
    summaries: dict[int, dict[str, Any]] = {}
    for era in eras:
        if era["status"] == "closed":
            summaries[era["era_index"]] = era["summary"] or {"principles": {}}
        else:
            summaries[era["era_index"]] = _compute_era_summary(
                db, driver=driver, era_lap_pks=era["lap_pks"],
                lap_cohorts=lap_cohorts, config=config,
            )
    records = _era_records(eras, summaries)
    cfg = config.coaching
    computed_at = datetime.now(timezone.utc).isoformat()
    existing = {
        (r["principle_id"], r["side"]): r
        for r in read_tendencies(db, driver)
    }
    rows: list[dict[str, Any]] = []
    with db.conn:
        for principle_id in sorted(PRINCIPLES):
            principle_records = records[principle_id]
            fault = fault_tendency_state(
                principle_records,
                persistent_min_share=cfg.tendency_persistent_min_share,
                resolved_min_eras=cfg.tendency_resolved_min_eras,
            )
            strength = strength_tendency_state(
                principle_records,
                persistent_min_share=cfg.tendency_persistent_min_share,
            )
            for side, outcome in (("fault", fault), ("strength", strength)):
                if outcome.state is None:
                    continue
                per_era: dict[str, dict[str, Any]] = {}
                evidence: dict[str, list[str]] = {}
                evidence_key = "evidence" if side == "fault" \
                    else "strength_evidence"
                for pos, era in enumerate(eras):
                    idx = str(era["era_index"])
                    record = principle_records[pos]
                    entry = summaries[era["era_index"]]["principles"].get(
                        principle_id)
                    if side == "fault":
                        corners = entry.get("fault_corners", []) \
                            if entry else []
                        cohorts = entry.get("fault_cohorts", []) \
                            if entry else []
                    else:
                        corners = entry.get("strength_corners", []) \
                            if entry else []
                        cohorts = entry.get("strength_cohorts", []) \
                            if entry else []
                    per_era[idx] = {
                        "fired": record.fired,
                        "band": record.band,
                        "strength": record.strength,
                        "corners": corners,
                        "cohorts": cohorts,
                        "evidence_count": len(
                            entry[evidence_key]) if entry else 0,
                    }
                    evidence[idx] = sorted(
                        entry[evidence_key]) if entry else []
                previous = existing.get((principle_id, side))
                first_seen = outcome.first_seen_era
                if previous is not None \
                        and previous["first_seen_era"] is not None:
                    first_seen = previous["first_seen_era"]
                row = _row_dict(
                    principle_id=principle_id, side=side, outcome=outcome,
                    per_era=per_era, evidence=evidence,
                    computed_at=computed_at,
                )
                row["first_seen_era"] = first_seen
                db.conn.execute(
                    "INSERT INTO driver_tendencies (owner_user_pk, driver,"
                    " principle_id, side, state, eras_fired, eras_total,"
                    " first_seen_era, last_seen_era, clearing_streak,"
                    " band_before, current_band, per_era_json, evidence_json,"
                    " tendency_version, computed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(owner_user_pk, driver, principle_id, side,"
                    " tendency_version) DO UPDATE SET state=excluded.state,"
                    " eras_fired=excluded.eras_fired,"
                    " eras_total=excluded.eras_total,"
                    " first_seen_era=excluded.first_seen_era,"
                    " last_seen_era=excluded.last_seen_era,"
                    " clearing_streak=excluded.clearing_streak,"
                    " band_before=excluded.band_before,"
                    " current_band=excluded.current_band,"
                    " per_era_json=excluded.per_era_json,"
                    " evidence_json=excluded.evidence_json,"
                    " computed_at=excluded.computed_at",
                    (db.user_pk, driver, principle_id, side, outcome.state,
                     outcome.eras_fired, outcome.eras_total, first_seen,
                     outcome.last_seen_era, outcome.clearing_streak,
                     outcome.band_before, outcome.current_band,
                     json.dumps(per_era, sort_keys=True),
                     json.dumps(evidence, sort_keys=True),
                     TENDENCY_MODEL_VERSION, computed_at),
                )
                rows.append(row)
    return sorted(rows, key=lambda r: (r["principle_id"], r["side"]))


def read_tendencies(db: Database, driver: str) -> list[dict[str, Any]]:
    """The persisted projection rows for a driver, words derived from
    the stored facts (never stored — ontology text stays in the
    ontology). Does not refresh: cohort payloads read the last rollup
    refresh; the driver payload refreshes first."""
    rows = db.conn.execute(
        "SELECT principle_id, side, state, eras_fired, eras_total,"
        " first_seen_era, last_seen_era, clearing_streak, band_before,"
        " current_band, per_era_json, evidence_json, tendency_version,"
        " computed_at FROM driver_tendencies"
        " WHERE owner_user_pk=? AND driver=? AND tendency_version=?"
        " ORDER BY principle_id, side",
        (db.user_pk, driver, TENDENCY_MODEL_VERSION),
    ).fetchall()
    out = []
    for r in rows:
        outcome = TendencyOutcome(
            state=str(r["state"]), eras_fired=int(r["eras_fired"]),
            eras_total=int(r["eras_total"]),
            first_seen_era=r["first_seen_era"],
            last_seen_era=r["last_seen_era"],
            clearing_streak=int(r["clearing_streak"]),
            band_before=r["band_before"], current_band=r["current_band"],
        )
        out.append(_row_dict(
            principle_id=str(r["principle_id"]), side=str(r["side"]),
            outcome=outcome,
            per_era=json.loads(r["per_era_json"]),
            evidence=json.loads(r["evidence_json"]),
            computed_at=r["computed_at"],
        ))
    return out


def tendencies_payload(
    db: Database, driver: str, config: DriverDNAConfig,
) -> dict[str, Any]:
    """The payload `tendencies` section: era list plus principle rows.
    Read-only — the caller refreshes first (the driver payload does so
    via the rollup; cohort payloads read the last rollup refresh).
    No wall-clock fields — `computed_at` stays in the DB, never in a
    payload, so the section is byte-deterministic."""
    eras = _era_rows(db, driver)
    dated = dict(db.dated_self_laps(driver))
    era_list = []
    for era in eras:
        lap_pks = _era_lap_pks(db, driver, era["era_index"])
        dates = sorted(dated[pk] for pk in lap_pks if pk in dated)
        if not dates:
            date_range = None
        elif dates[0] == dates[-1]:
            date_range = dates[0]
        else:
            date_range = f"{dates[0]} – {dates[-1]}"
        era_list.append({
            "era_index": era["era_index"],
            "status": era["status"],
            "n_laps": len(lap_pks),
            "date_range": date_range,
        })
    # The payload carries per-era REFERENCES (corners, cohorts, evidence
    # count inside per_era), not the raw per-observation evidence IDs:
    # on the owner corpus the full IDs run 44,668 ids / 546KB, 35% of
    # the whole payload (A59 measurement). The full lists stay in the
    # DB rows and frozen summaries for inspection.
    rows = [
        {k: v for k, v in row.items()
         if k not in ("computed_at", "evidence")}
        for row in read_tendencies(db, driver)
    ]
    return {
        "tendency_version": TENDENCY_MODEL_VERSION,
        "era_size_laps": get_era_size(db, driver, config),
        "eras": era_list,
        "principles": rows,
    }
