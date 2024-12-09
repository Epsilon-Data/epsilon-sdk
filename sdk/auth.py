class Auth:
    def __init__(self, access_key: str = None, secret_key: str = None, api_key: str = None):
        self.access_key = access_key
        self.secret_key = secret_key
        self.api_key = api_key

    def get_aws_credentials(self):
        if not self.access_key or not self.secret_key:
            raise ValueError("AWS credentials are not set.")
        return {"access_key": self.access_key, "secret_key": self.secret_key}

    def get_api_key(self):
        if not self.api_key:
            raise ValueError("API key is not set.")
        return self.api_key
