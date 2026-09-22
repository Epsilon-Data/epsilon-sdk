"""Opt-in model evaluations against fabricated data, through the real workbench API.

python -m evaluation.assistant --list
python -m evaluation.assistant --live --cases age-bar,gender-pie --execute --output /tmp/epsilon-evaluation.json
No production API or registered project is opened. Code runs only in the notebook container.
"""
import argparse
import csv
import io
import json
import sqlite3
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

from fastapi.testclient import TestClient

from sdk.archetype import compile_archetype
from sdk.workbench.api import build
from sdk.workbench.service import Workbench
from sdk.workbench.kernel import runtime_status

CASE_FILE = Path(__file__).with_name("assistant_cases.json")


def fixture(root, *, dates=True):
    generated = root / "generated"
    generated.mkdir(parents=True)
    columns = ["patient.age", "patient.bmi", "patient.gender", "outcome.diabetic"] + (["visit.date"] if dates else [])
    with (generated / "data.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for i in range(500):
            writer.writerow([30 + i % 50, 18 + (i % 170) / 10,
                             "WITHHELD_LABEL_CANARY" if i < 3 else "Female" if i % 2 else "Male",
                             "Yes" if i % 5 == 0 else "No"] + ([f"{2100 + (i % 4) * 2}-01-01"] if dates else []))
    properties = {"patient": {"type": "object", "properties": {"age": {"type": "integer"}, "bmi": {"type": "number"}, "gender": {"type": "string"}}},
                  "outcome": {"type": "object", "properties": {"diabetic": {"type": "string"}}}}
    if dates:
        properties["visit"] = {"type": "object", "properties": {"date": {"type": "string", "format": "date"}}}
    archetype = {"$id": "evaluation-fixture/archetype", "title": "Fabricated evaluation records", "type": "object", "properties": properties}
    (generated / "archetype.json").write_text(json.dumps(archetype))
    with redirect_stdout(io.StringIO()):
        compile_archetype(str(generated / "archetype.json"), str(generated / "models.py"))
    (generated / "__init__.py").write_text("")
    (root / "project.yml").write_text("dataset_id: evaluation-fixture\narchetype_id: evaluation-archetype\nentry_point: main.py\n")
    return root


def workspace_settings(path):
    """Read only the configured model settings; never load a user's projects."""
    if not path.exists():
        return None
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT value FROM settings WHERE key='ai'").fetchone()
    return json.loads(row[0]) if row else None


def wait_job(bench, pid, payload, timeout=180):
    job = bench.jobs.get(pid, payload["id"])
    deadline = time.monotonic() + timeout
    while job.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(.05)
    if job.status in ("queued", "running"):
        job.cancel.set()
        raise RuntimeError("Evaluation task exceeded its time budget.")
    return job


def evaluate(case, *, settings=None, execute=False):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="epsilon-assistant-eval-") as directory:
        root = fixture(Path(directory) / "project", dates=case.get("dates", True))
        bench = Workbench(root, state_dir=Path(directory) / "state", record=False)
        if settings:
            bench.store.set_setting("ai", settings)
        app = build(root, bench=bench, record=False)
        outcome = {"case": case["id"], "expectation": case["expect"], "passed": False, "checks": {}, "execution": "not_requested"}
        with TestClient(app, base_url="http://127.0.0.1:8787") as browser:
            boot = browser.post("/api/bootstrap", json={"token": app.state.local_sessions.launch_token})
            browser.headers["x-epsilon-csrf"] = boot.json()["csrf"]
            pid = bench.project_list()[0]["id"]
            path = "/api/projects/" + pid
            tid = browser.post(path + "/threads", json={"title": case["id"]}).json()["id"]
            outcome["connection"] = {k: bench.ai_status().get(k) for k in ("provider", "model")}
            runtime_status(wait=True)
            result = browser.post(path + "/threads/" + tid + "/messages", json={"message": case["question"], "notebook_id": "main", "request_id": "evaluation-request"})
            if result.status_code != 200:
                outcome["failure"] = "Request was rejected before model execution."
                return outcome
            job = wait_job(bench, pid, result.json())
            outcome["checks"]["request_completed"] = job.status == "completed"
            outcome["failure_reason"] = job.reason
            reply = str((job.result or {}).get("reply", ""))
            reply_lower = reply.lower()
            outcome["quality"] = {
                "reply_present": bool(reply.strip()),
                "mentions_data_boundary": any(term in reply_lower for term in ("synthetic", "not real people", "tre", "not findings")),
                "avoids_strong_findings_claim": not any(term in reply_lower for term in ("proves that", "causes", "definitive clinical", "real-world finding")),
            }
            drafts = bench.store.objects(pid, "draft", tid)
            source = "\n".join(d["code"] for d in reversed(drafts))
            outcome["checks"]["notebook_unchanged_before_review"] = bench.store.notebook(pid, "main")["revision"] == 0
            outcome["checks"]["no_static_errors"] = not any(i["code"] in {"syntax", "unknown_field", "missing_library"} for d in drafts for i in (d.get("checks") or {}).get("issues", []))
            if case["expect"] == "code":
                outcome["checks"]["code_prepared"] = bool(drafts)
                outcome["checks"]["requested_fields"] = all(field in source for field in case.get("fields", []))
            elif case["expect"] == "no_code":
                outcome["checks"]["no_code_prepared"] = not drafts
                outcome["checks"]["no_plan_prepared"] = not bench.store.objects(pid, "plan", tid)
            outcome["checks"]["no_forbidden_code"] = all(term not in source for term in case.get("forbidden", []))
            if execute and case["expect"] == "code" and drafts and job.status == "completed":
                # Use the same explicit apply and execute endpoints as the UI.
                all_ran, figures = True, 0
                for draft in reversed(drafts):
                    response = browser.post(path + "/drafts/" + draft["id"] + "/apply", json={})
                    if response.status_code != 200:
                        all_ran = False
                        break
                    book = response.json()["notebook"]
                    cell_id = response.json()["change"]["cell_id"]
                    index = next(i for i, cell in enumerate(book["cells"]) if cell["id"] == cell_id)
                    run = browser.post(path + "/notebooks/main/execute", json={"revision": book["revision"], "cell": index})
                    if run.status_code != 200:
                        all_ran = False
                        break
                    executed = wait_job(bench, pid, run.json())
                    output = (executed.result or {}).get("run", {}).get("output", {})
                    all_ran &= executed.status == "completed" and not output.get("error", True)
                    figures += sum(block.get("kind") == "image" for block in output.get("display", {}).get("blocks", []))
                    if not all_ran:
                        break
                outcome["checks"]["runs_in_fresh_notebook"] = all_ran
                if case.get("figure"):
                    outcome["checks"]["figure_rendered"] = figures > 0
                outcome["execution"] = "passed" if all_ran else "failed"
            outcome["passed"] = all(outcome["checks"].values())
        outcome["seconds"] = round(time.monotonic() - started, 2)
        return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--live", action="store_true", help="Send fabricated-fixture questions/schema to your configured AI provider (normal API charges apply).")
    parser.add_argument("--execute", action="store_true", help="Run prepared code through the isolated notebook runtime.")
    parser.add_argument("--cases", default="", help="Comma-separated scenario identifiers; omitted runs all scenarios.")
    parser.add_argument("--runs", type=int, default=1, choices=range(1, 6))
    parser.add_argument("--output", type=Path, default=Path("assistant-evaluation.json"))
    parser.add_argument("--settings-db", type=Path, default=Path.home() / ".epsilon_sdk/workbench.db")
    args = parser.parse_args()
    cases = json.loads(CASE_FILE.read_text())
    if args.list:
        for case in cases:
            print(case["id"] + ": " + case["question"])
        return
    if not args.live:
        parser.error("Use --list to inspect tasks, or --live to run model evaluations.")
    selected = set(filter(None, args.cases.split(",")))
    unknown = selected - {case["id"] for case in cases}
    if unknown:
        parser.error("Unknown cases: " + ", ".join(sorted(unknown)))
    settings = workspace_settings(args.settings_db)
    outcomes = []
    for trial in range(args.runs):
        for case in cases:
            if selected and case["id"] not in selected:
                continue
            try:
                result = evaluate(case, settings=settings, execute=args.execute)
            except Exception:
                result = {"case": case["id"], "passed": False, "failure": "Evaluation could not complete. Check local runtime and model settings."}
            result["trial"] = trial + 1
            outcomes.append(result)
            print(json.dumps(result), flush=True)
            args.output.write_text(json.dumps({"scope": "Technical task checks on fabricated data; not scientific validation or TRE approval.", "results": outcomes}, indent=2))
    raise SystemExit(0 if all(item["passed"] for item in outcomes) else 1)


if __name__ == "__main__":
    main()
