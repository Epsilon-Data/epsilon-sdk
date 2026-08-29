"""
The whole product, booted for real.

Everything else in the suite tests routes and logic in-process. This boots
the actual stack -- uvicorn, the mounted Chainlit app, the materialised
element files -- and drives the researcher's whole path over real HTTP.
The bugs it exists to catch live between the pieces: a route missing from
the server, a file resolved from the wrong directory, a framework quirk
that only bites when everything is up at once.

Needs the chat extra; skipped without it.
"""
import json
import os
import socket
import threading
import time
import urllib.request

import pytest

pytest.importorskip("chainlit")
pytest.importorskip("fastapi")

from tests.conftest import build_dataset  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    real = os.path.expanduser

    def fake(path):
        if path == "~" or path.startswith("~/"):
            return str(home) + path[1:]
        return real(path)

    monkeypatch.setattr(os.path, "expanduser", fake)


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    def refuse(*a, **kw):
        raise RuntimeError("no model in the smoke test")
    monkeypatch.setattr("sdk.llm.get_provider", refuse)
    monkeypatch.setattr("sdk.llm.available", lambda: False)


def _free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as res:
        return res.status, res.read().decode("utf-8", "replace")


def _post(url, payload, timeout=10):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.status, json.loads(res.read())


def test_the_researchers_whole_path(tmp_path, monkeypatch):
    from sdk import webapp, workspace
    from sdk.workspace import Workspace

    cohort = build_dataset(tmp_path / "cohort")
    monkeypatch.setenv("EPSILON_PROJECT_DIR", str(cohort))

    # -- boot the real server, exactly as `epsilon start` does ----------
    space = Workspace(str(tmp_path))          # started outside any project
    port = _free_port()
    server, base = webapp.serve(space, port, open_browser=False)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                _get(base + "api/projects", timeout=2)
                break
            except Exception:
                time.sleep(0.3)
        else:
            pytest.fail("the server never came up")

        # -- the front door is the list, empty for a new researcher -----
        status, body = _get(base)
        assert status == 200
        assert "<title>Epsilon projects</title>" in body

        # -- create a project against a real folder ----------------------
        status, out = _post(base + "api/projects/new", {
            "name": "Smoke cohort", "path": str(cohort),
            "description": "Booted for real."})
        assert status == 200
        assert out["ready"] is True
        pid = out["project"]["id"]

        # -- the detail page has a real URL ------------------------------
        status, body = _get(base + "projects/" + pid)
        assert status == 200
        assert "<title>Epsilon projects</title>" in body

        # -- cards answer instantly, and never offer blocked work --------
        status, body = _get(base + "api/cards?fast=1")
        assert status == 200
        cards = json.loads(body)
        assert cards["ready"] is True
        assert cards["cards"]
        assert all(c["analysis"] not in
                   ("prevalence", "logistic", "group_compare")
                   for c in cards["cards"])

        # -- a card becomes a seeded session -----------------------------
        status, out = _post(base + "api/handoff", {"card": cards["cards"][0]})
        assert status == 200
        assert out["url"].startswith("/chat?seed=")
        seed = workspace.take_seed(out["token"])
        assert seed is not None
        assert seed.project_dir == str(cohort)

        # -- the workspace is per-project --------------------------------
        status, body = _get(base + "workspace?p=" + pid)
        assert status == 200
        assert "<title>Epsilon workspace</title>" in body

        # -- the chat is mounted and its chart element is served ---------
        status, body = _get(base + "chat/")
        assert status == 200
        status, body = _get(base + "chat/public/elements/BarChart.jsx")
        assert status == 200
        assert "BarChart" in body or "props" in body
    finally:
        server.should_exit = True
        thread.join(timeout=15)
