"""
Configuration for Epsilon SDK
"""
import os
from pathlib import Path
from typing import Optional

# Credentials Configuration
CREDENTIALS_DIR = ".epsilon_sdk"
CREDENTIALS_FILE = "credentials.ini"
SERVER_FILE = "server"

# API Configuration
DEFAULT_BASE_URL = "https://app.epsilon-data.org"
TIMEOUT = 30

# Loopback port for `epsilon start`.
DEFAULT_PORT = 7878


def server_path() -> Path:
    return Path.home() / CREDENTIALS_DIR / SERVER_FILE


def saved_server() -> Optional[str]:
    """The server chosen with `epsilon change-server`, if any."""
    try:
        value = server_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def save_server(url: str) -> Path:
    """Remember the server outside the installed package, so upgrades keep it."""
    path = server_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(url + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


# Precedence: a launch-scoped environment override, then the saved choice,
# then the public service.
BASE_URL = (os.environ.get("EPSILON_SERVER_URL") or saved_server() or DEFAULT_BASE_URL).rstrip("/")

# API Endpoints
ENDPOINTS = {
    "auth": "/api/v1/hub/analysis/auth",
    "datasets": "/api/v1/hub/analysis/datasets",
    "dataset": "/api/v1/hub/analysis/datasets/{dataset_id}",
    "synthetic_data": "/api/v1/hub/analysis/datasets/{dataset_id}/synthetic-data"
}
