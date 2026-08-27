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

from sdk.llm.base import (AgentReply, LLMError, Message, Provider, Reply,
                          ToolCall, ToolSpec, Turn)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 120


def _http_error(provider: str, response, key_source: Optional[str] = None) -> LLMError:
    detail = ""
    try:
        body = response.json()
        detail = body.get("error", {}).get("message") or json.dumps(body)[:300]
    except ValueError:
        detail = (response.text or "")[:300]
    if response.status_code in (401, 403):
        # Naming the source matters more than it looks: an environment
        # variable left over from a different endpoint outranks the keyring and
        # silently sends the wrong credential.
        where = " The key came from {0}.".format(key_source) if key_source else ""
        hint = ""
        if key_source and key_source.startswith("env:"):
            name = key_source.split(":", 1)[1]
            hint = (" If that is not the key you meant, run 'unset {0}' -- an "
                    "environment variable takes precedence over the "
                    "keyring.".format(name))
        return LLMError(
            "{0} rejected the API key ({1}).{2}{3} Run 'epsilon ai status' to "
            "see what is configured.".format(
                provider, response.status_code, where, hint))
    if response.status_code == 429:
        return LLMError("{0} rate-limited the request. Retry shortly.".format(provider))
    return LLMError("{0} returned {1}: {2}".format(provider, response.status_code, detail))


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None,
                 timeout: int = DEFAULT_TIMEOUT, key_source: Optional[str] = None):
        if not api_key:
            raise LLMError("the Anthropic provider needs an API key")
        self.api_key = api_key
        self.model = model
        self.url = (base_url.rstrip("/") + "/v1/messages") if base_url else ANTHROPIC_URL
        self.timeout = timeout
        self.key_source = key_source

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
            raise _http_error("Anthropic", response, self.key_source)

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



    # -- agent loop ------------------------------------------------------

    def _serialise(self, history):
        messages = []
        for turn in history:
            blocks = []
            if turn.tool_results:
                for result in turn.tool_results:
                    blocks.append({"type": "tool_result",
                                   "tool_use_id": result.call_id,
                                   "content": result.content,
                                   "is_error": result.is_error})
            if turn.text:
                blocks.append({"type": "text", "text": turn.text})
            for call in turn.tool_calls:
                blocks.append({"type": "tool_use", "id": call.id,
                               "name": call.name, "input": call.input})
            if blocks:
                messages.append({"role": turn.role, "content": blocks})
        return messages

    def converse(self, system, history, tools=None, max_tokens=4096,
                 temperature=0.0):
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": self._serialise(history),
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {"name": t.name, "description": t.description,
                 "input_schema": t.schema} for t in tools]

        try:
            response = requests.post(
                self.url, json=payload, timeout=self.timeout,
                headers={"x-api-key": self.api_key,
                         "anthropic-version": ANTHROPIC_VERSION,
                         "content-type": "application/json"})
        except requests.RequestException as exc:
            raise LLMError("could not reach the Anthropic API: {0}".format(exc))
        if response.status_code != 200:
            raise _http_error("Anthropic", response, self.key_source)

        body = response.json()
        text, calls = [], []
        for block in body.get("content", []):
            if block.get("type") == "text":
                text.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(id=block.get("id", ""),
                                      name=block.get("name", ""),
                                      input=block.get("input") or {}))
        return AgentReply(text="".join(text), tool_calls=calls,
                          stop_reason=body.get("stop_reason"))


class OpenAICompatibleProvider(Provider):
    """OpenAI itself, plus vLLM, Ollama, llama.cpp, TGI, Together, Groq,
    OpenRouter and anything else serving /v1/chat/completions."""

    name = "openai-compatible"

    def __init__(self, api_key: Optional[str], model: str, base_url: str,
                 timeout: int = DEFAULT_TIMEOUT, key_source: Optional[str] = None):
        if not base_url:
            raise LLMError(
                "this provider needs a base_url "
                "(e.g. http://localhost:11434/v1 for Ollama)")
        self.api_key = api_key or "not-needed"
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.timeout = timeout
        self.key_source = key_source
        # OpenAI's newer reasoning models renamed max_tokens and refuse a
        # temperature other than the default. Rather than maintain a list of
        # model names that will be out of date within months, adapt to what the
        # endpoint actually rejects and remember it for the session.
        self._token_param = "max_tokens"
        self._send_temperature = True

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        for _ in range(3):
            body = dict(payload)
            body[self._token_param] = body.pop("__max_tokens")
            if self._send_temperature:
                body["temperature"] = payload.get("__temperature", 0.0)
            body.pop("__temperature", None)

            try:
                response = requests.post(
                    self.url, json=body, timeout=self.timeout,
                    headers={"Authorization": "Bearer " + self.api_key,
                             "Content-Type": "application/json"})
            except requests.RequestException as exc:
                raise LLMError("could not reach {0}: {1}".format(self.url, exc))

            if response.status_code == 200:
                return response.json()

            if response.status_code == 400 and self._adapt(response):
                continue
            raise _http_error("The endpoint", response, self.key_source)
        raise LLMError("the endpoint kept rejecting the request parameters")

    def _adapt(self, response) -> bool:
        """Learn from a 400 about parameters this model will not accept."""
        try:
            message = (response.json().get("error") or {}).get("message") or ""
        except ValueError:
            return False
        lowered = message.lower()
        if "max_completion_tokens" in lowered and self._token_param == "max_tokens":
            self._token_param = "max_completion_tokens"
            return True
        if "temperature" in lowered and self._send_temperature:
            self._send_temperature = False
            return True
        return False

    def complete(self, system, messages, tools=None, force_tool=None,
                 max_tokens=2048, temperature=0.0):
        chat: List[Dict[str, Any]] = []
        if system:
            chat.append({"role": "system", "content": system})
        chat.extend({"role": m.role, "content": m.content} for m in messages)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": chat,
            "__max_tokens": max_tokens,
            "__temperature": temperature,
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

        body = self._post(payload)
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



    # -- agent loop ------------------------------------------------------

    def _serialise(self, system, history):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        for turn in history:
            for result in turn.tool_results:
                messages.append({"role": "tool",
                                 "tool_call_id": result.call_id,
                                 "name": result.name,
                                 "content": result.content})
            if turn.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": turn.text or None,
                    "tool_calls": [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.name,
                                      "arguments": json.dumps(c.input)}}
                        for c in turn.tool_calls]})
            elif turn.text:
                messages.append({"role": turn.role, "content": turn.text})
        return messages

    def converse(self, system, history, tools=None, max_tokens=4096,
                 temperature=0.0):
        payload = {
            "model": self.model,
            "messages": self._serialise(system, history),
            "__max_tokens": max_tokens,
            "__temperature": temperature,
        }
        if tools:
            payload["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.schema}} for t in tools]

        body = self._post(payload)
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("the endpoint returned no choices")
        message = choices[0].get("message") or {}

        calls = []
        for i, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            raw = function.get("arguments")
            if isinstance(raw, str):
                try:
                    arguments = json.loads(raw)
                except ValueError:
                    arguments = {}
            else:
                arguments = raw or {}
            calls.append(ToolCall(
                id=call.get("id") or "call_{0}".format(i),
                name=function.get("name", ""), input=arguments))

        return AgentReply(text=message.get("content") or "", tool_calls=calls,
                          stop_reason=choices[0].get("finish_reason"))


def build(config) -> Provider:
    """Construct the provider described by an AIConfig."""
    from sdk.llm.config import (PROVIDER_ANTHROPIC, PROVIDER_OPENAI,
                                PROVIDER_OPENAI_COMPATIBLE)

    if config.provider == PROVIDER_ANTHROPIC:
        return AnthropicProvider(config.api_key, config.model, config.base_url,
                                 key_source=config.key_source)
    if config.provider in (PROVIDER_OPENAI, PROVIDER_OPENAI_COMPATIBLE):
        return OpenAICompatibleProvider(config.api_key, config.model,
                                        config.endpoint,
                                        key_source=config.key_source)
    raise LLMError("unknown provider '{0}'".format(config.provider))
