"""
Dataset Card: the semantic layer over an archetype.

An archetype says which columns a researcher may touch. It does not say what
those columns *mean* -- the served JSON Schema carries title-cased labels as
descriptions, collapses unmapped Atlas types to "object", and states nothing
about the grain of a row. A Card fills that gap: it is authored by the data
owner, attested by them, and pinned to the same schema hash as the synthetic
dataset the researcher develops against.

Cards are plain JSON. Nothing in this module calls a model.

When no card is published for a dataset, `derive_card` builds a thin one from
the archetype alone. A derived card is explicitly marked, its grain is unknown,
and downstream consumers (see sdk.catalogue) must refuse any analysis whose
correctness depends on knowing the grain.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CARD_VERSION = 1

CARD_FILENAME = "card.json"
ARCHETYPE_FILENAME = "archetype.json"

# Access levels, from the archetype node classification. NONE-level nodes are
# stripped server-side and never reach a card.
DETAILED = "DETAILED"
HIGH_LEVEL = "HIGH_LEVEL"

# Semantic types a card leaf may declare. Broader than JSON Schema's set
# because the distinctions matter for choosing an analysis.
TYPE_INTEGER = "integer"
TYPE_NUMBER = "number"
TYPE_CATEGORICAL = "categorical"
TYPE_CODE = "code"
TYPE_TIMESTAMP = "timestamp"
TYPE_DURATION = "duration"
TYPE_DATE = "date"
TYPE_STRING = "string"
TYPE_UNKNOWN = "unknown"

NUMERIC_TYPES = (TYPE_INTEGER, TYPE_NUMBER)
TEMPORAL_TYPES = (TYPE_TIMESTAMP, TYPE_DATE)
DURATION_TYPES = (TYPE_DURATION,)
DISCRETE_TYPES = (TYPE_CATEGORICAL, TYPE_CODE)


class CardError(Exception):
    """Raised when a card is malformed or inconsistent with its archetype."""


@dataclass
class CodeSystem:
    """A coding system attached to a code-typed leaf.

    `discriminator` names another leaf whose value selects the system for a
    given row -- the MIMIC-IV case, where icd_version picks ICD-9 vs ICD-10 and
    the same condition therefore carries two different codes.
    """
    systems: Dict[str, str] = field(default_factory=dict)
    discriminator: Optional[str] = None
    mixed: bool = False
    split: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "CodeSystem":
        return cls(
            systems=dict(raw.get("systems") or {}),
            discriminator=raw.get("discriminator"),
            mixed=bool(raw.get("mixed", False)),
            split={str(k): float(v) for k, v in (raw.get("split") or {}).items()},
        )

    def describe(self) -> str:
        names = [self.systems[k] for k in sorted(self.systems)]
        if not names:
            return "unspecified coding system"
        if len(names) == 1:
            return names[0]
        return " and ".join((", ".join(names[:-1]), names[-1]))


@dataclass
class Leaf:
    """One analysable field, addressed by its dot path in the archetype."""
    path: str
    type: str = TYPE_UNKNOWN
    access_level: str = DETAILED
    source: Optional[str] = None
    description: Optional[str] = None
    unit: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    cardinality: Optional[int] = None
    null_rate: Optional[float] = None
    value_range: Optional[List[Any]] = None
    code_system: Optional[CodeSystem] = None
    releasable_as: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    # None means the card takes no position. False means values cannot be
    # compared between entities -- de-identified data is routinely date-shifted
    # by a per-entity offset, which makes any cross-entity time axis
    # meaningless while leaving each entity's own intervals intact.
    comparable_across_entities: Optional[bool] = None

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
    def is_duration(self) -> bool:
        return self.type in DURATION_TYPES

    @property
    def is_discrete(self) -> bool:
        return self.type in DISCRETE_TYPES

    @property
    def is_detailed(self) -> bool:
        return self.access_level == DETAILED

    @property
    def coverage(self) -> Optional[float]:
        """Share of rows with a value, as a fraction."""
        if self.null_rate is None:
            return None
        return 1.0 - self.null_rate

    @classmethod
    def from_json(cls, path: str, raw: Dict[str, Any]) -> "Leaf":
        code_system = raw.get("codeSystem")
        return cls(
            path=path,
            type=raw.get("type") or TYPE_UNKNOWN,
            access_level=raw.get("accessLevel") or DETAILED,
            source=raw.get("source"),
            description=raw.get("description"),
            unit=raw.get("unit"),
            categories=list(raw.get("categories") or []),
            cardinality=raw.get("cardinality"),
            null_rate=raw.get("nullRate"),
            value_range=raw.get("range"),
            code_system=CodeSystem.from_json(code_system) if code_system else None,
            releasable_as=list(raw.get("releasableAs") or []),
            caveats=list(raw.get("caveats") or []),
            comparable_across_entities=raw.get("comparableAcrossEntities"),
        )


@dataclass
class Grain:
    """What one row of the projected dataset is.

    `dedupe_key` is the leaf path that groups rows back to the entity of
    interest. When it is None the dataset cannot be collapsed -- any per-entity
    quantity is not computable, no matter how the analysis is written.
    """
    unit: str = "unknown"
    statement: Optional[str] = None
    rows: Optional[int] = None
    dedupe_key: Optional[str] = None
    entity_counts: Dict[str, int] = field(default_factory=dict)
    known: bool = True

    @property
    def rows_per_entity(self) -> Optional[float]:
        """Mean rows per entity, when the card names an entity count."""
        if not self.rows or not self.entity_counts:
            return None
        smallest = min(self.entity_counts.values())
        if smallest <= 0:
            return None
        return self.rows / float(smallest)

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "Grain":
        return cls(
            unit=raw.get("unit") or "unknown",
            statement=raw.get("statement"),
            rows=raw.get("rows"),
            dedupe_key=raw.get("dedupeKey"),
            entity_counts={str(k): int(v) for k, v in (raw.get("entityCounts") or {}).items()},
            known=bool(raw.get("known", True)),
        )


@dataclass
class Policy:
    """Disclosure rules the researcher's code has to satisfy."""
    min_cell: int = 10
    allow_ai_profiling: bool = False
    max_output_rows: Optional[int] = None

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "Policy":
        return cls(
            min_cell=int(raw.get("minCell", 10)),
            allow_ai_profiling=bool(raw.get("allowAiProfiling", False)),
            max_output_rows=raw.get("maxOutputRows"),
        )


@dataclass
class Card:
    title: str = "Untitled dataset"
    dataset_id: Optional[str] = None
    archetype_id: Optional[str] = None
    schema_hash: Optional[str] = None
    dataset_version: Optional[int] = None
    grain: Grain = field(default_factory=Grain)
    leaves: Dict[str, Leaf] = field(default_factory=dict)
    policy: Policy = field(default_factory=Policy)
    caveats: List[str] = field(default_factory=list)
    excluded: List[str] = field(default_factory=list)
    attested_by: Optional[Dict[str, Any]] = None
    derived: bool = False

    # -- selectors used by the catalogue ----------------------------------

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

    def duration_leaves(self) -> List[Leaf]:
        return [l for l in self.all_leaves() if l.is_duration]

    def code_leaves(self) -> List[Leaf]:
        return [l for l in self.all_leaves() if l.type == TYPE_CODE]

    def mixed_code_leaves(self) -> List[Leaf]:
        return [l for l in self.code_leaves()
                if l.code_system is not None and l.code_system.mixed]

    def aggregate_only_leaves(self) -> List[Leaf]:
        return [l for l in self.all_leaves() if l.access_level == HIGH_LEVEL]

    @property
    def has_dedupe_key(self) -> bool:
        return bool(self.grain.dedupe_key)

    # -- serialisation ----------------------------------------------------

    @classmethod
    def from_json(cls, raw: Dict[str, Any]) -> "Card":
        if not isinstance(raw, dict):
            raise CardError("card must be a JSON object")
        version = raw.get("cardVersion", CARD_VERSION)
        if version != CARD_VERSION:
            raise CardError(
                "unsupported card version {0} (this SDK reads version {1}); "
                "upgrade epsilon-sdk".format(version, CARD_VERSION)
            )
        leaves_raw = raw.get("leaves") or {}
        if not isinstance(leaves_raw, dict):
            raise CardError("card 'leaves' must be an object keyed by dot path")
        return cls(
            title=raw.get("title") or "Untitled dataset",
            dataset_id=raw.get("datasetId"),
            archetype_id=raw.get("archetype"),
            schema_hash=raw.get("schemaHash"),
            dataset_version=raw.get("datasetVersion"),
            grain=Grain.from_json(raw.get("grain") or {}),
            leaves={p: Leaf.from_json(p, v) for p, v in leaves_raw.items()},
            policy=Policy.from_json(raw.get("policy") or {}),
            caveats=list(raw.get("caveats") or []),
            excluded=list(raw.get("excluded") or []),
            attested_by=raw.get("attestedBy"),
            derived=bool(raw.get("derived", False)),
        )


# -- deriving a card when none is published -------------------------------

# Atlas data_type strings, lowercased, mapped onto card semantic types. The
# archetype's JSON Schema type is a poor source on its own: unmapped Atlas
# types arrive as "object".
_JSON_SCHEMA_TYPES = {
    "integer": TYPE_INTEGER,
    "number": TYPE_NUMBER,
    "string": TYPE_STRING,
    "boolean": TYPE_CATEGORICAL,
}


def _walk_schema(node: Dict[str, Any], prefix: str = "") -> List[tuple]:
    """Yield (dot_path, subschema) for every leaf property in an archetype."""
    out = []
    props = node.get("properties")
    if not isinstance(props, dict):
        return out
    for name, sub in props.items():
        if not isinstance(sub, dict):
            continue
        path = "{0}.{1}".format(prefix, name) if prefix else name
        if "properties" in sub:
            # A branch. Empty branches (archetypes routinely carry an empty
            # "root") contribute no leaves and are not fields themselves.
            out.extend(_walk_schema(sub, path))
        else:
            # A leaf. Note that type may be "object" here: that is an Atlas
            # data_type the API failed to map, not a nested structure.
            out.append((path, sub))
    return out


def derive_card(archetype: Dict[str, Any]) -> Card:
    """Build a thin, explicitly-degraded card from an archetype alone.

    The result is honest about what it does not know: grain is unknown and no
    dedupe key is claimed, so the catalogue will refuse per-entity analyses
    rather than silently permitting a mis-weighted one.
    """
    full_id = str(archetype.get("$id") or "")
    dataset_id, _, archetype_id = full_id.partition("/")
    leaves = {}
    for path, sub in _walk_schema(archetype):
        # Skip structural nodes that carry no properties and no type at all,
        # e.g. the empty "root" branch archetypes often contain.
        if not sub:
            continue
        leaves[path] = Leaf(
            path=path,
            type=_JSON_SCHEMA_TYPES.get(sub.get("type"), TYPE_UNKNOWN),
            description=sub.get("description"),
        )
    synthetic = archetype.get("syntheticData") or {}
    return Card(
        title=archetype.get("title") or "Untitled dataset",
        dataset_id=dataset_id or None,
        archetype_id=archetype_id or None,
        schema_hash=synthetic.get("schemaHash"),
        dataset_version=synthetic.get("version"),
        grain=Grain(unit="unknown", known=False, statement=None),
        leaves=leaves,
        caveats=[
            "No dataset card is published for this archetype, so this "
            "description was derived from the archetype alone. Field types, "
            "value domains, coding systems and the grain of a row are all "
            "unknown. Ask the data owner to publish a card.",
        ],
        derived=True,
    )


# -- loading ---------------------------------------------------------------

def load_card(project_dir: str = ".", generated_dir: str = "generated") -> Card:
    """Load the card for a project, deriving one from the archetype if absent.

    Raises CardError when neither a card nor an archetype can be found, which
    means the directory is not an initialised Epsilon project.
    """
    base = os.path.join(project_dir, generated_dir)
    card_path = os.path.join(base, CARD_FILENAME)
    archetype_path = os.path.join(base, ARCHETYPE_FILENAME)

    if os.path.exists(card_path):
        with open(card_path, "r", encoding="utf-8") as fh:
            try:
                raw = json.load(fh)
            except ValueError as exc:
                raise CardError("{0} is not valid JSON: {1}".format(card_path, exc))
        card = Card.from_json(raw)
        _warn_on_archetype_drift(card, archetype_path)
        return card

    if os.path.exists(archetype_path):
        with open(archetype_path, "r", encoding="utf-8") as fh:
            try:
                archetype = json.load(fh)
            except ValueError as exc:
                raise CardError("{0} is not valid JSON: {1}".format(archetype_path, exc))
        return derive_card(archetype)

    raise CardError(
        "no {0} or {1} found in {2} -- run 'epsilon init <dataset_id>' first".format(
            CARD_FILENAME, ARCHETYPE_FILENAME, base
        )
    )


def _warn_on_archetype_drift(card: Card, archetype_path: str) -> None:
    """Attach a caveat when the card and the archetype disagree on fields.

    A card is pinned to a schema hash, but a researcher can hold a card from
    one version and an archetype from another. Rather than failing -- the card
    is still mostly useful -- record the drift where every consumer will see it.
    """
    if not os.path.exists(archetype_path):
        return
    try:
        with open(archetype_path, "r", encoding="utf-8") as fh:
            archetype = json.load(fh)
    except (ValueError, OSError):
        return
    archetype_paths = set(p for p, _ in _walk_schema(archetype))
    if not archetype_paths:
        return
    card_paths = set(card.leaves)
    missing = sorted(archetype_paths - card_paths)
    extra = sorted(card_paths - archetype_paths)
    if missing:
        card.caveats.append(
            "Card is out of date: the archetype grants {0} that the card does "
            "not describe ({1}).".format(
                "fields" if len(missing) > 1 else "a field", ", ".join(missing)
            )
        )
    if extra:
        card.caveats.append(
            "Card is out of date: it describes {0} the archetype no longer "
            "grants ({1}).".format(
                "fields" if len(extra) > 1 else "a field", ", ".join(extra)
            )
        )
