"""Dated manual import: `driverdna import --date` / a manifest entry's
`date` field set `lap_date` the same way `sync` does from the API's
startTime, so manually-imported laps become eligible for M6 trend. The
trend algorithm itself is covered exhaustively in test_scoring.py; these
tests are about the CLI plumbing — validation, precedence, persistence.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.db import Database

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SRC_A = FIXTURES_DIR / "Garage_61_RH11X7.csv"
_SRC_B = FIXTURES_DIR / "Garage_61_HKWPXX.csv"


def _lap_dates(db_path: Path) -> dict[str, str | None]:
    with Database.open(db_path) as db:
        rows = db.conn.execute("SELECT source_file, lap_date FROM laps").fetchall()
        return {Path(r["source_file"]).name: r["lap_date"] for r in rows}


def test_flag_date_applies_to_every_lap_without_a_manifest(tmp_path):
    csvs = tmp_path / "csvs"
    csvs.mkdir()
    shutil.copy(_SRC_A, csvs / "a.csv")
    shutil.copy(_SRC_B, csvs / "b.csv")

    db_path = tmp_path / "test.db"
    result = CliRunner().invoke(
        app,
        ["import", str(csvs), "--car", "GR86", "--track", "SomeTrack",
         "--db", str(db_path), "--date", "2026-06-01"],
    )
    assert result.exit_code == 0, result.output
    dates = _lap_dates(db_path)
    assert dates == {"a.csv": "2026-06-01", "b.csv": "2026-06-01"}


def test_no_date_flag_leaves_laps_undated(tmp_path):
    csvs = tmp_path / "csvs"
    csvs.mkdir()
    shutil.copy(_SRC_A, csvs / "a.csv")

    db_path = tmp_path / "test.db"
    result = CliRunner().invoke(
        app, ["import", str(csvs), "--car", "GR86", "--track", "SomeTrack",
              "--db", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    assert _lap_dates(db_path) == {"a.csv": None}


def test_invalid_date_flag_rejected_loudly_and_imports_nothing(tmp_path):
    csvs = tmp_path / "csvs"
    csvs.mkdir()
    shutil.copy(_SRC_A, csvs / "a.csv")
    db_path = tmp_path / "test.db"

    result = CliRunner().invoke(
        app, ["import", str(csvs), "--car", "GR86", "--track", "SomeTrack",
              "--db", str(db_path), "--date", "not-a-date"],
    )
    assert result.exit_code == 2
    assert "not valid" in result.output
    assert not db_path.exists()


def test_full_iso8601_timestamp_accepted(tmp_path):
    csvs = tmp_path / "csvs"
    csvs.mkdir()
    shutil.copy(_SRC_A, csvs / "a.csv")
    db_path = tmp_path / "test.db"

    result = CliRunner().invoke(
        app, ["import", str(csvs), "--car", "GR86", "--track", "SomeTrack",
              "--db", str(db_path), "--date", "2026-06-01T14:30:00Z"],
    )
    assert result.exit_code == 0, result.output
    assert _lap_dates(db_path) == {"a.csv": "2026-06-01T14:30:00Z"}


def _manifest_dir(tmp_path: Path, entries: list[dict]) -> Path:
    d = tmp_path / "manifest_dir"
    d.mkdir()
    shutil.copy(_SRC_A, d / "a.csv")
    shutil.copy(_SRC_B, d / "b.csv")
    lines = []
    for e in entries:
        lines.append("[[fixtures]]")
        for k, v in e.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    (d / "manifest.toml").write_text("\n".join(lines))
    return d


def test_manifest_per_entry_date_overrides_flag_fallback(tmp_path):
    d = _manifest_dir(tmp_path, [
        {"file": "a.csv", "car": "GR86", "track": "T", "role": "self",
         "date": "2026-01-15"},
        {"file": "b.csv", "car": "GR86", "track": "T", "role": "self"},
    ])
    result = CliRunner().invoke(
        app, ["import", str(d), "--db", str(tmp_path / "t.db"), "--date", "2026-06-01"],
    )
    assert result.exit_code == 0, result.output
    dates = _lap_dates(tmp_path / "t.db")
    assert dates["a.csv"] == "2026-01-15"  # entry's own date wins
    assert dates["b.csv"] == "2026-06-01"  # --date fills the gap


def test_manifest_without_date_or_flag_stays_undated(tmp_path):
    d = _manifest_dir(tmp_path, [
        {"file": "a.csv", "car": "GR86", "track": "T", "role": "self"},
    ])
    result = CliRunner().invoke(app, ["import", str(d), "--db", str(tmp_path / "t.db")])
    assert result.exit_code == 0, result.output
    assert _lap_dates(tmp_path / "t.db") == {"a.csv": None}


def test_invalid_manifest_entry_date_rejected_loudly(tmp_path):
    d = _manifest_dir(tmp_path, [
        {"file": "a.csv", "car": "GR86", "track": "T", "role": "self",
         "date": "not-a-real-date"},
    ])
    result = CliRunner().invoke(app, ["import", str(d), "--db", str(tmp_path / "t.db")])
    assert result.exit_code == 2
    assert "not valid" in result.output
