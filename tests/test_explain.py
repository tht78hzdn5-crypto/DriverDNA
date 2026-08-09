"""GET /api/explain (methodology disclosure, SPEC.md A35): the endpoint is a
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
# Both ways a view can name a methodology id. The hook form was invisible to
# this guard until 2026-08-09 (BUG-021): `<Methodology id="...">` was matched
# but `useMethodologyText("...")` was not, so ids reached only through the
# hook — the four in SourceLegend, and the incident mechanism/empathy ones —
# could be typo'd and would render as nothing with every test still green.
# Template-literal calls (`incident.${...}`) are deliberately not matched:
# their id isn't a literal, so it can't be checked statically. They are
# covered instead by test_every_incident_classification_has_methodology_text.
_METHODOLOGY_ID = re.compile(
    r'<Methodology\s+id="([^"]+)"'
    r"|useMethodologyText\(\s*\"([^\"$]+)\"\s*\)"
)


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
            referenced.add(match.group(1) or match.group(2))

    assert referenced, "expected at least one methodology id reference in ui/src"
    # Both reference forms must actually be reachable by the regex, or this
    # guard silently narrows again the next time a view switches form.
    assert "finding.grouping" in referenced, (
        "the useMethodologyText(\"...\") form is not being matched — this test "
        "has stopped covering hook-referenced ids (BUG-021)"
    )
    unknown = referenced - set(METHODOLOGY)
    assert not unknown, (
        f"JSX references methodology id(s) not in explain.py's METHODOLOGY: {unknown}"
    )


def _real_classifications() -> set[str]:
    """Every classification `classify_incident` can actually emit, read out of
    the engine's own source rather than re-listed here — a re-listed set drifts
    the moment a mechanism is added, which is the drift this file exists to
    catch."""
    source = (
        Path(__file__).parent.parent
        / "src" / "driverdna" / "incidents" / "classify.py"
    ).read_text()
    found = set(re.findall(r'classification(?:,\s*\w+)*\s*=\s*"([a-z_]+)"', source))
    found |= set(re.findall(r'classification="([a-z_]+)"', source))
    return {c for c in found if c != "classification"}


def test_every_incident_classification_has_methodology_text():
    """IncidentCard builds its ids as template literals (`incident.${cls}`), so
    the static reference check above structurally cannot see them. This is the
    cover for that blind spot: every mechanism the engine can emit must have a
    mechanism explanation, or the card renders a classification with no text
    and nothing fails (BUG-021)."""
    classifications = _real_classifications()
    assert classifications, "sanity: no classifications extracted from classify.py"
    missing = {c for c in classifications if f"incident.{c}" not in METHODOLOGY}
    assert not missing, f"classifications with no incident.<cls> methodology: {missing}"


def test_incident_empathy_text_exists_for_named_mechanisms_only():
    """The empathy line is deliberately withheld where the engine named no
    cause: a generic reassurance about a lap it couldn't read would be the
    guessing the constitution forbids (explain.py's own note). Pinned so the
    absence stays a decision rather than looking like an oversight."""
    from driverdna.incidents.coaching import eligible_principle_for

    for cls in _real_classifications():
        has_empathy = f"incident.empathy.{cls}" in METHODOLOGY
        named = eligible_principle_for(cls) is not None
        assert has_empathy == named, (
            f"{cls}: empathy text present={has_empathy} but engine names a "
            f"cause={named} — these must agree"
        )
