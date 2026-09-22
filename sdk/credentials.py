"""Credentials shared by epsilon login and the local browser workspace."""
import configparser
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from sdk.client import APIClient
from sdk.errors import AuthenticationError

_LOCK = RLock()
_REFRESH_FAILURES = {}


def credentials_path():
    configured = os.environ.get("EPSILON_CREDENTIALS_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(os.path.expanduser("~")) / ".epsilon_sdk" / "credentials.ini"


def save_client(client, username, path=None, auth=None):
    """Atomically save the token, never the password, in the CLI's format."""
    path = Path(path) if path is not None else credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _LOCK:
        parser = configparser.ConfigParser(interpolation=None)
        if path.exists():
            parser.read(str(path))
        parser["default"] = {
            "access_token": client.access_token,
            "expires_at": (client.token_expires_at.isoformat()
                           if client.token_expires_at else ""),
            "username": username,
        }
        server = getattr(client, "base_url", None)
        if isinstance(server, str):
            parser["default"]["server_url"] = server.rstrip("/")
        if auth:
            parser["default"].update(auth)
        fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                parser.write(stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, str(path))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def sign_in(username, password, path=None, client_factory=APIClient):
    if not isinstance(username, str) or not username.strip() or not password:
        raise AuthenticationError("Enter your username and password.")
    client = client_factory()
    client.authenticate(username.strip(), password)
    save_client(client, username.strip(), path)
    return client


def status(path=None):
    path = Path(path) if path is not None else credentials_path()
    try:
        client = APIClient.from_config(path)
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(str(path))
        if not client.is_authenticated():
            return {"authenticated": False, "expired": True}
        return {"authenticated": True, "username": parser.get("default", "username", fallback="Researcher"),
                "expires_at": client.token_expires_at.isoformat() if client.token_expires_at else None}
    except (AuthenticationError, OSError, ValueError, configparser.Error):
        return {"authenticated": False, "expired": path.exists()}


def sign_out(path=None):
    path = Path(path) if path is not None else credentials_path()
    with _LOCK:
        if path.exists():
            path.unlink()
        _REFRESH_FAILURES.pop(str(path), None)


def stored_secrets(path=None):
    """Read saved credentials for outbound checks without refreshing or keyring I/O."""
    path = Path(path) if path is not None else credentials_path()
    try:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(path)
        return [parser.get("default", key, fallback="") for key in ("access_token", "refresh_token")]
    except (OSError, ValueError, configparser.Error):
        return []


def refresh_client(client, path, force=False):
    """Serialize refresh rotation with save/sign-out; keep tokens out of UI state."""
    from sdk.sso import refresh, SignInError
    path = Path(path)
    with _LOCK:
        current = APIClient.from_config(path, refresh=False)
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(path)
        auth = dict(parser["default"])
        if current.access_token != client.access_token and current.is_authenticated():
            client.access_token, client.token_expires_at = current.access_token, current.token_expires_at
            return client
        if current.is_authenticated() and not force:
            client.access_token, client.token_expires_at = current.access_token, current.token_expires_at
            return client
        try:
            if (auth.get("auth_method") != "browser" or not auth.get("refresh_token")
                    or datetime.fromisoformat(auth.get("refresh_expires_at", "")) <= datetime.now(timezone.utc)):
                raise AuthenticationError("Your Epsilon session has ended. Please sign in again.")
        except (ValueError, TypeError):
            raise AuthenticationError("Your Epsilon session has ended. Please sign in again.") from None
        stamp = (path.stat().st_mtime_ns, path.stat().st_size)
        failed = _REFRESH_FAILURES.get(str(path))
        if failed and failed[0] == stamp and time.monotonic() - failed[1] < 30:
            raise AuthenticationError("Epsilon sign-in is temporarily unavailable. Please retry.")
        try:
            result = refresh(auth, client.base_url)
        except SignInError as exc:
            if len(_REFRESH_FAILURES) >= 64:
                _REFRESH_FAILURES.clear()
            _REFRESH_FAILURES[str(path)] = (stamp, time.monotonic())
            if exc.kind == "invalid_grant":
                current.token_expires_at = datetime.now(timezone.utc)
                # A revoked SSO session must not be retried on every page visit.
                save_client(current, auth.get("username", "Researcher"), path)
            raise AuthenticationError(exc.public_message) from None
        client.access_token, client.token_expires_at = result["access_token"], result["expires_at"]
        save_client(client, auth.get("username", "Researcher"), path, auth=result["auth"])
        _REFRESH_FAILURES.pop(str(path), None)
        return client
