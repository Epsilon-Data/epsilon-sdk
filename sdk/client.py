import configparser
import os
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
                    # 409 Conflict from the synthetic-data endpoint reports the
                    # archetype columns missing from the current manifest.
                    # The body is untrusted input: only format missingColumns
                    # when it is the documented list shape.
                    if isinstance(error_data, dict):
                        missing_columns = error_data.get('missingColumns')
                        if isinstance(missing_columns, list) and missing_columns:
                            error_message = (
                                f"{error_message} "
                                f"(missing columns: {', '.join(str(c) for c in missing_columns)})"
                            )
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

    def get_card(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the dataset card, or None when this server does not serve one.

        The card is optional metadata: an older hub has no such route, and a
        project whose owner has not authored one has nothing to return. Either
        way the SDK degrades to describing the archetype alone rather than
        failing an init. An authentication failure is a different matter and
        is allowed to propagate.
        """
        endpoint = config.ENDPOINTS['card'].format(dataset_id=dataset_id)
        try:
            response = self._make_request("GET", endpoint)
        except AuthenticationError:
            raise
        except SDKError:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def download_synthetic_data(self, dataset_id: str, dest_path: str) -> Dict[str, Any]:
        """
        Download the archetype-scoped synthetic dataset projection as CSV.

        Streams the response body to dest_path and returns the destination
        path together with the schema hash and dataset version the server
        reported in the response headers.
        """
        endpoint = config.ENDPOINTS['synthetic_data'].format(dataset_id=dataset_id)
        response = self._make_request("GET", endpoint, stream=True)

        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        # Stream the download so large files are not held fully in memory.
        # Write to a temp file and move it into place only on success, so a
        # failed or interrupted download never leaves a partial dest_path.
        tmp_path = f"{dest_path}.part"
        bytes_written = 0
        try:
            with open(tmp_path, 'wb') as csvfile:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        csvfile.write(chunk)
                        bytes_written += len(chunk)

            if bytes_written == 0:
                raise ValueError(f"Downloaded synthetic dataset is empty: {dest_path}")

            os.replace(tmp_path, dest_path)
        except requests.RequestException as e:
            raise SDKError(f"Synthetic dataset download interrupted: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return {
            "path": dest_path,
            "schema_hash": response.headers.get("X-Epsilon-Schema-Hash"),
            "version": response.headers.get("X-Epsilon-Dataset-Version"),
        }

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