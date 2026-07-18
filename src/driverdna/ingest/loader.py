"""SessionLoader: laps -> cohorts (driver/car/track-config), sessions, runs.

Built in M1. There is no run/stint channel in the data: runs are reconstructed
at ingest from sync/session metadata and lap timestamps (manual-import path:
file timestamps + user-supplied session metadata; filenames carry only a lap
ID), and lap-within-run is therefore a labeled proxy. Lap role is `self` or
`reference`; reference laps never enter self history or trends.

M1 ships the fixture-manifest slice used by the debug artifacts; session/run
reconstruction and the general import path land with persistence in M2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from driverdna.ingest.contract import load_fixture_manifest
from driverdna.ingest.parser import TelemetryLap, parse_lap


@dataclass
class Cohort:
    """Laps grouped for analysis: one driver, one car, one track(-config)."""

    driver: str
    car: str
    track: str
    laps: list[TelemetryLap]


def load_fixture_cohorts(fixtures_dir: Path) -> list[Cohort]:
    """Parse the manifest-listed fixtures into cohorts (role `self` only).

    Reference-role laps never enter cohorts used for self analysis.
    """
    cohorts: dict[tuple[str, str], Cohort] = {}
    for entry in load_fixture_manifest(fixtures_dir):
        if entry["role"] != "self":
            continue
        lap = parse_lap(fixtures_dir / entry["file"])
        key = (entry["car"], entry["track"])
        if key not in cohorts:
            cohorts[key] = Cohort(
                driver="owner", car=entry["car"], track=entry["track"], laps=[]
            )
        cohorts[key].laps.append(lap)
    return [cohorts[k] for k in sorted(cohorts)]
