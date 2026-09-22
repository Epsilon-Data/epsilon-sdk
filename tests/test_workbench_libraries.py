"""Runtime package availability must describe the notebook, not the host SDK."""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sdk.llm.base import AgentReply
from sdk.workbench import assistant, kernel, libraries
from tests.conftest import finished
def test_package_probe_is_cached_by_image_and_has_no_project_or_network(monkeypatch):
    libraries.installed_libraries.cache_clear()
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps({"python": "3.11.14", "packages": {"pandas": "2.3.3", "unrelated-private-package": "1.0"}})))
    monkeypatch.setattr(libraries.subprocess, "run", run)
    first = libraries.installed_libraries("docker", "sha256:old")
    assert first["packages"] == [{"name": "pandas", "module": "pandas", "version": "2.3.3", "purpose": "Data tables"}]
    libraries.installed_libraries("docker", "sha256:old")
    assert run.call_count == 1
    libraries.installed_libraries("docker", "sha256:new")
    assert run.call_count == 2
    argv = run.call_args.args[0]
    for flag in ("--network=none", "--read-only", "--pull=never", "--cap-drop=ALL", "--user=65532:65532"):
        assert flag in argv
    assert not {"--mount", "-v", "--env", "-e", "--privileged"} & set(argv)
    libraries.installed_libraries.cache_clear()


def test_older_image_reports_missing_libraries_without_claiming_they_are_installed(monkeypatch):
    monkeypatch.setattr(kernel.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(kernel, "docker_environment", lambda: {})
    monkeypatch.setattr(kernel.subprocess, "run", Mock(side_effect=[SimpleNamespace(returncode=0, stdout="unix:///local/docker.sock"), SimpleNamespace(returncode=0, stdout="sha256:old")]))
    monkeypatch.setattr(kernel, "installed_libraries", lambda *_: {"python": "3.11.14", "packages": [{"name": "pandas", "module": "pandas", "version": "2.3.3"}]})
    status = kernel.runtime_status(refresh=True)
    assert status["available"] and status["inventory_verified"] and status["needs_rebuild"]
    assert "seaborn" in status["missing_packages"]
    assert {p["name"] for p in status["packages"]} == {"pandas"}


def test_failed_inventory_does_not_invent_installed_versions(monkeypatch):
    monkeypatch.setattr(kernel.shutil, "which", lambda _: "docker")
    monkeypatch.setattr(kernel, "docker_environment", lambda: {"DOCKER_HOST": "unix:///local/docker.sock"})
    monkeypatch.setattr(kernel.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0, stdout="sha256:old")))
    monkeypatch.setattr(kernel, "installed_libraries", Mock(side_effect=ValueError("private diagnostic")))
    status = kernel.runtime_status(refresh=True)
    assert status["available"] and not status["inventory_verified"] and status["packages"] == []
    assert "private diagnostic" not in json.dumps(status)


def test_running_notebook_reports_its_own_packages_after_image_update(tmp_path, monkeypatch):
    manager = kernel.Kernels(tmp_path)
    old = {"available": True, "image_id": "sha256:old", "packages": [{"name": "pandas", "version": "2.3.3"}]}
    current = {"available": True, "image_id": "sha256:new", "packages": [{"name": "seaborn", "version": "0.13.2"}]}
    process = Mock()
    process.poll.return_value = None
    manager.items[("one", "main")] = SimpleNamespace(runtime=old, image_id=old["image_id"], process=process)
    monkeypatch.setattr(kernel, "runtime_status", lambda **_: current)
    running = manager.status("one", "main")
    assert running["packages"] == old["packages"] and running["update_available"] and running["active"]
    other = manager.status("two", "main")
    assert other["packages"] == current["packages"] and not other["active"]
    assert not process.kill.called


def test_assistant_receives_bounded_actual_environment_metadata(workspace):
    w = workspace
    status = {"available": True, "inventory_verified": True, "python": "3.11.14", "update_available": True,
              "packages": [{"name": "pandas", "module": "pandas", "version": "2.3.3", "output": "private kernel value"}],
              "local_path": "private project path"}
    w.bench.notebook_runtime = Mock(return_value=status)
    original = w.bench.ai_status
    w.bench.ai_status = lambda: dict(original(), configured=True)
    provider = Mock()
    provider.converse.return_value = AgentReply(text="I can use the installed pandas library.")
    w.bench.provider = lambda: provider
    tid = w.bench.store.notebook_thread(w.pid, "main")
    finished(w.bench, w.pid, assistant.chat(w.bench, w.pid, tid, "Which libraries can I use?", "main").payload())
    system = provider.converse.call_args.args[0]
    context = json.loads(system.split("PERMITTED CONTEXT:\n", 1)[1])["runtime"]
    assert context["packages"] == [{"name": "pandas", "module": "pandas", "version": "2.3.3"}]
    assert context["inventory_verified"] and context["restart_for_update"]
    assert "seaborn" in context["planned_packages"]
    assert "private kernel value" not in system and "private project path" not in system
    w.bench.notebook_runtime.assert_called_once_with(w.pid, "main")


def test_runtime_endpoint_uses_the_requested_project_and_notebook(workspace, monkeypatch):
    w = workspace
    status = Mock(return_value={"available": True, "packages": []})
    monkeypatch.setattr(w.app.state.kernels, "status", status)
    assert w.browser.get(w.path + "/notebooks/main/runtime").status_code == 200
    status.assert_called_once_with(w.pid, "main")
    assert w.browser.get("/api/projects/missing/notebooks/main/runtime").status_code == 404
    assert status.call_count == 1


@pytest.mark.skipif(os.environ.get("EPSILON_TEST_NOTEBOOK") != "1", reason="Build the optional notebook image first")
def test_real_seaborn_heatmap_and_scientific_library_inventory(dataset_dir, tmp_path):
    manager = kernel.Kernels(tmp_path)
    try:
        notebook = manager.get("research", "libraries", dataset_dir)
        assert notebook.runtime["inventory_verified"] and not notebook.runtime["needs_rebuild"]
        output = notebook.execute("import pandas as pd\nimport matplotlib.pyplot as plt\nimport seaborn as sns\nimport numpy as np\nimport scipy\nimport statsmodels.api as sm\nfrom importlib.metadata import version\nprint('SEABORN', version('seaborn'))\nframe = pd.read_csv('generated/data.csv')\ncounts = pd.crosstab(frame['patient.gender'], frame['admissions.type'])\n# This synthetic test figure is local notebook output.\nsns.heatmap(counts.where(counts >= 10), annot=True, fmt='.0f', cmap='Blues', mask=counts < 10)\nplt.tight_layout()\nplt.show()")
        assert not output["error"] and output["images"], output
        actual = next(p["version"] for p in notebook.runtime["packages"] if p["name"] == "seaborn")
        assert "SEABORN " + actual in output["text"]
    finally:
        manager.close()
