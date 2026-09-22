"""Evaluation fixtures and real notebook output checks for shared chart templates."""
import json
import os

import pytest

from evaluation.assistant import CASE_FILE, fixture
from sdk.profile import profile_project
from sdk.workbench import starters
from sdk.workbench.kernel import Kernels


def test_evaluation_bank_uses_only_fabricated_project_fields(tmp_path):
    cases = json.loads(CASE_FILE.read_text())
    assert len(cases) == 30 and len({case['id'] for case in cases}) == 30
    for dates in (False, True):
        root = fixture(tmp_path / str(dates), dates=dates)
        profile = profile_project(root)
        assert not profile.has_dedupe_key
        assert any(leaf.type in ('date', 'timestamp') for leaf in profile.all_leaves()) == dates
        fields = {leaf.path for leaf in profile.all_leaves()}
        for case in cases:
            if case.get('dates', True) == dates:
                assert set(case.get('fields', [])) <= fields
    assert 'from generated.models import create_dataset' in starters.notebook(root, profile, 'describe')['cells'][1]['source']


@pytest.mark.skipif(os.environ.get('EPSILON_TEST_NOTEBOOK') != '1', reason='Opt-in Docker notebook evaluation')
def test_shared_templates_render_figures_and_keep_withheld_groups_out(tmp_path):
    root = fixture(tmp_path / 'fixture')
    profile = profile_project(root)
    kernels = Kernels(tmp_path)
    try:
        kernel = kernels.get('fixture', 'charts', root)
        for method, fields, chart in [
            ('describe', {'field': 'patient.gender'}, 'pie'),
            ('describe', {'field': 'patient.age'}, 'line'),
            ('describe', {'field': 'patient.bmi'}, 'bar'),
            ('cross_tab', {'rows': 'patient.gender', 'cols': 'outcome.diabetic'}, 'bar'),
            ('trend', {}, 'line'),
        ]:
            book = starters.notebook(root, profile, method, fields, chart=chart)
            source = '\n\n'.join(cell['source'] for cell in book['cells'] if cell['kind'] == 'code')
            source = source.replace('plt.show()', 'figure = plt.gcf()\n    plt.show()')
            source += '''
import json
axis = figure.axes[0]
print(json.dumps({"fixture_inspection": True, "shown": [str(i) for i in shown.index],
    "texts": [t.get_text() for t in axis.texts],
    "lines": [[None if pd.isna(v) else float(v) for v in line.get_ydata()] for line in axis.lines]}))
'''
            result = kernel.execute(source)
            assert not result['error'], result.get('text')
            blocks = result['display']['blocks']
            assert any(block['kind'] == 'image' for block in blocks)
            text = '\n'.join(block.get('text', '') for block in blocks)
            assert 'WITHHELD_LABEL_CANARY' not in text
            inspection = next(json.loads(line) for line in text.splitlines() if line.startswith('{"fixture_inspection"'))
            if chart == 'pie':
                assert not any('%' in value for value in inspection['texts'])
            if chart == 'line':
                assert inspection['lines']
            if method == 'trend':
                assert any(value is None for value in inspection['lines'][0]), 'Absent years must break the line.'
    finally:
        kernels.close()
