"""Starting points prepare editable code without persistent clutter."""
import pytest

@pytest.mark.parametrize("method", ["describe", "composition", "cross_tab", "trend"])
def test_starter_is_readable_and_has_no_durable_side_effects(workspace, method):
    w = workspace
    card = next(c for c in w.browser.get(w.path + "/cards").json()["cards"] if c["analysis"] == method)
    response = w.browser.post(w.path + "/starters", json={"analysis": method, "fields": card["fields"]})
    assert response.status_code == 200
    notebook = response.json()
    assert notebook["temporary"] and notebook["revision"] == 0
    assert notebook["fields"] == card["fields"]
    assert all(len(cell["source"].splitlines()) < 40 and not cell.get("output") for cell in notebook["cells"])
    code = "\n".join(cell["source"] for cell in notebook["cells"])
    assert "import pandas as pd" in code and "SPEC = " not in code and "def _compute" not in code
    assert all(value in code for value in card["fields"].values())
    assert not w.bench.store.threads(w.pid) and not w.bench.store.recent_work(w.pid)
    assert not w.bench.store.objects(w.pid, "plan")
    assert w.browser.get(w.path + "/notebooks").json()["notebooks"] == []
    assert not w.bench.jobs.jobs and not w.app.state.kernels.items


def test_starter_uses_generated_wrapper_without_importing_it_on_host(workspace):
    w = workspace
    marker = w.tmp / "host-imported"
    (w.root / "generated/models.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()")
    notebook = w.browser.post(w.path + "/starters", json={"analysis": "describe"}).json()
    assert "from generated.models import create_dataset" in notebook["cells"][1]["source"]
    assert "pd.DataFrame(dataset.records)" in notebook["cells"][1]["source"]
    assert not marker.exists()


@pytest.mark.parametrize("candidate", [
    {"analysis": "logistic"}, {"analysis": "shell"},
    {"analysis": "describe", "fields": {"field": "__class__"}},
    {"analysis": "cross_tab", "fields": {"rows": "missing.field"}},
])
def test_forged_starters_have_no_side_effects(workspace, candidate):
    w = workspace
    assert w.browser.post(w.path + "/starters", json=candidate).status_code == 400
    assert not w.bench.store.threads(w.pid)
    assert not w.bench.store.recent_work(w.pid)


def test_saving_starter_then_archiving_and_restoring_preserves_source(workspace):
    w = workspace
    draft = w.browser.post(w.path + "/starters", json={"analysis": "describe"}).json()
    path = w.path + "/notebooks/" + draft["id"]
    saved = w.browser.put(path, json={"revision": 0, "title": draft["title"], "cells": [
        {"id": c["id"], "kind": c["kind"], "source": c["source"]} for c in draft["cells"]]}).json()
    assert saved["title"] == draft["title"] and saved["revision"] == 1
    assert not saved.get("temporary")
    assert len(w.bench.store.recent_work(w.pid)) == 1
    assert w.browser.post(path + "/archive", json={"archived": True}).status_code == 200
    assert not w.bench.store.recent_work(w.pid)
    assert w.browser.get(path).json()["cells"] == saved["cells"]
    assert len(w.browser.get(w.path + "/work?archived=true").json()["work"]) == 1
    assert w.browser.post(path + "/archive", json={"archived": False}).status_code == 200
    assert len(w.bench.store.recent_work(w.pid)) == 1


def test_reimporting_an_explicit_preview_preserves_manual_edits(workspace):
    w = workspace
    plan = w.browser.post(w.path + "/plans", json={"analysis": "describe"}).json()
    body = {"kind": "plan", "object_id": plan["id"]}
    notebook = w.browser.post(w.path + "/notebooks/import", json=body).json()
    notebook["cells"][0]["source"] += "\n# my refinement\n"
    saved = w.bench.store.save_notebook(w.pid, notebook["id"], notebook["cells"], notebook["revision"])
    reopened = w.browser.post(w.path + "/notebooks/import", json=body).json()
    assert reopened["revision"] == saved["revision"]
    assert reopened["cells"][0]["source"].endswith("# my refinement\n")
