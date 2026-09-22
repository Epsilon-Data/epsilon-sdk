"""Explicit code placement, retry safety and plain-chat code suggestions."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from sdk.llm.base import AgentReply
from sdk.workbench import assistant
from sdk.workbench.store import cell_digest
from tests.conftest import finished
from tests.test_workbench_workspace import write_call


def suggestion(w, source="answer = 42", target=None):
    tid = w.bench.store.notebook_thread(w.pid, "main")
    expected = {target["id"]: cell_digest(target)} if target else None
    return assistant.prepare_cell(w.bench, w.pid, tid, "main", source, "Answer", cell_id=target["id"] if target else None, expected=expected)


def test_repeated_and_concurrent_add_requests_create_only_one_cell(workspace):
    w = workspace
    draft = suggestion(w)
    def apply(_):
        return w.bench.store.write_ai_cell(w.pid, "main", draft["thread_id"], draft["code"], draft["title"], draft_id=draft["id"])
    with ThreadPoolExecutor(max_workers=3) as pool:
        changes = list(pool.map(apply, range(3)))
    assert len({item["cell_id"] for item in changes}) == 1
    assert len(w.bench.store.notebook(w.pid, "main")["cells"]) == 1
    response = w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={})
    assert response.status_code == 200 and response.json()["change"]["already_applied"] is True
    assert response.json()["notebook"]["revision"] == 1
    assert w.app.state.kernels.items == {}


def test_add_as_new_cell_keeps_the_original_even_for_a_refinement(workspace):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    w.bench.store.write_ai_cell(w.pid, "main", tid, "answer = 41", "Original")
    original = w.bench.store.notebook(w.pid, "main")["cells"][0]
    draft = suggestion(w, target=original)
    response = w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={"mode": "append"})
    assert response.status_code == 200
    cells = response.json()["notebook"]["cells"]
    assert [c["source"] for c in cells] == ["answer = 41", "answer = 42"]
    assert cells[0]["id"] == original["id"] and cells[1]["id"] != original["id"]


def test_pending_code_is_available_for_followups_without_sharing_notebook_edits(workspace):
    w = workspace
    draft = suggestion(w)
    w.bench.store.save_notebook(w.pid, "main", [{"source": "private_manual_source", "output": {"text": "private_notebook_output"}}], 0)
    context = assistant.pending_code_context(w.bench, w.pid, draft["thread_id"], "main")
    assert context[0]["source"] == "answer = 42"
    assert "private_" not in repr(context)
    assert assistant.pending_code_context(w.bench, w.pid, draft["thread_id"], "another-notebook") == []
    other = w.bench.store.create_thread(w.pid, "Other")
    assert assistant.pending_code_context(w.bench, w.pid, other["id"], "main") == []
    assert w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={}).status_code == 200
    assert assistant.pending_code_context(w.bench, w.pid, draft["thread_id"], "main") == []


def test_plain_fenced_python_becomes_an_addable_card_without_changing_notebook(workspace, monkeypatch):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    provider = Mock()
    provider.converse.return_value = AgentReply(text="Here is the code:\n```python\nanswer = 42\nprint(answer)\n```\nRun it when ready.")
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": True})
    result = finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, tid, "Write code", "main").payload())
    draft = w.bench.store.objects(w.pid, "draft", tid)[0]
    assert "print(answer)" in draft["code"] and "```" not in result["reply"]
    assert draft["message_id"] == w.bench.store.thread(w.pid, tid)["messages"][-1]["seq"]
    assert w.bench.store.notebook(w.pid, "main")["revision"] == 0
    assert w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={}).status_code == 200
    assert not w.app.state.kernels.items


def test_repeated_code_in_tool_reply_and_fence_produces_one_card(workspace, monkeypatch):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    provider = Mock()
    provider.converse.side_effect = [AgentReply(tool_calls=[write_call()]), AgentReply(text="```python\nanswer = 42\n```\n")]
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": True})
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, tid, "Write code", "main").payload())
    assert len(w.bench.store.objects(w.pid, "draft", tid)) == 1


def test_legacy_code_drafts_can_be_added_to_their_conversation_notebook(workspace):
    w = workspace
    thread = w.bench.store.create_thread(w.pid, "Earlier work")
    draft = w.bench.store.put(w.pid, "draft", {"title": "Legacy source", "code": "answer = 42"}, thread["id"])
    response = w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={})
    assert response.status_code == 200
    assert response.json()["notebook"]["id"] == thread["id"]


def test_apply_requires_the_stored_target_and_does_not_accept_arbitrary_source(workspace):
    w = workspace
    draft = suggestion(w)
    path = w.path + "/drafts/" + draft["id"] + "/apply"
    assert w.browser.post(path, json={"mode": "replace"}).status_code == 400
    assert w.browser.post(path, json={"mode": "append", "source": "injected", "notebook_id": "other"}).status_code == 422
    assert w.browser.post(path, json={}, headers={"x-epsilon-csrf": "invalid"}).status_code == 403
    other = w.bench.create_project("Other", w.tmp / "other", "")
    assert w.browser.post("/api/projects/" + other["id"] + "/drafts/" + draft["id"] + "/apply", json={}).status_code == 404
    assert w.bench.store.notebook(w.pid, "main")["revision"] == 0


@pytest.mark.parametrize("source", ["import subprocess\nsubprocess.run(['whoami'])", "def invalid("])
def test_apply_rechecks_saved_source_before_adding_a_cell(workspace, source):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    draft = w.bench.store.put(w.pid, "draft", {"title": "Code", "code": source, "kind": "code", "notebook_id": "main"}, tid)
    assert w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={}).status_code == 400
    assert w.bench.store.notebook(w.pid, "main")["revision"] == 0


def test_undo_reopens_the_suggestion_for_an_explicit_new_application(workspace):
    w = workspace
    draft = suggestion(w)
    path = w.path + "/drafts/" + draft["id"] + "/apply"
    first = w.browser.post(path, json={}).json()["change"]
    undo = w.browser.post(w.path + "/notebooks/main/changes/" + first["change_id"] + "/undo", json={})
    assert undo.status_code == 200
    pending = w.bench.store.get(w.pid, "draft", draft["id"])
    assert "applied" not in pending and "cell_id" not in pending
    second = w.browser.post(path, json={}).json()["change"]
    assert second["change_id"] != first["change_id"]
