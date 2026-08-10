## 2026-07-27T20:56:48Z
You are Worker 1, a versatile worker agent. Your working directory is `c:\Users\benja\driverdna\.agents\worker_1`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your mission is to perform Programmatic Benchmarking (Requirement R1) of the database performance improvements introduced in `antigravity/fix-db-performance`.

Context & References:
- Read Explorer 1's findings: `c:\Users\benja\driverdna\.agents\explorer_1\handoff.md` and `c:\Users\benja\driverdna\.agents\explorer_1\analysis.md`.
- Read application database code in `c:\Users\benja\driverdna\src\driverdna\db.py` and `c:\Users\benja\driverdna\src\driverdna\report\payload.py`.
- Benchmark Working Directory: `c:\Users\benja\teamwork_projects\db_perf_analysis` (create this folder if it does not exist).

Key Requirements:
1. READ-ONLY APPLICATION CODE (R3): Do NOT modify any source code files in `c:\Users\benja\driverdna`. All benchmark scripts, configuration, fixtures, and reports MUST be created in `c:\Users\benja\teamwork_projects\db_perf_analysis`.
2. PROGRAMMATIC BENCHMARKING (R1):
   - Write python benchmark scripts in `c:\Users\benja\teamwork_projects\db_perf_analysis`:
     a) Data scaling / fixture setup (`seed_benchmark_db.py`): Populates or configures a local test database with representative data (cohorts, laps, corner_observations, metric_values, detector_results, phase_times, corners).
     b) Micro-benchmarks (`benchmark_queries.py`): Measures latency (mean, median, p90, p99 in ms) and execution time for each of the 5 modified queries identified by Explorer 1, comparing execution WITH Migration 007 indexes vs WITHOUT indexes (or indexed vs unindexed table scan).
     c) Macro-benchmarks (`benchmark_payloads.py`): Measures execution time, query count, and memory overhead for `build_cohort_payload` and `build_driver_payload` (comparing the legacy eager per-cohort driver payload assembly algorithm vs the optimized metadata rollup algorithm).
     d) Throughput benchmark (`benchmark_throughput.py`): Measures QPS / throughput (queries/sec or ops/sec) under parallel query workloads.
3. EXECUTE BENCHMARKS:
   - Run the benchmark scripts against the local database using Python / PowerShell.
   - Capture real, verifiable, quantifiable metrics (latency in ms, execution time in seconds, throughput in ops/sec).
   - Export benchmark execution results to JSON/CSV formatted log files in `c:\Users\benja\teamwork_projects\db_perf_analysis\benchmark_results.json` and `c:\Users\benja\teamwork_projects\db_perf_analysis\reports\`.
4. DELIVERABLES & REPORTING:
   - Save all benchmark scripts in `c:\Users\benja\teamwork_projects\db_perf_analysis`.
   - Update `c:\Users\benja\driverdna\.agents\worker_1\progress.md` after each step.
   - Write a complete `handoff.md` in `c:\Users\benja\driverdna\.agents\worker_1\handoff.md` detailing the script implementations, execution commands, and exact quantitative results obtained.
   - Send a message to parent (`31ef0cb8-5342-4121-b9c9-c7dc6c24699b`) referencing your `handoff.md` and results.
