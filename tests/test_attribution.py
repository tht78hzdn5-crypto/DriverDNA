"""M3 tests: canonical windows, phase times, baselines, ranker, isolation."""

import numpy as np
import pytest

from driverdna.attribution.engine import (
    PhaseWindows,
    baseline,
    derive_windows,
    phase_times,
    screen_outliers,
    time_at,
)
from driverdna.attribution.ranker import (
    cumulative_loss,
    vs_reference_findings,
    vs_self_findings,
)
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.pipeline import phase_windows_from_stored
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}

# C01's mid/exit windows sit around its apex (~21.5 % of the lap).
C01_WARP_WINDOW = (0.19, 0.22)


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


# --- Engine units ----------------------------------------------------------


def test_derive_windows_takes_medians():
    records = [
        {"brake_start": 0.30, "turn_in": 0.35, "apex": 0.40, "full_throttle": 0.45, "exit": 0.47},
        {"brake_start": 0.31, "turn_in": 0.36, "apex": 0.41, "full_throttle": 0.46, "exit": 0.48},
        {"brake_start": 0.32, "turn_in": 0.37, "apex": 0.42, "full_throttle": 0.47, "exit": 0.49},
    ]
    w = derive_windows(records)
    assert w.window("entry") == (0.31, 0.36)
    assert w.window("mid") == (0.36, 0.41)
    assert w.window("exit") == (0.41, 0.46)  # full throttle before corner exit


def test_derive_windows_handles_start_finish_seam():
    records = [
        {"brake_start": 0.97, "turn_in": 0.98, "apex": 0.995, "full_throttle": 0.01, "exit": 0.02},
    ]
    w = derive_windows(records)
    assert w.window("entry") == (0.97, 0.98)
    exit_window = w.window("exit")
    assert exit_window == pytest.approx((0.995, 0.01))  # wraps through the line


def test_time_at_wraps_positions_before_lap_start():
    lap_dist = np.linspace(0.001, 1.0005, 600)
    elapsed = np.linspace(0.0, 100.0, 600)
    assert time_at(lap_dist, elapsed, 0.0005) > 99.9  # maps past the line
    assert abs(time_at(lap_dist, elapsed, 0.5) - 50.0) < 0.2


def test_phase_times_measure_fixed_spans():
    lap_dist = np.linspace(0.0, 1.0, 3600)
    elapsed = np.linspace(0.0, 60.0, 3600)  # uniform speed
    w = PhaseWindows(entry_start=0.1, turn_in=0.2, apex=0.3, exit_end=0.4)
    t = phase_times(lap_dist, elapsed, w)
    assert abs(t["entry"] - 6.0) < 0.05
    assert abs(t["mid"] - 6.0) < 0.05
    assert abs(t["exit"] - 6.0) < 0.05


def test_outlier_screening_and_robust_baseline():
    times = [5.0, 5.1, 4.9, 5.05, 9.0]  # one off-lap must not become the yardstick
    kept, screened = screen_outliers(times, CONFIG.attribution.outlier_mad_k)
    assert screened == 1 and 9.0 not in kept
    base = baseline(times, CONFIG.attribution)
    assert base.n == 4 and base.n_outliers == 1
    assert base.single_best_s == 4.9
    assert abs(base.robust_best_s - 5.0) < 1e-9  # median of top-3 screened
    assert base.median_s < 5.1


def test_baseline_single_sample():
    base = baseline([5.0], CONFIG.attribution)
    assert base.robust_best_s == base.single_best_s == base.median_s == 5.0


# --- The F1 fix, directionally --------------------------------------------


def test_later_braking_shows_less_time_in_fixed_entry_window(db):
    """A lap that brakes later crosses the canonical entry window faster.

    Measured between per-lap landmarks this signal would be destroyed —
    both laps would report 'their own braking phase' instead of the same
    stretch of road.
    """
    from synth import make_lap, one_corner_lap, ramp

    base_lap = one_corner_lap()
    base_lap.source_path = base_lap.source_path.with_name("base.csv")
    run_synthetic_lap(db, base_lap, car="BrakeCar", track="BrakeTrack")

    late = one_corner_lap()
    late.source_path = late.source_path.with_name("late.csv")
    # Brake 20 samples later and carry speed further before slowing.
    late.brake[:] = 0.0
    ramp(late.brake, 620, 650, 0.0, 0.8)
    late.brake[650:690] = 0.8
    ramp(late.brake, 690, 720, 0.8, 0.0)
    late.speed[:] = 50.0
    ramp(late.speed, 620, 750, 50.0, 25.0)
    ramp(late.speed, 750, 960, 25.0, 50.0)
    # Same total pace elsewhere; time through the entry window must shrink
    # because more of it is crossed at higher speed. Warp elapsed to match
    # physics: crossing [entry window] faster = less elapsed there.
    late = warp_time(late, (0.335, 0.373), -0.10)
    run_synthetic_lap(db, late, car="BrakeCar", track="BrakeTrack")

    history = db.phase_history(
        car="BrakeCar", track="BrakeTrack", corner_id="C01", phase="entry",
        role="self", driver="owner",
    )
    assert len(history) == 2
    assert history[1]["time_s"] < history[0]["time_s"]


# --- Ranker on a constructed cohort ----------------------------------------


def _build_cohort(db, *, n_fast=6, n_slow=6, warp_s=0.4):
    """12 laps, 2 sessions, slow laps consistently losing in C01's window."""
    laps = []
    for i in range(n_fast):
        lap = track_lap(src=f"fast{i}.csv")
        laps.append((lap, f"s{i % 2 + 1}"))
    for i in range(n_slow):
        lap = warp_time(track_lap(src=f"slow{i}.csv"), C01_WARP_WINDOW, warp_s)
        laps.append((lap, f"s{i % 2 + 1}"))
    for lap, session in laps:
        run_synthetic_lap(db, lap, session_key=session)


def _windows(db):
    map_pk, _ = db.load_corner_map(car=COHORT["car"], track=COHORT["track"])
    return {
        cid: phase_windows_from_stored(w)
        for cid, w in db.load_corner_windows(map_pk).items()
    }


def test_vs_self_finds_the_planted_weakness(db):
    _build_cohort(db)
    findings = vs_self_findings(
        db, **COHORT, windows_by_corner=_windows(db), config=CONFIG
    )
    shown = [f for f in findings if f.shown]
    assert shown, "the planted weakness must pass the gates"
    top = max(shown, key=lambda f: f.details["rank_score"] or 0)
    assert top.corner_id == "C01"
    assert top.details["opportunity_s"] > 0.15
    assert top.details["repeatability"] == 1.0
    assert top.n == 12 and top.details["n_sessions"] == 2
    assert all(e.startswith("obs:") for e in top.evidence_ids)
    # The planted 0.4 s straddles C01's mid and exit windows; the phases'
    # opportunities must jointly recover it.
    c01_total = sum(
        f.details["opportunity_s"] for f in shown if f.corner_id == "C01"
    )
    assert 0.3 < c01_total < 0.5
    # Corners without a planted effect are suppressed as no-effect, stated:
    others = [f for f in findings if f.corner_id != "C01"]
    assert others and all(not f.shown for f in others)
    assert all(f.gate_reason for f in others)


def test_vs_self_opportunity_ignores_one_incident_lap(db):
    """A single off/spin/near-stop must not manufacture a phantom
    opportunity the way it must never become the baseline (docs/SPEC.md
    M3): the blind acceptance test on real independent Spa laps found this
    exact failure mode (2026-07-21) — a spin at one corner inflated its
    reported "opportunity" ~2.5x. This plants the same shape: a consistent
    cohort plus one lap with a severe, isolated time loss at C01."""
    _build_cohort(db)
    incident = warp_time(track_lap(src="incident.csv"), C01_WARP_WINDOW, 6.0)
    run_synthetic_lap(db, incident, session_key="s1")  # 13th lap, slowest by far

    findings = vs_self_findings(
        db, **COHORT, windows_by_corner=_windows(db), config=CONFIG
    )
    c01 = [f for f in findings if f.corner_id == "C01"]
    assert any(f.details["n_outliers"] >= 1 for f in c01), (
        "the incident lap must be screened at C01, mirroring baseline()'s fence"
    )
    # Opportunity must track the planted 0.4 s technique effect, not the
    # incident's 6 s loss — screening must land close to the un-incidented
    # test above (0.3-0.5 s total), not somewhere between that and 6 s.
    c01_total = sum(
        f.details["opportunity_s"] for f in c01 if f.details["opportunity_s"] is not None
    )
    assert c01_total < 1.0, f"incident leaked into opportunity: {c01_total} s"
    # The raw observation is never silently dropped: n and evidence still
    # include it, only the derived opportunity/repeatability exclude it.
    assert any(f.n == 13 for f in c01)


def test_stint_only_variation_yields_zero_shown_findings(db):
    """Acceptance gate 4 (M3 form): identical laps, only session/stint
    position varies -> no technique findings survive."""
    for i in range(12):
        lap = track_lap(src=f"same{i}.csv")
        run_synthetic_lap(db, lap, session_key=f"s{i % 2 + 1}")
    findings = vs_self_findings(
        db, **COHORT, windows_by_corner=_windows(db), config=CONFIG
    )
    assert findings and not any(f.shown for f in findings)


def test_gates_suppress_small_samples(db):
    for i in range(4):
        run_synthetic_lap(db, track_lap(src=f"few{i}.csv"), session_key="s1")
    findings = vs_self_findings(
        db, **COHORT, windows_by_corner=_windows(db), config=CONFIG
    )
    assert findings and not any(f.shown for f in findings)
    assert any("phase samples" in (f.gate_reason or "") for f in findings)


# --- Reference isolation at the gap level (trust gate 3, M3 form) ----------


def test_reference_import_perturbs_gap_sections_only(db):
    _build_cohort(db)
    windows = _windows(db)
    self_before = vs_self_findings(db, **COHORT, windows_by_corner=windows, config=CONFIG)
    loss_before = cumulative_loss(db, **COHORT, windows_by_corner=windows, config=CONFIG)
    history_before = db.phase_history(
        car=COHORT["car"], track=COHORT["track"], corner_id="C01", phase="mid",
        role="self", driver=COHORT["driver"],
    )
    assert not vs_reference_findings(
        db, **COHORT, windows_by_corner=windows, config=CONFIG
    )

    ref = warp_time(track_lap(src="ref.csv"), C01_WARP_WINDOW, -0.2)
    run_synthetic_lap(db, ref, driver="faster-driver", role="reference")

    # Self sections byte-identical:
    assert vs_self_findings(db, **COHORT, windows_by_corner=windows, config=CONFIG) == self_before
    assert cumulative_loss(db, **COHORT, windows_by_corner=windows, config=CONFIG) == loss_before
    assert db.phase_history(
        car=COHORT["car"], track=COHORT["track"], corner_id="C01", phase="mid",
        role="self", driver=COHORT["driver"],
    ) == history_before
    # Gap sections now exist, labeled as gap:
    gaps = vs_reference_findings(db, **COHORT, windows_by_corner=windows, config=CONFIG)
    assert gaps
    c01 = [g for g in gaps if g.corner_id == "C01"]
    assert c01 and all("gap" in g.description.lower() for g in c01)
    assert any(g.details["gap_median_s"] > 0 for g in c01)
