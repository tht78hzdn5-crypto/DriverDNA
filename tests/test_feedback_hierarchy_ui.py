"""Browser-driven checks for the fundamental landmark header (SPEC.md A48).

A46 grouped the cohort page's feedback by racing fundamental; A48 makes the
fundamental *read* as a section landmark and turns the group into a coaching
block with the measurements one click below it. Three things have to be true
on a real page, and none of them is provable by reading JSX:

1. The coaching sentence for a fundamental precedes its first finding row in
   DOM order — that is the whole point of promoting the lede.
2. The `priority` chip lands on exactly the fundamental that owns the page
   headline, and that principle is not restated a second time in the same
   group (the duplication A46 exists to prevent).
3. The findings are collapsed, never dropped: every row is still in the DOM
   with its own `.src-tag`, inside a closed `<details>`. This is the binding
   half of UI-SPEC decision 6 — grouping and disclosure are presentation, the
   source tag on each row is not.

Skipped automatically when Playwright/Chromium or the built SPA is absent.
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

    root = tmp_path_factory.mktemp("feedback-hierarchy")
    db_path = root / "feedback.db"
    assert CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    ).exit_code == 0

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
    yield base
    uv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def payload(server):
    return httpx.get(f"{server}/api/cohorts/{SLUG}/payload", timeout=10).json()


def _cohort_page(browser, base):
    page = browser.new_page()
    page.goto(f"{base}/#/cohort/{SLUG}", wait_until="networkidle")
    page.wait_for_selector(".fgroup", timeout=8000)
    return page


def test_coaching_sentence_precedes_the_first_finding_in_every_group(server, payload):
    """The racing takeaway is the first thing read under a fundamental."""
    headline = payload["coaching"]["headline"]
    assert headline, "fixture precondition: the cohort has a coaching headline"

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _cohort_page(browser, server)

        groups = page.locator(".panel .fgroup")
        assert groups.count() >= 3, "expected several fundamental groups on the fixture"

        checked = 0
        for i in range(groups.count()):
            group = groups.nth(i)
            if group.locator(".fgroup-lede .coach-say").count() == 0:
                continue  # a fundamental with no eligible principle invents no sentence
            # `.coach-say` before `.finding` in document order, in this group.
            order = group.evaluate(
                """el => [...el.querySelectorAll('.coach-say, .finding')]
                          .map(n => n.classList.contains('coach-say') ? 'say' : 'finding')"""
            )
            assert order, "group has neither a sentence nor a finding"
            assert order[0] == "say", (
                f"group {i}: a measurement row is read before the coaching "
                f"sentence — order was {order[:4]}"
            )
            checked += 1

        assert checked >= 2, "expected at least two coached fundamentals in the fixture"
        browser.close()


def test_priority_chip_marks_only_the_headline_fundamental_and_is_said_once(server, payload):
    headline = payload["coaching"]["headline"]
    expression = headline["coaching_expression"]

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _cohort_page(browser, server)

        chips = page.locator(".fgroup-head .chip-priority")
        assert chips.count() == 1, (
            f"exactly one fundamental owns the headline; found {chips.count()} chips"
        )

        # The chipped group is the headline's fundamental, and it leads with the
        # headline's own sentence.
        chipped = page.locator(".fgroup", has=page.locator(".chip-priority")).first
        assert chipped.locator(".fgroup-lede .coach-say").inner_text().strip() == expression

        # Said once: the headline principle's expression must not be repeated
        # lower down in the same group (A46's two-voices problem, one level in).
        repeats = chipped.locator(".coach-say", has_text=expression).count()
        assert repeats == 1, f"headline sentence rendered {repeats} times in its group"
        browser.close()


def test_findings_are_collapsed_not_dropped_and_keep_their_source_tags(server, payload):
    """Owner-directed: the vs-self / vs-principle / vs-reference rows stop
    leading the section. They stay in the DOM, tagged, inside a closed
    disclosure — the crawler reads inside closed <details>, so this is a
    presentation change, not a loss of evidence."""
    shown = [f for f in payload["findings"] if f["shown"]]
    assert shown, "fixture precondition: some findings clear the gates"

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _cohort_page(browser, server)

        # Every shown finding still renders, and every rendered row is tagged.
        rows = page.locator(".panel .fgroup .finding")
        assert rows.count() >= len(shown)
        tagged = page.locator(".panel .fgroup .finding .src-tag").count()
        assert tagged == rows.count(), (
            f"{rows.count() - tagged} finding row(s) render without a source tag"
        )

        # In a coached group the rows sit inside a disclosure that starts closed.
        coached = page.locator(".fgroup", has=page.locator(".fgroup-lede")).first
        wrapper = coached.locator("details.fgroup-findings")
        assert wrapper.count() == 1, "coached group must wrap its findings in one disclosure"
        assert wrapper.first.evaluate("el => el.open") is False, (
            "the measurements disclosure must start closed"
        )
        assert coached.locator("details.fgroup-findings .finding").count() > 0

        # …and opening it reveals them, so nothing is unreachable. Direct
        # child only: each finding row carries its own nested <summary>.
        wrapper.first.locator(":scope > summary").click()
        page.wait_for_timeout(120)
        assert wrapper.first.locator(".finding").first.is_visible()
        browser.close()


def test_every_group_header_carries_the_shared_tier_mark(server, payload):
    """The Driver Model tie: one glyph, the pyramid in miniature, on both
    surfaces. Position in the fixed seven — never a score."""
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = _cohort_page(browser, server)
        groups = page.locator(".panel .fgroup")
        marks = page.locator(".panel .fgroup .fgroup-head .tiermark")
        assert marks.count() == groups.count()

        # The same glyph appears on #/model's meters, from the same component.
        page.goto(f"{server}/#/model", wait_until="networkidle")
        page.wait_for_selector(".fbar", timeout=8000)
        assert page.locator(".fbar .tiermark").count() == page.locator(".fbar").count()
        browser.close()
