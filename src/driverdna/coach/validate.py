"""Local validation of coach output — the model is never trusted (M4, M7).

Rejects: malformed JSON, missing sections, priorities citing suppressed or
unknown findings, unknown evidence IDs, hypotheses without a labeled
confidence, and any number-with-unit not present in the payload (the
numeric-claim validator in coach/grounding.py). M7 adds: coaching_priorities
citing an unknown or ineligible coaching_principle_id, and any
confidence/percentage language attached to a no_signal principle
(docs/COACHING.md: "a confidence value never launders an unmeasured
inference") — both mechanical rejections, same mechanism as an unknown
evidence ID. Incidents (Layer 3, SPEC.md A20) add: an incident_explanation
must cite exactly the ONE coaching_principle_id the engine deterministically
judged eligible for that incident's classification — the AI explains the
engine's verdict, it never picks or overrides it — and an incident with no
eligible principle (unclassified/external) cannot be explained at all. A
rejected output is never persisted and never shown as a plan.
"""

from __future__ import annotations

import json
import re
from typing import Any

from driverdna.coach.grounding import number_pool, numeric_claims, unsupported_claims
from driverdna.coach.payload import eligible_incident_principles, evidence_universe
from driverdna.coaching.ontology import PRINCIPLES
from driverdna.model.taxonomy import SignalStatus

_CONFIDENCES = {"low", "medium", "high"}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class CoachValidationError(ValueError):
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


def validate_coach_output(raw_text: str, report: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    try:
        output = json.loads(_FENCE.sub("", raw_text.strip()))
    except json.JSONDecodeError as e:
        raise CoachValidationError([f"output is not valid JSON: {e}"]) from None

    for key in ("measured_priorities", "coaching_priorities", "coaching_plan",
                "hypotheses", "incident_explanations"):
        if not isinstance(output.get(key), list):
            violations.append(f"missing or non-list section: {key}")
    if violations:
        raise CoachValidationError(violations)

    shown_findings, evidence = evidence_universe(report)
    pool = number_pool(report)
    coaching = report.get("coaching", {})
    coaching_candidates = (
        ([coaching["headline"]] if coaching.get("headline") else [])
        + coaching.get("secondary", [])
        + coaching.get("self_checks", [])
    )
    eligible_principles = {c["coaching_principle_id"] for c in coaching_candidates}
    for c in coaching_candidates:
        evidence.update(c["evidence_ids"])

    def check_numbers(text: str, where: str) -> None:
        for claim in unsupported_claims(text, pool):
            violations.append(
                f"{where}: number not present in the payload: {claim}"
            )

    for i, p in enumerate(output["measured_priorities"]):
        where = f"measured_priorities[{i}]"
        finding_id = p.get("finding_id")
        if finding_id not in shown_findings:
            violations.append(
                f"{where}: finding {finding_id!r} is not a shown finding "
                "(unknown or below its confidence gate)"
            )
        ids = p.get("evidence_ids") or []
        if not ids:
            violations.append(f"{where}: no evidence_ids cited")
        for e in ids:
            if e not in evidence:
                violations.append(f"{where}: unknown evidence ID {e!r}")
        check_numbers(str(p.get("why", "")), where)

    for i, cp in enumerate(output["coaching_priorities"]):
        where = f"coaching_priorities[{i}]"
        principle_id = cp.get("coaching_principle_id")
        if principle_id not in eligible_principles:
            violations.append(
                f"{where}: coaching principle {principle_id!r} is not "
                "eligible (unknown or not currently triggered)"
            )
        for e in cp.get("evidence_ids") or []:
            if e not in evidence:
                violations.append(f"{where}: unknown evidence ID {e!r}")
        text = f"{cp.get('expression', '')} {cp.get('why', '')}"
        check_numbers(text, where)
        principle = PRINCIPLES.get(principle_id)
        if principle is not None and principle.signal_status is SignalStatus.NO_SIGNAL:
            percent_claims = [c for c in numeric_claims(text) if c[1] == "%"]
            if percent_claims:
                violations.append(
                    f"{where}: no_signal principle {principle_id!r} carries "
                    f"confidence/percentage language {percent_claims!r} — "
                    "forbidden, a confidence value never launders an "
                    "unmeasured inference"
                )

    incident_principles = eligible_incident_principles(report)
    for i, ie in enumerate(output["incident_explanations"]):
        where = f"incident_explanations[{i}]"
        incident_id = ie.get("incident_id")
        required_principle = incident_principles.get(incident_id)
        if required_principle is None:
            violations.append(
                f"{where}: incident {incident_id!r} is not eligible for "
                "explanation (unknown, or the engine did not classify it "
                "clearly enough to name a cause)"
            )
        elif ie.get("coaching_principle_id") != required_principle:
            violations.append(
                f"{where}: coaching_principle_id {ie.get('coaching_principle_id')!r} "
                f"does not match the engine's own verdict {required_principle!r} "
                f"for incident {incident_id!r} — the AI explains the "
                "classification, it does not choose or override it"
            )
        ids = ie.get("evidence_ids") or []
        if incident_id not in ids:
            violations.append(f"{where}: must cite its own incident_id as evidence")
        for e in ids:
            if e not in evidence:
                violations.append(f"{where}: unknown evidence ID {e!r}")
        if ie.get("confidence") not in _CONFIDENCES:
            violations.append(
                f"{where}: incident explanation must carry confidence low/medium/high"
            )
        check_numbers(str(ie.get("explanation", "")), where)

    for i, step in enumerate(output["coaching_plan"]):
        where = f"coaching_plan[{i}]"
        if not step.get("title"):
            violations.append(f"{where}: missing title")
        check_numbers(json.dumps(step, sort_keys=True), where)

    for i, h in enumerate(output["hypotheses"]):
        where = f"hypotheses[{i}]"
        if h.get("confidence") not in _CONFIDENCES:
            violations.append(
                f"{where}: hypothesis must carry confidence low/medium/high"
            )
        if not h.get("basis"):
            violations.append(f"{where}: hypothesis must state its basis")
        for e in h.get("evidence_ids") or []:
            if e not in evidence:
                violations.append(f"{where}: unknown evidence ID {e!r}")
        check_numbers(str(h.get("statement", "")), where)

    if violations:
        raise CoachValidationError(violations)
    return output


def render_plan_markdown(output: dict[str, Any], cohort: dict[str, Any]) -> str:
    lines = [
        f"# Coaching plan — {cohort['driver']} / {cohort['car']} @ {cohort['track']}",
        "",
        "Generated on demand; every measured claim below is validated "
        "against the deterministic payload before this file is written.",
        "",
        "## Measured priorities",
        "",
    ]
    for p in output["measured_priorities"]:
        lines += [f"- **{p['finding_id']}** — {p.get('why', '')} "
                  f"(evidence: {', '.join(p['evidence_ids'])})"]
    lines += ["", "## Coaching", ""]
    for cp in output.get("coaching_priorities", []):
        lines += [
            f"- **{cp['coaching_principle_id']}** — {cp.get('expression', '')} "
            f"{cp.get('why', '')} "
            f"(evidence: {', '.join(cp.get('evidence_ids') or []) or 'none — self-check'})"
        ]
    if output.get("incident_explanations"):
        lines += ["", "## Incidents", ""]
        for ie in output["incident_explanations"]:
            lines += [
                f"- **{ie['incident_id']}** ({ie['coaching_principle_id']}, "
                f"{ie['confidence']}) — {ie.get('explanation', '')} "
                f"(evidence: {', '.join(ie.get('evidence_ids') or [])})"
            ]
    lines += ["", "## Plan", ""]
    for step in output["coaching_plan"]:
        lines += [f"### {step['title']}", "", step.get("focus", ""), ""]
        for action in step.get("actions", []):
            lines.append(f"- {action}")
        lines.append("")
    lines += ["## Hypotheses (labeled — not measurements)", ""]
    for h in output["hypotheses"]:
        lines += [
            f"- ({h['confidence']}) {h['statement']} — basis: {h['basis']}"
        ]
    return "\n".join(lines) + "\n"
