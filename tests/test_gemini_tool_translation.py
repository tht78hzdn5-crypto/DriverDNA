"""DEPLOY-SPEC Track P item 4: tool-schema translation, Anthropic -> Gemini.

translate_tool_schema is pure-Python dict transformation and needs no SDK,
so it's tested directly and unconditionally. translate_tools builds real
google.genai.types objects and is skipped when the optional google-genai
package isn't installed — the same importorskip pattern this codebase
already uses for Playwright.
"""

from __future__ import annotations

import pytest

from driverdna.chat.gemini_tools import translate_tool_schema, translate_tools
from driverdna.chat.tools import TOOL_DEFS


def test_flat_string_schema_translates():
    schema = {
        "type": "object",
        "properties": {"finding_id": {"type": "string"}},
        "required": ["finding_id"],
    }
    assert translate_tool_schema(schema) == {
        "type": "OBJECT",
        "properties": {"finding_id": {"type": "STRING"}},
        "required": ["finding_id"],
    }


def test_enum_property_translates():
    schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["acknowledged", "intentional"]},
        },
        "required": ["status"],
    }
    translated = translate_tool_schema(schema)
    assert translated["properties"]["status"]["enum"] == ["acknowledged", "intentional"]
    assert translated["properties"]["status"]["type"] == "STRING"


def test_every_real_tool_def_translates_without_raising():
    """The actual TOOL_DEFS this codebase ships, not a synthetic example —
    proves the translator handles every schema shape currently in use,
    including propose_config_change's untyped `new_value` (an empty {})."""
    for tool_def in TOOL_DEFS:
        translated = translate_tool_schema(tool_def["input_schema"])
        assert translated["type"] == "OBJECT"


def test_unknown_keyword_raises_rather_than_silently_dropping():
    schema = {"type": "object", "oneOf": [{"type": "string"}]}
    with pytest.raises(ValueError, match="oneOf"):
        translate_tool_schema(schema)


def test_unknown_type_value_raises():
    schema = {"type": "null"}
    with pytest.raises(ValueError, match="null"):
        translate_tool_schema(schema)


def test_nested_array_items_translate():
    schema = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
    }
    translated = translate_tool_schema(schema)
    assert translated["properties"]["tags"]["items"] == {"type": "STRING"}


google_genai = pytest.importorskip("google.genai")


def test_translate_tools_builds_real_gemini_tool():
    from google.genai import types

    tool = translate_tools(TOOL_DEFS)
    assert isinstance(tool, types.Tool)
    names = {fd.name for fd in tool.function_declarations}
    assert names == {t["name"] for t in TOOL_DEFS}
    # Every declared parameter set is a real, SDK-validated Schema — this
    # would raise at construction time if translation produced anything
    # google-genai's own pydantic models reject.
    for fd in tool.function_declarations:
        assert fd.parameters.type == types.Type.OBJECT
