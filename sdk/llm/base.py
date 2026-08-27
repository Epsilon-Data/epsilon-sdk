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


class Provider(object):
    """Interface every backend implements."""

    name = "base"

    def complete(self, system: str, messages: List[Message],
                 tools: Optional[List[ToolSpec]] = None,
                 force_tool: Optional[str] = None,
                 max_tokens: int = 2048,
                 temperature: float = 0.0) -> Reply:
        raise NotImplementedError
