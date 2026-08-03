"""Browser-driven check for the populated score-history chart (SPEC.md A36).

The shared `tests/fixtures/` DB is deliberately undated (per its own
manifest comment and UI-SPEC's "Design language v2" precedent for the
reference-lap figures), so the render-parity/offline gates only ever
exercise the chart's *unavailable* empty state. This test builds its own
throwaway dated DB — never editing `tests/fixtures/` — to prove the
populated line-chart path actually renders in a real browser: SVG lines
appear, toggling a chip removes its line, and every number rendered traces
to the payload (same discipline as test_render_parity.py, scoped to this
one route). Skipped automatically when Playwright/Chromium or the built SPA
is absent.
"""

from __future__ import annotations

import re
import socket
import threading
from pathlib import Path

import httpx
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from driverdna.coach.grounding import number_pool
from driverdna.db import Database

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"
TESTS_DIR = Path(__file__).parent
import sys  # noqa: E402

sys.path.insert(0, str(TESTS_DIR))
from synth import one_corner_lap, ramp, run_synthetic_lap  # noqa: E402


def _find_chrome() -> Path | None:
    hits = sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))
    return hits[-1] if hits else None


CHROME = _find_chrome()

pytestmark = pytest.mark.skipif(
    CHROME is None or not (STATIC / "index.html").exists(),
    reason="Chromium binary or built SPA not present",
)

# 25 dated laps -- matches the default gate (history_buckets=6 x
# trend_min_laps_per_bucket=4 = 24) and mirrors the owner's real synced
# history (also 25 dated laps, CLAUDE.md "Dated manual import" status note).
_PEAKS = [0.1, 0.3, 0.5, 0.7, 0.9] * 5


def _brake_peak_lap(i, peak):
    lap = one_corner_lap()
    lap.source_path = lap.source_path.with_name(f"uibp{i}.csv")
    lap.vert_accel[:] = 9.8 + i * 1e-6
    lap.brake[:] = 0.0
    ramp(lap.brake, 600, 630, 0.0, peak)
    lap.brake[630:690] = peak
    ramp(lap.brake, 690, 720, peak, 0.0)
    return lap


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path):
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    from driverdna.config import DriverDNAConfig
    from driverdna.ui.api import create_app

    db_path = tmp_path / "history.db"
    config = DriverDNAConfig()
    with Database.open(db_path) as db:
        for i, peak in enumerate(_PEAKS):
            run_synthetic_lap(
                db, _brake_peak_lap(i, peak),
                driver="owner", car="TestCar", track="SynthRing",
                session_key=f"s{i % 2}", lap_date=f"2026-01-{i + 1:02d}",
                config=config,
            )

    app = create_app(db_path, tmp_path / "config.toml")
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="spa")

    port = _free_port()
    uv_config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv = uvicorn.Server(uv_config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/api/driver/score-history", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            threading.Event().wait(0.1)
    yield base
    uv.should_exit = True
    thread.join(timeout=5)


_DECIMAL = re.compile(r"[-+]?\d+\.\d+")


def test_populated_score_history_chart_renders_lines_and_traces_to_payload(server):
    base = server
    history = httpx.get(f"{base}/api/driver/score-history", timeout=10).json()
    assert history["x_axis"]["kind"] == "date_bucket"
    # #/model also renders /api/driver's own (non-bucketed) beliefs on the
    # same page — its numbers must be in the pool too, or they'd falsely
    # trip the check below as "invented".
    pool = number_pool(history)
    number_pool(httpx.get(f"{base}/api/driver", timeout=10).json(), pool)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"{base}/#/model", wait_until="networkidle")
        page.wait_for_selector(".history-chart", timeout=8000)

        lines_before = page.locator(".history-line").count()
        assert lines_before > 0, "expected at least one rendered score-history line"

        # Toggle the first chip off — its line(s) must disappear, proving the
        # multi-select toggle actually drives what's drawn, not just its label.
        first_chip = page.locator(".history-legend .chip.toggle").first
        first_chip.click()
        page.wait_for_timeout(150)
        lines_after = page.locator(".history-line").count()
        assert lines_after < lines_before

        texts = page.eval_on_selector_all(".num", "els => els.map(e => e.textContent)")
        violations = []
        for text in texts:
            for match in _DECIMAL.finditer(text or ""):
                value = float(match.group(0))
                tol = 0.5 * 10 ** (-len(match.group(0).split(".")[1])) + 1e-9
                if not any(abs(value - p_val) <= tol for p_val in pool):
                    violations.append(f"'{text.strip()}' -> {value}")
        assert not violations, f"figures with no matching payload number: {violations}"
        assert not errors, f"JS error(s) rendering the populated chart: {errors}"
        browser.close()
