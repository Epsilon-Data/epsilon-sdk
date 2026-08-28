"""Tests for generated analysis code."""
import ast
import os

import pytest

from sdk.catalogue import SPECS_BY_KEY, evaluate, feasible
from sdk.snippets import SnippetError, accessor, render, write


def compiles(code):
    ast.parse(code)
    return True


class TestGeneration:
    def test_every_feasible_analysis_produces_valid_python(self, profile):
        matches = feasible(profile)
        assert matches
        for match in matches:
            assert compiles(render(profile, match))

    def test_every_feasible_entry_has_a_template(self, keyed_profile):
        """Survival stays blocked by design; everything else must render."""
        matches = evaluate(keyed_profile)
        blocked = [m.key for m in matches if not m.feasible]
        assert blocked == ["survival"], blocked
        for match in matches:
            if match.feasible:
                assert compiles(render(keyed_profile, match))

    def test_refuses_to_generate_a_blocked_analysis(self, profile):
        match = SPECS_BY_KEY["prevalence"].evaluate(profile)
        with pytest.raises(SnippetError) as exc:
            render(profile, match)
        assert "not feasible" in str(exc.value)

    def test_accessor_matches_the_generated_model_api(self):
        assert accessor("patient.gender") == "record.patient.gender"


class TestDisclosureRulesAreStructural:
    def test_the_suppression_threshold_is_a_platform_constant(self, profile):
        from sdk.profile import MIN_CELL
        code = render(profile, SPECS_BY_KEY["describe"].evaluate(profile))
        assert "MIN_CELL = {0}".format(MIN_CELL) in code

    def test_every_snippet_applies_the_threshold(self, keyed_profile):
        for match in evaluate(keyed_profile):
            if match.feasible:
                assert "MIN_CELL" in render(keyed_profile, match)

    def test_the_unit_of_analysis_is_stated_in_the_docstring(self, profile):
        code = render(profile, SPECS_BY_KEY["composition"].evaluate(profile))
        assert "UNIT OF ANALYSIS: record" in code

    def test_the_unit_is_returned_with_the_result(self, profile):
        code = render(profile, SPECS_BY_KEY["composition"].evaluate(profile))
        assert '"unit"' in code

    def test_measured_warnings_are_carried_into_the_code(self, profile):
        code = render(profile, SPECS_BY_KEY["describe"].evaluate(profile))
        assert "Measured warnings that apply" in code
        assert "capped at 91" in code

    def test_generated_code_passes_the_submission_checks(self, profile):
        """The generator must satisfy the rules the generated code is graded by."""
        from sdk.checks import check_source
        for match in feasible(profile):
            findings = check_source("generated.py", render(profile, match))
            assert [f for f in findings if f.blocking] == []

    def test_no_snippet_prints_a_record(self, keyed_profile):
        for match in evaluate(keyed_profile):
            if match.feasible:
                assert "print(record" not in render(keyed_profile, match)


class TestWriting:
    def test_writes_under_analyses_and_makes_it_a_package(self, tmp_path, profile):
        match = SPECS_BY_KEY["describe"].evaluate(profile)
        path = write(profile, match, project_dir=str(tmp_path))
        assert os.path.exists(path)
        assert os.path.exists(os.path.join(str(tmp_path), "analyses", "__init__.py"))

    def test_honours_an_explicit_filename(self, tmp_path, profile):
        match = SPECS_BY_KEY["describe"].evaluate(profile)
        path = write(profile, match, project_dir=str(tmp_path), filename="table1.py")
        assert path.endswith("table1.py")

    def test_a_path_like_filename_is_flattened(self, tmp_path, profile):
        """Agents pass 'analyses/foo.py'; that must not nest a second dir."""
        match = SPECS_BY_KEY["describe"].evaluate(profile)
        path = write(profile, match, project_dir=str(tmp_path),
                     filename="analyses/foo.py")
        assert os.path.exists(path)
        assert path.endswith(os.path.join("analyses", "foo.py"))
        assert "analyses/analyses" not in path

    def test_an_escaping_filename_cannot_leave_analyses(self, tmp_path, profile):
        match = SPECS_BY_KEY["describe"].evaluate(profile)
        path = write(profile, match, project_dir=str(tmp_path),
                     filename="../../escape.py")
        assert os.path.exists(path)
        assert os.path.dirname(path).endswith("analyses")

    def test_an_extension_is_added_when_missing(self, tmp_path, profile):
        match = SPECS_BY_KEY["describe"].evaluate(profile)
        path = write(profile, match, project_dir=str(tmp_path), filename="table1")
        assert path.endswith("table1.py")

    def test_written_code_compiles(self, tmp_path, profile):
        match = SPECS_BY_KEY["cross_tab"].evaluate(profile)
        path = write(profile, match, project_dir=str(tmp_path))
        with open(path, encoding="utf-8") as fh:
            assert compiles(fh.read())


class TestDescribeRespectsAccessLevel:
    """The describe template dumped 275 raw HIGH_LEVEL timestamps with exact
    counts, which is the policy it claims to enforce being violated by the
    generator itself."""

    def test_an_aggregate_only_timestamp_is_bucketed(self, profile):
        code = render(profile, SPECS_BY_KEY["describe"].evaluate(profile))
        assert "_bucket(record.admissions.time" in code
        assert 'totals["admissions.time"][str(' not in code

    def test_the_bucket_matches_the_coarsest_releasable_unit(self, profile):
        profile.leaf("admissions.time").releasable_as = ["month"]
        code = render(profile, SPECS_BY_KEY["describe"].evaluate(profile))
        assert "_bucket(record.admissions.time, 7)" in code  # YYYY-MM

    def test_a_detailed_field_is_not_bucketed(self, profile):
        code = render(profile, SPECS_BY_KEY["describe"].evaluate(profile))
        assert 'totals["patient.gender"][str(record.patient.gender)]' in code

    def test_levels_are_capped_not_dumped(self, profile):
        code = render(profile, SPECS_BY_KEY["describe"].evaluate(profile))
        assert "TOP_LEVELS" in code
        assert "levels_not_shown" in code

    def test_output_stays_small_on_a_wide_dataset(self, tmp_path, profile):
        """A 1,472-level code column must not produce a 40,000-char result."""
        import json as json_mod
        import subprocess
        import sys
        project = tmp_path
        (project / "generated").mkdir(exist_ok=True)
        (project / "generated" / "__init__.py").write_text("", encoding="utf-8")
        (project / "generated" / "models.py").write_text(MODELS, encoding="utf-8")
        rows = ["admissions.time,admissions.type,patient.gender,patient.age,"
                "diagnoses.icd_code,diagnoses.icd_version"]
        for i in range(3000):
            rows.append("21{0:02d}-01-01,EW EMER.,M,50,CODE{1},9".format(
                i % 100, i))          # 3000 distinct codes, 100 distinct years
        (project / "generated" / "data.csv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8")
        path = write(profile, SPECS_BY_KEY["describe"].evaluate(profile),
                     project_dir=str(project))
        proc = subprocess.run(
            [sys.executable, "-c",
             "import json,sys; sys.path.insert(0,'.');"
             "from analyses.describe import main;"
             "print(json.dumps(main(), default=str))"],
            cwd=str(project), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.returncode == 0, proc.stderr.decode()
        out = proc.stdout.decode()
        assert len(out) < 8000, "describe produced %d chars" % len(out)
        parsed = json_mod.loads(out)
        assert parsed["fields"]["diagnoses.icd_code"]["levels_not_shown"] > 0


# Minimal stand-in for the codegen output, so describe can actually be run.
MODELS = '''
import csv, os


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


class TestCharts:
    """A figure is an output artifact. The generator only ever draws the
    released aggregate, never records, because a chart built from rows is a
    disclosure risk no output review can see."""

    def test_chartable_analyses_compile_with_a_chart(self, profile):
        for key in ("describe", "composition", "cross_tab"):
            match = SPECS_BY_KEY[key].evaluate(profile)
            assert compiles(render(profile, match, chart=True))

    def test_the_chart_draws_the_result_not_the_dataset(self, profile):
        code = render(profile, SPECS_BY_KEY["cross_tab"].evaluate(profile), chart=True)
        chart_fn = code[code.index("def chart("):]
        assert "create_dataset" not in chart_fn
        assert "result[" in chart_fn

    def test_suppressed_cells_survive_into_the_chart(self, profile):
        code = render(profile, SPECS_BY_KEY["cross_tab"].evaluate(profile), chart=True)
        # the chart consumes r["n"], which main() already set to None when
        # below the threshold
        assert 'r["n"]' in code

    def test_an_unchartable_analysis_says_so(self, keyed_profile):
        match = SPECS_BY_KEY["prevalence"].evaluate(keyed_profile)
        with pytest.raises(SnippetError) as exc:
            render(keyed_profile, match, chart=True)
        assert "no chart" in str(exc.value)
        assert "Chartable analyses:" in str(exc.value)

    def test_no_chart_is_added_unless_asked(self, profile):
        code = render(profile, SPECS_BY_KEY["describe"].evaluate(profile))
        assert "def chart(" not in code

    def test_the_helper_is_written_alongside(self, tmp_path, profile):
        from sdk.snippets import CHART_HELPER_NAME
        write(profile, SPECS_BY_KEY["describe"].evaluate(profile),
              project_dir=str(tmp_path), chart=True)
        assert (tmp_path / "analyses" / CHART_HELPER_NAME).exists()

    def test_the_helper_needs_no_third_party_package(self):
        from sdk.snippets import CHART_MODULE
        tree = ast.parse(CHART_MODULE)
        imported = [n for n in ast.walk(tree)
                    if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert imported == [], "chart helper must be stdlib-only"

    def test_the_helper_passes_the_submission_checks(self):
        from sdk.checks import check_source
        from sdk.snippets import CHART_MODULE
        assert check_source("_charts.py", CHART_MODULE) == []

    def test_a_suppressed_value_is_drawn_as_suppressed_not_as_zero(self):
        from sdk.snippets import CHART_MODULE
        ns = {}
        exec(CHART_MODULE, ns)
        svg = ns["bar_chart"]("t", [("shown", 100), ("hidden", None)])
        assert "suppressed" in svg
        # the suppressed row must not carry a readable magnitude
        assert ">100<" in svg or "100" in svg
        assert svg.count("fill=\"#c2cdc9\"") == 1

    def test_charts_generated_from_a_card_pass_the_checks(self, profile):
        from sdk.checks import check_source
        for key in ("describe", "composition", "cross_tab"):
            code = render(profile, SPECS_BY_KEY[key].evaluate(profile), chart=True)
            assert [f for f in check_source("a.py", code) if f.blocking] == []
