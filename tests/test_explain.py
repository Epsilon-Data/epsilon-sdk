"""Tests for the briefing renderer."""
from sdk.card import Card, derive_card
from sdk.explain import render, render_summary


class TestBriefing:
    def test_states_the_grain_first(self, card):
        text = render(card)
        assert "GRAIN" in text
        assert "One row per diagnosis code." in text

    def test_lists_every_granted_field(self, card):
        text = render(card)
        for path in card.leaves:
            assert path in text

    def test_shows_access_level_per_field(self, card):
        text = render(card)
        assert "HIGH_LEVEL" in text
        assert "DETAILED" in text

    def test_warns_that_rows_cannot_be_grouped(self, card):
        assert "NO DEDUPE KEY" in render(card)

    def test_names_the_most_aggregated_entity_in_the_warning(self, card):
        # 100 patients vs 275 admissions: patients is the coarser grouping and
        # the one a researcher is most likely to want.
        assert "a patient" in render(card)

    def test_warns_about_grain_amplification(self, card):
        text = render(card)
        assert "GRAIN AMPLIFICATION" in text
        assert "1,000 rows" in text

    def test_warns_about_two_coding_systems(self, card):
        text = render(card)
        assert "TWO CODING SYSTEMS" in text
        assert "ICD-9-CM" in text
        assert "diagnoses.icd_version" in text  # the discriminator

    def test_warns_about_aggregate_only_fields(self, card):
        text = render(card)
        assert "AGGREGATE ONLY" in text
        assert "month, quarter, year" in text

    def test_surfaces_leaf_caveats(self, card):
        assert "recorded as 91" in render(card)

    def test_lists_what_the_archetype_excludes(self, card):
        assert "No discharge date" in render(card)

    def test_says_the_local_data_is_synthetic(self, card):
        assert "SYNTHETIC" in render(card)

    def test_no_line_runs_past_the_terminal(self, card):
        assert max(len(l) for l in render(card).splitlines()) <= 100


class TestDegradedCard:
    def test_says_the_grain_is_unknown(self, mock_archetype):
        text = render(derive_card(mock_archetype))
        assert "GRAIN UNKNOWN" in text or "Unknown" in text

    def test_marks_itself_as_derived(self, mock_archetype):
        assert "DERIVED" in render(derive_card(mock_archetype))

    def test_renders_without_a_card(self, mock_archetype):
        # Must not raise: this is the path for every project whose owner has
        # not authored a card.
        assert len(render(derive_card(mock_archetype))) > 0


class TestEmptyArchetype:
    def test_says_so_rather_than_rendering_an_empty_table(self):
        card = Card.from_json({"cardVersion": 1, "title": "Empty", "leaves": {}})
        assert "grants no fields" in render(card)


class TestSummary:
    def test_is_one_line(self, card):
        assert "\n" not in render_summary(card)

    def test_mentions_the_missing_key(self, card):
        assert "no dedupe key" in render_summary(card)
