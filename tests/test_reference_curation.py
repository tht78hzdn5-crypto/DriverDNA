"""Reference laps R2 (identity/depth) + R3 (curation) — SPEC.md A39.

R2: the reference pool becomes inspectable instead of an opaque pooled
number — `build_cohort_payload`'s new `references` section names who
contributed (driver, lap time, date) and states the lap-time envelope
(n, median, best) those contributors add up to.

R3: a bad/unwanted reference lap can be excluded — reversibly and audited,
the same shape `finding_annotations` already established for findings
(mark, don't delete; live recompute; undo restores the prior state).
Exclusion is enforced once, at `db.phase_history`'s query surface (role=
'reference'), the same place role isolation itself is enforced (A34) — so
`vs_reference_findings` (attribution/ranker.py) and the corner-drill reads
need no changes of their own to honour it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from driverdna.attribution.engine import PHASES
from driverdna.attribution.ranker import vs_reference_findings
from driverdna.cli import app as cli_app
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.pipeline import phase_windows_from_stored
from driverdna.report.payload import build_cohort_payload
from synth import run_synthetic_lap, track_lap, warp_time

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}
CORNERS = ("C01", "C02", "C03")

# Matches test_attribution.py's own constant: C01's mid/exit windows sit
# around its apex (~21.5% of the lap).
C01_WARP_WINDOW = (0.19, 0.22)


@pytest.fixture()
def db():
    with Database.open(":memory:") as database:
        yield database


def _build_self_cohort(db, *, n=12) -> None:
    """Enough self laps (2 sessions) to clear every finding gate — mirrors
    test_attribution.py's own _build_cohort so vs-reference findings show
    rather than being suppressed for thin self history."""
    for i in range(n):
        lap = track_lap(src=f"self{i}.csv")
        run_synthetic_lap(db, lap, session_key=f"s{i % 2 + 1}", config=CONFIG)


def _reference(db, *, driver="faster-driver", warp_s=0.0, src):
    lap = track_lap(src=src)
    if warp_s:
        lap = warp_time(lap, C01_WARP_WINDOW, warp_s)
    return run_synthetic_lap(db, lap, driver=driver, role="reference", config=CONFIG)


def _windows(db):
    map_pk, _ = db.load_corner_map(car=COHORT["car"], track=COHORT["track"])
    return {
        cid: phase_windows_from_stored(w)
        for cid, w in db.load_corner_windows(map_pk).items()
    }


def _reference_phase_lap_pks(db) -> set[int]:
    """Every lap_pk phase_history(role='reference') returns, across every
    corner/phase — the read the envelope and the corner drill are built
    from. Used to check exclusion at the query surface without needing to
    know which corner/phase combination actually has data."""
    pks: set[int] = set()
    for corner_id in CORNERS:
        for phase in PHASES:
            for h in db.phase_history(
                car=COHORT["car"], track=COHORT["track"], corner_id=corner_id,
                phase=phase, role="reference",
            ):
                pks.add(h["lap_pk"])
    return pks


# --- R2: reference_laps_for_cohort (identity) -------------------------------


def test_reference_laps_for_cohort_lists_driver_time_date_and_excluded_flag(db):
    _build_self_cohort(db)
    _reference(db, driver="Alice", src="ref-alice.csv")
    _reference(db, driver="Bob", src="ref-bob.csv")

    contributors = db.reference_laps_for_cohort(car=COHORT["car"], track=COHORT["track"])
    assert {c["driver"] for c in contributors} == {"Alice", "Bob"}
    assert all(c["excluded"] is False for c in contributors)
    assert all(isinstance(c["duration_s"], float) for c in contributors)
    assert all(isinstance(c["lap_pk"], int) for c in contributors)


def test_reference_laps_for_cohort_is_empty_with_no_reference_laps(db):
    _build_self_cohort(db)
    assert db.reference_laps_for_cohort(car=COHORT["car"], track=COHORT["track"]) == []


def test_reference_laps_for_cohort_never_lists_self_laps(db):
    _build_self_cohort(db, n=2)
    assert db.reference_laps_for_cohort(car=COHORT["car"], track=COHORT["track"]) == []


# --- R3: exclude / include (curation) ---------------------------------------


def test_exclude_reference_lap_flags_without_deleting_and_is_reversible(db):
    _build_self_cohort(db)
    result = _reference(db, src="ref.csv")
    lap_pk = result.lap_pk

    db.exclude_reference_lap(lap_pk=lap_pk, note="looked like a fluke lap")
    exclusions = db.reference_exclusions()
    assert lap_pk in exclusions and exclusions[lap_pk]["note"] == "looked like a fluke lap"

    contributors = db.reference_laps_for_cohort(car=COHORT["car"], track=COHORT["track"])
    assert len(contributors) == 1 and contributors[0]["excluded"] is True
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM laps WHERE lap_pk=?", (lap_pk,)
    ).fetchone()["n"] == 1  # never deleted

    db.include_reference_lap(lap_pk)
    assert lap_pk not in db.reference_exclusions()
    assert db.reference_laps_for_cohort(car=COHORT["car"], track=COHORT["track"])[0]["excluded"] is False


def test_exclude_reference_lap_rejects_a_self_lap(db):
    _build_self_cohort(db, n=1)
    self_lap_pk = int(
        db.conn.execute("SELECT lap_pk FROM laps WHERE role='self'").fetchone()["lap_pk"]
    )
    with pytest.raises(ValueError):
        db.exclude_reference_lap(lap_pk=self_lap_pk)


def test_exclude_reference_lap_rejects_an_unknown_lap_pk(db):
    with pytest.raises(ValueError):
        db.exclude_reference_lap(lap_pk=999999)


def test_exclude_reference_lap_is_upsert_not_a_duplicate_row(db):
    _build_self_cohort(db)
    result = _reference(db, src="ref.csv")
    db.exclude_reference_lap(lap_pk=result.lap_pk, note="first note")
    db.exclude_reference_lap(lap_pk=result.lap_pk, note="revised note")
    assert db.reference_exclusions()[result.lap_pk]["note"] == "revised note"
    n = db.conn.execute("SELECT COUNT(*) n FROM reference_exclusions").fetchone()["n"]
    assert n == 1


def test_include_reference_lap_that_was_never_excluded_is_a_silent_no_op(db):
    """The DB layer doesn't reject this itself — same contract as
    `clear_annotation` (existence-checking is the API/CLI layer's job, per
    the audited-annotations precedent this mirrors)."""
    _build_self_cohort(db)
    result = _reference(db, src="ref.csv")
    db.include_reference_lap(result.lap_pk)  # must not raise
    assert result.lap_pk not in db.reference_exclusions()


# --- exclusion enforced at the query surface (role='reference' reads) ------


def test_phase_history_excludes_an_excluded_reference_laps_rows(db):
    _build_self_cohort(db)
    r1 = _reference(db, src="ref1.csv")
    r2 = _reference(db, src="ref2.csv")

    assert _reference_phase_lap_pks(db) == {r1.lap_pk, r2.lap_pk}

    db.exclude_reference_lap(lap_pk=r1.lap_pk)
    assert _reference_phase_lap_pks(db) == {r2.lap_pk}

    db.include_reference_lap(r1.lap_pk)
    assert _reference_phase_lap_pks(db) == {r1.lap_pk, r2.lap_pk}


def test_phase_history_self_role_is_unaffected_by_reference_exclusions(db):
    _build_self_cohort(db, n=2)
    ref = _reference(db, src="ref.csv")
    db.exclude_reference_lap(lap_pk=ref.lap_pk)

    self_pks = {
        h["lap_pk"]
        for corner_id in CORNERS
        for phase in PHASES
        for h in db.phase_history(
            car=COHORT["car"], track=COHORT["track"], corner_id=corner_id,
            phase=phase, role="self", driver="owner",
        )
    }
    assert self_pks  # self history exists...
    assert ref.lap_pk not in self_pks  # ...and was never in it anyway


# --- vs_reference_findings (ranker.py, UNCHANGED) recomputes on exclusion --


def test_vs_reference_envelope_recomputes_without_an_excluded_lap(db):
    """No change to attribution/ranker.py was needed for this: exclusion is
    enforced once, in db.phase_history's query surface, which
    vs_reference_findings already reads through."""
    _build_self_cohort(db)
    _reference(db, driver="fast-driver", warp_s=-0.3, src="fast.csv")
    slow_ref = _reference(db, driver="slow-driver", warp_s=0.3, src="slow.csv")
    windows = _windows(db)

    gaps_original = vs_reference_findings(db, **COHORT, windows_by_corner=windows, config=CONFIG)
    c01_before = {g.phase: g for g in gaps_original if g.corner_id == "C01"}
    assert c01_before  # both reference laps feed the envelope
    assert all(g.details["reference_n"] == 2 for g in c01_before.values())

    # Exclude the slower reference: the envelope should now be one lap's
    # worth (n=1).
    db.exclude_reference_lap(lap_pk=slow_ref.lap_pk)
    gaps_after = vs_reference_findings(db, **COHORT, windows_by_corner=windows, config=CONFIG)
    c01_after = {g.phase: g for g in gaps_after if g.corner_id == "C01"}
    assert c01_after
    assert all(g.details["reference_n"] == 1 for g in c01_after.values())

    # Reversible: re-including restores the exact original envelope.
    db.include_reference_lap(slow_ref.lap_pk)
    gaps_restored = vs_reference_findings(db, **COHORT, windows_by_corner=windows, config=CONFIG)
    assert gaps_restored == gaps_original


# --- R2 payload: build_cohort_payload's new `references` section ----------


def test_build_cohort_payload_references_section_shape_and_content(db):
    _build_self_cohort(db)
    alice = _reference(db, driver="Alice", warp_s=-0.1, src="alice.csv")
    bob = _reference(db, driver="Bob", warp_s=0.2, src="bob.csv")

    payload = build_cohort_payload(db, **COHORT, config=CONFIG)
    refs = payload["references"]
    assert refs["n"] == 2
    assert refs["n_excluded"] == 0
    assert refs["envelope"]["n"] == 2
    contributors = {c["lap_pk"]: c for c in refs["contributors"]}
    assert contributors[alice.lap_pk]["driver"] == "Alice"
    assert contributors[bob.lap_pk]["driver"] == "Bob"
    assert all(c["excluded"] is False for c in contributors.values())


def test_build_cohort_payload_references_section_reflects_exclusion(db):
    _build_self_cohort(db)
    alice = _reference(db, driver="Alice", src="alice.csv")
    bob = _reference(db, driver="Bob", src="bob.csv")
    db.exclude_reference_lap(lap_pk=bob.lap_pk, note="not representative")

    payload = build_cohort_payload(db, **COHORT, config=CONFIG)
    refs = payload["references"]
    assert refs["n"] == 1  # active only
    assert refs["n_excluded"] == 1
    assert refs["envelope"]["n"] == 1
    contributors = {c["lap_pk"]: c for c in refs["contributors"]}
    assert len(contributors) == 2  # both still listed -- marked, not hidden
    assert contributors[bob.lap_pk]["excluded"] is True
    assert contributors[alice.lap_pk]["excluded"] is False


def test_build_cohort_payload_references_section_empty_with_no_reference_laps(db):
    _build_self_cohort(db)
    payload = build_cohort_payload(db, **COHORT, config=CONFIG)
    assert payload["references"] == {
        "n": 0, "n_excluded": 0, "envelope": None, "contributors": [],
    }


def test_references_section_never_perturbs_self_sections_of_the_payload(db):
    """Same trust gate as M3's own reference-isolation test, one layer up:
    adding and then excluding a reference lap must never move the cohort,
    driver_model, coaching, cumulative_loss, metrics, phase_baselines, or
    self findings sections."""
    _build_self_cohort(db)
    before = build_cohort_payload(db, **COHORT, config=CONFIG)
    ref = _reference(db, src="ref.csv")
    db.exclude_reference_lap(lap_pk=ref.lap_pk)
    after = build_cohort_payload(db, **COHORT, config=CONFIG)

    for key in ("cohort", "cumulative_loss", "driver_model", "coaching", "metrics", "phase_baselines"):
        assert after[key] == before[key], key
    self_before = [f for f in before["findings"] if f["source"] != "vs-reference"]
    self_after = [f for f in after["findings"] if f["source"] != "vs-reference"]
    assert self_after == self_before


# --- CLI: exclude-reference / include-reference -----------------------------


def _import_reference_lap(runner, db_path, *, driver="teammate JD"):
    """A real reference lap in a real on-disk DB, via two CLI imports: the
    fixture directory (self, founds GR86 @ Spa-Francorchamps), then a
    second file tagged --role reference into the same cohort (A34: a
    reference lap can only import once a self lap already founded the
    cohort's map).

    The reference file comes from the spa-blind-2026-07/ subdirectory, not
    the top-level fixtures: `driverdna import FIXTURES_DIR` globs only the
    top level (non-recursive), so this file's content_hash was never
    touched by the first import -- reusing a top-level fixture here would
    be content-deduped as the same lap re-appearing under a new path (A12),
    never actually creating a second, reference-role row."""
    import tempfile

    result = runner.invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output

    with tempfile.TemporaryDirectory() as tmp:
        ref_file = Path(tmp) / "Garage_61_60GBCK.csv"
        shutil.copy(FIXTURES_DIR / "spa-blind-2026-07" / "Garage_61_60GBCK.csv", ref_file)
        result = runner.invoke(cli_app, [
            "import", tmp, "--db", str(db_path),
            "--role", "reference", "--driver", driver,
            "--car", "GR86", "--track", "Spa-Francorchamps",
        ])
        assert result.exit_code == 0, result.output

    with Database.open(db_path) as db:
        row = db.conn.execute(
            "SELECT lap_pk FROM laps WHERE role='reference'"
        ).fetchone()
        return int(row["lap_pk"])


def test_cli_exclude_then_include_reference_lap(tmp_path):
    db_path = tmp_path / "cli.db"
    runner = CliRunner()
    lap_pk = _import_reference_lap(runner, db_path)

    result = runner.invoke(cli_app, [
        "exclude-reference", str(lap_pk), "--db", str(db_path), "--note", "test exclusion",
    ])
    assert result.exit_code == 0, result.output
    with Database.open(db_path) as db:
        assert lap_pk in db.reference_exclusions()
        assert db.reference_exclusions()[lap_pk]["note"] == "test exclusion"

    result = runner.invoke(cli_app, ["include-reference", str(lap_pk), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    with Database.open(db_path) as db:
        assert lap_pk not in db.reference_exclusions()


def test_cli_exclude_reference_rejects_a_self_lap_pk(tmp_path):
    db_path = tmp_path / "cli2.db"
    runner = CliRunner()
    result = runner.invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    with Database.open(db_path) as db:
        self_lap_pk = int(
            db.conn.execute("SELECT lap_pk FROM laps WHERE role='self' LIMIT 1").fetchone()["lap_pk"]
        )
    result = runner.invoke(cli_app, ["exclude-reference", str(self_lap_pk), "--db", str(db_path)])
    assert result.exit_code == 2
    assert "not a reference lap" in result.output


def test_cli_exclude_reference_rejects_unknown_lap_pk(tmp_path):
    db_path = tmp_path / "cli3.db"
    runner = CliRunner()
    result = runner.invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli_app, ["exclude-reference", "999999", "--db", str(db_path)])
    assert result.exit_code == 2
    # Content-checked, not just the exit code: exit 2 alone doesn't
    # distinguish "rejected for the right reason" from e.g. a typo'd
    # command name, which also exits 2.
    assert "no such lap" in result.output.lower()


def test_cli_include_reference_rejects_a_lap_that_is_not_excluded(tmp_path):
    db_path = tmp_path / "cli4.db"
    runner = CliRunner()
    lap_pk = _import_reference_lap(runner, db_path)
    result = runner.invoke(cli_app, ["include-reference", str(lap_pk), "--db", str(db_path)])
    assert result.exit_code == 2
    assert "not currently excluded" in result.output.lower()
