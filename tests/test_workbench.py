"""Behavioural checks for the browser's real workflows and trust boundaries."""
import copy
import io
import json
import os
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from sdk import credentials, llm
from sdk.client import APIClient
from sdk.epsilon_cli import app as cli
from sdk.errors import AuthenticationError, SDKError
from sdk.llm.base import AgentReply, ToolCall, Reply, LLMError
from sdk.workbench import analysis, assistant
from sdk.workbench.kernel import container_command
from sdk.workbench.security import safe_path
from sdk.workbench.store import Store
from tests.conftest import ARCHETYPE, _rows, finished, settled


def test_browser_unlock_origin_csrf_and_one_use(workspace):
    w = workspace
    with TestClient(w.app, base_url="http://127.0.0.1:8787") as stranger:
        assert stranger.get("/api/projects").status_code == 401
        assert stranger.get("/api/session").json() == {"unlocked": False}
        assert stranger.post("/api/bootstrap", json={"token": w.token}).status_code == 400
    assert w.browser.get("/api/projects", headers={"Host": "attacker.example"}).status_code == 403
    assert w.browser.get("/api/projects", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert w.browser.get("/api/projects", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert w.browser.post(w.path + "/threads", json={}, headers={"x-epsilon-csrf": "bad"}).status_code == 403
    assert w.browser.post(w.path + "/threads", content="title=x", headers={"content-type": "text/plain"}).status_code == 415
    assert w.browser.post(w.path + "/threads", content=b" " * 2100001, headers={"content-type": "application/json"}).status_code == 413
    assert "HttpOnly" in w.browser.post("/api/bootstrap", json={"token": "x" * 32}).headers.get("set-cookie", "") or all(c.has_nonstandard_attr("HttpOnly") for c in w.browser.cookies.jar)
    assert "frame-ancestors 'none'" in w.browser.get("/").headers["content-security-policy"]


def test_credentials_share_cli_format_without_password_or_key_in_response(workspace):
    w = workspace
    response = w.browser.post("/api/auth/login", json={"username": "researcher", "password": "fixture-password"})
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    w.hub.authenticate.assert_called_once_with("researcher", "fixture-password")
    assert APIClient.from_config(w.bench.credentials_path).access_token == w.hub.access_token
    assert w.bench.credentials_path.stat().st_mode & 0o777 == 0o600
    assert "fixture-password" not in w.bench.credentials_path.read_text()
    assert w.hub.access_token not in response.text
    assert "password" not in w.browser.get("/api/session").text
    invalid = w.browser.post("/api/auth/login", json={"username": "r", "password": "fixture-password", "extra": "oops"})
    assert invalid.status_code == 422 and "fixture-password" not in invalid.text
    w.hub.authenticate.side_effect = AuthenticationError("credential detail fixture-password")
    failed = w.browser.post("/api/auth/login", json={"username": "r", "password": "fixture-password"})
    assert failed.status_code == 401 and "fixture-password" not in failed.text
    assert w.browser.post("/api/auth/logout", json={}).json()["authenticated"] is False
    assert not w.bench.credentials_path.exists()


def test_existing_expired_and_percent_credentials(tmp_path):
    client = APIClient()
    client.access_token = "example%token"
    client.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    path = tmp_path / "credentials.ini"
    credentials.save_client(client, "scientist", path)
    assert credentials.status(path)["authenticated"]
    client.token_expires_at -= timedelta(hours=2)
    credentials.save_client(client, "scientist", path)
    assert credentials.status(path) == {"authenticated": False, "expired": True}


def test_real_project_initialisation_and_failed_download_retry(workspace):
    w = workspace
    cwd = os.getcwd()
    project = w.browser.post("/api/projects", json={"name": "New study", "path": str(w.tmp / "new-study")}).json()
    pid, path = project["id"], "/api/projects/" + project["id"]
    entry = Path(project["path"]) / "main.py"
    entry.write_text("# existing research\n")
    w.hub.download_synthetic_data.side_effect = SDKError("Download unavailable")
    failed = w.browser.post(path + "/initialise", json={"dataset_id": "ds-1"}).json()
    job = w.bench.jobs.get(pid, failed["id"])
    for _ in range(100):
        if job.status == "failed":
            break
        time.sleep(.01)
    assert job.status == "failed"
    assert not (entry.parent / "project.yml").exists()
    assert not list(entry.parent.glob(".epsilon-init-*"))
    def download(dataset_id, destination):
        Path(destination).write_text(_rows())
        return {"schema_hash": ARCHETYPE["syntheticData"]["schemaHash"], "version": 3}
    w.hub.download_synthetic_data.side_effect = download
    result = finished(w.bench, pid, w.browser.post(path + "/initialise", json={"dataset_id": "ds-1"}).json())
    assert result["project"]["dataset_version"] == 3
    assert w.browser.get(path).json()["ready"]
    assert entry.read_text() == "# existing research\n"
    assert os.getcwd() == cwd


@pytest.mark.parametrize("candidate", [
    {"analysis": "shell"}, {"analysis": "logistic"}, {"analysis": "survival"},
    {"analysis": "cross_tab", "fields": {"rows": "../../credentials.ini"}},
    {"analysis": "trend", "fields": {"time": "patient.age"}},
    {"analysis": "trend", "fields": {"bucket": "second"}},
])
def test_forged_plans_have_no_side_effects(workspace, candidate):
    w = workspace
    assert w.browser.post(w.path + "/plans", json=candidate).status_code == 400
    assert w.bench.store.threads(w.pid) == []
    assert w.bench.store.objects(w.pid, "plan") == []


@pytest.mark.parametrize("method", sorted(analysis.SUPPORTED))
def test_real_preview_is_reproducible_persistent_and_project_scoped(workspace, method):
    w = workspace
    # An editable generated module must never execute in the web process.
    marker = w.tmp / "host-executed"
    (w.root / "generated/models.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\nraise RuntimeError('untrusted')\n")
    response = w.browser.post(w.path + "/plans", json={"analysis": method})
    assert response.status_code == 200, response.text
    plan = response.json()
    artifact = finished(w.bench, w.pid, w.browser.post(w.path + "/plans/" + plan["id"] + "/run", json={}).json())
    assert not marker.exists()
    assert artifact["result"]["tables"]
    # Execute only source generated by our trusted implementation, in this
    # test, to prove the downloadable code reproduces the checked artifact.
    namespace = {"__name__": "reproduction_test"}
    exec(compile(artifact["code"], "preview.py", "exec"), namespace)
    assert namespace["main"](str(w.root / "generated/data.csv")) == artifact["result"]
    reopened = Store(w.bench.store.path).thread(w.pid, plan["thread_id"])
    assert reopened["artifacts"][0] == artifact
    other = w.bench.create_project("Another", w.tmp / "another", "")
    for suffix in ("/threads/" + plan["thread_id"], "/artifacts/" + artifact["id"]):
        assert w.browser.get("/api/projects/" + other["id"] + suffix).status_code == 404
    assert w.browser.post("/api/projects/" + other["id"] + "/plans/" + plan["id"] + "/run", json={}).status_code == 404
    package = w.browser.get(w.path + "/artifacts/" + artifact["id"] + "/export")
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert set(archive.namelist()) == {"analysis.py", "manifest.json", "README.txt"}
        assert archive.read("analysis.py").decode() == artifact["code"]
        assert json.loads(archive.read("manifest.json"))["tre_approval"] == "Not requested"


def test_suppression_removes_values_and_complementary_group():
    rows = [{"a": label, "b": "group"} for label, n in (("shown", 30), ("complement", 20), ("rare-secret-label", 3)) for _ in range(n)]
    output = analysis._compute(rows, {"analysis": "cross_tab", "fields": {"rows": "a", "cols": "b"}, "min_cell": 1})
    table = output["tables"][0]
    assert table["rows"] == [{"a": "shown", "b": "group", "records": 30}]
    assert table["chart"] == {"labels": ["shown / group"], "values": [30]}
    assert table["withheld_groups"] == 2 and output["min_cell"] == 10
    assert "rare-secret-label" not in json.dumps(output)
    assert "complement\"" not in json.dumps(output)
    assert analysis._compute([], {"analysis": "cross_tab", "fields": {"rows": "a", "cols": "b"}, "min_cell": 10})["tables"][0]["rows"] == []


def test_changed_inputs_and_symlinks_cannot_run(workspace):
    w = workspace
    plan = w.browser.post(w.path + "/plans", json={"analysis": "describe"}).json()
    data = w.root / "generated/data.csv"
    data.write_text(data.read_text() + "2100-03-04 11:00,URGENT,F,50,I123,10\n")
    with pytest.raises(SDKError, match="changed"):
        analysis.run_plan(w.root, plan)
    (w.root / "outside").symlink_to(w.tmp)
    with pytest.raises(SDKError, match="Symbolic"):
        safe_path(w.root, "outside/credentials.ini", must_exist=False)
    with pytest.raises(SDKError):
        safe_path(w.root, "../credentials.ini", must_exist=False)


def test_notebook_revisions_and_exports_never_trust_client_output(workspace):
    w = workspace
    path = w.path + "/notebooks/main"
    first = w.browser.put(path, json={"revision": 0, "cells": [{"source": "value = 41\n"}]}).json()
    assert first["revision"] == 1
    assert w.browser.put(path, json={"revision": 0, "cells": [{"source": "stale"}]}).status_code == 409
    assert w.browser.put(path, json={"revision": 1, "cells": [{"source": "x", "output": {"reviewed": True}}]}).status_code == 422
    w.bench.store.save_notebook(w.pid, "main", [{"source": "value = 41\n", "output": {"text": "RAW-NOTEBOOK-OUTPUT", "reviewed": False}}], 1)
    assert "RAW-NOTEBOOK-OUTPUT" in w.browser.get(path).text
    exported = w.browser.get(path + "/export").json()
    assert exported["cells"][0]["outputs"] == []
    assert "RAW-NOTEBOOK-OUTPUT" not in json.dumps(exported)
    changed = w.browser.put(path, json={"revision": 2, "cells": [{"source": "value = 42\n"}]}).json()
    assert changed["cells"][0]["output"] is None
    other = w.bench.create_project("Other notebook", w.tmp / "other-notebook", "")
    assert w.bench.store.notebook(other["id"], "main")["revision"] == 0


def test_assistant_only_receives_permitted_context_and_cannot_execute(workspace, monkeypatch):
    w = workspace
    thread = w.bench.store.create_thread(w.pid)
    w.bench.store.message(w.pid, thread["id"], "assistant", "LEGACY-OBSERVED-SECRET", shareable=False)
    w.bench.store.save_notebook(w.pid, "main", [{"source": "print('x')", "output": {"text": "RAW-NOTEBOOK-OUTPUT"}}], 0)
    calls = [ToolCall("schema", "read_dataset", {}), ToolCall("shell", "run", {"code": "print('unsafe')"}),
             ToolCall("plan", "propose_analysis", {"analysis": "cross_tab"}),
             ToolCall("bad-draft", "save_code_draft", {"title": "bad", "code": "import subprocess\nsubprocess.run(['whoami'])"}),
             ToolCall("draft", "save_code_draft", {"title": "Explore", "code": "import pandas as pd\nframe = pd.read_csv('generated/data.csv')\n"})]
    provider = Mock()
    captured = []
    def converse(system, history, tools, **kwargs):
        captured.append(copy.deepcopy({"system": system, "history": history, "tools": tools}))
        return AgentReply(tool_calls=calls) if len(captured) == 1 else AgentReply(text="Inspect the plan and source, then run a synthetic preview.")
    provider.converse.side_effect = converse
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": True})
    job = assistant.chat(w.bench, w.pid, thread["id"], "Compare recorded admission types by gender.")
    finished(w.bench, w.pid, job.payload())
    payload = repr(captured)
    for secret in ("RAW-NOTEBOOK-OUTPUT", "LEGACY-OBSERVED-SECRET", "EW EMER.", "SURGICAL SAME DAY ADMISSION", w.hub.access_token):
        assert secret not in payload
    assert {t.name for t in captured[0]["tools"]} == {"resolve_fields", "read_dataset", "list_analyses", "propose_analysis", "save_code_draft", "prepare_notebook_cell", "prepare_notebook_analysis"}
    results = captured[1]["history"][-1].tool_results
    assert next(r for r in results if r.call_id == "shell").is_error
    assert next(r for r in results if r.call_id == "bad-draft").is_error
    assert not w.bench.store.objects(w.pid, "artifact")
    assert len(w.bench.store.objects(w.pid, "plan")) == 1
    assert len(w.bench.store.objects(w.pid, "draft")) == 1
    resumed = assistant.chat(w.bench, w.pid, thread["id"], "What did we decide?")
    finished(w.bench, w.pid, resumed.payload())
    assert any(t.text == "Compare recorded admission types by gender." for t in captured[-1]["history"])


def test_secret_questions_and_no_model_recovery(workspace):
    w = workspace
    credentials.save_client(w.hub, "researcher", w.bench.credentials_path)
    thread = w.bench.store.create_thread(w.pid)
    path = w.path + "/threads/" + thread["id"] + "/messages"
    assert w.browser.post(path, json={"message": "My token is " + w.hub.access_token}).status_code == 400
    assert w.bench.store.thread(w.pid, thread["id"])["messages"] == []
    result = settled(w.bench, w.pid, w.browser.post(path, json={"message": "Explain my analysis options"}).json())
    assert result.status == "failed" and result.reason == "configuration"
    assert "Connect AI" in result.error
    assert len(w.bench.store.thread(w.pid, thread["id"])["messages"]) == 1


def test_tailored_suggestions_use_schema_and_drop_infeasible_proposals(workspace, monkeypatch):
    w = workspace
    provider = Mock()
    provider.complete.return_value = Reply(text="", tool_input={"suggestions": [
        {"analysis": "cross_tab", "fields": {"rows": "patient.gender", "cols": "admissions.type"}, "title": "Explore recorded admission patterns", "question": "How do record counts vary?"},
        {"analysis": "logistic", "fields": {}, "title": "Fit a patient model", "question": "Can we predict patient risk?"},
        {"analysis": "cross_tab", "fields": {"rows": "invented.field"}, "title": "Forged field", "question": "Use this field"},
    ]})
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    job = assistant.suggest(w.bench, w.pid)
    result = finished(w.bench, w.pid, job.payload())
    assert len(result["cards"]) == 1
    assert result["cards"][0]["source"] == "model"
    assert result["cards"][0]["analysis"] == "cross_tab"
    prompt = repr(provider.complete.call_args)
    assert "patient.gender" in prompt
    assert "EW EMER." not in prompt and "SURGICAL SAME DAY ADMISSION" not in prompt
    assert w.bench.store.threads(w.pid) == []
    card = result["cards"][0]
    response = w.browser.post(w.path + "/plans", json={"analysis": card["analysis"], "fields": card["fields"]})
    assert response.status_code == 200


def test_provider_http_error_never_reaches_progress_stream(workspace, monkeypatch):
    w = workspace
    provider = Mock()
    provider.complete.side_effect = LLMError("Provider body with fixture-private-credential")
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    job = assistant.suggest(w.bench, w.pid)
    deadline = time.monotonic() + 5
    while job.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(.01)
    assert job.status == "failed"
    assert "fixture-private-credential" not in json.dumps(job.payload())


def test_billing_failure_preserves_notebook_and_explains_credits(workspace, monkeypatch):
    from tests.test_llm import FakeResponse
    w = workspace
    monkeypatch.setattr(llm, "load", lambda: llm.AIConfig(provider="openai", model="gpt-4o", api_key="fixture-model-key"))
    monkeypatch.setattr("sdk.llm.providers.requests.post", lambda *a, **k: FakeResponse(429,
        {"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota", "message": "fixture-private-credential"}}))
    thread = w.bench.store.create_thread(w.pid, "Summarise data")
    before = w.bench.store.notebook(w.pid, "main")
    response = w.browser.post(w.path + "/threads/" + thread["id"] + "/messages",
                              json={"message": "Write a dataset summary cell", "notebook_id": "main"})
    assert response.status_code == 200
    result = settled(w.bench, w.pid, response.json())
    assert result.status == "failed" and "no API credits remaining" in result.error
    assert "fixture-private-credential" not in json.dumps(result.payload())
    assert w.bench.store.notebook(w.pid, "main") == before
    assert [m["role"] for m in w.bench.store.thread(w.pid, thread["id"])["messages"]] == ["user"]
    job = assistant.suggest(w.bench, w.pid)
    deadline = time.monotonic() + 5
    while job.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(.01)
    assert job.status == "failed" and "no API credits remaining" in job.error
    assert "fixture-private-credential" not in json.dumps(job.payload())


@pytest.mark.parametrize("reason", ["credits", "quota", "authentication", "timeout", None])
def test_connection_check_explains_failure_without_provider_body(workspace, monkeypatch, reason):
    w = workspace
    provider = Mock()
    provider.converse.side_effect = LLMError("fixture-private-credential", reason=reason)
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": True})
    response = w.browser.post("/api/settings/ai/test", json={})
    assert response.status_code == 200 and response.json()["connected"] is False
    assert response.json()["message"] == LLMError("", reason=reason).public_message
    assert "fixture-private" not in response.text
    assert w.bench.store.threads(w.pid) == []


def test_connection_check_sends_no_research_context_and_never_executes_tools(workspace, monkeypatch):
    w = workspace
    provider = Mock()
    provider.converse.return_value = AgentReply(text="fixture-private-response", tool_calls=[
        ToolCall("c1", "write_notebook_cell", {"title": "must not be saved", "kind": "code", "source": "print(42)"})])
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": True})
    before = w.bench.store.notebook(w.pid, "main")
    response = w.browser.post("/api/settings/ai/test", json={})
    assert response.status_code == 200 and response.json()["connected"] is True
    assert "fixture-private" not in response.text
    sent = provider.converse.call_args
    assert sent.args[1][0].text == "Connection check"
    assert "patient.gender" not in repr(sent) and w.root.name not in repr(sent)
    assert sent.kwargs["max_tokens"] == 64
    assert w.bench.store.notebook(w.pid, "main") == before
    assert w.bench.store.threads(w.pid) == []
    assert w.app.state.kernels.items == {}


def test_connection_check_requires_configuration_session_and_csrf(workspace, monkeypatch):
    w = workspace
    provider = Mock()
    monkeypatch.setattr(w.bench, "provider", provider)
    result = w.browser.post("/api/settings/ai/test", json={})
    assert result.status_code == 200 and result.json()["connected"] is False
    assert "Save an AI connection" in result.json()["message"]
    assert w.browser.post("/api/settings/ai/test", json={}, headers={"x-epsilon-csrf": "bad"}).status_code == 403
    assert w.browser.post("/api/settings/ai/test", json={"message": "private"}).status_code == 422
    with TestClient(w.app, base_url="http://127.0.0.1:8787") as stranger:
        assert stranger.post("/api/settings/ai/test", json={}).status_code == 401
    provider.assert_not_called()


def test_container_constraints_and_missing_runtime(workspace, monkeypatch):
    argv = container_command("docker", "epsilon-test", "/tmp/snapshot", "sha256:fixture")
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory=1g", "--user=65532:65532", "--pids-limit=128", "--pull=never"):
        assert flag in argv
    assert not {"--privileged", "-p", "--env", "-e"} & set(argv)
    assert "docker.sock" not in " ".join(argv)
    w = workspace
    monkeypatch.setattr("sdk.workbench.api.runtime_status", lambda: {"available": False, "reason": "Docker unavailable"})
    response = w.browser.post(w.path + "/notebooks/main/execute", json={"revision": 0, "cell": 0})
    assert response.status_code == 400 and "Docker unavailable" in response.text
    assert w.app.state.kernels.items == {}


def test_cli_starts_the_workbench(monkeypatch):
    server = Mock()
    launch = Mock(return_value=(server, "http://127.0.0.1:8787/#launch=fixture"))
    monkeypatch.setattr("sdk.workbench.server.available", lambda: True)
    monkeypatch.setattr("sdk.workbench.server.serve", launch)
    result = CliRunner().invoke(cli, ["start", "--no-browser", "--no-record"])
    assert result.exit_code == 0, result.output
    launch.assert_called_once_with(".", 7878, open_browser=False, record=False)
    server.run.assert_called_once()
    # The Chainlit interface was removed; the flag must not linger.
    assert "--legacy-chat" not in CliRunner().invoke(cli, ["start", "--help"]).output


def test_import_is_read_only_idempotent_and_not_model_context(workspace):
    w = workspace
    legacy = w.bench.state_dir / "chat.db"
    with sqlite3.connect(legacy) as db:
        db.executescript('CREATE TABLE threads (id TEXT, name TEXT, "userIdentifier" TEXT); CREATE TABLE steps ("threadId" TEXT, "createdAt" TEXT, type TEXT, output TEXT, input TEXT);')
        db.execute("INSERT INTO threads VALUES (?,?,?)", ("old", "Older study", "project:" + w.pid))
        db.execute("INSERT INTO threads VALUES (?,?,?)", ("elsewhere", "Private other project", "project:elsewhere"))
        db.execute("INSERT INTO steps VALUES (?,?,?,?,?)", ("old", "2026-01-01", "assistant_message", "Observed historic text", ""))
    original = legacy.read_bytes()
    assert w.browser.post(w.path + "/history/import", json={}).json()["imported"] == 1
    assert w.browser.post(w.path + "/history/import", json={}).json()["imported"] == 0
    assert legacy.read_bytes() == original
    threads = w.bench.store.threads(w.pid)
    assert len(threads) == 1
    assert w.bench.store.thread(w.pid, threads[0]["id"])["messages"][0]["shareable"] == 0


def test_ai_key_never_saved_in_database_or_reused_for_another_endpoint(workspace, monkeypatch):
    w = workspace
    monkeypatch.setattr(llm.config, "keyring_backend", lambda: None)
    key = "fixture-model-secret-123456789"
    settings = {"provider": "openai-compatible", "model": "institution-model", "base_url": "http://127.0.0.1:11434/v1", "api_key": key}
    response = w.browser.post("/api/settings/ai", json=settings)
    assert response.status_code == 200 and key not in response.text
    assert key not in w.bench.store.path.read_bytes().decode("latin1")
    assert key not in json.dumps(w.bench.store.setting("ai"))
    assert w.bench.ai_config().api_key == key
    settings.update(base_url="https://another.example/v1", api_key="")
    assert w.browser.post("/api/settings/ai", json=settings).status_code == 200
    assert w.bench.ai_config().api_key is None
    for url in ("http://remote.example/v1", "https://user:pass@example.test/v1", "https://example.test/v1?key=foo"):
        settings["base_url"] = url
        assert w.browser.post("/api/settings/ai", json=settings).status_code == 400


@pytest.mark.skipif(os.environ.get("EPSILON_TEST_NOTEBOOK") != "1", reason="Set EPSILON_TEST_NOTEBOOK=1 with the Docker notebook image built")
def test_real_isolated_jupyter_state_outputs_and_stop(dataset_dir, tmp_path, monkeypatch):
    from sdk.workbench.kernel import Kernels
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-host-key-must-not-reach-kernel")
    kernels = Kernels(tmp_path / "state")
    try:
        kernel = kernels.get("research", "main", dataset_dir)
        assert not kernel.execute("answer = 41")["error"]
        assert kernel.execute("print(answer + 1)")["text"].strip() == "42"
        output = kernel.execute("import os, socket\nfrom pathlib import Path\nprint('NO_KEY', 'ANTHROPIC_API_KEY' not in os.environ)\nprint('READABLE', Path('generated/data.csv').exists())\ntry:\n Path('generated/data.csv').write_text('replace')\nexcept OSError:\n print('READ_ONLY')\ntry:\n socket.create_connection(('1.1.1.1', 443), timeout=1)\nexcept OSError:\n print('NO_NETWORK')\n")
        for value in ("NO_KEY True", "READABLE True", "READ_ONLY", "NO_NETWORK"):
            assert value in output["text"], output
        assert output["reviewed"] is False
        png = kernel.execute("import matplotlib.pyplot as plt\nplt.plot([1,2,3]); plt.show()")
        assert png["images"] and not png["error"], png
        assert png["execution_count"] == 4
        rich = kernel.execute("import pandas as pd\nfrom IPython.display import display, Markdown, JSON, HTML, clear_output\nprint('before', flush=True)\ndisplay(pd.DataFrame({'age':[30,40], 'count':[12,18]}))\ndisplay(Markdown('## Notebook result'))\ndisplay(JSON({'nested': [1,2]}))\nprint('after', flush=True)")
        blocks = rich["display"]["blocks"]
        assert [b["kind"] for b in blocks] == ["text", "html", "html", "json", "text"], rich
        assert "<table" in blocks[1]["html"] and "<h2>Notebook result</h2>" in blocks[2]["html"]
        assert blocks[3]["value"] == {"nested": [1, 2]} and rich["execution_count"] == 5
        assert not rich["reviewed"]
        last = kernel.execute("pd.DataFrame({'value': [42]})")
        assert last["display"]["blocks"][0]["kind"] == "html", last
        cleared = kernel.execute("print('discarded', flush=True)\nclear_output(wait=True)\ndisplay(Markdown('**Kept**'))")
        assert len(cleared["display"]["blocks"]) == 1 and "Kept" in cleared["display"]["blocks"][0]["html"], cleared
        initial = kernel.execute("handle = display(HTML('<b>Initial</b>'), display_id=True)")
        updated = kernel.execute("handle.update(HTML('<i>Updated</i><script>BAD</script><img src=\"https://invalid.example\">'))")
        assert updated["display"]["blocks"] == []
        assert updated["display"]["updates"][0]["display_id"] == initial["display"]["blocks"][0]["display_id"]
        assert updated["display"]["updates"][0]["html"] == "<i>Updated</i>"
        kernels.stop("research", "main")
        assert not kernels.items
        fresh = kernels.get("research", "main", dataset_dir)
        assert "NameError" in fresh.execute("print(answer)")["text"]
    finally:
        kernels.close()
