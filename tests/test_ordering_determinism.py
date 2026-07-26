"""Ordering and dialect-neutrality locks (Phase 0 of the Postgres port).

These guard properties that SQLite has been satisfying *by accident* — via
rowid return order and its permissive typing — rather than because the SQL
says so. Each one is a real defect the moment the same schema runs on a
store that does not promise insertion order.

Honest scope note, established by experiment rather than assumed: **none of
the ordering defects can be made to fail under SQLite.**

- `corner_positions` — `corners` carries `UNIQUE (map_pk, corner_id)`, and
  the query filters on `map_pk`, so SQLite serves it from that index and
  returns corner_id order already. Postgres is free to seq-scan a small
  table instead, at which point the order is whatever the heap says.
- the tercile split in `attribution/ranker.py` — SQLite's incidental rowid
  order happens to equal the intended `lap_pk` tie-break.

So the behavioural assertions below pass with *and without* the fixes on
this backend; they lock intent, not the regression. What actually catches a
regression locally is the accompanying source assertion on each query, and
what catches it for real is the cross-backend parity test that arrives with
the Postgres backend. This is written down so the coverage gap is a known,
deliberate one rather than a false sense of safety.
"""

import inspect

from pathlib import Path

import pytest

from driverdna.db import Database

COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def _map_with_corners_inserted_out_of_order(db) -> int:
    """Freeze a map whose rows land in an order that is deliberately not
    corner_id order, so an unordered SELECT returns them wrongly."""
    map_pk = db._insert_returning(
        "INSERT INTO corner_maps (car, track, built_from_n_laps) VALUES (?, ?, ?)",
        (COHORT["car"], COHORT["track"], 3),
        "map_pk",
    )
    # Insert C03, C01, C02 in that order: rowid order != corner_id order.
    for corner_id, lap_dist in (("C03", 0.75), ("C01", 0.25), ("C02", 0.50)):
        db.conn.execute(
            """INSERT INTO corners (map_pk, corner_id, lat, lon, lap_dist,
                                    n_build_observations)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (map_pk, corner_id, 0.0, 0.0, lap_dist, 3),
        )
    db.conn.commit()
    return map_pk


def test_corner_positions_is_ordered_by_corner_id(db):
    """`corner_positions` feeds `_corner_at`, which resolves a distance tie
    with `min()` — first minimum wins. So dict order decides the corner an
    incident is labelled with, and that label is persisted into
    incidents.corner_id. Fails without `ORDER BY corner_id`.
    """
    _map_with_corners_inserted_out_of_order(db)
    positions = db.corner_positions(car=COHORT["car"], track=COHORT["track"])
    assert list(positions) == ["C01", "C02", "C03"]

    # The assertion that actually regresses if the clause is dropped (see the
    # module docstring: the behavioural one above cannot, on SQLite).
    assert "ORDER BY corner_id" in inspect.getsource(Database.corner_positions)


def test_tercile_query_orders_by_lap_pk_within_a_duration_tie():
    """`rank_vs_self` slices `laps[:third]` / `laps[-third:]` out of this
    ordering, so laps sharing a `duration_s` would otherwise land in the fast
    or slow group by storage order. Source assertion for the same reason as
    above: SQLite's incidental order already equals the intended one, so no
    behavioural test can fail here."""
    from driverdna.attribution import ranker

    source = inspect.getsource(ranker)
    assert "ORDER BY duration_s, lap_pk" in source


def test_tied_distance_labels_the_lower_corner_id(db):
    """The tie itself, end to end: a sample equidistant between two corners
    must resolve to the lower corner_id every time, not to whichever row the
    store happened to return first.

    The two corners sit 0.02 lap apart so the midpoint is 0.01 from each —
    inside `_corner_at`'s 0.03 tolerance, which is what makes the tie
    reachable at all.
    """
    from driverdna.incidents.detector import _corner_at

    map_pk = db._insert_returning(
        "INSERT INTO corner_maps (car, track, built_from_n_laps) VALUES (?, ?, ?)",
        (COHORT["car"], COHORT["track"], 3),
        "map_pk",
    )
    # C02 inserted first, so rowid order puts the *higher* id first.
    for corner_id, lap_dist in (("C02", 0.270), ("C01", 0.250)):
        db.conn.execute(
            """INSERT INTO corners (map_pk, corner_id, lat, lon, lap_dist,
                                    n_build_observations)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (map_pk, corner_id, 0.0, 0.0, lap_dist, 3),
        )
    db.conn.commit()

    positions = db.corner_positions(car=COHORT["car"], track=COHORT["track"])

    class _Lap:
        lap_dist = [0.260]  # 0.010 from each corner — an exact tie

    assert _corner_at(_Lap(), 0, positions) == "C01"


def test_empty_lap_pk_bucket_matches_nothing(db):
    """An empty M6 trend bucket honestly has no evidence — it must not
    degrade into 'no restriction'. The fragment is also the one place the
    schema relied on SQLite's int-as-boolean coercion (`AND 0`)."""
    from driverdna.db import _lap_pk_filter

    clause, params = _lap_pk_filter(frozenset())
    assert params == []
    # `AND 0` is not valid outside SQLite; `AND 1=0` means the same thing
    # everywhere and is what the fragment must emit.
    assert clause.strip() == "AND 1=0"

    # And it must actually match nothing when executed.
    row = db.conn.execute(
        f"SELECT COUNT(*) AS n FROM laps l WHERE 1=1{clause}"
    ).fetchone()
    assert row["n"] == 0


def test_no_lap_pk_filter_is_unrestricted(db):
    """The None case must stay genuinely unrestricted — the empty-set fix
    must not have collapsed the two cases together."""
    from driverdna.db import _lap_pk_filter

    assert _lap_pk_filter(None) == ("", [])


def test_retention_derived_table_is_aliased(db):
    """`enforce_retention`'s subquery must carry an alias — a bare
    `FROM (SELECT ...)` is a syntax error outside SQLite. Executing the real
    path is the check; an unaliased derived table would still run here, so
    this also asserts the alias textually."""
    source = inspect.getsource(Database.enforce_retention)
    assert ") ranked WHERE rn >" in source

    # The path still works and still evicts nothing from an empty DB.
    assert db.enforce_retention(keep=10) == 0


def test_annotation_pk_is_stable_across_reannotation(db):
    """The upsert rewrite changed `INSERT OR REPLACE` (delete + reinsert,
    renumbering the pk) to `ON CONFLICT DO UPDATE` (update in place). The pk
    staying put is the observable difference, and it is the behaviour that
    matches 'the measurement is never deleted'."""
    first = db.annotate_finding(finding_id="f:1", status="acknowledged")
    second = db.annotate_finding(finding_id="f:1", status="intentional", note="mine")
    assert first == second

    stored = db.annotations()["f:1"]
    assert stored == {"status": "intentional", "note": "mine"}


def test_phase_times_upsert_overwrites_in_place(db):
    """`store_phase_times` is the other rewritten upsert — re-storing must
    replace the value, not duplicate the (obs_pk, phase) row."""
    lap_pk = db._insert_returning(
        """INSERT INTO laps (source_file, driver, car, track, role, n_samples,
                             duration_s, quality_flags)
           VALUES (?, ?, ?, ?, 'self', 10, 1.0, '[]')""",
        (str(Path("synthetic-upsert.csv")), COHORT["driver"], COHORT["car"],
         COHORT["track"]),
        "lap_pk",
    )
    obs_pk = db._insert_returning(
        """INSERT INTO corner_observations
           (lap_pk, corner_pk, span_start, span_end, landmarks,
            landmark_positions, apex_lat, apex_lon, apex_lap_dist, min_speed_ms)
           VALUES (?, NULL, 0, 5, '{}', '{}', 0.0, 0.0, 0.5, 10.0)""",
        (lap_pk,),
        "obs_pk",
    )
    db.conn.commit()

    db.store_phase_times(obs_pk, {"entry": 1.0, "mid": 2.0, "exit": 3.0})
    db.store_phase_times(obs_pk, {"entry": 1.5})

    rows = db.conn.execute(
        "SELECT phase, time_s FROM phase_times WHERE obs_pk=? ORDER BY phase", (obs_pk,)
    ).fetchall()
    assert [(r["phase"], r["time_s"]) for r in rows] == [
        ("entry", 1.5), ("exit", 3.0), ("mid", 2.0),
    ]
