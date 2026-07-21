"""Incident detection + characterization (Layers 1-2).

Synthetic traces exercise each detector and each mechanism in isolation; the
real committed blind-test laps (tests/fixtures/spa-blind-2026-07/) are the
ground-truth anchor — 9XVJTW's La Source spin and 9PH9M2's Bus Stop near-stop
must be found on real telemetry, and every clean lap must stay silent.
"""

from pathlib import Path

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.incidents import scan_incidents
from driverdna.ingest.parser import parse_lap
from synth import make_lap

CFG = DriverDNAConfig().incidents
FIX = Path(__file__).parent / "fixtures" / "spa-blind-2026-07"


@pytest.fixture()
def tmp_db():
    from driverdna.db import Database

    with Database.open(":memory:") as database:
        yield database


def _base(n=1800):
    """A clean lap: 180 km/h, full throttle, on track, no rotation."""
    return make_lap(n)


def _inject_spin(lap, at, *, brake=0.0, throttle=1.0, throttle_before=None):
    """A steering reversal (-80 -> +80 deg) with a yaw spike at `at`."""
    lap.steering_deg[at : at + 12] = np.linspace(-80.0, 80.0, 12)
    lap.yaw_rate[at : at + 12] = 1.0
    lap.speed[at : at + 20] = 20.0  # rotation scrubs speed
    if throttle_before is not None:
        lap.throttle[at - 10 : at] = throttle_before
    lap.throttle[at : at + 12] = throttle
    lap.brake[at : at + 12] = brake


# --- Detection (Layer 1) ---------------------------------------------------


def test_near_stop_detected():
    lap = _base()
    lap.speed[900:960] = 3.0  # ~11 km/h for 1 s
    incs = scan_incidents(lap, corner_positions={}, config=CFG)
    assert len(incs) == 1 and "near_stop" in incs[0].kinds


def test_off_track_detected():
    lap = _base()
    lap.position_type[900:940] = 4  # off-track surface for ~0.7 s
    incs = scan_incidents(lap, corner_positions={}, config=CFG)
    assert len(incs) == 1 and "off_track" in incs[0].kinds


def test_clean_lap_has_no_incidents():
    assert scan_incidents(_base(), corner_positions={}, config=CFG) == []


def test_brief_blips_below_min_duration_are_not_incidents():
    lap = _base()
    lap.speed[900:905] = 3.0  # < near_stop_min_s
    lap.position_type[910:913] = 4  # < offtrack_min_s
    assert scan_incidents(lap, corner_positions={}, config=CFG) == []


# --- Characterization (Layer 2) -------------------------------------------


def test_spin_under_brake_is_trail_brake_oversteer():
    lap = _base()
    _inject_spin(lap, 900, brake=0.8, throttle=0.0)
    (inc,) = scan_incidents(lap, corner_positions={}, config=CFG)
    assert "spin" in inc.kinds
    assert inc.classification == "trail_brake_oversteer" and inc.confidence == "high"


def test_spin_after_lift_is_lift_off_oversteer():
    lap = _base()
    _inject_spin(lap, 900, brake=0.0, throttle=0.0, throttle_before=1.0)
    (inc,) = scan_incidents(lap, corner_positions={}, config=CFG)
    assert inc.classification == "lift_off_oversteer"


def test_spin_on_power_is_power_on_oversteer():
    lap = _base()
    _inject_spin(lap, 900, brake=0.0, throttle=1.0, throttle_before=1.0)
    (inc,) = scan_incidents(lap, corner_positions={}, config=CFG)
    assert inc.classification == "power_on_oversteer"


def test_off_without_rotation_is_understeer_off():
    lap = _base()
    lap.position_type[900:940] = 4
    lap.steering_deg[900:940] = 120.0  # loaded up
    lap.yaw_rate[900:940] = 0.05  # but not rotating
    (inc,) = scan_incidents(lap, corner_positions={}, config=CFG)
    assert inc.classification == "understeer_off"


def test_ambiguous_snap_stays_unclassified():
    """A snap with no clean pedal signature and no external spike must not be
    given a guessed cause."""
    lap = _base()
    _inject_spin(lap, 900, brake=0.0, throttle=0.1, throttle_before=0.1)
    (inc,) = scan_incidents(lap, corner_positions={}, config=CFG)
    assert inc.classification == "unclassified" and inc.confidence == "low"


# --- Determinism + corner association -------------------------------------


def test_scan_is_deterministic():
    lap = _base()
    _inject_spin(lap, 900, brake=0.8)
    a = scan_incidents(lap, corner_positions={}, config=CFG)
    b = scan_incidents(lap, corner_positions={}, config=CFG)
    assert [(*i.kinds, i.classification, i.span_start) for i in a] == [
        (*i.kinds, i.classification, i.span_start) for i in b
    ]


def test_incident_associates_to_nearest_corner():
    lap = _base()
    _inject_spin(lap, 900, brake=0.8)  # sample 900 of 1800 -> ~0.5 lap
    (inc,) = scan_incidents(lap, corner_positions={"C09": 0.5, "C01": 0.05}, config=CFG)
    assert inc.corner_id == "C09"


# --- Real ground truth (the committed blind-test laps) ---------------------

_SPA_CORNERS = {"C01": 0.06, "C15": 0.965}


def test_real_spin_lap_detects_trail_brake_oversteer_at_la_source():
    lap = parse_lap(FIX / "Garage_61_9XVJTW.csv")
    incs = scan_incidents(lap, corner_positions=_SPA_CORNERS, config=CFG)
    spins = [i for i in incs if "spin" in i.kinds]
    assert spins, "the known La Source spin must be detected"
    top = spins[0]
    assert top.corner_id == "C01"
    assert top.classification == "trail_brake_oversteer"
    assert top.min_speed_kmh < 15  # near-stop confirmed on real data


def test_real_deadstop_lap_detects_near_stop_at_bus_stop():
    lap = parse_lap(FIX / "Garage_61_9PH9M2.csv")
    incs = scan_incidents(lap, corner_positions=_SPA_CORNERS, config=CFG)
    near = [i for i in incs if "near_stop" in i.kinds]
    assert near, "the known Bus Stop dead-stop must be detected"
    assert any(i.corner_id == "C15" and i.min_speed_kmh < 5 for i in near)


@pytest.mark.parametrize("lid", ["TTMWSD", "QHD9QC", "X0P687", "60GBCK", "808ASQ"])
def test_real_clean_laps_have_no_incidents(lid):
    lap = parse_lap(FIX / f"Garage_61_{lid}.csv")
    assert scan_incidents(lap, corner_positions=_SPA_CORNERS, config=CFG) == []


# --- Persistence + isolation (through the import pipeline) ------------------


def _lap_with_spin(src):
    from synth import track_lap

    lap = track_lap(src=src)
    at = 720  # inside the synthetic track's first corner window
    lap.steering_deg[at : at + 12] = np.linspace(-80.0, 80.0, 12)
    lap.yaw_rate[at : at + 12] = 1.0
    lap.speed[at : at + 20] = 5.0
    lap.brake[at : at + 12] = 0.8
    return lap


def test_reference_lap_is_never_scanned_into_incidents(tmp_db):
    """A reference lap with an obvious incident produces no self incident
    record — reference driving is never analysed."""
    from synth import run_synthetic_lap

    run_synthetic_lap(tmp_db, _lap_with_spin("ref.csv"), role="reference")
    assert tmp_db.incidents_for_cohort(driver="owner", car="TestCar", track="SynthRing") == []


def test_self_incident_is_persisted_with_evidence(tmp_db):
    from synth import run_synthetic_lap

    run_synthetic_lap(tmp_db, _lap_with_spin("self.csv"), role="self")
    incs = tmp_db.incidents_for_cohort(driver="owner", car="TestCar", track="SynthRing")
    assert len(incs) == 1
    assert "spin" in incs[0]["kinds"]
    assert incs[0]["incident_id"].startswith("incident:")
    assert incs[0]["classification"] == "trail_brake_oversteer"


def test_import_produces_deterministic_incident_rows():
    """Two independent imports of identical content -> identical incident
    rows (byte-diff of the normalised list)."""
    from driverdna.db import Database
    from synth import run_synthetic_lap

    def rows():
        with Database.open(":memory:") as db:
            run_synthetic_lap(db, _lap_with_spin("d.csv"))
            got = db.incidents_for_cohort(driver="owner", car="TestCar", track="SynthRing")
        for r in got:
            r.pop("lap_pk", None)  # surrogate key, not content
        return got

    assert rows() == rows()
