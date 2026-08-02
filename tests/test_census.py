"""`driverdna census` — the corpus-readiness artifact.

Census answers "do I need more lap data, and which laps?" from the store.
It applies no gate of its own: every row reuses either a count the engine
already exposes or the exact `gate_reason` string the engine emitted. The
anti-drift tests below are the point of the module — a census that says a
finding is blocked for a reason the engine never gave is a silent lie, which
is the one failure mode this project spends most of its machinery preventing.
"""

from dataclasses import replace

from typer.testing import CliRunner

from driverdna.census import build_census, build_census_report
from driverdna.cli import app
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.model.scoring import (
    _confidence,
    _driver_cohorts,
    confidence_from_terms,
    confidence_terms,
)
from driverdna.model.taxonomy import SignalStatus
from driverdna.report.payload import build_driver_payload
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()


def _one_cohort_db(n_laps: int = 8, *, car="TestCar", track="SynthRing", db=None, dated=False):
    """A single-cohort corpus: one car, one track, two sessions."""
    db = db or Database.open(":memory:")
    for i in range(n_laps):
        lap = track_lap(src=f"{car}-{track}-{i}.csv")
        if i % 2:
            lap = warp_time(lap, (0.19, 0.22), 0.4)
        run_synthetic_lap(
            db, lap, car=car, track=track, session_key=f"s{i % 2 + 1}",
            lap_date=f"2026-07-{i + 1:02d}" if dated else None,
        )
    return db


# --- the refactor pin: one confidence formula, not two ----------------------


def test_confidence_terms_reproduce_confidence_exactly():
    """`confidence_terms` must decompose the very formula `_confidence` uses.

    Census reads the terms individually; if the two ever diverge, census
    reports a shortfall against a floor the scorer is not actually applying.
    """
    with _one_cohort_db() as db:
        cohorts = _driver_cohorts(db, "owner")
        for evidence_count in (0, 3, 11, 50, 120):
            terms = confidence_terms(
                db, "owner", cohorts, evidence_count, CONFIG,
            )
            assert confidence_from_terms(terms) == _confidence(
                db, "owner", cohorts, evidence_count,
                SignalStatus.MEASURED, CONFIG,
            )


def test_confidence_terms_expose_have_and_floor_for_every_term():
    with _one_cohort_db() as db:
        terms = confidence_terms(db, "owner", _driver_cohorts(db, "owner"), 11, CONFIG)
    by_label = {t.label: t for t in terms}
    assert set(by_label) == {"evidence laps", "sessions", "tracks", "cars"}
    assert by_label["cars"].have == 1
    assert by_label["cars"].floor == CONFIG.model.confidence_car_floor
    assert by_label["tracks"].have == 1
    assert by_label["evidence laps"].have == 11
    # ratio is capped at 1.0 — surplus evidence never inflates a term
    assert replace(by_label["evidence laps"], have=10_000).ratio == 1.0


# --- census content ---------------------------------------------------------


def test_census_on_empty_db_says_so():
    with Database.open(":memory:") as db:
        report = build_census_report(db, CONFIG)
    assert "No self laps imported" in report


def test_census_is_deterministic():
    with _one_cohort_db() as db:
        a = build_census_report(db, CONFIG)
        b = build_census_report(db, CONFIG)
    assert a == b


def test_census_reports_car_and_track_floor_shortfall():
    """One car at one track is the live instrument's actual shape."""
    with _one_cohort_db() as db:
        census = build_census(db, CONFIG)
    gates = {g.label: g for s in census.sections for g in s.gates}
    assert gates["cars"].have == 1
    assert gates["cars"].need == CONFIG.model.confidence_car_floor
    assert not gates["cars"].met
    assert gates["tracks"].have == 1
    assert not gates["tracks"].met


def test_census_second_car_clears_the_car_floor():
    with _one_cohort_db() as db:
        _one_cohort_db(car="OtherCar", db=db)
        census = build_census(db, CONFIG)
    gates = {g.label: g for s in census.sections for g in s.gates}
    assert gates["cars"].have == 2
    assert gates["cars"].met
    # ...and the track floor is still short, because a second car at the same
    # track adds no track.
    assert gates["tracks"].have == 1
    assert not gates["tracks"].met


def test_census_reports_that_no_reference_lap_has_ever_been_imported():
    with _one_cohort_db() as db:
        census = build_census(db, CONFIG)
        report = build_census_report(db, CONFIG)
    gates = {g.label: g for s in census.sections for g in s.gates}
    assert gates["reference laps"].have == 0
    assert not gates["reference laps"].met
    assert "--role reference" in report


def test_census_counts_an_imported_reference_lap():
    with _one_cohort_db() as db:
        run_synthetic_lap(db, track_lap(src="ref.csv"), role="reference", driver="fast_guy")
        census = build_census(db, CONFIG)
    gates = {g.label: g for s in census.sections for g in s.gates}
    assert gates["reference laps"].have == 1
    assert gates["reference laps"].met


def test_census_reports_trend_blocked_by_undated_laps():
    """Trend needs `trend_min_laps_per_bucket` dated laps in EACH half."""
    with _one_cohort_db(n_laps=10) as db:
        census = build_census(db, CONFIG)
    gates = {g.label: g for s in census.sections for g in s.gates}
    dated = gates["dated laps"]
    assert dated.have == 0
    assert dated.need == CONFIG.model.trend_min_laps_per_bucket * 2
    assert not dated.met
    assert "sync" in dated.remedy or "--date" in dated.remedy


def test_census_dated_laps_clear_the_trend_gate():
    with _one_cohort_db(n_laps=10, dated=True) as db:
        census = build_census(db, CONFIG)
    gates = {g.label: g for s in census.sections for g in s.gates}
    assert gates["dated laps"].have == 10
    assert gates["dated laps"].met


# --- anti-drift: census quotes the engine, it does not re-derive -------------


def test_census_rollup_gate_text_is_the_engines_own_string():
    """The suppressed-rollup reason must be the string the payload emitted."""
    with _one_cohort_db() as db:
        payload = build_driver_payload(db, CONFIG)
        report = build_census_report(db, CONFIG)
    suppressed = [r for r in payload["cross_track_rollups"] if not r["shown"]]
    assert suppressed, "single-track corpus should suppress every rollup"
    for rollup in suppressed:
        assert rollup["gate_reason"] in report


def test_census_finding_gate_text_is_the_engines_own_string():
    """Same rule one level down: suppressed findings quote `ranker._gate`."""
    with _one_cohort_db(n_laps=4) as db:
        census = build_census(db, CONFIG)
        report = build_census_report(db, CONFIG)
    assert census.suppressed_gate_reasons, "4 laps should suppress some findings"
    for reason in census.suppressed_gate_reasons:
        assert reason in report


# --- the actual answer: what to add next ------------------------------------


def test_next_steps_quantify_the_gain_for_corpus_level_gates():
    """Adding a car/track moves a term the same amount for every fundamental,
    so the gain is exact and can be stated as a number."""
    with _one_cohort_db() as db:
        census = build_census(db, CONFIG)
    by_action = {s.action: s for s in census.next_steps}
    car_step = next(s for a, s in by_action.items() if "car" in a)
    # cars 1/2 -> 2/2 moves that term 0.5 -> 1.0, i.e. +0.5/4 of confidence
    assert car_step.delta_points == 12.5


def test_next_steps_do_not_guess_the_gain_from_more_laps():
    """How much a new lap raises evidence_count depends on which corners it
    produces — census states the shortfall and refuses to project a number."""
    with _one_cohort_db() as db:
        census = build_census(db, CONFIG)
    lap_step = next(
        s for s in census.next_steps if "lap" in s.action and "car" not in s.action
    )
    assert lap_step.delta_points is None
    assert lap_step.detail


def test_next_steps_are_ranked_by_gain():
    with _one_cohort_db() as db:
        census = build_census(db, CONFIG)
    quantified = [s.delta_points for s in census.next_steps if s.delta_points is not None]
    assert quantified == sorted(quantified, reverse=True)


def test_a_saturated_term_is_not_offered_as_a_next_step():
    """Sessions saturate at 6; once there, more sessions buy exactly nothing
    and census must stop recommending them."""
    with Database.open(":memory:") as db:
        for i in range(12):
            run_synthetic_lap(db, track_lap(src=f"s{i}.csv"), session_key=f"sess{i}")
        census = build_census(db, CONFIG)
        gates = {g.label: g for s in census.sections for g in s.gates}
        assert gates["sessions"].met
        assert not any("session" in s.action for s in census.next_steps)


# --- CLI --------------------------------------------------------------------


def test_census_cli_requires_existing_db(tmp_path):
    result = CliRunner().invoke(app, ["census", "--db", str(tmp_path / "nope.db")])
    assert result.exit_code == 2
    assert "run `driverdna import`" in result.output


def test_census_cli_writes_the_artifact(tmp_path):
    db_path = tmp_path / "c.db"
    with Database.open(db_path) as db:
        _one_cohort_db(db=db)
    out = tmp_path / "census-report.md"
    result = CliRunner().invoke(
        app, ["census", "--db", str(db_path), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "cars" in out.read_text()
