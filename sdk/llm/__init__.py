"""
Model access for the copilot.

Everything here is optional. `epsilon explain`, `epsilon snippet` and
`epsilon check` all produce their verdicts without a model configured -- the
model phrases and plans, it never decides. `available()` is how callers ask
whether the enrichment layer is present before reaching for it.
"""
from __future__ import annotations

from typing import Optional

from sdk.llm.base import (LLMError, Message, NoModelConfigured, Provider,
                          Reply, TierTooLow, ToolSpec)
from sdk.llm.config import (AIConfig, TIER_A, TIER_B, TIER_C, load,
                            tier_at_least)
from sdk.llm.providers import build
from sdk.llm.schema import ValidationError, structured, validate

__all__ = [
    "AIConfig", "LLMError", "Message", "NoModelConfigured", "Provider",
    "Reply", "TierTooLow", "ToolSpec", "ValidationError",
    "TIER_A", "TIER_B", "TIER_C",
    "available", "get_provider", "load", "structured", "tier_at_least",
    "validate",
]


def available() -> bool:
    """Whether a model is configured. Never raises."""
    try:
        return load().configured
    except Exception:
        return False


def get_provider(required_tier: str = TIER_C,
                 feature: str = "this feature") -> Provider:
    """Build the configured provider, or explain precisely why we cannot.

    Refuses rather than degrades when the configured model is below the tier a
    feature needs: a model too weak to follow the disclosure rules would emit
    code that leaks records, which is a policy incident and not a quality
    problem.
    """
    config = load()
    if not config.configured:
        raise NoModelConfigured(
            "No model is configured, so {0} is unavailable. Run "
            "'epsilon ai login', or set ANTHROPIC_API_KEY. Deterministic "
            "commands (explain, snippet, check) work without "
            "one.".format(feature))
    if not tier_at_least(config.tier, required_tier):
        raise TierTooLow(
            "{0} needs a tier-{1} model; the configured model is tier {2}. "
            "Raise 'tier' in ~/.epsilon_sdk/config.ini only if the model can "
            "genuinely do it.".format(feature, required_tier, config.tier))
    return build(config)
