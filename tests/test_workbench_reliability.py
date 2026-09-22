"""Regressions for local saves, concurrency, request boundaries and recovery."""
import asyncio
import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sdk import llm
from sdk.workbench import analysis, kernel
from sdk.workbench.errors import PublicError
from sdk.workbench.middleware import LocalBoundary
from sdk.workbench.security import LocalSessions, check_outbound
from sdk.workbench.store import notebook_cells
from tests.conftest import finished
@pytest.mark.parametrize("source", ["risk-adjusted_mortality", "# password: required", "Authorization: required", "api_key = 'a-real-looking-secret-12345'"])
def test_local_saves_do_not_run_outbound_checks_or_keyring(workspace, monkeypatch, source):
    w = workspace
    monkeypatch.setattr(w.bench, "known_secrets", Mock(side_effect=AssertionError("No secret resolution on local save")))
    response = w.browser.put(w.path + "/notebooks/main", json={"revision": 0, "cells": [{"source": source}]})
    assert response.status_code == 200
    assert response.json()["cells"][0]["source"] == source


def test_secret_filter_boundaries_and_placeholders():
    for text in ("risk-adjusted_mortality", "# password: required", "Authorization: required"):
        assert check_outbound(text) == text
    for text in ("sk-1234567890abcdefghijkl", "password='a-real-secret-1234567890'", "Authorization: Bearer abc12345", "AKIAABCDEFGHIJKLMNOP"):
        with pytest.raises(PublicError):
            check_outbound(text)


@pytest.mark.parametrize("error", [KeyError("secret-column"), ValueError("private diagnostic"), PermissionError("/private/host/secrets"), OSError("/Users/researcher/project-private")])
def test_unexpected_errors_are_not_resource_misses_or_raw_ui_text(workspace, monkeypatch, error):
    w = workspace
    monkeypatch.setattr(w.bench, "detail", Mock(side_effect=error))
    response = w.browser.get(w.path)
    assert response.status_code == 500
    assert str(error) not in response.text
    job = w.bench.jobs.submit(w.pid, "test", "failure", lambda _: (_ for _ in ()).throw(error))
    deadline = time.monotonic() + 2
    while job.status in ("running", "queued") and time.monotonic() < deadline:
        time.sleep(.01)
    assert job.status == "failed" and str(error) not in json.dumps(job.payload())


def test_expired_local_session_can_renew_without_account_signin(workspace):
    w = workspace
    session = next(iter(w.app.state.local_sessions.sessions.values()))
    session["created"] -= 86401
    assert w.browser.get(w.path).json()["code"] == "local_session_required"
    recovery = w.browser.get("/api/session").json()
    assert recovery["recoverable"] and not recovery["unlocked"]
    assert w.browser.post("/api/session/renew", json={}, headers={"x-epsilon-csrf": "wrong"}).status_code == 400
    assert w.browser.post("/api/session/renew", json={}).status_code == 200
    assert w.browser.get(w.path).status_code == 200


def test_public_asgi_body_replay_supports_fragmented_and_bounded_requests():
    async def exercise(chunks):
        seen, replies = [], []
        async def inner(scope, receive, send):
            seen.append(await receive())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        queue = iter({"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1} for i, chunk in enumerate(chunks))
        async def receive():
            return next(queue)
        async def send(message):
            replies.append(message)
        scope = {"type": "http", "method": "POST", "path": "/api/bootstrap", "scheme": "http", "query_string": b"", "headers": [(b"host", b"127.0.0.1:8000"), (b"content-type", b"application/json")], "server": ("127.0.0.1", 8000)}
        await LocalBoundary(inner, LocalSessions())(scope, receive, send)
        return seen, replies
    seen, replies = asyncio.run(exercise([b'{"token":', b'"value"', b'}']))
    assert seen == [{"type": "http.request", "body": b'{"token":"value"}', "more_body": False}]
    seen, replies = asyncio.run(exercise([b" " * 1100000, b" " * 1100000]))
    assert not seen and replies[0]["status"] == 413


@pytest.mark.parametrize("identifier", ['evil%22%3E', '%3Cscript%3E', '%2E%2E', 'a' * 81])
def test_notebook_path_identifiers_are_validated(workspace, identifier):
    assert workspace.browser.get(workspace.path + "/notebooks/" + identifier).status_code in (404, 422)


def test_cell_ids_are_unique_when_positional_cells_mix_with_existing_ids():
    cells = notebook_cells([{"id": "cell-1", "source": "a"}, {"source": "b"}, {"source": "c"}])
    assert len({c["id"] for c in cells}) == 3


def test_input_hash_is_reused_until_the_file_identity_changes(workspace, monkeypatch):
    w = workspace
    analysis._digests.clear()
    reads = Mock(wraps=analysis.load_inputs)
    monkeypatch.setattr(analysis, "load_inputs", reads)
    first = analysis.input_digest(w.root)
    for _ in range(8):
        assert analysis.input_digest(w.root) == first
    assert reads.call_count == 1
    path = w.root / "generated/data.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    assert analysis.input_digest(w.root) != first
    assert reads.call_count == 2


@pytest.mark.parametrize("change", ["later", "earlier", "executed"])
def test_completed_output_survives_concurrent_save(workspace, change):
    w = workspace
    saved = w.bench.store.save_notebook(w.pid, "race", [{"id": str(i), "kind": "code", "source": "print(1)"} for i in range(3)], 0)
    newer = copy.deepcopy(saved)
    newer["cells"][{"earlier": 0, "executed": 1, "later": 2}[change]]["source"] = "print(2)"
    w.bench.store.save_notebook(w.pid, "race", newer["cells"], newer["revision"])
    result = w.bench.store.attach_execution(w.pid, "race", saved, 1, {"text": "completed output", "reviewed": False})
    assert len(w.bench.store.objects(w.pid, "notebook_run")) == 1
    assert result["run"]["output"]["text"] == "completed output"
    assert result["saved"] == (change != "executed")
    if change != "executed":
        assert result["notebook"]["cells"][1]["output"].get("stale", False) == (change == "earlier")
    assert w.bench.store.objects(w.pid, "artifact") == []


def test_cold_kernel_does_not_hold_registry_and_stop_cancels_start(tmp_path, monkeypatch):
    started, release = Event(), Event()
    instance = SimpleNamespace(process=Mock(), close=Mock())
    instance.process.poll.return_value = None
    def create(*_):
        started.set()
        assert release.wait(2)
        return instance
    monkeypatch.setattr(kernel, "Kernel", create)
    monkeypatch.setattr(kernel, "runtime_status", lambda **_: {"available": True})
    manager = kernel.Kernels(tmp_path)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(manager.get, "p", "n", tmp_path)
        assert started.wait(1)
        before = time.monotonic()
        assert manager.status("p", "n")["starting"]
        manager.stop("p", "n")
        assert time.monotonic() - before < .2
        release.set()
        with pytest.raises(PublicError, match="startup was stopped"):
            future.result(timeout=2)
    assert not manager.items and not manager.starting
    instance.close.assert_called_once()


def test_docker_discovery_is_cached_single_flight_and_nonblocking(monkeypatch):
    started, release = Event(), Event()
    def probe():
        started.set()
        assert release.wait(2)
        return {"available": False, "reason": "Docker stopped"}
    monkeypatch.setattr(kernel, "_runtime_cache", None)
    mocked = Mock(side_effect=probe)
    monkeypatch.setattr(kernel, "_probe_runtime", mocked)
    assert kernel.runtime_status(wait=False)["checking"]
    assert started.wait(1)
    for _ in range(10):
        assert kernel.runtime_status(wait=False)["checking"]
    release.set()
    assert kernel.runtime_status()["reason"] == "Docker stopped"
    assert kernel.runtime_status()["reason"] == "Docker stopped"
    mocked.assert_called_once()


def test_keyring_resolution_cached_and_replaced_entry_removed(workspace, monkeypatch):
    w = workspace
    ring = Mock()
    ring.get_password.return_value = "fixture-model-key-123456789"
    monkeypatch.setattr(llm.config, "keyring_backend", lambda: ring)
    old = {"provider": "openai", "model": "old", "base_url": None, "tier": "A"}
    w.bench.store.set_setting("ai", old)
    for _ in range(10):
        assert w.bench.ai_config().api_key == "fixture-model-key-123456789"
    ring.get_password.assert_called_once()
    w.bench.configure_ai("openai", "new", "", "new-credential-12345678", True)
    ring.delete_password.assert_called_once_with("epsilon-workbench", w.bench._ai_account(old))


def test_ui_plan_creation_uses_service_audit_without_fabricated_user_message(workspace):
    w = workspace
    plan = w.browser.post(w.path + "/plans", json={"analysis": "describe"}).json()
    assert w.bench.store.thread(w.pid, plan["thread_id"])["messages"] == []
    events = [json.loads(line) for line in (w.bench.state_dir / "audit" / (w.pid + ".jsonl")).read_text().splitlines()]
    assert any(e["kind"] == "plan.created" and e["plan_id"] == plan["id"] for e in events)


def test_config_changes_cannot_pair_a_new_credential_with_an_old_endpoint(workspace, monkeypatch):
    w = workspace
    entered, release = Event(), Event()
    old = {"provider": "openai-compatible", "model": "old", "base_url": "https://old.example/v1", "tier": "A"}
    w.bench.store.set_setting("ai", old)
    def read(*_):
        entered.set()
        assert release.wait(2)
        return "old-endpoint-credential"
    ring = Mock()
    ring.get_password.side_effect = read
    monkeypatch.setattr(llm.config, "keyring_backend", lambda: ring)
    with ThreadPoolExecutor() as pool:
        reading = pool.submit(w.bench.ai_config)
        assert entered.wait(1)
        changing = pool.submit(w.bench.configure_ai, "openai-compatible", "new", "https://new.example/v1", "new-endpoint-credential", False)
        release.set()
        config = reading.result(timeout=2)
        changing.result(timeout=2)
    assert (config.base_url, config.api_key) == (old["base_url"], "old-endpoint-credential")
    current = w.bench.ai_config()
    assert (current.base_url, current.api_key) == ("https://new.example/v1", "new-endpoint-credential")


def test_state_permission_failure_is_not_reported_as_a_busy_port(monkeypatch):
    from typer.testing import CliRunner
    from sdk import epsilon_cli
    from sdk.workbench import server
    monkeypatch.setattr(server, "available", lambda: True)
    monkeypatch.setattr(server, "serve", Mock(side_effect=PermissionError(13, "denied", "/private/state")))
    port_taken = Mock()
    monkeypatch.setattr(epsilon_cli, "_port_taken", port_taken)
    result = CliRunner().invoke(epsilon_cli.app, ["start", "--no-browser"])
    assert result.exit_code == 1 and "state directory" in result.stdout
    assert "/private/state" not in result.stdout
    port_taken.assert_not_called()


# -- audit regressions ------------------------------------------------------

def test_job_payload_is_a_snapshot_that_worker_writes_cannot_change():
    from sdk.workbench.jobs import Job
    job = Job("p", "chat", "p:thread:t", metadata={"request": {"question": "q"}})
    snapshot = job.payload()
    job.remember("plans", {"key": "plan-1"})
    job.remember("draft_ids", ["d1"])
    snapshot["metadata"]["request"]["question"] = "changed by a reader"
    # A payload being serialised on another thread never sees these writes,
    # and a reader cannot reach back into the job either.
    assert "plans" not in snapshot["metadata"]
    assert job.metadata == {"request": {"question": "q"}, "plans": {"key": "plan-1"}, "draft_ids": ["d1"]}
    drafts = ["d2"]
    job.remember("draft_ids", drafts)
    drafts.append("d3")
    assert job.metadata["draft_ids"] == ["d2"]


def test_progress_stream_reads_the_database_off_the_event_loop(workspace):
    import threading
    w = workspace
    job = w.bench.jobs.submit(w.pid, "test", "stream", lambda _: {"done": True})
    finished(w.bench, w.pid, job.payload())
    reads, original = [], w.bench.jobs.get
    def tracked(*args):
        reads.append(threading.current_thread().name)
        return original(*args)
    w.bench.jobs.get = tracked
    with w.browser.stream("GET", w.path + "/jobs/" + job.id + "/events") as response:
        body = "".join(response.iter_text())
    assert '"status": "completed"' in body
    # The event loop runs in the test client's portal thread; reads must not.
    assert reads and all(name.startswith(("AnyIO worker", "ThreadPoolExecutor")) for name in reads), reads
    assert w.browser.get(w.path + "/jobs/unknown-job/events").status_code == 404


def test_a_cell_without_an_id_never_inherits_another_cells_identity(workspace):
    w = workspace
    path = w.path + "/notebooks/main"
    first = w.browser.put(path, json={"revision": 0, "cells": [{"id": "cell-a", "source": "a = 1"}]}).json()
    w.bench.store.save_notebook(w.pid, "main", [dict(first["cells"][0], output={"text": "old", "reviewed": False})], first["revision"])
    # A new id-less cell inserted before the existing one, with the same source.
    saved = w.browser.put(path, json={"revision": first["revision"] + 1,
                                     "cells": [{"source": "a = 1"}, {"id": "cell-a", "source": "a = 1"}]})
    assert saved.status_code == 200, saved.text
    new, kept = saved.json()["cells"]
    assert new["id"] not in ("cell-a",) and kept["id"] == "cell-a"
    assert new["output"] is None and kept["output"]["text"] == "old"


def test_a_slow_runtime_recheck_refuses_with_a_message_not_a_crash(tmp_path, monkeypatch):
    # A re-check still running reports the old "available" status, which has no reason.
    monkeypatch.setattr(kernel, "runtime_status", lambda **_: {"available": True, "image_id": "sha256:x", "checking": True})
    with pytest.raises(PublicError, match="Checking the notebook runtime"):
        kernel.Kernel(tmp_path, tmp_path)


def test_the_api_key_never_appears_in_a_printed_configuration():
    config = llm.AIConfig(provider="openai", model="gpt-4o", api_key="sk-audit-secret-1234567890")
    assert "sk-audit-secret" not in repr(config) and "sk-audit-secret" not in str(config)
    assert config.api_key == "sk-audit-secret-1234567890"
