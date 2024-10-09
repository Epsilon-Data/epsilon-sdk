class Auth:
    def __init__(self, access_key: str, secret_key: str):
        self.access_key = access_key
        self.secret_key = secret_key

    def get_headers(self):
        return {
            'Authorization': f'{self.access_key}:{self.secret_key}',
            'Content-Type': 'application/json'
        }
