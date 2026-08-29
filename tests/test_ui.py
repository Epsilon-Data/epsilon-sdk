"""
Tests for the local web interface.

The page is a string embedded in a Python module, so nothing type-checks it and
a stray quote turns the whole interface blank while the server still returns
200. These tests exist mostly to make that impossible.
"""
import json
import re
import shutil
import subprocess
import urllib.request

import pytest

from sdk.ui import (PAGE, analyses_payload, dataset_payload, generate,
                    make_handler, run_module, serve, status_payload)


class TestPageIsValid:
    def test_the_script_parses(self):
        """A syntax error here renders an empty page against a 200 response."""
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        script = re.search(r"<script>(.*?)</script>", PAGE, re.S).group(1)
        proc = subprocess.run([node, "--check", "-"], input=script.encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.returncode == 0, proc.stderr.decode()

    def test_quotes_and_braces_balance(self):
        script = re.search(r"<script>(.*?)</script>", PAGE, re.S).group(1)
        assert script.count("{") == script.count("}")
        assert script.count("(") == script.count(")")

    def test_it_loads_nothing_from_the_network(self):
        """It must work on a machine with no outbound access."""
        head = PAGE.split("<script>")[0]
        assert "src=" not in head
        assert "//fonts." not in PAGE
        assert "cdn" not in PAGE.lower()

    def test_every_endpoint_the_page_calls_is_routed(self):
        """A path the page fetches but the server does not route returns 404
        into a promise, which surfaces as a silently dead button."""
        import inspect

        import sdk.ui as ui
        called = set(re.findall(r'"(/api/[a-z]+)"', PAGE))
        routed = inspect.getsource(ui.make_handler)
        missing = sorted(p for p in called if '"{0}"'.format(p) not in routed)
        assert not missing, missing
        assert len(called) >= 6


class TestPayloads:
    def test_dataset_payload_is_json_serialisable(self, profile):
        payload = json.loads(json.dumps(dataset_payload(profile)))
        assert payload["rows"] == 4000
        assert payload["hasEntityKey"] is False
        assert len(payload["fields"]) == 6

    def test_fields_carry_what_the_page_renders(self, profile):
        field = dataset_payload(profile)["fields"][0]
        for key in ("path", "type", "access", "coverage", "caveats"):
            assert key in field

    def test_analyses_payload_carries_reasons(self, profile):
        analyses = analyses_payload(profile)["analyses"]
        blocked = [m for m in analyses if m["status"] != "FEASIBLE"]
        assert blocked
        assert all(m["blockers"] for m in blocked)


class TestServer:
    @pytest.fixture
    def server(self, profile, dataset_dir):
        server, url = serve(profile, str(dataset_dir), session=None,
                            port=0, open_browser=False)
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield "http://127.0.0.1:{0}".format(server.server_address[1])
        server.shutdown()
        server.server_close()

    def _get(self, url):
        return urllib.request.urlopen(url, timeout=5)

    def test_serves_the_page(self, server):
        body = self._get(server + "/").read().decode()
        assert "<title>Epsilon workspace</title>" in body

    def test_serves_the_dataset(self, server):
        payload = json.load(self._get(server + "/api/dataset"))
        assert payload["rows"] == 4000

    def test_serves_the_analyses(self, server):
        payload = json.load(self._get(server + "/api/analyses"))
        assert len(payload["analyses"]) == 8

    def test_reports_chat_as_unavailable_without_a_model(self, server):
        assert json.load(self._get(server + "/api/session"))["chat"] is False

    def test_chat_without_a_model_explains_rather_than_failing(self, server):
        request = urllib.request.Request(
            server + "/api/chat", data=json.dumps({"message": "hi"}).encode(),
            headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=5)
        assert exc.value.code == 400
        assert "epsilon ai login" in json.load(exc.value)["error"]

    def test_binds_to_loopback_only(self, profile, dataset_dir):
        server, _url = serve(profile, str(dataset_dir), session=None,
                             port=0, open_browser=False)
        assert server.server_address[0] == "127.0.0.1"
        server.server_close()

    def test_unknown_paths_404(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            self._get(server + "/etc/passwd")
        assert exc.value.code == 404


class TestGuidedSteps:
    """The page walks the README workflow, and each step is detected from the
    project rather than remembered -- so doing a step in the terminal, or
    reloading, loses nothing."""

    def test_status_detects_a_project(self, profile, dataset_dir):
        assert status_payload(profile, str(dataset_dir))["hasProject"] is True

    def test_status_reports_no_project_before_init(self, dataset_dir):
        """`epsilon start` runs before init, so a missing profile is normal."""
        assert status_payload(None, str(dataset_dir))["hasProject"] is False

    def test_the_five_setup_steps_are_reported(self, profile, dataset_dir):
        steps = status_payload(profile, str(dataset_dir))["steps"]
        assert [s["key"] for s in steps] == [
            "install", "login", "datasets", "init", "model"]

    def test_install_is_done_because_we_are_running(self, profile, dataset_dir):
        steps = status_payload(profile, str(dataset_dir))["steps"]
        assert steps[0]["done"] is True

    def test_init_is_done_once_a_profile_exists(self, profile, dataset_dir):
        by_key = {s["key"]: s for s in status_payload(profile, str(dataset_dir))["steps"]}
        assert by_key["init"]["done"] is True
        assert "4,000" in by_key["init"]["note"]

    def test_init_is_not_done_without_one(self, dataset_dir):
        by_key = {s["key"]: s for s in status_payload(None, str(dataset_dir))["steps"]}
        assert by_key["init"]["done"] is False

    def test_the_model_step_is_optional(self, profile, dataset_dir):
        by_key = {s["key"]: s for s in status_payload(profile, str(dataset_dir))["steps"]}
        assert by_key["model"]["optional"] is True

    def test_every_step_carries_a_copyable_command(self, profile, dataset_dir):
        for step in status_payload(profile, str(dataset_dir))["steps"]:
            assert step["cmd"].strip()

    def test_status_lists_written_analyses(self, profile, dataset_dir):
        assert status_payload(profile, str(dataset_dir))["analyses"] == []
        generate(profile, str(dataset_dir), "describe")
        assert status_payload(profile, str(dataset_dir))["analyses"] == ["describe.py"]

    def test_status_ignores_the_chart_helper(self, profile, dataset_dir):
        analyses = dataset_dir / "analyses"
        analyses.mkdir(exist_ok=True)
        (analyses / "_charts.py").write_text("", encoding="utf-8")
        assert status_payload(profile, str(dataset_dir))["analyses"] == []

    def test_status_counts_blocking_findings(self, profile, dataset_dir):
        (dataset_dir / "leak.py").write_text(
            "from generated.models import create_dataset\n"
            "for record in create_dataset():\n    print(record)\n",
            encoding="utf-8")
        assert status_payload(profile, str(dataset_dir))["blocking"] >= 1


class TestGenerateAndRun:
    def test_generate_writes_a_feasible_analysis(self, profile, dataset_dir):
        result = generate(profile, str(dataset_dir), "describe")
        assert result["ok"] is True
        assert (dataset_dir / "analyses" / "describe.py").exists()

    def test_generate_refuses_a_blocked_analysis_with_the_reason(self, profile,
                                                                 dataset_dir):
        result = generate(profile, str(dataset_dir), "prevalence")
        assert result["ok"] is False
        assert "entity" in result["message"]

    def test_generate_rejects_an_unknown_analysis(self, profile, dataset_dir):
        assert generate(profile, str(dataset_dir), "nope")["ok"] is False

    def test_run_rejects_a_path(self, dataset_dir):
        """The module name comes from the browser; it must not be a path."""
        result = run_module(str(dataset_dir), "../../etc/passwd")
        assert result["ok"] is False

    def test_run_rejects_a_non_python_name(self, dataset_dir):
        assert run_module(str(dataset_dir), "data.csv")["ok"] is False

    def test_run_reports_a_missing_module(self, dataset_dir):
        assert "does not exist" in run_module(str(dataset_dir), "nope.py")["output"]
