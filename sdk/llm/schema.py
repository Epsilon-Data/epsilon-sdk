"""
Ask for a validated object rather than prose.

Nearly every model call the copilot makes wants structured data: which
catalogue entry a question maps onto, which leaves to parameterise a template
with. Native constrained decoding handles that where the backend offers it
(Anthropic forced tool-use; OpenAI-compatible function calling). Where it does
not, or where a weaker model emits something that does not validate, the reply
is fed its own validation error and asked again.

That retry loop is what makes a tier-B open model usable on the same code path
as a frontier one, so nothing above this layer has to know which is configured.

The validator covers the subset of JSON Schema these prompts use. It is
deliberately small: adding `jsonschema` as a dependency to buy draft-2020
coverage nobody needs would work against keeping the SDK thin.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from sdk.llm.base import LLMError, Message, Provider, Reply, ToolSpec

MAX_ATTEMPTS = 3

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


class ValidationError(Exception):
    """The model's output did not match the requested schema."""


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def validate(value: Any, schema: Dict[str, Any], path: str = "$") -> None:
    """Raise ValidationError describing the first mismatch found."""
    expected = schema.get("type")
    if expected:
        actual = _type_name(value)
        ok = (actual == expected
              or (expected == "number" and actual == "integer")
              or (expected == "integer" and isinstance(value, bool) is False
                  and actual == "integer"))
        if not ok:
            raise ValidationError(
                "{0}: expected {1}, got {2}".format(path, expected, actual))

    if "enum" in schema and value not in schema["enum"]:
        raise ValidationError(
            "{0}: {1!r} is not one of {2}".format(path, value, schema["enum"]))

    if expected == "object" or isinstance(value, dict):
        properties = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if not isinstance(value, dict) or name not in value:
                raise ValidationError("{0}: missing required property '{1}'".format(path, name))
        if isinstance(value, dict):
            for name, sub in properties.items():
                if name in value:
                    validate(value[name], sub, "{0}.{1}".format(path, name))

    if expected == "array" or isinstance(value, list):
        items = schema.get("items")
        if items and isinstance(value, list):
            for i, item in enumerate(value):
                validate(item, items, "{0}[{1}]".format(path, i))


def extract_json(text: str) -> Any:
    """Pull a JSON value out of a reply that may be wrapped in prose or fences."""
    if not text:
        raise ValidationError("the model returned an empty reply")
    candidates: List[str] = []
    match = _JSON_BLOCK.search(text)
    if match:
        candidates.append(match.group(1).strip())
    candidates.append(text.strip())
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise ValidationError("the model's reply was not valid JSON")


def structured(provider: Provider, system: str, prompt: str,
               schema: Dict[str, Any], tool_name: str = "respond",
               description: str = "Return the answer in the required shape.",
               max_attempts: int = MAX_ATTEMPTS,
               max_tokens: int = 2048) -> Dict[str, Any]:
    """Get a schema-valid object back, retrying with the validation error."""
    messages = [Message("user", prompt)]
    tool = ToolSpec(name=tool_name, description=description, schema=schema)
    last_error: Optional[str] = None

    for attempt in range(max_attempts):
        use_tools = attempt == 0
        try:
            if use_tools:
                reply = provider.complete(system, messages, tools=[tool],
                                          force_tool=tool_name, max_tokens=max_tokens)
            else:
                reply = provider.complete(system, messages, max_tokens=max_tokens)
        except LLMError as exc:
            # Removing tools cannot resolve billing, access or network errors.
            # Do not immediately repeat a rate-limited request either.
            if exc.reason not in (None, "request") or attempt + 1 >= max_attempts:
                raise
            continue

        try:
            value = _value_from(reply, schema)
            validate(value, schema)
            return value
        except ValidationError as exc:
            last_error = str(exc)
            messages = [
                Message("user", prompt),
                Message("assistant", reply.text or json.dumps(reply.tool_input or {})),
                Message("user",
                        "That did not match the required schema: {0}\n\n"
                        "Reply with JSON only -- no prose, no code fences -- "
                        "matching this schema exactly:\n{1}".format(
                            last_error, json.dumps(schema, indent=2))),
            ]

    raise LLMError(
        "the model did not return a valid response after {0} attempts "
        "(last error: {1}). A more capable model may be needed.".format(
            max_attempts, last_error))


def _value_from(reply: Reply, schema: Dict[str, Any]) -> Any:
    """Prefer a tool call's input; fall back to parsing the text."""
    if reply.tool_input is not None:
        return reply.tool_input
    return extract_json(reply.text)
