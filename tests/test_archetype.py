"""
Tests for archetype helpers (field extraction and synthetic CSV verification)
"""
import pytest

from sdk.archetype import extract_fields_from_archetype, verify_synthetic_csv


def make_archetype(schema_hash='hash_a'):
    """Archetype JSON with nested (branch.leaf) properties"""
    return {
        '$id': 'test_project/test_archetype_id',
        '$schema': 'https://json-schema.org/draft/2020-12/schema#',
        'title': 'Test Dataset',
        'type': 'object',
        'properties': {
            'patient': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'integer'},
                    'age': {'type': 'integer'}
                }
            },
            'score': {'type': 'number'}
        },
        'syntheticData': {'available': True, 'schemaHash': schema_hash, 'version': 2}
    }


class TestExtractFieldsFromArchetype:
    """Test suite for extract_fields_from_archetype"""

    def test_nested_dot_paths(self):
        fields = extract_fields_from_archetype(make_archetype())

        assert {path for path, _ in fields} == {'patient.id', 'patient.age', 'score'}

    def test_flat_paths(self):
        fields = extract_fields_from_archetype({
            'type': 'object',
            'properties': {'field1': {'type': 'string'}}
        })

        assert fields == [('field1', 'string')]


class TestVerifySyntheticCsv:
    """Test suite for verify_synthetic_csv"""

    def test_matching_headers_and_hash(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        csv_path.write_text('patient.id,patient.age,score\n1,42,0.5\n', encoding='utf-8')

        # Should not raise
        verify_synthetic_csv(str(csv_path), make_archetype(), 'hash_a')

    def test_bom_header_is_stripped(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        # utf-8-sig prefixes the file with a UTF-8 BOM
        csv_path.write_text('patient.id,patient.age,score\n1,42,0.5\n', encoding='utf-8-sig')

        # Should not raise despite the BOM before the first header cell
        verify_synthetic_csv(str(csv_path), make_archetype(), 'hash_a')

    def test_header_mismatch_lists_columns(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        csv_path.write_text('patient.id,unexpected_col\n1,2\n', encoding='utf-8')

        with pytest.raises(ValueError) as exc_info:
            verify_synthetic_csv(str(csv_path), make_archetype(), 'hash_a')

        message = str(exc_info.value)
        assert 'patient.age' in message
        assert 'score' in message
        assert 'unexpected_col' in message

    def test_duplicate_columns_rejected(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        csv_path.write_text('patient.id,patient.age,score,score\n1,42,0.5,99\n', encoding='utf-8')

        with pytest.raises(ValueError, match="duplicated") as exc_info:
            verify_synthetic_csv(str(csv_path), make_archetype(), 'hash_a')

        assert 'score' in str(exc_info.value)

    def test_schema_hash_mismatch(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        csv_path.write_text('patient.id,patient.age,score\n1,42,0.5\n', encoding='utf-8')

        with pytest.raises(ValueError, match="epsilon init"):
            verify_synthetic_csv(str(csv_path), make_archetype('hash_a'), 'hash_b')

    def test_missing_server_hash_skips_hash_check(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        csv_path.write_text('patient.id,patient.age,score\n1,42,0.5\n', encoding='utf-8')

        # Should not raise: nothing to compare against
        verify_synthetic_csv(str(csv_path), make_archetype(), None)

    def test_missing_descriptor_hash_skips_hash_check(self, tmp_path):
        archetype = make_archetype()
        del archetype['syntheticData']
        csv_path = tmp_path / 'data.csv'
        csv_path.write_text('patient.id,patient.age,score\n1,42,0.5\n', encoding='utf-8')

        # Should not raise: archetype pins no hash
        verify_synthetic_csv(str(csv_path), archetype, 'hash_b')

    def test_empty_csv(self, tmp_path):
        csv_path = tmp_path / 'data.csv'
        csv_path.write_text('', encoding='utf-8')

        with pytest.raises(ValueError, match="no header row"):
            verify_synthetic_csv(str(csv_path), make_archetype(), 'hash_a')
