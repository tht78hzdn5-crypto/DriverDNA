"""AttributionEngine: time-at-distance deltas over canonical phase windows.

Built in M3. t(LapDistPct) interpolated per lap. Phase windows are CANONICAL
per corner — frozen from cross-lap median landmark positions (entry = brake
start -> turn-in; mid = turn-in -> apex; exit = apex -> full throttle or
corner exit) — so every lap is measured over the identical stretch of track;
per-lap landmarks feed technique metrics, never the measurement windows.
Baselines are robust: statistical outliers screened, default baseline
median-of-top-3 executions (configurable; single best shown, labeled).
Composite best labeled theoretical. Reference envelopes labeled "gap".
"""
