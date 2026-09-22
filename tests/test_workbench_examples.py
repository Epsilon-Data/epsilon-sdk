"""Examples remain read-only until copied, and their notebook counts reproduce previews."""
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from evaluation.assistant import fixture
from sdk.workbench import examples
from sdk.workbench.kernel import Kernels
from sdk.workbench.service import Workbench

def test_browsing_examples_needs_no_ai_or_runtime_and_creates_nothing(workspace, monkeypatch):
    w = workspace
    monkeypatch.setattr(w.bench, "ai_config", lambda: pytest.fail("Browsing must not use AI"))
    cards = w.browser.get(w.path + "/examples").json()["examples"]
    assert len(cards) == 3
    for card in cards:
        response = w.browser.get(w.path + "/examples/" + card["id"])
        assert response.status_code == 200
        item = response.json()
        assert len(item["panels"]) >= 2 and item["learn"] and item["fields"]
        assert item["preview"]["status"] == "ready"
        assert item["provenance"]["synthetic"] and item["provenance"]["min_cell"] >= 10
        assert all(len(cell["source"].splitlines()) < 40 for cell in item["cells"])
        assert not any(cell["output"] for cell in item["cells"])
        assert all(field in "\n".join(c["source"] for c in item["cells"]) for field in item["fields"])
    assert w.browser.get(w.path + "/notebooks").json()["notebooks"] == []
    assert not w.bench.store.threads(w.pid) and not w.bench.store.recent_work(w.pid)
    assert not w.bench.jobs.jobs and not w.app.state.kernels.items
    with w.bench.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM objects").fetchone()[0] == 0


def test_copy_is_independent_and_retry_keeps_manual_edits(workspace):
    w = workspace
    detail = w.browser.get(w.path + "/examples/measurements").json()
    path = w.path + "/examples/measurements/copy"
    body = {"version": detail["version"], "request_id": "copy-one"}
    first = w.browser.post(path, json=body).json()
    assert first["revision"] == 1 and first["example"]["id"] == "measurements"
    assert not any(cell.get("ai") or cell.get("output") for cell in first["cells"])
    assert first["cells"][0]["id"] != detail["cells"][0]["id"]
    cells = [{key: c[key] for key in ("id", "kind", "source")} for c in first["cells"]]
    cells[1]["source"] += "\n# My research changes\n"
    saved = w.browser.put(w.path + "/notebooks/" + first["id"], json={"revision": 1, "cells": cells}).json()
    assert saved["example"] == first["example"]
    retried = w.browser.post(path, json=body).json()
    assert retried["id"] == first["id"] and retried["revision"] == 2
    assert "# My research changes" in retried["cells"][1]["source"]
    assert len(w.bench.store.recent_work(w.pid)) == 1
    thread = w.bench.store.thread(w.pid, w.bench.store.threads(w.pid)[0]["id"])
    assert thread["messages"] == []
    second = w.browser.post(path, json=dict(body, request_id="copy-two")).json()
    assert second["id"] != first["id"] and second["revision"] == 1
    assert "# My research changes" not in second["cells"][1]["source"]
    assert {c["id"] for c in first["cells"]}.isdisjoint(c["id"] for c in second["cells"])
    assert len(w.bench.store.recent_work(w.pid)) == 2
    assert w.browser.get(w.path + "/examples/measurements").json() == detail


def test_concurrent_copy_requests_are_atomic(workspace):
    w = workspace
    library = examples.Examples(w.bench)
    detail = library.detail(w.pid, "measurements")
    with ThreadPoolExecutor(max_workers=4) as pool:
        books = list(pool.map(lambda _: w.bench.store.copy_example(w.pid, detail, "same-request"), range(8)))
    assert len({book["id"] for book in books}) == 1
    assert len(w.bench.store.threads(w.pid)) == 1
    assert len(w.bench.store.recent_work(w.pid)) == 1


def test_copy_revalidates_inputs_and_does_not_accept_code_or_forged_fields(workspace):
    w = workspace
    detail = w.browser.get(w.path + "/examples/measurements").json()
    path = w.path + "/examples/measurements/copy"
    body = {"version": detail["version"], "request_id": "copy-one"}
    assert w.browser.post(path, json=dict(body, cells=[{"source": "raise SystemExit()"}])).status_code == 422
    assert w.browser.post(path, json=dict(body, fields={"field": "unknown"})).status_code == 422
    assert w.browser.get(w.path + "/examples/forged").status_code == 404
    assert w.browser.get("/api/projects/not-my-project/examples").status_code == 404
    csv_path = w.root / "generated/data.csv"
    csv_path.write_text(csv_path.read_text() + "2100-01-01,URGENT,F,35,4019,9\n")
    assert w.browser.post(path, json=body).status_code == 409
    assert not w.bench.store.recent_work(w.pid) and not w.bench.store.threads(w.pid)


def test_no_dates_no_trend_no_model_import_and_cache_invalidates(tmp_path, monkeypatch):
    root = fixture(tmp_path / "fixture", dates=False)
    data_path = root / "generated/data.csv"
    rows = list(csv.reader(data_path.read_text().splitlines()))
    for row in rows[1:4]:
        row[3] = "WITHHELD_LABEL_CANARY"
    with data_path.open("w", newline="") as stream:
        csv.writer(stream).writerows(rows)
    bench = Workbench(root, state_dir=tmp_path / "state")
    pid = bench.project_list()[0]["id"]
    marker = tmp_path / "imported-on-host"
    (root / "generated/models.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()")
    library = examples.Examples(bench)
    try:
        cards = library.catalogue(pid)
        assert {c["id"] for c in cards} == {"measurements", "compare-groups", "categories"}
        call = examples._tables
        reads = []
        def counting(*args):
            reads.append(True)
            return call(*args)
        monkeypatch.setattr(examples, "_tables", counting)
        item = library.detail(pid, "categories")
        assert "WITHHELD_LABEL_CANARY" not in json.dumps(item)
        assert item["preview"]["tables"][0]["withheld_groups"] == 2
        assert "from generated.models import create_dataset" in item["cells"][1]["source"]
        assert not marker.exists()
        assert library.detail(pid, "categories") == item and len(reads) == 1
        # Cached responses are copies, never mutable shared notebook state.
        item["preview"]["tables"].clear()
        assert library.detail(pid, "categories")["preview"]["tables"]
        with (root / "generated/data.csv").open("a") as stream:
            stream.write("44,25,Female,No\n")
        fresh = library.detail(pid, "categories")
        assert fresh["version"] != item["version"] and len(reads) == 2
    finally:
        bench.jobs.close()


def test_empty_and_suppressed_previews_never_invent_charts(workspace):
    w = workspace
    path = w.root / "generated/data.csv"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:3]) + "\n")
    cards = w.browser.get(w.path + "/examples").json()["examples"]
    assert cards
    detail = w.browser.get(w.path + "/examples/" + cards[0]["id"]).json()
    assert detail["preview"]["status"] == "ready"
    assert all(not table["rows"] and not table["chart"]["values"] for table in detail["preview"]["tables"])


def test_unavailable_preview_keeps_source_and_copy_accessible(workspace, monkeypatch):
    w = workspace
    monkeypatch.setattr(examples, "MAX_GROUPS", 1)
    response = w.browser.get(w.path + "/examples/measurements")
    assert response.status_code == 200
    detail = response.json()
    assert detail["preview"]["status"] == "unavailable" and detail["cells"]
    assert "tables" not in detail["preview"]
    copied = w.browser.post(w.path + "/examples/measurements/copy", json={
        "version": detail["version"], "request_id": "without-preview"})
    assert copied.status_code == 200
    assert all(not cell["output"] for cell in copied.json()["cells"])


@pytest.mark.skipif(os.environ.get("EPSILON_TEST_NOTEBOOK") != "1", reason="Opt-in real notebook execution")
@pytest.mark.parametrize("dates", [False, True])
def test_every_example_runs_and_reproduces_preview_counts_in_docker(tmp_path, dates):
    root = fixture(tmp_path / "fixture", dates=dates)
    # Include invalid values and unequal scales, preserving the generated wrapper.
    with (root / "generated/data.csv").open("a", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["NaN", "inf", "Female", "No"] + (["not-a-date"] if dates else []))
        writer.writerow(["", "", "", ""] + ([""] if dates else []))
    bench = Workbench(root, state_dir=tmp_path / "state")
    pid = bench.project_list()[0]["id"]
    library, kernels = examples.Examples(bench), Kernels(tmp_path / "runtime")
    try:
        kernel = kernels.get(pid, "examples", root)
        for card in library.catalogue(pid):
            detail = library.detail(pid, card["id"])
            book = library.clone(pid, card["id"], detail["version"], "copy-" + card["id"])
            source = "\n\n".join(cell["source"] for cell in book["cells"] if cell["kind"] == "code")
            source += "\nimport json\ninspection = []\n"
            for index in range(len(detail["series"])):
                source += (f"inspection.append([{{'group': ' / '.join(key) if isinstance(key, tuple) else str(key), 'records': int(value)}} "
                           f"for key, value in shown_{index + 1}.items()])\n")
            source += "print('EXAMPLE_COUNTS:' + json.dumps(inspection))\n"
            output = kernel.execute(source)
            assert not output["error"], output
            blocks = output["display"]["blocks"]
            assert sum(block["kind"] == "image" for block in blocks) == len(detail["panels"])
            text = "\n".join(block.get("text", "") for block in blocks)
            assert "WITHHELD_LABEL_CANARY" not in text
            actual = json.loads(next(line.removeprefix("EXAMPLE_COUNTS:") for line in text.splitlines() if line.startswith("EXAMPLE_COUNTS:")))
            expected = [[{key: row[key] for key in ("group", "records")} for row in table["rows"]] for table in detail["preview"]["tables"]]
            assert actual == expected, card["id"]
    finally:
        kernels.close()
        bench.jobs.close()
