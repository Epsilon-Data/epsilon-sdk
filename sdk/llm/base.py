"""
Provider-neutral chat interface.

Two backends cover the field: Anthropic's Messages API, and anything speaking
OpenAI-compatible /chat/completions -- which is vLLM, Ollama, llama.cpp, TGI,
Together, Groq and OpenRouter. Both are plain HTTP over `requests`, which the
SDK already depends on, so the copilot adds no new dependency to a package
researchers install onto their own machines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sdk.errors import SDKError


class LLMError(SDKError):
    """A model call failed, or no model is configured."""

    PUBLIC_MESSAGES = {
        "configuration": "Connect AI in Settings, then retry this question. Your notebook remains available.",
        "step_limit": "The assistant could not finish within its step limit. Prepared code is saved; retry or ask a more specific question.",
        "code_checks": "The assistant has not produced corrected code yet. Retry, or choose a simpler analysis. Your notebook is saved.",
        "credits": "Your AI provider has no API credits remaining. Add credits in its billing settings, or choose another connection in Settings.",
        "spend_limit": "Your AI provider's spending limit has been reached. Review the limit with your account administrator, or choose another connection in Settings.",
        "quota": "Your AI provider's API quota is exhausted. Check its billing and usage limits, or choose another connection in Settings.",
        "authentication": "Your AI provider rejected the API key. Check the credential source in Settings and update the key.",
        "permission": "Your AI provider denied access. Check the account, model and endpoint permissions in Settings.",
        "rate_limit": "Your AI provider is receiving requests too quickly. Wait briefly, then try again.",
        "not_found": "Your AI provider could not find the model or endpoint. Check both in Settings.",
        "timeout": "Your AI provider took too long to respond. Try again, or check the connection in Settings.",
        "connection": "Epsilon could not reach your AI provider. Check your network and the endpoint in Settings.",
        "unavailable": "Your AI provider is temporarily unavailable. Try again shortly.",
        "request": "Your AI provider rejected the request format. Check that the model and endpoint support chat with tools.",
    }

    def __init__(self, message, *, reason=None, status_code=None):
        super().__init__(message)
        self.reason = reason if isinstance(reason, str) and reason in self.PUBLIC_MESSAGES else None
        self.status_code = status_code

    @property
    def public_message(self):
        # Provider bodies may echo credentials, prompts or arbitrary markup.
        # Browser/history messages always come from this fixed vocabulary.
        return self.PUBLIC_MESSAGES.get(self.reason,
            "The model request failed. Check the provider connection in Settings and retry.")


class NoModelConfigured(LLMError):
    """No API key is available. Deterministic features still work."""


class TierTooLow(LLMError):
    """The configured model is not capable enough for this feature."""


@dataclass
class Usage:
    """Tokens one request consumed, in provider-neutral form.

    `input_tokens` excludes cached tokens on every backend, so the four
    counters never overlap and can be priced independently.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __add__(self, other):
        if other is None:
            return self
        return Usage(self.input_tokens + other.input_tokens,
                     self.output_tokens + other.output_tokens,
                     self.cache_read_tokens + other.cache_read_tokens,
                     self.cache_write_tokens + other.cache_write_tokens)

    __radd__ = __add__

    @property
    def total_tokens(self) -> int:
        return (self.input_tokens + self.output_tokens +
                self.cache_read_tokens + self.cache_write_tokens)


@dataclass
class Message:
    role: str  # "user" or "assistant"
    content: str


@dataclass
class ToolSpec:
    """A tool the model may call. Also how structured output is forced."""
    name: str
    description: str
    schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Reply:
    text: str
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    stop_reason: Optional[str] = None
    usage: Optional[Usage] = None


@dataclass
class ToolCall:
    """One tool invocation the model asked for."""
    id: str
    name: str
    input: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Turn:
    """One exchange in an agent conversation, in provider-neutral form.

    A user turn carries either text or the results of tools the assistant
    called. An assistant turn carries text, tool calls, or both.
    """
    role: str
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)


@dataclass
class AgentReply:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: Optional[str] = None
    usage: Optional[Usage] = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Provider:
    """Interface every backend implements."""

    name = "base"

    def complete(self, system: str, messages: List[Message],
                 tools: Optional[List[ToolSpec]] = None,
                 force_tool: Optional[str] = None,
                 max_tokens: int = 2048,
                 temperature: float = 0.0) -> Reply:
        raise NotImplementedError

    def converse(self, system: str, history: List[Turn],
                 tools: Optional[List[ToolSpec]] = None,
                 max_tokens: int = 4096,
                 temperature: float = 0.0) -> AgentReply:
        """One step of an agent loop: may return text, tool calls, or both."""
        raise NotImplementedError

    def list_models(self) -> List[Dict[str, str]]:
        """Models this credential can call, as [{"id", "label"}]."""
        raise NotImplementedError


class Metered(Provider):
    """Counts what a wrapped provider spends, across every call and retry.

    Attribute access falls through, so callers keep tuning `timeout` and
    friends on the real backend. A backend that reports no usage counts zero.
    """

    def __init__(self, inner: Provider):
        object.__setattr__(self, "inner", inner)
        object.__setattr__(self, "usage", Usage())
        object.__setattr__(self, "calls", 0)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def __setattr__(self, name, value):
        if name in ("usage", "calls"):
            object.__setattr__(self, name, value)
        else:
            setattr(self.inner, name, value)

    def _record(self, reply):
        usage = getattr(reply, "usage", None)
        self.usage = self.usage + (usage if isinstance(usage, Usage) else None)
        self.calls += 1
        return reply

    def complete(self, *args, **kwargs):
        return self._record(self.inner.complete(*args, **kwargs))

    def converse(self, *args, **kwargs):
        return self._record(self.inner.converse(*args, **kwargs))

    def list_models(self):
        return self.inner.list_models()
