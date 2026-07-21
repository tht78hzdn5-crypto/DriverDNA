"""Self-lap sync: Garage61 API -> the same import pipeline as manual CSVs.

Built from M0b's observed API behavior (docs/garage61-api.md): `/laps`
requires an explicit `tracks` filter and is not owner-scoped, so cohort
discovery goes through `/me/statistics` and `Garage61Client.list_own_laps`
filters every result to this account's own driver id before anything is
fetched. Reference laps (other drivers') are never reachable here — that
path stays manual `import`, tagged `role=reference`, per the M0b finding
that other-driver lap detail/CSV returns 403 `forbidden_lap`.

The API gives real session/run/date metadata a bare CSV file cannot: each
lap carries `event` + `session` (session grouping), `run` (stint index —
resolves part of SPEC.md's "no run/stint channel" gap for the sync path
specifically; the manual-import path still reconstructs it), and `startTime`
(real lap date, the M6 trend precondition).

Idempotency is the existing source_file/content_hash dedup in
`db.import_lap` — a sync-fetched lap's `source_file` is
`garage61-api:<api lap id>`. This module also skips a cheap pre-check
before spending an API call on a CSV it already has, and records a
per-cohort summary in `garage61_sync_state` for `driverdna sync` to report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.garage61.client import Garage61Client
from driverdna.ingest.parser import FlagCode, QualityFlag, parse_lap_text
from driverdna.pipeline import ImportResult, import_parsed_lap


def _track_label(track: dict[str, Any]) -> str:
    """Cohort key includes track configuration (SPEC.md: "track variants are
    distinct cohorts") — fold the API's `variant` into the label."""
    variant = track.get("variant") or ""
    return f"{track['name']} ({variant})" if variant else track["name"]


@dataclass
class CohortSync:
    car: str
    track: str
    laps_seen: int = 0
    laps_new: int = 0
    laps_skipped: list[tuple[str, str]] = field(default_factory=list)  # (lap_id, reason)
    results: list[ImportResult] = field(default_factory=list)


def discover_cohorts(client: Garage61Client) -> list[dict[str, Any]]:
    """(car_id, track_id, car label, track label) for every cohort this
    account has actually driven at least one lap in, per `/me/statistics`.
    """
    cars_by_id = {c["id"]: c for c in client.cars()}
    tracks_by_id = {t["id"]: t for t in client.tracks()}
    seen: dict[tuple[int, int], dict[str, Any]] = {}
    for row in client.statistics():
        if row.get("lapsDriven", 0) <= 0:
            continue
        key = (row["car"], row["track"])
        if key in seen:
            continue
        car = cars_by_id.get(row["car"])
        track = tracks_by_id.get(row["track"])
        if car is None or track is None:
            continue  # unresolvable id — skip rather than guess a label
        seen[key] = {
            "car_id": row["car"], "track_id": row["track"],
            "car": car["name"], "track": _track_label(track),
        }
    return sorted(seen.values(), key=lambda c: (c["car"], c["track"]))


def sync_driver(
    db: Database,
    client: Garage61Client,
    *,
    driver: str,
    config: DriverDNAConfig,
    car: str | None = None,
    track: str | None = None,
) -> list[CohortSync]:
    """Discover cohorts (or restrict to a given car/track), pull every new
    self-lap through the import pipeline, and record sync state per cohort.
    """
    cohorts = discover_cohorts(client)
    if car:
        cohorts = [c for c in cohorts if c["car"] == car]
    if track:
        cohorts = [c for c in cohorts if c["track"] == track]

    summaries: list[CohortSync] = []
    for c in cohorts:
        summary = CohortSync(car=c["car"], track=c["track"])
        laps = client.list_own_laps(track_id=c["track_id"], car_id=c["car_id"])
        summary.laps_seen = len(laps)
        for item in sorted(laps, key=lambda lap_item: lap_item.get("startTime") or ""):
            lap_id = item["id"]
            if item.get("missing") or item.get("incomplete"):
                reason = "missing" if item.get("missing") else "incomplete"
                summary.laps_skipped.append((lap_id, reason))
                continue

            # No "//" — parse_lap_text wraps this in a Path, which collapses
            # a double slash, so a later exact-string lookup would miss.
            source_label = f"garage61-api:{lap_id}"
            existing = db.conn.execute(
                "SELECT lap_pk FROM laps WHERE source_file = ?", (source_label,)
            ).fetchone()
            if existing is not None:
                continue  # already synced — never re-fetch a CSV we have

            csv_bytes = client.lap_csv(lap_id)
            lap = parse_lap_text(
                csv_bytes.decode("utf-8-sig"), source_label=source_label, lap_id=lap_id,
            )
            lap.quality_flags.append(
                QualityFlag(
                    FlagCode.API_LAP_METADATA,
                    {
                        "clean": item.get("clean"),
                        "offtrack": item.get("offtrack"),
                        "discontinuity": item.get("discontinuity"),
                        "pitlane": item.get("pitlane"),
                    },
                )
            )
            result = import_parsed_lap(
                db, lap, driver=driver, car=c["car"], track=c["track"], role="self",
                session_key=f"{item.get('event')}:{item.get('session')}",
                run_index=item.get("run"),
                lap_date=item.get("startTime"),
                config=config,
            )
            if result.was_new:
                summary.laps_new += 1
            summary.results.append(result)

        db.record_sync_state(
            driver=driver, car=c["car"], track=c["track"],
            laps_seen=summary.laps_seen, laps_new=summary.laps_new,
            synced_at=datetime.now(UTC).isoformat(),
        )
        summaries.append(summary)
    return summaries
