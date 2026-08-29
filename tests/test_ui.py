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
