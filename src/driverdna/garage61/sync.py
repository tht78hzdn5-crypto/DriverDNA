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
from typing import Any, Callable

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.garage61.client import (
    Garage61Client,
    Garage61ForbiddenError,
    Garage61NotFoundError,
)
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
    #: Rows the listing paged through, and how many belonged to other drivers
    #: (discarded client-side). A non-zero `foreign_rows` means the
    #: server-side `drivers=me` scope did not apply — reported, never assumed.
    rows_scanned: int = 0
    foreign_rows: int = 0
    #: Laps listed but skipped because the API said their telemetry is not
    #: viewable by this token (`canViewTelemetry: false`). Counted separately
    #: from `laps_skipped` because this is a plan/permission ceiling, not a
    #: property of the lap — see docs/garage61-api.md on `seeTelemetry`.
    laps_without_telemetry: int = 0
    #: CSV fetch returned 404 — telemetry not stored for this lap (observed
    #: on free-plan non-PB laps with group=none, A30).
    laps_csv_not_found: int = 0
    #: CSV fetch returned 403 — permission denied despite listing.
    laps_csv_forbidden: int = 0


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
    unclean: bool = True,
    after: str | None = None,
    max_age_days: int | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[CohortSync]:
    """Discover cohorts (or restrict to a given car/track), pull every new
    self-lap through the import pipeline, and record sync state per cohort.

    `after`/`max_age_days` are passed through to the API's own date filters
    and are always driver-supplied. There is deliberately **no automatic
    watermark** off `garage61_sync_state.last_synced_at`: `after` filters on
    when a lap was *driven*, not when it was synced, so a lap driven before
    the last sync but uploaded after it would be silently skipped forever.
    Re-listing a cohort in full is cheap (the `source_file` pre-check below
    means an already-synced lap never costs a CSV fetch); silently missing a
    lap is not.
    """
    def _progress(event: dict[str, Any]) -> None:
        if on_progress is not None:
            on_progress(event)

    cohorts = discover_cohorts(client)
    if car:
        cohorts = [c for c in cohorts if c["car"] == car]
    if track:
        cohorts = [c for c in cohorts if c["track"] == track]
    _progress({"type": "discovering", "cohorts": len(cohorts)})

    summaries: list[CohortSync] = []
    for ci, c in enumerate(cohorts):
        _progress({
            "type": "cohort_start", "car": c["car"], "track": c["track"],
            "index": ci, "total": len(cohorts),
        })
        summary = CohortSync(car=c["car"], track=c["track"])
        listing = client.list_own_laps(
            track_id=c["track_id"], car_id=c["car_id"],
            unclean=unclean, after=after, max_age_days=max_age_days,
        )
        summary.laps_seen = len(listing.laps)
        summary.rows_scanned = listing.rows_scanned
        summary.foreign_rows = listing.foreign_rows
        for item in sorted(listing.laps, key=lambda lap_item: lap_item.get("startTime") or ""):
            lap_id = item["id"]
            if item.get("missing") or item.get("incomplete"):
                reason = "missing" if item.get("missing") else "incomplete"
                summary.laps_skipped.append((lap_id, reason))
                continue

            # Only an explicit `false` — the field is required by the spec,
            # but a missing key must not be read as "no access" and silently
            # drop a lap we could have fetched.
            if item.get("canViewTelemetry") is False:
                summary.laps_without_telemetry += 1
                summary.laps_skipped.append((lap_id, "telemetry not viewable"))
                continue

            # No "//" — parse_lap_text wraps this in a Path, which collapses
            # a double slash, so a later exact-string lookup would miss.
            source_label = f"garage61-api:{lap_id}"
            existing = db.conn.execute(
                "SELECT lap_pk FROM laps WHERE source_file = ?", (source_label,)
            ).fetchone()
            if existing is not None:
                continue  # already synced — never re-fetch a CSV we have

            try:
                csv_bytes = client.lap_csv(lap_id)
            except Garage61NotFoundError:
                summary.laps_csv_not_found += 1
                summary.laps_skipped.append((lap_id, "csv not found (404)"))
                continue
            except Garage61ForbiddenError:
                summary.laps_csv_forbidden += 1
                summary.laps_skipped.append((lap_id, "csv forbidden (403)"))
                continue
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
                _progress({
                    "type": "lap", "car": c["car"], "track": c["track"],
                    "lap_index": summary.laps_new, "laps_new": summary.laps_new,
                })
            summary.results.append(result)

        db.record_sync_state(
            driver=driver, car=c["car"], track=c["track"],
            laps_seen=summary.laps_seen, laps_new=summary.laps_new,
            synced_at=datetime.now(UTC).isoformat(),
        )
        summaries.append(summary)
        _progress({
            "type": "cohort_done", "car": c["car"], "track": c["track"],
            "index": ci, "total": len(cohorts),
            "laps_seen": summary.laps_seen, "laps_new": summary.laps_new,
        })
    return summaries
