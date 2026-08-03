"""DEPLOY-SPEC Track P: GeminiCoachProvider, mirroring GeminiChatProvider's
test discipline — real google.genai.types objects, network boundary mocked.
Skipped when google-genai isn't installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("google.genai")

from google.genai import types  # noqa: E402

from driverdna.coach.provider import GeminiCoachProvider  # noqa: E402


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    return GeminiCoachProvider("gemini-3.5-flash", max_tokens=1234)


def test_complete_returns_response_text(provider, monkeypatch):
    captured = {}

    def fake_generate(**kw):
        captured.update(kw)
        return types.GenerateContentResponse(
            candidates=[types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text='{"ok": true}')])
            )]
        )

    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate)
    result = provider.complete("system prompt", "user content")
    assert result == '{"ok": true}'
    assert captured["model"] == "gemini-3.5-flash"
    assert captured["contents"] == "user content"
    assert captured["config"].system_instruction == "system prompt"
    assert captured["config"].max_output_tokens == 1234


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiCoachProvider("gemini-3.5-flash")
