"""SQLite persistence: schema, migrations, lap-blob storage, eviction (M2).

Raw lap samples are stored as one compressed npz blob per lap — laps are
always loaded whole, nothing queries individual samples by SQL. Everything
queryable lives in compact relational rows: laps (metadata + quality flags),
frozen corner maps, per-lap corner observations (span, landmarks, apex
position), metric values, detector results, config history. Compact rows are
permanent; only raw blobs are windowed (newest N per driver/car/track
cohort, transactional single-row deletes that can never touch summaries).

Role isolation is enforced at the query surface: `self_metric_history` and
everything derived from it filter role='self', so reference laps can never
enter the driver's own history or trends.

Corner-map admission: unmatched observations accumulate as candidates; once
the same location is seen on enough distinct laps (config
identity.min_laps_for_admission), `admit_pending_candidates` appends a new
corner (next ID — existing IDs never renumber) and returns the admitted IDs
so the caller surfaces the map change. Nothing changes the map silently.
"""

from __future__ import annotations

import io
import json
import math
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from driverdna.config import IdentityConfig
from driverdna.corners.identity import CornerIdentity, CornerMap, _gps_ok, _meters
from driverdna.corners.segmenter import CornerSpan, Landmarks
from driverdna.ingest.parser import TelemetryLap

_BLOB_CHANNELS = (
    "elapsed_s", "lap_dist", "lap_dist_pct_raw", "speed", "lat", "lon",
    "brake", "throttle", "rpm", "steering_deg", "gear", "clutch",
    "abs_active", "drs_active", "lat_accel", "long_accel", "vert_accel",
    "yaw", "yaw_rate", "position_type",
)

MIGRATIONS: tuple[str, ...] = (
    # 001 — initial schema
    """
    CREATE TABLE laps (
        lap_pk INTEGER PRIMARY KEY,
        lap_id TEXT,
        source_file TEXT NOT NULL UNIQUE,
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('self', 'reference')),
        session_key TEXT,
        run_index INTEGER,
        n_samples INTEGER NOT NULL,
        duration_s REAL NOT NULL,
        imported_at TEXT,
        quality_flags TEXT NOT NULL
    );
    CREATE TABLE lap_samples (
        lap_pk INTEGER PRIMARY KEY REFERENCES laps(lap_pk) ON DELETE CASCADE,
        fmt TEXT NOT NULL,
        data BLOB NOT NULL
    );
    CREATE TABLE corner_maps (
        map_pk INTEGER PRIMARY KEY,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        built_from_n_laps INTEGER NOT NULL,
        UNIQUE (car, track)
    );
    CREATE TABLE corners (
        corner_pk INTEGER PRIMARY KEY,
        map_pk INTEGER NOT NULL REFERENCES corner_maps(map_pk) ON DELETE CASCADE,
        corner_id TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        lap_dist REAL NOT NULL,
        n_build_observations INTEGER NOT NULL,
        class TEXT,
        UNIQUE (map_pk, corner_id)
    );
    CREATE TABLE corner_observations (
        obs_pk INTEGER PRIMARY KEY,
        lap_pk INTEGER NOT NULL REFERENCES laps(lap_pk) ON DELETE CASCADE,
        corner_pk INTEGER REFERENCES corners(corner_pk),
        span_start INTEGER NOT NULL,
        span_end INTEGER NOT NULL,
        landmarks TEXT NOT NULL,
        landmark_positions TEXT NOT NULL,
        apex_lat REAL NOT NULL,
        apex_lon REAL NOT NULL,
        apex_lap_dist REAL NOT NULL,
        min_speed_ms REAL NOT NULL,
        UNIQUE (lap_pk, span_start)
    );
    CREATE TABLE corner_windows (
        corner_pk INTEGER PRIMARY KEY REFERENCES corners(corner_pk) ON DELETE CASCADE,
        entry_start REAL,
        turn_in REAL,
        apex REAL NOT NULL,
        exit_end REAL
    );
    CREATE TABLE phase_times (
        obs_pk INTEGER NOT NULL REFERENCES corner_observations(obs_pk) ON DELETE CASCADE,
        phase TEXT NOT NULL CHECK (phase IN ('entry', 'mid', 'exit')),
        time_s REAL NOT NULL,
        PRIMARY KEY (obs_pk, phase)
    );
    CREATE TABLE metric_values (
        obs_pk INTEGER NOT NULL REFERENCES corner_observations(obs_pk) ON DELETE CASCADE,
        name TEXT NOT NULL,
        value REAL,
        PRIMARY KEY (obs_pk, name)
    );
    CREATE TABLE detector_results (
        obs_pk INTEGER NOT NULL REFERENCES corner_observations(obs_pk) ON DELETE CASCADE,
        detector TEXT NOT NULL,
        triggered INTEGER NOT NULL,
        value REAL NOT NULL,
        threshold REAL NOT NULL,
        unit TEXT NOT NULL,
        rationale TEXT NOT NULL,
        PRIMARY KEY (obs_pk, detector)
    );
    CREATE TABLE config_history (
        change_pk INTEGER PRIMARY KEY,
        key TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT NOT NULL,
        source TEXT NOT NULL,
        note TEXT
    );
    CREATE TABLE coach_outputs (
        output_pk INTEGER PRIMARY KEY,
        driver TEXT NOT NULL,
        car TEXT NOT NULL,
        track TEXT NOT NULL,
        payload_version INTEGER NOT NULL,
        prompt_version TEXT NOT NULL,
        model TEXT NOT NULL,
        output_json TEXT NOT NULL,
        created_at TEXT
    );
    CREATE TABLE finding_annotations (
        annotation_pk INTEGER PRIMARY KEY,
        finding_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('acknowledged', 'intentional')),
        note TEXT,
        created_at TEXT
    );
    CREATE TABLE chat_transcripts (
        turn_pk INTEGER PRIMARY KEY,
        session_id TEXT NOT NULL,
        bundle_version INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('driver', 'assistant', 'system-event')),
        content TEXT NOT NULL,
        evidence_cited TEXT,
        effects TEXT
    );
    """,
)


def _lap_blob(lap: TelemetryLap) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **{c: getattr(lap, c) for c in _BLOB_CHANNELS})
    return buf.getvalue()


def _landmarks_json(landmarks: Landmarks) -> str:
    return json.dumps(asdict(landmarks), sort_keys=True)


def landmark_positions(lap: TelemetryLap, landmarks: Landmarks) -> dict[str, Any]:
    """Landmark lap-distance positions (mod 1) — the compact record canonical
    phase windows are derived from; must survive raw-blob eviction."""

    def pos(idx: int | None) -> float | None:
        return None if idx is None else float(lap.lap_dist[idx]) % 1.0

    data = {k: pos(v) for k, v in asdict(landmarks).items() if k != "apexes"}
    data["apexes"] = [pos(a) for a in landmarks.apexes]
    return data


def landmarks_from_json(text: str) -> Landmarks:
    data = json.loads(text)
    data["apexes"] = tuple(data["apexes"])
    return Landmarks(**data)


class Database:
    """One connection, migrations applied, typed helpers over the schema."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    @classmethod
    def open(cls, path: Path | str = ":memory:") -> "Database":
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _migrate(self) -> None:
        with self.conn:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
            )
            row = self.conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
            current = row["v"] or 0
            for i, script in enumerate(MIGRATIONS[current:], start=current + 1):
                self.conn.executescript(script)
                self.conn.execute("INSERT INTO schema_version VALUES (?)", (i,))

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
        return int(row["v"] or 0)

    # --- laps --------------------------------------------------------------

    def import_lap(
        self,
        lap: TelemetryLap,
        *,
        driver: str,
        car: str,
        track: str,
        role: str = "self",
        session_key: str | None = None,
        imported_at: str | None = None,
    ) -> tuple[int, bool]:
        """Store lap row + raw blob. Returns (lap_pk, was_new).

        Re-importing the same source file is a no-op returning the existing
        row — nothing is silently overwritten.
        """
        existing = self.conn.execute(
            "SELECT lap_pk FROM laps WHERE source_file = ?", (str(lap.source_path),)
        ).fetchone()
        if existing:
            return int(existing["lap_pk"]), False
        flags = json.dumps(
            [{"code": str(f.code), "detail": f.detail} for f in lap.quality_flags],
            sort_keys=True,
        )
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO laps (lap_id, source_file, driver, car, track, role,
                                     session_key, n_samples, duration_s, imported_at,
                                     quality_flags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lap.lap_id, str(lap.source_path), driver, car, track, role,
                    session_key, lap.n_samples, lap.duration_s, imported_at, flags,
                ),
            )
            lap_pk = int(cur.lastrowid)
            self.conn.execute(
                "INSERT INTO lap_samples (lap_pk, fmt, data) VALUES (?, 'npz-v1', ?)",
                (lap_pk, _lap_blob(lap)),
            )
        return lap_pk, True

    def load_lap_arrays(self, lap_pk: int) -> dict[str, np.ndarray] | None:
        row = self.conn.execute(
            "SELECT data FROM lap_samples WHERE lap_pk = ?", (lap_pk,)
        ).fetchone()
        if row is None:
            return None
        with np.load(io.BytesIO(row["data"])) as npz:
            return {name: npz[name] for name in npz.files}

    def enforce_retention(self, keep: int) -> int:
        """Evict raw blobs beyond the newest `keep` laps per cohort.

        Only lap_samples rows are deleted; laps, observations, metrics, and
        detector rows — everything trends are built from — are untouched.
        Returns the number of blobs evicted.
        """
        with self.conn:
            cur = self.conn.execute(
                """DELETE FROM lap_samples WHERE lap_pk IN (
                       SELECT lap_pk FROM (
                           SELECT l.lap_pk,
                                  ROW_NUMBER() OVER (
                                      PARTITION BY l.driver, l.car, l.track
                                      ORDER BY l.lap_pk DESC) AS rn
                           FROM laps l JOIN lap_samples s ON s.lap_pk = l.lap_pk
                       ) WHERE rn > ?)""",
                (keep,),
            )
        return cur.rowcount

    # --- corner maps -------------------------------------------------------

    def store_corner_map(
        self, corner_map: CornerMap, *, car: str, track: str,
        built_from_n_laps: int,
    ) -> int:
        """Corner maps are keyed by (car, track) — NOT driver — so reference
        laps from other drivers share the owner's corner identities; gap
        analysis joins on them."""
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO corner_maps (car, track, built_from_n_laps)
                   VALUES (?, ?, ?)""",
                (car, track, built_from_n_laps),
            )
            map_pk = int(cur.lastrowid)
            for c in corner_map.corners:
                self.conn.execute(
                    """INSERT INTO corners (map_pk, corner_id, lat, lon, lap_dist,
                                            n_build_observations)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (map_pk, c.corner_id, c.lat, c.lon, c.lap_dist,
                     c.n_build_observations),
                )
        return map_pk

    def load_corner_map(self, *, car: str, track: str) -> tuple[int, CornerMap] | None:
        row = self.conn.execute(
            "SELECT map_pk FROM corner_maps WHERE car=? AND track=?",
            (car, track),
        ).fetchone()
        if row is None:
            return None
        map_pk = int(row["map_pk"])
        corners = tuple(
            CornerIdentity(
                corner_id=r["corner_id"], lat=r["lat"], lon=r["lon"],
                lap_dist=r["lap_dist"],
                n_build_observations=r["n_build_observations"],
            )
            for r in self.conn.execute(
                "SELECT * FROM corners WHERE map_pk=? ORDER BY corner_id", (map_pk,)
            )
        )
        return map_pk, CornerMap(corners=corners)

    def corner_pk(self, map_pk: int, corner_id: str) -> int:
        row = self.conn.execute(
            "SELECT corner_pk FROM corners WHERE map_pk=? AND corner_id=?",
            (map_pk, corner_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"no corner {corner_id} in map {map_pk}")
        return int(row["corner_pk"])

    def set_corner_class(self, corner_pk: int, cls: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE corners SET class=? WHERE corner_pk=?", (cls, corner_pk)
            )

    # --- observations, metrics, detectors ----------------------------------

    def store_observation(
        self,
        *,
        lap: TelemetryLap,
        lap_pk: int,
        span: CornerSpan,
        corner_pk: int | None,
        metrics: dict[str, float | None],
        detector_results: list[Any],
    ) -> int:
        apex = span.landmarks.apex
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO corner_observations
                   (lap_pk, corner_pk, span_start, span_end, landmarks,
                    landmark_positions, apex_lat, apex_lon, apex_lap_dist,
                    min_speed_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lap_pk, corner_pk, span.start, span.end,
                    _landmarks_json(span.landmarks),
                    json.dumps(landmark_positions(lap, span.landmarks), sort_keys=True),
                    float(lap.lat[apex]), float(lap.lon[apex]),
                    float(lap.lap_dist[apex]) % 1.0, span.min_speed(lap),
                ),
            )
            obs_pk = int(cur.lastrowid)
            self.conn.executemany(
                "INSERT INTO metric_values (obs_pk, name, value) VALUES (?, ?, ?)",
                [(obs_pk, name, value) for name, value in sorted(metrics.items())],
            )
            self.conn.executemany(
                """INSERT INTO detector_results
                   (obs_pk, detector, triggered, value, threshold, unit, rationale)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (obs_pk, r.detector, int(r.triggered), r.value, r.threshold,
                     r.unit, r.rationale)
                    for r in detector_results
                ],
            )
        return obs_pk

    def self_metric_history(
        self, *, driver: str, car: str, track: str, corner_id: str, metric: str
    ) -> list[float]:
        """Per-lap values for one metric on one corner — role='self' ONLY.

        This is the single gate through which trends and consistency see
        data; reference laps are excluded here, not in each caller.
        """
        rows = self.conn.execute(
            """SELECT mv.value FROM metric_values mv
               JOIN corner_observations o ON o.obs_pk = mv.obs_pk
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN corner_maps m ON m.map_pk = c.map_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE l.role = 'self' AND l.driver=? AND l.car=? AND l.track=?
                 AND c.corner_id=? AND mv.name=? AND mv.value IS NOT NULL
               ORDER BY l.lap_pk, o.span_start""",
            (driver, car, track, corner_id, metric),
        ).fetchall()
        return [float(r["value"]) for r in rows]

    # --- canonical windows and phase times ----------------------------------

    def store_corner_windows(
        self, corner_pk: int, *, entry_start: float | None, turn_in: float | None,
        apex: float, exit_end: float | None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO corner_windows
                   (corner_pk, entry_start, turn_in, apex, exit_end)
                   VALUES (?, ?, ?, ?, ?)""",
                (corner_pk, entry_start, turn_in, apex, exit_end),
            )

    def load_corner_windows(self, map_pk: int) -> dict[str, dict[str, float | None]]:
        rows = self.conn.execute(
            """SELECT c.corner_id, w.entry_start, w.turn_in, w.apex, w.exit_end
               FROM corner_windows w JOIN corners c ON c.corner_pk = w.corner_pk
               WHERE c.map_pk = ? ORDER BY c.corner_id""",
            (map_pk,),
        ).fetchall()
        return {
            r["corner_id"]: {
                "entry_start": r["entry_start"], "turn_in": r["turn_in"],
                "apex": r["apex"], "exit_end": r["exit_end"],
            }
            for r in rows
        }

    def store_phase_times(self, obs_pk: int, times: dict[str, float]) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO phase_times (obs_pk, phase, time_s) VALUES (?, ?, ?)",
                [(obs_pk, phase, t) for phase, t in sorted(times.items())],
            )

    def phase_history(
        self, *, car: str, track: str, corner_id: str, phase: str, role: str,
        driver: str | None = None,
    ) -> list[dict[str, Any]]:
        """Per-lap phase times for one corner, filtered by role.

        role='self' additionally requires driver (self history is one
        driver's); role='reference' aggregates all reference drivers.
        """
        if role == "self" and driver is None:
            raise ValueError("self phase history requires a driver")
        clause = "AND l.driver = ?" if driver is not None else ""
        params = [car, track, corner_id, phase, role] + ([driver] if driver else [])
        rows = self.conn.execute(
            f"""SELECT p.time_s, l.lap_pk, l.session_key, o.obs_pk
                FROM phase_times p
                JOIN corner_observations o ON o.obs_pk = p.obs_pk
                JOIN corners c ON c.corner_pk = o.corner_pk
                JOIN laps l ON l.lap_pk = o.lap_pk
                WHERE l.car=? AND l.track=? AND c.corner_id=? AND p.phase=?
                  AND l.role=? {clause}
                ORDER BY l.lap_pk, o.span_start""",
            params,
        ).fetchall()
        return [
            {"time_s": float(r["time_s"]), "lap_pk": int(r["lap_pk"]),
             "session_key": r["session_key"], "obs_pk": int(r["obs_pk"])}
            for r in rows
        ]

    def observation_positions(self, corner_pk: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT landmark_positions FROM corner_observations WHERE corner_pk=? ORDER BY obs_pk",
            (corner_pk,),
        ).fetchall()
        return [json.loads(r["landmark_positions"]) for r in rows]

    def self_metric_table(
        self, *, driver: str, car: str, track: str
    ) -> dict[str, dict[str, list[float]]]:
        """{corner_id: {metric: per-lap values}} — role='self' only."""
        rows = self.conn.execute(
            """SELECT c.corner_id, mv.name, mv.value FROM metric_values mv
               JOIN corner_observations o ON o.obs_pk = mv.obs_pk
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
                 AND mv.value IS NOT NULL
               ORDER BY c.corner_id, mv.name, l.lap_pk, o.span_start""",
            (driver, car, track),
        ).fetchall()
        table: dict[str, dict[str, list[float]]] = {}
        for r in rows:
            table.setdefault(r["corner_id"], {}).setdefault(r["name"], []).append(
                float(r["value"])
            )
        return table

    def self_detector_table(
        self, *, driver: str, car: str, track: str
    ) -> dict[str, dict[str, tuple[int, int]]]:
        """{corner_id: {detector: (triggered, total)}} — role='self' only."""
        rows = self.conn.execute(
            """SELECT c.corner_id, d.detector,
                      SUM(d.triggered) AS trig, COUNT(*) AS total
               FROM detector_results d
               JOIN corner_observations o ON o.obs_pk = d.obs_pk
               JOIN corners c ON c.corner_pk = o.corner_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
               GROUP BY c.corner_id, d.detector
               ORDER BY c.corner_id, d.detector""",
            (driver, car, track),
        ).fetchall()
        table: dict[str, dict[str, tuple[int, int]]] = {}
        for r in rows:
            table.setdefault(r["corner_id"], {})[r["detector"]] = (
                int(r["trig"]), int(r["total"])
            )
        return table

    def corner_classes(self, *, car: str, track: str) -> dict[str, str | None]:
        loaded = self.load_corner_map(car=car, track=track)
        if loaded is None:
            return {}
        map_pk, _ = loaded
        return {
            r["corner_id"]: r["class"]
            for r in self.conn.execute(
                "SELECT corner_id, class FROM corners WHERE map_pk=? ORDER BY corner_id",
                (map_pk,),
            )
        }

    # --- candidate admission ------------------------------------------------

    def admit_pending_candidates(
        self, *, car: str, track: str, cfg: IdentityConfig
    ) -> list[str]:
        """Admit consistently-unmatched corners to the frozen map.

        Clusters unmatched observations in the cohort; a cluster seen on at
        least cfg.min_laps_for_admission DISTINCT laps becomes a new corner
        with the next ID (existing IDs never renumber). Re-links the
        observations and returns the admitted corner IDs — the caller must
        surface them; the map never changes silently.
        """
        loaded = self.load_corner_map(car=car, track=track)
        if loaded is None:
            return []
        map_pk, corner_map = loaded

        rows = self.conn.execute(
            """SELECT o.obs_pk, o.apex_lat, o.apex_lon, o.apex_lap_dist, o.lap_pk
               FROM corner_observations o JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE o.corner_pk IS NULL AND l.car=? AND l.track=?
               ORDER BY o.obs_pk""",
            (car, track),
        ).fetchall()
        clusters: list[dict[str, Any]] = []
        for r in rows:
            best = None
            best_d = math.inf
            for cl in clusters:
                if _gps_ok(r["apex_lat"], r["apex_lon"]) and _gps_ok(cl["lat"], cl["lon"]):
                    d = _meters(r["apex_lat"], r["apex_lon"], cl["lat"], cl["lon"])
                    ok = d <= cfg.match_radius_m
                else:
                    d = abs(r["apex_lap_dist"] - cl["lap_dist"])
                    d = min(d, 1.0 - d)
                    ok = d <= cfg.dist_pct_fallback_radius
                if ok and d < best_d:
                    best, best_d = cl, d
            if best is None:
                clusters.append(
                    {"lat": r["apex_lat"], "lon": r["apex_lon"],
                     "lap_dist": r["apex_lap_dist"], "obs": [r]}
                )
            else:
                best["obs"].append(r)

        admitted: list[str] = []
        next_num = 1 + max(
            (int(c.corner_id[1:]) for c in corner_map.corners), default=0
        )
        with self.conn:
            for cl in clusters:
                lap_pks = {r["lap_pk"] for r in cl["obs"]}
                if len(lap_pks) < cfg.min_laps_for_admission:
                    continue
                corner_id = f"C{next_num:02d}"
                next_num += 1
                cur = self.conn.execute(
                    """INSERT INTO corners (map_pk, corner_id, lat, lon, lap_dist,
                                            n_build_observations)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (map_pk, corner_id,
                     float(np.median([r["apex_lat"] for r in cl["obs"]])),
                     float(np.median([r["apex_lon"] for r in cl["obs"]])),
                     float(np.median([r["apex_lap_dist"] for r in cl["obs"]])),
                     len(cl["obs"])),
                )
                new_pk = int(cur.lastrowid)
                self.conn.executemany(
                    "UPDATE corner_observations SET corner_pk=? WHERE obs_pk=?",
                    [(new_pk, r["obs_pk"]) for r in cl["obs"]],
                )
                admitted.append(corner_id)
        return admitted

    # --- coach outputs ------------------------------------------------------

    def store_coach_output(
        self, *, driver: str, car: str, track: str, payload_version: int,
        prompt_version: str, model: str, output_json: str,
        created_at: str | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO coach_outputs
                   (driver, car, track, payload_version, prompt_version, model,
                    output_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (driver, car, track, payload_version, prompt_version, model,
                 output_json, created_at),
            )
        return int(cur.lastrowid)

    def coach_history(self, *, driver: str, car: str, track: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT output_pk, output_json FROM coach_outputs
               WHERE driver=? AND car=? AND track=? ORDER BY output_pk""",
            (driver, car, track),
        ).fetchall()
        history = []
        for r in rows:
            output = json.loads(r["output_json"])
            history.append({
                "output_pk": int(r["output_pk"]),
                "plan_titles": [p.get("title") for p in output.get("coaching_plan", [])],
            })
        return history

    # --- annotations and chat transcripts -----------------------------------

    def annotate_finding(
        self, *, finding_id: str, status: str, note: str | None = None,
        created_at: str | None = None,
    ) -> int:
        """Record driver intent about a finding. Suppresses it from priority
        framing; the underlying measurement is never deleted."""
        with self.conn:
            cur = self.conn.execute(
                """INSERT OR REPLACE INTO finding_annotations
                   (finding_id, status, note, created_at) VALUES (?, ?, ?, ?)""",
                (finding_id, status, note, created_at),
            )
        return int(cur.lastrowid)

    def annotations(self) -> dict[str, dict[str, Any]]:
        return {
            r["finding_id"]: {"status": r["status"], "note": r["note"]}
            for r in self.conn.execute(
                "SELECT * FROM finding_annotations ORDER BY finding_id"
            )
        }

    def add_chat_turn(
        self, *, session_id: str, bundle_version: int, role: str, content: str,
        evidence_cited: list[str] | None = None,
        effects: dict[str, Any] | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO chat_transcripts
                   (session_id, bundle_version, role, content, evidence_cited, effects)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id, bundle_version, role, content,
                    json.dumps(evidence_cited or [], sort_keys=True),
                    json.dumps(effects or {}, sort_keys=True),
                ),
            )
        return int(cur.lastrowid)

    def chat_session_turns(self, session_id: str) -> list[dict[str, Any]]:
        return [
            {
                "role": r["role"], "content": r["content"],
                "bundle_version": int(r["bundle_version"]),
                "evidence_cited": json.loads(r["evidence_cited"] or "[]"),
                "effects": json.loads(r["effects"] or "{}"),
            }
            for r in self.conn.execute(
                "SELECT * FROM chat_transcripts WHERE session_id=? ORDER BY turn_pk",
                (session_id,),
            )
        ]

    # --- config history -----------------------------------------------------

    def record_config_change(
        self, *, key: str, old_value: str | None, new_value: str, source: str,
        note: str | None = None,
    ) -> int:
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO config_history (key, old_value, new_value, source, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, old_value, new_value, source, note),
            )
        return int(cur.lastrowid)
