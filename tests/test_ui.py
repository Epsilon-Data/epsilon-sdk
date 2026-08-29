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

from sdk.ui import PAGE, analyses_payload, dataset_payload, make_handler, serve


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

    def test_every_endpoint_the_page_calls_exists(self):
        called = set(re.findall(r'fetch\("(/api/[a-z]+)"', PAGE))
        assert called == {"/api/dataset", "/api/analyses", "/api/session",
                          "/api/chat"}


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
        assert "<title>Epsilon copilot</title>" in body

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
