import requests
import pandas as pd
from io import StringIO, BytesIO

from session import Session
from .errors import DatasetNotFoundError

class DataReader:
    def __init__(self, session: Session):
        self.session = session

    def read_dataset(self, dataset_id: str):
        self.session.ensure_valid_session()
        headers = self.session.auth.get_headers()
        url = f"{self.session.api_base_url}/datasets/{dataset_id}/download"
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise DatasetNotFoundError(f"Dataset with ID {dataset_id} not found.")

        return pd.read_csv(StringIO(response.text))

    def list_datasets(self):
        self.session.ensure_valid_session()
        headers = self.session.auth.get_headers()
        url = f"{self.session.api_base_url}/datasets"
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise DatasetNotFoundError("Failed to retrieve datasets list.")
        
        return response.json()

    def read_xls(self, dataset_id: str):
        self.session.ensure_valid_session()
        headers = self.session.auth.get_headers()
        url = f"{self.session.api_base_url}/datasets/{dataset_id}/download"
        
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise DatasetNotFoundError(f"Dataset with ID {dataset_id} not found.")

        return pd.read_excel(BytesIO(response.content))
