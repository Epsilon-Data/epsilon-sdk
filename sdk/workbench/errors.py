"""Only deliberately authored messages may cross the workbench boundary."""
from sdk.errors import SDKError
from sdk.llm.base import LLMError


class PublicError(SDKError):
    status_code = 400


class NotFound(PublicError, KeyError):
    status_code = 404

    def __str__(self):
        return self.args[0]


class Conflict(PublicError, ValueError):
    status_code = 409


def public_error(exc):
    if isinstance(exc, LLMError):
        return exc.public_message
    if isinstance(exc, PublicError):
        return str(exc)[:500]
    if isinstance(exc, PermissionError):
        return "Epsilon cannot access a required local file. Check folder permissions and retry."
    if isinstance(exc, OSError):
        return "A local file or service could not be accessed. Check the project and runtime, then retry."
    return "The operation could not complete. Check the project and connection settings, then retry."
