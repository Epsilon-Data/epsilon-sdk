"""
Tests for the catalogue matcher.

These are the verdicts the whole copilot rests on. They are decided in code
precisely so they can be pinned here: an analysis that is wrong for a dataset
runs cleanly, passes the submission gate and returns attested, so the refusal
has to be right and has to stay right.
"""
import copy

import pytest

from sdk.catalogue import (BLOCKED, FEASIBLE, SPECS_BY_KEY, OverrideError,
                           blocked, evaluate, feasible, override)


def verdict(profile, key):
    return SPECS_BY_KEY[key].evaluate(profile)


class TestPerEntityAnalysesNeedAKey:
    """The headline refusal: no key back to the entity, no per-entity answer."""

    def test_prevalence_is_blocked_without_a_dedupe_key(self, profile):
        match = verdict(profile, "prevalence")
        assert match.status == BLOCKED
        assert any("per-entity quantity" in b for b in match.blockers)

    def test_prevalence_says_what_would_unlock_it(self, profile):
        match = verdict(profile, "prevalence")
        assert match.unlock is not None
        assert "pseudonymised" in match.unlock

    def test_prevalence_is_feasible_once_a_key_exists(self, keyed_profile):
        assert verdict(keyed_profile, "prevalence").status == FEASIBLE

    def test_composition_survives_where_prevalence_does_not(self, profile):
        """The narrower record-level question is still answerable."""
        match = verdict(profile, "composition")
        assert match.status == FEASIBLE
        assert match.unit == "record"
        assert any("narrower question" in w for w in match.warnings)


class TestIndependence:
    """Repeated rows per entity break the assumptions of several tests."""

    def test_group_compare_is_blocked_by_repeated_measures(self, profile):
        match = verdict(profile, "group_compare")
        assert match.status == BLOCKED
        assert any("assumes one observation per entity" in b for b in match.blockers)

    def test_logistic_is_blocked_by_repeated_measures(self, profile):
        match = verdict(profile, "logistic")
        assert match.status == BLOCKED
        assert any("independent observations" in b for b in match.blockers)

    def test_both_are_feasible_when_rows_are_one_per_entity(self, keyed_profile):
        assert verdict(keyed_profile, "group_compare").status == FEASIBLE
        assert verdict(keyed_profile, "logistic").status == FEASIBLE


class TestSurvival:
    """Blocked structurally: an archetype grants columns, not the knowledge of
    which date starts a clock and which stops it."""

    def test_always_blocked(self, profile, keyed_profile):
        assert verdict(profile, "survival").status == BLOCKED
        assert verdict(keyed_profile, "survival").status == BLOCKED

    def test_says_why_rather_than_just_no(self, profile):
        blockers = " ".join(verdict(profile, "survival").blockers)
        assert "which date starts a clock" in blockers

    def test_offers_the_unlock(self, profile):
        assert "follow-up or discharge date" in verdict(profile, "survival").unlock


class TestTrend:
    def test_warns_that_dates_may_be_shifted(self, profile):
        """Shifted dates are indistinguishable from real ones in the data, so
        the honest move is to warn rather than to block or to permit."""
        match = verdict(profile, "trend")
        assert any("shift dates by a per-entity offset" in w
                   for w in match.warnings)

    def test_feasible_with_a_releasable_bucket(self, profile):
        match = verdict(profile, "trend")
        assert match.status == FEASIBLE
        assert "month" in match.params["buckets"]

    def test_blocked_when_there_is_no_temporal_field(self, profile):
        del profile.leaves["admissions.time"]
        match = verdict(profile, "trend")
        assert match.status == BLOCKED
        assert any("cross-section" in b for b in match.blockers)

    def test_blocked_when_aggregate_only_with_no_buckets(self, profile):
        profile.leaf("admissions.time").releasable_as = []
        match = verdict(profile, "trend")
        assert match.status == BLOCKED
        assert any("no releasable buckets" in b for b in match.blockers)


class TestCrossTab:
    def test_wide_code_columns_are_not_offered_as_strata(self, profile):
        """1472 ICD codes crossed with anything is unreleasable."""
        match = verdict(profile, "cross_tab")
        assert "diagnoses.icd_code" not in match.params.values()

    def test_blocked_when_the_table_would_be_too_sparse(self, profile):
        profile.grain.rows = 20
        match = verdict(profile, "cross_tab")
        assert match.status == BLOCKED
        assert any("expected per cell" in b for b in match.blockers)

    def test_warns_when_cells_are_merely_thin(self, profile):
        profile.grain.rows = 200
        match = verdict(profile, "cross_tab")
        assert match.status == FEASIBLE
        assert any("suppressed at n <" in w for w in match.warnings)


class TestWarningsReachTheResearcher:
    def test_leaf_caveats_are_surfaced_on_analyses_that_touch_them(self, profile):
        match = verdict(profile, "describe")
        assert any("capped at 91" in w for w in match.warnings)

    def test_a_possible_mixed_code_column_is_flagged(self, profile):
        match = verdict(profile, "describe")
        assert any("more than one revision" in w for w in match.warnings)

    def test_aggregate_only_access_is_flagged(self, profile):
        match = verdict(profile, "describe")
        assert any("released as month" in w for w in match.warnings)


class TestOrdering:
    def test_feasible_entries_come_first(self, profile):
        statuses = [m.status for m in evaluate(profile)]
        assert statuses == sorted(statuses, key=lambda s: 0 if s == FEASIBLE else 1)

    def test_helpers_partition_the_catalogue(self, profile):
        assert len(feasible(profile)) + len(blocked(profile)) == len(evaluate(profile))

    def test_selected_keys_can_be_evaluated_alone(self, profile):
        matches = evaluate(profile, keys=["describe"])
        assert [m.key for m in matches] == ["describe"]

    def test_unknown_keys_are_ignored(self, profile):
        assert evaluate(profile, keys=["nope"]) == []


class TestOverrides:
    """Researcher-chosen fields are validated, never trusted."""

    def test_a_valid_choice_is_applied(self, profile):
        match = override(profile, verdict(profile, "cross_tab"),
                         {"rows": "patient.gender", "cols": "admissions.type"})
        assert match.status == FEASIBLE
        assert match.params["rows"] == "patient.gender"

    def test_the_wrong_kind_of_field_is_rejected(self, profile):
        with pytest.raises(OverrideError) as exc:
            override(profile, verdict(profile, "cross_tab"), {"rows": "patient.age"})
        assert "categorical or coded field" in str(exc.value)

    def test_an_unknown_field_is_rejected(self, profile):
        with pytest.raises(OverrideError) as exc:
            override(profile, verdict(profile, "cross_tab"), {"rows": "patient.nope"})
        assert "not a field in this dataset" in str(exc.value)

    def test_an_unknown_parameter_is_rejected(self, profile):
        with pytest.raises(OverrideError) as exc:
            override(profile, verdict(profile, "cross_tab"), {"nope": "patient.gender"})
        assert "takes no parameter" in str(exc.value)

    def test_a_blocked_analysis_cannot_be_unblocked(self, profile):
        with pytest.raises(OverrideError) as exc:
            override(profile, verdict(profile, "prevalence"), {"outcome": "patient.gender"})
        assert "not available" in str(exc.value)

    def test_a_wide_column_is_still_refused_when_chosen_explicitly(self, profile):
        from sdk.profile import Leaf
        profile.leaves["diagnoses.wide"] = Leaf(
            path="diagnoses.wide", type="code", cardinality=1472, null_rate=0.0)
        match = override(profile, verdict(profile, "cross_tab"),
                         {"rows": "diagnoses.wide"})
        assert match.status == BLOCKED
        assert any("1,472 distinct values" in b for b in match.blockers)

    def test_sparsity_is_rechecked_against_the_chosen_fields(self, profile):
        """A choice can be sparser than what the matcher picked for you."""
        from sdk.profile import Leaf
        profile.grain.rows = 500
        profile.leaves["vitals.chapter"] = Leaf(
            path="vitals.chapter", type="categorical", cardinality=15,
            null_rate=0.0)
        c = profile
        auto = verdict(c, "cross_tab")
        assert auto.status == FEASIBLE          # picks 9 x 2 = 18 cells over 500

        match = override(c, auto, {"rows": "vitals.chapter",
                                   "cols": "admissions.type"})
        assert match.status == BLOCKED          # 15 x 9 = 135 cells over 500
        assert any("expected per cell" in b for b in match.blockers)

    def test_a_roomier_choice_is_allowed(self, profile):
        from sdk.profile import Leaf
        profile.grain.rows = 5000
        profile.leaves["vitals.chapter"] = Leaf(
            path="vitals.chapter", type="categorical", cardinality=15,
            null_rate=0.0)
        c = profile
        match = override(c, verdict(c, "cross_tab"),
                         {"rows": "vitals.chapter", "cols": "admissions.type"})
        assert match.status == FEASIBLE

    def test_caveats_of_chosen_fields_are_surfaced(self, profile):
        """A field the matcher did not pick still brings its warnings along."""
        auto = verdict(profile, "cross_tab")
        assert "patient.gender" not in auto.params.values()
        match = override(profile, auto, {"rows": "diagnoses.icd_code"})
        assert any("more than one revision" in w for w in match.warnings)

    def test_warnings_are_not_duplicated(self, profile):
        match = override(profile, verdict(profile, "cross_tab"),
                         {"rows": "patient.gender"})
        assert len(match.warnings) == len(set(match.warnings))


class TestSuggestedCommands:
    def test_every_command_names_a_real_catalogue_key(self, keyed_profile):
        for match in evaluate(keyed_profile):
            if not match.command:
                continue
            key = match.command.split()[2]
            assert key in SPECS_BY_KEY, match.command

    def test_commands_use_the_set_syntax(self, keyed_profile):
        for match in evaluate(keyed_profile):
            if match.command and "--" in match.command:
                assert "--set " in match.command, match.command

    def test_a_printed_command_round_trips(self, profile):
        """Copy-pasting what explain prints must actually work."""
        match = verdict(profile, "cross_tab")
        choices = dict(part.split("=", 1)
                       for part in match.command.split()
                       if "=" in part)
        again = override(profile, verdict(profile, "cross_tab"), choices)
        assert again.status == FEASIBLE
        assert again.params == match.params
