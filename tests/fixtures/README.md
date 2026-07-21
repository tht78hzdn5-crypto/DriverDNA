# Telemetry fixtures

The two real Garage61 exports the source contract (docs/SPEC.md) was verified
against, under their original download names:

| File | Identity | Lap time |
|---|---|---|
| `Garage_61_RH11X7.csv` | Mustang @ Laguna Seca | 1:37.268 |
| `Garage_61_HKWPXX.csv` | GR86 @ Spa-Francorchamps | 2:51.250 |

Garage61 filenames carry only a lap ID — no driver/car/track/lap-time — so
`manifest.toml` records each fixture's verified identity plus the locked
dirty-data counts. The M0a schema-lock tests (`tests/test_schema_lock.py`)
assert the exact header order, 60 Hz timing against the manifest lap times,
single LapDistPct wrap, unit sanity, and the manifest's dirty-data counts.
These fixtures are the regression anchor for the entire pipeline.

Synthetic traces (landmark shapes, double-apex cases, detector edge cases) are
added from M1 onward, in `tests/fixtures/synthetic/`.
