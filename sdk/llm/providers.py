"""
The two backends.

Both speak plain HTTP through `requests`. Neither pulls in a vendor SDK: the
whole point of the abstraction is that epsilon-sdk stays thin enough to install
onto a researcher's machine without dragging a dependency tree behind it.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

from sdk.llm.base import LLMError, Message, Provider, Reply, ToolSpec

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 120


def _http_error(provider: str, response) -> LLMError:
    detail = ""
    try:
        body = response.json()
        detail = body.get("error", {}).get("message") or json.dumps(body)[:300]
    except ValueError:
        detail = (response.text or "")[:300]
    if response.status_code in (401, 403):
        return LLMError(
            "{0} rejected the API key ({1}). Check 'epsilon ai status', or set "
            "the key again with 'epsilon ai login'.".format(provider, response.status_code))
    if response.status_code == 429:
        return LLMError("{0} rate-limited the request. Retry shortly.".format(provider))
    return LLMError("{0} returned {1}: {2}".format(provider, response.status_code, detail))


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None,
                 timeout: int = DEFAULT_TIMEOUT):
        if not api_key:
            raise LLMError("the Anthropic provider needs an API key")
        self.api_key = api_key
        self.model = model
        self.url = (base_url.rstrip("/") + "/v1/messages") if base_url else ANTHROPIC_URL
        self.timeout = timeout

    def complete(self, system, messages, tools=None, force_tool=None,
                 max_tokens=2048, temperature=0.0):
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.schema}
                for t in tools
            ]
            if force_tool:
                payload["tool_choice"] = {"type": "tool", "name": force_tool}

        try:
            response = requests.post(
                self.url, json=payload, timeout=self.timeout,
                headers={"x-api-key": self.api_key,
                         "anthropic-version": ANTHROPIC_VERSION,
                         "content-type": "application/json"})
        except requests.RequestException as exc:
            raise LLMError("could not reach the Anthropic API: {0}".format(exc))

        if response.status_code != 200:
            raise _http_error("Anthropic", response)

        body = response.json()
        text_parts, tool_name, tool_input = [], None, None
        for block in body.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_name = block.get("name")
                tool_input = block.get("input")
        return Reply(text="".join(text_parts), tool_name=tool_name,
                     tool_input=tool_input, stop_reason=body.get("stop_reason"))


class OpenAICompatibleProvider(Provider):
    """vLLM, Ollama, llama.cpp, TGI, Together, Groq, OpenRouter, and friends."""

    name = "openai-compatible"

    def __init__(self, api_key: Optional[str], model: str, base_url: str,
                 timeout: int = DEFAULT_TIMEOUT):
        if not base_url:
            raise LLMError(
                "the openai-compatible provider needs a base_url "
                "(e.g. http://localhost:11434/v1 for Ollama)")
        self.api_key = api_key or "not-needed"
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.timeout = timeout

    def complete(self, system, messages, tools=None, force_tool=None,
                 max_tokens=2048, temperature=0.0):
        chat: List[Dict[str, Any]] = []
        if system:
            chat.append({"role": "system", "content": system})
        chat.extend({"role": m.role, "content": m.content} for m in messages)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": chat,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.schema}}
                for t in tools
            ]
            if force_tool:
                payload["tool_choice"] = {"type": "function",
                                          "function": {"name": force_tool}}

        try:
            response = requests.post(
                self.url, json=payload, timeout=self.timeout,
                headers={"Authorization": "Bearer " + self.api_key,
                         "Content-Type": "application/json"})
        except requests.RequestException as exc:
            raise LLMError("could not reach {0}: {1}".format(self.url, exc))

        if response.status_code != 200:
            raise _http_error("The endpoint", response)

        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("the endpoint returned no choices")
        message = choices[0].get("message") or {}

        tool_name, tool_input = None, None
        for call in (message.get("tool_calls") or []):
            function = call.get("function") or {}
            tool_name = function.get("name")
            raw = function.get("arguments")
            if isinstance(raw, str):
                try:
                    tool_input = json.loads(raw)
                except ValueError:
                    tool_input = None
            elif isinstance(raw, dict):
                tool_input = raw
            break

        return Reply(text=message.get("content") or "", tool_name=tool_name,
                     tool_input=tool_input,
                     stop_reason=choices[0].get("finish_reason"))


def build(config) -> Provider:
    """Construct the provider described by an AIConfig."""
    from sdk.llm.config import PROVIDER_ANTHROPIC, PROVIDER_OPENAI_COMPATIBLE

    if config.provider == PROVIDER_ANTHROPIC:
        return AnthropicProvider(config.api_key, config.model, config.base_url)
    if config.provider == PROVIDER_OPENAI_COMPATIBLE:
        return OpenAICompatibleProvider(config.api_key, config.model, config.base_url)
    raise LLMError("unknown provider '{0}'".format(config.provider))
