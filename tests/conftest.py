"""
Pytest configuration and fixtures
"""
import os
import tempfile

# Chainlit resolves its config, files and public/ directory from
# CHAINLIT_APP_ROOT at import time. Point it at a throwaway directory before
# anything imports chainlit, so tests never write into the repository.
os.environ.setdefault("CHAINLIT_APP_ROOT",
                      tempfile.mkdtemp(prefix="epsilon-test-chainlit-"))

import pytest
from unittest.mock import Mock
from datetime import datetime, timedelta

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
