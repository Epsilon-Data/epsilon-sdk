"""
Pytest configuration and fixtures
"""

import pytest
from unittest.mock import Mock
from datetime import datetime, timedelta, timezone

from sdk.client import APIClient


@pytest.fixture
def mock_client():
    """Create a mock API client"""
    client = Mock(spec=APIClient)
    client.access_token = 'test_token_123'
    client.token_expires_at = datetime.now() + timedelta(hours=1)
    client.base_url = 'https://app.epsilon-data.org'
    client.timeout = 30
    client.is_authenticated.return_value = True
    return client


@pytest.fixture
def authenticated_client():
    """Create an authenticated API client"""
    client = APIClient()
    client.access_token = 'test_token_123'
    client.token_expires_at = datetime.now() + timedelta(hours=1)
    return client


@pytest.fixture
def mock_datasets():
    """Sample dataset data for testing"""
    return [
        {
            'datasetId': 'dataset_1',
            'packageId': 'test_package_1',
            'name': 'Test Dataset 1',
            'status': 'active',
            'lastModified': '2024-01-01T10:00:00Z'
        },
        {
            'datasetId': 'dataset_2',
            'packageId': 'test_package_2',
            'name': 'Test Dataset 2',
            'status': 'active',
            'lastModified': '2024-01-02T10:00:00Z'
        }
    ]


@pytest.fixture
def mock_archetype():
    """Sample archetype data for testing (JSON Schema format)"""
    return {
        '$id': 'test_dataset',
        '$schema': 'https://json-schema.org/draft/2020-12/schema#',
        'title': 'Test Dataset',
        'type': 'object',
        'properties': {
            'patient': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'integer', 'description': 'Patient ID'},
                    'name': {'type': 'string', 'description': 'Patient Name'},
                    'age': {'type': 'integer', 'description': 'Patient Age'}
                }
            },
            'vitals': {
                'type': 'object',
                'properties': {
                    'heartrate': {'type': 'integer', 'description': 'Heart Rate'},
                    'bloodpressure': {'type': 'object', 'description': 'Blood Pressure'}
                }
            }
        }
    }

# -- copilot fixtures -------------------------------------------------------

# A projection shaped like the live MIMIC-IV demo: diagnosis grain, no entity
# key, an aggregate-only timestamp, a top-coded age and two ICD revisions in
# one column. The awkward parts are the point -- they are what the profiler
# has to notice and the catalogue has to refuse.
HEADER = ("admissions.time,admissions.type,patient.gender,patient.age,"
          "diagnoses.icd_code,diagnoses.icd_version")

TYPES = ["EW EMER.", "OBSERVATION ADMIT", "URGENT", "EU OBSERVATION",
         "SURGICAL SAME DAY ADMISSION", "DIRECT EMER.", "ELECTIVE",
         "DIRECT OBSERVATION", "AMBULATORY OBSERVATION"]


def _code(i):
    """Many distinct codes, so the column profiles as a code rather than a
    category -- and split across two ICD revisions, as MIMIC-IV is."""
    return "4019" if i % 3 else "I{0:03d}".format(10 + (i % 40))


def _rows(n=4000):
    out = [HEADER]
    for i in range(n):
        # age 30..89 normally, with a deliberate pile-up at 91 (top-coded)
        age = 91 if i % 11 == 0 else 30 + (i % 60)
        out.append("21{0:02d}-03-04 11:00,{1},{2},{3},{4},{5}".format(
            i % 40, TYPES[i % len(TYPES)], "M" if i % 2 else "F", age,
            _code(i), 9 if i % 3 else 10))
    return "\n".join(out) + "\n"


ARCHETYPE = {
    "$id": "ds-1/arch-1",
    "title": "Test cohort",
    "type": "object",
    "syntheticData": {"available": True, "schemaHash": "4f2a91c0b3de00112233",
                      "version": 3},
    "properties": {
        "patient": {"type": "object", "properties": {
            "gender": {"type": "string"}, "age": {"type": "integer"}}},
        "admissions": {"type": "object", "properties": {
            "type": {"type": "object"}, "time": {"type": "object"}}},
        "diagnoses": {"type": "object", "properties": {
            "icd_code": {"type": "object"}, "icd_version": {"type": "integer"}}},
    },
}


def build_dataset(path):
    """Materialise the fixture dataset into a directory."""
    import json
    generated = path / "generated"
    generated.mkdir(parents=True)
    (generated / "data.csv").write_text(_rows(), encoding="utf-8")
    (generated / "archetype.json").write_text(json.dumps(ARCHETYPE),
                                              encoding="utf-8")
    return path


@pytest.fixture
def dataset_dir(tmp_path):
    """An initialised project with a real CSV to measure."""
    return build_dataset(tmp_path)


@pytest.fixture
def profile(dataset_dir):
    from sdk.profile import profile_project
    return profile_project(str(dataset_dir))


@pytest.fixture
def keyed_profile(profile):
    """The same dataset once an archetype grants a pseudonymised entity key."""
    import copy
    from sdk.profile import DETAILED, Leaf
    p = copy.deepcopy(profile)
    p.leaves["patient.pid"] = Leaf(path="patient.pid", type="code",
                                   access_level=DETAILED, cardinality=400,
                                   null_rate=0.0)
    p.grain.dedupe_key = "patient.pid"
    p.grain.unit = "patient"
    return p


# -- shared workbench fixture --------------------------------------------

def settled(bench, pid, payload):
    """Wait for a background job to stop, whatever its outcome."""
    import time
    job = bench.jobs.get(pid, payload["id"])
    deadline = time.monotonic() + 10
    while job.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(.01)
    assert job.status not in ("queued", "running"), job.payload()
    return job


def finished(bench, pid, payload):
    """Wait for a background job and require that it completed."""
    job = settled(bench, pid, payload)
    assert job.status == "completed", job.payload()
    return job.result


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A registered project, a mocked Epsilon API and an unlocked browser session."""
    import copy
    from pathlib import Path
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from sdk import llm
    from sdk.workbench.api import build
    from sdk.workbench.service import Workbench
    monkeypatch.setattr(llm, "load", lambda: llm.AIConfig(api_key=None))
    root = build_dataset(tmp_path / "respiratory")
    (root / "project.yml").write_text("dataset_id: ds-1\narchetype_id: arch-1\nentry_point: main.py\n")
    bench = Workbench(root, state_dir=tmp_path / "state")
    pid = bench.project_list()[0]["id"]
    hub = Mock(spec=APIClient)
    hub.access_token = "fixture-access-token-123456789"
    hub.token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    hub.get_datasets.return_value = [{"datasetId": "ds-1", "name": "Respiratory study"}]
    hub.get_dataset.return_value = copy.deepcopy(ARCHETYPE)
    def download(dataset_id, destination):
        Path(destination).write_text(_rows())
        return {"schema_hash": ARCHETYPE["syntheticData"]["schemaHash"], "version": 3}
    hub.download_synthetic_data.side_effect = download
    bench.client_factory = lambda: hub
    monkeypatch.setattr(bench, "client", lambda: hub)
    app = build(root, bench=bench)
    # Unit workflows do not need to inspect the developer's Docker environment.
    bench.notebook_runtime = lambda *_: {"available": False, "inventory_verified": False, "packages": []}
    with TestClient(app, base_url="http://127.0.0.1:8787") as browser:
        token = app.state.local_sessions.launch_token
        response = browser.post("/api/bootstrap", json={"token": token})
        assert response.status_code == 200
        browser.headers["x-epsilon-csrf"] = response.json()["csrf"]
        yield SimpleNamespace(bench=bench, pid=pid, root=root, hub=hub, app=app,
                              browser=browser, token=token, tmp=tmp_path,
                              path="/api/projects/" + pid)
