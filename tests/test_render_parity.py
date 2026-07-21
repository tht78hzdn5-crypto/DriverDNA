"""U1 trust gate 1: render-parity crawler (docs/UI-SPEC.md).

Launches the real built SPA in Chromium against a fixture DB and asserts that
every fractional measurement rendered in a data (`.num`) element traces to a
number the API actually served. This is the mechanical form of the binding
UI rule: the UI renders what the engine computed and never computes a
measurement.

Scope — fractional figures only: seconds, km/h, percentages, spreads, ranks,
repeatabilities, lap times (m:ss.mmm), signed deltas. Bare integer counts
(finding tallies, sample sizes n, corner numbers) are structural and
UI-derivable by design — the spec explicitly permits counting — so they are
out of this gate's scope. Client-side derivation of a *measurement* is always
fractional in this product (e.g. summing per-phase losses), so this is the
failure mode the gate catches.

Skipped automatically when Playwright/Chromium or the built SPA is absent, so
the core suite stays browser-free.
"""

from __future__ import annotations

import re
import socket
import threading
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from typer.testing import CliRunner

from driverdna.coach.grounding import number_pool

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _find_chrome() -> Path | None:
    # The environment preinstalls Chromium under a versioned dir; glob rather
    # than pin a build so an env update doesn't silently skip the gate.
    hits = sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))
    return hits[-1] if hits else None


CHROME = _find_chrome()

pytestmark = pytest.mark.skipif(
    CHROME is None or not (STATIC / "index.html").exists(),
    reason="Chromium binary or built SPA not present",
)

# A time m:ss.mmm, a percent, or a signed/plain decimal. Bare integers omitted.
_TIME = re.compile(r"[-+]?(\d+):(\d{2})\.(\d+)")
_DECIMAL = re.compile(r"[-+]?\d+\.\d+%?")


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


def _tokens(text: str) -> list[tuple[float, int]]:
    """Fractional (value, decimals) tokens in one rendered string."""
    out: list[tuple[float, int]] = []
    consumed = text
    for m in _TIME.finditer(text):
        minutes, secs, frac = m.groups()
        out.append((int(minutes) * 60 + int(secs) + float(f"0.{frac}"), len(frac)))
        consumed = consumed.replace(m.group(0), " ")
    for m in _DECIMAL.finditer(consumed):
        raw = m.group(0).rstrip("%")
        decimals = len(raw.split(".")[1])
        out.append((float(raw), decimals))
    return out


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn

    root = tmp_path_factory.mktemp("parity")
    db_path = root / "parity.db"
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


def _number_pool(base: str, slug: str) -> set[float]:
    """Every number the API serves for the crawled views."""
    pool: set[float] = set()
    get = lambda path: httpx.get(f"{base}{path}", timeout=10).json()
    number_pool(get("/api/driver"), pool)
    number_pool(get("/api/config"), pool)
    for cohort in get("/api/cohorts"):
        s = cohort["slug"]
        number_pool(get(f"/api/cohorts/{s}/payload"), pool)
        number_pool(get(f"/api/cohorts/{s}/corners"), pool)
        number_pool(get(f"/api/laps?cohort={s}"), pool)
    # Corner drill defaults to this metric and renders its live distribution.
    number_pool(get(f"/api/metrics/C01/min_speed_kmh/distribution?cohort={slug}"), pool)
    return pool


def test_every_fractional_figure_traces_to_the_payload(server):
    base = server
    slug = "gr86-spa-francorchamps"
    pool = _number_pool(base, slug)
    payload = httpx.get(f"{base}/api/cohorts/{slug}/payload", timeout=10).json()
    finding_id = payload["findings"][0]["finding_id"]

    routes = [
        "/#/",
        f"/#/cohort/{slug}",
        f"/#/corner/{slug}/C01",
        f"/#/finding/{slug}/{quote(finding_id, safe='')}",
        f"/#/laps/{slug}",
        "/#/config",  # U2: config values must trace to /api/config too
        "/#/model",  # M6 Driver Model view: scores/confidence/trend from the payload
    ]

    violations: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME))
        page = browser.new_page()
        for route in routes:
            page.goto("about:blank")
            page.goto(f"{base}{route}", wait_until="networkidle")
            page.wait_for_selector(".num", timeout=8000)
            page.wait_for_timeout(300)  # settle any second async fetch
            texts = page.eval_on_selector_all(
                ".num", "els => els.map(e => e.textContent)"
            )
            for text in texts:
                for value, decimals in _tokens(text or ""):
                    tol = 0.5 * 10 ** (-decimals) + 1e-9
                    if not any(abs(value - p_val) <= tol for p_val in pool):
                        violations.append(f"{route}: '{text.strip()}' → {value}")
        browser.close()

    assert not violations, (
        "on-screen figures with no matching payload number (the UI must never "
        "compute a measurement):\n" + "\n".join(sorted(set(violations)))
    )


def test_crawler_would_catch_an_invented_number(server):
    """Guard the guard: a fabricated fractional figure must be rejected by the
    same matcher, so a green parity test means something."""
    pool = _number_pool(server, "gr86-spa-francorchamps")
    # A plausible-looking but absent measurement.
    invented = 3.1415
    tol = 0.5 * 10 ** (-4) + 1e-9
    assert not any(abs(invented - p_val) <= tol for p_val in pool)
