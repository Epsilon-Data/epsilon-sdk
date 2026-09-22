"""Rich Jupyter display semantics and the browser's inert output boundary."""
import copy
import json

import pytest

from sdk.workbench import analysis
from sdk.workbench.display import (MAX_TOTAL, apply_updates, axes, markdown,
                                   notebook_view, png, render_output, safe_html)
from sdk.workbench.runtime.worker import Outputs

def test_order_clear_wait_and_display_handles():
    output = Outputs()
    output.feed("execute_input", {"execution_count": 7})
    output.feed("stream", {"name": "stdout", "text": "before\n"})
    output.feed("display_data", {"data": {"text/html": "<table><tr><td>42</td></tr></table>"}, "transient": {"display_id": "table"}})
    output.feed("stream", {"name": "stdout", "text": "after\n"})
    output.feed("update_display_data", {"data": {"text/plain": "updated table"}, "transient": {"display_id": "table"}})
    view = render_output({"outputs": output.items})
    assert [b["text"] for b in view["blocks"]] == ["before\n", "updated table", "after\n"]
    assert view["updates"][0]["display_id"] == "table"
    assert output.execution_count == 7
    output.feed("clear_output", {"wait": True})
    assert len(output.items) == 4
    output.feed("stream", {"name": "stderr", "text": "new output"})
    assert len(output.items) == 1 and output.items[0]["name"] == "stderr"
    output.feed("clear_output", {"wait": False})
    assert output.items == []


def test_output_budget_retains_error_state():
    output = Outputs()
    for i in range(50):
        output.feed("display_data", {"data": {"text/plain": str(i) * 60000}})
    output.feed("error", {"ename": "RuntimeError", "evalue": "failure"})
    assert output.truncated and output.error
    assert len(json.dumps(output.items)) <= MAX_TOTAL
    output = Outputs()
    output.feed("display_data", {"data": {"application/javascript": "fetch('https://invalid.example')"}})
    assert "javascript" not in json.dumps(output.items)


@pytest.mark.parametrize("payload", [
    '<script>BAD</script><img src="https://invalid.example/x" onerror="BAD"><table style="background:url(https://invalid.example)"><tr><td onclick="BAD">Good</td></tr></table>',
    '<svg><script>BAD</script></svg><iframe srcdoc="BAD"></iframe><a href="javascript:BAD">Good</a>',
    '<math><annotation-xml><script>BAD</script></annotation-xml></math><style>BAD</style><p id="app" class="overlay">Good</p>',
    '<table><tr><td colspan="³" onmouseover="BAD">Good</td></tr></table>',
])
def test_html_has_no_active_content_or_external_resources(payload):
    value = safe_html(payload)
    assert "Good" in value and "BAD" not in value
    assert not any(token in value for token in ("src=", "href=", "style=", "class=", "id=", "onclick", "onerror", "<script", "<img", "<svg", "<iframe", "<math"))


def test_markdown_tables_and_plain_data_remain_readable():
    rendered = markdown("## Results\n\n| Group | Value |\n| --- | --- |\n| A | 12 |\n\n<img src='https://invalid.example/x'>")
    assert "<h2>Results</h2>" in rendered and "<table>" in rendered
    assert "<img" not in rendered and "&lt;img" in rendered
    out = render_output({"outputs": [
        {"output_type": "display_data", "data": {"text/html": "<table><tr><th>age</th></tr><tr><td>42</td></tr></table>", "text/plain": "age 42"}},
        {"output_type": "display_data", "data": {"application/json": {"nested": [1, 2, "<script>"]}}},
        {"output_type": "error", "traceback": [None, 42, "\x1b[31mError"]},
    ]})
    assert [b["kind"] for b in out["blocks"]] == ["html", "json", "error"]
    assert "\x1b" not in out["blocks"][-1]["text"]
    assert png("not a PNG") is None


def test_existing_saved_preview_displays_without_mutating_results(workspace):
    w = workspace
    plan = analysis.make_plan(w.root, "describe", {})
    plan["id"] = "legacy-plan"
    artifact = analysis.run_plan(w.root, plan)
    legacy = {"id": "legacy", "cells": [{"source": artifact["code"], "output": {"text": json.dumps(artifact["result"], indent=2), "reviewed": False}}]}
    original = copy.deepcopy(legacy)
    shown = notebook_view(legacy)
    block = shown["cells"][0]["output"]["display"]["blocks"][0]
    assert block["kind"] == "preview" and block["result"] == artifact["result"]
    assert legacy == original and shown["cells"][0]["source"] == artifact["code"]
    w.bench.store.save_notebook(w.pid, "legacy", legacy["cells"], 0)
    reloaded = w.browser.get(w.path + "/notebooks/legacy").json()
    assert reloaded["cells"][0]["output"]["display"] == shown["cells"][0]["output"]["display"]
    persisted = w.bench.store.notebook(w.pid, "legacy")["cells"][0]
    assert persisted["source"] == original["cells"][0]["source"]
    assert persisted["output"] == original["cells"][0]["output"]


def test_axes_are_ordered_and_preserve_gaps_without_inventing_values():
    numeric = {"tables": [{"name": "age", "chart": {"labels": ["40 to < 50", "10 to < 20", "20 to < 30", "Missing"]}}]}
    source = "SPEC = {'analysis':'describe','descriptors':[{'path':'age','type':'number'}]}"
    axis = axes(numeric, source)[0]
    assert axis == {"kind": "numeric", "points": [{"index": 1, "x": 10.0}, {"index": 2, "x": 20.0}, {"index": 0, "x": 40.0}], "step": 10.0}
    time = {"tables": [{"name": "result", "chart": {"labels": ["2024-04", "2024-01", "2024-02", "Invalid date"]}}]}
    axis = axes(time, "SPEC = {'analysis':'trend','fields':{'bucket':'month'}}")[0]
    assert [p["index"] for p in axis["points"]] == [1, 2, 0]
    assert axis["points"][2]["x"] - axis["points"][1]["x"] == 2 and axis["step"] == 1
    assert axes(numeric, "SPEC = {'analysis':'describe','descriptors':[{'path':'age','type':'categorical'}]}")[0]["kind"] == "category"
    assert axes(numeric, "SPEC = __import__('os').system('false')")[0]["points"] == []


def test_updates_cannot_change_outputs_from_another_kernel():
    def cell(kernel):
        return {"source": "display(value)", "output": {"kernel_id": kernel, "display": {"blocks": [{"kind": "text", "text": "old", "display_id": "same"}]}}}
    notebook = {"cells": [cell("current"), cell("previous")]}
    output = {"kernel_id": "current", "display": {"updates": [{"kind": "text", "text": "new", "display_id": "same"}]}}
    apply_updates(notebook, output)
    assert notebook["cells"][0]["output"]["text"] == "new"
    assert notebook["cells"][1]["output"]["display"]["blocks"][0]["text"] == "old"


def test_markdown_cells_save_render_export_but_do_not_execute(workspace):
    w = workspace
    path = w.path + "/notebooks/main"
    payload = {"revision": 0, "cells": [{"kind": "markdown", "source": "# Research notes\n\n**Local** observations."}, {"kind": "code", "source": "2 + 2"}]}
    saved = w.browser.put(path, json=payload).json()
    assert "<h1>Research notes</h1>" in saved["cells"][0]["html"]
    exported = w.browser.get(path + "/export").json()
    assert exported["cells"][0]["cell_type"] == "markdown" and "outputs" not in exported["cells"][0]
    assert exported["cells"][1]["outputs"] == []
    response = w.browser.post(path + "/execute", json={"revision": 1, "cell": 0})
    assert response.status_code == 400 and "Markdown" in response.text
    assert w.browser.get("/assets/notebook.js").status_code == 200
