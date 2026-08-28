"""
Tests for measuring a dataset.

This replaces the owner-authored card. Everything a verdict rests on is now
inferred here, so the inference has to be conservative: when a signal is
ambiguous the profile should say less rather than guess, because a wrong fact
produces a confidently wrong refusal or a confidently wrong permission.
"""
import os

import pytest

from sdk.profile import (AGGREGATE_ONLY, DETAILED, MIN_CELL, ProfileError,
                         profile_csv, profile_project)


def write_csv(tmp_path, text):
    path = tmp_path / "d.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestTypeInference:
    def test_integers(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join(str(i) for i in range(50)))
        assert profile_csv(p)["a"].type == "integer"

    def test_decimals(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join("%.2f" % (i/3.0) for i in range(50)))
        assert profile_csv(p)["a"].type == "number"

    def test_timestamps(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join(
            "2110-01-%02d 10:30:00" % (1 + i % 28) for i in range(40)))
        assert profile_csv(p)["a"].type == "timestamp"

    def test_dates(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join(
            "2110-01-%02d" % (1 + i % 28) for i in range(40)))
        assert profile_csv(p)["a"].type == "date"

    def test_few_levels_is_a_category(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join(["M", "F"] * 40))
        assert profile_csv(p)["a"].type == "categorical"

    def test_a_numeric_column_with_few_levels_is_a_category_not_a_measure(self, tmp_path):
        """An ICD version is 9 or 10; averaging it would be meaningless."""
        p = write_csv(tmp_path, "a\n" + "\n".join(["9", "10"] * 40))
        assert profile_csv(p)["a"].type == "categorical"

    def test_many_short_tokens_is_a_code(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join("I%03d" % i for i in range(300)))
        assert profile_csv(p)["a"].type == "code"

    def test_long_free_text_is_not_offered_as_a_stratum(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join(
            "a rather long free text value number %d" % i for i in range(300)))
        leaf = profile_csv(p)["a"]
        assert leaf.type == "string"
        assert not leaf.is_discrete

    def test_an_empty_column_is_unknown_rather_than_guessed(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join([""] * 20))
        assert profile_csv(p)["a"].type == "unknown"


class TestMeasurement:
    def test_counts_distinct_and_nulls(self, tmp_path):
        # a second column keeps the blank row a row: csv skips wholly empty lines
        p = write_csv(tmp_path, "a,b\nM,1\nF,1\nM,1\n,1\n")
        leaf = profile_csv(p)["a"]
        assert leaf.cardinality == 2
        assert leaf.null_rate == 0.25
        assert leaf.coverage == 0.75

    def test_records_a_numeric_range(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join(str(i) for i in range(21, 92)))
        assert profile_csv(p)["a"].value_range == [21, 91]

    def test_lists_categories_when_there_are_few(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join(["M", "F"] * 20))
        assert sorted(profile_csv(p)["a"].categories) == ["F", "M"]

    def test_does_not_list_categories_for_a_wide_column(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join("I%03d" % i for i in range(300)))
        assert profile_csv(p)["a"].categories == []


class TestInferredCaveats:
    def test_detects_a_top_coded_maximum(self, tmp_path):
        """A pile-up at the maximum is how age is capped for de-identification."""
        rows = [str(30 + i % 60) for i in range(600)] + ["91"] * 300
        leaf = profile_csv(write_csv(tmp_path, "age\n" + "\n".join(rows)))["age"]
        assert any("capped at 91" in c for c in leaf.caveats)

    def test_leaves_an_ordinary_distribution_alone(self, tmp_path):
        rows = [str(30 + i % 60) for i in range(600)]
        leaf = profile_csv(write_csv(tmp_path, "age\n" + "\n".join(rows)))["age"]
        assert leaf.caveats == []

    def test_flags_a_code_column_beside_a_version_column(self, tmp_path):
        text = "d.icd_code,d.icd_version\n" + "\n".join(
            "I%03d,%d" % (i, 9 if i % 2 else 10) for i in range(300))
        leaves = profile_csv(write_csv(tmp_path, text))
        assert any("more than one revision" in c
                   for c in leaves["d.icd_code"].caveats)

    def test_does_not_flag_a_code_column_on_its_own(self, tmp_path):
        text = "d.icd_code\n" + "\n".join("I%03d" % i for i in range(300))
        leaves = profile_csv(write_csv(tmp_path, text))
        assert leaves["d.icd_code"].caveats == []


class TestAccessDefaults:
    def test_timestamps_are_aggregate_only(self, tmp_path):
        p = write_csv(tmp_path, "t\n" + "\n".join(
            "2110-01-%02d 09:00:00" % (1 + i % 28) for i in range(40)))
        leaf = profile_csv(p)["t"]
        assert leaf.access_level == AGGREGATE_ONLY
        assert leaf.releasable_as == ["month", "quarter", "year"]

    def test_everything_else_is_detailed(self, tmp_path):
        p = write_csv(tmp_path, "a\n" + "\n".join(["M", "F"] * 20))
        assert profile_csv(p)["a"].access_level == DETAILED


class TestProject:
    def test_measures_an_initialised_project(self, dataset_dir):
        profile = profile_project(str(dataset_dir))
        assert profile.profiled is True
        assert profile.grain.rows == 4000
        assert len(profile.leaves) == 6

    def test_takes_identity_from_the_archetype(self, dataset_dir):
        profile = profile_project(str(dataset_dir))
        assert profile.title == "Test cohort"
        assert profile.archetype_id == "arch-1"
        assert profile.schema_hash == "4f2a91c0b3de00112233"

    def test_there_is_never_an_entity_key(self, dataset_dir):
        """Identifiers are stripped at projection. This is a property of the
        platform, so it needs no declaration and cannot be got wrong."""
        assert profile_project(str(dataset_dir)).has_dedupe_key is False

    def test_says_it_was_measured_not_declared(self, dataset_dir):
        profile = profile_project(str(dataset_dir))
        assert any("measured from the local dataset" in c
                   for c in profile.caveats)

    def test_uses_the_platform_suppression_floor(self, dataset_dir):
        assert profile_project(str(dataset_dir)).min_cell == MIN_CELL

    def test_works_without_an_archetype(self, dataset_dir):
        os.remove(str(dataset_dir / "generated" / "archetype.json"))
        profile = profile_project(str(dataset_dir))
        assert len(profile.leaves) == 6      # the CSV alone is enough
        assert profile.archetype_id is None

    def test_errors_when_there_is_nothing_to_measure(self, tmp_path):
        with pytest.raises(ProfileError) as exc:
            profile_project(str(tmp_path))
        assert "epsilon init" in str(exc.value)
        assert "data.csv" in str(exc.value)


class TestScale:
    def test_stops_after_the_sample_limit(self, tmp_path):
        from sdk.profile import SAMPLE_ROWS
        rows = "\n".join(str(i % 7) for i in range(SAMPLE_ROWS + 5000))
        leaves = profile_csv(write_csv(tmp_path, "a\n" + rows), max_rows=100)
        assert leaves["a"].cardinality <= 7
