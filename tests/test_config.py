"""
Tests for configuration module
"""
from sdk import config


class TestConfig:
    """Test suite for configuration"""

    def test_base_url(self):
        """Test BASE_URL is set correctly"""
        assert config.BASE_URL == "http://localhost:3334"
        assert isinstance(config.BASE_URL, str)

    def test_timeout(self):
        """Test TIMEOUT is set correctly"""
        assert config.TIMEOUT == 30
        assert isinstance(config.TIMEOUT, int)

    def test_endpoints(self):
        """Test ENDPOINTS dictionary"""
        assert 'auth' in config.ENDPOINTS
        assert 'datasets' in config.ENDPOINTS
        assert 'dataset' in config.ENDPOINTS

        # Check endpoint values
        assert config.ENDPOINTS['auth'] == "/api/v1/hub/analysis/auth"
        assert config.ENDPOINTS['datasets'] == "/api/v1/hub/analysis/datasets"
        assert config.ENDPOINTS['dataset'] == "/api/v1/hub/analysis/datasets/{dataset_id}"

    def test_endpoint_formatting(self):
        """Test endpoint formatting with parameters"""
        dataset_endpoint = config.ENDPOINTS['dataset'].format(dataset_id='test_123')
        assert dataset_endpoint == "/api/v1/hub/analysis/datasets/test_123"

    def test_credentials_config(self):
        """Test credentials configuration"""
        assert config.CREDENTIALS_DIR == ".epsilon_sdk"
        assert config.CREDENTIALS_FILE == "credentials.ini"