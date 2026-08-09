"""Browser-driven checks for U6 (cockpit actions, docs/UI-SPEC.md): the Sync
button's no-token guidance state and the Rebuild map confirm gate. The API
parity/token tests (test_cockpit_api.py) already prove DB-effect equivalence
with the CLI; this confirms the browser path that drives them renders
correctly, mirroring test_upload_ui.py's convention for write flows. Skipped
automatically when Playwright/Chromium or the built SPA is absent.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from browser import chromium_executable

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

CHROME = chromium_executable()

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        CHROME is None or not (STATIC / "index.html").exists(),
        reason="Chromium binary or built SPA not present",
    ),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """A real server over a real imported fixture cohort -- the Sync/Rebuild
    buttons only render on views that already require a populated DB."""
    monkeypatch.delenv("GARAGE61_TOKEN", raising=False)
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    from driverdna.cli import app as cli_app
    from driverdna.ui.api import create_app

    db_path = tmp_path / "cockpit.db"
    result = CliRunner().invoke(cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)])
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


def test_sync_button_shows_guidance_not_an_input_field_without_a_token(server):
    base, db_path = server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base}/#/", wait_until="networkidle")
        page.click("button:has-text('Sync')")
        page.wait_for_selector("text=Set GARAGE61_TOKEN to sync.", timeout=8000)

        # Directive guidance, never a place to type a secret into the browser.
        assert page.locator("input[type=password]").count() == 0
        assert page.locator("input[name=token]").count() == 0
        assert page.locator("input[name=car]").count() == 0  # no stray sync form either
        browser.close()

    # Nothing written: the same DB the fixtures were imported into, untouched.
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    laps_before = conn.execute("SELECT COUNT(*) FROM laps").fetchone()[0]
    conn.close()
    assert laps_before == 12  # every fixture CSV's own lap count, not one more


def test_rebuild_map_confirm_gate_then_report_through_the_real_browser(server):
    base, _ = server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 1000, "height": 900})
        page.goto(f"{base}/#/cohort/gr86-spa-francorchamps", wait_until="networkidle")
        page.wait_for_selector("svg.trackmap", timeout=8000)

        # An unconfirmed click changes nothing (decision 5): Cancel closes the
        # gate with no rebuild report ever appearing.
        page.click("button:has-text('Rebuild map')")
        page.wait_for_selector("text=confirm to proceed", timeout=8000)
        page.click("button:has-text('Cancel')")
        page.wait_for_timeout(200)
        assert page.locator("text=Rebuild report").count() == 0

        # The distinct confirm action actually runs it and renders the report.
        page.click("button:has-text('Rebuild map')")
        page.wait_for_selector("text=confirm to proceed", timeout=8000)
        page.click("button:has-text('Confirm rebuild')")
        page.wait_for_selector("text=Rebuild report", timeout=8000)
        page.wait_for_timeout(200)

        report_text = page.locator("body").inner_text().lower()  # v2: th/eyebrow render upper-case
        assert "c01" in report_text
        assert "re-measured" in report_text
        browser.close()

    # The endpoint's own JSON confirms the browser rendered the real result.
    r = httpx.post(f"{base}/api/cohorts/gr86-spa-francorchamps/rebuild-map")
    assert r.status_code == 200
    assert r.json()["car"] == "GR86"
