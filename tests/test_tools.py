"""
Tests for the agent's tools.

Several of these encode mistakes a real model made driving this toolbox:
passing every column as a list, nesting {"fields": [...]}, naming a module
"describe.py" when it lives in analyses/. A tool a model cannot drive is a tool
that burns turns, so each of those has to fail with a message that says what to
do instead -- or not fail at all.
"""
import json
import os

import pytest

from sdk.tools import ToolError, Toolbox, build_tools


# A stand-in for the codegen output: dot-path attribute access over CSV rows,
# which is the API every generated snippet targets.
MODELS = '''
import csv, os

COLUMNS = ["admissions.time", "admissions.type", "patient.gender",
           "patient.age", "diagnoses.icd_code", "diagnoses.icd_version"]


class Group(object):
    def __init__(self, row, prefix):
        self._row, self._prefix = row, prefix

    def __getattr__(self, name):
        return self._row.get(self._prefix + "." + name)


class Record(object):
    def __init__(self, row):
        self._row = row

    def __getattr__(self, name):
        return Group(self._row, name)


class DatasetWrapper(object):
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        for row in self.rows:
            yield Record(row)


def create_dataset(csv_file=None):
    path = csv_file or os.path.join("generated", "data.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        return DatasetWrapper(list(csv.DictReader(fh)))
'''

