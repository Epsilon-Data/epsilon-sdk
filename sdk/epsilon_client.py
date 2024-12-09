import requests
from sdk.iepsilon import IEpsilon
from sdk.auth import Auth
from sdk.errors import ClientError

class EpsilonClient(IEpsilon):
    def __init__(self, base_url: str, auth: Auth):
        self.base_url = base_url
        self.auth = auth
        self.api_key = auth.get_api_key()

    def file_list(self):
        try:
            url = f"{self.base_url}/dataset"
            headers = {"x-api-key": f"{self.api_key}"}
            print(headers)
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ClientError(f"REST file list operation failed: {str(e)}")

    def file_detail(self, file_id: str):
        try:
            url = f"{self.base_url}/files/{file_id}"
            headers = {"x-api-key": f"{self.api_key}"}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ClientError(f"REST file detail operation failed: {str(e)}")
