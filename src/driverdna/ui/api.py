"""U0 — the API layer (docs/UI-SPEC.md, decision 2 and 3).

Read endpoints are pass-throughs: the payload endpoints return the SAME
normalized bytes as `driverdna report` JSON files (contract-tested), and
everything else is an existing DB read. Write endpoints wrap the audited
paths (`db.annotate_finding`, `ConfigStore.propose/apply`) and return the
audit record they created. No aggregation, statistics, or ranking happens
here — the SPA gets exactly what the engine computed.

Chat endpoints land with U3 alongside their SSE display contract (recorded
deviation from the spec's U0 wording: shipping a chat API before the
validated-display client exists would invite unvalidated rendering).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from driverdna.chat.tools import execute_tool
from driverdna.config import ConfigStore, config_snapshot, describe_key, load_config
from driverdna.db import Database
from driverdna.report.payload import (
    build_cohort_payload,
    build_driver_payload,
    cohort_slug,
    list_cohorts,
    to_normalized_json,
)

TRACE_POINTS = 800  # transport downsampling only — layout math, not measurement


class AnnotateBody(BaseModel):
    status: str  # acknowledged | intentional
    note: str | None = None


class ProposeBody(BaseModel):
    key: str
    new_value: Any


class ApplyBody(BaseModel):
    proposal: dict[str, Any]
    note: str | None = None


def create_app(db_path: Path, config_path: Path) -> FastAPI:
    app = FastAPI(title="DriverDNA", docs_url=None, redoc_url=None)

    def open_db() -> Database:
        if not db_path.exists():
            raise HTTPException(404, detail=f"no DB at {db_path} — run `driverdna import` first")
        return Database.open(db_path)

    def resolve(db: Database, slug: str) -> dict[str, str]:
        for cohort in list_cohorts(db):
            if cohort_slug(cohort["car"], cohort["track"]) == slug:
                return cohort
        raise HTTPException(404, detail=f"unknown cohort: {slug}")

    def normalized(payload: dict) -> Response:
        return Response(content=to_normalized_json(payload), media_type="application/json")

    # --- reads --------------------------------------------------------------

    @app.get("/api/driver")
    def driver() -> Response:
        with open_db() as db:
            return normalized(build_driver_payload(db, load_config(config_path)))

    @app.get("/api/cohorts")
    def cohorts() -> list[dict[str, str]]:
        with open_db() as db:
            return [
                c | {"slug": cohort_slug(c["car"], c["track"])}
                for c in list_cohorts(db)
            ]

    @app.get("/api/cohorts/{slug}/payload")
    def cohort_payload(slug: str) -> Response:
        with open_db() as db:
            cohort = resolve(db, slug)
            return normalized(
                build_cohort_payload(db, **cohort, config=load_config(config_path))
            )

    @app.get("/api/cohorts/{slug}/corners")
    def corners(slug: str) -> list[dict[str, Any]]:
        with open_db() as db:
            cohort = resolve(db, slug)
            loaded = db.load_corner_map(car=cohort["car"], track=cohort["track"])
            if loaded is None:
                return []
            map_pk, corner_map = loaded
            classes = db.corner_classes(car=cohort["car"], track=cohort["track"])
            windows = db.load_corner_windows(map_pk)
            return [
                {
                    "corner_id": c.corner_id,
                    "lat": c.lat,
                    "lon": c.lon,
                    "lap_dist": c.lap_dist,
                    "class": classes.get(c.corner_id),
                    "windows": windows.get(c.corner_id),
                }
                for c in corner_map.corners
            ]

    @app.get("/api/cohorts/{slug}/track-trace")
    def track_trace(slug: str) -> dict[str, Any]:
        """Lat/Lon of the newest retained self lap, downsampled for transport
        — the outline the cohort view draws (UI-SPEC view 2)."""
        with open_db() as db:
            cohort = resolve(db, slug)
            rows = db.conn.execute(
                """SELECT l.lap_pk, l.lap_id FROM laps l
                   JOIN lap_samples s ON s.lap_pk = l.lap_pk
                   WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
                   ORDER BY l.lap_pk DESC LIMIT 1""",
                (cohort["driver"], cohort["car"], cohort["track"]),
            ).fetchall()
            if not rows:
                raise HTTPException(
                    404, detail="no raw lap within retention for this cohort"
                )
            arrays = db.load_lap_arrays(int(rows[0]["lap_pk"]))
            step = max(1, len(arrays["lat"]) // TRACE_POINTS)
            return {
                "lap_id": rows[0]["lap_id"],
                "lat": [round(float(v), 6) for v in arrays["lat"][::step]],
                "lon": [round(float(v), 6) for v in arrays["lon"][::step]],
                "lap_dist": [round(float(v), 5) for v in arrays["lap_dist"][::step]],
            }

    @app.get("/api/laps")
    def laps(cohort: str) -> list[dict[str, Any]]:
        with open_db() as db:
            c = resolve(db, cohort)
            rows = db.conn.execute(
                """SELECT lap_pk, lap_id, role, duration_s, session_key,
                          quality_flags,
                          EXISTS(SELECT 1 FROM lap_samples s
                                 WHERE s.lap_pk = laps.lap_pk) AS raw_retained
                   FROM laps WHERE car=? AND track=? ORDER BY lap_pk""",
                (c["car"], c["track"]),
            ).fetchall()
            return [
                {
                    "lap_pk": r["lap_pk"],
                    "lap_id": r["lap_id"],
                    "role": r["role"],
                    "duration_s": r["duration_s"],
                    "session_key": r["session_key"],
                    "quality_flags": json.loads(r["quality_flags"]),
                    "raw_retained": bool(r["raw_retained"]),
                }
                for r in rows
            ]

    @app.get("/api/metrics/{corner_id}/{metric}/distribution")
    def metric_distribution(corner_id: str, metric: str, cohort: str) -> dict[str, Any]:
        with open_db() as db:
            c = resolve(db, cohort)
            result = execute_tool(
                db=db, store=ConfigStore(config_path, db), cohort=c,
                bundle={"report": {"findings": []}}, staged=[],
                name="metric_distribution",
                args={"corner_id": corner_id, "metric": metric},
            )
            if "error" in result:
                raise HTTPException(404, detail=result["error"])
            return result

    @app.get("/api/config")
    def config_view() -> dict[str, dict[str, Any]]:
        config = load_config(config_path)
        return {
            key: {"value": value, "description": describe_key(key)}
            for key, value in sorted(config_snapshot(config).items())
        }

    @app.get("/api/config/history")
    def config_history() -> list[dict[str, Any]]:
        with open_db() as db:
            return [
                dict(r)
                for r in db.conn.execute(
                    "SELECT * FROM config_history ORDER BY change_pk"
                )
            ]

    # --- writes (wrappers over the audited paths only) ----------------------

    @app.post("/api/findings/{finding_id}/annotate")
    def annotate(finding_id: str, body: AnnotateBody) -> dict[str, Any]:
        if body.status not in ("acknowledged", "intentional"):
            raise HTTPException(422, detail="status must be acknowledged or intentional")
        with open_db() as db:
            config = load_config(config_path)
            known = {
                f["finding_id"]
                for c in list_cohorts(db)
                for f in build_cohort_payload(db, **c, config=config)["findings"]
            }
            if finding_id not in known:
                raise HTTPException(404, detail=f"unknown finding: {finding_id}")
            db.annotate_finding(finding_id=finding_id, status=body.status, note=body.note)
            return {
                "annotated": finding_id,
                "annotation": db.annotations()[finding_id],
                "effect": "suppressed from future priority framing; the "
                          "measurement itself is kept",
            }

    @app.delete("/api/findings/{finding_id}/annotate")
    def clear_annotation(finding_id: str) -> dict[str, Any]:
        """Undo an annotation — driver sovereignty cuts both ways. The finding
        returns to normal framing; no measurement was ever touched."""
        with open_db() as db:
            if finding_id not in db.annotations():
                raise HTTPException(404, detail=f"no annotation on {finding_id}")
            db.clear_annotation(finding_id)
            return {"cleared": finding_id}

    @app.post("/api/config/propose")
    def config_propose(body: ProposeBody) -> dict[str, Any]:
        with open_db() as db:
            try:
                return ConfigStore(config_path, db).propose(body.key, body.new_value)
            except (KeyError, ValueError) as e:
                raise HTTPException(422, detail=str(e)) from None

    @app.post("/api/config/apply")
    def config_apply(body: ApplyBody) -> dict[str, Any]:
        with open_db() as db:
            store = ConfigStore(config_path, db)
            try:
                # Re-validate rather than trusting the client's proposal.
                proposal = store.propose(
                    body.proposal["key"], body.proposal["new_value"]
                )
                change_pk = store.apply(proposal, source="ui", note=body.note)
            except (KeyError, ValueError) as e:
                raise HTTPException(422, detail=str(e)) from None
            row = db.conn.execute(
                "SELECT * FROM config_history WHERE change_pk=?", (change_pk,)
            ).fetchone()
            return dict(row)

    @app.post("/api/config/revert/{change_pk}")
    def config_revert(change_pk: int) -> dict[str, Any]:
        """Revert a recorded change (applies its old value back as a new,
        audited change) — the reversibility the philosophy requires."""
        with open_db() as db:
            try:
                new_pk = ConfigStore(config_path, db).revert(change_pk)
            except KeyError as e:
                raise HTTPException(404, detail=str(e)) from None
            row = db.conn.execute(
                "SELECT * FROM config_history WHERE change_pk=?", (new_pk,)
            ).fetchone()
            return dict(row)

    return app
