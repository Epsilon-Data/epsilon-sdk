"""
Tests for APIClient
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import requests
from sdk.client import APIClient
from sdk.errors import AuthenticationError
from sdk import config
from pathlib import Path


class TestAPIClient:
    """Test suite for APIClient"""

    def setup_method(self):
        """Set up test fixtures"""
        self.client = APIClient()

    def test_init(self):
        """Test client initialization"""
        assert self.client.base_url == config.BASE_URL.rstrip('/')
        assert self.client.timeout == config.TIMEOUT
        assert self.client.access_token is None
        assert self.client.token_expires_at is None

    @patch('sdk.client.requests.post')
    def test_authenticate_success(self, mock_post):
        """Test successful authentication"""
        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {
            'access_token': 'test_token_123',
            'expires_in': 3600
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Call authenticate
        result = self.client.authenticate('testuser', 'testpass')

        # Assertions
        assert self.client.access_token == 'test_token_123'
        assert self.client.token_expires_at is not None
        assert result['access_token'] == 'test_token_123'

        # Verify API call
        mock_post.assert_called_once_with(
            f"{config.BASE_URL}{config.ENDPOINTS['auth']}",
            json={'username': 'testuser', 'password': 'testpass'},
            timeout=config.TIMEOUT
        )

    @patch('sdk.client.requests.post')
    def test_authenticate_no_token(self, mock_post):
        """Test authentication with no token in response"""
        mock_response = Mock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        with pytest.raises(AuthenticationError, match="No access token received"):
            self.client.authenticate('testuser', 'testpass')

    @patch('sdk.client.requests.post')
    def test_authenticate_request_error(self, mock_post):
        """Test authentication with request error"""
        mock_post.side_effect = requests.RequestException("Connection error")

        with pytest.raises(Exception, match="Authentication failed"):
            self.client.authenticate('testuser', 'testpass')

    def test_is_authenticated_no_token(self):
        """Test is_authenticated when no token"""
        assert self.client.is_authenticated() is False

    def test_is_authenticated_with_token(self):
        """Test is_authenticated with valid token"""
        self.client.access_token = 'test_token'
        self.client.token_expires_at = datetime.now() + timedelta(hours=1)
        assert self.client.is_authenticated() is True

    def test_is_authenticated_expired_token(self):
        """Test is_authenticated with expired token"""
        self.client.access_token = 'test_token'
        self.client.token_expires_at = datetime.now() - timedelta(hours=1)
        assert self.client.is_authenticated() is False

    @patch('sdk.client.requests.request')
    def test_make_request_success(self, mock_request):
        """Test successful API request"""
        # Set up authenticated client
        self.client.access_token = 'test_token'
        self.client.token_expires_at = datetime.now() + timedelta(hours=1)

        # Mock response
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_request.return_value = mock_response

        # Make request
        result = self.client._make_request('GET', '/test/endpoint')

        # Assertions
        assert result == mock_response
        mock_request.assert_called_once_with(
            'GET',
            f"{config.BASE_URL}/test/endpoint",
            headers={'Authorization': 'Bearer test_token'},
            timeout=config.TIMEOUT
        )

    def test_make_request_not_authenticated(self):
        """Test request when not authenticated"""
        with pytest.raises(AuthenticationError, match="Not authenticated"):
            self.client._make_request('GET', '/test')

    @patch('sdk.client.requests.request')
    def test_make_request_error(self, mock_request):
        """Test request with error"""
        self.client.access_token = 'test_token'
        self.client.token_expires_at = datetime.now() + timedelta(hours=1)

        mock_request.side_effect = requests.RequestException("API error")

        with pytest.raises(Exception, match="Request failed"):
            self.client._make_request('GET', '/test')

    @patch.object(APIClient, '_make_request')
    def test_get_datasets(self, mock_request):
        """Test get_datasets method"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {'id': '1', 'name': 'Dataset 1'},
            {'id': '2', 'name': 'Dataset 2'}
        ]
        mock_request.return_value = mock_response

        result = self.client.get_datasets()

        assert len(result) == 2
        assert result[0]['name'] == 'Dataset 1'
        mock_request.assert_called_once_with('GET', config.ENDPOINTS['datasets'])

    @patch.object(APIClient, '_make_request')
    def test_get_dataset_single(self, mock_request):
        """Test get_dataset with single dataset response"""
        mock_response = Mock()
        mock_response.json.return_value = {'id': 'test_id', 'name': 'Test Dataset'}
        mock_request.return_value = mock_response

        result = self.client.get_dataset('test_id')

        assert result['name'] == 'Test Dataset'
        expected_endpoint = config.ENDPOINTS['dataset'].format(dataset_id='test_id')
        mock_request.assert_called_once_with('GET', expected_endpoint)

    @patch.object(APIClient, '_make_request')
    def test_get_dataset_array_response(self, mock_request):
        """Test get_dataset with array response"""
        mock_response = Mock()
        mock_response.json.return_value = [{'id': 'test_id', 'name': 'Test Dataset'}]
        mock_request.return_value = mock_response

        result = self.client.get_dataset('test_id')

        assert result['name'] == 'Test Dataset'

    @patch('sdk.client.configparser.ConfigParser')
    @patch('sdk.client.Path.exists')
    def test_from_config_success(self, mock_exists, mock_config_parser):
        """Test from_config class method"""
        mock_exists.return_value = True

        mock_config = MagicMock()
        mock_config.__contains__ = Mock(return_value=True)
        mock_config.__getitem__ = Mock(return_value={
            'access_token': 'stored_token',
            'expires_at': (datetime.now() + timedelta(hours=1)).isoformat()
        })
        mock_config_parser.return_value = mock_config

        client = APIClient.from_config(Mock())

        assert client.access_token == 'stored_token'
        assert client.token_expires_at is not None

    @patch('sdk.client.Path.exists')
    def test_from_config_no_file(self, mock_exists):
        """Test from_config when credentials file doesn't exist"""
        mock_path = Mock(spec=Path)
        mock_path.exists.return_value = False

        with pytest.raises(AuthenticationError, match="No credentials found"):
            APIClient.from_config(mock_path)

    @patch('sdk.client.configparser.ConfigParser')
    @patch('sdk.client.Path.exists')
    def test_from_config_no_token(self, mock_exists, mock_config_parser):
        """Test from_config with no token in config"""
        mock_exists.return_value = True

        mock_config = MagicMock()
        mock_config.__contains__ = Mock(return_value=True)
        mock_config.__getitem__ = Mock(return_value={'username': 'test'})
        mock_config_parser.return_value = mock_config

        with pytest.raises(AuthenticationError, match="No access token found"):
            APIClient.from_config(Mock())