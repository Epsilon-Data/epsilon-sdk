import configparser
from pathlib import Path
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from .errors import SDKError, AuthenticationError
from . import config


class APIClient:
    """API client for Epsilon services."""

    def __init__(self):
        self.base_url = config.BASE_URL.rstrip('/')
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self.timeout = config.TIMEOUT

    def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate and store access token."""
        url = f"{self.base_url}{config.ENDPOINTS['auth']}"
        payload = {"username": username, "password": password}

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)

            # Check for error response
            if not response.ok:
                try:
                    error_data = response.json()
                    error_message = error_data.get('message', error_data.get('error', 'Authentication failed'))
                    raise AuthenticationError(f"{error_message}")
                except (ValueError, KeyError):
                    response.raise_for_status()

            auth_data = response.json()
            self.access_token = auth_data.get("access_token")

            if not self.access_token:
                raise AuthenticationError("No access token received")

            # Set expiration if provided
            if "expires_in" in auth_data:
                self.token_expires_at = datetime.now() + timedelta(seconds=auth_data["expires_in"])

            return auth_data

        except requests.RequestException as e:
            # Handle connection errors
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_message = error_data.get('message', error_data.get('error', str(e)))
                    raise AuthenticationError(f"{error_message}")
                except (ValueError, KeyError, AttributeError):
                    raise AuthenticationError(f"Authentication failed: {e}")
            raise AuthenticationError(f"Authentication failed: {e}")

    def is_authenticated(self) -> bool:
        """Check if client has valid authentication."""
        return (
            self.access_token is not None and
            (self.token_expires_at is None or datetime.now() < self.token_expires_at)
        )

    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated request."""
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated")

        url = f"{self.base_url}{endpoint}"
        headers = kwargs.get("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        kwargs["headers"] = headers
        kwargs.setdefault("timeout", self.timeout)

        try:
            response = requests.request(method, url, **kwargs)

            # Check for error response
            if not response.ok:
                try:
                    error_data = response.json()
                    error_message = error_data.get('message', error_data.get('error', str(error_data)))
                    raise SDKError(f"{error_message}")
                except (ValueError, KeyError):
                    # If response is not JSON or doesn't have expected fields
                    response.raise_for_status()

            return response
        except requests.RequestException as e:
            # Handle connection errors
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_message = error_data.get('message', error_data.get('error', str(error_data)))
                    raise SDKError(f"{error_message}")
                except (ValueError, KeyError, AttributeError):
                    raise SDKError(f"Request failed: {e}")
            raise SDKError(f"Request failed: {e}")

    def get_datasets(self) -> List[Dict[str, Any]]:
        """Get available datasets."""
        response = self._make_request("GET", config.ENDPOINTS['datasets'])
        return response.json()

    def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """Get specific dataset."""
        endpoint = config.ENDPOINTS['dataset'].format(dataset_id=dataset_id)
        response = self._make_request("GET", endpoint)
        data = response.json()

        # Handle array response
        if isinstance(data, list) and data:
            return data[0]
        return data

    @classmethod
    def from_config(cls, config_path: Path):
        """Create client from stored credentials."""
        if not config_path.exists():
            raise AuthenticationError("No credentials found. Please login first.")

        config = configparser.ConfigParser()
        config.read(config_path)

        # Use 'default' section or first available section
        section = 'default' if 'default' in config else config.sections()[0] if config.sections() else None
        if not section:
            raise AuthenticationError("No credentials found")

        creds = config[section]
        access_token = creds.get("access_token")

        if not access_token:
            raise AuthenticationError("No access token found. Please login first.")

        client = cls()  # Uses default from config
        client.access_token = access_token

        # Set token expiration
        expires_at_str = creds.get('expires_at')
        if expires_at_str:
            try:
                client.token_expires_at = datetime.fromisoformat(expires_at_str)
            except ValueError:
                pass

        return client