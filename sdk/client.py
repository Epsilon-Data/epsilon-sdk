from .auth import Auth
from .session import Session
from .data_reader import DataReader

class SDKClient:
    def __init__(self, access_key: str, secret_key: str, api_base_url: str):
        auth = Auth(access_key, secret_key)
        self.session = Session(auth, api_base_url)
        self.data_reader = DataReader(self.session)

    def get_dataset(self, dataset_id: str):
        return self.data_reader.read_dataset(dataset_id)

    def get_xls_dataset(self, dataset_id: str):
        return self.data_reader.read_xls(dataset_id)

    def list_all_datasets(self):
        return self.data_reader.list_datasets()
