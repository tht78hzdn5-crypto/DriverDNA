"""U1 packaging checks: built SPA present, self-contained, served.

The render-parity crawler (UI-SPEC trust gate 1: every on-screen number
exists in the payload or a read endpoint) requires a browser and lands as
the next UI task — tracked, not forgotten. These tests hold the offline and
serving constraints meanwhile.
"""

import json
import re
from pathlib import Path

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"
TOKENS = Path(__file__).parents[1] / "ui" / "tokens.json"


def test_built_spa_is_present():
    assert (STATIC / "index.html").exists(), "run `npm run build` in ui/"
    assert list((STATIC / "assets").glob("index-*.js"))


def test_index_references_only_local_assets():
    html = (STATIC / "index.html").read_text()
    for attr in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert not attr.startswith(("http://", "https://", "//")), attr


def test_bundle_makes_no_external_requests():
    bundle = next((STATIC / "assets").glob("index-*.js")).read_text()
    # fetch() targets in our code are /api/... only; no absolute URLs.
    assert "https://" not in bundle.replace(
        "https://reactjs.org", ""  # React dev-warning URL strings are inert text
    ).replace("https://react.dev", "")


def test_css_has_no_external_imports():
    css = next((STATIC / "assets").glob("index-*.css")).read_text()
    assert "@import" not in css and "url(http" not in css


# --- U7 mobile/PWA (docs/UI-V3-PLAN.md Track A5) ----------------------------


def test_theme_color_matches_tokens_json():
    """index.html's static <meta name="theme-color"> can't be sourced from
    tokens.json at parse time (the browser reads it before any JS runs) —
    main.jsx re-asserts the real value at runtime as defense in depth, but
    this catches the static HTML itself drifting from the single source of
    truth, the same discipline report/builder.py's _TOKENS mirror gets."""
    html = (STATIC / "index.html").read_text()
    match = re.search(r'<meta name="theme-color" content="([^"]+)"', html)
    assert match, "index.html is missing its theme-color meta tag"
    tokens = json.loads(TOKENS.read_text())
    assert match.group(1) == tokens["color"]["base"]


def test_manifest_and_service_worker_are_present_and_local():
    manifest_path = STATIC / "manifest.webmanifest"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["display"] == "standalone"
    tokens = json.loads(TOKENS.read_text())
    assert manifest["theme_color"] == tokens["color"]["base"]
    assert manifest["icons"], "manifest has no icons — nothing installable"
    for icon in manifest["icons"]:
        assert icon["src"].startswith("/"), f"non-local icon src: {icon['src']}"
        assert (STATIC / icon["src"].lstrip("/")).exists()

    assert (STATIC / "sw.js").exists()
    sw = (STATIC / "sw.js").read_text()
    # The one binding rule (DEPLOY-SPEC Track M item 4): /api/* must never
    # be servable from this worker's cache.
    assert '"/api/"' in sw or "'/api/'" in sw


def test_index_references_manifest_and_icons():
    html = (STATIC / "index.html").read_text()
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert "apple-touch-icon" in html
