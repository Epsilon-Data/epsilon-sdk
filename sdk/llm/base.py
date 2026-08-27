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


class NoModelConfigured(LLMError):
    """No API key is available. Deterministic features still work."""


class TierTooLow(LLMError):
    """The configured model is not capable enough for this feature."""


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

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class Provider(object):
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
