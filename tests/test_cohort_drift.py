"""Cohort-label drift detection (SPEC.md A27).

`car`/`track` are cohort keys, so one real cohort under two labels halves the
evidence behind every baseline, trend and consistency number without raising
anything. These tests pin both directions: the drift signatures are caught,
and legitimately distinct cohorts are never flagged — a false positive here
would train the driver to ignore the warning that matters.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.cohorts import find_label_drift

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _cohorts(*triples: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"driver": d, "car": c, "track": t} for d, c, t in triples]


# --- the signatures that are real drift --------------------------------------


def test_variant_present_on_one_side_only_is_flagged():
    """The motivating case: `sync` folds the API's variant into the label,
    a manual import takes the filename's bare name."""
    pairs = find_label_drift(_cohorts(
        ("owner", "Ford Mustang GT4", "Summit Point Raceway"),
        ("owner", "Ford Mustang GT4", "Summit Point Raceway (Shenandoah)"),
    ))
    assert len(pairs) == 1
    assert "variant" in pairs[0].describe()


def test_case_and_punctuation_differences_are_flagged():
    pairs = find_label_drift(_cohorts(
        ("owner", "GR86", "Spa-Francorchamps"),
        ("owner", "GR86", "Spa Francorchamps"),
    ))
    assert len(pairs) == 1
    assert "case or punctuation" in pairs[0].describe()


def test_drift_on_the_car_axis_is_flagged_too():
    pairs = find_label_drift(_cohorts(
        ("owner", "Ford Mustang GT4", "Summit Point Raceway"),
        ("owner", "ford mustang gt4", "Summit Point Raceway"),
    ))
    assert len(pairs) == 1
    assert "car labels" in pairs[0].describe()


# --- what must NOT be flagged ------------------------------------------------


def test_two_different_variants_are_distinct_cohorts_not_drift():
    """"Track variants are distinct cohorts" is the spec's own rule. Flagging
    these would make the warning noise."""
    assert find_label_drift(_cohorts(
        ("owner", "GR86", "Summit Point Raceway (Main)"),
        ("owner", "GR86", "Summit Point Raceway (Shenandoah)"),
    )) == []


def test_genuinely_different_tracks_are_not_flagged():
    assert find_label_drift(_cohorts(
        ("owner", "GR86", "Spa-Francorchamps"),
        ("owner", "GR86", "Summit Point Raceway"),
    )) == []


def test_genuinely_different_cars_at_one_track_are_not_flagged():
    assert find_label_drift(_cohorts(
        ("owner", "GR86", "Spa-Francorchamps"),
        ("owner", "Ford Mustang GT4", "Spa-Francorchamps"),
    )) == []


def test_two_drivers_are_never_compared():
    assert find_label_drift(_cohorts(
        ("alice", "GR86", "Spa-Francorchamps"),
        ("bob", "GR86", "Spa Francorchamps"),
    )) == []


def test_a_single_cohort_produces_nothing():
    assert find_label_drift(_cohorts(("owner", "GR86", "Spa-Francorchamps"))) == []


def test_detection_is_deterministic():
    cohorts = _cohorts(
        ("owner", "GR86", "Spa Francorchamps"),
        ("owner", "GR86", "Spa-Francorchamps"),
        ("owner", "Ford Mustang GT4", "Summit Point Raceway"),
        ("owner", "Ford Mustang GT4", "Summit Point Raceway (Shenandoah)"),
    )
    assert find_label_drift(cohorts) == find_label_drift(list(reversed(cohorts)))


# --- surfaced where the driver actually looks --------------------------------


def _import(runner, db_path, src_dir, *extra):
    return runner.invoke(
        app, ["import", str(src_dir), "--db", str(db_path), *extra]
    )


def _drifted_store(tmp_path):
    """One cohort imported twice: once bare, once with the API-style variant."""
    runner = CliRunner()
    db_path = tmp_path / "drift.db"
    a, b = tmp_path / "a", tmp_path / "b"
    for d, fixture in ((a, "Garage_61_HKWPXX.csv"), (b, "Garage_61_W5JRZB.csv")):
        d.mkdir()
        (d / fixture).write_bytes((FIXTURES_DIR / fixture).read_bytes())
    assert _import(runner, db_path, a, "--car", "GR86",
                   "--track", "Spa-Francorchamps").exit_code == 0
    second = _import(runner, db_path, b, "--car", "GR86",
                     "--track", "Spa-Francorchamps (Grand Prix)")
    assert second.exit_code == 0
    return runner, db_path, second


def test_import_warns_at_the_moment_drift_is_created(tmp_path):
    _runner, _db_path, second = _drifted_store(tmp_path)
    assert "look like the same cohort under two labels" in second.output
    assert "Spa-Francorchamps (Grand Prix)" in second.output
    assert "Nothing has been changed automatically" in second.output


def test_history_reports_existing_drift(tmp_path):
    runner, db_path, _ = _drifted_store(tmp_path)
    out = runner.invoke(app, ["history", "--db", str(db_path)]).output
    assert "look like the same cohort under two labels" in out
    assert "variant" in out


def test_no_warning_when_labels_are_consistent(tmp_path):
    runner = CliRunner()
    db_path = tmp_path / "clean.db"
    assert _import(runner, db_path, FIXTURES_DIR).exit_code == 0
    out = runner.invoke(app, ["history", "--db", str(db_path)]).output
    assert "look like the same cohort" not in out
