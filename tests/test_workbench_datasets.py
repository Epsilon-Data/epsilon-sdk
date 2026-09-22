"""Approved dataset selection precedes local initialization."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sdk.client import APIClient
from sdk.errors import AuthenticationError
from sdk.workbench.jobs import Job
from tests.conftest import finished
def test_account_datasets_are_distinct_from_local_projects(workspace):
    w = workspace
    original = w.bench.project_list()
    w.hub.get_datasets.return_value = [
        {"datasetId": "ds-1", "name": "Respiratory study"},
        {"datasetId": "ds-2"}, {"datasetId": "ds-1"}, {}, None,
    ]
    response = w.browser.get("/api/datasets")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["datasets"]] == ["ds-1", "ds-2"]
    assert w.bench.project_list() == original
    assert len(w.browser.get("/api/projects").json()["projects"]) == 1
    w.hub.get_dataset.assert_not_called()
    w.hub.download_synthetic_data.assert_not_called()


def test_dataset_display_fetches_only_approved_archetype_metadata(workspace):
    w = workspace
    original = w.bench.project_list()
    response = w.browser.get("/api/datasets/ds-1")
    assert response.status_code == 200
    assert response.json() == {"id": "ds-1", "name": "Test cohort", "status": "Approved",
                               "description": "", "synthetic_available": True}
    assert "properties" not in response.text and "patient.gender" not in response.text
    w.hub.get_dataset.assert_called_once_with("ds-1")
    w.hub.download_synthetic_data.assert_not_called()
    assert w.bench.project_list() == original


def test_unapproved_dataset_cannot_fetch_details_or_create_a_folder(workspace):
    w = workspace
    original = w.bench.project_list()
    assert w.browser.get("/api/datasets/unapproved").status_code == 404
    path = w.tmp / "should-not-exist"
    response = w.browser.post("/api/projects", json={"name": "Study", "path": str(path), "dataset_id": "unapproved"})
    assert response.status_code == 404
    assert not path.exists()
    assert w.bench.project_list() == original
    w.hub.get_dataset.assert_not_called()
    w.hub.download_synthetic_data.assert_not_called()


def test_expired_credentials_request_sign_in_without_echoing_the_upstream_error(workspace):
    workspace.hub.get_datasets.side_effect = AuthenticationError("private upstream credential detail")
    response = workspace.browser.get("/api/datasets")
    assert response.status_code == 401
    assert response.json()["code"] == "epsilon_sign_in_required"
    assert "private upstream" not in response.text


def test_selected_dataset_initializes_chosen_folder_with_shared_sdk_service(workspace):
    w = workspace
    path = w.tmp / "chosen-folder"
    created = w.browser.post("/api/projects", json={"name": "Selected study", "path": str(path), "dataset_id": "ds-1"})
    assert created.status_code == 200
    project = created.json()
    assert project["dataset_id"] == "ds-1"
    assert not (path / "project.yml").exists()
    w.hub.download_synthetic_data.assert_not_called()
    project_url = "/api/projects/" + project["id"]
    assert w.browser.get(project_url).json()["dataset_id"] == "ds-1"
    result = finished(w.bench, project["id"], w.browser.post(project_url + "/initialise", json={"dataset_id": "ds-1"}).json())
    assert result["source"] == "synthetic"
    assert (path / "project.yml").is_file()
    assert (path / "main.py").is_file()
    assert all((path / "generated" / name).is_file() for name in ("data.csv", "models.py", "archetype.json"))
    assert w.browser.get(project_url).json()["ready"] is True
    assert w.bench.store.threads(project["id"]) == []
    assert len(w.bench.project_list()) == 2


def test_revoked_access_stops_initialization_before_a_job_or_download(workspace):
    w = workspace
    path = w.tmp / "revoked"
    project = w.browser.post("/api/projects", json={"name": "Study", "path": str(path), "dataset_id": "ds-1"}).json()
    w.hub.get_datasets.return_value = []
    response = w.browser.post("/api/projects/" + project["id"] + "/initialise", json={"dataset_id": "ds-1"})
    assert response.status_code == 404
    assert not w.bench.jobs.jobs
    assert not (path / "project.yml").exists()
    w.hub.download_synthetic_data.assert_not_called()


def test_queued_initialization_keeps_the_client_that_started_it(workspace, monkeypatch):
    w = workspace
    project = w.bench.create_project("Queued study", str(w.tmp / "queued"), "", "ds-1")
    captured = {}
    def submit(project_id, kind, scope, operation):
        captured["operation"] = operation
        return SimpleNamespace(id="queued-job")
    monkeypatch.setattr(w.bench.jobs, "submit", submit)
    w.bench.initialise(project["id"], "ds-1")
    another = Mock(spec=APIClient)
    monkeypatch.setattr(w.bench, "client", lambda: another)
    result = captured["operation"](Job(project["id"], "initialise", "test"))
    assert result["source"] == "synthetic"
    assert (Path(project["path"]) / "generated/data.csv").exists()
    another.get_dataset.assert_not_called()
    another.download_synthetic_data.assert_not_called()


@pytest.mark.parametrize("value", [None, {}, {"datasets": []}])
def test_invalid_dataset_response_is_an_error_instead_of_an_empty_account(workspace, value):
    workspace.hub.get_datasets.return_value = value
    response = workspace.browser.get("/api/datasets")
    assert response.status_code == 400
    assert "unexpected dataset list" in response.text
