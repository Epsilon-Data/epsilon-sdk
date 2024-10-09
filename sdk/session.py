import requests

from auth import Auth
from .errors import InvalidSessionError

class Session:
    def __init__(self, auth: Auth, api_base_url: str):
        self.auth = auth
        self.api_base_url = api_base_url
        self.is_valid = self.validate_keys()

    def validate_keys(self):
        headers = self.auth.get_headers()
        try:
            response = requests.get(f"{self.api_base_url}/validate", headers=headers)
            response.raise_for_status()
            return True
        except requests.HTTPError:
            return False

    def ensure_valid_session(self):
        if not self.is_valid:
            raise InvalidSessionError("Session is invalid. Please check API keys.")