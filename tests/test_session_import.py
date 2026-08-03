"""Session labeling for manual imports: `driverdna import --session` sets
`session_key` the same way `sync` does from the API's event+session, so
manually-imported laps become eligible for the `min_sessions` gate and
within-session repeatability.  The downstream gates themselves are covered
in test_scoring.py and the attribution tests; these tests are about the CLI
plumbing — precedence, persistence — following the test_dated_import.py
pattern exactly.
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


def _session_keys(db_path: Path) -> dict[str, str | None]:
    with Database.open(db_path) as db:
        rows = db.conn.execute("SELECT source_file, session_key FROM laps").fetchall()
        return {Path(r["source_file"]).name: r["session_key"] for r in rows}


def test_flag_session_applies_to_every_lap_without_a_manifest(tmp_path):
    csvs = tmp_path / "csvs"
    csvs.mkdir()
    shutil.copy(_SRC_A, csvs / "a.csv")
    shutil.copy(_SRC_B, csvs / "b.csv")

    db_path = tmp_path / "test.db"
    result = CliRunner().invoke(
        app,
        ["import", str(csvs), "--car", "GR86", "--track", "SomeTrack",
         "--db", str(db_path), "--session", "morning-practice"],
    )
    assert result.exit_code == 0, result.output
    assert _session_keys(db_path) == {
        "a.csv": "morning-practice",
        "b.csv": "morning-practice",
    }


def test_no_session_flag_leaves_laps_without_session_key(tmp_path):
    csvs = tmp_path / "csvs"
    csvs.mkdir()
    shutil.copy(_SRC_A, csvs / "a.csv")

    db_path = tmp_path / "test.db"
    result = CliRunner().invoke(
        app, ["import", str(csvs), "--car", "GR86", "--track", "SomeTrack",
              "--db", str(db_path)],
    )
    assert result.exit_code == 0, result.output
    assert _session_keys(db_path) == {"a.csv": None}


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


def test_manifest_per_entry_session_overrides_flag_fallback(tmp_path):
    d = _manifest_dir(tmp_path, [
        {"file": "a.csv", "car": "GR86", "track": "T", "role": "self",
         "session": "qualifying"},
        {"file": "b.csv", "car": "GR86", "track": "T", "role": "self"},
    ])
    result = CliRunner().invoke(
        app, ["import", str(d), "--db", str(tmp_path / "t.db"),
              "--session", "race-1"],
    )
    assert result.exit_code == 0, result.output
    keys = _session_keys(tmp_path / "t.db")
    assert keys["a.csv"] == "qualifying"  # entry's own session wins
    assert keys["b.csv"] == "race-1"      # --session fills the gap


def test_manifest_without_session_or_flag_stays_none(tmp_path):
    d = _manifest_dir(tmp_path, [
        {"file": "a.csv", "car": "GR86", "track": "T", "role": "self"},
    ])
    result = CliRunner().invoke(
        app, ["import", str(d), "--db", str(tmp_path / "t.db")]
    )
    assert result.exit_code == 0, result.output
    assert _session_keys(tmp_path / "t.db") == {"a.csv": None}
