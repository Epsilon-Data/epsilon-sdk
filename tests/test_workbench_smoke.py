"""Boot the default CLI server and cross the real HTTP/session boundary."""
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import requests

from sdk import llm
from sdk.workbench import api, server


def test_default_server_launch_to_saved_preview(dataset_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "load", lambda: llm.AIConfig(api_key=None))
    original = api.build
    monkeypatch.setattr(api, "build", lambda root, record: original(root, state_dir=tmp_path / "state", record=record))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    instance, launch = server.serve(dataset_dir, port, open_browser=False)
    parsed = urlsplit(launch)
    base = "http://" + parsed.netloc
    token = parse_qs(parsed.fragment)["launch"][0]
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not instance.started and time.monotonic() < deadline:
            time.sleep(.02)
        assert instance.started
        with requests.Session() as browser:
            assert browser.get(base + "/api/projects", timeout=5).status_code == 401
            assert browser.get(base + "/api/health", timeout=5).json()["application"] == "epsilon-workbench"
            response = browser.post(base + "/api/bootstrap", json={"token": token}, timeout=5)
            assert "HttpOnly" in response.headers["Set-Cookie"]
            browser.headers["x-epsilon-csrf"] = response.json()["csrf"]
            pid = browser.get(base + "/api/projects", timeout=5).json()["projects"][0]["id"]
            path = base + "/api/projects/" + pid
            plan = browser.post(path + "/plans", json={"analysis": "describe"}, timeout=5).json()
            job = browser.post(path + "/plans/" + plan["id"] + "/run", json={}, timeout=5).json()
            # The same SSE endpoint the browser subscribes to reports the
            # committed artifact and terminates at completion.
            events = browser.get(path + "/jobs/" + job["id"] + "/events", timeout=10)
            assert '"status": "completed"' in events.text
            saved = browser.get(path + "/threads/" + plan["thread_id"], timeout=5).json()
            assert saved["artifacts"][0]["result"]["tables"]
            assert browser.get(base + "/projects/" + pid + "/assistant/" + plan["thread_id"], timeout=5).status_code == 200
            assert browser.get(base + "/assets/app.js", timeout=5).status_code == 200
    finally:
        instance.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()
