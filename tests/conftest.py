"""
Pytest configuration and fixtures
"""
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

# Modelled on the live MIMIC-IV demo archetype: six leaves at diagnosis grain,
# no patient key, and two ICD revisions in one column. The awkward parts are
# the point -- they are what the catalogue has to refuse.
CARD_JSON = {
    "cardVersion": 1,
    "title": "Test cohort",
    "datasetId": "ds-1",
    "archetype": "arch-1",
    "schemaHash": "4f2a91c0b3de00112233",
    "datasetVersion": 3,
    "grain": {
        "unit": "diagnosis_record",
        "statement": "One row per diagnosis code.",
        "rows": 100000,
        "entityCounts": {"admissions": 275, "patients": 100},
        "dedupeKey": None,
        "known": True,
    },
    "leaves": {
        "patient.gender": {
            "source": "hosp.patients.gender", "type": "categorical",
            "accessLevel": "DETAILED", "categories": ["M", "F"],
            "cardinality": 2, "nullRate": 0.0,
            "caveats": ["Denormalised onto every diagnosis row. At row level "
                        "the split is 51.6% M / 48.4% F; across patients it is "
                        "57% / 43%."],
        },
        "patient.age": {
            "source": "hosp.patients.anchor_age", "type": "integer",
            "accessLevel": "DETAILED", "unit": "years", "range": [21, 91],
            "nullRate": 0.0,
            "caveats": ["Ages above 89 are recorded as 91."],
        },
        "admissions.type": {
            "source": "hosp.admissions.admission_type", "type": "categorical",
            "accessLevel": "DETAILED", "cardinality": 9, "nullRate": 0.0,
        },
        "admissions.time": {
            "source": "hosp.admissions.admittime", "type": "timestamp",
            "accessLevel": "HIGH_LEVEL", "nullRate": 0.0,
            "releasableAs": ["month", "quarter", "year"],
            "comparableAcrossEntities": False,
        },
        "diagnoses.icd_code": {
            "source": "hosp.diagnoses_icd.icd_code", "type": "code",
            "accessLevel": "DETAILED", "cardinality": 1472, "nullRate": 0.0,
            "codeSystem": {
                "discriminator": "diagnoses.icd_version",
                "systems": {"9": "ICD-9-CM", "10": "ICD-10-CM"},
                "mixed": True, "split": {"9": 0.487, "10": 0.513},
            },
        },
        "diagnoses.icd_version": {
            "source": "hosp.diagnoses_icd.icd_version", "type": "categorical",
            "accessLevel": "DETAILED", "categories": ["9", "10"],
            "cardinality": 2, "nullRate": 0.0,
        },
    },
    "excluded": ["No discharge date, so no length of stay."],
    "policy": {"minCell": 10, "allowAiProfiling": True},
}


@pytest.fixture
def card_json():
    """Raw card dict, safe to mutate in a test."""
    import copy
    return copy.deepcopy(CARD_JSON)


@pytest.fixture
def card(card_json):
    from sdk.card import Card
    return Card.from_json(card_json)


@pytest.fixture
def unblocked_card(card_json):
    """The same dataset once the owner grants a key, a duration and real dates."""
    import copy
    from sdk.card import Card
    raw = copy.deepcopy(card_json)
    raw["grain"].update({"dedupeKey": "patient.pid",
                         "entityCounts": {"patients": 100}, "rows": 100})
    raw["leaves"]["patient.pid"] = {
        "type": "string", "accessLevel": "DETAILED", "nullRate": 0.0}
    raw["leaves"]["stay.los"] = {
        "type": "duration", "unit": "days", "accessLevel": "DETAILED",
        "nullRate": 0.0}
    raw["leaves"]["admissions.time"]["comparableAcrossEntities"] = True
    return Card.from_json(raw)
