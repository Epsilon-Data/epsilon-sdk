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

    def test_no_external_script_or_stylesheet_beyond_fonts(self):
        """A workspace inside a TRE may have no outbound access at all. The
        design asks for IBM Plex, which is allowed to fail: every font stack
        names a system fallback, so the page still renders."""
        head = PAGE.split("<script>")[0]
        assert "<script src=" not in head
        assert "cdn" not in PAGE.lower()
        external = [l for l in head.splitlines()
                    if "href=\"http" in l and "fonts.google" not in l
                    and "fonts.gstatic" not in l]
        assert external == [], external
        assert "system-ui" in PAGE  # the fallback the design declares

    def test_every_font_stack_has_a_local_fallback(self):
        import re as _re
        for stack in _re.findall(r"font-family:\s*([^;\"']+)", PAGE):
            if "IBM Plex" in stack:
                assert ("system-ui" in stack or "sans-serif" in stack
                        or "monospace" in stack), stack

    def test_every_endpoint_the_page_calls_is_routed(self):
        """A path the page fetches but the server does not route returns 404
        into a promise, which surfaces as a silently dead button."""
        import inspect

        import sdk.ui as ui
        called = set(re.findall(r'"(/api/[a-z]+)"', PAGE))
        routed = inspect.getsource(ui.make_handler)
        missing = sorted(p for p in called if '"{0}"'.format(p) not in routed)
        assert not missing, missing
        assert {"/api/status", "/api/dataset", "/api/analyses",
                "/api/chat"} <= called


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

    def test_serves_the_workspace(self, server):
        body = self._get(server + "/workspace").read().decode()
        assert "<title>Epsilon workspace</title>" in body

    def test_serves_the_project_list_at_the_front_door(self, server):
        body = self._get(server + "/").read().decode()
        assert "<title>Epsilon projects</title>" in body

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


class TestDesignFidelity:
    """The page is the design canvas's markup, rendered with live data. These
    guard the seam: if the design is re-exported, the markup changes and the
    bindings it needs must still be supplied."""

    def test_the_markup_is_the_designs_own(self):
        from sdk import ui_page
        assert "IBM Plex" in ui_page.MARKUP
        assert ui_page.MARKUP.count("<sc-for") == 19
        assert ui_page.MARKUP.count("<sc-if") == 27

    def test_the_designs_value_derivation_is_used_unmodified(self):
        from sdk import ui_page
        assert ui_page.RENDER_VALS.startswith("renderVals()")
        assert "verdictStyle" in ui_page.RENDER_VALS

    def test_every_data_method_renderVals_calls_is_implemented(self):
        """renderVals calls into the component; each of those must exist or the
        page renders blank."""
        import re

        from sdk import ui_page
        called = set(re.findall(r"this\.(\w+)\(", ui_page.RENDER_VALS))
        defined = set(re.findall(r"^  (\w+)\(", ui_page.RUNTIME, re.M))
        defined |= {"setState", "go", "pick", "runStep", "send", "renderVals"}
        missing = sorted(called - defined)
        assert not missing, missing

    def test_the_one_hardcoded_count_became_a_binding(self):
        from sdk.ui import PAGE
        assert "{{ grantedCount }} columns" in PAGE
        assert "&mdash; 10 columns" not in PAGE

    def test_fixtures_from_the_mockup_do_not_reach_the_page(self):
        """The design shipped with invented sample content. None of it should
        survive into a page a researcher reads as fact."""
        from sdk.ui import PAGE
        for fixture in ("nordic-icu-2019", "icu_encounter_v3", "41,208",
                        "r.halvorsen@ki.se", "mrn", "clinician_id"):
            assert fixture not in PAGE, fixture


class TestTheMockupsDecorativeParts:
    """The canvas is a design: its chat box is a styled div and its suggestion
    chips reveal canned turns. Both have to become real without disturbing the
    surrounding styles."""

    def test_the_chat_box_is_a_real_input(self):
        from sdk.ui import PAGE
        assert 'id=\\"ask\\"' in PAGE
        assert "placeholder=" in PAGE

    def test_the_placeholder_still_comes_from_the_design(self):
        from sdk.ui import PAGE
        assert "{{ inputHint }}" in PAGE

    def test_a_design_change_fails_loudly_rather_than_silently(self):
        """If the canvas is re-exported and the substitution target moves, the
        build must stop -- not ship a page with no way to type."""
        import pytest as _pytest

        from sdk.ui import _livewire
        with _pytest.raises(RuntimeError) as exc:
            _livewire("<div>a design that changed</div>")
        assert "no longer applies" in str(exc.value)

    def test_typed_text_survives_a_rerender(self):
        """The whole tree is replaced on every state change, so a reply
        arriving mid-sentence must not wipe the box."""
        from sdk import ui_page
        assert "carry" in ui_page.RUNTIME
        assert "document.activeElement" in ui_page.RUNTIME


class TestReplyFormatting:
    """A model answers in markdown; the design renders typed blocks. Without a
    parser a generated script arrives as one unbroken paragraph with literal
    backticks in it."""

    def _parser(self):
        import re
        from sdk import ui_page
        start = ui_page.RUNTIME.index("const FENCE")
        end = ui_page.RUNTIME.index("// The component.")
        return ui_page.RUNTIME[start:end]

    def test_the_parser_ships(self):
        src = self._parser()
        for fn in ("function tidy(", "function pushProse(", "function parseReply("):
            assert fn in src

    def test_fenced_code_becomes_its_own_block(self):
        assert 'kind: "code"' in self._parser()

    def test_a_filename_labels_the_panel(self):
        assert "named[named.length - 1]" in self._parser()

    def test_markdown_markers_are_stripped(self):
        src = self._parser()
        # bold, headings and inline code would otherwise render literally
        assert r"\*\*([^*]+)\*\*" in src
        assert r"^#{1,6}[ \t]*" in src

    def test_paragraphs_are_split(self):
        assert r"split(/\n{2,}/)" in self._parser()

    def test_text_blocks_keep_their_line_breaks(self):
        """Lists collapse onto one line without this."""
        from sdk.ui import PAGE
        assert "white-space: pre-wrap" in PAGE


class TestTableFormatting:
    """A model returns markdown tables. Rendered as text they are a wall of
    pipes; the design has a table block, so use it."""

    def _parser(self):
        from sdk import ui_page
        start = ui_page.RUNTIME.index("const FENCE")
        end = ui_page.RUNTIME.index("// The component.")
        return ui_page.RUNTIME[start:end]

    def test_the_table_parser_ships(self):
        assert "function asTable(" in self._parser()

    def test_a_withheld_cell_is_shown_as_withheld(self):
        """Suppression is the point of the rule, not an empty cell."""
        src = self._parser()
        assert "suppressed|^none$|^null$" in src
        assert "— suppressed" in src

    def test_the_column_count_follows_the_data(self):
        """Only the table's grid becomes dynamic; the stats block below it is
        genuinely four columns and stays as designed."""
        from sdk.ui import PAGE
        assert "{{ b.grid }}" in PAGE
        assert "1.3fr repeat(4, minmax(0, 1fr))" not in PAGE
        assert 'grid: "1.3fr repeat(" + (head.length - 1)' in self._parser()

    def test_a_paragraph_that_is_not_a_table_stays_text(self):
        src = self._parser()
        # the rule row is required, so prose with pipes is not mistaken for one
        assert r"/^\|[\s:|-]+\|$/" in src


class TestProjectRoutes:
    """Creating, opening and forgetting projects over HTTP."""

    @pytest.fixture(autouse=True)
    def isolated_home(self, tmp_path, monkeypatch):
        import os
        home = tmp_path / "home"
        real = os.path.expanduser

        def fake(path):
            if path == "~" or path.startswith("~/"):
                return str(home) + path[1:]
            return real(path)

        monkeypatch.setattr(os.path, "expanduser", fake)

    @pytest.fixture(autouse=True)
    def no_model(self, monkeypatch):
        def refuse():
            raise RuntimeError("no model")
        monkeypatch.setattr("sdk.llm.get_provider", refuse)
        monkeypatch.setattr("sdk.llm.available", lambda: False)

    @pytest.fixture
    def server(self, profile, dataset_dir):
        import threading
        server, _url = serve(profile, str(dataset_dir), session=None,
                             port=0, open_browser=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield "http://127.0.0.1:{0}".format(server.server_address[1])
        server.shutdown()
        server.server_close()

    def _post(self, url, payload):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(request, timeout=5))

    def _post_error(self, url, payload):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=5)
        return exc.value.code, json.load(exc.value)

    def test_lists_no_projects_before_any_are_registered(self, server):
        payload = json.load(urllib.request.urlopen(server + "/api/projects"))
        assert payload["projects"] == []

    def test_registers_a_project(self, server, dataset_dir):
        out = self._post(server + "/api/projects/new",
                         {"name": "Diabetes cohort", "path": str(dataset_dir),
                          "description": "Risk factors"})
        assert out["project"]["name"] == "Diabetes cohort"
        assert out["ready"] is True
        listed = json.load(urllib.request.urlopen(server + "/api/projects"))
        assert listed["projects"][0]["description"] == "Risk factors"
        assert listed["projects"][0]["open"] is True

    def test_refuses_a_path_that_is_not_a_directory(self, server, tmp_path):
        code, body = self._post_error(
            server + "/api/projects/new",
            {"name": "Ghost", "path": str(tmp_path / "nowhere")})
        assert code == 400
        assert "not a directory" in body["error"]

    def test_refuses_a_duplicate_directory(self, server, dataset_dir):
        self._post(server + "/api/projects/new",
                   {"name": "First", "path": str(dataset_dir)})
        code, body = self._post_error(
            server + "/api/projects/new",
            {"name": "Second", "path": str(dataset_dir)})
        assert code == 400
        assert "already registered" in body["error"]

    def test_opens_a_registered_project(self, server, dataset_dir):
        self._post(server + "/api/projects/new",
                   {"name": "Cohort", "path": str(dataset_dir)})
        out = self._post(server + "/api/projects/open", {"id": "cohort"})
        assert out["project"]["id"] == "cohort"
        assert out["ready"] is True

    def test_opening_an_unknown_project_404s(self, server):
        code, _body = self._post_error(server + "/api/projects/open",
                                       {"id": "ghost"})
        assert code == 404

    def test_forgets_a_project_without_touching_the_files(self, server,
                                                          dataset_dir):
        import os
        self._post(server + "/api/projects/new",
                   {"name": "Cohort", "path": str(dataset_dir)})
        assert self._post(server + "/api/projects/forget",
                          {"id": "cohort"})["forgotten"] is True
        assert os.path.isdir(str(dataset_dir))
        listed = json.load(urllib.request.urlopen(server + "/api/projects"))
        assert listed["projects"] == []

    def test_forgetting_an_unknown_project_404s(self, server):
        code, _body = self._post_error(server + "/api/projects/forget",
                                       {"id": "ghost"})
        assert code == 404


class TestCardRoutes:
    """The suggested analyses, and handing one to a session."""

    @pytest.fixture(autouse=True)
    def isolated_home(self, tmp_path, monkeypatch):
        import os
        home = tmp_path / "home"
        real = os.path.expanduser

        def fake(path):
            if path == "~" or path.startswith("~/"):
                return str(home) + path[1:]
            return real(path)

        monkeypatch.setattr(os.path, "expanduser", fake)

    @pytest.fixture(autouse=True)
    def no_model(self, monkeypatch):
        def refuse():
            raise RuntimeError("no model")
        monkeypatch.setattr("sdk.llm.get_provider", refuse)
        monkeypatch.setattr("sdk.llm.available", lambda: False)

    @pytest.fixture
    def server(self, profile, dataset_dir):
        import threading
        server, _url = serve(profile, str(dataset_dir), session=None,
                             port=0, open_browser=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield "http://127.0.0.1:{0}".format(server.server_address[1])
        server.shutdown()
        server.server_close()

    def _post(self, url, payload):
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(request, timeout=5))

    def test_serves_cards_for_the_open_project(self, server):
        payload = json.load(urllib.request.urlopen(server + "/api/cards"))
        assert payload["ready"] is True
        assert payload["cards"]
        for card in payload["cards"]:
            assert card["title"] and card["question"] and card["analysis"]

    def test_says_when_no_model_proposed_them(self, server):
        payload = json.load(urllib.request.urlopen(server + "/api/cards"))
        assert payload["suggested"] is False

    def test_never_offers_a_blocked_analysis(self, server, profile):
        from sdk import catalogue
        feasible = set(m.key for m in catalogue.evaluate(profile) if m.feasible)
        payload = json.load(urllib.request.urlopen(server + "/api/cards"))
        assert all(c["analysis"] in feasible for c in payload["cards"])

    def test_a_card_hands_off_to_a_session(self, server):
        out = self._post(server + "/api/handoff", {"index": 0})
        assert out["url"].startswith("/chat?seed=")
        assert out["title"]

    def test_the_seed_can_be_claimed_once(self, server):
        from sdk import workspace
        out = self._post(server + "/api/handoff", {"index": 0})
        token = out["token"]
        assert workspace.take_seed(token) is not None
        assert workspace.take_seed(token) is None

    def test_an_out_of_range_card_is_refused(self, server):
        request = urllib.request.Request(
            server + "/api/handoff", data=json.dumps({"index": 99}).encode(),
            headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=5)
        assert exc.value.code == 400

    def test_a_typed_question_opens_a_session(self, server):
        from sdk import workspace
        out = self._post(server + "/api/ask",
                         {"question": "What is the age distribution?"})
        seed = workspace.take_seed(out["token"])
        assert seed.question == "What is the age distribution?"
        assert seed.analysis == ""

    def test_an_empty_question_is_refused(self, server):
        request = urllib.request.Request(
            server + "/api/ask", data=json.dumps({"question": "  "}).encode(),
            headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=5)
        assert exc.value.code == 400


class TestProjectsPage:
    """The screen in front of the workspace: pick a cohort, ask it something."""

    def test_the_script_parses(self):
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        script = re.search(r"<script>(.*?)</script>", PROJECTS_PAGE, re.S).group(1)
        proc = subprocess.run([node, "--check", "-"], input=script.encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.returncode == 0, proc.stderr.decode()

    def test_no_external_asset_beyond_fonts(self):
        """A TRE workspace may have no outbound access; fonts fall back."""
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        head = PROJECTS_PAGE.split("<script>")[0]
        assert "<script src=" not in head
        external = [l for l in head.splitlines()
                    if 'href="http' in l and "fonts.google" not in l
                    and "fonts.gstatic" not in l]
        assert external == [], external
        assert "system-ui" in PROJECTS_PAGE

    def test_every_endpoint_it_calls_is_routed(self):
        import inspect

        import sdk.ui as ui
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        called = set(re.findall(r'"(/api/[a-z/]+)"', PROJECTS_PAGE))
        routed = inspect.getsource(ui.make_handler) + inspect.getsource(
            ui.project_route)
        missing = sorted(p for p in called if '"{0}"'.format(p) not in routed)
        assert not missing, missing
        assert {"/api/projects", "/api/cards", "/api/handoff",
                "/api/ask"} <= called

    def test_is_served(self, profile, dataset_dir):
        import threading
        server, _url = serve(profile, str(dataset_dir), session=None,
                             port=0, open_browser=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = "http://127.0.0.1:{0}".format(server.server_address[1])
            body = urllib.request.urlopen(base + "/projects").read().decode()
            assert "<title>Epsilon projects</title>" in body
        finally:
            server.shutdown()
            server.server_close()


class TestEntryPoint:
    """With no project open, the workspace has nothing to describe."""

    @pytest.fixture(autouse=True)
    def isolated_home(self, tmp_path, monkeypatch):
        import os
        home = tmp_path / "home"
        real = os.path.expanduser

        def fake(path):
            if path == "~" or path.startswith("~/"):
                return str(home) + path[1:]
            return real(path)

        monkeypatch.setattr(os.path, "expanduser", fake)

    def _serve(self, profile, directory):
        import threading
        server, _url = serve(profile, str(directory), session=None,
                             port=0, open_browser=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, "http://127.0.0.1:{0}".format(server.server_address[1])

    def test_the_front_door_is_the_project_list(self, profile, dataset_dir):
        """Even with a project open: you choose what you are working on."""
        server, base = self._serve(profile, dataset_dir)
        try:
            body = urllib.request.urlopen(base + "/").read().decode()
            assert "<title>Epsilon projects</title>" in body
        finally:
            server.shutdown()
            server.server_close()

    def test_the_workspace_describes_the_open_project(self, profile,
                                                      dataset_dir):
        server, base = self._serve(profile, dataset_dir)
        try:
            body = urllib.request.urlopen(base + "/workspace").read().decode()
            assert "<title>Epsilon workspace</title>" in body
        finally:
            server.shutdown()
            server.server_close()

    def test_the_workspace_sends_you_back_when_nothing_is_open(self, tmp_path):
        server, base = self._serve(None, tmp_path)
        try:
            body = urllib.request.urlopen(base + "/workspace").read().decode()
            assert "<title>Epsilon projects</title>" in body
        finally:
            server.shutdown()
            server.server_close()

    def test_the_project_detail_offers_the_workspace(self):
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        assert 'href="/workspace"' in PROJECTS_PAGE

    def test_the_landing_view_is_the_list(self):
        """The main page is what you are working on, not one project."""
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        assert 'view: "list"' in PROJECTS_PAGE
        assert "function listHtml()" in PROJECTS_PAGE

    def test_suggesting_waits_until_a_project_is_chosen(self):
        """A model call must not sit in front of the list."""
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        body = PROJECTS_PAGE[PROJECTS_PAGE.index("async function load()"):]
        body = body[:body.index("async function loadCards")]
        assert 'if (state.view === "home") loadCards();' in body

    def test_the_workspace_link_is_hidden_until_there_is_a_projection(self):
        """Otherwise it sends the researcher straight back here."""
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        assert "p.initialised" in PROJECTS_PAGE


class TestSetupSteps:
    """An un-initialised project shows what to do, not what to run."""

    def test_the_page_asks_for_the_steps(self):
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        assert "/api/status" in PROJECTS_PAGE
        assert "stepsHtml" in PROJECTS_PAGE

    def test_steps_replace_the_cards_until_there_is_a_projection(self):
        from sdk.projects_page import PAGE as PROJECTS_PAGE
        assert "p.initialised" in PROJECTS_PAGE
        assert "stepsHtml()" in PROJECTS_PAGE

    def test_the_steps_carry_a_command_and_a_done_flag(self, profile,
                                                       dataset_dir):
        payload = status_payload(profile, str(dataset_dir))
        assert payload["steps"]
        for step in payload["steps"]:
            assert "cmd" in step and "done" in step and "title" in step
