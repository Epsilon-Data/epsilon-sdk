"""Tests for the briefing renderer."""
from sdk.explain import render, render_catalogue, render_full, render_summary


class TestBriefing:
    def test_states_the_grain_first(self, profile):
        text = render(profile)
        assert "GRAIN" in text
        assert "One row per record" in text

    def test_lists_every_granted_field(self, profile):
        text = render(profile)
        for path in profile.leaves:
            assert path in text

    def test_shows_how_an_aggregate_only_field_may_be_released(self, profile):
        text = render(profile)
        assert "month, quarter, year" in text

    def test_warns_that_rows_cannot_be_grouped(self, profile):
        assert "NO ENTITY KEY" in render(profile)

    def test_says_per_entity_figures_are_not_computable(self, profile):
        assert "not computable" in render(profile).lower()

    def test_reports_the_row_count_it_measured(self, profile):
        assert "4,000 rows" in render(profile)

    def test_flags_a_possible_mixed_code_column(self, profile):
        text = render(profile)
        assert "more than one revision" in text
        assert "diagnoses.icd_version" in text

    def test_warns_about_aggregate_only_fields(self, profile):
        text = render(profile)
        assert "AGGREGATE ONLY" in text
        assert "month, quarter, year" in text

    def test_surfaces_leaf_caveats(self, profile):
        assert "capped at 91" in render(profile)

    def test_says_the_description_was_measured_not_declared(self, profile):
        assert "measured from the local dataset" in render(profile)

    def test_says_the_local_data_is_synthetic(self, profile):
        assert "SYNTHETIC" in render(profile)

    def test_no_line_runs_past_the_terminal(self, profile):
        assert max(len(l) for l in render(profile).splitlines()) <= 100


class TestSummary:
    def test_is_one_line(self, profile):
        assert "\n" not in render_summary(profile)

    def test_mentions_the_missing_key(self, profile):
        assert "no entity key" in render_summary(profile)


class TestCatalogueRendering:
    """The catalogue listing moved here from the removed `suggest` command:
    the model-free half was worth keeping, the keyword guessing was not."""

    def test_lists_available_and_unavailable(self, profile):
        text = render_catalogue(profile)
        assert "AVAILABLE (" in text
        assert "NOT AVAILABLE (" in text

    def test_a_refusal_carries_its_reason(self, profile):
        text = render_catalogue(profile)
        assert "[NO] Prevalence" in text
        assert "why not:" in text

    def test_a_refusal_carries_its_unlock_path(self, profile):
        assert "unlock:" in render_catalogue(profile)

    def test_feasible_entries_show_the_command(self, profile):
        assert "epsilon snippet" in render_catalogue(profile)

    def test_notes_are_capped(self, profile):
        profile.leaf("patient.age").caveats = [
            "caveat {0}".format(i) for i in range(8)]
        assert "more note" in render_catalogue(profile)

    def test_lines_stay_within_a_terminal(self, profile):
        assert max(len(l) for l in render_catalogue(profile).splitlines()) <= 100


class TestRenderFull:
    def test_combines_the_briefing_and_the_catalogue(self, profile):
        text = render_full(profile)
        assert "GRAIN" in text
        assert "AVAILABLE (" in text

    def test_the_briefing_comes_first(self, profile):
        text = render_full(profile)
        assert text.index("GRAIN") < text.index("AVAILABLE (")
