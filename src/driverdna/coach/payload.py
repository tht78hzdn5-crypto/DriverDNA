"""Coach payload: the report payload plus focus history, versioned (M4)."""

from __future__ import annotations

from typing import Any

from driverdna.coach.provider import PROMPT_VERSION
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.report.payload import build_cohort_payload


def build_coach_payload(
    db: Database, *, driver: str, car: str, track: str, config: DriverDNAConfig
) -> dict[str, Any]:
    report = build_cohort_payload(db, driver=driver, car=car, track=track, config=config)
    # Incidents are deterministic engine output and live in the full payload
    # (report + UI), but the coach must not see them yet: the grounded path
    # that lets AI *explain* a classification while citing it (incident
    # evidence IDs in the citable universe) is Layer 3, a later pass. Until
    # then, keep them out of the model's context entirely so nothing can be
    # said about a spin without the machinery to ground it.
    report = {k: v for k, v in report.items() if k != "incidents"}
    # Raw traces stay out unless explicitly enabled; nothing implements the
    # flag yet, and it defaults off — the findings are the ground truth.
    return {
        "prompt_version": PROMPT_VERSION,
        "report": report,
        "focus_history": db.coach_history(driver=driver, car=car, track=track),
    }


def evidence_universe(report: dict[str, Any]) -> tuple[set[str], set[str]]:
    """(priority-eligible finding IDs, all citable evidence IDs).

    Annotated findings (driver said acknowledged/intentional) are excluded
    from priorities like suppressed ones — but remain citable evidence.
    """
    shown_findings = {
        f["finding_id"] for f in report["findings"]
        if f["shown"] and not f.get("annotation")
    }
    evidence: set[str] = set()
    for f in report["findings"]:
        evidence.add(f["finding_id"])
        evidence.update(f["evidence_ids"])
    return shown_findings, evidence
