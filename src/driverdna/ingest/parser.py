"""Garage61Parser: one CSV export -> typed TelemetryLap.

Built in M1, against the verified source contract in docs/SPEC.md: exact
18-column header, 60 Hz with no time column (elapsed = index/60), single
LapDistPct wrap, m/s speeds, radian steering -> degrees, string-boolean
ABS/DRS, real GPS. Dirty data is admitted with structured quality flags;
nothing is silently repaired except pedal clipping to [0, 1], which is flagged
with counts. Filename metadata parsed best-effort, never fatal.
"""
