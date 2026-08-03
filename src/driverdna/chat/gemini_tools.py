"""Tool-schema translation, Anthropic -> Gemini (DEPLOY-SPEC Track P item 4).

`chat/tools.py`'s TOOL_DEFS use Anthropic's `input_schema` (a JSON-Schema
object); Gemini's `google.genai.types.FunctionDeclaration` wants a
`parameters` dict shaped for its own `Schema` type (an OpenAPI subset —
verified against the installed google-genai SDK by direct introspection,
not assumed from memory). Every current tool schema here is a flat object
of required strings/enums, so translation is mechanical — but it is a real,
tested function that raises on any schema keyword it doesn't know how to
translate, rather than silently dropping it. A silently dropped `required`
would quietly loosen a tool's real contract — exactly the kind of quiet
degradation this project forbids everywhere else, extended here.
"""

from __future__ import annotations

from typing import Any

# JSON-Schema's lowercase `type` values -> Gemini's Schema `type` values.
# Verified by direct SDK introspection: types.Schema(type="STRING", ...)
# validates and coerces to the types.Type enum automatically; the raw JSON
# Schema value ("string") is NOT accepted as-is, so this uppercase mapping
# is a real translation step, not cosmetic.
_JSON_TYPE_TO_GEMINI = {
    "string": "STRING",
    "object": "OBJECT",
    "array": "ARRAY",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
}

# Every JSON-Schema keyword this function knows how to translate. Anything
# outside this set raises rather than being dropped. TOOL_DEFS today only
# ever use type/properties/required/enum, but the set also covers `items`
# and `description` since both map cleanly onto Gemini's Schema and a
# future tool schema could reasonably use either.
_SUPPORTED_KEYS = {"type", "properties", "required", "enum", "items", "description"}


def translate_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """One Anthropic `input_schema` object -> a dict shaped for
    `google.genai.types.Schema`. Recurses into `properties`/`items`.
    Raises ValueError on any keyword or `type` value it cannot faithfully
    translate."""
    unknown = set(schema) - _SUPPORTED_KEYS
    if unknown:
        raise ValueError(
            f"cannot translate schema keyword(s) to Gemini: {sorted(unknown)}"
        )

    out: dict[str, Any] = {}
    if "type" in schema:
        json_type = schema["type"]
        gemini_type = _JSON_TYPE_TO_GEMINI.get(json_type)
        if gemini_type is None:
            raise ValueError(f"cannot translate schema type to Gemini: {json_type!r}")
        out["type"] = gemini_type
    if "description" in schema:
        out["description"] = schema["description"]
    if "enum" in schema:
        out["enum"] = list(schema["enum"])
    if "required" in schema:
        out["required"] = list(schema["required"])
    if "properties" in schema:
        out["properties"] = {
            name: translate_tool_schema(sub) for name, sub in schema["properties"].items()
        }
    if "items" in schema:
        out["items"] = translate_tool_schema(schema["items"])
    return out


def translate_tools(tool_defs: list[dict[str, Any]]):
    """`chat/tools.py`'s TOOL_DEFS -> one `google.genai.types.Tool` holding
    every function declaration. Lazy-imports the SDK like every other
    provider-specific path in this codebase."""
    from google.genai import types

    declarations = [
        types.FunctionDeclaration(
            name=tool_def["name"],
            description=tool_def["description"],
            parameters=translate_tool_schema(tool_def["input_schema"]),
        )
        for tool_def in tool_defs
    ]
    return types.Tool(function_declarations=declarations)
