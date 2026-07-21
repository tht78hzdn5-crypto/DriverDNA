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
    # Incidents are now grounded (Layer 3): each event carries the one
    # coaching_principle_id the engine deterministically judged eligible
    # (None for unclassified/external), and the coach may write a validated
    # "why" for exactly that principle, citing the incident's evidence — see
    # validate.py's incident_explanations checks. The AI still never picks
    # the principle or the cause; it only explains the engine's own verdict.
    # Chat's live Q&A path does not consume incidents yet — a later pass.
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
    for e in report.get("incidents", {}).get("events", []):
        evidence.add(e["incident_id"])
    return shown_findings, evidence


def eligible_incident_principles(report: dict[str, Any]) -> dict[str, str]:
    """incident_id -> the one coaching_principle_id it may be explained
    through (only classified mechanisms; unclassified/external are absent —
    the AI may not explain a cause the engine itself didn't identify)."""
    return {
        e["incident_id"]: e["coaching_principle_id"]
        for e in report.get("incidents", {}).get("events", [])
        if e.get("coaching_principle_id")
    }
