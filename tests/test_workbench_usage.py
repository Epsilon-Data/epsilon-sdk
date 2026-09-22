"""Token accounting, model choice and column suggestions."""
from unittest.mock import Mock

import pytest

from sdk.llm import pricing
from sdk.llm.base import AgentReply, LLMError, Metered, ToolCall, Turn, Usage
from sdk.llm.providers import AnthropicProvider, OpenAICompatibleProvider
from sdk.workbench import assistant, fields
from tests.conftest import finished, settled

CONNECTION = {"configured": True, "provider": "anthropic", "model": "claude-sonnet-5", "base_url": "", "source": "workspace"}


def response(status, body):
    reply = Mock(status_code=status, text=str(body))
    reply.json.return_value = body
    return reply


def scripted(bench, monkeypatch, *replies, connection=CONNECTION):
    provider, seen = Mock(), []
    queue = list(replies)

    def converse(system, history, tools, **kwargs):
        seen.append({"system": system, "history": list(history)})
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    provider.converse.side_effect = converse
    monkeypatch.setattr(bench, "provider", lambda: provider)
    monkeypatch.setattr(bench, "ai_status", lambda: dict(connection))
    return seen


# -- providers and prices ---------------------------------------------------

def test_both_backends_report_disjoint_token_counters(monkeypatch):
    anthropic = response(200, {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                               "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900,
                                         "cache_creation_input_tokens": 50}})
    monkeypatch.setattr("sdk.llm.providers.requests.post", lambda *a, **k: anthropic)
    usage = AnthropicProvider("key", "claude-sonnet-5").converse("", [Turn("user", text="hi")]).usage
    assert usage == Usage(100, 20, 900, 50) and usage.total_tokens == 1070

    openai = response(200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 1000, "completion_tokens": 30,
                                      "prompt_tokens_details": {"cached_tokens": 600}}})
    monkeypatch.setattr("sdk.llm.providers.requests.post", lambda *a, **k: openai)
    usage = OpenAICompatibleProvider("key", "gpt-4o", "https://api.openai.com/v1").converse("", [Turn("user", text="hi")]).usage
    # OpenAI counts cached tokens inside prompt_tokens; they must not be billed twice.
    assert usage == Usage(400, 30, 600, 0)

    silent = response(200, {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": "many"}})
    monkeypatch.setattr("sdk.llm.providers.requests.post", lambda *a, **k: silent)
    assert OpenAICompatibleProvider(None, "local", "http://localhost:11434/v1").converse("", [Turn("user", text="hi")]).usage == Usage()


def test_anthropic_drops_temperature_once_a_model_refuses_it(monkeypatch):
    sent = []
    def post(url, json, **kwargs):
        sent.append(json)
        if "temperature" in json:
            return response(400, {"error": {"type": "invalid_request_error", "message": "temperature is not supported for this model"}})
        return response(200, {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1}})
    monkeypatch.setattr("sdk.llm.providers.requests.post", post)
    provider = AnthropicProvider("key", "claude-opus-5")
    assert provider.converse("", [Turn("user", text="hi")]).text == "ok"
    provider.converse("", [Turn("user", text="again")])
    assert ["temperature" in body for body in sent] == [True, False, False]


def test_model_lists_come_from_the_provider_and_skip_non_chat_models(monkeypatch):
    listing = response(200, {"data": [{"id": "gpt-4o"}, {"id": "text-embedding-3-large"}, {"id": "gpt-4o-audio-preview"},
                                     {"id": "o3"}, {"id": 7}, {"id": "x" * 200}]})
    monkeypatch.setattr("sdk.llm.providers.requests.get", lambda *a, **k: listing)
    assert [m["id"] for m in OpenAICompatibleProvider("k", "gpt-4o", "https://api.openai.com/v1").list_models()] == ["gpt-4o", "o3"]
    # A self-hosted endpoint names its models however it likes.
    assert len(OpenAICompatibleProvider(None, "m", "http://localhost:8000/v1").list_models()) == 4
    claude = response(200, {"data": [{"id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"}]})
    monkeypatch.setattr("sdk.llm.providers.requests.get", lambda *a, **k: claude)
    assert AnthropicProvider("k", "claude-sonnet-5").list_models() == [{"id": "claude-sonnet-5", "label": "Claude Sonnet 5"}]


def test_costs_are_estimates_and_never_guessed():
    million = Usage(1_000_000, 1_000_000, 1_000_000, 1_000_000)
    sonnet = pricing.rates("anthropic", "claude-sonnet-5")
    assert pricing.cost(million, sonnet) == pytest.approx(2 + 10 + 0.2 + 2.5)
    # Dated snapshots price as their family; the longest prefix wins.
    assert pricing.rates("anthropic", "claude-haiku-4-5-20251001")["input"] == 1.0
    assert pricing.rates("openai", "gpt-4o-mini-2024-07-18")["input"] == 0.15
    assert pricing.rates("openai", "gpt-5-mini")["output"] == 2.0
    # The same model name behind an institution endpoint says nothing about its price.
    assert pricing.rates("openai-compatible", "claude-sonnet-5") is None
    assert pricing.rates("anthropic", "claude-unreleased") is None
    assert pricing.cost(million, None) is None
    own = pricing.rates("openai-compatible", "llama-70b", {"llama-70b": {"input": 0.5, "output": 1.5}})
    assert own["source"] == "custom" and pricing.cost(Usage(2_000_000, 1_000_000), own) == pytest.approx(2.5)
    assert pricing.rates("anthropic", "claude-sonnet-5", {"claude-sonnet-5": {"input": True, "output": -1}})["input"] == 2.0


def test_meter_counts_every_call_and_tolerates_silent_backends():
    inner = Mock()
    inner.converse.side_effect = [AgentReply(text="a", usage=Usage(10, 2)), AgentReply(text="b"), AgentReply(text="c", usage=Usage(5, 1))]
    meter = Metered(inner)
    meter.timeout = 7
    for _ in range(3):
        meter.converse("", [])
    assert (meter.usage, meter.calls, inner.timeout) == (Usage(15, 3), 3, 7)


# -- accounting through the assistant --------------------------------------

def test_each_reply_shows_its_tokens_with_workspace_and_project_totals(workspace, monkeypatch):
    w = workspace
    thread = w.bench.store.create_thread(w.pid)
    scripted(w.bench, monkeypatch,
             AgentReply(tool_calls=[ToolCall("schema", "read_dataset", {})], usage=Usage(1000, 50)),
             AgentReply(text="Your dataset has admissions and patients.", usage=Usage(1200, 150, 300)),
             AgentReply(text="Second answer.", usage=Usage(500, 100)))
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, thread["id"], "What is in my dataset?").payload())
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, thread["id"], "And then?").payload())
    other = w.bench.store.create_thread(w.pid)
    scripted(w.bench, monkeypatch, AgentReply(text="Elsewhere.", usage=Usage(40, 10)),
             connection=dict(CONNECTION, provider="openai-compatible", model="llama-70b"))
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, other["id"], "Another workspace").payload())

    shown = w.browser.get(w.path + "/threads/" + thread["id"]).json()
    first, second = [m["usage"] for m in shown["messages"] if m["role"] == "assistant"]
    assert all(m["usage"] is None for m in shown["messages"] if m["role"] == "user")
    # Both model calls behind one prompt are reported under that prompt.
    assert (first["input_tokens"], first["output_tokens"], first["cache_read_tokens"], first["calls"]) == (2200, 200, 300, 2)
    assert first["cost"] == pytest.approx((2200 * 2 + 200 * 10 + 300 * 0.2) / 1e6)
    assert first["models"][0]["model"] == "claude-sonnet-5"
    assert second["total_tokens"] == 600
    assert shown["usage"]["total_tokens"] == 2700 + 600 and shown["usage"]["requests"] == 2

    project = w.browser.get(w.path).json()["usage"]
    assert project["total_tokens"] == 3300 + 50 and project["requests"] == 3
    # One request had no known rates: the total stays honest about that.
    assert project["unpriced"] == 1 and project["cost"] == pytest.approx(shown["usage"]["cost"])
    report = w.browser.get("/api/usage").json()
    assert report["total"]["total_tokens"] == 3350 and report["projects"][0]["usage"]["requests"] == 3
    assert {m["model"] for m in report["total"]["models"]} == {"claude-sonnet-5", "llama-70b"}


def test_a_failed_request_still_records_what_it_spent(workspace, monkeypatch):
    w = workspace
    thread = w.bench.store.create_thread(w.pid)
    scripted(w.bench, monkeypatch, AgentReply(tool_calls=[ToolCall("s", "read_dataset", {})], usage=Usage(800, 40)),
             LLMError("no credit", reason="credits"))
    job = settled(w.bench, w.pid, assistant.chat(w.bench, w.pid, thread["id"], "Describe the data").payload())
    assert job.status == "failed"
    assert w.bench.store.usage(w.pid)["total_tokens"] == 840
    # Nothing is recorded when no model was reached at all.
    monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": False})
    settled(w.bench, w.pid, assistant.chat(w.bench, w.pid, w.bench.store.create_thread(w.pid)["id"], "Hello").payload())
    assert w.bench.store.usage(w.pid)["requests"] == 1


def test_custom_rates_apply_to_new_requests_only(workspace, monkeypatch):
    w = workspace
    assert w.browser.post("/api/settings/ai/price", json={"model": "llama-70b", "input": 1, "output": None}).status_code == 400
    assert w.browser.post("/api/settings/ai/price", json={"model": "llama-70b", "input": -1, "output": 1}).status_code == 422
    local = dict(CONNECTION, provider="openai-compatible", model="llama-70b")
    for expected in (None, pytest.approx(0.0025)):
        thread = w.bench.store.create_thread(w.pid)
        scripted(w.bench, monkeypatch, AgentReply(text="ok", usage=Usage(2000, 1000)), connection=local)
        finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, thread["id"], "Question").payload())
        assert w.bench.store.usage(w.pid, thread["id"])["cost"] == expected
        monkeypatch.undo()
        w.bench.notebook_runtime = lambda *_: {"available": False, "inventory_verified": False, "packages": []}
        assert w.browser.post("/api/settings/ai/price", json={"model": "llama-70b", "input": 0.5, "output": 1.5}).status_code == 200
    assert w.browser.post("/api/settings/ai/price", json={"model": "llama-70b"}).status_code == 200
    assert w.bench.store.setting("ai_prices") == {}


# -- model choice -----------------------------------------------------------

def test_changing_model_keeps_the_connection_and_its_key(workspace, monkeypatch):
    w = workspace
    assert w.browser.post("/api/settings/ai/model", json={"model": "claude-opus-5"}).status_code == 400  # nothing connected
    saved = w.browser.post("/api/settings/ai", json={"provider": "anthropic", "model": "claude-sonnet-5", "api_key": "workspace-key-1234567890"}).json()
    assert saved["model"] == "claude-sonnet-5" and saved["rates"]["input"] == 2.0
    changed = w.browser.post("/api/settings/ai/model", json={"model": "claude-opus-5"}).json()
    assert changed["model"] == "claude-opus-5" and changed["configured"] and changed["rates"]["input"] == 5.0
    config = w.bench.ai_config()
    assert (config.model, config.api_key) == ("claude-opus-5", "workspace-key-1234567890")
    assert "workspace-key" not in w.browser.get("/api/settings/ai").text
    # The Settings form may change only the model without re-entering the key.
    again = w.browser.post("/api/settings/ai", json={"provider": "anthropic", "model": "claude-haiku-4-5"})
    assert again.status_code == 200 and w.bench.ai_config().api_key == "workspace-key-1234567890"
    assert w.bench.ai_config().model == "claude-haiku-4-5"
    # A different provider is a different connection: it needs its own key and forgets the choice.
    assert w.browser.post("/api/settings/ai", json={"provider": "openai", "model": "gpt-4o"}).status_code == 400
    w.browser.post("/api/settings/ai", json={"provider": "openai", "model": "gpt-4o", "api_key": "another-key-1234567890"})
    assert w.bench.ai_config().model == "gpt-4o"
    assert w.browser.post("/api/settings/ai/model", json={"model": "bad\nname"}).status_code == 400


def test_model_list_falls_back_to_suggestions_and_is_cached(workspace, monkeypatch):
    w = workspace
    assert w.browser.get("/api/settings/ai/models").json()["source"] == "none"
    w.browser.post("/api/settings/ai", json={"provider": "anthropic", "model": "claude-custom-1", "api_key": "workspace-key-1234567890"})
    calls = []
    def listing(self):
        calls.append(1)
        if len(calls) == 1:
            raise LLMError("down", reason="connection")
        return [{"id": "claude-sonnet-5", "label": "Claude Sonnet 5"}]
    monkeypatch.setattr(AnthropicProvider, "list_models", listing)
    offered = w.browser.get("/api/settings/ai/models").json()
    assert offered["source"] == "suggested" and offered["models"][0]["id"] == "claude-custom-1"
    assert offered["models"][0]["rates"] is None and offered["models"][1]["rates"]["input"] == 2.0
    w.browser.get("/api/settings/ai/models")
    assert len(calls) == 1
    live = w.browser.get("/api/settings/ai/models?refresh=true").json()
    assert live["source"] == "provider" and [m["id"] for m in live["models"]] == ["claude-custom-1", "claude-sonnet-5"]


# -- column names -----------------------------------------------------------

SCHEMA = [{"path": p, "type": "categorical"} for p in (
    "demographics.gender", "demographics.age_years", "demographics.ethnic_group", "clinical.bmi",
    "clinical.diabetes_status", "clinical.systolic_bp", "lifestyle.smoking_status", "visit.visit_date")]


@pytest.mark.parametrize("term,expected", [
    ("sex", "demographics.gender"), ("patient_age", "demographics.age_years"), ("etnicity", "demographics.ethnic_group"),
    ("body mass index", "clinical.bmi"), ("diabetic outcome", "clinical.diabetes_status"),
    ("blood pressure", "clinical.systolic_bp"), ("smokng status", "lifestyle.smoking_status"),
    ("visit_dt", "visit.visit_date")])
def test_everyday_words_find_the_real_column_first(term, expected):
    match = fields.resolve(term, SCHEMA)
    assert match["exact"] is None and match["candidates"][0]["path"] == expected


@pytest.mark.parametrize("term", ["genotype", "cholesterol", "postcode", "genome_score", "xyz"])
def test_absent_columns_get_no_invented_match(term):
    assert fields.resolve(term, SCHEMA) == {"term": term, "exact": None, "candidates": []}


def test_exact_names_need_no_confirmation():
    assert fields.resolve("clinical.bmi", SCHEMA)["exact"] == "clinical.bmi"
    assert fields.resolve("BMI", SCHEMA)["exact"] == "clinical.bmi"
    # The same words in another spelling name the column outright.
    assert fields.resolve("date of visit", SCHEMA)["exact"] == "visit.visit_date"
    assert fields.resolve("Smoking Status", SCHEMA)["exact"] == "lifestyle.smoking_status"
    ambiguous = SCHEMA + [{"path": "baseline.bmi", "type": "number"}]
    assert fields.resolve("bmi", ambiguous)["exact"] is None
    assert {c["path"] for c in fields.resolve("bmi", ambiguous)["candidates"]} == {"clinical.bmi", "baseline.bmi"}


def test_only_words_written_like_columns_are_prescanned():
    question = "Plot `patient_sex` by admissions.type with plt.show() from generated/data.csv, then a \"bar chart\""
    assert fields.identifier_terms(question) == ["patient_sex", "admissions.type", "plt.show", "data.csv", "bar chart"]


def test_the_researcher_chooses_the_column_not_the_model(workspace, monkeypatch):
    w = workspace
    thread = w.bench.store.create_thread(w.pid)
    code = "import pandas as pd\nframe = pd.read_csv('generated/data.csv')\nframe['patient.gender'].value_counts()\n"
    seen = scripted(w.bench, monkeypatch,
                    AgentReply(tool_calls=[ToolCall("r", "resolve_fields", {"terms": ["sex", "genotype", "admissions.type"]}),
                                           ToolCall("c", "prepare_notebook_cell", {"title": "Counts", "source": code, "kind": "code"})]),
                    AgentReply(text="Did you mean patient.gender? There is no genotype column."))
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, thread["id"], "Count records by sex and genotype").payload())
    resolved, refused = seen[1]["history"][-1].tool_results
    assert '"exact": "admissions.type"' in resolved.content and "patient.gender" in resolved.content
    assert refused.is_error and "not confirmed" in refused.content
    assert not w.bench.store.objects(w.pid, "draft")
    shown = w.browser.get(w.path + "/threads/" + thread["id"]).json()["messages"][-1]
    assert shown["meta"]["missing_fields"] == ["genotype"]
    choice = shown["meta"]["field_choices"][0]
    assert choice["term"] == "sex" and choice["candidates"][0]["path"] == "patient.gender"

    # Picking a suggestion teaches the project that word; an invented path is refused.
    path = w.path + "/threads/" + thread["id"] + "/messages"
    assert w.browser.post(path, json={"message": "Use it", "field_choice": {"term": "sex", "path": "invented.column"}}).status_code == 400
    seen = scripted(w.bench, monkeypatch,
                    AgentReply(tool_calls=[ToolCall("r", "resolve_fields", {"terms": ["Sex"]}),
                                           ToolCall("c", "prepare_notebook_cell", {"title": "Counts", "source": code, "kind": "code"})]),
                    AgentReply(text="Your code is ready."))
    answer = w.browser.post(path, json={"message": 'Use patient.gender for "sex".', "field_choice": {"term": "sex", "path": "patient.gender"}})
    finished(w.bench, w.pid, answer.json())
    assert '"vocabulary": {"sex": "patient.gender"}' in seen[0]["system"]
    resolved, prepared = seen[1]["history"][-1].tool_results
    assert '"confirmed_by_researcher": true' in resolved.content and not prepared.is_error
    assert len(w.bench.store.objects(w.pid, "draft")) == 1
    assert w.browser.get(w.path + "/threads/" + thread["id"]).json()["messages"][-1]["meta"] is None
    assert w.browser.get(w.path + "/vocabulary").json() == {"vocabulary": {"sex": "patient.gender"}}
    assert w.browser.post(w.path + "/vocabulary/forget", json={"term": "SEX"}).json() == {"vocabulary": {}}


def test_column_like_words_in_the_question_are_checked_before_the_model_answers(workspace, monkeypatch):
    w = workspace
    thread = w.bench.store.create_thread(w.pid)
    seen = scripted(w.bench, monkeypatch, AgentReply(text="Which column did you mean?"))
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, thread["id"], "Chart patient_sex against `adm_type`, not patient_gender").payload())
    assert '"term": "patient_sex"' in seen[0]["system"] and '"term": "patient_gender"' not in seen[0]["system"]
    meta = w.bench.store.thread(w.pid, thread["id"])["messages"][-1]["meta"]
    assert [(c["term"], c["candidates"][0]["path"]) for c in meta["field_choices"]] == [
        ("patient_sex", "patient.gender"), ("adm_type", "admissions.type")]


def test_unknown_columns_in_code_name_the_closest_real_ones(workspace):
    w = workspace
    runtime = {"available": False, "inventory_verified": False, "packages": [{"module": "pandas"}]}
    source = "import pandas as pd\nframe = pd.read_csv('generated/data.csv')\nframe.groupby('patient_gender').size()\nframe['sex'].value_counts()\nframe['genotype']\n"
    issues = assistant.code_feedback(w.bench, w.pid, source, "code", runtime, [])
    assert [(i["field"], i["closest"]) for i in issues] == [
        ("patient_gender", ["patient.gender"]), ("sex", ["patient.gender"]), ("genotype", [])]


# -- text values from the generated wrapper ---------------------------------

WRAPPER = "import pandas as pd\nfrom generated.models import create_dataset\ndata = pd.DataFrame(create_dataset().records)\n"
RUNTIME = {"available": False, "inventory_verified": False, "packages": [{"module": "pandas"}]}


@pytest.mark.parametrize("body", [
    "data.groupby('patient.gender')['patient.age'].median()\n",          # raises TypeError when run
    "data['patient.age'].max()\n",                                        # silently compares strings
    "older = data[data['patient.age'] > 65]\n",
    "subset = data[data['patient.gender'] == 'F']\nsubset['patient.age'].mean()\n"])
def test_maths_on_text_values_from_the_wrapper_is_caught_before_the_researcher_sees_it(body):
    from sdk.workbench.code_checks import check_code
    issues = check_code(WRAPPER + body, ["patient.age", "patient.gender"], RUNTIME, (), ["patient.age"])["issues"]
    assert [(i["code"], i["field"]) for i in issues] == [("text_values", "patient.age")]
    assert "pd.to_numeric" in issues[0]["message"]


@pytest.mark.parametrize("source", [
    WRAPPER + "data['patient.age'] = pd.to_numeric(data['patient.age'], errors='coerce')\ndata.groupby('patient.gender')['patient.age'].median()\n",
    WRAPPER + "ages = pd.to_numeric(data['patient.age'], errors='coerce')\nages.median()\n",
    WRAPPER + "pd.to_numeric(data['patient.age'], errors='coerce').max()\n",
    WRAPPER + "data['patient.gender'].value_counts().max()\n",
    "import pandas as pd\nframe = pd.read_csv('generated/data.csv')\nframe['patient.age'].median()\n"])
def test_converted_or_typed_values_are_not_flagged(source):
    from sdk.workbench.code_checks import check_code
    assert check_code(source, ["patient.age", "patient.gender"], RUNTIME, (), ["patient.age"])["issues"] == []


def test_the_assistant_must_correct_unconverted_maths_before_finishing(workspace, monkeypatch):
    w = workspace
    thread = w.bench.store.create_thread(w.pid)
    wrong = WRAPPER + "data.groupby('patient.gender')['patient.age'].median()\n"
    right = WRAPPER + "data['patient.age'] = pd.to_numeric(data['patient.age'], errors='coerce')\ndata.groupby('patient.gender')['patient.age'].median()\n"
    seen = scripted(w.bench, monkeypatch,
                    AgentReply(tool_calls=[ToolCall("a", "prepare_notebook_cell", {"title": "Median age", "source": wrong, "kind": "code"})]),
                    AgentReply(tool_calls=[ToolCall("b", "prepare_notebook_cell", {"title": "Median age", "source": right, "kind": "code"})]),
                    AgentReply(text="Your code is ready."))
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, thread["id"], "Median patient.age by patient.gender").payload())
    assert "VALUE TYPES" in seen[0]["system"] and "EVERY value is text" in seen[0]["system"]
    refused = seen[1]["history"][-1].tool_results[0]
    assert refused.is_error and "text_values" in refused.content and "patient.age" in refused.content
    [draft] = w.bench.store.objects(w.pid, "draft")
    assert draft["code"] == right
    assert not [i for i in draft["checks"]["issues"] if i["code"] == "text_values"]



def test_list_prices_apply_only_on_the_providers_own_endpoints():
    assert pricing.rates("openai", "gpt-4o", None, "https://api.openai.com/v1/")["input"] == 2.5
    assert pricing.rates("anthropic", "claude-sonnet-5", None, "https://api.anthropic.com")["input"] == 2.0
    # A gateway or institution proxy speaking the same API sets its own price.
    assert pricing.rates("openai", "gpt-4o", None, "https://gateway.university.example/v1") is None
    assert pricing.rates("anthropic", "claude-sonnet-5", None, "https://claude-proxy.example") is None
    own = {"gpt-4o": {"input": 1, "output": 2}}
    assert pricing.rates("openai", "gpt-4o", own, "https://gateway.university.example/v1")["source"] == "custom"


@pytest.mark.parametrize("body", [ValueError("not json"), ["a", "list"], "plain text"])
def test_a_successful_response_that_is_not_a_json_object_is_a_provider_error(monkeypatch, body):
    reply = Mock(status_code=200, text="<html>proxy login</html>")
    if isinstance(body, Exception):
        reply.json.side_effect = body
    else:
        reply.json.return_value = body
    monkeypatch.setattr("sdk.llm.providers.requests.post", lambda *a, **k: reply)
    monkeypatch.setattr("sdk.llm.providers.requests.get", lambda *a, **k: reply)
    for provider in (AnthropicProvider("k", "claude-sonnet-5"), OpenAICompatibleProvider("k", "gpt-4o", "https://api.openai.com/v1")):
        with pytest.raises(LLMError) as raised:
            provider.converse("", [Turn("user", text="hi")])
        assert raised.value.reason == "request"
        with pytest.raises(LLMError):
            provider.list_models()


def test_model_list_falls_back_when_the_provider_answers_with_a_web_page(workspace, monkeypatch):
    w = workspace
    w.browser.post("/api/settings/ai", json={"provider": "anthropic", "model": "claude-sonnet-5", "api_key": "workspace-key-1234567890"})
    page = Mock(status_code=200, text="<html>")
    page.json.side_effect = ValueError("not json")
    monkeypatch.setattr("sdk.llm.providers.requests.get", lambda *a, **k: page)
    response = w.browser.get("/api/settings/ai/models?refresh=true")
    assert response.status_code == 200 and response.json()["source"] == "suggested"
