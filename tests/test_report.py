"""M4 report tests: deterministic payload/JSON, offline HTML, CLI."""

from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.report.builder import (
    render_cohort_html,
    render_cohort_markdown,
    render_driver_html,
    render_driver_markdown,
)
from driverdna.report.payload import (
    build_cohort_payload,
    build_driver_payload,
    to_normalized_json,
)
from synth import run_synthetic_lap, track_lap, warp_time

CONFIG = DriverDNAConfig()
COHORT = {"driver": "owner", "car": "TestCar", "track": "SynthRing"}
C01_WARP_WINDOW = (0.19, 0.22)


def _build_db():
    db = Database.open(":memory:")
    for i in range(6):
        run_synthetic_lap(db, track_lap(src=f"fast{i}.csv"), session_key=f"s{i % 2 + 1}")
    for i in range(6):
        lap = warp_time(track_lap(src=f"slow{i}.csv"), C01_WARP_WINDOW, 0.4)
        run_synthetic_lap(db, lap, session_key=f"s{i % 2 + 1}")
    return db


def test_payload_and_json_deterministic():
    with _build_db() as db:
        a = build_cohort_payload(db, **COHORT, config=CONFIG)
        b = build_cohort_payload(db, **COHORT, config=CONFIG)
        assert a == b
        assert to_normalized_json(a) == to_normalized_json(b)
        assert "payload_version" in a and a["findings"]


def test_markdown_shows_findings_and_honesty_sections():
    with _build_db() as db:
        payload = build_cohort_payload(db, **COHORT, config=CONFIG)
        md = render_cohort_markdown(payload)
    assert "C01" in md
    assert "vs-self" in md
    assert "Not measured (never inferred)" in md
    assert "tire slip" in md
    assert "Suppressed findings:" in md


def test_html_is_self_contained_with_charts():
    with _build_db() as db:
        payload = build_cohort_payload(db, **COHORT, config=CONFIG)
        page = render_cohort_html(payload)
    assert page.startswith("<!DOCTYPE html>")
    assert "<svg" in page and "polyline" in page
    for forbidden in ("http://", "https://", "src=", "@import", "url("):
        assert forbidden not in page, f"external reference found: {forbidden}"


def test_driver_rollup_gates_single_track():
    with _build_db() as db:
        payload = build_driver_payload(db, CONFIG)
        md = render_driver_markdown(payload)
        page = render_driver_html(payload)
    assert payload["cross_track_rollups"]
    assert all(not r["shown"] for r in payload["cross_track_rollups"])
    assert "suppressed" in md and "track(s) <" in md
    assert "cross-car claims" in md
    assert page.startswith("<!DOCTYPE html>")


def test_report_cli_writes_all_formats(tmp_path):
    db_path = tmp_path / "r.db"
    runner = CliRunner()
    result = runner.invoke(
        app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    out_dir = tmp_path / "reports"
    result = runner.invoke(
        app, ["report", "--db", str(db_path), "--out-dir", str(out_dir)]
    )
    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in out_dir.iterdir())
    assert "driver.html" in names and "driver.json" in names and "driver.md" in names
    assert any(n.startswith("gr86-spa") for n in names)
    assert any(n.startswith("mustang-laguna") for n in names)
    spa_html = next(out_dir.glob("gr86-spa*.html")).read_text()
    assert "<svg" in spa_html


def test_report_cli_cohort_filter(tmp_path):
    db_path = tmp_path / "r.db"
    runner = CliRunner()
    runner.invoke(
        app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)]
    )
    out_dir = tmp_path / "reports"
    result = runner.invoke(
        app,
        ["report", "--db", str(db_path), "--out-dir", str(out_dir),
         "--cohort", "GR86:Spa-Francorchamps"],
    )
    assert result.exit_code == 0, result.output
    cohort_files = [p for p in out_dir.iterdir() if not p.name.startswith("driver")]
    assert all("gr86" in p.name for p in cohort_files)

    result = runner.invoke(
        app,
        ["report", "--db", str(db_path), "--out-dir", str(out_dir),
         "--cohort", "Nope:Nowhere"],
    )
    assert result.exit_code == 2
