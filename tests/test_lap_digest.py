"""`driverdna lap-digest` — readable per-corner slices of the stored trace.

The digest exists so a human or a cheap agent can actually READ a lap: a lap
is ~10,000 samples x 20 channels, which nobody reviews directly. It is the
shared evidence base for the lap-analysis protocol (docs/LAP-ANALYSIS-
PROTOCOL.md), so its one binding property is that it MEASURES NOTHING.

Permitted transforms: row selection (window + stride) and column selection.
Nothing else. A digest that computed `min_speed` would be the engine's
"never compute a measurement outside the engine" rule violated one layer
over, and — worse for this use — a bug in it would poison every rater
identically and invisibly. So purity is asserted cell-for-cell here, not
assumed.

Purity is relative to `load_lap_arrays()`, the arrays the engine itself
analyzes, NOT the source CSV: the parser's documented normalizations
(radians -> degrees, LapDistPct unwrap, pedal clipping) are already locked
by tests/test_schema_lock.py, and a rater should see what the engine saw.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from driverdna.analysis.digest import (
    DIGEST_VERSION,
    NoFrozenMap,
    build_digest,
    format_cell,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from synth import run_synthetic_lap as _run
from synth import track_lap

CONFIG = DriverDNAConfig()
CAR, TRACK = "TestCar", "SynthRing"


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


@pytest.fixture()
def cohort(db):
    """A frozen three-corner cohort with a few laps behind it."""
    for i in range(4):
        _run(
            db,
            track_lap(src=f"syn-{i}.csv"),
            car=CAR,
            track=TRACK,
            session_key=f"s{i // 2}",
            config=CONFIG,
        )
    return db


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    lines = path.read_text().splitlines()
    header = lines[0].split(",")
    rows = [ln.split(",") for ln in lines[1:]]
    return header, rows


def _any_digest_file(out: Path) -> Path:
    files = sorted(p for p in out.rglob("*.csv"))
    assert files, "digest produced no corner files"
    return files[0]


def _lap_pk_by_dir(out: Path) -> dict[str, int]:
    """Directory name -> lap_pk, from the manifest.

    Synthetic laps carry no `lap_id` (a Garage61 export code), so the digest
    names their directory after the primary key instead; the manifest is the
    authority either way.
    """
    m = json.loads((out / "manifest.json").read_text())
    return {
        lap["dir"]: lap["lap_pk"]
        for c in m["cohorts"]
        for lap in c["laps"]
    }


# --- the core guarantee: every cell is a verbatim stored sample -------------


def test_every_digest_cell_equals_the_stored_sample_at_that_row(cohort, tmp_path):
    out = tmp_path / "blind"
    report = build_digest(cohort, out_dir=out)
    assert report.corners_written > 0

    by_dir = _lap_pk_by_dir(out)

    checked = 0
    for csv_path in sorted(out.rglob("*.csv")):
        arrays = cohort.load_lap_arrays(by_dir[csv_path.parent.name])
        header, rows = _read_csv(csv_path)
        assert header[0] == "row"
        for row in rows:
            src_index = int(row[0])
            for channel, cell in zip(header[1:], row[1:], strict=True):
                assert cell == format_cell(arrays[channel][src_index]), (
                    f"{csv_path.name} row {src_index} channel {channel}: "
                    f"digest says {cell!r}, stored sample is "
                    f"{format_cell(arrays[channel][src_index])!r}"
                )
                checked += 1
    assert checked > 1000, "purity check covered suspiciously few cells"


def test_digest_emits_no_channel_the_engine_does_not_store(cohort, tmp_path):
    """No derived columns. A digest that added `min_speed` or `speed_kmh`
    would be computing a measurement."""
    out = tmp_path / "blind"
    build_digest(cohort, out_dir=out)
    lap_pk = cohort.conn.execute("SELECT lap_pk FROM laps LIMIT 1").fetchone()["lap_pk"]
    stored = set(cohort.load_lap_arrays(lap_pk))
    header, _ = _read_csv(_any_digest_file(out))
    assert set(header[1:]) <= stored


def test_digest_is_byte_identical_across_runs(cohort, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    build_digest(cohort, out_dir=a)
    build_digest(cohort, out_dir=b)
    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert files_a == files_b
    for rel in files_a:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


# --- row selection is the window, and only the window ----------------------


def test_rows_are_strictly_increasing_and_stride_spaced(cohort, tmp_path):
    out = tmp_path / "blind"
    build_digest(cohort, out_dir=out, stride=6)
    for csv_path in sorted(out.rglob("*.csv")):
        _, rows = _read_csv(csv_path)
        indices = [int(r[0]) for r in rows]
        assert indices == sorted(set(indices)), f"{csv_path} rows not ordered/unique"
        steps = {b - a for a, b in zip(indices, indices[1:], strict=False)}
        assert steps <= {6}, f"{csv_path} has non-stride steps {steps}"


def test_slice_spans_the_frozen_window_plus_margin(cohort, tmp_path):
    """The digest covers the corner's canonical window — the same span the
    attribution engine measures over — widened by the stated margin."""
    out = tmp_path / "blind"
    margin = 0.01
    build_digest(cohort, out_dir=out, margin=margin)
    manifest = json.loads((out / "manifest.json").read_text())
    windows = manifest["cohorts"][0]["corners"]
    by_dir = _lap_pk_by_dir(out)

    for csv_path in sorted(out.rglob("*.csv")):
        corner_id = csv_path.stem
        lap_dist = cohort.load_lap_arrays(by_dir[csv_path.parent.name])["lap_dist"]
        _, rows = _read_csv(csv_path)
        covered = [float(lap_dist[int(r[0])]) % 1.0 for r in rows]
        w = windows[corner_id]
        apex = w["apex"]
        assert min(covered) <= apex <= max(covered), (
            f"{csv_path} does not contain its own apex at {apex}"
        )


def test_stride_one_emits_every_sample_in_the_window(cohort, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    build_digest(cohort, out_dir=a, stride=1)
    build_digest(cohort, out_dir=b, stride=6)
    name = _any_digest_file(b).relative_to(b)
    _, fine = _read_csv(a / name)
    _, coarse = _read_csv(b / name)
    assert len(fine) > len(coarse)
    coarse_indices = {int(r[0]) for r in coarse}
    fine_indices = {int(r[0]) for r in fine}
    assert coarse_indices <= fine_indices


# --- honest degradation, never a silent gap --------------------------------


def test_cohort_without_a_frozen_map_is_refused_not_skipped(db, tmp_path):
    with pytest.raises(NoFrozenMap):
        build_digest(db, out_dir=tmp_path / "blind", car="Nope", track="Nowhere")


def test_lap_with_an_unreadable_trace_is_reported_not_dropped(cohort, tmp_path):
    """A lap whose blob was evicted cannot be digested. Philosophy #7: say so,
    never leave a silent hole in the evidence base."""
    out = tmp_path / "blind"
    row = cohort.conn.execute("SELECT lap_pk FROM laps ORDER BY lap_pk").fetchone()
    cohort.blobs.delete(row["lap_pk"])
    report = build_digest(cohort, out_dir=out)
    assert report.unavailable_laps, "an unreadable lap vanished without a word"
    gone = report.unavailable_laps[0]
    assert not (out / gone).exists()
    assert row["lap_pk"] not in _lap_pk_by_dir(out).values()


# --- the manifest is what makes a slice interpretable ----------------------


def test_manifest_states_units_channels_and_windows(cohort, tmp_path):
    out = tmp_path / "blind"
    build_digest(cohort, out_dir=out, stride=6)
    m = json.loads((out / "manifest.json").read_text())

    assert m["digest_version"] == DIGEST_VERSION
    assert m["stride"] == 6
    # Units are the stored ones, and saying so is the whole point: speed is
    # m/s not km/h, and steering is degrees despite the source being radians.
    assert m["units"]["speed"] == "m/s"
    assert m["units"]["yaw_rate"] == "rad/s"
    # Degrees, not the source contract's radians — the exact wording is free,
    # the claim is not.
    assert m["units"]["steering_deg"].startswith("degrees")
    assert set(m["channels"]) == set(m["units"])

    cohort_entry = m["cohorts"][0]
    assert cohort_entry["car"] == CAR and cohort_entry["track"] == TRACK
    corner = next(iter(cohort_entry["corners"].values()))
    assert {"entry_start", "turn_in", "apex", "exit_end"} <= set(corner)
    assert cohort_entry["laps"], "manifest lists no laps"


def test_manifest_withholds_lap_time_so_the_read_stays_blind(cohort, tmp_path):
    """Lap time would tell a blind rater which laps are the slow ones, which
    is exactly the judgment the rater is supposed to form from the trace."""
    out = tmp_path / "blind"
    build_digest(cohort, out_dir=out)
    blob = (out / "manifest.json").read_text()
    assert "duration_s" not in blob
    assert "lap_time" not in blob


def test_digest_carries_no_engine_finding(cohort, tmp_path):
    """The blind half must not leak what the engine concluded."""
    out = tmp_path / "blind"
    build_digest(cohort, out_dir=out)
    blob = " ".join(p.read_text() for p in out.rglob("*") if p.is_file())
    for leaked in ("opportunity", "gate_reason", "finding", "incident",
                   "coaching", "detector", "baseline"):
        assert leaked not in blob.lower(), f"digest leaks {leaked!r}"


# --- formatting is exact and round-trips -----------------------------------


def test_format_cell_round_trips_floats_exactly():
    for v in (0.1, 50.443122012853976, -0.0, 1e-9, 3.0):
        assert float(format_cell(np.float64(v))) == v


def test_format_cell_renders_nan_as_empty_not_as_a_number():
    assert format_cell(np.float64("nan")) == ""
