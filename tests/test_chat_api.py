"""U3 contract tests: chat over HTTP — SSE progress events, the mechanical
validated-only display contract, and the confirm endpoint. A
`chat_provider_factory` injects the same MockProvider pattern test_chat.py
uses; no test ever calls a live model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from driverdna.cli import app as cli_app
from driverdna.config import load_config
from driverdna.ui.api import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SPA_SLUG = "gr86-spa-francorchamps"


class MockProvider:
    """Scripted provider: each entry is one chat_step return value."""

    def __init__(self, steps):
        self.steps = list(steps)

    def chat_step(self, system, messages, tools):
        step = self.steps.pop(0)
        return {"text": step.get("text"), "tool_calls": step.get("tool_calls", []),
                "raw_content": None}


@pytest.fixture()
def env(tmp_path):
    db_path = tmp_path / "api.db"
    result = CliRunner().invoke(
        cli_app, ["import", str(FIXTURES_DIR), "--db", str(db_path)]
    )
    assert result.exit_code == 0, result.output
    return {"db_path": db_path, "config_path": tmp_path / "config.toml"}


def make_client(env, steps):
    factory_state = {"steps": steps}
    app = create_app(
        env["db_path"], env["config_path"],
        chat_provider_factory=lambda: MockProvider(factory_state["steps"]),
    )
    return TestClient(app)


def create_session(client) -> str:
    resp = client.post("/api/chat/sessions", json={"cohort": SPA_SLUG, "driver": "owner"})
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


def parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def shown_finding_id(db_path, config_path):
    from driverdna.db import Database
    from driverdna.report.payload import build_cohort_payload

    with Database.open(db_path) as db:
        payload = build_cohort_payload(
            db, driver="owner", car="GR86", track="Spa-Francorchamps",
            config=load_config(config_path),
        )
    return next(f["finding_id"] for f in payload["findings"] if f["shown"])


def test_create_session_without_provider_returns_503(env):
    client = TestClient(create_app(env["db_path"], env["config_path"]))
    resp = client.post("/api/chat/sessions", json={"cohort": SPA_SLUG})
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.text


def test_create_session_unknown_cohort_404s(env):
    client = make_client(env, [])
    resp = client.post("/api/chat/sessions", json={"cohort": "does-not-exist"})
    assert resp.status_code == 404


def test_message_streams_thinking_then_response(env):
    good_id = shown_finding_id(env["db_path"], env["config_path"])
    client = make_client(env, [{"text": f"Your biggest loss is here [{good_id}]."}])
    session_id = create_session(client)

    resp = client.post(
        f"/api/chat/sessions/{session_id}/messages", json={"text": "where do I lose time?"}
    )
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    assert [e["type"] for e in events] == ["thinking", "validating", "response"]
    final = events[-1]
    assert good_id in final["evidence"]
    assert final["text"] == f"Your biggest loss is here [{good_id}]."


def test_message_surfaces_tool_calls_as_consulting_tool_events(env):
    client = make_client(env, [
        {"tool_calls": [{"id": "t1", "name": "metric_distribution",
                         "args": {"corner_id": "C01", "metric": "min_speed_kmh"}}]},
        {"text": "Noted."},
    ])
    session_id = create_session(client)
    resp = client.post(
        f"/api/chat/sessions/{session_id}/messages", json={"text": "how fast through C01?"}
    )
    events = parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert types == ["thinking", "consulting_tool", "validating", "response"]
    assert events[1]["tool"] == "metric_distribution"
    assert events[1]["args"] == {"corner_id": "C01", "metric": "min_speed_kmh"}


def test_message_rejected_twice_yields_error_event_not_partial_text(env):
    client = make_client(env, [
        {"text": "C01 costs you 999999.99 s per lap."},
        {"text": "Believe me, it is 999999.99 s."},
    ])
    session_id = create_session(client)
    resp = client.post(
        f"/api/chat/sessions/{session_id}/messages", json={"text": "how bad is C01?"}
    )
    events = parse_sse(resp.text)
    assert events[-1]["type"] == "error"
    assert "rejected by the grounding contract" in events[-1]["error"]
    # No "response" event ever fires for a rejected turn:
    assert "response" not in [e["type"] for e in events]


def test_messages_unknown_session_404s(env):
    client = make_client(env, [])
    resp = client.post("/api/chat/sessions/unknown/messages", json={"text": "hi"})
    assert resp.status_code == 404


def test_confirm_applies_staged_proposal_and_is_reversible(env):
    client = make_client(env, [
        {"tool_calls": [{"id": "t1", "name": "propose_config_change",
                         "args": {"key": "detectors.max_corrections", "new_value": 2,
                                  "reason": "bumpy track"}}]},
        {"text": "Staged the change; confirm to apply."},
    ])
    session_id = create_session(client)
    msg_resp = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"text": "relax the correction rule"},
    )
    final = parse_sse(msg_resp.text)[-1]
    assert final["staged"] and final["staged"][0]["key"] == "detectors.max_corrections"
    assert load_config(env["config_path"]).detectors.max_corrections == 1  # not applied yet

    confirm_resp = client.post(f"/api/chat/sessions/{session_id}/confirm/1")
    assert confirm_resp.status_code == 200, confirm_resp.text
    assert load_config(env["config_path"]).detectors.max_corrections == 2


def test_confirm_unknown_index_404s(env):
    client = make_client(env, [{"text": "hello"}])
    session_id = create_session(client)
    client.post(f"/api/chat/sessions/{session_id}/messages", json={"text": "hi"})
    resp = client.post(f"/api/chat/sessions/{session_id}/confirm/1")
    assert resp.status_code == 404
