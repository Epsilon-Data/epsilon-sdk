class SDKError(Exception):
    pass
class ClientError(SDKError):
    pass
class DatasetNotFoundError(SDKError):
    pass