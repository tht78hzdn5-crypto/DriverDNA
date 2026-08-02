"""GET /api/explain (methodology disclosure, SPEC.md A33): the endpoint is a
pass-through of driverdna.explain.METHODOLOGY, and every id a JSX view
actually references must exist in that dict — a typo'd id must fail here,
at test time, not render silently as nothing in the browser."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from driverdna.explain import METHODOLOGY
from driverdna.ui.api import create_app

UI_SRC = Path(__file__).parent.parent / "ui" / "src"
_METHODOLOGY_ID = re.compile(r'<Methodology\s+id="([^"]+)"')


def test_explain_endpoint_matches_methodology_dict(tmp_path):
    client = TestClient(create_app(tmp_path / "nonexistent.db", tmp_path / "config.toml"))
    response = client.get("/api/explain")
    assert response.status_code == 200
    assert response.json() == dict(sorted(METHODOLOGY.items()))


def test_methodology_dict_has_no_empty_entries():
    assert METHODOLOGY, "explain.py's METHODOLOGY dict must not be empty"
    for key, text in METHODOLOGY.items():
        assert "." in key, f"{key!r} should be namespaced like 'category.name'"
        assert text.strip(), f"{key!r} has empty/whitespace-only text"


def test_every_jsx_methodology_id_reference_exists():
    referenced: set[str] = set()
    for path in UI_SRC.rglob("*.jsx"):
        text = path.read_text()
        for match in _METHODOLOGY_ID.finditer(text):
            referenced.add(match.group(1))

    assert referenced, "expected at least one <Methodology id=...> reference in ui/src"
    unknown = referenced - set(METHODOLOGY)
    assert not unknown, (
        f"JSX references methodology id(s) not in explain.py's METHODOLOGY: {unknown}"
    )
