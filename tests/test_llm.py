"""Tests for the provider abstraction, key handling and structured output."""
import json
import os

import pytest

from sdk.llm import config as ai_config
from sdk.llm.base import LLMError, Message, NoModelConfigured, Reply, TierTooLow
from sdk.llm.providers import (AnthropicProvider, OpenAICompatibleProvider,
                               build)
from sdk.llm.schema import ValidationError, extract_json, structured, validate


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ai_config.ENV_KEYS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    return tmp_path


class TestKeyResolution:
    def test_environment_wins(self, home, monkeypatch):
        monkeypatch.setattr(ai_config, "_key_from_keyring", lambda: "from-ring")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        cfg = ai_config.load()
        assert cfg.api_key == "from-env"
        assert cfg.key_source == "env:ANTHROPIC_API_KEY"

    def test_keyring_is_used_when_the_environment_is_empty(self, home, monkeypatch):
        monkeypatch.setattr(ai_config, "_key_from_keyring", lambda: "from-ring")
        cfg = ai_config.load()
        assert cfg.api_key == "from-ring"
        assert cfg.key_source == "keyring"

    def test_the_config_file_is_the_last_resort(self, home, monkeypatch):
        monkeypatch.setattr(ai_config, "_key_from_keyring", lambda: None)
        ai_config.save("anthropic", "claude-sonnet-5", None, "A")
        path = ai_config.config_path()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("api_key = from-file\n")
        cfg = ai_config.load()
        assert cfg.api_key == "from-file"
        assert cfg.key_source == "config file"

    def test_no_key_is_not_an_error(self, home, monkeypatch):
        monkeypatch.setattr(ai_config, "_key_from_keyring", lambda: None)
        cfg = ai_config.load()
        assert cfg.api_key is None
        assert cfg.configured is False

    def test_include_key_false_skips_resolution(self, home, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        assert ai_config.load(include_key=False).api_key is None


class TestConfigFile:
    def test_save_never_writes_the_key(self, home):
        path = ai_config.save("anthropic", "claude-sonnet-5", None, "A")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        assert "api_key" not in body
        assert "claude-sonnet-5" in body

    def test_saved_settings_round_trip(self, home):
        ai_config.save("openai-compatible", "llama-3.3-70b",
                       "http://localhost:8000/v1", "B")
        cfg = ai_config.load(include_key=False)
        assert cfg.provider == "openai-compatible"
        assert cfg.base_url == "http://localhost:8000/v1"
        assert cfg.tier == "B"

    def test_the_config_file_is_not_world_readable(self, home):
        path = ai_config.save("anthropic", "m", None, "A")
        assert oct(os.stat(path).st_mode)[-3:] == "600"

    def test_a_corrupt_config_file_does_not_crash(self, home):
        os.makedirs(ai_config.config_dir(), exist_ok=True)
        with open(ai_config.config_path(), "w", encoding="utf-8") as fh:
            fh.write("this is not ini [[[\n")
        assert ai_config.load(include_key=False).provider == "anthropic"


class TestTiers:
    def test_ordering(self):
        assert ai_config.tier_at_least("A", "B")
        assert ai_config.tier_at_least("B", "B")
        assert not ai_config.tier_at_least("C", "B")

    def test_an_unknown_tier_never_satisfies_a_requirement(self):
        assert not ai_config.tier_at_least("Z", "C")

    def test_get_provider_refuses_below_the_required_tier(self, home, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        ai_config.save("anthropic", "tiny", None, "C")
        from sdk import llm
        with pytest.raises(TierTooLow):
            llm.get_provider(llm.TIER_A, "code generation")

    def test_get_provider_explains_when_nothing_is_configured(self, home, monkeypatch):
        monkeypatch.setattr(ai_config, "_key_from_keyring", lambda: None)
        from sdk import llm
        with pytest.raises(NoModelConfigured) as exc:
            llm.get_provider(llm.TIER_C, "suggestions")
        assert "work without one" in str(exc.value)


class TestProviderConstruction:
    def test_anthropic_needs_a_key(self):
        with pytest.raises(LLMError):
            AnthropicProvider("", "claude-sonnet-5")

    def test_openai_compatible_needs_a_base_url(self):
        with pytest.raises(LLMError) as exc:
            OpenAICompatibleProvider("k", "m", "")
        assert "base_url" in str(exc.value)

    def test_openai_compatible_works_without_a_key(self):
        """Ollama and a local vLLM want no credential at all."""
        provider = OpenAICompatibleProvider(None, "llama", "http://localhost:11434/v1")
        assert provider.url.endswith("/chat/completions")

    def test_build_rejects_an_unknown_provider(self):
        cfg = ai_config.AIConfig(provider="mystery")
        with pytest.raises(LLMError):
            build(cfg)


class TestValidator:
    SCHEMA = {
        "type": "object",
        "required": ["pick"],
        "properties": {
            "pick": {"type": "string", "enum": ["a", "b"]},
            "n": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }

    def test_accepts_a_valid_object(self):
        validate({"pick": "a", "n": 1, "tags": ["x"]}, self.SCHEMA)

    def test_reports_the_missing_property_by_name(self):
        with pytest.raises(ValidationError) as exc:
            validate({"n": 1}, self.SCHEMA)
        assert "'pick'" in str(exc.value)

    def test_reports_a_bad_enum_value(self):
        with pytest.raises(ValidationError) as exc:
            validate({"pick": "z"}, self.SCHEMA)
        assert "not one of" in str(exc.value)

    def test_reports_a_type_mismatch_with_its_path(self):
        with pytest.raises(ValidationError) as exc:
            validate({"pick": "a", "n": "x"}, self.SCHEMA)
        assert "$.n" in str(exc.value)

    def test_checks_inside_arrays(self):
        with pytest.raises(ValidationError) as exc:
            validate({"pick": "a", "tags": ["ok", 3]}, self.SCHEMA)
        assert "$.tags[1]" in str(exc.value)

    def test_an_integer_satisfies_number(self):
        validate(3, {"type": "number"})


class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('sure:\n```json\n{"a": 1}\n```\n') == {"a": 1}

    def test_json_embedded_in_prose(self):
        assert extract_json('Here it is {"a": 1} hope that helps') == {"a": 1}

    def test_empty_reply_raises(self):
        with pytest.raises(ValidationError):
            extract_json("")

    def test_unparseable_reply_raises(self):
        with pytest.raises(ValidationError):
            extract_json("no json at all")


class FakeProvider:
    """Replays canned replies and records how it was called."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, system, messages, tools=None, force_tool=None,
                 max_tokens=2048, temperature=0.0):
        self.calls.append({"messages": list(messages), "tools": tools,
                           "force_tool": force_tool})
        return self.replies.pop(0)


class TestStructured:
    SCHEMA = {"type": "object", "required": ["pick"],
              "properties": {"pick": {"type": "string"}}}

    def test_uses_forced_tool_use_on_the_first_attempt(self):
        provider = FakeProvider([Reply(text="", tool_name="respond",
                                       tool_input={"pick": "a"})])
        result = structured(provider, "sys", "prompt", self.SCHEMA)
        assert result == {"pick": "a"}
        assert provider.calls[0]["force_tool"] == "respond"

    def test_falls_back_to_parsing_text(self):
        provider = FakeProvider([Reply(text='{"pick": "a"}')])
        assert structured(provider, "sys", "prompt", self.SCHEMA) == {"pick": "a"}

    def test_retries_with_the_validation_error(self):
        """The retry loop is what makes a weaker open model usable."""
        provider = FakeProvider([
            Reply(text='{"wrong": true}'),
            Reply(text='{"pick": "a"}'),
        ])
        assert structured(provider, "sys", "prompt", self.SCHEMA) == {"pick": "a"}
        retry_prompt = provider.calls[1]["messages"][-1].content
        assert "missing required property 'pick'" in retry_prompt

    def test_stops_using_tools_after_the_first_attempt(self):
        provider = FakeProvider([Reply(text="junk"), Reply(text='{"pick": "a"}')])
        structured(provider, "sys", "prompt", self.SCHEMA)
        assert provider.calls[1]["tools"] is None

    def test_gives_up_with_a_useful_message(self):
        provider = FakeProvider([Reply(text="junk")] * 3)
        with pytest.raises(LLMError) as exc:
            structured(provider, "sys", "prompt", self.SCHEMA)
        assert "more capable model" in str(exc.value)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestOpenAIProvider:
    """OpenAI's own API is the openai-compatible backend. Its newer models
    renamed max_tokens and refuse a custom temperature, and the model list
    changes faster than any hardcoded table would survive."""

    def _ok(self):
        return FakeResponse(200, {"choices": [
            {"message": {"content": "hi"}, "finish_reason": "stop"}]})

    def _rejects(self, text):
        return FakeResponse(400, {"error": {"message": text}})

    def test_the_openai_provider_defaults_to_the_public_endpoint(self):
        cfg = ai_config.AIConfig(provider="openai", model="gpt-4o", api_key="k")
        provider = build(cfg)
        assert provider.url == "https://api.openai.com/v1/chat/completions"

    def test_an_explicit_base_url_still_wins(self):
        cfg = ai_config.AIConfig(provider="openai", model="gpt-4o", api_key="k",
                                 base_url="https://gateway.internal/v1")
        assert build(cfg).url.startswith("https://gateway.internal/v1")

    def test_max_tokens_is_renamed_when_the_model_rejects_it(self, monkeypatch):
        sent = []

        def fake_post(url, json=None, **kwargs):
            sent.append(json)
            if "max_tokens" in json:
                return self._rejects(
                    "Unsupported parameter: 'max_tokens' is not supported with "
                    "this model. Use 'max_completion_tokens' instead.")
            return self._ok()

        monkeypatch.setattr("sdk.llm.providers.requests.post", fake_post)
        provider = OpenAICompatibleProvider("k", "o3", "https://api.openai.com/v1")
        provider.complete("sys", [Message("user", "hi")])
        assert "max_completion_tokens" in sent[-1]
        assert "max_tokens" not in sent[-1]

    def test_the_rename_is_remembered_for_later_calls(self, monkeypatch):
        sent = []

        def fake_post(url, json=None, **kwargs):
            sent.append(json)
            if "max_tokens" in json:
                return self._rejects("Use 'max_completion_tokens' instead.")
            return self._ok()

        monkeypatch.setattr("sdk.llm.providers.requests.post", fake_post)
        provider = OpenAICompatibleProvider("k", "o3", "https://api.openai.com/v1")
        provider.complete("sys", [Message("user", "hi")])
        provider.complete("sys", [Message("user", "again")])
        # first call retried; the second must not repeat the mistake
        assert len(sent) == 3
        assert "max_completion_tokens" in sent[-1]

    def test_temperature_is_dropped_when_the_model_refuses_it(self, monkeypatch):
        sent = []

        def fake_post(url, json=None, **kwargs):
            sent.append(json)
            if "temperature" in json:
                return self._rejects(
                    "Unsupported value: 'temperature' does not support 0.0 "
                    "with this model. Only the default (1) is supported.")
            return self._ok()

        monkeypatch.setattr("sdk.llm.providers.requests.post", fake_post)
        provider = OpenAICompatibleProvider("k", "o3", "https://api.openai.com/v1")
        provider.complete("sys", [Message("user", "hi")])
        assert "temperature" not in sent[-1]

    def test_the_agent_loop_adapts_the_same_way(self, monkeypatch):
        from sdk.llm.base import Turn
        sent = []

        def fake_post(url, json=None, **kwargs):
            sent.append(json)
            if "max_tokens" in json:
                return self._rejects("Use 'max_completion_tokens' instead.")
            return self._ok()

        monkeypatch.setattr("sdk.llm.providers.requests.post", fake_post)
        provider = OpenAICompatibleProvider("k", "o3", "https://api.openai.com/v1")
        provider.converse("sys", [Turn("user", text="hi")])
        assert "max_completion_tokens" in sent[-1]

    def test_an_unrelated_400_is_raised_not_retried(self, monkeypatch):
        calls = []

        def fake_post(url, json=None, **kwargs):
            calls.append(json)
            return self._rejects("You exceeded your current quota.")

        monkeypatch.setattr("sdk.llm.providers.requests.post", fake_post)
        provider = OpenAICompatibleProvider("k", "gpt-4o", "https://api.openai.com/v1")
        with pytest.raises(LLMError) as exc:
            provider.complete("sys", [Message("user", "hi")])
        assert "quota" in str(exc.value)
        assert len(calls) == 1

    def test_a_bad_key_says_so_plainly(self, monkeypatch):
        monkeypatch.setattr("sdk.llm.providers.requests.post",
                            lambda *a, **k: FakeResponse(401, {"error": {
                                "message": "Incorrect API key provided"}}))
        provider = OpenAICompatibleProvider("bad", "gpt-4o",
                                            "https://api.openai.com/v1")
        with pytest.raises(LLMError) as exc:
            provider.complete("sys", [Message("user", "hi")])
        assert "rejected the API key" in str(exc.value)
        assert "epsilon ai login" in str(exc.value)
