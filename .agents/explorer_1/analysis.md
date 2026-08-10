# Database Performance Analysis Report — `antigravity/fix-db-performance`

**Author**: Explorer 1 (Read-Only Exploration Agent)  
**Repository**: `c:\Users\benja\driverdna`  
**Target Branch**: `antigravity/fix-db-performance` vs `main`  
**Date**: 2026-07-27  

---

## 1. Executive Summary

This report provides a comprehensive read-only analysis of the performance optimizations introduced in the `antigravity/fix-db-performance` git branch. 

The primary objective of `antigravity/fix-db-performance` was to resolve severe latency and timeout issues on key API endpoints—specifically `/api/cohorts/{slug}/payload` and `/api/driver`. Prior to these changes, generating the driver payload across 30 cohorts hit timeouts exceeding **20 minutes**, rendering the application unusable under standard dataset sizes.

### Key Performance Gains (Verified in `docs/STATUS.md`):
- **Cohort Payload Generation (`/api/cohorts/{slug}/payload`)**: Latency reduced from **40.41s → 12.02s** (~3.4× speedup).
- **Driver Payload Generation (`/api/driver`)**: Latency reduced from **>20 minutes (timeout) → 13.35s** (~100× speedup).

### Summary of Changes:
1. **Database Schema Migration 007**: Added 7 targeted database indexes across core query hot-paths (`laps`, `corner_observations`, `corners`, `metric_values`, `detector_results`, `phase_times`).
2. **Payload Generation Refactoring**: Restructured `build_driver_payload` in `src/driverdna/report/payload.py` to directly fetch required metadata and loss rollups instead of eagerly calling `build_cohort_payload` for all 30 cohorts (which previously re-computed full metrics, findings, coaching sections, phase baselines, and driver model beliefs 30 times over).

---

## 2. Git Branch Diff Analysis

### Commit History (`main..antigravity/fix-db-performance`):
- `09be83d`: `perf: compute only needed data for driver payload`
- `3712493`: `docs: update STATUS.md with database performance optimization details`

### Modified Files Breakdown:
1. **`docs/STATUS.md`**: Updated snapshot status to document the 500/timeout resolution and recorded the benchmark metrics (~3.4× speedup for cohort payload, ~100× speedup for driver payload).
2. **`src/driverdna/db.py`**: Appended Migration 007 (`007 - Performance indexes`) to the `MIGRATIONS` tuple.
3. **`src/driverdna/report/payload.py`**: Refactored `build_driver_payload()` to streamline metadata extraction and defer heavy driver model computations to a single execution.

---

## 3. Database Architecture & Setup

### 3.1 Dual-Backend Support (SQLite & PostgreSQL)
DriverDNA is designed to work seamlessly with both **SQLite** and **PostgreSQL** backends through an abstraction layer in `src/driverdna/db.py`:
- **SQLite**: Default backend for local files and in-memory execution (`:memory:`). Uses `sqlite3` standard library with `sqlite3.Row` row factory. Enables foreign keys via `PRAGMA foreign_keys = ON`.
- **PostgreSQL**: Opt-in backend selected automatically when connection path is a `postgresql://` DSN. Uses `psycopg` v3 driver with `dict_row` row factory.

### 3.2 Connection & Environment Variables
- **`DRIVERDNA_DATABASE_URL`**: App/production database connection string. Handles password redaction (`redact_dsn()`) to ensure credentials never leak into error messages, logs, or HTTP responses.
- **`DRIVERDNA_TEST_DATABASE_URL`**: Local PostgreSQL DSN used for opt-in PostgreSQL unit tests (`tests/conftest.py`). Restricted strictly to local hosts (`localhost`, `127.0.0.1`, `::1`) to prevent accidental `DROP SCHEMA ... CASCADE` on remote instances (e.g. Supabase).

### 3.3 Security & Namespace Controls
- **PostgreSQL Namespace (`PG_SCHEMA = "driverdna"`)**: Tables are isolated in the `driverdna` schema (not `public`). This prevents PostgREST / Supabase auto-exposing unauthenticated REST endpoints for sensitive tables like `laps` or `chat_transcripts`.
- **Row-Level Security (`_harden_postgres`)**: Runs `ALTER TABLE "<table>" ENABLE ROW LEVEL SECURITY` with 0 policies on connect, denying access to anon/authenticated PostgREST roles by default.

### 3.4 Test Fixtures & Synthetic Data
- **Real Telemetry Fixtures (`tests/fixtures/`)**: Contains real recorded CSV lap files (e.g., `Garage_61_59384F.csv`, `Garage_61_593850.csv`) from tracks such as Spa-Francorchamps and Laguna Seca.
- **Fixture Manifest (`tests/fixtures/manifest.toml`)**: Source contract anchor for schema lock tests (`tests/test_schema_lock.py`).
- **Synthetic Generator (`tests/synth.py`)**: Provides helpers (`one_corner_lap()`, `track_lap()`, `warp_time()`, `run_synthetic_lap()`) for deterministic performance testing and edge-case verification.

---

## 4. Schema Migration 007: Performance Indexes

Migration 007 in `src/driverdna/db.py` (lines 250–260) introduces 7 indexes designed to turn $O(N)$ full table scans into $O(\log N)$ index range lookups across hot queries:

```sql
-- Migration 007 - Performance indexes
CREATE INDEX IF NOT EXISTS idx_laps_cohort ON laps(driver, car, track, role);
CREATE INDEX IF NOT EXISTS idx_corner_obs_lap ON corner_observations(lap_pk);
CREATE INDEX IF NOT EXISTS idx_corner_obs_corner ON corner_observations(corner_pk);
CREATE INDEX IF NOT EXISTS idx_metric_values_obs ON metric_values(obs_pk);
CREATE INDEX IF NOT EXISTS idx_detector_results_obs ON detector_results(obs_pk);
CREATE INDEX IF NOT EXISTS idx_phase_times_obs ON phase_times(obs_pk);
CREATE INDEX IF NOT EXISTS idx_corners_map ON corners(map_pk);
```

### Index Impact Analysis:
1. **`idx_laps_cohort ON laps(driver, car, track, role)`**:
   - **Target**: Filtering self laps by cohort (`WHERE role='self' AND driver=? AND car=? AND track=?`).
   - **Impact**: Used by `build_cohort_payload`, `build_driver_payload`, `self_metric_table`, `self_detector_table`, `phase_history`, and `list_cohorts`. Replaces full table scans on `laps`.
2. **`idx_corner_obs_lap ON corner_observations(lap_pk)`**:
   - **Target**: Joining `laps` to `corner_observations` on foreign key `lap_pk`.
   - **Impact**: Accelerates observation lookups for all laps in a cohort.
3. **`idx_corner_obs_corner ON corner_observations(corner_pk)`**:
   - **Target**: Querying `corner_observations` by `corner_pk`.
   - **Impact**: Speeds up landmark position lookups and corner-centric observation aggregation.
4. **`idx_metric_values_obs ON metric_values(obs_pk)`**:
   - **Target**: Joining `corner_observations` to `metric_values`.
   - **Impact**: Drastically reduces join cost when fetching metric vectors in `self_metric_table` and belief scoring.
5. **`idx_detector_results_obs ON detector_results(obs_pk)`**:
   - **Target**: Joining `corner_observations` to `detector_results`.
   - **Impact**: Accelerates detector summary aggregations in `self_detector_table`.
6. **`idx_phase_times_obs ON phase_times(obs_pk)`**:
   - **Target**: Joining `corner_observations` to `phase_times`.
   - **Impact**: Speeds up phase time history extraction in `phase_history`.
7. **`idx_corners_map ON corners(map_pk)`**:
   - **Target**: Filtering corners by corner map (`WHERE map_pk=?`).
   - **Impact**: Accelerates corner classification and position resolution in `corner_classes` and `corner_positions`.

---

## 5. Detailed Query Comparison (Before vs. After)

### 5.1 Driver Payload Assembly Logic (`build_driver_payload`)

#### BEFORE (`main` branch):
```python
def build_driver_payload(db: Database, config: DriverDNAConfig) -> dict[str, Any]:
    cohorts = list_cohorts(db)
    # Eagerly builds full cohort payload for EVERY cohort in the database!
    payloads = [build_cohort_payload(db, **c, config=config) for c in cohorts]

    by_car_class: dict[str, dict[str, Any]] = {}
    for p in payloads:
        car = p["cohort"]["car"]
        classes = {c["corner_id"]: c["class"] for c in p["corner_map"]}
        for corner_id, phases in p["cumulative_loss"]["per_corner"].items():
            cls = classes.get(corner_id) or "unclassified"
            entry = by_car_class.setdefault(car, {}).setdefault(
                cls, {"loss_s": 0.0, "tracks": set()}
            )
            entry["loss_s"] += sum(phases.values())
            entry["tracks"].add(p["cohort"]["track"])
    ...
```
**Bottlenecks in BEFORE:**
- Calling `build_cohort_payload` for 30 cohorts executed:
  - 30× full metric table lookups (`self_metric_table`).
  - 30× phase baseline calculations and phase history queries.
  - 30× full findings engine runs (`vs_self_findings`, `vs_principle_findings`, `vs_reference_findings`).
  - 30× full belief calculations across the entire driver history (`driver_model_section`).
  - 30× coaching section and incident section generations.
- **Computational Complexity**: $O(N_{\text{cohorts}} \times (N_{\text{corners}} \cdot N_{\text{phases}} \cdot N_{\text{metrics}} + N_{\text{findings}} + N_{\text{beliefs}}))$. For 30 cohorts, this triggered tens of thousands of database operations, leading to HTTP 500 / gateway timeouts (>20 mins).

#### AFTER (`antigravity/fix-db-performance` branch):
```python
def build_driver_payload(db: Database, config: DriverDNAConfig) -> dict[str, Any]:
    cohorts_metadata = []
    by_car_class: dict[str, dict[str, Any]] = {}
    driver_name = None

    for c in list_cohorts(db):
        driver = c["driver"]
        car = c["car"]
        track = c["track"]
        if driver_name is None:
            driver_name = driver

        laps = db.conn.execute(
            """SELECT lap_id, duration_s, session_key
               FROM laps WHERE role='self' AND driver=? AND car=? AND track=?
               ORDER BY lap_pk""",
            (driver, car, track),
        ).fetchall()
        
        sessions = {r["session_key"] for r in laps if r["session_key"] is not None}
        
        cohorts_metadata.append({
            "driver": driver, "car": car, "track": track,
            "n_laps": len(laps), "n_sessions": len(sessions),
            "lap_durations_s": [round(float(r["duration_s"]), 4) for r in laps],
            "lap_ids": [r["lap_id"] for r in laps],
            "lap_delta_s": [
                round(float(r["duration_s"]) - min(float(x["duration_s"]) for x in laps), 4)
                for r in laps
            ] if laps else [],
        })

        loaded = db.load_corner_map(car=car, track=track)
        map_pk, corner_map = loaded if loaded else (None, None)
        stored_windows = db.load_corner_windows(map_pk) if map_pk else {}
        windows_by_corner = {
            cid: phase_windows_from_stored(w) for cid, w in sorted(stored_windows.items())
        }
        classes = db.corner_classes(car=car, track=track)

        loss = cumulative_loss(
            db, driver=driver, car=car, track=track,
            windows_by_corner=windows_by_corner, config=config,
        ) if windows_by_corner else {"per_corner": {}}

        for corner_id, phases in loss.get("per_corner", {}).items():
            cls = classes.get(corner_id) or "unclassified"
            entry = by_car_class.setdefault(car, {}).setdefault(
                cls, {"loss_s": 0.0, "tracks": set()}
            )
            entry["loss_s"] += sum(phases.values())
            entry["tracks"].add(track)

    ...
    driver_model = None
    if driver_name is not None:
        driver_model = driver_model_section(db, driver=driver_name, config=config)

    return {
        "payload_version": PAYLOAD_VERSION,
        "cohorts": cohorts_metadata,
        "cross_track_rollups": rollups,
        "driver_model": driver_model,
        "note": "cross-car claims are computed but never reported in v1",
    }
```
**Improvements in AFTER:**
- Bypasses metric tables, phase baselines, findings generation, coaching sections, and incident generation for driver-level rollups.
- Fetches lightweight lap metadata directly via a targeted index query on `laps`.
- Runs `cumulative_loss()` directly per cohort to obtain cross-track loss rollups.
- Computes `driver_model_section()` **exactly once** at the end.
- **Computational Complexity**: Reduced to $O(N_{\text{cohorts}} \times N_{\text{corners}} \cdot N_{\text{phases}} + N_{\text{beliefs}})$, bringing total latency down to **13.35s** (~100× speedup).

---

### 5.2 Key SQL Queries (Before vs. After Optimization)

#### 1. Laps Cohort Lookup (`laps` table)
```sql
SELECT lap_pk, lap_id, duration_s, session_key, quality_flags 
FROM laps 
WHERE role='self' AND driver=? AND car=? AND track=? 
ORDER BY lap_pk;
```
- **Before Migration 007**: Scanned all rows in `laps` (Full Table Scan).
- **After Migration 007**: Uses `idx_laps_cohort (driver, car, track, role)` to perform a fast index range scan.

#### 2. Metric Values Aggregation (`self_metric_table`)
```sql
SELECT c.corner_id, mv.name, mv.value 
FROM metric_values mv
JOIN corner_observations o ON o.obs_pk = mv.obs_pk
JOIN corners c ON c.corner_pk = o.corner_pk
JOIN laps l ON l.lap_pk = o.lap_pk
WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
  AND mv.value IS NOT NULL
ORDER BY c.corner_id, mv.name, l.lap_pk, o.span_start;
```
- **Before Migration 007**: Full table scans on `laps`, `corner_observations`, and `metric_values`.
- **After Migration 007**: Index scan on `idx_laps_cohort` -> index lookup on `idx_corner_obs_lap` -> index lookup on `idx_metric_values_obs`.

#### 3. Phase History Query (`phase_history`)
```sql
SELECT p.time_s, l.lap_pk, l.session_key, o.obs_pk
FROM phase_times p
JOIN corner_observations o ON o.obs_pk = p.obs_pk
JOIN corners c ON c.corner_pk = o.corner_pk
JOIN laps l ON l.lap_pk = o.lap_pk
WHERE l.car=? AND l.track=? AND c.corner_id=? AND p.phase=?
  AND l.role=? AND l.driver=?
ORDER BY l.lap_pk, o.span_start;
```
- **Before Migration 007**: Full table scans across 4 tables.
- **After Migration 007**: Indexed access path via `idx_laps_cohort` and `idx_phase_times_obs`.

#### 4. Detector Summary Table (`self_detector_table`)
```sql
SELECT c.corner_id, d.detector, SUM(d.triggered) AS trig, COUNT(*) AS total
FROM detector_results d
JOIN corner_observations o ON o.obs_pk = d.obs_pk
JOIN corners c ON c.corner_pk = o.corner_pk
JOIN laps l ON l.lap_pk = o.lap_pk
WHERE l.role='self' AND l.driver=? AND l.car=? AND l.track=?
GROUP BY c.corner_id, d.detector
ORDER BY c.corner_id, d.detector;
```
- **Before Migration 007**: Unindexed scan over `detector_results`.
- **After Migration 007**: Index scan using `idx_detector_results_obs`.

#### 5. Corner Map Lookup (`corner_classes`, `corner_positions`)
```sql
SELECT corner_id, class FROM corners WHERE map_pk=? ORDER BY corner_id;
```
- **Before Migration 007**: Scanned full `corners` table.
- **After Migration 007**: Filtered via `idx_corners_map (map_pk)`.

---

## 6. Recommendations for Benchmark Suite Design (Worker 1)

Worker 1 will build programmatic benchmark scripts in `c:\Users\benja\teamwork_projects\db_perf_analysis` to measure latency, execution time, and throughput of these modified queries.

### 6.1 Recommended Project Structure (`c:\Users\benja\teamwork_projects\db_perf_analysis`)
```
c:\Users\benja\teamwork_projects\db_perf_analysis\
├── README.md                  # Instructions for executing benchmarks
├── requirements.txt           # Benchmark dependencies (pytest, pytest-benchmark, psycopg, matplotlib/pandas)
├── config.py                  # Database connection parameters & benchmark configuration
├── seed_data.py               # Data generator script for scale testing (30+ cohorts, 1000s of laps/metrics)
├── benchmarks/
│   ├── test_index_perf.py     # Micro-benchmarks comparing query performance WITH vs WITHOUT Migration 007 indexes
│   ├── test_payload_perf.py   # Macro-benchmarks for build_cohort_payload vs build_driver_payload (Before vs After algorithm)
│   ├── test_api_endpoints.py  # HTTP benchmark for /api/cohorts/{slug}/payload and /api/driver
│   └── test_concurrency.py    # Throughput/QPS load testing under concurrent database read connections
└── reports/                   # Output directory for generated CSV/JSON benchmark logs and latency distribution charts
```

### 6.2 Data Scale Generation Strategy
To properly stress-test the database and simulate production workloads:
1. Use `seed_data.py` to populate a synthetic benchmark database containing:
   - **Cohorts**: At least **30 distinct cohorts** (combinations of driver, car, track).
   - **Laps**: 20–50 self laps per cohort (~1,000 total laps).
   - **Corner Observations**: ~15,000 observations across all corners.
   - **Metric Values**: ~150,000 metric rows (`metric_values`).
   - **Detector Results**: ~45,000 detector result rows (`detector_results`).
   - **Phase Times**: ~45,000 phase time rows (`phase_times`).

### 6.3 Micro-Benchmark Design (Indexes)
In `benchmarks/test_index_perf.py`, Worker 1 should measure single-query execution times with indexes present versus indexes dropped:
- Execute `EXPLAIN QUERY PLAN` (SQLite) / `EXPLAIN ANALYZE` (PostgreSQL) for each of the 5 queries listed in Section 5.2.
- Measure average, p50, p90, and p99 latency across 100 iterations.
- Test against both **SQLite** (`:memory:` and disk-backed `.db`) and **PostgreSQL**.

### 6.4 Macro-Benchmark Design (Payload Construction)
In `benchmarks/test_payload_perf.py`, Worker 1 should benchmark:
1. `build_cohort_payload()` across single cohorts.
2. `build_driver_payload()` using the legacy eager approach vs. the new refactored algorithm.
3. Compare wall-clock execution time, peak memory usage (via `tracemalloc`), and total SQL queries executed.

### 6.5 Concurrency & Throughput Testing
In `benchmarks/test_concurrency.py`:
- Use `concurrent.futures.ThreadPoolExecutor` or `asyncio` + `httpx` to send concurrent requests to `/api/cohorts/{slug}/payload` and `/api/driver`.
- Measure Requests Per Second (RPS / QPS) at concurrency levels 1, 5, 10, and 20.
- Verify database connection behavior under high concurrency for both SQLite (`check_same_thread=False`) and PostgreSQL (`psycopg` pool).

---
