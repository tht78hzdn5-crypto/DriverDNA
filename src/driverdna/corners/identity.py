"""Corner identity: build -> freeze -> match track map with persistent IDs (M1).

Per cohort, the corner map is built ONCE by clustering the GPS position of
each corner's primary (minimum-speed) apex across the build laps, then
frozen. Subsequent laps are MATCHED against the frozen map — never
re-clustered — so IDs cannot drift as data accumulates. Matching accepts any
apex of a multi-apex complex (the primary can legitimately alternate between
the dips of a chicane lap to lap) and falls back to circular lap-distance
proximity when GPS is degraded. IDs are "C01", "C02", ... in track order at
build time and never renumber.

Admission of genuinely new corners (consistently unmatched across
min_laps_for_admission laps) is explicit and surfaced by the caller; the
counting machinery lands with persistence in M2. See docs/SPEC.md, M1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from driverdna.config import IdentityConfig
from driverdna.corners.segmenter import CornerSpan
from driverdna.ingest.parser import TelemetryLap

_M_PER_DEG_LAT = 111_320.0


def _gps_ok(lat: float, lon: float) -> bool:
    return math.isfinite(lat) and math.isfinite(lon) and not (lat == 0.0 and lon == 0.0)


def _meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Small-distance approximation, ample for corner-scale geometry."""
    dlat = (lat2 - lat1) * _M_PER_DEG_LAT
    dlon = (lon2 - lon1) * _M_PER_DEG_LAT * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def _circular_dist(a: float, b: float) -> float:
    d = abs(a % 1.0 - b % 1.0)
    return min(d, 1.0 - d)


@dataclass(frozen=True)
class CornerIdentity:
    corner_id: str  # "C01".. in track order at build; never renumbered
    lat: float  # frozen center: median of build observations (NaN if no GPS)
    lon: float
    lap_dist: float  # median primary-apex lap distance (mod 1)
    n_build_observations: int


@dataclass(frozen=True)
class CornerMap:
    """Frozen per-cohort corner identities."""

    corners: tuple[CornerIdentity, ...]

    def match_span(
        self, lap: TelemetryLap, span: CornerSpan, cfg: IdentityConfig
    ) -> str | None:
        """Best identity for one observed corner, or None if nothing is near."""
        best_id: str | None = None
        best_score = math.inf
        for identity in self.corners:
            for apex in span.landmarks.apexes:
                a_lat, a_lon = float(lap.lat[apex]), float(lap.lon[apex])
                if _gps_ok(a_lat, a_lon) and _gps_ok(identity.lat, identity.lon):
                    d = _meters(a_lat, a_lon, identity.lat, identity.lon)
                    within, score = d <= cfg.match_radius_m, d
                else:
                    d = _circular_dist(float(lap.lap_dist[apex]), identity.lap_dist)
                    # Scale to meters-comparable so mixed scoring stays sane.
                    within, score = d <= cfg.dist_pct_fallback_radius, d * 1e6
                if within and score < best_score:
                    best_id, best_score = identity.corner_id, score
        return best_id

    def match_lap(
        self, lap: TelemetryLap, spans: list[CornerSpan], cfg: IdentityConfig
    ) -> list[str | None]:
        return [self.match_span(lap, span, cfg) for span in spans]


def build_corner_map(
    laps_with_spans: list[tuple[TelemetryLap, list[CornerSpan]]],
    cfg: IdentityConfig,
) -> CornerMap:
    """Cluster primary-apex positions across the build laps and freeze the map."""
    clusters: list[dict[str, list[float]]] = []

    for lap, spans in laps_with_spans:
        for span in spans:
            apex = span.landmarks.apex
            a_lat, a_lon = float(lap.lat[apex]), float(lap.lon[apex])
            a_dist = float(lap.lap_dist[apex]) % 1.0
            use_gps = _gps_ok(a_lat, a_lon)

            best = None
            best_d = math.inf
            for cluster in clusters:
                c_lat = float(np.nanmedian(cluster["lats"]))
                c_lon = float(np.nanmedian(cluster["lons"]))
                if use_gps and _gps_ok(c_lat, c_lon):
                    d = _meters(a_lat, a_lon, c_lat, c_lon)
                    if d <= cfg.match_radius_m and d < best_d:
                        best, best_d = cluster, d
                else:
                    d = _circular_dist(a_dist, float(np.median(cluster["dists"])))
                    if d <= cfg.dist_pct_fallback_radius and d < best_d:
                        best, best_d = cluster, d

            if best is None:
                clusters.append(
                    {"lats": [a_lat], "lons": [a_lon], "dists": [a_dist]}
                )
            else:
                best["lats"].append(a_lat)
                best["lons"].append(a_lon)
                best["dists"].append(a_dist)

    ordered = sorted(clusters, key=lambda c: float(np.median(c["dists"])))
    corners = tuple(
        CornerIdentity(
            corner_id=f"C{i + 1:02d}",
            lat=float(np.nanmedian(c["lats"])),
            lon=float(np.nanmedian(c["lons"])),
            lap_dist=float(np.median(c["dists"])),
            n_build_observations=len(c["dists"]),
        )
        for i, c in enumerate(ordered)
    )
    return CornerMap(corners=corners)
