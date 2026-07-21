"""Browser-driven test of the upload-laps flow (view 7, docs/UI-SPEC.md): a
real file picked, a real multipart POST, a real result rendered — and the
true cold-start path (no DB file exists yet) shows direction, not a raw
CLI-flavored 404. Skipped automatically when Playwright/Chromium or the
built SPA is absent, mirroring test_offline.py's convention.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import httpx
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
ONE_LAP = FIXTURES_DIR / "Garage_61_HKWPXX.csv"


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
def cold_server(tmp_path):
    """A server pointed at a DB path that does not exist yet — the true
    cold-start state, before any lap has ever been imported."""
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    from driverdna.ui.api import create_app

    db_path = tmp_path / "cold.db"
    assert not db_path.exists()
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
            # /openapi.json always responds, unlike /api/cohorts which 404s
            # until a DB exists — that 404 is exactly the state under test.
            if httpx.get(f"{base}/openapi.json", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.1)
    yield base, db_path
    uv.should_exit = True
    thread.join(timeout=5)


def test_cold_start_shows_direction_not_a_raw_cli_error(cold_server):
    base, db_path = cold_server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base}/#/", wait_until="networkidle")
        page.wait_for_timeout(400)
        body = page.locator("body").inner_text()
        assert "no DB at" not in body, "raw CLI-flavored 404 leaked into the cold-start UI"
        assert "Import laps" in body
        browser.close()


def test_upload_flow_end_to_end_through_the_real_browser(cold_server):
    """File picked, form filled, submitted, result rendered, and the link
    into the newly-landed cohort actually works — the full path a driver
    with zero CLI experience would take."""
    base, db_path = cold_server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page(viewport={"width": 960, "height": 900})

        page.goto(f"{base}/#/upload", wait_until="networkidle")
        page.set_input_files("input[type=file]", str(ONE_LAP.resolve()))
        page.fill("input[placeholder='GR86']", "GR86")
        page.fill("input[placeholder='Spa-Francorchamps']", "Spa-Francorchamps")
        page.click("button:has-text('Import')")
        page.wait_for_selector("text=Import result", timeout=8000)
        page.wait_for_timeout(300)

        result_text = page.locator("body").inner_text()
        assert "imported" in result_text
        assert "corners 14/14 matched" in result_text
        assert "View GR86 @ Spa-Francorchamps" in result_text
        assert db_path.exists(), "the DB must exist now — the cold-start path worked"

        page.click("text=View GR86 @ Spa-Francorchamps")
        page.wait_for_selector("svg.trackmap", timeout=8000)
        assert "GR86" in page.locator("h1").first.inner_text()

        browser.close()

    # The API-level parity test already proves DB-effect equivalence with
    # the CLI (tests/test_upload_api.py); this confirms the browser path
    # that drives it renders real, correct numbers end to end.
    assert httpx.get(f"{base}/api/cohorts").json() == [
        {"driver": "owner", "car": "GR86", "track": "Spa-Francorchamps",
         "slug": "gr86-spa-francorchamps"}
    ]


def test_duplicate_reupload_reported_not_double_counted(cold_server):
    base, _ = cold_server
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{base}/#/upload", wait_until="networkidle")

        for _ in range(2):
            page.set_input_files("input[type=file]", str(ONE_LAP.resolve()))
            page.fill("input[placeholder='GR86']", "GR86")
            page.fill("input[placeholder='Spa-Francorchamps']", "Spa-Francorchamps")
            page.click("button:has-text('Import')")
            page.wait_for_selector("text=Import result", timeout=8000)
            page.wait_for_timeout(300)

        assert "duplicate" in page.locator("body").inner_text()
        browser.close()

    laps = httpx.get(f"{base}/api/laps?cohort=gr86-spa-francorchamps").json()
    assert len(laps) == 1, "a re-uploaded identical file must not double-count"
