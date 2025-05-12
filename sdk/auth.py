import requests
from datetime import datetime, timedelta
import json


class Auth:
    def __init__(self, access_token: str = None):
        self.access_token = access_token
        self.token_expires_at = None

    def get_access_token(self):
        if not self.access_token:
            raise ValueError("Access token is not set.")
        return self.access_token

    def is_token_expired(self):
        """Check if the current token has expired"""
        if not self.token_expires_at:
            return True
        return datetime.now() >= self.token_expires_at

    @classmethod
    def authenticate_with_keycloak(cls, username: str, password: str, auth_url: str):
        """
        Authenticate with Keycloak using username and password to get access token

        Args:
            username: User's username or email
            password: User's password
            auth_url: Full Keycloak token endpoint URL
                     (e.g., "http://localhost:8080/realms/EPSILON/protocol/openid-connect/token")

        Returns:
            Auth instance with access token

        Raises:
            AuthenticationError: If authentication fails
        """
        data = {
            "client_id": "metadata-client",
            "username": username,
            "password": password,
            "grant_type": "password"
        }

        try:
            response = requests.post(auth_url, data=data)
            response.raise_for_status()

            token_data = response.json()
            access_token = token_data.get("access_token")

            if not access_token:
                raise AuthenticationError("No access token received from Keycloak")

            # Create Auth instance with token and expiration time
            auth = cls(access_token=access_token)

            return auth, token_data

        except requests.RequestException as e:
            raise AuthenticationError(f"Authentication failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise AuthenticationError(f"Invalid response from authentication server: {str(e)}")


class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass