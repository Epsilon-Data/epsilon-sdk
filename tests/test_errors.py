"""
Tests for error classes
"""
import pytest

from sdk.errors import SDKError, ClientError, DatasetNotFoundError, AuthenticationError


class TestErrors:
    """Test suite for error classes"""

    def test_sdk_error(self):
        """Test SDKError base exception"""
        error = SDKError("Test error message")
        assert str(error) == "Test error message"
        assert isinstance(error, Exception)

    def test_client_error(self):
        """Test ClientError"""
        error = ClientError("Client error occurred")
        assert str(error) == "Client error occurred"
        assert isinstance(error, SDKError)

    def test_dataset_not_found_error(self):
        """Test DatasetNotFoundError"""
        error = DatasetNotFoundError("Dataset xyz not found")
        assert str(error) == "Dataset xyz not found"
        assert isinstance(error, SDKError)

    def test_authentication_error(self):
        """Test AuthenticationError"""
        error = AuthenticationError("Invalid credentials")
        assert str(error) == "Invalid credentials"
        assert isinstance(error, SDKError)

    def test_error_inheritance(self):
        """Test error class inheritance"""
        # All custom errors should inherit from SDKError
        assert issubclass(ClientError, SDKError)
        assert issubclass(DatasetNotFoundError, SDKError)
        assert issubclass(AuthenticationError, SDKError)

    def test_raising_errors(self):
        """Test raising custom errors"""
        with pytest.raises(SDKError) as exc_info:
            raise SDKError("Test SDK error")
        assert "Test SDK error" in str(exc_info.value)

        with pytest.raises(AuthenticationError) as exc_info:
            raise AuthenticationError("Auth failed")
        assert "Auth failed" in str(exc_info.value)
