"""Browser-driven checks for the sign-in gate (docs/DEPLOY-SPEC.md track H1).

`test_auth_api.py` proves the server refuses; this proves the browser half —
that a locked cockpit shows a sign-in instead of a wall of failed panels, that
the right passphrase gets in, and that signing out actually ends the session.

Same convention as `test_cockpit_ui.py`/`test_upload_ui.py`: skipped
automatically when Playwright, Chromium, or the built SPA is absent.
"""

from __future__ import annotations

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
TOKEN = "a-long-random-passphrase-for-one-driver"


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
def locked_server(tmp_path):
    """A real server over a real imported cohort, with a passphrase set."""
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    from driverdna.cli import app as cli_app
    from driverdna.ui.api import create_app

    db_path = tmp_path / "auth.db"
    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output

    app = create_app(db_path, tmp_path / "config.toml", access_token=TOKEN)
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="spa")

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/api/auth/status", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.1)
    yield base
    uv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def open_server(tmp_path):
    """The same server with no passphrase configured — the local loopback
    instrument, unchanged by any of this."""
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    from driverdna.cli import app as cli_app
    from driverdna.ui.api import create_app

    db_path = tmp_path / "open.db"
    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    )
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
            if httpx.get(f"{base}/api/auth/status", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.1)
    yield base
    uv.should_exit = True
    thread.join(timeout=5)


def _page(browser, base):
    page = browser.new_page()
    page.goto(f"{base}/#/", wait_until="networkidle")
    return page


def test_an_unconfigured_cockpit_shows_no_gate_at_all(open_server):
    """Guards the guard, the same way test_render_parity checks that its own
    crawler would catch an invented number: if this passed *and* the locked
    tests passed, the gate tests would be proving nothing about auth."""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _page(browser, open_server)
        page.wait_for_selector("nav .tab", timeout=8000)
        assert page.locator("input[type=password]").count() == 0
        assert "Sign in" not in page.locator("body").inner_text()
        # No sign-out either: there is no session to end.
        assert page.locator("button:has-text('Sign out')").count() == 0
        browser.close()


def test_a_locked_cockpit_shows_a_sign_in_not_an_error(locked_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _page(browser, locked_server)
        page.wait_for_selector("input[type=password]", timeout=8000)

        text = page.locator("body").inner_text()
        assert "Sign in" in text
        # The failure mode this replaces: every panel fetching, 401ing, and
        # rendering its own error. None of that may be on screen.
        assert "401" not in text
        assert "not authenticated" not in text
        # And the shell is not drawn behind the gate — no tabs to click at.
        assert page.locator("nav .tab").count() == 0
        browser.close()


def test_the_right_passphrase_opens_the_cockpit(locked_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _page(browser, locked_server)
        page.fill("input[type=password]", TOKEN)
        page.click("button:has-text('Enter')")

        # The real shell, over real data: the six-tab bar and driver home.
        page.wait_for_selector("nav .tab", timeout=8000)
        assert page.locator("input[type=password]").count() == 0
        page.wait_for_selector(".num", timeout=8000)
        browser.close()


def test_a_wrong_passphrase_says_so_and_stays_locked(locked_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _page(browser, locked_server)
        page.fill("input[type=password]", "hunter2")
        page.click("button:has-text('Enter')")

        page.wait_for_selector(".error", timeout=8000)
        assert "incorrect passphrase" in page.locator(".error").inner_text()
        assert page.locator("input[type=password]").count() == 1
        assert page.locator("nav .tab").count() == 0
        browser.close()


def test_signing_out_returns_to_the_gate(locked_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _page(browser, locked_server)
        page.fill("input[type=password]", TOKEN)
        page.click("button:has-text('Enter')")
        page.wait_for_selector("nav .tab", timeout=8000)

        page.click("button:has-text('Sign out')")
        page.wait_for_selector("input[type=password]", timeout=8000)
        # And a reload does not quietly let us back in.
        page.reload(wait_until="networkidle")
        page.wait_for_selector("input[type=password]", timeout=8000)
        browser.close()


def test_the_passphrase_is_not_readable_from_javascript(locked_server):
    """The session is an HttpOnly cookie, and the passphrase is never put
    anywhere the page can read it back — no localStorage, no sessionStorage,
    no non-HttpOnly cookie."""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _page(browser, locked_server)
        page.fill("input[type=password]", TOKEN)
        page.click("button:has-text('Enter')")
        page.wait_for_selector("nav .tab", timeout=8000)

        assert page.evaluate("document.cookie") == ""
        assert page.evaluate("JSON.stringify(window.localStorage)") == "{}"
        assert page.evaluate("JSON.stringify(window.sessionStorage)") == "{}"
        browser.close()


def test_the_gate_makes_no_third_party_requests(locked_server):
    """UI-SPEC trust gate 5a, extended to the one screen `test_offline.py`
    cannot reach: it crawls the authenticated routes, so without this the
    sign-in page would be the only view never checked for external calls."""
    blocked: list[str] = []
    from urllib.parse import urlparse

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()

        def guard(route):
            host = urlparse(route.request.url).hostname
            if host not in ("127.0.0.1", "localhost"):
                blocked.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        page.route("**/*", guard)
        page.goto(f"{locked_server}/#/", wait_until="networkidle")
        page.wait_for_selector("input[type=password]", timeout=8000)
        page.fill("input[type=password]", "hunter2")
        page.click("button:has-text('Enter')")
        page.wait_for_selector(".error", timeout=8000)
        browser.close()

    assert blocked == []
