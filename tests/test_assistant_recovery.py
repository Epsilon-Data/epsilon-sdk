"""Request outcomes, retries, reviewed context and generated-code regressions."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from sdk.llm.base import AgentReply, ToolCall, LLMError
from sdk.workbench import assistant
from sdk.workbench.jobs import Jobs
from sdk.workbench.errors import Conflict
from sdk.workbench.store import Store

from tests.test_workbench_repairs import RUNTIME


def settle(w, payload):
    job = w.bench.jobs.get(w.pid, payload["id"])
    deadline = time.monotonic() + 8
    while job.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(.01)
    assert job.status not in ("queued", "running"), job.payload()
    # Wait for the same terminal state to reach durable storage.
    while w.bench.store.saved_job(w.pid, job.id)["status"] != job.status and time.monotonic() < deadline:
        time.sleep(.01)
    return job


def setup_model(w, monkeypatch, responses):
    provider = Mock()
    provider.converse.side_effect = responses
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": True, "provider": "fixture", "model": "fixture-model"})
    monkeypatch.setattr(w.bench, "notebook_runtime", lambda *_: RUNTIME)
    tid = w.bench.store.notebook_thread(w.pid, "main")
    return provider, tid, w.path + "/threads/" + tid


def code(source="answer = 42"):
    return AgentReply(tool_calls=[ToolCall("code", "prepare_notebook_cell", {"source": source, "kind": "code", "title": "Answer"})])


def send(w, path, **body):
    response = w.browser.post(path + "/messages", json={"message": "Write code", "notebook_id": "main", "request_id": "request-1", **body})
    assert response.status_code == 200, response.text
    return settle(w, response.json())


def test_failed_request_retries_in_place_without_duplicate_question_or_draft(workspace, monkeypatch):
    w = workspace
    provider, tid, path = setup_model(w, monkeypatch, [code(), LLMError("SECRET_PROVIDER_BODY", reason="quota")])
    first = send(w, path)
    assert first.status == "failed" and first.reason == "quota"
    assert "SECRET_PROVIDER_BODY" not in json.dumps(first.payload())
    assert [m["role"] for m in w.bench.store.thread(w.pid, tid)["messages"]] == ["user"]
    assert len(w.bench.store.objects(w.pid, "draft", tid)) == 1
    provider.converse.side_effect = [code(), AgentReply(text="Review the code, then add it to your notebook.")]
    result = w.browser.post(path + "/requests/request-1/retry", json={})
    assert result.status_code == 200
    final = settle(w, result.json())
    assert final.id == first.id and final.attempt == 2 and final.status == "completed"
    assert [m["role"] for m in w.bench.store.thread(w.pid, tid)["messages"]] == ["user", "assistant"]
    assert len(w.bench.store.objects(w.pid, "draft", tid)) == 1
    assert w.bench.store.notebook(w.pid, "main")["revision"] == 0
    assert not w.app.state.kernels.items


@pytest.mark.parametrize("reason", ["quota", "credits", "authentication", "permission", "request"])
def test_non_transient_failures_do_not_repeat_provider_calls(workspace, monkeypatch, reason):
    w = workspace
    provider, _, path = setup_model(w, monkeypatch, [LLMError("private", reason=reason)])
    job = send(w, path)
    assert job.status == "failed" and job.reason == reason
    assert provider.converse.call_count == 1


@pytest.mark.parametrize("reason", ["timeout", "connection", "rate_limit", "unavailable"])
def test_transient_retry_preserves_the_one_question(workspace, monkeypatch, reason):
    w = workspace
    provider, tid, path = setup_model(w, monkeypatch, [LLMError("private", reason=reason), AgentReply(text="Hello")])
    job = send(w, path)
    assert job.status == "completed" and provider.converse.call_count == 2
    assert len(w.bench.store.thread(w.pid, tid)["messages"]) == 2
    assert any(e["stage"] == "retrying" for e in job.events)


def test_transient_retries_are_bounded(workspace, monkeypatch):
    w = workspace
    provider, _, path = setup_model(w, monkeypatch, [LLMError("private", reason="timeout")] * 3)
    assert send(w, path).status == "failed"
    assert provider.converse.call_count == 3


def test_replayed_post_is_idempotent_and_foreign_request_ids_are_rejected(workspace, monkeypatch):
    w = workspace
    provider, tid, path = setup_model(w, monkeypatch, [AgentReply(text="Hello")])
    first = send(w, path)
    second = send(w, path)
    assert first.id == second.id and provider.converse.call_count == 1
    assert len(w.bench.store.thread(w.pid, tid)["messages"]) == 2
    other = w.bench.store.create_thread(w.pid)
    response = w.browser.post(w.path + "/threads/" + other["id"] + "/messages", json={"message": "Other", "request_id": "request-1"})
    assert response.status_code == 409
    assert w.bench.store.saved_job(w.pid, first.id)["scope"] == w.pid + ":thread:" + tid


def test_repeated_concurrent_requests_queue_one_model_call(workspace, monkeypatch):
    w = workspace
    entered, release = Event(), Event()
    def response(*_a, **_kw):
        entered.set()
        assert release.wait(3)
        return AgentReply(text="Done")
    provider, tid, _ = setup_model(w, monkeypatch, response)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = list(pool.map(lambda _: assistant.chat(w.bench, w.pid, tid, "Hello", "main", request_id="same"), range(3)))
        assert entered.wait(1)
        assert len({job.id for job in jobs}) == 1
    finally:
        release.set()
    assert settle(w, jobs[0].payload()).status == "completed"
    assert provider.converse.call_count == 1


def test_saved_failed_request_is_retryable_after_service_restart(workspace, monkeypatch):
    w = workspace
    provider, tid, path = setup_model(w, monkeypatch, [LLMError("private", reason="quota")])
    first = send(w, path)
    w.bench.jobs.close()
    w.bench.jobs = Jobs(Store(w.bench.store.path))
    assert w.bench.jobs.get(w.pid, first.id).status == "failed"
    assert w.browser.get(path).json()["requests"][0]["status"] == "failed"
    provider.converse.side_effect = [AgentReply(text="Recovered")]
    job = settle(w, w.browser.post(path + "/requests/request-1/retry", json={}).json())
    assert job.status == "completed" and job.attempt == 2
    assert len(w.bench.store.thread(w.pid, tid)["messages"]) == 2


def test_dead_process_jobs_become_interrupted_without_reexecution(workspace, monkeypatch):
    w = workspace
    _, tid, path = setup_model(w, monkeypatch, [AgentReply(text="Done")])
    job = send(w, path)
    saved = w.bench.store.saved_job(w.pid, job.id)
    saved.update(status="running", owner_pid=123456789)
    w.bench.store.save_job(saved)
    monkeypatch.setattr("sdk.workbench.jobs.owner_alive", lambda _pid: False)
    restored = Jobs(w.bench.store)
    try:
        assert restored.get(w.pid, job.id).status == "interrupted"
        assert not restored.active(w.pid)
    finally:
        restored.close()


def job_outcome(manager, job):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        value = manager.get(job.project_id, job.id).payload()
        if value["status"] not in ("queued", "running"):
            return value
        time.sleep(.01)
    pytest.fail("Task did not reach a terminal outcome")


def test_cancel_and_retry_from_another_server_refresh_the_original_server(tmp_path):
    store = Store(tmp_path / "jobs.db")
    first, second = Jobs(store), Jobs(store)
    entered, release = Event(), Event()

    def operation(job):
        entered.set()
        assert release.wait(3)
        job.check_cancelled()
        pytest.fail("A remotely cancelled request must not continue")

    metadata = {"request": {"question": "Hello", "thread_id": "thread", "notebook_id": "main"}}
    try:
        job = first.submit("project", "chat", "project:thread:thread", operation, request_id="request", metadata=metadata)
        assert entered.wait(1)
        assert second.cancel("project", job.id)
        release.set()
        assert job_outcome(first, job)["status"] == "cancelled"
        retry = second.submit("project", "chat", job.scope, lambda _: {"reply": "Recovered"}, request_id=job.id, metadata=metadata, retry=True)
        assert job_outcome(second, retry)["status"] == "completed"
        observed = first.get("project", job.id).payload()
        assert observed["attempt"] == 2 and observed["result"]["reply"] == "Recovered"
        assert not observed["cancel_requested"]
    finally:
        release.set()
        first.close()
        second.close()


def test_stopped_worker_cannot_overwrite_a_new_retry(tmp_path):
    store = Store(tmp_path / "jobs.db")
    first, second = Jobs(store), Jobs(store)
    entered, release = Event(), Event()

    def blocked_provider(_job):
        entered.set()
        assert release.wait(3)
        raise LLMError("Late response from a stopped provider", reason="timeout")

    metadata = {"request": {"question": "Hello"}}
    try:
        old = first.submit("project", "chat", "project:thread:thread", blocked_provider, request_id="request", metadata=metadata)
        assert entered.wait(1)
        first.close()
        retry = second.submit("project", "chat", old.scope, lambda _: {"reply": "Recovered"}, request_id=old.id, metadata=metadata, retry=True)
        assert job_outcome(second, retry)["status"] == "completed"
        release.set()
        first.executor.shutdown(wait=True)
        saved = store.saved_job("project", old.id)
        assert saved["attempt"] == 2 and saved["status"] == "completed"
        assert saved["result"]["reply"] == "Recovered"
    finally:
        release.set()
        first.close()
        second.close()


def test_a_racing_claim_cannot_reexecute_an_already_completed_request(tmp_path):
    store = Store(tmp_path / "jobs.db")
    manager = Jobs(store)
    try:
        job = manager.submit("project", "chat", "scope", lambda _: "Done", request_id="request")
        assert job_outcome(manager, job)["status"] == "completed"
        snapshot = dict(store.saved_job("project", job.id), status="queued", owner="other-server")
        with pytest.raises(Conflict, match="already been accepted"):
            store.save_job(snapshot, claim=True)
        assert store.saved_job("project", job.id)["status"] == "completed"
    finally:
        manager.close()


def test_retry_cannot_reorder_questions_in_a_conversation(workspace, monkeypatch):
    w = workspace
    _, _, path = setup_model(w, monkeypatch, [LLMError("private", reason="quota"), AgentReply(text="New answer")])
    send(w, path)
    send(w, path, request_id="request-2", message="A newer question")
    assert w.browser.post(path + "/requests/request-1/retry", json={}).status_code == 409


def selected_cell(w):
    w.bench.store.save_notebook(w.pid, "main", [
        {"id": "selected", "kind": "code", "source": "manual_value = 7", "output": {"text": "PRIVATE_OUTPUT"}},
        {"id": "other", "kind": "code", "source": "other_private_source = 1", "output": None}], 0)
    path = w.path + "/notebooks/main/cells/selected/context-preview"
    review = w.browser.post(path, json={})
    assert review.status_code == 200
    return {"cell_id": "selected", "context_digest": review.json()["context_digest"], "confirmed": True}


def test_selected_source_is_shared_once_and_no_outputs_or_other_cells_leave(workspace, monkeypatch):
    w = workspace
    provider, tid, path = setup_model(w, monkeypatch, [code("manual_value = 8"), AgentReply(text="Review the change")])
    chosen = selected_cell(w)
    provider.converse.assert_not_called()
    assert send(w, path, selected_cell=chosen).status == "completed"
    wire = repr(provider.converse.call_args_list)
    assert "manual_value = 7" in wire
    assert "PRIVATE_OUTPUT" not in wire and "other_private_source" not in wire
    draft = w.bench.store.objects(w.pid, "draft", tid)[0]
    assert draft["target_cell_id"] == "selected" and not draft["shareable"]
    assert all(not m["shareable"] for m in w.bench.store.thread(w.pid, tid)["messages"])
    provider.reset_mock()
    provider.converse.side_effect = [AgentReply(text="Hello")]
    send(w, path, request_id="request-2", message="Hello")
    assert "manual_value" not in repr(provider.converse.call_args_list)


@pytest.mark.parametrize("change", ["source", "connection"])
def test_changed_selected_source_or_destination_needs_new_consent(workspace, monkeypatch, change):
    w = workspace
    provider, _, path = setup_model(w, monkeypatch, [AgentReply(text="Hello")])
    chosen = selected_cell(w)
    if change == "source":
        book = w.bench.store.notebook(w.pid, "main")
        book["cells"][0]["source"] = "changed = 2"
        w.bench.store.save_notebook(w.pid, "main", book["cells"], book["revision"])
    else:
        monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": True, "provider": "another"})
    response = w.browser.post(path + "/messages", json={"message": "Explain", "notebook_id": "main", "selected_cell": chosen})
    assert response.status_code == 400
    provider.converse.assert_not_called()


def test_retrying_selected_source_requires_review_again(workspace, monkeypatch):
    w = workspace
    provider, _, path = setup_model(w, monkeypatch, [LLMError("private", reason="quota")])
    chosen = selected_cell(w)
    assert send(w, path, selected_cell=chosen).status == "failed"
    assert w.browser.post(path + "/requests/request-1/retry", json={}).status_code == 400
    provider.converse.side_effect = [AgentReply(text="Explained")]
    response = w.browser.post(path + "/requests/request-1/retry", json={"selected_cell": chosen})
    assert response.status_code == 200 and settle(w, response.json()).status == "completed"


def test_static_feedback_corrects_missing_library_before_a_card_is_saved(workspace, monkeypatch):
    w = workspace
    provider, tid, path = setup_model(w, monkeypatch, [code("import seaborn"), code("import matplotlib.pyplot as plt"), AgentReply(text="Review this code")])
    assert send(w, path).status == "completed"
    drafts = w.bench.store.objects(w.pid, "draft", tid)
    assert len(drafts) == 1 and drafts[0]["code"] == "import matplotlib.pyplot as plt"
    assert "missing_library" in repr(provider.converse.call_args_list)
    assert not w.app.state.kernels.items


def test_correction_attempts_are_bounded_and_unfixed_draft_keeps_its_warning(workspace, monkeypatch):
    w = workspace
    provider, tid, path = setup_model(w, monkeypatch, [code("import seaborn")] * 3 + [AgentReply(text="Review the library warning")])
    assert send(w, path).status == "completed"
    drafts = w.bench.store.objects(w.pid, "draft", tid)
    assert len(drafts) == 1 and drafts[0]["checks"]["issues"][0]["code"] == "missing_library"
    assert provider.converse.call_count == 4


def test_claiming_a_fix_without_corrected_code_is_not_a_success(workspace, monkeypatch):
    w = workspace
    _, tid, path = setup_model(w, monkeypatch, [code("import seaborn"), AgentReply(text="I fixed it")])
    job = send(w, path)
    assert job.status == "failed" and job.reason == "code_checks"
    assert not w.bench.store.objects(w.pid, "draft", tid)


def test_research_goal_survives_long_conversations_and_cannot_cross_projects(workspace, monkeypatch):
    w = workspace
    provider, tid, path = setup_model(w, monkeypatch, [AgentReply(text="Use your chosen variable")])
    response = w.browser.put(w.path + "/research-context", json={"goal": "Investigate adult age distribution", "fields": ["patient.age"]})
    assert response.status_code == 200
    for i in range(24):
        w.bench.store.message(w.pid, tid, "user" if i % 2 == 0 else "assistant", f"Earlier exchange {i}")
    assert send(w, path).status == "completed"
    assert "Investigate adult age distribution" in provider.converse.call_args.args[0]
    other = w.bench.create_project("Other", w.tmp / "other", "")
    assert w.browser.get("/api/projects/" + other["id"] + "/research-context").json() == {"goal": "", "fields": []}
    assert w.browser.put(w.path + "/research-context", json={"goal": "Secret", "fields": ["invented.column"]}).status_code == 400


def test_refresh_launch_requires_cli_capability_and_preserves_active_session(workspace):
    w = workspace
    sessions = w.app.state.local_sessions
    assert w.browser.post('/api/launch', json={'token': 'incorrect-token-123456789'}).status_code == 400
    control = sessions.launch_control
    assert control not in w.browser.get('/api/session').text
    first = w.browser.post('/api/launch', json={'token': control})
    assert first.status_code == 200
    second = w.browser.post('/api/launch', json={'token': control})
    assert second.json()['token'] != first.json()['token']
    assert w.browser.post('/api/bootstrap', json={'token': first.json()['token']}).status_code == 400
    assert w.browser.get(w.path).status_code == 200
    assert w.browser.post('/api/launch', json={'token': control}, headers={'Origin': 'https://attacker.example'}).status_code == 403


def test_cli_launch_capability_file_is_private_and_unsafe_files_are_ignored(workspace, monkeypatch):
    from sdk.workbench import server
    w = workspace
    server.remember_server(w.app, 8787)
    path = w.bench.state_dir / 'servers/8787.json'
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    value = json.loads(path.read_text())
    assert value['control'] == w.app.state.local_sessions.launch_control
    path.chmod(0o644)
    assert server.existing_launch_url(8787, w.bench.state_dir) is None
    path.unlink()
    path.symlink_to(w.bench.store.path)
    assert server.existing_launch_url(8787, w.bench.state_dir) is None


@pytest.mark.parametrize('analysis,fields,chart', [
    ('describe', {'field': 'patient.age'}, 'line'),
    ('describe', {'field': 'patient.gender'}, 'pie'),
    ('describe', {'field': 'patient.age'}, 'bar'),
    ('cross_tab', {'rows': 'patient.gender', 'cols': 'admissions.type'}, 'bar'),
    ('trend', {'time': 'admissions.time'}, 'line'),
])
def test_template_tool_prepares_checked_code_without_running_or_saving_notebook(workspace, monkeypatch, analysis, fields, chart):
    w = workspace
    call = ToolCall('template', 'prepare_notebook_analysis', {'analysis': analysis, 'fields': fields, 'chart': chart})
    _, tid, path = setup_model(w, monkeypatch, [AgentReply(tool_calls=[call]), AgentReply(text='Review the notebook code')])
    job = send(w, path)
    assert job.status == 'completed'
    drafts = w.bench.store.objects(w.pid, 'draft', tid)
    assert len(drafts) == 1
    assert 'min_cell = 10' in drafts[0]['code']
    assert 'SPEC =' not in drafts[0]['code'] and '_compute' not in drafts[0]['code']
    assert w.bench.store.notebook(w.pid, 'main')['revision'] == 0
    assert not w.app.state.kernels.items


def test_template_tool_rejects_line_over_unordered_categories(workspace, monkeypatch):
    w = workspace
    call = ToolCall('template', 'prepare_notebook_analysis', {'analysis': 'describe', 'fields': {'field': 'patient.gender'}, 'chart': 'line'})
    provider, tid, path = setup_model(w, monkeypatch, [AgentReply(tool_calls=[call]), AgentReply(text='Use a bar chart for categories')])
    assert send(w, path).status == 'completed'
    assert not w.bench.store.objects(w.pid, 'draft', tid)
    assert provider.converse.call_args.args[1][-1].text == 'Use a bar chart for categories' or any(t.tool_results and t.tool_results[0].is_error for t in provider.converse.call_args.args[1])


def test_template_does_not_silently_choose_a_default_field(workspace, monkeypatch):
    w = workspace
    empty = ToolCall('missing', 'prepare_notebook_analysis', {'analysis': 'describe', 'fields': {}, 'chart': 'pie'})
    corrected = ToolCall('chosen', 'prepare_notebook_analysis', {'analysis': 'describe', 'fields': {'field': 'patient.gender'}, 'chart': 'pie'})
    provider, tid, path = setup_model(w, monkeypatch, [AgentReply(tool_calls=[empty]), AgentReply(tool_calls=[corrected]), AgentReply(text='Review the gender chart')])
    assert send(w, path).status == 'completed'
    drafts = w.bench.store.objects(w.pid, 'draft', tid)
    assert len(drafts) == 1 and "field = 'patient.gender'" in drafts[0]['code']
    assert any(result.is_error and 'Explicit field bindings' in result.content
               for turn in provider.converse.call_args.args[1] for result in turn.tool_results)
