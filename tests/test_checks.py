"""Tests for the local submission checks."""
import os

import pytest

from sdk.checks import (BLOCK, WARN, check_project, check_requirements,
                        check_packaging, check_source, local_modules,
                        scan_secrets, should_scan_secrets, summarise)


def rules(findings):
    return set(f.rule for f in findings)


def blocking(findings):
    return [f for f in findings if f.blocking]


CLEAN = '''
from collections import Counter
from generated.models import create_dataset

MIN_CELL = 10


def main():
    dataset = create_dataset()
    counts = Counter()
    for record in dataset:
        counts[record.patient.gender] += 1
    return {k: (v if v >= MIN_CELL else None) for k, v in counts.items()}
'''


class TestRecordOutput:
    def test_printing_a_record_is_blocked(self):
        source = '''
from generated.models import create_dataset
dataset = create_dataset()
for record in dataset:
    print(record)
'''
        findings = check_source("a.py", source)
        assert "no-record-output" in rules(findings)
        assert blocking(findings)

    def test_printing_a_field_of_a_record_is_also_blocked(self):
        source = '''
from generated.models import create_dataset
dataset = create_dataset()
for row in dataset:
    print(row.patient.age)
'''
        findings = check_source("a.py", source)
        assert "no-record-output" in rules(findings)
        assert any("row.patient.age" in f.message for f in findings)

    def test_printing_the_dataset_is_blocked(self):
        source = '''
from generated.models import create_dataset
dataset = create_dataset()
print(dataset)
'''
        assert "no-record-output" in rules(check_source("a.py", source))

    def test_printing_an_aggregate_is_fine(self):
        assert "no-record-output" not in rules(check_source("a.py", CLEAN))

    def test_printing_an_unrelated_variable_is_fine(self):
        source = '''
total = 5
for x in [1, 2, 3]:
    print(x)
print(total)
'''
        assert "no-record-output" not in rules(check_source("a.py", source))


class TestEgressAndExecution:
    def test_network_imports_are_blocked(self):
        for module in ("requests", "socket", "urllib.request", "httpx"):
            findings = check_source("a.py", "import {0}\n".format(module))
            assert "no-network" in rules(findings), module

    def test_from_imports_are_caught_too(self):
        findings = check_source("a.py", "from urllib.request import urlopen\n")
        assert "no-network" in rules(findings)

    def test_subprocess_is_blocked(self):
        assert "no-subprocess" in rules(check_source("a.py", "import subprocess\n"))

    def test_os_system_is_blocked(self):
        assert "no-subprocess" in rules(check_source("a.py", "import os\nos.system('ls')\n"))

    def test_eval_is_blocked(self):
        assert "no-dynamic-exec" in rules(check_source("a.py", "eval('1+1')\n"))

    def test_ordinary_stdlib_imports_are_fine(self):
        findings = check_source("a.py", "import json\nimport collections\n")
        assert findings == []


class TestDataframeWrites:
    def test_to_csv_is_a_warning_not_a_block(self):
        findings = check_source("a.py", "df.to_csv('out.csv')\n")
        assert "check-output-shape" in rules(findings)
        assert not blocking(findings)


class TestSyntax:
    def test_unparseable_files_block(self):
        findings = check_source("a.py", "def broken(\n")
        assert "parse-error" in rules(findings)
        assert blocking(findings)


class TestRequirements:
    def test_unpinned_dependencies_warn(self, tmp_path):
        path = tmp_path / "requirements.txt"
        path.write_text("pandas\nnumpy==1.26.0\n# comment\n\n", encoding="utf-8")
        findings = check_requirements(str(path))
        assert len(findings) == 1
        assert "pandas" in findings[0].message
        assert findings[0].level == WARN

    def test_urls_and_flags_are_left_alone(self, tmp_path):
        path = tmp_path / "requirements.txt"
        path.write_text("-r other.txt\nhttps://example.com/x.whl\n", encoding="utf-8")
        assert check_requirements(str(path)) == []


class TestSecrets:
    def test_an_anthropic_key_blocks(self):
        text = 'KEY = "sk-ant-api03-' + "A" * 40 + '"'
        findings = scan_secrets("a.py", text)
        assert findings and findings[0].blocking
        assert "epsilon build" in findings[0].message

    def test_aws_and_github_shapes_block(self):
        assert scan_secrets("a.py", "AKIA" + "A" * 16)
        assert scan_secrets("a.py", "ghp_" + "b" * 36)

    def test_private_keys_block(self):
        assert scan_secrets("a.py", "-----BEGIN RSA PRIVATE KEY-----")

    def test_a_suspicious_assignment_only_warns(self):
        findings = scan_secrets("a.py", 'password = "correct-horse-battery-staple"')
        assert findings
        assert not findings[0].blocking

    def test_ordinary_code_is_not_flagged(self):
        assert scan_secrets("a.py", "x = 1\ntoken = None\n") == []


class TestDotfilesAreScanned:
    """os.path.splitext('.env') == ('.env', ''), so an extension allowlist
    silently skips exactly the files credentials live in."""

    @pytest.mark.parametrize("name", [
        ".env", ".env.local", ".envrc", ".netrc", ".npmrc", "credentials"])
    def test_secret_bearing_filenames_are_selected(self, name):
        assert should_scan_secrets(name)

    def test_ordinary_dotfiles_are_not(self):
        assert not should_scan_secrets(".gitignore")
        assert not should_scan_secrets("data.csv")

    def test_a_key_in_dotenv_blocks(self, tmp_path):
        (tmp_path / ".env").write_text(
            "ANTHROPIC_API_KEY=sk-ant-api03-" + "A" * 38 + "\n", encoding="utf-8")
        findings = check_project(str(tmp_path))
        assert [f for f in findings if f.blocking], findings

    def test_an_env_file_warns_even_when_it_looks_empty(self, tmp_path):
        (tmp_path / ".env").write_text("DEBUG=1\n", encoding="utf-8")
        findings = check_project(str(tmp_path))
        assert findings
        assert "environment file" in findings[0].message


class TestProjectScan:
    def _project(self, tmp_path, files):
        for name, content in files.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return str(tmp_path)

    def test_a_clean_project_passes(self, tmp_path):
        root = self._project(tmp_path, {
            "main.py": CLEAN, "requirements.txt": "pandas==2.0.0\n"})
        assert check_project(root) == []

    def test_generated_code_is_exempt_from_the_ast_rules(self, tmp_path):
        root = self._project(tmp_path, {
            "generated/models.py": "import requests\n"})
        assert "no-network" not in rules(check_project(root))

    def test_generated_code_is_not_exempt_from_the_secret_scan(self, tmp_path):
        root = self._project(tmp_path, {
            "generated/models.py": 'K = "sk-ant-api03-' + "A" * 40 + '"'})
        findings = check_project(root)
        assert "no-secrets" in rules(findings)

    def test_virtualenvs_are_skipped(self, tmp_path):
        root = self._project(tmp_path, {".venv/lib/thing.py": "import socket\n"})
        assert check_project(root) == []

    def test_blocking_findings_sort_first(self, tmp_path):
        root = self._project(tmp_path, {
            "a.py": "import requests\n", "requirements.txt": "pandas\n"})
        findings = check_project(root)
        assert findings[0].blocking
        assert not findings[-1].blocking


class TestSummary:
    def test_reports_nothing_when_clean(self):
        assert summarise([]) == "All checks passed."

    def test_counts_blocking_and_warnings(self):
        findings = check_source("a.py", "import requests\ndf.to_csv('x')\n")
        text = summarise(findings)
        assert "1 blocking issue" in text
        assert "1 warning" in text


class TestPackaging:
    """`epsilon build` ships a subset of the project. An import that does not
    survive it fails inside the enclave, after the queue."""

    def _project(self, tmp_path, files):
        for name, content in files.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return str(tmp_path)

    def test_local_modules_are_discovered(self, tmp_path):
        root = self._project(tmp_path, {
            "helpers.py": "X = 1\n",
            "analyses/__init__.py": "",
            "notes/thing.txt": "",
        })
        found = local_modules(root)
        assert "helpers" in found
        assert "analyses" in found
        assert "notes" not in found  # no __init__.py

    def test_an_unpackaged_import_blocks(self, tmp_path):
        root = self._project(tmp_path, {
            "helpers.py": "X = 1\n",
            "main.py": "from helpers import X\n",
        })
        findings = check_packaging(root, "main.py", {"generated", "analyses"})
        assert findings and findings[0].blocking
        assert "helpers" in findings[0].message

    def test_a_packaged_import_is_fine(self, tmp_path):
        root = self._project(tmp_path, {
            "analyses/__init__.py": "",
            "analyses/table.py": "def main():\n    return {}\n",
            "main.py": "from analyses.table import main\n",
        })
        assert check_packaging(root, "main.py", {"generated", "analyses"}) == []

    def test_stdlib_and_third_party_imports_are_ignored(self, tmp_path):
        root = self._project(tmp_path, {
            "main.py": "import json\nimport pandas\n"})
        assert check_packaging(root, "main.py", {"generated", "analyses"}) == []

    def test_imports_inside_packaged_code_are_checked_too(self, tmp_path):
        root = self._project(tmp_path, {
            "helpers.py": "X = 1\n",
            "analyses/__init__.py": "",
            "analyses/table.py": "from helpers import X\n",
            "main.py": "from analyses.table import X\n",
        })
        findings = check_packaging(root, "main.py", {"generated", "analyses"})
        assert findings and "helpers" in findings[0].message

    def test_each_missing_module_is_reported_once(self, tmp_path):
        root = self._project(tmp_path, {
            "helpers.py": "X = 1\n",
            "analyses/__init__.py": "",
            "analyses/a.py": "from helpers import X\n",
            "analyses/b.py": "from helpers import X\n",
            "main.py": "from helpers import X\n",
        })
        findings = check_packaging(root, "main.py", {"generated", "analyses"})
        assert len(findings) == 1


class TestPlottingLibraries:
    def test_matplotlib_warns_and_points_at_the_generator(self):
        findings = check_source("a.py", "import matplotlib.pyplot as plt\n")
        assert "chart-from-released-result" in rules(findings)
        assert not findings[0].blocking
        assert "--chart" in findings[0].fix

    def test_other_plotting_libraries_too(self):
        for module in ("seaborn", "plotly", "altair"):
            assert "chart-from-released-result" in rules(
                check_source("a.py", "import {0}\n".format(module)))

    def test_it_is_a_warning_not_a_block(self):
        findings = check_source("a.py", "import seaborn\n")
        assert [f for f in findings if f.blocking] == []
