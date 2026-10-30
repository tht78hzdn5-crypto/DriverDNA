"""Regression pins for the entry-phase tranche (SPEC.md A57, PR #56)
that tests/test_coaching_entry_phase.py does not already cover.

Deliberately NOT duplicated here (already pinned there):
- the three principles firing, their strengths, and their guards
  (trail and application);
- the four config thresholds' documented defaults;
- the ontology shape of all three principles;
- measured-over-proxy precedence at selection and rollup level;
- that precedence is presentation-only (eligibility untouched).

What this module pins instead:
- the IQR's stated reason for existing: a single outlier lap must not
  flip a fixed brake point into a fault (robustness no wandering /
  fixed pair of tests exercises — both move every lap together);
- that `same_marker` carries NO braking guard, unlike the other two
  tranche-1 principles: it judges brake-point spread wherever a
  braking event exists, so a light-braking wandering corner still
  fires (a future guard added without a decision would silence it);
- the `same_marker` candidate banding on entry loss, like its two
  siblings (the existing test asserts only n);
- the application strength's observed kind (trail and same-marker
  kinds are pinned; application's is not);
- the version constants, literally: the tranche moves the ontology
  to v5 while leaving the payload at v9 and the scoring model at
  dm-v2 — a structural separation no self-consistent check would
  catch reverting.

Builders below mirror tests/test_coaching_entry_phase.py so this
module stands alone; they are copies, not imports, on purpose.
"""

import numpy as np
import pytest

from driverdna.coaching.engine import (
    _metric_stat,
    eligible_principles,
    eligible_strengths,
)
from driverdna.coaching.ontology import ONTOLOGY_VERSION
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.scoring import SCORING_MODEL_VERSION
from driverdna.report.payload import PAYLOAD_VERSION
from synth import make_lap, ramp
from synth import run_synthetic_lap as _run

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}

SAME_MARKER = "cp.brake_point_selection.same_marker"
APPLICATION = "cp.brake_application.get_to_peak"


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def run_synthetic_lap(db, lap, **kw):
    kw.setdefault("driver", COHORT["driver"])
    kw.setdefault("car", COHORT["car"])
    kw.setdefault("track", COHORT["track"])
    kw.setdefault("config", CONFIG)
    return _run(db, lap, **kw)


def _candidates(db, principle_id, config=CONFIG):
    return [
        c for c in eligible_principles(db, config=config, **COHORT)
        if c.principle_id == principle_id
    ]


def _strengths(db, principle_id, config=CONFIG):
    return [
        s for s in eligible_strengths(db, config=config, **COHORT)
        if s.principle_id == principle_id
    ]


def _brake_point_lap(src: str, start: int):
    """One canonical corner whose whole brake event sits at `start`."""
    lap = make_lap(1800, src=src)
    from synth import one_corner_lap
    canonical = one_corner_lap()
    lap.speed = canonical.speed
    lap.throttle = canonical.throttle
    lap.steering_deg = canonical.steering_deg
    brake = np.zeros(1800)
    ramp(brake, start, start + 30, 0.0, 0.85)
    brake[start + 30:start + 70] = 0.85
    ramp(brake, start + 70, start + 100, 0.85, 0.0)
    lap.brake = brake
    return lap


def _base_traces(n=1800):
    speed = np.full(n, 45.0)
    ramp(speed, 600, 760, 45.0, 28.0)
    ramp(speed, 760, 900, 28.0, 45.0)
    throttle = np.ones(n)
    ramp(throttle, 580, 600, 1.0, 0.0)
    throttle[600:780] = 0.0
    ramp(throttle, 780, 830, 0.0, 1.0)
    return speed, throttle


def _steering(n=1800, start=690):
    steering = np.zeros(n)
    ramp(steering, start, start + 30, 0.0, 25.0)
    steering[start + 30:840] = 25.0
    ramp(steering, 840, 870, 25.0, 0.0)
    return steering


def _fast_application_lap(src: str):
    """Peak reached in ~0.1 s and trailed in: the application strength."""
    n = 1800
    speed, throttle = _base_traces(n)
    brake = np.zeros(n)
    ramp(brake, 600, 608, 0.0, 0.85)
    brake[608:700] = 0.85
    ramp(brake, 700, 760, 0.85, 0.0)
    return make_lap(n, speed=speed, brake=brake,
                    steering_deg=_steering(n, start=660),
                    throttle=throttle, src=src)


# --- the IQR's reason for existing -------------------------------------------


def test_same_marker_iqr_ignores_a_single_outlier_lap(db):
    # Nine laps on one marker, one lap far away. The IQR of nine
    # identical values plus one outlier is still ~0 — the middle half
    # never sees the outlier — while a mean-based spread (std) of the
    # same values clears the 1.0 floor easily. If the gate ever swapped
    # IQR for std or CV, this cohort would flip from strength to
    # fault; that flip is exactly what the IQR was chosen to prevent.
    for i in range(9):
        run_synthetic_lap(db, _brake_point_lap(f"bp{i}.csv", 600),
                          session_key=f"s{i % 2}")
    run_synthetic_lap(db, _brake_point_lap("bp9.csv", 870), session_key="s1")
    assert not _candidates(db, SAME_MARKER)
    strengths = _strengths(db, SAME_MARKER)
    assert strengths, "a fixed marker with one stray lap is still a strength"
    s = strengths[0]
    assert s.observed_kind == "metric_iqr"
    assert s.observed < 1.0
    # The outlier lap's value must actually be in the statistic — n == 10
    # proves the IQR ignored it, rather than the lap never being measured.
    assert s.n == 10
    table = db.self_metric_table(driver="owner", car="TestCar", track="SynthRing")
    values = table["C01"]["brake_point_dist_pct"]
    assert len(values) == 10
    assert float(np.std(values)) > 1.0  # the spread a std gate would see
    assert _metric_stat(values, "iqr") < 1.0  # the spread the IQR gate sees


# --- same_marker has no guard --------------------------------------------------


def test_same_marker_carries_no_braking_guard(db):
    # Trail and application both scope out below a 0.50 brake_peak
    # median. Same_marker's gate deliberately names no guard: a
    # wandering brake point on light braking is still a fault, not an
    # unjudged corner. Scale the peak to 0.45 — below the guard floor
    # the other two principles use, but a real braking event.
    for i in range(10):
        lap = _brake_point_lap(f"bp{i}.csv", 560 + i * 30)
        lap.brake = lap.brake * (0.45 / 0.85)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2}")
    table = db.self_metric_table(driver="owner", car="TestCar", track="SynthRing")
    assert float(np.median(table["C01"]["brake_peak"])) < 0.50
    found = _candidates(db, SAME_MARKER)
    assert found, "a wandering brake point must fire even below a 0.50 peak"
    assert found[0].corner_id == "C01"


# --- same_marker bands like its siblings ---------------------------------------


def test_same_marker_candidate_bands_on_entry_loss(db):
    # SPEC A57: all three principles band on the entry phase's
    # cumulative loss. The existing test asserts only n; the banding
    # itself — the statistic is the trigger, the seconds are the tone —
    # is pinned for trail and application but not here.
    for i in range(10):
        run_synthetic_lap(db, _brake_point_lap(f"bp{i}.csv", 560 + i * 30),
                          session_key=f"s{i % 2}")
    found = _candidates(db, SAME_MARKER)
    assert found
    assert found[0].magnitude_kind == "seconds_lost"
    assert found[0].corner_id == "C01"


# --- application strength kind ---------------------------------------------------


def test_brake_application_strength_reports_median_kind(db):
    for i in range(8):
        run_synthetic_lap(db, _fast_application_lap(f"app{i}.csv"),
                          session_key=f"s{i % 2}")
    strengths = _strengths(db, APPLICATION)
    assert strengths
    assert strengths[0].observed_kind == "metric_median"
    assert strengths[0].observed >= 2.0


# --- version constants, literally ----------------------------------------------


def test_version_pins_entry_phase_tranche():
    # The tranche moves the ontology and nothing else: the payload
    # gains no field (a candidate is a candidate) and the scoring
    # model cannot move — every new threshold is config.coaching.*.
    # Literal pins: self-consistent checks would pass a silent revert.
    # The payload/scoring pins track the merged main (v13 / dm-v3),
    # not the tranche's own base (v9 / dm-v2). A58 moved the ontology
    # pin to coach-onto-v6; A59 moves it to coach-onto-v7 and the
    # payload pin to v13 (tendencies section). Scoring is unchanged.
    assert ONTOLOGY_VERSION == "coach-onto-v7"
    assert PAYLOAD_VERSION == 13
    assert SCORING_MODEL_VERSION == "dm-v3"
