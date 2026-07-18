"""SessionLoader: laps -> cohorts (driver/car/track-config), sessions, runs.

Built in M1. There is no run/stint channel in the data: runs are reconstructed
at ingest from sync/session metadata and lap timestamps (manual-import path:
file timestamps + user-supplied session metadata; filenames carry only a lap
ID), and lap-within-run is therefore a labeled proxy. Lap role is `self` or `reference`; reference laps never enter
self history or trends.
"""
