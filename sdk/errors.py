class SDKError(Exception):
    pass

class InvalidSessionError(SDKError):
    pass

class DatasetNotFoundError(SDKError):
    pass
