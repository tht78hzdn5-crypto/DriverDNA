"""Ranker: vs-self opportunity x repeatability, confidence gates, rollups.

Built in M3. Within a cohort, laps split into faster/slower terciles by lap
time; opportunity = median phase-time difference between terciles for the
corner/phase; repeatability = fraction of sessions where the difference keeps
its sign; rank by the product, always reporting both factors, N, and spread.
Confidence gates (configurable): >= 10 corner-phase samples and >= 2 sessions
per finding; cross-track rollups (within car, within class only) >= 2 tracks.
Every finding carries N, spread, source tag, and evidence IDs.
"""
