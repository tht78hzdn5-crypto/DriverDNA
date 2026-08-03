"""Reference laps never define the driver's own geometry (SPEC.md A34).

The non-negotiable is "reference laps never enter self history, trends, or
consistency statistics". The *measurement* layer honoured that from M2 — every
history/metric/detector/class query is `role='self'`. The **corner map** did
not, and the corner map is the coordinate system those measurements are taken
in: a corner's centroid decides which observations belong to it, and its frozen
phase windows decide where every entry/mid/exit time is measured. Someone
else's racing line moving that geometry moves the driver's own numbers, which
is the same leak one level down.

Three paths could write reference geometry into the map:

1. **Founding** — the first lap in a cohort builds the map. A reference lap
   imported into an empty cohort founded the whole thing.
2. **Admission** — an unmatched cluster becomes a corner once it is seen on
   `min_laps_for_admission` distinct laps. A reference lap counted as one of
   them, and its apex fed the new centroid.
3. **Rebuild** — `rebuild-map` (A22) re-derives every centroid and window from
   the corner's full observation set, which included reference observations.

These tests pin all three shut. A reference observation is still *linked* to
its corner and still measured — that is what vs-reference gaps are made of.
It just never votes on where the corner is.
"""

from __future__ import annotations

import numpy as np
import pytest

from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.pipeline import (
    ReferenceCannotFoundMap,
    import_parsed_lap,
    rebuild_cohort_map,
)
from synth import CORNER_WINDOWS, TRACK_LAT, TRACK_LON, track_lap
from synth import run_synthetic_lap as _run

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}

# ~27 m east at this latitude: well inside the 75 m match radius, so a lap on
# this line still matches the same corners — it just sits somewhere else, which
# is exactly how a faster driver's line differs from the owner's.
OFFSET_LON = TRACK_LON + 0.0003
# ...and turning in a little later, so the reference lap's landmark positions
# (which is what the canonical phase windows are derived from) differ too.
OFFSET_WINDOWS = [(s + 30, e + 30) for s, e in CORNER_WINDOWS]

# Two of each, deliberately. A median over {2 self, 2 reference} lands between
# the two lines, so a leak moves the number; a median over {2 self, 1 reference}
# would still land on the self line and the test would pass while leaking.
_N_SELF = 2
_N_REFERENCE = 2


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def _reference(db, lap, **kw):
    return _run(db, lap, driver="faster-driver", role="reference", config=CONFIG, **kw)


def _geometry(db, car="TestCar", track="SynthRing"):
    """Every frozen number the map holds: centroids and phase windows."""
    map_pk, _ = db.load_corner_map(car=car, track=track)
    corners = {
        r["corner_id"]: (r["lat"], r["lon"], r["lap_dist"])
        for r in db.conn.execute(
            "SELECT corner_id, lat, lon, lap_dist FROM corners WHERE map_pk=?",
            (map_pk,),
        )
    }
    return corners, db.load_corner_windows(map_pk)


def _self_phase_times(db):
    return {
        (r["lap_id"], r["corner_id"], r["phase"]): r["time_s"]
        for r in db.conn.execute(
            """SELECT l.lap_id, c.corner_id, p.phase, p.time_s
               FROM phase_times p
               JOIN corner_observations o ON o.obs_pk = p.obs_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               JOIN corners c ON c.corner_pk = o.corner_pk
               WHERE l.role='self'"""
        )
    }


# --- 1. founding: a reference lap cannot be the first lap in a cohort --------


def test_reference_lap_cannot_found_a_corner_map(db):
    with pytest.raises(ReferenceCannotFoundMap) as e:
        _reference(db, track_lap(src="ref.csv"))
    assert "TestCar" in str(e.value) and "SynthRing" in str(e.value)

    # Nothing partially written: no map, no corners, and no orphan lap row.
    assert db.load_corner_map(car="TestCar", track="SynthRing") is None
    assert db.conn.execute("SELECT COUNT(*) n FROM corners").fetchone()["n"] == 0
    assert db.conn.execute("SELECT COUNT(*) n FROM laps").fetchone()["n"] == 0


def test_reference_lap_imports_normally_once_a_self_lap_exists(db):
    _run(db, track_lap(src="base.csv"), config=CONFIG)
    result = _reference(db, track_lap(src="ref.csv"))
    assert result.status == "imported"
    assert result.assigned == ["C01", "C02", "C03"]


def test_a_second_cohort_is_still_refused_when_only_the_first_has_self_laps(db):
    # The guard is per (car, track) — a self lap at SynthRing does not license
    # founding OtherRing's map from a stranger.
    _run(db, track_lap(src="base.csv"), config=CONFIG)
    with pytest.raises(ReferenceCannotFoundMap):
        _reference(db, track_lap(src="ref.csv"), track="OtherRing")


# --- 2. admission: a reference lap is not one of the N distinct laps --------


def test_reference_lap_does_not_count_toward_corner_admission(db):
    extra = CORNER_WINDOWS + [(2200, 2350)]
    _run(db, track_lap(src="base.csv"), config=CONFIG)  # freezes C01..C03
    _run(db, track_lap(windows=extra, src="a.csv"), config=CONFIG)
    _run(db, track_lap(windows=extra, src="b.csv"), config=CONFIG)

    # Two distinct SELF laps have seen the candidate; the threshold is 3. A
    # reference lap must not be the deciding third.
    result = _reference(db, track_lap(windows=extra, src="ref.csv"))
    assert result.admitted == []
    assert "C04" not in _geometry(db)[0]

    # A third self lap still admits it — the gate is unchanged, not raised.
    assert _run(db, track_lap(windows=extra, src="c.csv"), config=CONFIG).admitted == [
        "C04"
    ]


def test_reference_laps_alone_can_never_admit_a_corner(db):
    """The sharp case: the owner has driven the candidate once, the reference
    driver twice. Leaked, that is three distinct laps — enough to admit a
    corner, positioned on the reference driver's line, which the owner's own
    laps would then be measured against."""
    extra = CORNER_WINDOWS + [(2200, 2350)]
    _run(db, track_lap(src="base.csv"), config=CONFIG)
    _run(db, track_lap(windows=extra, src="a.csv"), config=CONFIG)
    _reference(db, track_lap(windows=extra, lon=OFFSET_LON, src="ref1.csv"))
    result = _reference(db, track_lap(windows=extra, lon=OFFSET_LON, src="ref2.csv"))

    assert result.admitted == []
    assert "C04" not in _geometry(db)[0]


# --- 3. rebuild-map: the A22 refreeze reads self observations only ----------


def _build_cohort(db, *, with_reference: bool) -> None:
    for i in range(_N_SELF):
        _run(db, track_lap(src=f"lap{i}.csv"), config=CONFIG)
    if with_reference:
        for i in range(_N_REFERENCE):
            _reference(
                db,
                track_lap(windows=OFFSET_WINDOWS, lon=OFFSET_LON, src=f"ref{i}.csv"),
            )


def test_rebuild_map_geometry_is_identical_with_and_without_a_reference_lap():
    with Database.open(":memory:") as clean, Database.open(":memory:") as tainted:
        _build_cohort(clean, with_reference=False)
        _build_cohort(tainted, with_reference=True)
        rebuild_cohort_map(clean, config=CONFIG, **COHORT)
        rebuild_cohort_map(tainted, config=CONFIG, **COHORT)
        assert _geometry(tainted) == _geometry(clean)


def test_rebuild_map_never_changes_the_owners_own_phase_times():
    """The consequence that matters: phase windows decide where entry/mid/exit
    are measured, so leaked geometry silently re-times every self lap."""
    with Database.open(":memory:") as clean, Database.open(":memory:") as tainted:
        _build_cohort(clean, with_reference=False)
        _build_cohort(tainted, with_reference=True)
        rebuild_cohort_map(clean, config=CONFIG, **COHORT)
        rebuild_cohort_map(tainted, config=CONFIG, **COHORT)
        assert _self_phase_times(tainted) == _self_phase_times(clean)


def test_rebuild_map_still_re_measures_the_reference_lap_itself():
    """Isolation is not exclusion: the reference lap keeps its observations and
    its phase times, or there would be nothing to compute a gap from."""
    with Database.open(":memory:") as db:
        _build_cohort(db, with_reference=True)
        rebuild_cohort_map(db, config=CONFIG, **COHORT)
        n = db.conn.execute(
            """SELECT COUNT(*) n FROM phase_times p
               JOIN corner_observations o ON o.obs_pk = p.obs_pk
               JOIN laps l ON l.lap_pk = o.lap_pk
               WHERE l.role='reference'"""
        ).fetchone()["n"]
        assert n > 0


# --- the query surface itself, so a future caller inherits the guarantee ----


def test_corner_apex_positions_returns_self_observations_only(db):
    _build_cohort(db, with_reference=True)
    map_pk, _ = db.load_corner_map(car="TestCar", track="SynthRing")
    corner_pk = db.corner_pk(map_pk, "C01")
    apexes = db.corner_apex_positions(corner_pk)
    assert apexes
    assert all(a[1] == pytest.approx(float(TRACK_LON[0]), abs=1e-9) for a in apexes)


def test_observation_positions_returns_self_observations_only(db):
    _build_cohort(db, with_reference=True)
    map_pk, _ = db.load_corner_map(car="TestCar", track="SynthRing")
    corner_pk = db.corner_pk(map_pk, "C01")
    n_self = db.conn.execute(
        """SELECT COUNT(*) n FROM corner_observations o
           JOIN laps l ON l.lap_pk = o.lap_pk
           WHERE o.corner_pk=? AND l.role='self'""",
        (corner_pk,),
    ).fetchone()["n"]
    n_all = db.conn.execute(
        "SELECT COUNT(*) n FROM corner_observations WHERE corner_pk=?", (corner_pk,)
    ).fetchone()["n"]
    assert n_all > n_self  # the reference observation is linked...
    assert len(db.observation_positions(corner_pk)) == n_self  # ...but not read


# --- the real cohort this was found on --------------------------------------


def test_reference_lap_leaves_every_self_measurement_untouched_end_to_end(db):
    """M2/M3's own tables, not just the map: importing a reference lap changes
    no self observation, metric, detector result or phase time."""
    _build_cohort(db, with_reference=False)

    def snapshot():
        return {
            t: db.conn.execute(
                f"""SELECT {cols} FROM {t} x
                    JOIN corner_observations o ON o.obs_pk = x.obs_pk
                    JOIN laps l ON l.lap_pk = o.lap_pk
                    WHERE l.role='self' ORDER BY x.obs_pk, 2"""
            ).fetchall()
            for t, cols in (
                ("metric_values", "x.obs_pk, x.name, x.value"),
                ("phase_times", "x.obs_pk, x.phase, x.time_s"),
                ("detector_results", "x.obs_pk, x.detector, x.triggered, x.value"),
            )
        }

    before = snapshot()
    _reference(db, track_lap(windows=OFFSET_WINDOWS, lon=OFFSET_LON, src="ref.csv"))
    after = snapshot()
    for table in before:
        assert [tuple(r) for r in after[table]] == [tuple(r) for r in before[table]]


def test_admitted_corner_is_built_from_self_observations_only(db):
    """The admitted corner's centroid equals numpy's median over the SELF
    observations in its cluster, and `n_build_observations` counts only those —
    even though the reference observations are linked to it."""
    # Reference laps arrive first, so a leak admits the corner on THEIR line
    # (median of two reference apexes and one self apex) before the owner's
    # third lap ever gets a vote.
    extra = CORNER_WINDOWS + [(2200, 2350)]
    _run(db, track_lap(src="base.csv"), config=CONFIG)
    for i in range(_N_REFERENCE):
        _reference(db, track_lap(windows=extra, lon=OFFSET_LON, src=f"ref{i}.csv"))
    for src in ("a.csv", "b.csv", "c.csv"):
        _run(db, track_lap(windows=extra, src=src), config=CONFIG)

    map_pk, _ = db.load_corner_map(car="TestCar", track="SynthRing")
    corner_pk = db.corner_pk(map_pk, "C04")
    self_apexes = db.conn.execute(
        """SELECT o.apex_lat, o.apex_lon FROM corner_observations o
           JOIN laps l ON l.lap_pk = o.lap_pk
           WHERE o.corner_pk=? AND l.role='self'""",
        (corner_pk,),
    ).fetchall()
    row = db.conn.execute(
        "SELECT lat, lon, n_build_observations FROM corners WHERE corner_pk=?",
        (corner_pk,),
    ).fetchone()
    assert len(self_apexes) == 3
    assert row["n_build_observations"] == 3  # not 3 + _N_REFERENCE
    assert row["lat"] == pytest.approx(
        float(np.median([r["apex_lat"] for r in self_apexes]))
    )
    assert row["lon"] == pytest.approx(
        float(np.median([r["apex_lon"] for r in self_apexes]))
    )


def test_import_parsed_lap_rejects_reference_before_touching_the_store(db):
    """The refusal happens before the lap row is written, so a rejected import
    leaves nothing to clean up (same contract as `--date`'s exit-2 rejection)."""
    with pytest.raises(ReferenceCannotFoundMap):
        import_parsed_lap(
            db, track_lap(src="ref.csv"), driver="faster-driver", car="TestCar",
            track="SynthRing", role="reference", config=CONFIG,
        )
    assert db.conn.execute("SELECT COUNT(*) n FROM laps").fetchone()["n"] == 0
