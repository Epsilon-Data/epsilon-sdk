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

from sdk.llm.base import (AgentReply, LLMError, Provider, Reply,
                          ToolCall, Usage)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 120


def _http_error(provider: str, response, key_source: Optional[str] = None) -> LLMError:
    detail, error = "", {}
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        error = error if isinstance(error, dict) else {}
        detail = str(error.get("message") or json.dumps(body))[:300]
    except ValueError:
        detail = (response.text or "")[:300]
    code = error.get("code")
    code = code if isinstance(code, str) else ""
    error_type = error.get("type")
    billing = {"credit_balance_exhausted": "credits", "insufficient_quota": "quota",
               "organization_spend_limit_exceeded": "spend_limit",
               "project_spend_limit_exceeded": "spend_limit",
               "organization_usage_limit_exceeded": "quota"}
    # A billing 429 needs an account change; it is not a transient rate limit.
    reason = billing.get(code) or ("quota" if error_type == "insufficient_quota" else None)
    if reason and response.status_code in (400, 402, 429):
        return LLMError(LLMError.PUBLIC_MESSAGES[reason], reason=reason, status_code=response.status_code)
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
                provider, response.status_code, where, hint),
            reason="authentication" if response.status_code == 401 else "permission",
            status_code=response.status_code)
    if response.status_code == 429:
        return LLMError("{0} rate-limited the request. Retry shortly.".format(provider),
                        reason="rate_limit", status_code=429)
    reason = ("not_found" if response.status_code == 404 else
              "unavailable" if response.status_code >= 500 else
              "request" if response.status_code in (400, 422) else None)
    return LLMError("{0} returned {1}: {2}".format(provider, response.status_code, detail),
                    reason=reason, status_code=response.status_code)


def _connection_error(detail, error):
    return LLMError(detail, reason="timeout" if isinstance(error, requests.Timeout) else "connection")


def _json_body(provider: str, response) -> Dict[str, Any]:
    """A successful response must still be a JSON object before we read it."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise LLMError("{0} returned a response that is not a JSON object".format(provider), reason="request")
    return body


def _anthropic_tools(tools) -> List[Dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools]


def _openai_tools(tools) -> List[Dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
            for t in tools]


def _openai_message(body):
    """The first choice and its message, which is all either call reads."""
    choices = body.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise LLMError("the endpoint returned no choices")
    return choices[0], choices[0].get("message") or {}


def _arguments(raw, default):
    """Tool arguments arrive as a JSON string from most servers, a dict from a few."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return default
    return raw if isinstance(raw, dict) else default


# OpenAI lists embeddings, speech and image models beside chat ones.
_OPENAI_NON_CHAT = ("embedding", "audio", "realtime", "tts", "transcribe", "image",
                    "whisper", "dall-e", "moderation", "search", "instruct")


def _openai_chat_model(name) -> bool:
    return name.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")) and not any(w in name for w in _OPENAI_NON_CHAT)


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _anthropic_usage(body) -> Optional[Usage]:
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return None
    return Usage(_count(usage.get("input_tokens")), _count(usage.get("output_tokens")),
                 _count(usage.get("cache_read_input_tokens")),
                 _count(usage.get("cache_creation_input_tokens")))


def _openai_usage(body) -> Optional[Usage]:
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return None
    details = usage.get("prompt_tokens_details")
    cached = _count(details.get("cached_tokens")) if isinstance(details, dict) else 0
    prompt = _count(usage.get("prompt_tokens"))
    # OpenAI counts cached tokens inside prompt_tokens; keep counters disjoint.
    return Usage(max(0, prompt - cached), _count(usage.get("completion_tokens")), cached, 0)


def _model_list(body, keep=None) -> List[Dict[str, str]]:
    models = []
    for item in (body.get("data") if isinstance(body, dict) else None) or []:
        model_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(model_id, str) or not 0 < len(model_id) <= 150 or (keep and not keep(model_id)):
            continue
        label = item.get("display_name")
        models.append({"id": model_id, "label": label[:150] if isinstance(label, str) and label else model_id})
    return models[:200]


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
        # Current Claude models reject sampling parameters outright. As with
        # the OpenAI backend, learn that from the endpoint, not a model list.
        self._send_temperature = True

    def _headers(self):
        return {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json"}

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        for _ in range(2):
            body = dict(payload)
            if not self._send_temperature:
                body.pop("temperature", None)
            try:
                response = requests.post(self.url, json=body, timeout=self.timeout,
                                         headers=self._headers())
            except requests.RequestException as exc:
                raise _connection_error("could not reach the Anthropic API: {0}".format(exc), exc)
            if response.status_code == 200:
                return _json_body("Anthropic", response)
            if response.status_code == 400 and self._send_temperature and "temperature" in (response.text or "").lower():
                self._send_temperature = False
                continue
            raise _http_error("Anthropic", response, self.key_source)
        raise LLMError("Anthropic kept rejecting the request parameters", reason="request")

    def list_models(self):
        try:
            response = requests.get(self.url.rsplit("/", 1)[0] + "/models", params={"limit": 100},
                                    timeout=self.timeout, headers=self._headers())
        except requests.RequestException as exc:
            raise _connection_error("could not reach the Anthropic API: {0}".format(exc), exc)
        if response.status_code != 200:
            raise _http_error("Anthropic", response, self.key_source)
        return _model_list(_json_body("Anthropic", response))

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
            payload["tools"] = _anthropic_tools(tools)
            if force_tool:
                payload["tool_choice"] = {"type": "tool", "name": force_tool}

        body = self._post(payload)
        text_parts, tool_name, tool_input = [], None, None
        for block in body.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_name = block.get("name")
                tool_input = block.get("input")
        return Reply(text="".join(text_parts), tool_name=tool_name,
                     tool_input=tool_input, stop_reason=body.get("stop_reason"),
                     usage=_anthropic_usage(body))


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
            payload["tools"] = _anthropic_tools(tools)

        body = self._post(payload)
        text, calls = [], []
        for block in body.get("content", []):
            if block.get("type") == "text":
                text.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(id=block.get("id", ""),
                                      name=block.get("name", ""),
                                      input=block.get("input") or {}))
        return AgentReply(text="".join(text), tool_calls=calls,
                          stop_reason=body.get("stop_reason"), usage=_anthropic_usage(body))


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
                raise _connection_error("could not reach {0}: {1}".format(self.url, exc), exc)

            if response.status_code == 200:
                return _json_body("The endpoint", response)

            if response.status_code == 400 and self._adapt(response):
                continue
            raise _http_error("The endpoint", response, self.key_source)
        raise LLMError("the endpoint kept rejecting the request parameters")

    def list_models(self):
        try:
            response = requests.get(self.url.rsplit("/chat/completions", 1)[0] + "/models",
                                    timeout=self.timeout,
                                    headers={"Authorization": "Bearer " + self.api_key})
        except requests.RequestException as exc:
            raise _connection_error("could not reach {0}: {1}".format(self.url, exc), exc)
        if response.status_code != 200:
            raise _http_error("The endpoint", response, self.key_source)
        keep = _openai_chat_model if self.url.startswith("https://api.openai.com/") else None
        return _model_list(_json_body("The endpoint", response), keep)

    def _adapt(self, response) -> bool:
        """Learn from a 400 about parameters this model will not accept."""
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
        except ValueError:
            return False
        if not isinstance(message, str):
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
            payload["tools"] = _openai_tools(tools)
            if force_tool:
                payload["tool_choice"] = {"type": "function",
                                          "function": {"name": force_tool}}

        body = self._post(payload)
        choice, message = _openai_message(body)

        tool_name, tool_input = None, None
        for call in (message.get("tool_calls") or [])[:1]:
            function = call.get("function") or {}
            tool_name = function.get("name")
            tool_input = _arguments(function.get("arguments"), None)

        return Reply(text=message.get("content") or "", tool_name=tool_name,
                     tool_input=tool_input,
                     stop_reason=choice.get("finish_reason"),
                     usage=_openai_usage(body))


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
            payload["tools"] = _openai_tools(tools)

        body = self._post(payload)
        choice, message = _openai_message(body)

        calls = []
        for i, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            calls.append(ToolCall(
                id=call.get("id") or "call_{0}".format(i),
                name=function.get("name", ""), input=_arguments(function.get("arguments"), {})))

        return AgentReply(text=message.get("content") or "", tool_calls=calls,
                          stop_reason=choice.get("finish_reason"),
                          usage=_openai_usage(body))


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
