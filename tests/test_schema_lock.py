"""M0a schema-lock and absence tests.

Locks the verified Garage61 source contract onto the two real fixtures.
Identities and dirty-data counts are anchored in tests/fixtures/manifest.toml
(filenames carry only a lap ID). Any future export that diverges fails here,
consciously — see docs/SPEC.md, "Source contract".
"""

import math
from functools import lru_cache
from pathlib import Path

import pytest

from driverdna.ingest.contract import (
    EXPECTED_HEADER,
    FORBIDDEN_COLUMN_NAMES,
    collect_facts,
    load_fixture_manifest,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MANIFEST = load_fixture_manifest(FIXTURES_DIR)

parametrized = pytest.mark.parametrize(
    "entry", MANIFEST, ids=[e["lap_id"] for e in MANIFEST]
)


@lru_cache(maxsize=None)
def facts_for(filename: str):
    return collect_facts(FIXTURES_DIR / filename)


@parametrized
def test_header_exact_order(entry):
    assert facts_for(entry["file"]).header == EXPECTED_HEADER


@parametrized
def test_no_forbidden_columns(entry):
    present = set(facts_for(entry["file"]).header) & FORBIDDEN_COLUMN_NAMES
    assert not present, (
        f"channels the contract assumes absent have appeared: {sorted(present)}; "
        "re-verify the contract before building on them"
    )


@parametrized
def test_60hz_duration_matches_manifest_lap_time(entry):
    facts = facts_for(entry["file"])
    assert abs(facts.duration_s - entry["lap_time_s"]) < 0.005, (
        f"rows/60 = {facts.duration_s:.4f}s vs known {entry['lap_time_s']}s — "
        "60 Hz assumption violated"
    )


@parametrized
def test_single_lapdistpct_wrap(entry):
    assert facts_for(entry["file"]).wrap_count == 1


@parametrized
def test_speed_is_meters_per_second(entry):
    facts = facts_for(entry["file"])
    assert facts.speed_min >= 0
    assert 150 < facts.speed_max * 3.6 < 350, (
        "peak speed implausible for m/s units — unit change?"
    )


@parametrized
def test_gps_matches_known_track(entry):
    facts = facts_for(entry["file"])
    assert abs(facts.lat_mean - entry["expected_lat"]) < 0.05
    assert abs(facts.lon_mean - entry["expected_lon"]) < 0.05


@parametrized
def test_steering_is_radians(entry):
    # A degrees channel would exceed 2π by an order of magnitude at full lock.
    assert facts_for(entry["file"]).steering_abs_max < 2 * math.pi


@parametrized
def test_abs_drs_are_string_booleans(entry):
    facts = facts_for(entry["file"])
    assert set(facts.abs_values) <= {"true", "false"}
    assert facts.drs_values == ("false",), "DRS expected all-false in fixtures"


@parametrized
def test_dirty_data_counts_locked(entry):
    facts = facts_for(entry["file"])
    observed = {
        "throttle_over": facts.throttle_over,
        "throttle_under": facts.throttle_under,
        "brake_over": facts.brake_over,
        "brake_under": facts.brake_under,
        "gear0_samples": facts.gear0_samples,
    }
    expected = {k: entry[k] for k in observed}
    assert observed == expected


@parametrized
def test_clutch_pinned_uninformative(entry):
    assert facts_for(entry["file"]).clutch_values == ("1",)


@parametrized
def test_position_type_constant(entry):
    assert facts_for(entry["file"]).position_type_values == ("3",)
