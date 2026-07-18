"""Read-only tool surface for the chat (M5).

These return real DB values — the mechanism by which the chat stays honest
instead of recalling numbers from context. The ONLY writes are
annotate_finding (recording explicit driver intent about a finding) and
propose_config_change, which STAGES a change; applying it requires the
driver's explicit /confirm, which goes through ConfigStore.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from driverdna.config import ConfigStore, describe_key
from driverdna.db import Database
from driverdna.metrics.technique import METRIC_DEFS

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "lookup_finding",
        "description": "Fetch one finding (any source, shown or suppressed) "
                       "by its finding_id, with N, spread, evidence and gate status.",
        "input_schema": {
            "type": "object",
            "properties": {"finding_id": {"type": "string"}},
            "required": ["finding_id"],
        },
    },
    {
        "name": "metric_distribution",
        "description": "Per-lap values, N, median and spread of one technique "
                       "metric for one corner (self laps only).",
        "input_schema": {
            "type": "object",
            "properties": {"corner_id": {"type": "string"},
                           "metric": {"type": "string"}},
            "required": ["corner_id", "metric"],
        },
    },
    {
        "name": "corners_in_class",
        "description": "List corner IDs in a speed class (slow/medium/fast).",
        "input_schema": {
            "type": "object",
            "properties": {"corner_class": {"type": "string"}},
            "required": ["corner_class"],
        },
    },
    {
        "name": "config_value",
        "description": "Current value and documentation of a config threshold "
                       "(dotted key, e.g. detectors.max_corrections).",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "annotate_finding",
        "description": "Record the driver's explicit statement about a finding "
                       "(acknowledged / intentional). Suppresses it from future "
                       "priority framing; never deletes the measurement. Use "
                       "only when the driver clearly asked for it.",
        "input_schema": {
            "type": "object",
            "properties": {"finding_id": {"type": "string"},
                           "status": {"type": "string",
                                      "enum": ["acknowledged", "intentional"]},
                           "note": {"type": "string"}},
            "required": ["finding_id", "status"],
        },
    },
    {
        "name": "propose_config_change",
        "description": "STAGE a config change (dotted key) with the reason. "
                       "It is NOT applied: the driver must explicitly confirm. "
                       "Show the driver the staged old/new values.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"},
                           "new_value": {},
                           "reason": {"type": "string"}},
            "required": ["key", "new_value", "reason"],
        },
    },
]


def execute_tool(
    *, db: Database, store: ConfigStore, cohort: dict[str, str],
    bundle: dict[str, Any], staged: list[dict[str, Any]],
    name: str, args: dict[str, Any],
) -> dict[str, Any]:
    if name == "lookup_finding":
        finding_id = args.get("finding_id", "")
        for f in bundle["report"]["findings"]:
            if f["finding_id"] == finding_id:
                return f
        return {"error": f"unknown finding: {finding_id}"}

    if name == "metric_distribution":
        metric = args.get("metric", "")
        if metric not in METRIC_DEFS:
            return {"error": f"not measured: {metric}. Only deterministic "
                             "metrics exist; nothing is inferred."}
        values = db.self_metric_history(
            driver=cohort["driver"], car=cohort["car"], track=cohort["track"],
            corner_id=args.get("corner_id", ""), metric=metric,
        )
        if not values:
            return {"error": "insufficient data: no values for that corner/metric"}
        return {
            "corner_id": args.get("corner_id"), "metric": metric,
            "unit": METRIC_DEFS[metric][0], "values": values, "n": len(values),
            "median": float(np.median(values)),
            "spread": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        }

    if name == "corners_in_class":
        classes = db.corner_classes(car=cohort["car"], track=cohort["track"])
        wanted = args.get("corner_class", "")
        ids = sorted(cid for cid, cls in classes.items() if cls == wanted)
        return {"corner_class": wanted, "corners": ids}

    if name == "config_value":
        key = args.get("key", "")
        try:
            return {"key": key, "value": store.get(key),
                    "description": describe_key(key)}
        except KeyError:
            return {"error": f"unknown config key: {key}"}

    if name == "annotate_finding":
        finding_id = args.get("finding_id", "")
        known = {f["finding_id"] for f in bundle["report"]["findings"]}
        if finding_id not in known:
            return {"error": f"unknown finding: {finding_id}"}
        db.annotate_finding(
            finding_id=finding_id, status=args.get("status", "acknowledged"),
            note=args.get("note"),
        )
        return {"annotated": finding_id, "status": args.get("status"),
                "effect": "suppressed from future priority framing; the "
                          "measurement itself is kept"}

    if name == "propose_config_change":
        try:
            proposal = store.propose(args.get("key", ""), args.get("new_value"))
        except (KeyError, ValueError) as e:
            return {"error": str(e)}
        proposal["reason"] = args.get("reason", "")
        staged.append(proposal)
        return {
            "staged": proposal,
            "staged_index": len(staged),
            "note": "NOT applied. The driver must confirm explicitly "
                    "(/confirm N in the chat) before this is written through "
                    "ConfigStore.",
        }

    return {"error": f"unknown tool: {name}"}
