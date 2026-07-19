"""M1 parser tests: real fixtures + synthetic malformed inputs."""

from pathlib import Path

import numpy as np
import pytest

from driverdna.ingest.contract import EXPECTED_HEADER, load_fixture_manifest
from driverdna.ingest.parser import FlagCode, ParseError, parse_lap

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MANIFEST = load_fixture_manifest(FIXTURES_DIR)

parametrized = pytest.mark.parametrize(
    "entry", MANIFEST, ids=[e["lap_id"] for e in MANIFEST]
)


def write_csv(path: Path, n: int = 120, mutate=None) -> Path:
    """Write a minimal contract-shaped export (single wrap, clean values)."""
    ldp = [f"{v:.6f}" for v in np.linspace(0.001, 0.999, n - 1)] + ["0.0005"]
    cols: dict[str, list[str]] = {
        "Speed": ["30.0"] * n,
        "LapDistPct": ldp,
        "Lat": ["36.58"] * n,
        "Lon": ["-121.75"] * n,
        "Brake": ["0"] * n,
        "Throttle": ["0.5"] * n,
        "RPM": ["4000"] * n,
        "SteeringWheelAngle": ["0.1"] * n,
        "Gear": ["3"] * n,
        "Clutch": ["1"] * n,
        "ABSActive": ["false"] * n,
        "DRSActive": ["false"] * n,
        "LatAccel": ["0"] * n,
        "LongAccel": ["0"] * n,
        "VertAccel": ["9.8"] * n,
        "Yaw": ["0"] * n,
        "YawRate": ["0"] * n,
        "PositionType": ["3"] * n,
    }
    if mutate:
        mutate(cols)
    header = [c for c in EXPECTED_HEADER if c in cols]
    lines = [",".join(header)]
    length = len(next(iter(cols.values())))
    for i in range(length):
        lines.append(",".join(cols[c][i] for c in header))
    path.write_text("\n".join(lines) + "\n")
    return path


# --- Real fixtures ---------------------------------------------------------


@parametrized
def test_fixture_parses_clean(entry):
    lap = parse_lap(FIXTURES_DIR / entry["file"])
    assert lap.lap_id == entry["lap_id"]
    assert abs(lap.duration_s - entry["lap_time_s"]) < 0.005
    assert lap.n_samples == len(lap.speed) == len(lap.elapsed_s)
    # Only expected flag on the real files is clipped_pedal (when counts > 0).
    codes = {f.code for f in lap.quality_flags}
    assert codes <= {FlagCode.CLIPPED_PEDAL}


@parametrized
def test_fixture_pedals_clipped_and_flagged(entry):
    lap = parse_lap(FIXTURES_DIR / entry["file"])
    assert float(lap.throttle.min()) >= 0.0 and float(lap.throttle.max()) <= 1.0
    assert float(lap.brake.min()) >= 0.0 and float(lap.brake.max()) <= 1.0
    flag = lap.flag(FlagCode.CLIPPED_PEDAL)
    assert flag is not None, "both fixtures have pedal excursions"
    assert flag.detail == {
        "throttle_over": entry["throttle_over"],
        "throttle_under": entry["throttle_under"],
        "brake_over": entry["brake_over"],
        "brake_under": entry["brake_under"],
    }


@parametrized
def test_fixture_units_and_types(entry):
    lap = parse_lap(FIXTURES_DIR / entry["file"])
    # Steering converted to degrees: peaks range from ~150° up to ~430° at
    # slow hairpins (road-car wheel past a full turn). If radians hadn't been
    # converted the max would be single digits, failing the lower bound.
    assert 90 < float(np.abs(lap.steering_deg).max()) < 720
    assert lap.abs_active.dtype == np.bool_ and lap.drs_active.dtype == np.bool_
    assert not lap.drs_active.any()
    assert lap.gear.dtype == np.int64
    assert set(np.unique(lap.position_type)) <= {1, 2, 3, 4, 5}


@parametrized
def test_fixture_lap_dist_continuous(entry):
    lap = parse_lap(FIXTURES_DIR / entry["file"])
    # Unwrapped distance spans one full lap and never jumps backwards.
    assert abs((lap.lap_dist[-1] - lap.lap_dist[0]) - 1.0) < 0.01
    assert float(np.diff(lap.lap_dist).min()) > -0.01


# --- Synthetic faults ------------------------------------------------------


def test_clean_synthetic_has_no_flags(tmp_path):
    lap = parse_lap(write_csv(tmp_path / "Garage_61_SYNTH1.csv"))
    assert lap.quality_flags == []
    assert lap.lap_id == "SYNTH1"


def test_malformed_float_becomes_nan_and_flagged(tmp_path):
    def mutate(cols):
        cols["Speed"][5] = "abc"

    lap = parse_lap(write_csv(tmp_path / "Garage_61_BADF.csv", mutate=mutate))
    assert np.isnan(lap.speed[5])
    flag = lap.flag(FlagCode.MALFORMED_VALUES)
    assert flag is not None and flag.detail["counts"] == {"Speed": 1}


def test_malformed_bool_becomes_false_and_flagged(tmp_path):
    def mutate(cols):
        cols["ABSActive"][3] = "TRUE"  # contract booleans are lowercase

    lap = parse_lap(write_csv(tmp_path / "Garage_61_BADB.csv", mutate=mutate))
    assert not bool(lap.abs_active[3])
    flag = lap.flag(FlagCode.MALFORMED_VALUES)
    assert flag is not None and flag.detail["counts"] == {"ABSActive": 1}


def test_missing_channel_flagged_not_fatal(tmp_path):
    def mutate(cols):
        del cols["Clutch"]

    lap = parse_lap(write_csv(tmp_path / "Garage_61_NOCL.csv", mutate=mutate))
    flag = lap.flag(FlagCode.MISSING_CHANNEL)
    assert flag is not None and flag.detail["channels"] == ["Clutch"]
    assert np.isnan(lap.clutch).all()
    assert lap.flag(FlagCode.MALFORMED_VALUES) is None


def test_line_to_line_lap_is_clean(tmp_path):
    # A complete lap sampled exactly start/finish-line to line: 0 wraps, full
    # coverage. This is not a defect — it must parse clean (no wrap/coverage
    # flag), only the clip flag the synthetic pedals earn.
    def mutate(cols):
        n = len(cols["LapDistPct"])
        cols["LapDistPct"] = [f"{v:.6f}" for v in np.linspace(0.0, 1.0, n)]

    lap = parse_lap(write_csv(tmp_path / "Garage_61_LINE2LINE.csv", mutate=mutate))
    assert lap.flag(FlagCode.UNEXPECTED_WRAP_COUNT) is None
    assert lap.flag(FlagCode.INCOMPLETE_LAP) is None
    assert float(lap.lap_dist[0]) == 0.0 and float(lap.lap_dist[-1]) == 1.0


def test_partial_lap_flagged_incomplete(tmp_path):
    # A file covering only part of a lap (0 wraps but short span) must be
    # flagged, not silently accepted as complete.
    def mutate(cols):
        n = len(cols["LapDistPct"])
        cols["LapDistPct"] = [f"{v:.6f}" for v in np.linspace(0.25, 0.72, n)]

    lap = parse_lap(write_csv(tmp_path / "Garage_61_PARTIAL.csv", mutate=mutate))
    flag = lap.flag(FlagCode.INCOMPLETE_LAP)
    assert flag is not None and flag.detail["coverage"] < 0.5
    assert lap.flag(FlagCode.UNEXPECTED_WRAP_COUNT) is None


def test_multi_wrap_flagged_and_unwrapped(tmp_path):
    def mutate(cols):
        n = len(cols["LapDistPct"])
        third = n // 3
        seq = (
            list(np.linspace(0.4, 0.99, third))
            + list(np.linspace(0.0, 0.99, third))
            + list(np.linspace(0.0, 0.6, n - 2 * third))
        )
        cols["LapDistPct"] = [f"{v:.6f}" for v in seq]

    lap = parse_lap(write_csv(tmp_path / "Garage_61_MULTI.csv", mutate=mutate))
    flag = lap.flag(FlagCode.UNEXPECTED_WRAP_COUNT)
    assert flag is not None and flag.detail["observed"] == 2
    assert float(np.diff(lap.lap_dist).min()) > -0.01


def test_synthetic_pedal_clipping(tmp_path):
    def mutate(cols):
        cols["Throttle"][10] = "1.02"
        cols["Throttle"][11] = "-0.03"
        cols["Brake"][12] = "-0.5"

    lap = parse_lap(write_csv(tmp_path / "Garage_61_CLIP.csv", mutate=mutate))
    assert lap.throttle[10] == 1.0 and lap.throttle[11] == 0.0 and lap.brake[12] == 0.0
    flag = lap.flag(FlagCode.CLIPPED_PEDAL)
    assert flag is not None
    assert flag.detail == {
        "throttle_over": 1,
        "throttle_under": 1,
        "brake_over": 0,
        "brake_under": 1,
    }


def test_empty_file_raises(tmp_path):
    p = tmp_path / "Garage_61_EMPTY.csv"
    p.write_text("")
    with pytest.raises(ParseError):
        parse_lap(p)


def test_header_only_raises(tmp_path):
    p = tmp_path / "Garage_61_HDR.csv"
    p.write_text(",".join(EXPECTED_HEADER) + "\n")
    with pytest.raises(ParseError):
        parse_lap(p)


def test_foreign_filename_gives_no_lap_id(tmp_path):
    lap = parse_lap(write_csv(tmp_path / "someones-lap.csv"))
    assert lap.lap_id is None
    assert lap.flag(FlagCode.METADATA_FAILURE) is None
