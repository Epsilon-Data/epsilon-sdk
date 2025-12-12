"""
Tests for CLI commands
"""
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from typer.testing import CliRunner
from sdk.epsilon_cli import app, get_client
from sdk.errors import AuthenticationError

runner = CliRunner()


class TestCLI:
    """Test suite for CLI commands"""

    @patch('sdk.epsilon_cli.APIClient')
    @patch('sdk.epsilon_cli.CONFIG_PATH')
    def test_login_success(self, mock_config_path, mock_api_client):
        """Test successful login command"""
        # Setup mocks
        mock_config_path.exists.return_value = False
        mock_client = Mock()
        mock_client.access_token = 'test_token_123'
        mock_client.token_expires_at = datetime.now() + timedelta(hours=1)
        mock_api_client.return_value = mock_client

        # Run command
        result = runner.invoke(app, ['login'], input='testuser\ntestpass\n')

        # Assertions
        assert result.exit_code == 0
        mock_client.authenticate.assert_called_once_with('testuser', 'testpass')

    @patch('sdk.epsilon_cli.APIClient')
    def test_login_authentication_error(self, mock_api_client):
        """Test login with authentication error"""
        mock_client = Mock()
        mock_client.authenticate.side_effect = AuthenticationError("Invalid credentials")
        mock_api_client.return_value = mock_client

        result = runner.invoke(app, ['login'], input='testuser\ntestpass\n')

        assert result.exit_code == 1
        assert "Authentication failed" in result.output

    @patch('sdk.epsilon_cli.get_client')
    def test_datasets_command(self, mock_get_client):
        """Test datasets command"""
        mock_client = Mock()
        mock_client.get_datasets.return_value = [
            {'datasetId': 'dataset_1', 'packageId': 'package_1', 'name': 'Dataset 1', 'lastModified': '2024-01-01T10:00:00Z'},
            {'datasetId': 'dataset_2', 'packageId': 'package_2', 'name': 'Dataset 2', 'lastModified': '2024-01-02T10:00:00Z'}
        ]
        mock_get_client.return_value = mock_client

        result = runner.invoke(app, ['datasets'])

        assert result.exit_code == 0
        assert "dataset_1" in result.output  # Check dataset ID
        assert "dataset_2" in result.output  # Check dataset ID
        assert "package_1" in result.output  # Check package ID
        assert "package_2" in result.output  # Check package ID
        mock_client.get_datasets.assert_called_once()

    @patch('sdk.epsilon_cli.get_client')
    def test_datasets_error(self, mock_get_client):
        """Test datasets command with error"""
        mock_client = Mock()
        mock_client.get_datasets.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        result = runner.invoke(app, ['datasets'])

        assert result.exit_code == 1
        assert ("Error" in result.output or "error" in result.output)

    @patch('sdk.epsilon_cli.get_client')
    @patch('sdk.epsilon_cli.os.path.exists')
    @patch('sdk.epsilon_cli.os.makedirs')
    @patch('builtins.open')
    @patch('sdk.epsilon_cli.generate_csv_dummy_data')
    @patch('sdk.epsilon_cli.compile_arch')
    @patch('sdk.epsilon_cli.yaml.dump')
    def test_init_command(self, mock_yaml_dump, mock_compile_arch, mock_generate_csv,
                          mock_open, mock_makedirs, mock_exists, mock_get_client):
        """Test init command creates project structure"""
        # Setup mocks
        mock_exists.return_value = False  # project.yml doesn't exist
        mock_client = Mock()
        mock_client.get_datasets.return_value = [
            {'datasetId': 'test_dataset', 'packageId': 'test_package'}
        ]
        mock_client.get_dataset.return_value = {
            'id': 'test_dataset',
            'name': 'Test Dataset',
            'schema': {'properties': {'field1': {'type': 'string'}}}
        }
        mock_get_client.return_value = mock_client

        result = runner.invoke(app, ['init', 'test_dataset'])

        assert result.exit_code == 0
        assert "✓ Created generated/archetype.json" in result.output
        assert "✓ Created generated/data.csv" in result.output
        assert "✓ Created generated/models.py" in result.output
        assert "✓ Created project.yml" in result.output
        assert "✓ Created main.py template" in result.output
        assert "Project initialized successfully!" in result.output

        # Verify calls
        mock_client.get_datasets.assert_called_once()
        mock_client.get_dataset.assert_called_once_with('test_dataset')
        assert mock_makedirs.call_count >= 1  # Creates generated directory
        assert mock_generate_csv.call_count == 1
        assert mock_compile_arch.call_count == 1

    @patch('sdk.epsilon_cli.os.path.exists')
    def test_init_command_project_exists(self, mock_exists):
        """Test init command when project already exists"""
        mock_exists.return_value = True  # project.yml exists

        result = runner.invoke(app, ['init', 'test_dataset'])

        assert result.exit_code == 1
        assert "Project already initialized" in result.output


    @patch('sdk.epsilon_cli.os.path.exists')
    @patch('sdk.epsilon_cli.yaml.safe_load')
    @patch('builtins.open')
    @patch('sdk.epsilon_cli.subprocess.run')
    def test_run_command(self, mock_subprocess, mock_open, mock_yaml_load, mock_exists):
        """Test run command executes project script"""
        # Mock project exists
        mock_exists.side_effect = lambda path: path == "project.yml" or path == "main.py"
        mock_yaml_load.return_value = {'entry_point': 'main.py'}

        # Mock successful script execution
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Script output"
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result

        result = runner.invoke(app, ['run'])

        assert result.exit_code == 0
        assert "Running main.py locally..." in result.output
        assert "✓ Script completed successfully" in result.output

    @patch('sdk.epsilon_cli.os.path.exists')
    def test_run_command_no_project(self, mock_exists):
        """Test run command when not in project directory"""
        mock_exists.return_value = False

        result = runner.invoke(app, ['run'])

        assert result.exit_code == 1
        assert "Not in an Epsilon project directory" in result.output

    @patch('sdk.epsilon_cli.os.path.exists')
    @patch('sdk.epsilon_cli.os.remove')
    @patch('shutil.rmtree')
    def test_clean_command(self, mock_rmtree, mock_remove, mock_exists):
        """Test clean command removes project files"""
        # Mock files exist
        mock_exists.return_value = True

        result = runner.invoke(app, ['clean'])

        assert result.exit_code == 0
        assert "Cleaned:" in result.output
        # Should remove files and directories
        assert mock_remove.call_count >= 1
        assert mock_rmtree.call_count >= 1

    @patch('sdk.epsilon_cli.os.path.exists')
    @patch('builtins.open')
    @patch('sdk.epsilon_cli.yaml.safe_load')
    @patch('shutil.copytree')
    @patch('shutil.copy2')
    @patch('sdk.epsilon_cli.subprocess.run')
    @patch('sdk.epsilon_cli.os.makedirs')
    @patch('sdk.epsilon_cli.yaml.dump')
    def test_build_command(self, mock_yaml_dump, mock_makedirs, mock_subprocess,
                           mock_copy2, mock_copytree, mock_yaml_load, mock_open, mock_exists):
        """Test build command creates deployment package"""
        # Mock project exists
        mock_exists.side_effect = lambda path: path in ["project.yml", "main.py", "generated"]
        mock_yaml_load.return_value = {
            'entry_point': 'main.py',
            'dataset_id': 'test_dataset',
            'package_id': 'test_package'
        }

        # Mock pip freeze
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "package1==1.0.0\npackage2==2.0.0"
        mock_subprocess.return_value = mock_result

        result = runner.invoke(app, ['build'])

        assert result.exit_code == 0
        assert "Building analysis package from: main.py" in result.output
        assert "Dataset: test_dataset (test_package)" in result.output
        assert "Analysis package built successfully!" in result.output

    @patch('sdk.epsilon_cli.os.path.exists')
    def test_build_command_no_project(self, mock_exists):
        """Test build command when not in project directory"""
        mock_exists.return_value = False

        result = runner.invoke(app, ['build'])

        assert result.exit_code == 1
        assert "Not in an Epsilon project directory" in result.output

    def test_version_command(self):
        """Test version command"""
        result = runner.invoke(app, ['version'])

        assert result.exit_code == 0

    @patch('sdk.epsilon_cli.APIClient.from_config')
    def test_get_client_function(self, mock_from_config):
        """Test get_client helper function"""
        mock_client = Mock()
        mock_from_config.return_value = mock_client

        client = get_client()

        assert client == mock_client
        mock_from_config.assert_called_once()

    @patch('sdk.epsilon_cli.CONFIG_PATH')
    @patch('sdk.epsilon_cli.configparser.ConfigParser')
    def test_status_command_logged_in(self, mock_config_parser, mock_config_path):
        """Test status command with logged in user"""
        mock_config_path.exists.return_value = True

        # Mock config
        mock_config = Mock()
        mock_config.__contains__ = Mock(return_value=True)
        mock_config.__getitem__ = Mock(return_value={
            'username': 'testuser'
        })
        mock_config_parser.return_value = mock_config

        result = runner.invoke(app, ['status'])

        assert result.exit_code == 0
        assert "Epsilon SDK Status" in result.output
        assert "Server:" in result.output
        assert "Logged in as: testuser" in result.output

    @patch('sdk.epsilon_cli.CONFIG_PATH')
    def test_status_command_not_logged_in(self, mock_config_path):
        """Test status command with no credentials"""
        mock_config_path.exists.return_value = False

        result = runner.invoke(app, ['status'])

        assert result.exit_code == 0
        assert "Epsilon SDK Status" in result.output
        assert "Not logged in" in result.output
        assert "Run 'epsilon login'" in result.output

    @patch('sdk.epsilon_cli.CONFIG_PATH')
    @patch('sdk.epsilon_cli.configparser.ConfigParser')
    def test_status_command_no_default_section(self, mock_config_parser, mock_config_path):
        """Test status command with config file but no default section"""
        mock_config_path.exists.return_value = True

        # Mock config without default section
        mock_config = Mock()
        mock_config.__contains__ = Mock(return_value=False)  # No "default" section
        mock_config_parser.return_value = mock_config

        result = runner.invoke(app, ['status'])

        assert result.exit_code == 0
        assert "No credentials found" in result.output
        assert "Run 'epsilon login' to authenticate" in result.output

    @patch('builtins.open')
    @patch('sdk.epsilon_cli.Path')
    def test_change_server_command_success(self, mock_path, mock_open):
        """Test successful server change"""
        # Mock file operations
        mock_file = Mock()
        mock_file.read.return_value = 'BASE_URL = "https://old-server.com"'
        mock_open.return_value.__enter__.return_value = mock_file

        result = runner.invoke(app, ['change-server', 'https://new-server.com'])

        assert result.exit_code == 0
        assert "Server updated to: https://new-server.com" in result.output
        assert "You'll need to login again" in result.output

    def test_change_server_command_invalid_url(self):
        """Test change-server with invalid URL"""
        result = runner.invoke(app, ['change-server', 'invalid-url'])

        assert result.exit_code == 1
        assert "Please provide a valid URL" in result.output

    def test_change_server_command_missing_url(self):
        """Test change-server without URL argument"""
        result = runner.invoke(app, ['change-server'])

        assert result.exit_code == 2  # Typer exit code for missing argument

    @patch('builtins.open')
    @patch('sdk.epsilon_cli.Path')
    def test_change_server_command_file_error(self, mock_path, mock_open):
        """Test change-server with file operation error"""
        # Mock file read to raise exception
        mock_open.side_effect = Exception("File error")

        result = runner.invoke(app, ['change-server', 'https://new-server.com'])

        assert result.exit_code == 1
        assert "Failed to update server" in result.output