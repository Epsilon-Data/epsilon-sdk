"""
Describe a dataset by measuring it.

Everything here is derived at `epsilon init` time from two things the SDK
already has: the archetype, and the projected CSV whose headers are guaranteed
to be the archetype's leaf paths. There is no separate metadata artifact --
nothing for a data owner to author, and nothing that can drift from the data
it describes.

What is inferred is inferred conservatively -- when a signal is ambiguous the
profile says less rather than guessing, because every downstream refusal is
only as trustworthy as the fact under it.

The one thing not inferred is the most important: an archetype has no key that
groups rows back to an entity, because identifiers are stripped at projection.
That is a property of the platform, not of any dataset, so it needs no
declaration and cannot be got wrong.
"""
from __future__ import annotations

import csv
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Access levels. Timestamps default to aggregate-only: a raw timestamp is
# rarely releasable and this costs nothing when it is.
DETAILED = "DETAILED"
AGGREGATE_ONLY = "AGGREGATE_ONLY"

TYPE_INTEGER = "integer"
TYPE_NUMBER = "number"
TYPE_CATEGORICAL = "categorical"
TYPE_CODE = "code"
TYPE_TIMESTAMP = "timestamp"
TYPE_DATE = "date"
TYPE_STRING = "string"
TYPE_UNKNOWN = "unknown"

NUMERIC_TYPES = (TYPE_INTEGER, TYPE_NUMBER)
TEMPORAL_TYPES = (TYPE_TIMESTAMP, TYPE_DATE)
DISCRETE_TYPES = (TYPE_CATEGORICAL, TYPE_CODE)

# Platform-wide disclosure floor. One number, not a per-dataset setting.
MIN_CELL = 10

# A field with at most this many distinct values is a category rather than a
# code or free text.
MAX_CATEGORY_LEVELS = 25

# A numeric field whose largest value occurs this many times more often than
# the values just below it has been top-coded -- the standard way an age or an
# income is capped for de-identification.
TOPCODE_RATIO = 2.0

# Rows read to infer types. Enough to be confident, small enough to stay fast
# on a large projection.
SAMPLE_ROWS = 20000

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")

DATA_FILENAME = "data.csv"
ARCHETYPE_FILENAME = "archetype.json"


class ProfileError(Exception):
    """The project has nothing to profile."""


@dataclass
class Leaf:
    path: str
    type: str = TYPE_UNKNOWN
    access_level: str = DETAILED
    cardinality: Optional[int] = None
    null_rate: Optional[float] = None
    value_range: Optional[List[Any]] = None
    categories: List[str] = field(default_factory=list)
    releasable_as: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.rsplit(".", 1)[-1]

    @property
    def group(self) -> Optional[str]:
        return self.path.rsplit(".", 1)[0] if "." in self.path else None

    @property
    def is_numeric(self) -> bool:
        return self.type in NUMERIC_TYPES

    @property
    def is_temporal(self) -> bool:
        return self.type in TEMPORAL_TYPES

    @property
    def is_discrete(self) -> bool:
        return self.type in DISCRETE_TYPES

    @property
    def is_detailed(self) -> bool:
        return self.access_level == DETAILED

    @property
    def coverage(self) -> Optional[float]:
        return None if self.null_rate is None else 1.0 - self.null_rate


@dataclass
class Grain:
    rows: Optional[int] = None
    # Always None: identifiers are stripped at projection, so nothing groups
    # rows back to an entity. Present as a field so the day an archetype grants
    # a pseudonymised key, one assignment unlocks every per-entity analysis.
    dedupe_key: Optional[str] = None
    unit: str = "record"

    @property
    def label(self) -> str:
        return self.unit


@dataclass
class Profile:
    title: str = "Dataset"
    dataset_id: Optional[str] = None
    archetype_id: Optional[str] = None
    schema_hash: Optional[str] = None
    dataset_version: Optional[int] = None
    grain: Grain = field(default_factory=Grain)
    leaves: Dict[str, Leaf] = field(default_factory=dict)
    min_cell: int = MIN_CELL
    caveats: List[str] = field(default_factory=list)
    profiled: bool = False

    # -- selectors the catalogue uses ------------------------------------

    def leaf(self, path: str) -> Optional[Leaf]:
        return self.leaves.get(path)

    def all_leaves(self) -> List[Leaf]:
        return [self.leaves[p] for p in sorted(self.leaves)]

    def numeric_leaves(self, detailed_only: bool = False) -> List[Leaf]:
        return [l for l in self.all_leaves()
                if l.is_numeric and (l.is_detailed or not detailed_only)]

    def discrete_leaves(self, max_cardinality: Optional[int] = None) -> List[Leaf]:
        out = [l for l in self.all_leaves() if l.is_discrete]
        if max_cardinality is not None:
            out = [l for l in out
                   if l.cardinality is None or l.cardinality <= max_cardinality]
        return out

    def binary_leaves(self) -> List[Leaf]:
        return [l for l in self.all_leaves()
                if l.is_discrete and l.cardinality == 2]

    def temporal_leaves(self) -> List[Leaf]:
        return [l for l in self.all_leaves() if l.is_temporal]

    def aggregate_only_leaves(self) -> List[Leaf]:
        return [l for l in self.all_leaves() if l.access_level == AGGREGATE_ONLY]

    @property
    def has_dedupe_key(self) -> bool:
        return bool(self.grain.dedupe_key)


# -- inference -------------------------------------------------------------

def _classify(values: List[str], distinct: int) -> str:
    """Infer a semantic type from observed values."""
    if not values:
        return TYPE_UNKNOWN

    sample = values[:2000]
    if all(_TIMESTAMP.match(v) for v in sample):
        return TYPE_TIMESTAMP
    if all(_DATE.match(v) for v in sample):
        return TYPE_DATE

    ints = floats = 0
    for v in sample:
        try:
            float(v)
        except ValueError:
            break
        floats += 1
        try:
            int(v)
            ints += 1
        except ValueError:
            pass
    else:
        # A numeric column with very few levels is a coded category, not a
        # measurement -- an ICD version or a 0/1 flag.
        if distinct <= 3:
            return TYPE_CATEGORICAL
        return TYPE_INTEGER if ints == floats else TYPE_NUMBER

    if distinct <= MAX_CATEGORY_LEVELS:
        return TYPE_CATEGORICAL
    # Many distinct short tokens is a classification code; anything longer is
    # free text we should not offer as a stratum.
    if all(len(v) <= 12 for v in sample):
        return TYPE_CODE
    return TYPE_STRING


def _topcode_caveat(counts: Counter) -> Optional[str]:
    """Detect a capped maximum -- the usual de-identification of age or income."""
    numeric = {}
    for value, n in counts.items():
        try:
            numeric[float(value)] = n
        except ValueError:
            return None
    if len(numeric) < 8:
        return None
    ordered = sorted(numeric)
    top = ordered[-1]
    below = [numeric[v] for v in ordered[-6:-1]]
    if not below:
        return None
    average = sum(below) / float(len(below))
    if average > 0 and numeric[top] / average >= TOPCODE_RATIO:
        return ("Values appear capped at {0:g}: it occurs {1:.1f}x more often "
                "than the values just below it, which is how a maximum is "
                "usually top-coded for de-identification. Treat it as a "
                "censored band rather than a literal value."
                .format(top, numeric[top] / average))
    return None


def _mixed_code_caveat(leaves: Dict[str, Leaf], path: str,
                       leaf: Leaf) -> Optional[str]:
    """Flag a code column sitting beside a low-cardinality version column.

    Deliberately narrow: same group, one is a code, the other is named for a
    version and has very few levels. That is the shape of ICD-9 and ICD-10 in
    one column, where counting raw codes splits every concept in two.
    """
    if leaf.type != TYPE_CODE or not leaf.group:
        return None
    for other in leaves.values():
        if other.group != leaf.group or other.path == path:
            continue
        if not re.search(r"version|revision|coding", other.name, re.I):
            continue
        if other.cardinality and 2 <= other.cardinality <= 3:
            return ("{0} has {1} values, so this column may hold codes from "
                    "more than one revision. If it does, the same concept "
                    "carries a different code in each and counting raw values "
                    "splits it. Check before matching on codes."
                    .format(other.path, other.cardinality))
    return None


def profile_csv(csv_path: str, max_rows: int = SAMPLE_ROWS) -> Dict[str, Leaf]:
    """Build a leaf per CSV column by measuring the column."""
    counts: Dict[str, Counter] = {}
    blanks: Dict[str, int] = {}
    samples: Dict[str, List[str]] = {}
    total = 0

    with open(csv_path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        for name in columns:
            counts[name] = Counter()
            blanks[name] = 0
            samples[name] = []
        for row in reader:
            total += 1
            for name in columns:
                value = (row.get(name) or "").strip()
                if not value:
                    blanks[name] += 1
                    continue
                counts[name][value] += 1
                if len(samples[name]) < 2000:
                    samples[name].append(value)
            if total >= max_rows:
                break

    leaves: Dict[str, Leaf] = {}
    for name in columns:
        distinct = len(counts[name])
        kind = _classify(samples[name], distinct)
        leaf = Leaf(
            path=name,
            type=kind,
            cardinality=distinct,
            null_rate=(blanks[name] / float(total)) if total else None,
        )
        if kind in DISCRETE_TYPES and distinct <= MAX_CATEGORY_LEVELS:
            leaf.categories = [v for v, _n in counts[name].most_common()]
        if kind in NUMERIC_TYPES:
            numbers = []
            for v in counts[name]:
                try:
                    numbers.append(float(v))
                except ValueError:
                    pass
            if numbers:
                low, high = min(numbers), max(numbers)
                leaf.value_range = [int(low), int(high)] if kind == TYPE_INTEGER \
                    else [low, high]
            caveat = _topcode_caveat(counts[name])
            if caveat:
                leaf.caveats.append(caveat)
        if kind in TEMPORAL_TYPES:
            # Raw timestamps are rarely releasable; bucketing costs nothing
            # when they would have been.
            leaf.access_level = AGGREGATE_ONLY
            leaf.releasable_as = ["month", "quarter", "year"]
        leaves[name] = leaf

    for path, leaf in leaves.items():
        caveat = _mixed_code_caveat(leaves, path, leaf)
        if caveat:
            leaf.caveats.append(caveat)
    return leaves


def count_rows(csv_path: str) -> int:
    with open(csv_path, "r", encoding="utf-8") as fh:
        return max(sum(1 for _ in fh) - 1, 0)


def profile_project(project_dir: str = ".",
                    generated_dir: str = "generated") -> Profile:
    """Profile an initialised project. Raises when there is nothing to read."""
    base = os.path.join(project_dir, generated_dir)
    csv_path = os.path.join(base, DATA_FILENAME)
    archetype_path = os.path.join(base, ARCHETYPE_FILENAME)

    if not os.path.exists(csv_path):
        raise ProfileError(
            "no {0} in {1} -- run 'epsilon init <dataset_id>' first".format(
                DATA_FILENAME, base))

    profile = Profile(profiled=True)
    profile.leaves = profile_csv(csv_path)
    profile.grain = Grain(rows=count_rows(csv_path), dedupe_key=None,
                          unit="record")

    if os.path.exists(archetype_path):
        import json
        try:
            with open(archetype_path, "r", encoding="utf-8") as fh:
                archetype = json.load(fh)
        except (ValueError, OSError):
            archetype = {}
        profile.title = archetype.get("title") or "Dataset"
        full_id = str(archetype.get("$id") or "")
        dataset_id, _, archetype_id = full_id.partition("/")
        profile.dataset_id = dataset_id or None
        profile.archetype_id = archetype_id or None
        synthetic = archetype.get("syntheticData") or {}
        profile.schema_hash = synthetic.get("schemaHash")
        profile.dataset_version = synthetic.get("version")

    profile.caveats.append(
        "This description was measured from the local dataset, not supplied "
        "by the data owner. Value domains and distributions are as observed; "
        "anything the data means beyond its shape is not captured here.")
    return profile
