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
    # Raw traces stay out unless explicitly enabled; nothing implements the
    # flag yet, and it defaults off — the findings are the ground truth.
    return {
        "prompt_version": PROMPT_VERSION,
        "report": report,
        "focus_history": db.coach_history(driver=driver, car=car, track=track),
    }


def evidence_universe(report: dict[str, Any]) -> tuple[set[str], set[str]]:
    """(shown finding IDs, all citable evidence IDs) for validation."""
    shown_findings = {f["finding_id"] for f in report["findings"] if f["shown"]}
    evidence: set[str] = set()
    for f in report["findings"]:
        evidence.add(f["finding_id"])
        evidence.update(f["evidence_ids"])
    return shown_findings, evidence
