"""Tests for question routing and the suggest rendering."""
import pytest

from sdk.catalogue import CATALOGUE
from sdk.suggest import (QUESTION_SCHEMA, interpret, render_answer,
                         render_catalogue)


class TestWorksWithoutAModel:
    def test_catalogue_listing_needs_no_provider(self, card):
        text = render_catalogue(card)
        assert "AVAILABLE" in text
        assert "NOT AVAILABLE" in text

    def test_answering_needs_no_provider(self, card):
        text = render_answer(card, "what is in this dataset?")
        assert "Question:" in text

    def test_interpret_returns_nothing_without_a_provider(self, card):
        assert interpret(card, "anything", provider=None) == {}


class TestKeywordRouting:
    """Crude by design: it picks what to show first, never the verdict."""

    @pytest.mark.parametrize("question,expected", [
        ("does hypertension prevalence differ by sex?", "Prevalence"),
        ("how long until readmission?", "Survival analysis"),
        ("is admission type changing over time?", "Trend over time"),
        ("what predicts mortality adjusting for age?", "Logistic regression"),
        ("describe the cohort", "Cohort description"),
    ])
    def test_routes_to_the_right_entry(self, card, question, expected):
        assert expected in render_answer(card, question).split("RELATED")[0]

    def test_falls_back_to_description(self, card):
        text = render_answer(card, "zzz unrelated gibberish")
        assert "Cohort description" in text


class TestRefusalsAreShown:
    def test_a_blocked_entry_is_shown_rather_than_replaced(self, card):
        """Naming the blocked analysis is more useful than redirecting."""
        text = render_answer(card, "what is the prevalence of hypertension?")
        head = text.split("RELATED")[0]
        assert "[NO] Prevalence" in head
        assert "why not:" in head

    def test_the_unlock_path_is_offered(self, card):
        text = render_answer(card, "what is the prevalence of hypertension?")
        assert "unlock:" in text
        assert "pseudonymised" in text

    def test_related_feasible_entries_are_offered(self, card):
        text = render_answer(card, "what is the prevalence of hypertension?")
        assert "RELATED" in text
        assert "[OK]" in text


class TestModelCannotOverturnVerdicts:
    def test_a_model_choosing_prevalence_still_gets_the_refusal(self, card):
        interpretation = {"primary": "prevalence", "restated": "restated",
                          "explanation": "explained"}
        text = render_answer(card, "q", interpretation)
        assert "[NO] Prevalence" in text
        assert "why not:" in text

    def test_an_invalid_key_from_a_model_is_ignored(self, card):
        text = render_answer(card, "describe the cohort",
                             {"primary": "not-a-real-key"})
        assert "Cohort description" in text

    def test_model_prose_is_rendered_when_present(self, card):
        text = render_answer(card, "q", {"primary": "describe",
                                         "restated": "RESTATED-MARKER",
                                         "explanation": "EXPLAINED-MARKER"})
        assert "RESTATED-MARKER" in text
        assert "EXPLAINED-MARKER" in text


class TestSchema:
    def test_the_model_may_only_pick_a_real_catalogue_key(self):
        allowed = QUESTION_SCHEMA["properties"]["primary"]["enum"]
        assert allowed == [spec.key for spec in CATALOGUE]

    def test_the_schema_asks_for_no_verdict_field(self):
        """Feasibility is not the model's to report."""
        properties = set(QUESTION_SCHEMA["properties"])
        assert not properties & {"feasible", "status", "blocked", "verdict"}


class TestRendering:
    def test_lines_stay_within_a_terminal(self, card):
        longest = max(len(l) for l in render_catalogue(card).splitlines())
        assert longest <= 100

    def test_notes_are_capped_in_the_full_listing(self, card_json):
        from sdk.card import Card
        card_json["leaves"]["patient.age"]["caveats"] = [
            "caveat {0}".format(i) for i in range(8)]
        text = render_catalogue(Card.from_json(card_json))
        assert "more note" in text
        assert "caveat 7" not in text  # held back, not silently dropped

    def test_all_notes_are_shown_when_asking_about_one_analysis(self, card_json):
        from sdk.card import Card
        card_json["leaves"]["patient.age"]["caveats"] = [
            "caveat {0}".format(i) for i in range(8)]
        text = render_answer(Card.from_json(card_json), "describe the cohort")
        assert "caveat 7" in text
