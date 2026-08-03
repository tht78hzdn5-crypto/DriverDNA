"""DEPLOY-SPEC Track P item 3: GeminiChatProvider's Anthropic<->Gemini
transcript translation, both directions, against REAL google.genai.types
objects (not hand-rolled mocks) — only the network boundary
(`client.models.generate_content`) is mocked, so this exercises the SDK's
own pydantic validation of everything this provider constructs. Skipped
when google-genai isn't installed, same as test_gemini_tool_translation.py.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("google.genai")

from google.genai import types  # noqa: E402

from driverdna.chat.gemini_tools import translate_tools  # noqa: E402
from driverdna.chat.session import GeminiChatProvider, _gemini_contents_from_messages  # noqa: E402
from driverdna.chat.tools import TOOL_DEFS  # noqa: E402


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-tests")
    return GeminiChatProvider("gemini-3.5-flash")


def _text_response(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(
            content=types.Content(role="model", parts=[types.Part(text=text)])
        )]
    )


def _function_call_response(calls: list[tuple[str, str, dict]]) -> types.GenerateContentResponse:
    """calls: list of (call_id, name, args)."""
    parts = [
        types.Part(function_call=types.FunctionCall(id=cid, name=name, args=args))
        for cid, name, args in calls
    ]
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))]
    )


def _empty_response() -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[]))]
    )


# --- message translation (in) -----------------------------------------------


def test_plain_string_turns_translate_to_user_and_model_roles():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    contents = _gemini_contents_from_messages(messages)
    assert [c.role for c in contents] == ["user", "model"]
    assert contents[0].parts[0].text == "hello"
    assert contents[1].parts[0].text == "hi there"


def test_own_raw_content_echoes_back_as_is():
    stored = types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(id="c1", name="lookup_finding", args={}))],
    )
    messages = [{"role": "assistant", "content": stored}]
    contents = _gemini_contents_from_messages(messages)
    assert contents == [stored]


def test_tool_result_round_trip_recovers_function_name():
    """Anthropic's tool_result block only carries tool_use_id, not the
    function name — GeminiChatProvider must recover it from the earlier
    function_call part in the same transcript."""
    prior_call = types.Content(
        role="model",
        parts=[types.Part(function_call=types.FunctionCall(
            id="call-42", name="metric_distribution", args={"corner_id": "C01"},
        ))],
    )
    messages = [
        {"role": "assistant", "content": prior_call},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call-42",
             "content": json.dumps({"n": 8, "median": 1.23})},
        ]},
    ]
    contents = _gemini_contents_from_messages(messages)
    fr = contents[-1].parts[0].function_response
    assert fr.name == "metric_distribution"
    assert fr.id == "call-42"
    assert fr.response == {"n": 8, "median": 1.23}


def test_unrecognized_content_shape_raises():
    with pytest.raises(ValueError, match="unrecognized message content shape"):
        _gemini_contents_from_messages([{"role": "user", "content": 12345}])


# --- provider.chat_step (out) ------------------------------------------------


def test_text_only_reply(provider, monkeypatch):
    monkeypatch.setattr(
        provider._client.models, "generate_content",
        lambda **kw: _text_response("your biggest loss is C01"),
    )
    step = provider.chat_step("system", [{"role": "user", "content": "hi"}], [])
    assert step["text"] == "your biggest loss is C01"
    assert step["tool_calls"] == []
    assert step["raw_content"] is None


def test_two_tool_call_turn(provider, monkeypatch):
    monkeypatch.setattr(
        provider._client.models, "generate_content",
        lambda **kw: _function_call_response([
            ("c1", "lookup_finding", {"finding_id": "vs-self:x"}),
            ("c2", "corners_in_class", {"corner_class": "fast"}),
        ]),
    )
    step = provider.chat_step("system", [{"role": "user", "content": "hi"}], TOOL_DEFS)
    assert step["text"] is None
    assert [c["name"] for c in step["tool_calls"]] == ["lookup_finding", "corners_in_class"]
    assert step["tool_calls"][0]["args"] == {"finding_id": "vs-self:x"}
    assert isinstance(step["raw_content"], types.Content)
    # Its own function_call parts are recoverable on the next translation.
    assert len(step["raw_content"].parts) == 2


def test_tools_are_translated_and_passed_through(provider, monkeypatch):
    captured = {}

    def fake_generate(**kw):
        captured.update(kw)
        return _text_response("ok")

    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate)
    provider.chat_step("system", [{"role": "user", "content": "hi"}], TOOL_DEFS)
    assert captured["config"].tools == [translate_tools(TOOL_DEFS)]
    assert captured["config"].automatic_function_calling.disable is True


def test_empty_response_raises_rather_than_returning_silently(provider, monkeypatch):
    monkeypatch.setattr(
        provider._client.models, "generate_content", lambda **kw: _empty_response(),
    )
    with pytest.raises(RuntimeError, match="neither text nor a tool call"):
        provider.chat_step("system", [{"role": "user", "content": "hi"}], [])


def test_rate_limit_retries_then_succeeds(provider, monkeypatch):
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _client_error(429)
        return _text_response("finally")

    monkeypatch.setattr(provider._client.models, "generate_content", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)  # don't actually wait in tests
    step = provider.chat_step("system", [{"role": "user", "content": "hi"}], [])
    assert step["text"] == "finally"
    assert calls["n"] == 3


def test_rate_limit_exhaustion_raises_explicit_error(provider, monkeypatch):
    monkeypatch.setattr(
        provider._client.models, "generate_content",
        lambda **kw: (_ for _ in ()).throw(_client_error(429)),
    )
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="rate limited"):
        provider.chat_step("system", [{"role": "user", "content": "hi"}], [])


def test_non_rate_limit_error_propagates_immediately(provider, monkeypatch):
    calls = {"n": 0}

    def always_500(**kw):
        calls["n"] += 1
        raise _client_error(500)

    monkeypatch.setattr(provider._client.models, "generate_content", always_500)
    from google.genai import errors as genai_errors

    with pytest.raises(genai_errors.ClientError):
        provider.chat_step("system", [{"role": "user", "content": "hi"}], [])
    assert calls["n"] == 1  # no retry on a non-429 error


def _client_error(code: int):
    from google.genai import errors as genai_errors

    return genai_errors.ClientError(code, {"error": {"message": "boom"}})


def test_missing_api_key_raises_before_any_import(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiChatProvider("gemini-3.5-flash")
