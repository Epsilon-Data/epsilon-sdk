"""Local Docker sign-in must not overwrite the normal account or API target."""
import json
import os
import runpy
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from sdk import config, credentials
from sdk.workbench.service import Workbench


@pytest.mark.parametrize("override,expected", [
    (None, "https://app.epsilon-data.org"),
    ("http://localhost:3334/", "http://localhost:3334"),
])
def test_server_environment_is_scoped_to_the_process(monkeypatch, override, expected):
    original = Path(config.__file__).read_bytes()
    if override is None:
        monkeypatch.delenv("EPSILON_SERVER_URL", raising=False)
    else:
        monkeypatch.setenv("EPSILON_SERVER_URL", override)
    assert runpy.run_path(config.__file__)["BASE_URL"] == expected
    assert Path(config.__file__).read_bytes() == original


def test_workbench_and_cli_share_only_the_selected_credentials(tmp_path, monkeypatch):
    local = tmp_path / "local" / "credentials.ini"
    default = tmp_path / "researcher" / ".epsilon_sdk" / "credentials.ini"
    default.parent.mkdir(parents=True)
    default.write_text("production-placeholder")
    monkeypatch.setenv("EPSILON_CREDENTIALS_PATH", str(local))
    expanduser = os.path.expanduser
    monkeypatch.setattr(os.path, "expanduser", lambda path: str(default.parent.parent)
                        if path == "~" else expanduser(path))
    monkeypatch.setattr(config, "BASE_URL", "http://localhost:3334")
    bench = Workbench(tmp_path)
    assert bench.credentials_path == local
    assert bench.state_dir == default.parent
    client = SimpleNamespace(base_url=config.BASE_URL, access_token="local-placeholder",
                             token_expires_at=datetime.now() + timedelta(minutes=5))
    credentials.save_client(client, "Local researcher")
    assert local.stat().st_mode & 0o777 == 0o600
    assert default.read_text() == "production-placeholder"

    env = dict(os.environ, EPSILON_SERVER_URL="http://localhost:3334")
    output = subprocess.check_output([
        sys.executable, "-c",
        "import json; from sdk.epsilon_cli import CONFIG_PATH, get_client; "
        "client = get_client(); print(json.dumps([str(CONFIG_PATH), client.base_url, client.is_authenticated()]))",
    ], env=env, text=True)
    assert json.loads(output) == [str(local), "http://localhost:3334", True]
    credentials.sign_out(bench.credentials_path)
    assert not local.exists()
    assert default.read_text() == "production-placeholder"


def test_explicit_test_workspace_keeps_its_own_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("EPSILON_CREDENTIALS_PATH", str(tmp_path / "outside.ini"))
    state = tmp_path / "state"
    assert Workbench(tmp_path, state_dir=state).credentials_path == state / "credentials.ini"
