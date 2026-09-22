"""Provider failures remain actionable without disclosing response bodies."""
import pytest
import requests

from sdk.llm.base import LLMError, Message, Turn
from sdk.llm.providers import AnthropicProvider, OpenAICompatibleProvider
from tests.test_llm import FakeResponse

PRIVATE = "fixture-private-credential <script>provider body</script>"


@pytest.mark.parametrize("code,error_type,reason", [
    ("credit_balance_exhausted", "insufficient_quota", "credits"),
    ("organization_spend_limit_exceeded", "insufficient_quota", "spend_limit"),
    ("project_spend_limit_exceeded", "insufficient_quota", "spend_limit"),
    ("organization_usage_limit_exceeded", "insufficient_quota", "quota"),
    ("insufficient_quota", None, "quota"),
    (None, "insufficient_quota", "quota"),
])
def test_billing_429_is_not_a_transient_rate_limit(monkeypatch, code, error_type, reason):
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        return FakeResponse(429, {"error": {"code": code, "type": error_type, "message": PRIVATE}})
    monkeypatch.setattr("sdk.llm.providers.requests.post", post)
    provider = OpenAICompatibleProvider("k", "gpt-4o", "https://api.openai.com/v1")
    with pytest.raises(LLMError) as caught:
        provider.converse("sys", [Turn("user", text="hello")])
    error = caught.value
    assert error.reason == reason and error.status_code == 429
    assert len(calls) == 1
    assert "fixture-private" not in error.public_message
    assert "rate-limit" not in str(error) and "Retry shortly" not in str(error)
    assert "Settings" in error.public_message


@pytest.mark.parametrize("backend", ["openai", "anthropic"])
@pytest.mark.parametrize("method", ["complete", "converse"])
def test_ordinary_429_reports_a_rate_limit_on_both_chat_paths(monkeypatch, backend, method):
    monkeypatch.setattr("sdk.llm.providers.requests.post", lambda *a, **k:
        FakeResponse(429, {"error": {"code": "slow_down", "type": "rate_limit_error", "message": PRIVATE}}))
    provider = (AnthropicProvider("k", "m") if backend == "anthropic" else
                OpenAICompatibleProvider("k", "m", "https://endpoint.example/v1"))
    history = [Turn("user", text="hello")] if method == "converse" else [Message("user", "hello")]
    with pytest.raises(LLMError) as caught:
        getattr(provider, method)("sys", history)
    assert caught.value.reason == "rate_limit"
    assert "Wait briefly" in caught.value.public_message
    assert "fixture-private" not in caught.value.public_message


@pytest.mark.parametrize("payload", [[], {"error": "unusual response"}, {"error": None}])
def test_nonstandard_http_errors_do_not_crash_error_handling(monkeypatch, payload):
    monkeypatch.setattr("sdk.llm.providers.requests.post", lambda *a, **k: FakeResponse(400, payload))
    with pytest.raises(LLMError) as caught:
        OpenAICompatibleProvider("k", "m", "https://endpoint.example/v1").converse("sys", [])
    assert caught.value.reason == "request"
    assert "unusual response" not in caught.value.public_message


@pytest.mark.parametrize("exception,reason", [(requests.Timeout, "timeout"), (requests.ConnectionError, "connection")])
def test_network_errors_have_safe_recovery_text(monkeypatch, exception, reason):
    def post(*args, **kwargs):
        raise exception(PRIVATE)
    monkeypatch.setattr("sdk.llm.providers.requests.post", post)
    with pytest.raises(LLMError) as caught:
        OpenAICompatibleProvider("k", "m", "https://endpoint.example/v1").converse("sys", [])
    assert caught.value.reason == reason
    assert "fixture-private" not in caught.value.public_message


def test_unknown_reasons_never_become_browser_text():
    error = LLMError(PRIVATE, reason=PRIVATE)
    assert error.reason is None
    assert error.public_message.startswith("The model request failed.")
    assert "fixture-private" not in error.public_message


@pytest.mark.parametrize("reason", ["credits", "quota", "spend_limit", "authentication", "rate_limit", "connection"])
def test_structured_suggestions_do_not_retry_account_or_connection_errors(reason):
    from unittest.mock import Mock
    from sdk.llm.schema import structured
    provider = Mock()
    provider.complete.side_effect = LLMError(PRIVATE, reason=reason)
    with pytest.raises(LLMError) as caught:
        structured(provider, "sys", "hello", {"type": "object"})
    assert provider.complete.call_count == 1
    assert caught.value.reason == reason


def test_structured_output_can_still_fall_back_when_tools_are_rejected():
    from unittest.mock import Mock
    from sdk.llm.base import Reply
    from sdk.llm.schema import structured
    provider = Mock()
    provider.complete.side_effect = [LLMError("tools unsupported", reason="request"), Reply(text='{"ok": true}')]
    assert structured(provider, "sys", "hello", {"type": "object"}) == {"ok": True}
    assert provider.complete.call_count == 2
