"""A54 workstream 2, protocol 6 (click it): the Vision tier on #/model
renders the stored AI speculative guess inside the red entertainment flag,
while the score stays "—" and no numeric score or confidence appears for
vision.

Launches the real built SPA in Chromium against a fixture DB seeded with
a coach run carrying a vision guess. Skipped automatically when
Playwright/Chromium or the built SPA is absent, so the core suite stays
browser-free.
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from browser import chromium_executable
from driverdna.db import Database
from driverdna.ui.api import create_app

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
CHROME = chromium_executable()
GUESS = "Eyes drop to the apex too late; say out loud where you are looking at turn-in."

pytestmark = [
    # Selected by marker in CI's browser-tests job; without this the test
    # is deselected there and merely skipped in the pytest job — run nowhere.
    pytest.mark.browser,
    pytest.mark.skipif(
        CHROME is None or not (STATIC / "index.html").exists(),
        reason="Playwright/Chromium or the built SPA is absent",
    ),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_app(db_path: Path, config_path: Path):
    from fastapi.staticfiles import StaticFiles

    app = create_app(db_path, config_path)
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="spa")
    return app


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn

    root = tmp_path_factory.mktemp("vision_flag")
    db_path = root / "vision_flag.db"
    assert CliRunner().invoke(
        __import__("driverdna.cli", fromlist=["app"]).app,
        ["import", str(FIXTURES_DIR), "--db", str(db_path)],
    ).exit_code == 0

    with Database.open(db_path) as db:
        cohorts = db.conn.execute(
            "SELECT DISTINCT driver, car, track FROM laps"
        ).fetchall()
        for c in cohorts:
            db.store_coach_output(
                driver=c["driver"], car=c["car"], track=c["track"],
                payload_version=10, prompt_version="coach-v4", model="test",
                output_json=json.dumps({
                    "measured_priorities": [],
                    "coaching_priorities": [],
                    "coaching_plan": [],
                    "hypotheses": [],
                    "incident_explanations": [],
                    "fundamental_guesses": [
                        {"fundamental_id": "vision", "guess": GUESS},
                    ],
                }),
            )

    port = _free_port()
    config = uvicorn.Config(
        _build_app(db_path, root / "config.toml"),
        host="127.0.0.1", port=port, log_level="warning",
    )
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            # trust_env=False: a localhost probe must never go through an
            # egress proxy, and httpx chokes parsing some no_proxy entries
            # (bare IPv6 literals) when building its proxy map.
            if httpx.get(f"{base}/api/cohorts", timeout=1,
                         trust_env=False).status_code == 200:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.1)
    yield base
    uv.should_exit = True
    thread.join(timeout=5)


def test_model_view_shows_vision_guess_in_entertainment_flag(server):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        page.goto(f"{server}/#/model", wait_until="networkidle")
        page.wait_for_selector(".fbar", timeout=8000)
        flag = page.locator(".entertainment-flag")
        assert flag.count() == 1
        assert GUESS in flag.inner_text()
        assert "AI Speculation" in flag.inner_text()
        vision_bar = page.locator(".fbar", has_text="Vision").first
        assert vision_bar.locator(".fbar-score").inner_text().strip() == "—"
        browser.close()
