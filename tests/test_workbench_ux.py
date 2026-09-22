"""Research navigation includes durable work without exposing its contents."""


def test_recent_work_ignores_empty_conversations(workspace):
    w = workspace
    w.bench.store.create_thread(w.pid, "Empty conversation")
    w.bench.store.notebook_thread(w.pid, "main")
    assert w.browser.get(w.path + "/work").json() == {"work": []}


def test_recent_work_includes_manual_notebook_without_a_preview(workspace):
    w = workspace
    w.bench.store.save_notebook(w.pid, "my-notes", [{"source": "manual_private_source", "output": {"text": "private_output"}}], 0)
    result = w.browser.get(w.path + "/work")
    assert result.status_code == 200
    item = result.json()["work"][0]
    assert item["kind"] == "notebook" and item["notebook_id"] == "my-notes"
    assert item["thread_id"] is None and item["result_count"] == 0
    assert "manual_private_source" not in result.text and "private_output" not in result.text


def test_recent_work_groups_related_results_and_resumes_latest_notebook(workspace):
    w = workspace
    store = w.bench.store
    thread = store.create_thread(w.pid, "Age summary")
    store.message(w.pid, thread["id"], "user", "private_question")
    artifact = store.put(w.pid, "artifact", {"title": "Summary", "code": "private_code", "result": {"value": "private_result"}}, thread["id"])
    # An older imported artifact notebook is recognised before its first chat.
    store.save_notebook(w.pid, artifact["id"], [{"source": "older source", "output": None}], 0)
    item = w.browser.get(w.path + "/work").json()["work"][0]
    assert item["notebook_id"] == artifact["id"] and item["thread_id"] == thread["id"]
    store.thread_notebook(w.pid, thread["id"], "latest")
    store.save_notebook(w.pid, "latest", [{"source": "newer_private_source", "output": None}], 0)
    response = w.browser.get(w.path + "/work")
    assert len(response.json()["work"]) == 1
    item = response.json()["work"][0]
    assert item["title"] == "Age summary" and item["notebook_id"] == "latest"
    assert item["artifact_id"] == artifact["id"] and item["result_count"] == 1
    assert "private_" not in response.text


def test_recent_work_order_tracks_notebook_edits_and_conversation_updates(workspace):
    w = workspace
    store = w.bench.store
    book = store.save_notebook(w.pid, "main", [{"source": "answer = 1", "output": None}], 0)
    thread = store.create_thread(w.pid, "A later question")
    store.message(w.pid, thread["id"], "user", "hello")
    assert store.recent_work(w.pid)[0]["thread_id"] == thread["id"]
    store.save_notebook(w.pid, "main", [{"source": "answer = 2", "output": None}], book["revision"])
    assert store.recent_work(w.pid)[0]["notebook_id"] == "main"


def test_recent_work_is_project_scoped_and_requires_browser_session(workspace):
    from fastapi.testclient import TestClient
    w = workspace
    other = w.bench.create_project("Other study", str(w.tmp / "other-study"), "")
    thread = w.bench.store.create_thread(other["id"], "Private other work")
    w.bench.store.message(other["id"], thread["id"], "user", "other private question")
    assert w.browser.get(w.path + "/work").json() == {"work": []}
    assert len(w.browser.get("/api/projects/" + other["id"] + "/work").json()["work"]) == 1
    assert w.browser.get("/api/projects/not-registered/work").status_code == 404
    with TestClient(w.app, base_url="http://127.0.0.1:8787") as stranger:
        assert stranger.get(w.path + "/work").status_code == 401
