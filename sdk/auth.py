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
        Authenticate with Epsilon API using username and password to get access token

        Args:
            username: User's username or email
            password: User's password
            auth_url: Full authentication endpoint URL
                     (e.g., "https://app.epsilon-data.org/api/v1/hub/analysis/auth")

        Returns:
            Auth instance with access token

        Raises:
            AuthenticationError: If authentication fails
        """
        payload = {
            "username": username,
            "password": password
        }

        headers = {
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(auth_url, json=payload, headers=headers)
            response.raise_for_status()

            token_data = response.json()
            access_token = token_data.get("access_token")

            if not access_token:
                raise AuthenticationError("No access token received from authentication server")

            # Create Auth instance with token
            auth = cls(access_token=access_token)
            
            # Parse token expiration if available
            if "expires_in" in token_data:
                auth.token_expires_at = datetime.now() + timedelta(seconds=token_data["expires_in"])
            elif "exp" in token_data:
                auth.token_expires_at = datetime.fromtimestamp(token_data["exp"])

            return auth

        except requests.RequestException as e:
            raise AuthenticationError(f"Authentication failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise AuthenticationError(f"Invalid response from authentication server: {str(e)}")


class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass