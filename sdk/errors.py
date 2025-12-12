class SDKError(Exception):
    """Base SDK error"""
    pass


class ClientError(SDKError):
    """API client error"""
    pass


class DatasetNotFoundError(SDKError):
    """Dataset not found error"""
    pass


class AuthenticationError(SDKError):
    """Authentication error"""
    pass