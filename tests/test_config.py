"""
Tests for configuration module
"""
from sdk import config


class TestConfig:
    """Test suite for configuration"""

    def test_base_url(self):
        """Test BASE_URL is set correctly"""
        assert config.BASE_URL == "https://app.epsilon-data.org"
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
        assert 'synthetic_data' in config.ENDPOINTS

        # Check endpoint values
        assert config.ENDPOINTS['auth'] == "/api/v1/hub/analysis/auth"
        assert config.ENDPOINTS['datasets'] == "/api/v1/hub/analysis/datasets"
        assert config.ENDPOINTS['dataset'] == "/api/v1/hub/analysis/datasets/{dataset_id}"
        assert config.ENDPOINTS['synthetic_data'] == "/api/v1/hub/analysis/datasets/{dataset_id}/synthetic-data"

    def test_endpoint_formatting(self):
        """Test endpoint formatting with parameters"""
        dataset_endpoint = config.ENDPOINTS['dataset'].format(dataset_id='test_123')
        assert dataset_endpoint == "/api/v1/hub/analysis/datasets/test_123"

        synthetic_endpoint = config.ENDPOINTS['synthetic_data'].format(dataset_id='test_123')
        assert synthetic_endpoint == "/api/v1/hub/analysis/datasets/test_123/synthetic-data"

    def test_credentials_config(self):
        """Test credentials configuration"""
        assert config.CREDENTIALS_DIR == ".epsilon_sdk"
        assert config.CREDENTIALS_FILE == "credentials.ini"

def test_saved_server_is_used_at_startup_and_the_environment_still_wins(tmp_path):
    import subprocess, sys
    state = tmp_path / ".epsilon_sdk"
    state.mkdir()
    (state / "server").write_text("https://saved.example\n")
    probe = [sys.executable, "-c", "from sdk import config; print(config.BASE_URL)"]
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    assert subprocess.run(probe, env=env, capture_output=True, text=True, check=True).stdout.strip() == "https://saved.example"
    env["EPSILON_SERVER_URL"] = "https://from-env.example/"
    assert subprocess.run(probe, env=env, capture_output=True, text=True, check=True).stdout.strip() == "https://from-env.example"
    (state / "server").unlink()
    del env["EPSILON_SERVER_URL"]
    assert subprocess.run(probe, env=env, capture_output=True, text=True, check=True).stdout.strip() == "https://app.epsilon-data.org"
