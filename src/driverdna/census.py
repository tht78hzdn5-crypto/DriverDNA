"""`driverdna census` — what the corpus supports, and what would unblock the rest.

"Do I need more lap data?" is a question the store can answer, and until now
answering it meant hand-reading a payload and re-deriving the confidence
formula. Census reports **have vs. need** for every gate the engine already
applies, plus a ranked list of what closing each gap would buy.

Two rules make it trustworthy, and both are pinned by tests:

1. **Census applies no gate of its own.** Every threshold comes from
   `DriverDNAConfig`, and every suppression reason is the *exact string the
   engine emitted* — read back off `build_cohort_payload`'s findings and
   `build_driver_payload`'s rollups rather than re-derived here. A census that
   explained a suppression in its own words could drift from the real gate and
   report a corpus as ready when it is not.
2. **It never guesses a gain it cannot compute.** Closing a corpus-level
   confidence term (sessions/tracks/cars) moves that term by an exact amount,
   identical for every fundamental, so the gain is stated as a number. How much
   a new lap raises `evidence_count`, by contrast, depends on which corners and
   metrics that lap actually produces — so census states the shortfall and
   declines to project a number ("insufficient data" over guessing).

Deterministic: no wall-clock timestamps in the report body, same rule as every
other report module.

Cost note: census calls `build_cohort_payload` per cohort to read real
suppression reasons, so it recomputes what `report` computes. That is the
price of quoting the engine instead of paraphrasing it, and it is the same
full-recomputation shape `metrics`/`model`/`coaching` already have.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.scoring import (
    SCORING_MODEL_VERSION,
    ConfidenceTerm,
    _driver_cohorts,
    compute_all_beliefs,
    confidence_from_terms,
    confidence_terms,
)
from driverdna.model.taxonomy import SignalStatus
from driverdna.report.payload import build_cohort_payload, build_driver_payload

#: Confidence terms whose shortfall is closed by acquiring whole cohorts, and
#: whose gain is therefore exactly computable. "evidence laps" is deliberately
#: absent — see rule 2 in the module docstring.
_COHORT_LEVEL_TERMS = ("sessions", "tracks", "cars")


@dataclass(frozen=True)
class GateStatus:
    """One gate: how much evidence exists, how much the gate wants, and what
    clearing it turns on."""

    label: str
    have: int
    need: int
    unblocks: str
    remedy: str

    @property
    def met(self) -> bool:
        return self.have >= self.need

    def describe(self) -> str:
        return f"{self.have}/{self.need}"


@dataclass(frozen=True)
class CensusSection:
    title: str
    note: str
    gates: tuple[GateStatus, ...] = ()
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class NextStep:
    """One acquirable thing, and what it buys.

    `delta_points` is the exact confidence gain in points (0-100) across every
    measured fundamental, or None when the gain is real but not computable in
    advance — never a guess.
    """

    action: str
    delta_points: float | None
    detail: str


@dataclass(frozen=True)
class Census:
    driver: str
    n_self_laps: int
    n_reference_laps: int
    cohorts: tuple[tuple[str, str], ...]
    sections: tuple[CensusSection, ...]
    next_steps: tuple[NextStep, ...]
    suppressed_gate_reasons: tuple[str, ...]


def _drivers_with_self_laps(db: Database) -> list[str]:
    rows = db.conn.execute(
        """SELECT DISTINCT driver FROM laps WHERE role='self' AND owner_user_pk=?
           ORDER BY driver""",
        (db.user_pk,),
    ).fetchall()
    return [r["driver"] for r in rows]


def _count(db: Database, sql: str, params: tuple) -> int:
    return int(db.conn.execute(sql, params).fetchone()["n"])


def _confidence_section(
    terms: list[ConfidenceTerm], config: DriverDNAConfig
) -> CensusSection:
    remedies = {
        "evidence laps": "import more laps in any cohort (`driverdna sync`, "
                         "`driverdna import`, or #/upload).",
        "sessions": "drive on more separate occasions — one session is one "
                    "sitting, not one lap.",
        "tracks": "import laps from another track (a track variant counts as "
                  "its own cohort).",
        "cars": "import laps in another car.",
    }
    unblocks = {
        "evidence laps": "the volume quarter of every belief's confidence",
        "sessions": "the session-breadth quarter of confidence",
        "tracks": "the track-breadth quarter of confidence",
        "cars": "the car-breadth quarter of confidence",
    }
    gates = tuple(
        GateStatus(
            label=t.label, have=t.have, need=t.floor,
            unblocks=unblocks[t.label], remedy=remedies[t.label],
        )
        for t in terms
    )
    return CensusSection(
        title="Driver Model confidence",
        note=(
            f"Confidence is the mean of these four ratios, each capped at 1.0 "
            f"(model `{SCORING_MODEL_VERSION}`). A term at its floor is "
            f"saturated — more of it buys exactly nothing. Current ceiling for "
            f"a measured fundamental: "
            f"**{confidence_from_terms(terms) * 100:.1f}%** "
            f"(a proxy fundamental is additionally capped at "
            f"{config.model.proxy_confidence_cap * 100:.0f}%)."
        ),
        gates=gates,
    )


def _scoring_floor_section(beliefs: dict, config: DriverDNAConfig) -> CensusSection:
    floor = config.model.min_evidence_for_score
    lines = []
    for fid in sorted(beliefs):
        b = beliefs[fid]
        if b.signal_status is SignalStatus.NO_SIGNAL:
            lines.append(f"- `{fid}` — no signal; never scores at any volume of laps.")
        elif b.insufficient_reason:
            lines.append(f"- `{fid}` — **{b.insufficient_reason}**")
        else:
            lines.append(
                f"- `{fid}` — scoring on {b.evidence_count} lap(s), "
                f"confidence {b.confidence * 100:.0f}%."
            )
    return CensusSection(
        title="Per-fundamental evidence",
        note=(
            f"A fundamental needs at least `model.min_evidence_for_score` "
            f"= {floor} contributing laps before it emits a number at all. "
            "Evidence counts differ per fundamental because a lap only teaches "
            "the fundamentals whose metrics and detectors it actually produced."
        ),
        lines=tuple(lines),
    )


def _trend_section(db: Database, driver: str, config: DriverDNAConfig) -> CensusSection:
    per_bucket = config.model.trend_min_laps_per_bucket
    dated = db.driver_dated_lap_count(driver)
    gate = GateStatus(
        label="dated laps",
        have=dated,
        need=per_bucket * 2,
        unblocks=f"`trend` on every fundamental ({per_bucket} dated laps in "
                 "each of the earlier and recent halves)",
        remedy="`driverdna sync` sets lap_date from the API automatically; for "
               "manual CSVs use `driverdna import --date YYYY-MM-DD`.",
    )
    return CensusSection(
        title="Trend availability",
        note=(
            "Trend compares a fundamental's score between an earlier and a "
            "recent bucket of dated laps. An undated lap can still score — it "
            "just cannot be placed in time, so it never contributes a direction."
        ),
        gates=(gate,),
    )


def _reference_section(n_reference: int, cohorts: tuple) -> CensusSection:
    example = cohorts[0] if cohorts else ("<car>", "<track>")
    gate = GateStatus(
        label="reference laps",
        have=n_reference,
        need=1,
        unblocks="the vs-reference gap findings, the reference envelope, and "
                 "the 'ref n=K' UI — none of which have ever run on real data",
        remedy=(
            f'`driverdna import <lap.csv> --role reference --car "{example[0]}" '
            f'--track "{example[1]}"`'
        ),
    )
    return CensusSection(
        title="Reference laps",
        note=(
            "Reference laps are structurally isolated: they never enter self "
            "history, trends, or consistency statistics. `sync` cannot fetch "
            "them (other drivers' telemetry returns 403), so the manual import "
            "path is the only way in."
        ),
        gates=(gate,),
    )


def _suppression_section(
    db: Database, driver: str, cohorts: tuple, config: DriverDNAConfig,
) -> tuple[CensusSection, tuple[str, ...]]:
    """Read back what the engine actually suppressed, verbatim."""
    reasons: Counter[str] = Counter()
    n_shown = n_total = 0
    for car, track in cohorts:
        payload = build_cohort_payload(
            db, driver=driver, car=car, track=track, config=config
        )
        for finding in payload["findings"]:
            n_total += 1
            if finding["shown"]:
                n_shown += 1
            elif finding["gate_reason"]:
                reasons[finding["gate_reason"]] += 1

    rollup_reasons: Counter[str] = Counter()
    for rollup in build_driver_payload(db, config)["cross_track_rollups"]:
        if not rollup["shown"] and rollup["gate_reason"]:
            rollup_reasons[rollup["gate_reason"]] += 1

    lines = [f"- findings shown: **{n_shown}** of {n_total} computed."]
    if reasons:
        lines.append("- suppressed because (count of findings per reason):")
        # Most-blocking first, then alphabetical — the dominant gate is the
        # one worth acting on, and ties must order deterministically.
        lines += [
            f"    - `{r}` — {n}"
            for r, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
    if rollup_reasons:
        lines.append("- cross-track rollups suppressed because:")
        lines += [
            f"    - `{r}` — {n}"
            for r, n in sorted(rollup_reasons.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
    if not reasons and not rollup_reasons:
        lines.append("- nothing is currently suppressed by a confidence gate.")

    section = CensusSection(
        title="What the gates are hiding right now",
        note=(
            "These are the engine's own words, read back off the payload — "
            "census does not re-derive them. `gates.min_phase_samples` = "
            f"{config.gates.min_phase_samples}, `gates.min_sessions` = "
            f"{config.gates.min_sessions}, `gates.min_tracks_for_rollup` = "
            f"{config.gates.min_tracks_for_rollup}. **Not every suppression is "
            "a volume problem**: a sample-count or track-count reason clears "
            "with more laps, but 'no effect' means the fast and slow laps "
            "genuinely do not differ there, and 'below pattern floor' means the "
            "behaviour is an event rather than a habit — more laps will not "
            "turn either into a finding."
        ),
        lines=tuple(lines),
    )
    return section, tuple(sorted(set(reasons) | set(rollup_reasons)))


def _next_steps(
    terms: list[ConfidenceTerm], n_reference: int, dated_gate: GateStatus,
) -> tuple[NextStep, ...]:
    by_label = {t.label: t for t in terms}
    base = confidence_from_terms(terms)

    quantified: list[NextStep] = []
    for label in _COHORT_LEVEL_TERMS:
        term = by_label[label]
        if term.ratio >= 1.0:
            continue  # saturated: more of this buys exactly nothing
        shortfall = term.floor - term.have
        closed = [replace(t, have=t.floor) if t.label == label else t for t in terms]
        gain = (confidence_from_terms(closed) - base) * 100.0
        noun = {"sessions": "session", "tracks": "track", "cars": "car"}[label]
        quantified.append(
            NextStep(
                # Always "N more X", never "a second X": the shortfall can be 1
                # while the corpus already holds two (tracks 2/3), and "a second
                # track" would then be simply wrong.
                action=f"{shortfall} more {noun}" + ("" if shortfall == 1 else "s"),
                delta_points=round(gain, 2),
                detail=(
                    f"{noun}s {term.have}/{term.floor}; "
                    f"+{gain / shortfall:.2f} points each, on every measured "
                    "fundamental."
                ),
            )
        )
    quantified.sort(key=lambda s: (-(s.delta_points or 0.0), s.action))

    evidence = by_label["evidence laps"]
    unquantified: list[NextStep] = []
    if evidence.ratio < 1.0:
        unquantified.append(
            NextStep(
                action="more laps in an existing cohort",
                delta_points=None,
                detail=(
                    f"evidence {evidence.have}/{evidence.floor} on the weakest "
                    "scoring fundamental. The gain is real but not projectable: "
                    "how much a lap raises evidence_count depends on which "
                    "corners and metrics it actually produces."
                ),
            )
        )
    if n_reference == 0:
        unquantified.append(
            NextStep(
                action="import a reference lap",
                delta_points=None,
                detail=(
                    "buys capability rather than confidence: it is the only way "
                    "to fire the vs-reference path, which has never run on real "
                    "data."
                ),
            )
        )
    if not dated_gate.met:
        unquantified.append(
            NextStep(
                action="date the laps already imported",
                delta_points=None,
                detail=(
                    f"dated {dated_gate.have}/{dated_gate.need}; unblocks trend "
                    "without driving anything new."
                ),
            )
        )
    return tuple(quantified + unquantified)


def build_census(
    db: Database, config: DriverDNAConfig, *, driver: str | None = None
) -> Census:
    """Have-vs-need across every gate, for one driver's corpus."""
    if driver is None:
        drivers = _drivers_with_self_laps(db)
        if not drivers:
            raise ValueError("no self laps imported")
        driver = drivers[0]

    cohorts = tuple(_driver_cohorts(db, driver))
    n_self = _count(
        db,
        """SELECT COUNT(*) n FROM laps WHERE role='self' AND driver=?
           AND owner_user_pk=?""",
        (driver, db.user_pk),
    )
    n_reference = _count(
        db,
        "SELECT COUNT(*) n FROM laps WHERE role='reference' AND owner_user_pk=?",
        (db.user_pk,),
    )

    beliefs = compute_all_beliefs(db, driver=driver, config=config)
    scorable = [
        b.evidence_count for b in beliefs.values()
        if b.signal_status is not SignalStatus.NO_SIGNAL
    ]
    # The binding constraint is the weakest fundamental, not an average of
    # them: confidence is per-fundamental, and reporting the best would
    # overstate what the corpus supports.
    weakest_evidence = min(scorable) if scorable else 0
    terms = confidence_terms(db, driver, list(cohorts), weakest_evidence, config)

    trend_section = _trend_section(db, driver, config)
    suppression_section, suppressed = _suppression_section(
        db, driver, cohorts, config
    )
    sections = (
        _confidence_section(terms, config),
        _scoring_floor_section(beliefs, config),
        trend_section,
        _reference_section(n_reference, cohorts),
        suppression_section,
    )
    return Census(
        driver=driver,
        n_self_laps=n_self,
        n_reference_laps=n_reference,
        cohorts=cohorts,
        sections=sections,
        next_steps=_next_steps(terms, n_reference, trend_section.gates[0]),
        suppressed_gate_reasons=suppressed,
    )


def render_census(census: Census) -> list[str]:
    lines = [
        f"## {census.driver}",
        "",
        f"- self laps: **{census.n_self_laps}** across "
        f"**{len(census.cohorts)}** cohort(s)",
        f"- reference laps: **{census.n_reference_laps}**",
    ]
    # No blank line before the nested items: a blank line followed by a
    # four-space indent renders as a code block, not a sub-list.
    lines += [f"    - {car} @ {track}" for car, track in census.cohorts]
    lines.append("")

    for section in census.sections:
        lines += [f"### {section.title}", "", section.note, ""]
        if section.gates:
            lines += [
                "| gate | have / need | status | unblocks |",
                "|---|---|---|---|",
            ]
            for g in section.gates:
                status = "met" if g.met else "**short**"
                lines.append(
                    f"| {g.label} | {g.describe()} | {status} | {g.unblocks} |"
                )
            lines.append("")
            for g in section.gates:
                if not g.met:
                    lines.append(f"- to close **{g.label}**: {g.remedy}")
            lines.append("")
        if section.lines:
            lines += [*section.lines, ""]

    lines += ["### What to add next", ""]
    if not census.next_steps:
        lines += ["Every gate is met. More laps still sharpen nothing that is "
                  "currently suppressed.", ""]
        return lines
    lines += [
        "Ranked by confidence gained. A gain shown as `—` is real but not "
        "projectable, and census will not invent a number for it.",
        "",
        "| add | confidence gain | why |",
        "|---|---|---|",
    ]
    for step in census.next_steps:
        gain = "—" if step.delta_points is None else f"+{step.delta_points:.2f} pts"
        lines.append(f"| {step.action} | {gain} | {step.detail} |")
    lines.append("")
    return lines


def build_census_report(db: Database, config: DriverDNAConfig) -> str:
    """The `driverdna census` artifact."""
    lines = [
        "# Corpus census — what the evidence currently supports",
        "",
        "Generated by `driverdna census`. Every threshold below is read from "
        "config and every suppression reason is quoted from the engine's own "
        "payload — census measures nothing itself. Deterministic: no "
        "wall-clock timestamps.",
        "",
    ]
    drivers = _drivers_with_self_laps(db)
    if not drivers:
        lines += [
            "No self laps imported yet — nothing to take a census of. Start "
            "with `driverdna sync`, `driverdna import`, or the `#/upload` view.",
        ]
        return "\n".join(lines) + "\n"

    for driver in drivers:
        lines += render_census(build_census(db, config, driver=driver))
    return "\n".join(lines) + "\n"
