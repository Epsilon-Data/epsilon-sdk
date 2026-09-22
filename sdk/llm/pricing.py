"""
What a request cost, as an estimate the researcher can check.

Rates are list prices in US dollars per million tokens. They go out of date,
institution endpoints have their own, and a gateway may resell a model at a
different price -- so every figure shown from here is labelled an estimate,
an unknown model has no cost rather than a guessed one, and the researcher
can enter their own rates in Settings, which always win.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sdk.llm.base import Usage
from sdk.llm.config import PROVIDER_ANTHROPIC, PROVIDER_OPENAI

PRICES_AS_OF = "2026-06"

# model-id prefix -> (input, output, cached input). Dated snapshots such as
# claude-haiku-4-5-20251001 match their family by longest prefix.
_ANTHROPIC = {
    "claude-fable-5": (10.00, 50.00, None),
    "claude-mythos-5": (10.00, 50.00, None),
    "claude-opus-5": (5.00, 25.00, None),
    "claude-opus-4-8": (5.00, 25.00, None),
    "claude-opus-4-7": (5.00, 25.00, None),
    "claude-opus-4-6": (5.00, 25.00, None),
    "claude-sonnet-5": (2.00, 10.00, None),
    "claude-sonnet-4-6": (3.00, 15.00, None),
    "claude-haiku-4-5": (1.00, 5.00, None),
}
_OPENAI = {
    "gpt-5-nano": (0.05, 0.40, 0.005),
    "gpt-5-mini": (0.25, 2.00, 0.025),
    "gpt-5": (1.25, 10.00, 0.125),
    "gpt-4.1-nano": (0.10, 0.40, 0.025),
    "gpt-4.1-mini": (0.40, 1.60, 0.10),
    "gpt-4.1": (2.00, 8.00, 0.50),
    "gpt-4o-mini": (0.15, 0.60, 0.075),
    "gpt-4o": (2.50, 10.00, 1.25),
    "o4-mini": (1.10, 4.40, 0.275),
    "o3": (2.00, 8.00, 0.50),
}
_TABLES = {PROVIDER_ANTHROPIC: _ANTHROPIC, PROVIDER_OPENAI: _OPENAI}
# The providers' own endpoints, where the list prices above apply.
_OFFICIAL = {PROVIDER_ANTHROPIC: "https://api.anthropic.com", PROVIDER_OPENAI: "https://api.openai.com/v1"}

# Anthropic bills a cache read at a tenth of input and a write at 1.25x.
CACHE_READ_FACTOR = 0.1
CACHE_WRITE_FACTOR = 1.25


def _rate(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 <= value <= 10000 else None


def rates(provider: str, model: str, custom: Optional[Dict[str, Any]] = None,
          base_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The rates that apply to this model, or None when nothing is known.

    A self-hosted, gateway or institution endpoint is never priced from the
    public tables, whatever provider type it speaks: the same model name there
    says nothing about what it costs. The researcher's own rates still apply.
    """
    own = (custom or {}).get(model)
    if isinstance(own, dict):
        given_in, given_out = _rate(own.get("input")), _rate(own.get("output"))
        if given_in is not None and given_out is not None:
            return {"input": given_in, "output": given_out, "cache_read": given_in * CACHE_READ_FACTOR,
                    "cache_write": given_in * CACHE_WRITE_FACTOR, "source": "custom"}
    table = _TABLES.get(provider)
    if not table or not isinstance(model, str):
        return None
    if base_url and base_url.rstrip("/") != _OFFICIAL[provider]:
        return None
    match = max((key for key in table if model.startswith(key)), key=len, default=None)
    if match is None:
        return None
    price_in, price_out, cached = table[match]
    return {"input": price_in, "output": price_out,
            "cache_read": cached if cached is not None else price_in * CACHE_READ_FACTOR,
            "cache_write": price_in * CACHE_WRITE_FACTOR, "source": "list price " + PRICES_AS_OF}


def cost(usage: Usage, applied: Optional[Dict[str, Any]]) -> Optional[float]:
    """Estimated US dollars, or None when the model has no known rates."""
    if applied is None:
        return None
    return (usage.input_tokens * applied["input"] + usage.output_tokens * applied["output"] +
            usage.cache_read_tokens * applied["cache_read"] +
            usage.cache_write_tokens * applied["cache_write"]) / 1_000_000
