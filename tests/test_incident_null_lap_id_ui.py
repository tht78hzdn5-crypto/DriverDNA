"""Browser-driven check for BUG-053: a cohort page must render when an
incident event has a null lap_id.

An incident event's lap_id is null whenever the incident lap's laps.lap_id
was never stored (44 laps on the owner corpus at filing time; the Charlotte
Mustang cohort's payload carries 7 such events). IncidentCard rendered
event.lap_id.slice(0, 6) unguarded, so the whole cohort page blanked with
a TypeError and no incident card ever rendered. The fix falls back to the
lap_pk the payload always carries (lapIdShort in ui/src/views/shared.jsx).

The fixture import gives the GR86/Spa cohort two incidents with real
lap_ids; the test nulls one incident lap's lap_id in the test-only DB,
which is exactly the state the engine produces for those 44 laps — the
payload then carries lap_id null for that event. Skipped automatically
when Playwright/Chromium or the built SPA is absent.
"""

from __future__ import annotations

import socket
import sqlite3
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
SLUG = "gr86-spa-francorchamps"

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


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    from driverdna.cli import app as cli_app
    from driverdna.ui.api import create_app

    root = tmp_path_factory.mktemp("incident-null-lap-id")
    db_path = root / "null-lap-id.db"
    assert CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    ).exit_code == 0

    # One incident lap with no stored lap_id, mirroring the owner corpus:
    # pick the incident lap with the lowest lap_pk and null its lap_id.
    # The payload then carries lap_id null for that incident event, with
    # lap_pk still present — the exact shape BUG-053 is about.
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT lap_pk FROM incidents ORDER BY lap_pk LIMIT 1"
    ).fetchone()
    assert row, "fixture precondition: the fixture import has an incident"
    lap_pk = row[0]
    conn.execute("UPDATE laps SET lap_id = NULL WHERE lap_pk = ?", (lap_pk,))
    conn.commit()
    conn.close()

    app = create_app(db_path, root / "config.toml")
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="spa")

    port = _free_port()
    uv = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/api/cohorts", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.1)
    yield base, lap_pk
    uv.should_exit = True
    thread.join(timeout=5)


def test_cohort_page_renders_with_a_null_lap_id_incident(server):
    """The page must load, render every incident card, and show the lap_pk
    fallback where the lap_id is missing — not blank with a TypeError."""
    base, lap_pk = server
    payload = httpx.get(f"{base}/api/cohorts/{SLUG}/payload", timeout=10).json()
    events = payload["incidents"]["events"]
    assert events, "fixture precondition: the cohort has incident events"
    assert any(e["lap_id"] is None for e in events), (
        "fixture precondition: one incident event must carry lap_id null"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/#/cohort/{SLUG}", wait_until="networkidle")
        page.wait_for_selector(".incident-card", timeout=8000)

        assert errors == [], f"page threw while rendering: {errors}"
        assert page.locator(".incident-card").count() == len(events), (
            f"expected one card per incident event ({len(events)}), "
            f"found {page.locator('.incident-card').count()}"
        )
        # The null-lap_id card falls back to its lap_pk, not a blank chip.
        # The chip sits inside the card's closed <details>, so read the DOM
        # text (inner_text omits collapsed content; the parity crawler
        # reads inside closed <details> the same way).
        dom_text = page.evaluate("document.body.textContent")
        assert f"#{lap_pk}" in dom_text
        browser.close()
