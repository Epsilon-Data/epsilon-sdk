"""Tests for the dataset card: parsing, derivation, loading, drift."""
import json
import os

import pytest

from sdk.card import (Card, CardError, DETAILED, HIGH_LEVEL, derive_card,
                      load_card)


class TestParsing:
    def test_reads_leaves_and_grain(self, card):
        assert len(card.leaves) == 6
        assert card.grain.unit == "diagnosis_record"
        assert card.grain.rows == 100000
        assert card.derived is False

    def test_rejects_a_future_card_version(self, card_json):
        card_json["cardVersion"] = 99
        with pytest.raises(CardError) as exc:
            Card.from_json(card_json)
        assert "upgrade epsilon-sdk" in str(exc.value)

    def test_rejects_a_non_object(self):
        with pytest.raises(CardError):
            Card.from_json([1, 2, 3])

    def test_rejects_malformed_leaves(self, card_json):
        card_json["leaves"] = ["patient.age"]
        with pytest.raises(CardError):
            Card.from_json(card_json)

    def test_leaf_paths_split_into_group_and_name(self, card):
        leaf = card.leaf("patient.age")
        assert leaf.group == "patient"
        assert leaf.name == "age"

    def test_coverage_is_the_complement_of_null_rate(self, card):
        assert card.leaf("patient.age").coverage == 1.0

    def test_coverage_is_unknown_when_null_rate_is(self, card_json):
        del card_json["leaves"]["patient.age"]["nullRate"]
        card = Card.from_json(card_json)
        assert card.leaf("patient.age").coverage is None


class TestSelectors:
    def test_numeric_and_discrete_are_distinguished(self, card):
        assert [l.path for l in card.numeric_leaves()] == ["patient.age"]
        assert "diagnoses.icd_code" in [l.path for l in card.discrete_leaves()]

    def test_binary_leaves_need_exactly_two_levels(self, card):
        paths = [l.path for l in card.binary_leaves()]
        assert "patient.gender" in paths
        assert "admissions.type" not in paths  # nine levels

    def test_max_cardinality_filters_wide_columns(self, card):
        paths = [l.path for l in card.discrete_leaves(max_cardinality=20)]
        assert "diagnoses.icd_code" not in paths  # 1472 distinct codes

    def test_mixed_code_leaves_are_found(self, card):
        assert [l.path for l in card.mixed_code_leaves()] == ["diagnoses.icd_code"]

    def test_aggregate_only_leaves_are_found(self, card):
        leaves = card.aggregate_only_leaves()
        assert [l.path for l in leaves] == ["admissions.time"]
        assert leaves[0].access_level == HIGH_LEVEL

    def test_has_dedupe_key_reflects_the_grain(self, card, unblocked_card):
        assert card.has_dedupe_key is False
        assert unblocked_card.has_dedupe_key is True

    def test_rows_per_entity_uses_the_smallest_entity_count(self, card):
        assert card.grain.rows_per_entity == 1000.0  # 100000 rows / 100 patients


class TestDerivation:
    def test_branches_are_walked_and_leaves_collected(self, mock_archetype):
        card = derive_card(mock_archetype)
        assert sorted(card.leaves) == [
            "patient.age", "patient.id", "patient.name",
            "vitals.bloodpressure", "vitals.heartrate",
        ]

    def test_empty_branches_are_not_leaves(self):
        archetype = {"$id": "a/b", "properties": {
            "root": {"type": "object", "properties": {}},
            "demographics": {"type": "object", "properties": {
                "age": {"type": "integer"}}}}}
        card = derive_card(archetype)
        assert sorted(card.leaves) == ["demographics.age"]

    def test_unmapped_object_types_become_unknown_not_dropped(self, mock_archetype):
        card = derive_card(mock_archetype)
        # The archetype says "object" because Atlas's data_type did not map.
        # The field is real and must survive, with its type marked unknown.
        assert card.leaf("vitals.bloodpressure").type == "unknown"

    def test_derived_cards_admit_they_know_nothing_about_grain(self, mock_archetype):
        card = derive_card(mock_archetype)
        assert card.derived is True
        assert card.grain.known is False
        assert card.has_dedupe_key is False
        assert any("no dataset card" in c.lower() for c in card.caveats)

    def test_types_are_never_authoritative_on_a_derived_card(self, mock_archetype):
        """Two leaves carry a real type from the schema; that is not enough."""
        card = derive_card(mock_archetype)
        assert card.leaf("patient.age").type == "integer"
        assert card.types_known is False

    def test_types_are_authoritative_on_a_published_card(self, card):
        assert card.types_known is True

    def test_id_is_split_into_dataset_and_archetype(self):
        card = derive_card({"$id": "proj-1/arch-9", "properties": {}})
        assert card.dataset_id == "proj-1"
        assert card.archetype_id == "arch-9"


class TestLoading:
    def _write(self, tmp_path, name, payload):
        generated = tmp_path / "generated"
        generated.mkdir(exist_ok=True)
        (generated / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_prefers_a_published_card(self, tmp_path, card_json, mock_archetype):
        self._write(tmp_path, "card.json", card_json)
        self._write(tmp_path, "archetype.json", mock_archetype)
        card = load_card(str(tmp_path))
        assert card.derived is False
        assert card.title == "Test cohort"

    def test_falls_back_to_the_archetype(self, tmp_path, mock_archetype):
        self._write(tmp_path, "archetype.json", mock_archetype)
        card = load_card(str(tmp_path))
        assert card.derived is True

    def test_errors_when_the_project_is_not_initialised(self, tmp_path):
        with pytest.raises(CardError) as exc:
            load_card(str(tmp_path))
        assert "epsilon init" in str(exc.value)

    def test_errors_on_invalid_json(self, tmp_path):
        generated = tmp_path / "generated"
        generated.mkdir()
        (generated / "card.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(CardError) as exc:
            load_card(str(tmp_path))
        assert "not valid JSON" in str(exc.value)

    def test_drift_is_reported_when_the_archetype_grants_more(self, tmp_path, card_json,
                                                              mock_archetype):
        self._write(tmp_path, "card.json", card_json)
        self._write(tmp_path, "archetype.json", mock_archetype)
        card = load_card(str(tmp_path))
        assert any("out of date" in c for c in card.caveats)
        assert any("patient.name" in c for c in card.caveats)

    def test_no_drift_reported_when_they_agree(self, tmp_path, card_json):
        archetype = {"$id": "ds-1/arch-1", "properties": {}}
        properties = {}
        for path in card_json["leaves"]:
            group, name = path.split(".")
            properties.setdefault(group, {"type": "object", "properties": {}})
            properties[group]["properties"][name] = {"type": "string"}
        archetype["properties"] = properties
        self._write(tmp_path, "card.json", card_json)
        self._write(tmp_path, "archetype.json", archetype)
        card = load_card(str(tmp_path))
        assert not any("out of date" in c for c in card.caveats)
