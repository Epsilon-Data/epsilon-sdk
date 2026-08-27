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

    def test_written_code_compiles(self, tmp_path, card):
        match = SPECS_BY_KEY["cross_tab"].evaluate(card)
        path = write(card, match, project_dir=str(tmp_path))
        with open(path, encoding="utf-8") as fh:
            assert compiles(fh.read())
