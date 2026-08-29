"""The model proposes; the catalogue decides."""
import pytest

from sdk import suggestions as S
from sdk.profile import profile_project


@pytest.fixture
def profile(dataset_dir):
    return profile_project(str(dataset_dir))


class Stub:
    """A provider that returns whatever the test wants it to propose."""

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []


@pytest.fixture
def answer(monkeypatch):
    """Make sdk.llm.structured return a canned payload."""
    box = {}

    def install(payload):
        def fake(provider, system, prompt, schema, **kw):
            box["system"], box["prompt"], box["schema"] = system, prompt, schema
            if isinstance(payload, Exception):
                raise payload
            return payload
        monkeypatch.setattr("sdk.llm.structured", fake)
        return box

    return install


class TestValidate:
    def test_keeps_a_proposal_the_catalogue_allows(self, profile):
        kept = S.validate(profile, {
            "title": "Admission type by sex", "question": "Does it differ?",
            "analysis": "cross_tab",
            "fields": {"rows": "patient.gender", "cols": "admissions.type"}})
        assert kept is not None
        assert kept.analysis == "cross_tab"
        assert kept.fields["rows"] == "patient.gender"

    def test_discards_a_blocked_analysis(self, profile):
        assert S.validate(profile, {
            "title": "Diabetes prevalence", "question": "How common?",
            "analysis": "prevalence", "fields": {}}) is None

    def test_discards_an_unknown_analysis(self, profile):
        assert S.validate(profile, {
            "title": "t", "question": "q", "analysis": "vibes",
            "fields": {}}) is None

    def test_drops_fields_that_do_not_exist(self, profile):
        kept = S.validate(profile, {
            "title": "t", "question": "q", "analysis": "cross_tab",
            "fields": {"rows": "patient.gender", "cols": "patient.invented"}})
        assert kept is not None
        assert "patient.invented" not in kept.fields.values()

    def test_falls_back_when_the_fields_are_the_wrong_kind(self, profile):
        """A good idea with a bad field choice keeps the idea."""
        kept = S.validate(profile, {
            "title": "t", "question": "q", "analysis": "cross_tab",
            "fields": {"rows": "patient.age"}})
        assert kept is not None
        assert kept.fields  # the matcher's own choice, not the model's

    def test_requires_a_title_and_a_question(self, profile):
        assert S.validate(profile, {
            "title": "", "question": "q", "analysis": "describe",
            "fields": {}}) is None
        assert S.validate(profile, {
            "title": "t", "question": "  ", "analysis": "describe",
            "fields": {}}) is None

    def test_carries_the_warnings_through(self, profile):
        kept = S.validate(profile, {
            "title": "t", "question": "q", "analysis": "composition",
            "fields": {}})
        assert kept is not None
        assert isinstance(kept.warnings, list)


class TestPropose:
    def test_returns_validated_proposals(self, profile, answer):
        answer({"suggestions": [
            {"title": "Sex by admission type", "question": "Does it differ?",
             "why": "shows the mix", "analysis": "cross_tab",
             "fields": {"rows": "patient.gender", "cols": "admissions.type"}}]})
        out = S.propose(profile, provider=object())
        assert [s.title for s in out] == ["Sex by admission type"]

    def test_silently_drops_blocked_proposals(self, profile, answer):
        answer({"suggestions": [
            {"title": "Prevalence", "question": "q", "analysis": "prevalence",
             "fields": {}},
            {"title": "Composition", "question": "q", "analysis": "composition",
             "fields": {}}]})
        out = S.propose(profile, provider=object())
        assert [s.title for s in out] == ["Composition"]

    def test_deduplicates_by_title(self, profile, answer):
        answer({"suggestions": [
            {"title": "Same", "question": "q", "analysis": "describe", "fields": {}},
            {"title": "same", "question": "q", "analysis": "composition", "fields": {}}]})
        assert len(S.propose(profile, provider=object())) == 1

    def test_stops_at_the_wanted_count(self, profile, answer):
        answer({"suggestions": [
            {"title": "One", "question": "q", "analysis": "describe", "fields": {}},
            {"title": "Two", "question": "q", "analysis": "composition", "fields": {}},
            {"title": "Three", "question": "q", "analysis": "cross_tab", "fields": {}}]})
        assert len(S.propose(profile, provider=object(), wanted=2)) == 2

    def test_falls_back_when_the_model_proposes_nothing_usable(self, profile, answer):
        answer({"suggestions": [
            {"title": "Prevalence", "question": "q", "analysis": "prevalence",
             "fields": {}}]})
        out = S.propose(profile, provider=object())
        assert out  # the catalogue still has something to offer
        assert all(s.analysis != "prevalence" for s in out)

    def test_falls_back_when_the_model_errors(self, profile, answer):
        answer(RuntimeError("upstream is down"))
        assert S.propose(profile, provider=object())

    def test_works_with_no_provider(self, profile):
        from sdk import catalogue
        feasible = set(m.key for m in catalogue.evaluate(profile) if m.feasible)
        out = S.propose(profile, provider=None)
        assert out
        assert all(s.analysis in feasible for s in out)


class TestContext:
    def test_describes_measured_fields_and_verdicts(self, profile):
        text = S._context(profile)
        assert "patient.gender" in text
        assert "Catalogue verdicts" in text
        assert "prevalence: BLOCKED" in text

    def test_says_there_is_no_entity_key(self, profile):
        assert "No key groups rows back to an entity" in S._context(profile)

    def test_the_prompt_forbids_proposing_blocked_work(self):
        assert "blocked" in S.SYSTEM


class TestFallback:
    def test_offers_only_feasible_analyses(self, profile):
        for s in S.fallback(profile):
            assert s.analysis != "prevalence"

    def test_carries_the_matchers_own_fields(self, profile):
        by_key = {s.analysis: s for s in S.fallback(profile)}
        assert by_key["cross_tab"].fields
