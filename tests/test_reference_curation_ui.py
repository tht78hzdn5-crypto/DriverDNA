"""Browser-driven checks for reference-lap R2 (identity) + R3 (curation) UI —
SPEC.md A39: the cohort page's References panel (envelope, contributor
identity, exclude/include toggle) and the corner drill's reference overlay
columns. API-level parity (payload shape, exclusion semantics) is already
proven by test_api.py; this confirms the browser path that drives them
renders correctly, mirroring test_cockpit_ui.py's convention for write
flows. Skipped automatically when Playwright/Chromium or the built SPA is
absent.

Uses its own isolated DB (CLI import + one reference lap), not the shared
tests/fixtures/ render-parity DB — which deliberately carries zero
reference laps so the byte-identical report/determinism anchors are never
perturbed (see docs/UI-SPEC.md's "Reference-lap visibility" test-consequences
note).
"""

from __future__ import annotations

import shutil
import socket
import threading
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SPA_SLUG = "gr86-spa-francorchamps"


def _find_chrome() -> Path | None:
    hits = sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))
    return hits[-1] if hits else None


CHROME = _find_chrome()

pytestmark = pytest.mark.skipif(
    CHROME is None or not (STATIC / "index.html").exists(),
    reason="Chromium binary or built SPA not present",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path):
    """A real server over a real cohort plus one reference lap -- imported
    from spa-blind-2026-07/, which the top-level FIXTURES_DIR import never
    touches (non-recursive glob), so its content_hash is fresh and it
    imports as a genuine second, reference-role lap rather than being
    content-deduped against the self import (A12)."""
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    from driverdna.cli import app as cli_app
    from driverdna.ui.api import create_app

    db_path = tmp_path / "refcuration.db"
    runner = CliRunner()
    result = runner.invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
    assert result.exit_code == 0, result.output

    ref_dir = tmp_path / "ref_import"
    ref_dir.mkdir()
    shutil.copy(
        FIXTURES_DIR / "spa-blind-2026-07" / "Garage_61_60GBCK.csv",
        ref_dir / "Garage_61_60GBCK.csv",
    )
    result = runner.invoke(cli_app, [
        "import", str(ref_dir), "--db", str(db_path),
        "--role", "reference", "--driver", "teammate JD",
        "--car", "GR86", "--track", "Spa-Francorchamps",
    ])
    assert result.exit_code == 0, result.output

    app = create_app(db_path, tmp_path / "config.toml")
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="spa")

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/openapi.json", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.1)
    yield base, db_path
    uv.should_exit = True
    thread.join(timeout=5)


def test_cohort_page_shows_reference_identity_and_envelope(server):
    base, _ = server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base}/#/cohort/{SPA_SLUG}", wait_until="networkidle")
        page.wait_for_selector("text=Reference laps", timeout=8000)

        body = page.locator("body").inner_text()
        assert "teammate JD" in body
        assert "envelope: n=1" in body

        # The pit-board tile counts the active pool, from the payload.
        tile = page.locator(".tile", has_text="Reference laps")
        assert "1" in tile.inner_text()
        browser.close()


def test_exclude_then_include_reference_lap_updates_the_page_live(server):
    base, db_path = server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base}/#/cohort/{SPA_SLUG}", wait_until="networkidle")
        page.wait_for_selector("button:has-text('Exclude')", timeout=8000)

        page.click("button:has-text('Exclude')")
        page.wait_for_selector("text=excluded", timeout=8000)
        page.wait_for_timeout(200)

        body = page.locator("body").inner_text()
        assert "all\ncurrently excluded" in body or "all currently excluded" in body.replace("\n", " ")
        tile = page.locator(".tile", has_text="Reference laps")
        assert tile.inner_text().strip().startswith("0")

        # Re-include restores the envelope, live, no page reload.
        page.click("button:has-text('Include')")
        page.wait_for_selector("text=envelope: n=1", timeout=8000)
        browser.close()

    # The DB reflects exactly what the clicks did.
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    n = conn.execute("SELECT COUNT(*) FROM reference_exclusions").fetchone()[0]
    conn.close()
    assert n == 0  # ended included: exclude then include nets to zero rows...
    # ...but upsert-on-conflict means the row persists with a stale note if
    # only ever updated, never deleted -- assert the actual API-visible
    # state instead of the row's mere existence.
    r = httpx.get(f"{base}/api/cohorts/{SPA_SLUG}/payload")
    assert r.json()["references"]["n_excluded"] == 0


def test_corner_drill_shows_reference_overlay_columns(server):
    base, _ = server
    corners = httpx.get(f"{base}/api/cohorts/{SPA_SLUG}/corners").json()

    # Find a corner where the one reference lap actually produced a phase
    # time -- not guaranteed for every corner on a single real lap.
    target = None
    for c in corners:
        phases = httpx.get(
            f"{base}/api/cohorts/{SPA_SLUG}/corners/{c['corner_id']}/reference-phases"
        ).json()
        if any(v is not None for v in phases.values()):
            target = c["corner_id"]
            break
    assert target, "expected at least one corner to have reference phase data"

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base}/#/corner/{SPA_SLUG}/{target}", wait_until="networkidle")
        page.wait_for_selector("text=ref n", timeout=8000)
        page.wait_for_timeout(300)

        # v2 CSS uppercases table headers (same gotcha test_cockpit_ui.py
        # notes for its own report text) -- compare lower-cased.
        header_text = page.locator("thead").first.inner_text().lower()
        assert "ref n" in header_text and "ref median" in header_text and "ref best" in header_text
        browser.close()
