"""Corner identity: build -> freeze -> match track map with persistent IDs.

Built in M1. Per cohort, the corner map is built once by clustering the GPS
position (Lat/Lon) of each corner's minimum-speed point across laps
(LapDistPct center as fallback when GPS is degraded), then frozen. New laps
are MATCHED against the frozen map (nearest corner within a configurable
radius) — never re-clustered, so IDs cannot drift as data accumulates. A
genuinely new corner is admitted only when unmatched consistently across
several laps, and any map change is surfaced in the report, never silent.
"""
