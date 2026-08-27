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
from sdk.catalogue import (BLOCKED, FEASIBLE, SPECS_BY_KEY, blocked, evaluate,
                           feasible)


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
