"""Local validation of coach output — the model is never trusted (M4).

Rejects: malformed JSON, missing sections, priorities citing suppressed or
unknown findings, unknown evidence IDs, hypotheses without a labeled
confidence, and any number-with-unit not present in the payload (the
numeric-claim validator in coach/grounding.py). A rejected output is never
persisted and never shown as a plan.
"""

from __future__ import annotations

import json
import re
from typing import Any

from driverdna.coach.grounding import number_pool, unsupported_claims
from driverdna.coach.payload import evidence_universe

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

    for key in ("measured_priorities", "coaching_plan", "hypotheses"):
        if not isinstance(output.get(key), list):
            violations.append(f"missing or non-list section: {key}")
    if violations:
        raise CoachValidationError(violations)

    shown_findings, evidence = evidence_universe(report)
    pool = number_pool(report)

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
