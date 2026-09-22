"""Conversation-to-notebook integration and edit ownership boundaries."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from sdk.llm.base import AgentReply, ToolCall
from sdk.workbench import assistant
from tests.conftest import finished, settled
def provider_with(w, monkeypatch, tool_calls, during_call=None):
    captured = []
    def converse(system, history, tools, **kwargs):
        captured.append(copy.deepcopy({"system": system, "history": history, "tools": tools}))
        if len(captured) == 1:
            if during_call:
                during_call()
            return AgentReply(tool_calls=tool_calls)
        return AgentReply(text="The notebook is ready. Run the cell to see the result.")
    provider = Mock()
    provider.converse.side_effect = converse
    monkeypatch.setattr(w.bench, "provider", lambda: provider)
    monkeypatch.setattr(w.bench, "ai_status", lambda: {"configured": True})
    return captured


def write_call(source="answer = 42", cell_id=None, **extras):
    args = {"title": "Calculate an answer", "source": source, "kind": "code", **extras}
    if cell_id:
        args["cell_id"] = cell_id
    return ToolCall("write", "prepare_notebook_cell", args)


def test_conversation_and_notebook_links_persist_and_stay_in_project(workspace):
    w = workspace
    tid = w.browser.post(w.path + "/notebooks/main/conversation", json={}).json()["thread_id"]
    assert w.browser.post(w.path + "/notebooks/main/conversation", json={}).json()["thread_id"] == tid
    assert w.browser.post(w.path + "/threads/" + tid + "/notebook", json={}).json()["id"] == "main"
    other = w.bench.create_project("Other", w.tmp / "other", "")
    assert w.browser.post("/api/projects/" + other["id"] + "/threads/" + tid + "/notebook", json={}).status_code == 404
    second = w.bench.store.create_thread(w.pid)
    with pytest.raises(ValueError, match="another conversation"):
        w.bench.store.thread_notebook(w.pid, second["id"], "main")


def test_ai_prepares_code_for_explicit_addition_without_execution(workspace, monkeypatch):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "selected")
    w.bench.store.save_notebook(w.pid, "selected", [{"id": "researcher", "source": "private_note = 'MANUAL_PRIVATE_SOURCE'", "output": {"text": "RAW_OUTPUT"}}], 0)
    calls = [write_call("import pandas as pd\nframe = pd.read_csv('generated/data.csv')\nframe.groupby('patient.gender').size()"),
             write_call("## Method\n\nCount records by gender.", kind="markdown")]
    captured = provider_with(w, monkeypatch, calls)
    result = finished(w.bench, w.pid, w.browser.post(w.path + "/threads/" + tid + "/messages", json={"message": "Write a group summary and notes", "notebook_id": "selected"}).json())
    assert result["notebook_id"] == "selected"
    assert len(w.bench.store.notebook(w.pid, "selected")["cells"]) == 1
    drafts = w.bench.store.objects(w.pid, "draft", tid)
    assert all(d["message_id"] == w.bench.store.thread(w.pid, tid)["messages"][-1]["seq"] for d in drafts)
    for draft in reversed(drafts):
        applied = w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={})
        assert applied.status_code == 200
    book = w.browser.get(w.path + "/notebooks/selected").json()
    assert len(book["cells"]) == 3
    assert book["cells"][0]["source"].endswith("'MANUAL_PRIVATE_SOURCE'")
    assert book["cells"][1]["ai"]["can_undo"] and book["cells"][1]["output"] is None
    assert book["cells"][2]["kind"] == "markdown" and "<h2>Method</h2>" in book["cells"][2]["html"]
    assert not w.app.state.kernels.items and not w.bench.store.objects(w.pid, "artifact")
    assert "MANUAL_PRIVATE_SOURCE" not in repr(captured) and "RAW_OUTPUT" not in repr(captured)
    assert len(w.bench.store.objects(w.pid, "notebook_change")) == 2
    assert any(e["stage"] == "draft" for job in w.bench.jobs.jobs.values() for e in job.events)


def test_ai_can_refine_its_unchanged_cell_and_undo_restores_source(workspace, monkeypatch):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    first = w.bench.store.write_ai_cell(w.pid, "main", tid, "answer = 41", "Answer")
    captured = provider_with(w, monkeypatch, [write_call("answer = 42", first["cell_id"])])
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, tid, "Change it to 42", "main").payload())
    assert "answer = 41" in captured[0]["system"]
    assert w.bench.store.notebook(w.pid, "main")["cells"][0]["source"] == "answer = 41"
    draft = w.bench.store.objects(w.pid, "draft", tid)[0]
    assert draft["target_cell_id"] == first["cell_id"]
    assert w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={"mode": "replace"}).status_code == 200
    book = w.bench.store.notebook(w.pid, "main")
    assert len(book["cells"]) == 1 and book["cells"][0]["source"] == "answer = 42"
    cid = book["cells"][0]["ai"]["change_id"]
    restored = w.browser.post(w.path + "/notebooks/main/changes/" + cid + "/undo", json={}).json()
    assert restored["cells"][0]["source"] == "answer = 41"
    assert restored["cells"][0]["id"] == first["cell_id"]
    assert "applied" not in w.bench.store.get(w.pid, "draft", draft["id"])


def test_researcher_edit_during_model_request_is_preserved(workspace, monkeypatch):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    first = w.bench.store.write_ai_cell(w.pid, "main", tid, "answer = 41", "Answer")
    def edit():
        n = w.bench.store.notebook(w.pid, "main")
        n["cells"][0]["source"] = "answer = 'MANUAL_EDIT_MUST_SURVIVE'"
        w.bench.store.save_notebook(w.pid, "main", n["cells"], n["revision"])
    captured = provider_with(w, monkeypatch, [write_call("answer = 42", first["cell_id"])], edit)
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, tid, "Refine the code", "main").payload())
    draft = w.bench.store.objects(w.pid, "draft", tid)[0]
    response = w.browser.post(w.path + "/drafts/" + draft["id"] + "/apply", json={"mode": "replace"})
    assert response.status_code == 200 and response.json()["change"]["status"] == "added_after_edit"
    n = w.bench.store.notebook(w.pid, "main")
    assert [c["source"] for c in n["cells"]] == ["answer = 'MANUAL_EDIT_MUST_SURVIVE'", "answer = 42"]
    result = captured[1]["history"][-1].tool_results[0]
    assert "Awaiting" in json.loads(result.content)["status"]
    context, expected = assistant.notebook_context(w.bench, w.pid, "main")
    assert "MANUAL_EDIT_MUST_SURVIVE" not in repr(context)
    assert first["cell_id"] not in expected


@pytest.mark.parametrize("args", [
    {"notebook_id": "other"}, {"cell_id": "researcher-cell"},
    {"source": "import subprocess\nsubprocess.run(['whoami'])"},
    {"source": "import requests\nrequests.get('https://invalid.example')"},
    {"source": "def broken("}, {"kind": "javascript"},
])
def test_model_cannot_pick_another_notebook_or_bypass_source_checks(workspace, monkeypatch, args):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    captured = provider_with(w, monkeypatch, [write_call(**args)])
    job = settled(w.bench, w.pid, assistant.chat(w.bench, w.pid, tid, "Write a cell", "main").payload())
    assert job.status == ("failed" if args.get("source") == "def broken(" else "completed")
    assert captured[1]["history"][-1].tool_results[0].is_error
    assert w.bench.store.notebook(w.pid, "main")["revision"] == 0
    assert w.bench.store.objects(w.pid, "notebook_change") == []


def test_undo_does_not_overwrite_later_manual_edits_or_other_notebooks(workspace):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    change = w.bench.store.write_ai_cell(w.pid, "main", tid, "answer = 42", "Answer")
    path = w.path + "/notebooks/main"
    saved = w.browser.put(path, json={"revision": 1, "cells": [{"id": change["cell_id"], "source": "answer = 43"}]}).json()
    assert not saved["cells"][0]["ai"]["can_undo"]
    assert w.browser.post(path + "/changes/" + change["change_id"] + "/undo", json={}).status_code == 409
    assert w.browser.post(w.path + "/notebooks/other/changes/" + change["change_id"] + "/undo", json={}).status_code == 409
    assert w.bench.store.notebook(w.pid, "main")["cells"][0]["source"] == "answer = 43"
    forged = w.browser.put(path, json={"revision": 2, "cells": [{"id": "forged", "source": "secret = 1", "ai": {"digest": "fake"}}]})
    assert forged.status_code == 422


def test_concurrent_cell_appends_preserve_each_other(workspace):
    w = workspace
    tid = w.bench.store.notebook_thread(w.pid, "main")
    with ThreadPoolExecutor(max_workers=3) as pool:
        changes = list(pool.map(lambda i: w.bench.store.write_ai_cell(w.pid, "main", tid, "value = " + str(i), "Value"), range(3)))
    n = w.bench.store.notebook(w.pid, "main")
    assert len(n["cells"]) == 3 and len({c["cell_id"] for c in changes}) == 3
    assert {c["source"] for c in n["cells"]} == {"value = 0", "value = 1", "value = 2"}


def test_stable_cell_ids_keep_outputs_attached_to_their_source(workspace):
    w = workspace
    cells = [{"id": "a", "source": "1+1", "output": {"text": "2"}}, {"id": "b", "source": "2+2", "output": {"text": "4"}}]
    w.bench.store.save_notebook(w.pid, "main", cells, 0)
    result = w.browser.put(w.path + "/notebooks/main", json={"revision": 1, "cells": [{"id": "b", "source": "2+2"}, {"id": "a", "source": "1+1"}]}).json()
    assert [c["output"]["text"] for c in result["cells"]] == ["4", "2"]
