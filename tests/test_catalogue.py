"""
Tests for the catalogue matcher.

These are the verdicts the whole copilot rests on. They are decided in code
precisely so they can be pinned here: an analysis that is wrong for a dataset
runs cleanly, passes the submission gate and returns attested, so the refusal
has to be right and has to stay right.
"""
import copy

import pytest

from sdk.card import Card
from sdk.catalogue import (BLOCKED, FEASIBLE, SPECS_BY_KEY, OverrideError,
                           blocked, evaluate, feasible, override)


def verdict(card, key):
    return SPECS_BY_KEY[key].evaluate(card)


class TestPerEntityAnalysesNeedAKey:
    """The headline refusal: no key back to the entity, no per-entity answer."""

    def test_prevalence_is_blocked_without_a_dedupe_key(self, card):
        match = verdict(card, "prevalence")
        assert match.status == BLOCKED
        assert any("per-entity quantity" in b for b in match.blockers)

    def test_prevalence_says_what_would_unlock_it(self, card):
        match = verdict(card, "prevalence")
        assert match.unlock is not None
        assert "pseudonymised" in match.unlock

    def test_prevalence_is_feasible_once_a_key_exists(self, unblocked_card):
        assert verdict(unblocked_card, "prevalence").status == FEASIBLE

    def test_composition_survives_where_prevalence_does_not(self, card):
        """The narrower record-level question is still answerable."""
        match = verdict(card, "composition")
        assert match.status == FEASIBLE
        assert match.unit == "diagnosis_record"
        assert any("narrower question" in w for w in match.warnings)


class TestIndependence:
    """Repeated rows per entity break the assumptions of several tests."""

    def test_group_compare_is_blocked_by_repeated_measures(self, card):
        match = verdict(card, "group_compare")
        assert match.status == BLOCKED
        assert any("independence assumption" in b for b in match.blockers)

    def test_logistic_is_blocked_by_repeated_measures(self, card):
        match = verdict(card, "logistic")
        assert match.status == BLOCKED
        assert any("not independent" in b for b in match.blockers)

    def test_both_are_feasible_when_rows_are_one_per_entity(self, unblocked_card):
        assert verdict(unblocked_card, "group_compare").status == FEASIBLE
        assert verdict(unblocked_card, "logistic").status == FEASIBLE


class TestSurvival:
    def test_an_age_in_years_is_not_a_time_to_event(self, card):
        """patient.age has unit 'years'. It is not a duration, and treating it
        as one is exactly the error the catalogue exists to prevent."""
        match = verdict(card, "survival")
        assert match.status == BLOCKED
        assert any("not a duration" in b for b in match.blockers)

    def test_needs_an_explicit_duration_type(self, unblocked_card):
        match = verdict(unblocked_card, "survival")
        assert match.status == FEASIBLE
        assert match.params["duration"] == "stay.los"

    def test_suggests_asking_for_a_second_date(self, card):
        assert "two dates make a duration" in verdict(card, "survival").unlock


class TestTrend:
    def test_blocked_when_dates_are_shifted_per_entity(self, card):
        match = verdict(card, "trend")
        assert match.status == BLOCKED
        assert any("not comparable between entities" in b for b in match.blockers)

    def test_feasible_when_dates_are_comparable(self, unblocked_card):
        match = verdict(unblocked_card, "trend")
        assert match.status == FEASIBLE
        assert "month" in match.params["buckets"]

    def test_blocked_when_there_is_no_temporal_field(self, card_json):
        del card_json["leaves"]["admissions.time"]
        match = verdict(Card.from_json(card_json), "trend")
        assert match.status == BLOCKED
        assert any("cross-section" in b for b in match.blockers)

    def test_blocked_when_aggregate_only_with_no_buckets(self, card_json):
        card_json["leaves"]["admissions.time"]["releasableAs"] = []
        card_json["leaves"]["admissions.time"]["comparableAcrossEntities"] = True
        match = verdict(Card.from_json(card_json), "trend")
        assert match.status == BLOCKED
        assert any("no releasable buckets" in b for b in match.blockers)


class TestCrossTab:
    def test_wide_code_columns_are_not_offered_as_strata(self, card):
        """1472 ICD codes crossed with anything is unreleasable."""
        match = verdict(card, "cross_tab")
        assert "diagnoses.icd_code" not in match.params.values()

    def test_blocked_when_the_table_would_be_too_sparse(self, card_json):
        card_json["grain"]["rows"] = 20
        match = verdict(Card.from_json(card_json), "cross_tab")
        assert match.status == BLOCKED
        assert any("expected per cell" in b for b in match.blockers)

    def test_warns_when_cells_are_merely_thin(self, card_json):
        card_json["grain"]["rows"] = 200  # 18 cells -> ~11 expected each
        match = verdict(Card.from_json(card_json), "cross_tab")
        assert match.status == FEASIBLE
        assert any("suppressed at n <" in w for w in match.warnings)


class TestWarningsReachTheResearcher:
    def test_leaf_caveats_are_surfaced_on_analyses_that_touch_them(self, card):
        match = verdict(card, "describe")
        assert any("recorded as 91" in w for w in match.warnings)

    def test_mixed_coding_systems_are_flagged(self, card):
        match = verdict(card, "describe")
        assert any("ICD-9-CM" in w and "undercount" in w for w in match.warnings)

    def test_aggregate_only_access_is_flagged(self, card):
        match = verdict(card, "describe")
        assert any("HIGH_LEVEL" in w for w in match.warnings)


class TestUnknownGrain:
    """A derived card knows nothing, and must not pretend otherwise."""

    def test_per_entity_analyses_are_blocked(self, mock_archetype):
        from sdk.card import derive_card
        match = verdict(derive_card(mock_archetype), "prevalence")
        assert match.status == BLOCKED
        assert any("grain of this dataset is unknown" in b for b in match.blockers)

    def test_a_missing_card_is_not_blamed_on_the_archetype(self, mock_archetype):
        """The fields are granted; it is their types that are unknown."""
        from sdk.card import derive_card
        match = verdict(derive_card(mock_archetype), "cross_tab")
        blockers = " ".join(match.blockers)
        assert "No dataset card is published" in blockers
        assert "The fields themselves are granted" in blockers
        assert "archetype grants no" not in blockers


class TestOrdering:
    def test_feasible_entries_come_first(self, card):
        statuses = [m.status for m in evaluate(card)]
        assert statuses == sorted(statuses, key=lambda s: 0 if s == FEASIBLE else 1)

    def test_helpers_partition_the_catalogue(self, card):
        assert len(feasible(card)) + len(blocked(card)) == len(evaluate(card))

    def test_selected_keys_can_be_evaluated_alone(self, card):
        matches = evaluate(card, keys=["describe"])
        assert [m.key for m in matches] == ["describe"]

    def test_unknown_keys_are_ignored(self, card):
        assert evaluate(card, keys=["nope"]) == []


class TestOverrides:
    """Researcher-chosen fields are validated, never trusted."""

    def test_a_valid_choice_is_applied(self, card):
        match = override(card, verdict(card, "cross_tab"),
                         {"rows": "patient.gender", "cols": "admissions.type"})
        assert match.status == FEASIBLE
        assert match.params["rows"] == "patient.gender"

    def test_the_wrong_kind_of_field_is_rejected(self, card):
        with pytest.raises(OverrideError) as exc:
            override(card, verdict(card, "cross_tab"), {"rows": "patient.age"})
        assert "categorical or coded field" in str(exc.value)

    def test_an_unknown_field_is_rejected(self, card):
        with pytest.raises(OverrideError) as exc:
            override(card, verdict(card, "cross_tab"), {"rows": "patient.nope"})
        assert "not a field in this dataset" in str(exc.value)

    def test_an_unknown_parameter_is_rejected(self, card):
        with pytest.raises(OverrideError) as exc:
            override(card, verdict(card, "cross_tab"), {"nope": "patient.gender"})
        assert "takes no parameter" in str(exc.value)

    def test_a_blocked_analysis_cannot_be_unblocked(self, card):
        with pytest.raises(OverrideError) as exc:
            override(card, verdict(card, "prevalence"), {"outcome": "patient.gender"})
        assert "not available" in str(exc.value)

    def test_a_wide_column_is_still_refused_when_chosen_explicitly(self, card):
        match = override(card, verdict(card, "cross_tab"),
                         {"rows": "diagnoses.icd_code"})
        assert match.status == BLOCKED
        assert any("1,472 distinct values" in b for b in match.blockers)

    def test_sparsity_is_rechecked_against_the_chosen_fields(self, card_json):
        """A choice can be sparser than what the matcher picked for you."""
        card_json["grain"]["rows"] = 500
        card_json["leaves"]["vitals.chapter"] = {
            "type": "categorical", "accessLevel": "DETAILED",
            "cardinality": 15, "nullRate": 0.0}
        c = Card.from_json(card_json)
        auto = verdict(c, "cross_tab")
        assert auto.status == FEASIBLE          # picks 9 x 2 = 18 cells over 500

        match = override(c, auto, {"rows": "vitals.chapter",
                                   "cols": "admissions.type"})
        assert match.status == BLOCKED          # 15 x 9 = 135 cells over 500
        assert any("expected per cell" in b for b in match.blockers)

    def test_a_roomier_choice_is_allowed(self, card_json):
        card_json["grain"]["rows"] = 5000
        card_json["leaves"]["vitals.chapter"] = {
            "type": "categorical", "accessLevel": "DETAILED",
            "cardinality": 15, "nullRate": 0.0}
        c = Card.from_json(card_json)
        match = override(c, verdict(c, "cross_tab"),
                         {"rows": "vitals.chapter", "cols": "admissions.type"})
        assert match.status == FEASIBLE

    def test_caveats_of_chosen_fields_are_surfaced(self, card):
        """A field the matcher did not pick still brings its warnings along."""
        auto = verdict(card, "cross_tab")
        assert "patient.gender" not in auto.params.values()
        match = override(card, auto, {"rows": "patient.gender"})
        assert any("51.6% M" in w for w in match.warnings)

    def test_warnings_are_not_duplicated(self, card):
        match = override(card, verdict(card, "cross_tab"),
                         {"rows": "patient.gender"})
        assert len(match.warnings) == len(set(match.warnings))


class TestSuggestedCommands:
    def test_every_command_names_a_real_catalogue_key(self, unblocked_card):
        for match in evaluate(unblocked_card):
            if not match.command:
                continue
            key = match.command.split()[2]
            assert key in SPECS_BY_KEY, match.command

    def test_commands_use_the_set_syntax(self, unblocked_card):
        for match in evaluate(unblocked_card):
            if match.command and "--" in match.command:
                assert "--set " in match.command, match.command

    def test_a_printed_command_round_trips(self, card):
        """Copy-pasting what suggest prints must actually work."""
        match = verdict(card, "cross_tab")
        choices = dict(part.split("=", 1)
                       for part in match.command.split()
                       if "=" in part)
        again = override(card, verdict(card, "cross_tab"), choices)
        assert again.status == FEASIBLE
        assert again.params == match.params
