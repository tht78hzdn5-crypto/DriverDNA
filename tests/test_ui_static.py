"""U1 packaging checks: built SPA present, self-contained, served.

The render-parity crawler (UI-SPEC trust gate 1: every on-screen number
exists in the payload or a read endpoint) requires a browser and lands as
the next UI task — tracked, not forgotten. These tests hold the offline and
serving constraints meanwhile.
"""

import re
from pathlib import Path

STATIC = Path(__file__).parents[1] / "src" / "driverdna" / "ui" / "static"


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
