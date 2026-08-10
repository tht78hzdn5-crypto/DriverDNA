"""M4 report tests: deterministic payload/JSON, offline HTML, CLI."""

import json
from pathlib import Path

from typer.testing import CliRunner

from driverdna.cli import app
from driverdna.config import DriverDNAConfig
from driverdna.db import Database
from driverdna.report.builder import (
    _TOKENS,
    render_cohort_html,
    render_cohort_markdown,
    render_driver_html,
    render_driver_markdown,
)
from driverdna.model.taxonomy import FUNDAMENTALS
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


def test_html_is_byte_identical_across_independent_renders():
    """U4's own requirement ("report determinism tests must stay green
    through the restyle") needs a test that actually exercises HTML, not
    just the payload/JSON — this is that test."""
    with _build_db() as db:
        payload = build_cohort_payload(db, **COHORT, config=CONFIG)
        a = render_cohort_html(payload)
        b = render_cohort_html(payload)
    assert a == b


def test_report_css_tokens_match_ui_tokens_json():
    """U4: the static reports and the SPA share one appearance by both
    deriving from ui/tokens.json. A static HTML file has no JS runtime to
    import the JSON at render time, so report/builder.py mirrors it in
    `_TOKENS` — this is the guard against that mirror silently drifting."""
    tokens_path = Path(__file__).parent.parent / "ui" / "tokens.json"
    tokens = json.loads(tokens_path.read_text())
    assert _TOKENS == {**tokens["color"], **tokens["font"]}


def test_html_uses_token_colors_not_the_old_light_theme():
    with _build_db() as db:
        payload = build_cohort_payload(db, **COHORT, config=CONFIG)
        page = render_cohort_html(payload)
    assert "var(--base)" in page and "var(--warn)" in page
    # The old hardcoded light-theme palette must be fully gone.
    for old_color in ("#1a1a1a", "#f2f2f2", "#4472a8", "#fff8e6", "#e0b400"):
        assert old_color not in page


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


def test_cohort_payload_carries_driver_model_beliefs():
    from driverdna.model.taxonomy import FUNDAMENTALS, SignalStatus

    with _build_db() as db:
        payload = build_cohort_payload(db, **COHORT, config=CONFIG)
    dm = payload["driver_model"]
    assert dm["driver"] == "owner"
    assert set(dm["beliefs"]) == set(FUNDAMENTALS)
    vision = dm["beliefs"]["vision"]
    assert vision["signal_status"] == SignalStatus.NO_SIGNAL.value
    assert vision["score"] is None and "no telemetry channel" in vision["insufficient_reason"]
    rotation = dm["beliefs"]["rotation"]
    assert rotation["score"] is None or 0.0 <= rotation["score"] <= 100.0


def test_driver_payload_reuses_cohort_driver_model_without_recomputing():
    with _build_db() as db:
        cohort_payload = build_cohort_payload(db, **COHORT, config=CONFIG)
        driver_payload = build_driver_payload(db, CONFIG)
    assert driver_payload["driver_model"] == cohort_payload["driver_model"]


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


# --- Fundamental grouping in the static report (A46) -----------------------


def _fixture_payload(tmp_path):
    """A payload over the real fixture laps — the synthetic cohort triggers
    no detectors, so only this one exercises vs-principle rendering."""
    db_path = tmp_path / "r.db"
    result = CliRunner().invoke(
        app, ["import", str(Path(__file__).parent / "fixtures"), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    with Database.open(str(db_path)) as db:
        # The deepest cohort: a single-lap one clears no gate, so it would
        # prove nothing about how shown findings render.
        row = db.conn.execute(
            """SELECT driver, car, track, COUNT(*) n FROM laps WHERE role='self'
               GROUP BY driver, car, track ORDER BY n DESC, car, track LIMIT 1"""
        ).fetchone()
        return build_cohort_payload(
            db, driver=row["driver"], car=row["car"], track=row["track"], config=CONFIG
        )


def test_markdown_groups_findings_by_fundamental(tmp_path):
    payload = _fixture_payload(tmp_path)
    md = render_cohort_markdown(payload)
    shown = [f for f in payload["findings"] if f["shown"] and not f.get("annotation")]
    assert shown, "sanity: the fixtures must produce shown findings"
    for fundamental in {f["fundamental"] for f in shown}:
        label = FUNDAMENTALS[fundamental].label
        assert f"### {label}" in md, f"no section for {label}"


def test_markdown_keeps_the_source_tag_on_every_finding(tmp_path):
    # Grouping changed; SPEC decision 3 did not — a finding without its
    # source tag would be the blended reporting the spec forbids.
    payload = _fixture_payload(tmp_path)
    md = render_cohort_markdown(payload)
    for source in {f["source"] for f in payload["findings"] if f["shown"]}:
        assert source in md


def test_reference_boilerplate_is_not_repeated_per_row(tmp_path):
    payload = _fixture_payload(tmp_path)
    md = render_cohort_markdown(payload)
    html = render_cohort_html(payload)
    assert md.count("not recoverable time") <= 1
    assert html.count("not recoverable time") <= 1


def test_html_groups_findings_by_fundamental(tmp_path):
    payload = _fixture_payload(tmp_path)
    html = render_cohort_html(payload)
    shown = [f for f in payload["findings"] if f["shown"]]
    for fundamental in {f["fundamental"] for f in shown}:
        assert FUNDAMENTALS[fundamental].label in html


# --- A48: the report echoes the SPA's coaching-led fundamental sections ----
# The SPA promotes each fundamental's top-ranked coaching principle above its
# measurements. A report that still opened every section with a table would be
# a second, quieter voice for the same data — the exact divergence A46 exists
# to prevent. Markdown and inline CSS can't collapse the tables the way the
# browser does, so the report states the order rather than the affordance:
# coaching first, measurements under it.


def _lede_principle(payload, fundamental):
    """The principle the SPA would lede this fundamental with: headline first,
    then `secondary` in the engine's own ranked order. Anchored to the payload
    rather than restating the rule, so this test fails if either surface
    starts choosing differently."""
    coaching = payload["coaching"]
    ranked = ([coaching["headline"]] if coaching["headline"] else []) + coaching["secondary"]
    for c in ranked:
        if c["fundamental"] == fundamental:
            return c
    return None


def test_markdown_ledes_each_fundamental_with_its_coaching_expression(tmp_path):
    payload = _fixture_payload(tmp_path)
    md = render_cohort_markdown(payload)
    coached = {c["fundamental"] for c in payload["coaching"]["secondary"]}
    assert coached, "sanity: the fixtures must produce coaching candidates"
    for fundamental in coached:
        lede = _lede_principle(payload, fundamental)
        label = FUNDAMENTALS[fundamental].label
        assert f"### {label}" in md, f"no section for {label}"
        section = md.split(f"### {label}", 1)[1]
        expression = lede["coaching_expression"]
        assert expression in section.split("###", 1)[0], (
            f"{label}'s section does not lede with its coaching expression"
        )
        # Coaching above the measurements, not below them.
        body = section.split("###", 1)[0]
        if "| source |" in body:
            assert body.index(expression) < body.index("| source |")


def test_html_ledes_each_fundamental_with_its_coaching_expression(tmp_path):
    import html as html_mod

    payload = _fixture_payload(tmp_path)
    rendered = render_cohort_html(payload)
    for fundamental in {c["fundamental"] for c in payload["coaching"]["secondary"]}:
        lede = _lede_principle(payload, fundamental)
        # Escaped, like every other driver-facing string in this report — the
        # ontology's prose is full of apostrophes ("haven't committed to").
        assert html_mod.escape(lede["coaching_expression"]) in rendered
        assert html_mod.escape(lede["driving_principle"]) in rendered


def test_report_shows_a_coached_fundamental_with_no_findings(tmp_path):
    """`consistency` is the honest edge case: a major coaching signal at many
    corners with nothing clearing the finding gates. Dropping its section
    because the table would be empty would hide the loudest thing the engine
    has to say about this driver."""
    payload = _fixture_payload(tmp_path)
    shown = {f["fundamental"] for f in payload["findings"] if f["shown"]}
    coached = {c["fundamental"] for c in payload["coaching"]["secondary"]}
    orphans = coached - shown
    assert orphans, "sanity: the fixtures must include a coached-but-ungated fundamental"
    md = render_cohort_markdown(payload)
    for fundamental in orphans:
        assert f"### {FUNDAMENTALS[fundamental].label}" in md
        assert _lede_principle(payload, fundamental)["coaching_expression"] in md


def test_report_says_each_coaching_expression_once_per_section(tmp_path):
    """The lede is the section's voice; repeating it under its own heading is
    the two-voices problem one level in (A46)."""
    payload = _fixture_payload(tmp_path)
    md = render_cohort_markdown(payload)
    for fundamental in {c["fundamental"] for c in payload["coaching"]["secondary"]}:
        label = FUNDAMENTALS[fundamental].label
        section = md.split(f"### {label}", 1)[1].split("###", 1)[0]
        expression = _lede_principle(payload, fundamental)["coaching_expression"]
        assert section.count(expression) == 1
