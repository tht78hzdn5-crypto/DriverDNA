"""U4 trust gate 5 (docs/UI-SPEC.md): "the app fully loads and operates
with all non-localhost network blocked." test_ui_static.py checks this
statically (no external URLs in the built assets); this is the dynamic
form — a real browser, with every non-localhost request actively blocked
at the network layer, driven across every route.

Skipped automatically when Playwright/Chromium or the built SPA is absent,
mirroring test_render_parity.py's convention.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
import pytest
from typer.testing import CliRunner

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


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


def _build_app(db_path: Path, config_path: Path):
    from fastapi.staticfiles import StaticFiles

    from driverdna.ui.api import create_app

    app = create_app(db_path, config_path)
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="spa")
    return app


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn

    root = tmp_path_factory.mktemp("offline")
    db_path = root / "offline.db"
    assert CliRunner().invoke(
        __import__("driverdna.cli", fromlist=["app"]).app,
        ["import", str(FIXTURES_DIR), "--db", str(db_path)],
    ).exit_code == 0

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
            if httpx.get(f"{base}/api/cohorts", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.1)
    yield base
    uv.should_exit = True
    thread.join(timeout=5)


def test_app_loads_and_operates_with_non_localhost_network_blocked(server):
    base = server
    slug = "gr86-spa-francorchamps"
    finding_id = httpx.get(
        f"{base}/api/cohorts/{slug}/payload", timeout=10
    ).json()["findings"][0]["finding_id"]

    routes = [
        "/#/",
        f"/#/cohort/{slug}",
        f"/#/corner/{slug}/C01",
        f"/#/finding/{slug}/{quote(finding_id, safe='')}",
        f"/#/laps/{slug}",
        "/#/config",
        "/#/chat",
    ]

    blocked: list[str] = []

    def guard(route):
        host = urlparse(route.request.url).hostname
        if host not in ("127.0.0.1", "localhost"):
            blocked.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        # Route interception, not a mere assertion after the fact: a
        # non-local request would be actively aborted here, the way it
        # would be on a real offline machine, not just detected in hindsight.
        page.route("**/*", guard)

        for route in routes:
            page.goto(f"{base}{route}", wait_until="networkidle")
            # "Operates," not just "loads": each route renders its
            # identifying content, not a blank page or a stuck spinner.
            assert page.locator("body").inner_text().strip() != ""
            assert "Loading" not in page.title()

        # The signature interactive surfaces specifically:
        page.goto(f"{base}/#/cohort/{slug}", wait_until="networkidle")
        page.wait_for_selector("svg.trackmap", timeout=5000)  # the GPS track outline

        page.goto(f"{base}/#/config", wait_until="networkidle")
        page.wait_for_selector(".cfg", timeout=5000)  # config keys actually rendered

        browser.close()

    assert blocked == [], f"non-localhost requests were attempted: {blocked}"
