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