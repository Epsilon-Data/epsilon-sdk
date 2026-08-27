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
    def test_every_feasible_analysis_produces_valid_python(self, card):
        matches = feasible(card)
        assert matches
        for match in matches:
            assert compiles(render(card, match))

    def test_every_catalogue_entry_has_a_template(self, unblocked_card):
        matches = evaluate(unblocked_card)
        assert all(m.feasible for m in matches), \
            [(m.key, m.blockers) for m in matches if not m.feasible]
        for match in matches:
            assert compiles(render(unblocked_card, match))

    def test_refuses_to_generate_a_blocked_analysis(self, card):
        match = SPECS_BY_KEY["prevalence"].evaluate(card)
        with pytest.raises(SnippetError) as exc:
            render(card, match)
        assert "not feasible" in str(exc.value)

    def test_accessor_matches_the_generated_model_api(self):
        assert accessor("patient.gender") == "record.patient.gender"


class TestDisclosureRulesAreStructural:
    def test_the_suppression_threshold_comes_from_the_card(self, card_json):
        from sdk.card import Card
        card_json["policy"]["minCell"] = 25
        card = Card.from_json(card_json)
        code = render(card, SPECS_BY_KEY["describe"].evaluate(card))
        assert "MIN_CELL = 25" in code

    def test_every_snippet_applies_the_threshold(self, unblocked_card):
        for match in evaluate(unblocked_card):
            assert "MIN_CELL" in render(unblocked_card, match)

    def test_the_unit_of_analysis_is_stated_in_the_docstring(self, card):
        code = render(card, SPECS_BY_KEY["composition"].evaluate(card))
        assert "UNIT OF ANALYSIS: diagnosis_record" in code

    def test_the_unit_is_returned_with_the_result(self, card):
        code = render(card, SPECS_BY_KEY["composition"].evaluate(card))
        assert '"unit"' in code

    def test_card_warnings_are_carried_into_the_code(self, card):
        code = render(card, SPECS_BY_KEY["describe"].evaluate(card))
        assert "Card warnings that apply" in code
        assert "recorded as 91" in code

    def test_generated_code_passes_the_submission_checks(self, card):
        """The generator must satisfy the rules the generated code is graded by."""
        from sdk.checks import check_source
        for match in feasible(card):
            findings = check_source("generated.py", render(card, match))
            assert [f for f in findings if f.blocking] == []

    def test_no_snippet_prints_a_record(self, unblocked_card):
        for match in evaluate(unblocked_card):
            code = render(unblocked_card, match)
            assert "print(record" not in code


class TestWriting:
    def test_writes_under_analyses_and_makes_it_a_package(self, tmp_path, card):
        match = SPECS_BY_KEY["describe"].evaluate(card)
        path = write(card, match, project_dir=str(tmp_path))
        assert os.path.exists(path)
        assert os.path.exists(os.path.join(str(tmp_path), "analyses", "__init__.py"))

    def test_honours_an_explicit_filename(self, tmp_path, card):
        match = SPECS_BY_KEY["describe"].evaluate(card)
        path = write(card, match, project_dir=str(tmp_path), filename="table1.py")
        assert path.endswith("table1.py")

    def test_a_path_like_filename_is_flattened(self, tmp_path, card):
        """Agents pass 'analyses/foo.py'; that must not nest a second dir."""
        match = SPECS_BY_KEY["describe"].evaluate(card)
        path = write(card, match, project_dir=str(tmp_path),
                     filename="analyses/foo.py")
        assert os.path.exists(path)
        assert path.endswith(os.path.join("analyses", "foo.py"))
        assert "analyses/analyses" not in path

    def test_an_escaping_filename_cannot_leave_analyses(self, tmp_path, card):
        match = SPECS_BY_KEY["describe"].evaluate(card)
        path = write(card, match, project_dir=str(tmp_path),
                     filename="../../escape.py")
        assert os.path.exists(path)
        assert os.path.dirname(path).endswith("analyses")

    def test_an_extension_is_added_when_missing(self, tmp_path, card):
        match = SPECS_BY_KEY["describe"].evaluate(card)
        path = write(card, match, project_dir=str(tmp_path), filename="table1")
        assert path.endswith("table1.py")

    def test_written_code_compiles(self, tmp_path, card):
        match = SPECS_BY_KEY["cross_tab"].evaluate(card)
        path = write(card, match, project_dir=str(tmp_path))
        with open(path, encoding="utf-8") as fh:
            assert compiles(fh.read())


class TestDescribeRespectsAccessLevel:
    """The describe template dumped 275 raw HIGH_LEVEL timestamps with exact
    counts, which is the policy it claims to enforce being violated by the
    generator itself."""

    def test_an_aggregate_only_timestamp_is_bucketed(self, card):
        code = render(card, SPECS_BY_KEY["describe"].evaluate(card))
        assert "_bucket(record.admissions.time" in code
        assert 'totals["admissions.time"][str(' not in code

    def test_the_bucket_matches_the_coarsest_releasable_unit(self, card_json):
        from sdk.card import Card
        card_json["leaves"]["admissions.time"]["releasableAs"] = ["month"]
        c = Card.from_json(card_json)
        code = render(c, SPECS_BY_KEY["describe"].evaluate(c))
        assert "_bucket(record.admissions.time, 7)" in code  # YYYY-MM

    def test_a_detailed_field_is_not_bucketed(self, card):
        code = render(card, SPECS_BY_KEY["describe"].evaluate(card))
        assert 'totals["patient.gender"][str(record.patient.gender)]' in code

    def test_levels_are_capped_not_dumped(self, card):
        code = render(card, SPECS_BY_KEY["describe"].evaluate(card))
        assert "TOP_LEVELS" in code
        assert "levels_not_shown" in code

    def test_output_stays_small_on_a_wide_dataset(self, tmp_path, card):
        """A 1,472-level code column must not produce a 40,000-char result."""
        import json as json_mod
        import subprocess
        import sys
        project = tmp_path
        (project / "generated").mkdir()
        (project / "generated" / "__init__.py").write_text("", encoding="utf-8")
        (project / "generated" / "models.py").write_text(MODELS, encoding="utf-8")
        rows = ["admissions.time,admissions.type,patient.gender,patient.age,"
                "diagnoses.icd_code,diagnoses.icd_version"]
        for i in range(3000):
            rows.append("21{0:02d}-01-01,EW EMER.,M,50,CODE{1},9".format(
                i % 100, i))          # 3000 distinct codes, 100 distinct years
        (project / "generated" / "data.csv").write_text(
            "\n".join(rows) + "\n", encoding="utf-8")
        path = write(card, SPECS_BY_KEY["describe"].evaluate(card),
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
