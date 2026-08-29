"""
Tests for the agent's tools.

Several of these encode mistakes a real model made driving this toolbox:
passing every column as a list, nesting {"fields": [...]}, naming a module
"describe.py" when it lives in analyses/. A tool a model cannot drive is a tool
that burns turns, so each of those has to fail with a message that says what to
do instead -- or not fail at all.
"""
import json
import os

import pytest

from sdk.tools import ToolError, Toolbox, build_tools


# A stand-in for the codegen output: dot-path attribute access over CSV rows,
# which is the API every generated snippet targets.
MODELS = '''
import csv, os

COLUMNS = ["admissions.time", "admissions.type", "patient.gender",
           "patient.age", "diagnoses.icd_code", "diagnoses.icd_version"]


class Group(object):
    def __init__(self, row, prefix):
        self._row, self._prefix = row, prefix

    def __getattr__(self, name):
        return self._row.get(self._prefix + "." + name)


class Record(object):
    def __init__(self, row):
        self._row = row

    def __getattr__(self, name):
        return Group(self._row, name)


class DatasetWrapper(object):
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        for row in self.rows:
            yield Record(row)


def create_dataset(csv_file=None):
    path = csv_file or os.path.join("generated", "data.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        return DatasetWrapper(list(csv.DictReader(fh)))
'''


@pytest.fixture
def project(dataset_dir):
    """dataset_dir plus the generated models a snippet imports."""
    generated = dataset_dir / "generated"
    (generated / "__init__.py").write_text("", encoding="utf-8")
    (generated / "models.py").write_text(MODELS, encoding="utf-8")
    (dataset_dir / "main.py").write_text(
        "def main():\n    return {'ok': 1}\n", encoding="utf-8")
    return dataset_dir


@pytest.fixture
def box(project, profile):
    return Toolbox(str(project), profile)


class TestPathSafety:
    def test_reading_outside_the_project_is_refused(self, box):
        with pytest.raises(ToolError) as exc:
            box.read_file("../../../etc/passwd")
        assert "outside the project" in str(exc.value)

    def test_absolute_paths_are_refused(self, box):
        with pytest.raises(ToolError) as exc:
            box.read_file("/etc/passwd")
        assert "must be relative" in str(exc.value)

    def test_generated_is_read_only(self, box):
        with pytest.raises(ToolError) as exc:
            box.write_file("generated/models.py", "x = 1")
        assert "generated" in str(exc.value)

    def test_writing_inside_the_project_works(self, box, project):
        box.write_file("analyses/thing.py", "x = 1\n")
        assert (project / "analyses" / "thing.py").exists()


class TestForgivingPaths:
    """A model names a file the way the last tool result printed it."""

    def test_run_analysis_finds_a_bare_name_in_analyses(self, box, project):
        box.generate_analysis("describe")
        out = box.run_analysis("describe.py")
        assert "FAILED" not in out

    def test_read_file_finds_a_bare_name_in_analyses(self, box):
        box.generate_analysis("describe")
        assert "UNIT OF ANALYSIS" in box.read_file("describe.py")

    def test_a_genuinely_missing_file_says_what_to_do(self, box):
        with pytest.raises(ToolError) as exc:
            box.run_analysis("nope.py")
        assert "list_files" in str(exc.value)


class TestFieldArgument:
    """The `fields` argument is what a model gets wrong most often."""

    def test_a_list_value_is_rejected_with_guidance(self, box):
        with pytest.raises(ToolError) as exc:
            box.check_analysis("cross_tab", {"rows": ["a", "b"]})
        message = str(exc.value)
        assert "single field path as a string" in message
        assert "cross_tab takes: cols, rows" in message

    def test_a_non_object_is_rejected_with_guidance(self, box):
        with pytest.raises(ToolError) as exc:
            box.check_analysis("cross_tab", "patient.gender")
        assert "must be an object mapping" in str(exc.value)

    def test_empty_fields_are_treated_as_absent(self, box):
        assert json.loads(box.check_analysis("cross_tab", {}))["status"] == "FEASIBLE"

    def test_an_unknown_analysis_lists_the_real_ones(self, box):
        with pytest.raises(ToolError) as exc:
            box.check_analysis("regression")
        assert "cross_tab" in str(exc.value)


class TestVerdictsCannotBeBypassed:
    def test_generating_a_blocked_analysis_is_refused(self, box):
        with pytest.raises(ToolError) as exc:
            box.generate_analysis("prevalence")
        message = str(exc.value)
        assert "not available" in message
        assert "Tell the researcher this" in message

    def test_check_analysis_reports_the_matcher_verdict(self, box):
        payload = json.loads(box.check_analysis("prevalence"))
        assert payload["status"] == "BLOCKED"
        assert payload["blockers"]
        assert payload["unlock"]


class TestProfiling:
    def test_returns_aggregates_and_no_rows(self, box):
        report = json.loads(box.profile_field("patient.gender"))
        assert report["rows"] == 4000
        assert report["distinct"] == 2
        assert all(set(l) == {"value", "n"} for l in report["levels_above_threshold"])

    def test_rare_levels_are_suppressed(self, project, box):
        """A level below the threshold must not be readable one value at a
        time through repeated profiling."""
        (project / "generated" / "data.csv").write_text(
            "patient.gender\n" + "M\n" * 400 + "X\n", encoding="utf-8")
        report = json.loads(box.profile_field("patient.gender"))
        assert [l["value"] for l in report["levels_above_threshold"]] == ["M"]
        assert report["levels_suppressed"] == 1

    def test_profiling_the_local_projection_is_allowed(self, box):
        """The owner flag went with the card: what is profiled here is the
        synthetic projection on this machine, in aggregate."""
        report = json.loads(box.profile_field("patient.gender"))
        assert report["distinct"] == 2

    def test_an_unknown_field_is_refused(self, box):
        with pytest.raises(ToolError) as exc:
            box.profile_field("patient.ssn")
        assert "not a field" in str(exc.value)


class TestWriteFeedback:
    def test_writing_leaky_code_reports_it_immediately(self, box):
        out = box.write_file("analyses/bad.py",
                             "from generated.models import create_dataset\n"
                             "for record in create_dataset():\n"
                             "    print(record)\n")
        assert "would block a build" in out
        assert "per-record" in out

    def test_writing_clean_code_is_quiet(self, box):
        out = box.write_file("analyses/ok.py", "x = 1\n")
        assert "block a build" not in out


class TestSchemas:
    def test_every_tool_has_an_object_schema(self, box):
        for tool in build_tools(box):
            assert tool.spec.schema["type"] == "object"
            assert tool.spec.description

    def test_analysis_arguments_are_enumerated(self, box):
        tools = dict((t.spec.name, t) for t in build_tools(box))
        enum = tools["check_analysis"].spec.schema["properties"]["analysis"]["enum"]
        assert "prevalence" in enum and "cross_tab" in enum

    def test_field_arguments_are_enumerated(self, box):
        tools = dict((t.spec.name, t) for t in build_tools(box))
        enum = tools["profile_field"].spec.schema["properties"]["field"]["enum"]
        assert "patient.gender" in enum


class TestTruncationIsLoud:
    """A quietly clipped result gets summarised as though it were whole, and
    the gaps get filled from earlier context. That is how a model ends up
    reporting figures it never saw."""

    def test_a_short_result_is_untouched(self):
        from sdk.tools import _truncate
        assert _truncate("hello") == "hello"

    def test_a_long_result_is_marked_incomplete(self):
        from sdk.tools import _truncate
        out = _truncate("x" * 50000, limit=100)
        assert out.startswith("[INCOMPLETE RESULT]")
        assert "Do not summarise" in out
        assert "END OF VISIBLE PORTION" in out

    def test_the_real_sizes_are_stated(self):
        from sdk.tools import _truncate
        out = _truncate("x" * 500, limit=100)
        assert "first 100 of 500" in out
        assert "400 characters not shown" in out


class TestChartExtraction:
    """A chart has to come from the released result, not from the model. The
    assistant could otherwise describe a chart it never computed."""

    def test_a_distribution_becomes_a_series(self):
        from sdk.tools import chartable
        c = chartable({"fields": {"patient.gender": {
            "top": [{"value": "F", "n": 3752}, {"value": "M", "n": 1536}],
            "levels_not_shown": 0}}})
        assert c["title"] == "Distribution of patient.gender"
        assert c["groups"][0]["pairs"] == [("F", 3752), ("M", 1536)]

    def test_a_table_groups_by_its_first_column(self):
        from sdk.tools import chartable
        c = chartable({"table": [
            {"sex": "F", "type": "A", "n": 10}, {"sex": "F", "type": "B", "n": 20},
            {"sex": "M", "type": "A", "n": 30}]})
        assert "Counts by sex" == c["title"]
        assert len(c["groups"]) == 2

    def test_a_series_over_periods_is_drawn(self):
        from sdk.tools import chartable
        c = chartable({"series": [{"period": "2020", "n": 12},
                                  {"period": "2021", "n": 30}]})
        assert c["groups"][0]["pairs"] == [("2020", 12), ("2021", 30)]

    def test_suppressed_cells_are_counted_not_drawn(self):
        from sdk.tools import chartable
        c = chartable({"series": [{"period": "2020", "n": 12},
                                  {"period": "2021", "n": None}]})
        assert c["groups"][0]["pairs"] == [("2020", 12)]
        assert c["held"] == 1

    def test_bars_are_capped(self):
        from sdk.tools import chartable, MAX_BARS
        c = chartable({"series": [{"period": str(i), "n": i}
                                  for i in range(MAX_BARS + 20)]})
        assert len(c["groups"][0]["pairs"]) == MAX_BARS

    def test_nothing_chartable_returns_none(self):
        from sdk.tools import chartable
        assert chartable({"unit": "record", "n_rows": 5}) is None
        assert chartable("not a result") is None

    def test_running_an_analysis_captures_its_chart(self, box):
        box.generate_analysis("describe")
        assert box.charts == []
        box.run_analysis("describe.py")
        assert len(box.charts) == 1
        assert box.charts[0]["source"] == "analyses/describe.py"
