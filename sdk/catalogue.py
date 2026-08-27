"""
The analysis catalogue: what can be asked of a dataset, decided in code.

Each entry declares requirements that are checked against a Dataset Card by
ordinary Python. A model may rank these results or phrase them, but it never
decides them -- so the verdicts are reproducible, testable, and identical
whichever model (or none) is configured.

The important verdicts are the refusals. An analysis that is statistically
wrong for a dataset still runs, still passes the submission gate, and still
comes back attested; the only place to catch it is before it is written.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from sdk.card import Card, Leaf

FEASIBLE = "FEASIBLE"
BLOCKED = "BLOCKED"

# A contingency table needs enough expected count per cell to be meaningful;
# beyond this many levels the table is too sparse to release under any
# reasonable suppression threshold.
MAX_STRATA = 20

# Rule of thumb for logistic regression: ten outcome events per covariate.
MIN_EVENTS_PER_VARIABLE = 10


@dataclass
class Match:
    key: str
    title: str
    status: str
    unit: str
    summary: str
    params: Dict[str, str] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unlock: Optional[str] = None
    command: Optional[str] = None

    @property
    def feasible(self) -> bool:
        return self.status == FEASIBLE


@dataclass
class AnalysisSpec:
    key: str
    title: str
    question: str
    evaluate: Callable[[Card], Match]


# -- shared helpers --------------------------------------------------------

def _leaf_warnings(card: Card, paths: List[str]) -> List[str]:
    """Surface the caveats of every leaf an analysis would touch.

    This is how dataset-specific traps -- a de-identification age cap, shifted
    dates, a code system split across revisions -- reach the researcher at the
    moment they choose an analysis, rather than in a document they read once.
    """
    out = []
    for path in paths:
        leaf = card.leaf(path)
        if not leaf:
            continue
        for caveat in leaf.caveats:
            out.append("{0}: {1}".format(path, caveat))
        if leaf.code_system is not None and leaf.code_system.mixed:
            out.append(
                "{0}: values span {1}. Match concepts across every system or "
                "you will undercount.".format(path, leaf.code_system.describe())
            )
        if not leaf.is_detailed:
            allowed = ", ".join(leaf.releasable_as) or "aggregates only"
            out.append(
                "{0}: access is {1} -- releasable as {2}.".format(
                    path, leaf.access_level, allowed)
            )
    return out


def _grain_warning(card: Card) -> List[str]:
    ratio = card.grain.rows_per_entity
    if ratio and ratio >= 1.5:
        return ["Rows are not independent: about {0:,.0f} rows per entity, "
                "unevenly distributed. Every row-level statistic is weighted "
                "by row count.".format(ratio)]
    return []


def _no_dedupe_blocker(card: Card, quantity: str) -> Optional[str]:
    """The single most common reason an analysis is not computable."""
    if card.has_dedupe_key:
        return None
    if not card.grain.known:
        return ("The grain of this dataset is unknown -- no card is published "
                "-- so {0} cannot be shown to be correctly weighted.".format(quantity))
    return ("{0} is a per-entity quantity, and this archetype has no key that "
            "groups rows back to an entity (identifiers are stripped at "
            "projection). Computing it anyway yields a figure weighted by row "
            "count.".format(quantity))


_UNLOCK_DEDUPE = ("Ask the data owner for a pseudonymised entity key -- a "
                  "stable salted hash carries no re-identification risk and "
                  "makes per-entity denominators computable.")


def _pick(leaves: List[Leaf], exclude: Optional[List[str]] = None) -> Optional[Leaf]:
    exclude = exclude or []
    for leaf in leaves:
        if leaf.path not in exclude:
            return leaf
    return None


def _describe_missing(card: Card, want: str) -> str:
    return "This archetype grants no {0}. Fields available: {1}.".format(
        want, ", ".join(sorted(card.leaves)) or "none")


# -- entries ---------------------------------------------------------------

def _eval_describe(card: Card) -> Match:
    paths = sorted(card.leaves)
    return Match(
        key="describe",
        title="Cohort description",
        status=FEASIBLE if paths else BLOCKED,
        unit=card.grain.unit,
        summary="Counts, ranges and distributions for every granted field, "
                "reported per {0}.".format(card.grain.unit),
        params={"fields": ", ".join(paths)},
        blockers=[] if paths else ["This archetype grants no fields."],
        warnings=_leaf_warnings(card, paths) + _grain_warning(card),
        command="epsilon snippet describe",
    )


def _eval_prevalence(card: Card) -> Match:
    outcome = _pick(card.discrete_leaves(max_cardinality=MAX_STRATA))
    blockers, unlock = [], None
    if outcome is None:
        blockers.append(_describe_missing(card, "categorical or coded field to use as an outcome"))
    dedupe = _no_dedupe_blocker(card, "Prevalence")
    if dedupe:
        blockers.append(dedupe)
        unlock = _UNLOCK_DEDUPE
    return Match(
        key="prevalence",
        title="Prevalence",
        status=BLOCKED if blockers else FEASIBLE,
        unit="entity",
        summary="Share of entities with a given characteristic.",
        params={"outcome": outcome.path} if outcome else {},
        blockers=blockers,
        warnings=_leaf_warnings(card, [outcome.path] if outcome else []),
        unlock=unlock,
        command=None if blockers else "epsilon snippet prevalence",
    )


def _eval_composition(card: Card) -> Match:
    """The record-level question that survives when prevalence does not."""
    outcome = _pick(card.discrete_leaves(max_cardinality=MAX_STRATA))
    stratum = _pick(card.discrete_leaves(max_cardinality=MAX_STRATA),
                    exclude=[outcome.path] if outcome else [])
    blockers = []
    if outcome is None or stratum is None:
        blockers.append(_describe_missing(card, "two categorical or coded fields"))
    used = [l.path for l in (outcome, stratum) if l]
    warnings = _leaf_warnings(card, used)
    if not card.has_dedupe_key and card.grain.known:
        warnings.insert(0, (
            "This answers a narrower question than prevalence: it describes "
            "{0}s, not entities. State that denominator in your methods."
        ).format(card.grain.unit))
    return Match(
        key="composition",
        title="Composition by stratum",
        status=BLOCKED if blockers else FEASIBLE,
        unit=card.grain.unit,
        summary="Share of {0}s with a characteristic, broken down by a "
                "second field.".format(card.grain.unit),
        params={"outcome": outcome.path, "by": stratum.path} if not blockers else {},
        blockers=blockers,
        warnings=warnings + _grain_warning(card),
        command=None if blockers else "epsilon snippet composition --outcome {0} --by {1}".format(
            outcome.path, stratum.path),
    )


def _eval_cross_tab(card: Card) -> Match:
    candidates = card.discrete_leaves(max_cardinality=MAX_STRATA)
    a = _pick(candidates)
    b = _pick(candidates, exclude=[a.path] if a else [])
    blockers = []
    if a is None or b is None:
        blockers.append(_describe_missing(
            card, "two categorical fields with at most {0} levels".format(MAX_STRATA)))
    cells = None
    if a and b and a.cardinality and b.cardinality:
        cells = a.cardinality * b.cardinality
    warnings = _leaf_warnings(card, [l.path for l in (a, b) if l]) + _grain_warning(card)
    if cells and card.grain.rows:
        expected = card.grain.rows / float(cells)
        if expected < 5:
            blockers.append(
                "The table would have {0:,} cells over {1:,} rows -- about "
                "{2:.1f} expected per cell, below the 5 a chi-square test "
                "needs and below the suppression threshold of {3}.".format(
                    cells, card.grain.rows, expected, card.policy.min_cell))
        elif expected < card.policy.min_cell * 2:
            warnings.append(
                "About {0:.0f} expected per cell. Sparse cells will be "
                "suppressed at n < {1}.".format(expected, card.policy.min_cell))
    return Match(
        key="cross_tab",
        title="Cross-tabulation with chi-square",
        status=BLOCKED if blockers else FEASIBLE,
        unit=card.grain.unit,
        summary="Association between two categorical fields.",
        params={"rows": a.path, "cols": b.path} if not blockers else {},
        blockers=blockers,
        warnings=warnings,
        command=None if blockers else "epsilon snippet cross-tab --rows {0} --cols {1}".format(
            a.path, b.path),
    )


def _eval_group_compare(card: Card) -> Match:
    value = _pick(card.numeric_leaves(detailed_only=True))
    group = _pick(card.binary_leaves())
    blockers = []
    if value is None:
        blockers.append(_describe_missing(card, "numeric field at DETAILED access"))
    if group is None:
        blockers.append(_describe_missing(card, "two-level categorical field to compare across"))
    warnings = _leaf_warnings(card, [l.path for l in (value, group) if l])
    if not card.has_dedupe_key and card.grain.rows_per_entity:
        blockers.append(
            "Rows are repeated measures of the same entities ({0:,.0f} per "
            "entity) and there is no key to collapse them, so the "
            "independence assumption of a two-sample test does not hold."
            .format(card.grain.rows_per_entity))
    return Match(
        key="group_compare",
        title="Two-group comparison",
        status=BLOCKED if blockers else FEASIBLE,
        unit="entity" if card.has_dedupe_key else card.grain.unit,
        summary="Whether a numeric field differs between two groups.",
        params={"value": value.path, "group": group.path} if not blockers else {},
        blockers=blockers,
        warnings=warnings,
        unlock=_UNLOCK_DEDUPE if not card.has_dedupe_key else None,
        command=None if blockers else "epsilon snippet group-compare --value {0} --group {1}".format(
            value.path, group.path),
    )


def _eval_logistic(card: Card) -> Match:
    outcome = _pick(card.binary_leaves())
    covariates = [l for l in card.all_leaves()
                  if l.is_detailed and l is not outcome
                  and (l.is_numeric or (l.is_discrete and (l.cardinality or 99) <= MAX_STRATA))]
    if outcome:
        covariates = [l for l in covariates if l.path != outcome.path]
    blockers = []
    if outcome is None:
        blockers.append(_describe_missing(card, "binary outcome field"))
    if not covariates:
        blockers.append(_describe_missing(card, "covariate at DETAILED access"))
    if not card.has_dedupe_key and card.grain.rows_per_entity:
        blockers.append(
            "Observations are not independent: about {0:,.0f} rows per entity "
            "with no key to collapse them. A logistic model over these rows "
            "would report standard errors that are far too small."
            .format(card.grain.rows_per_entity))
    warnings = _leaf_warnings(card, [l.path for l in ([outcome] if outcome else []) + covariates])
    if card.grain.rows and covariates:
        capacity = card.grain.rows / float(MIN_EVENTS_PER_VARIABLE)
        if len(covariates) > capacity:
            warnings.append(
                "At {0} events per variable you have room for about {1:.0f} "
                "covariates.".format(MIN_EVENTS_PER_VARIABLE, capacity))
    warnings.append("Check events-per-variable on your own cohort: the card "
                    "reports row counts, not outcome counts.")
    return Match(
        key="logistic",
        title="Logistic regression",
        status=BLOCKED if blockers else FEASIBLE,
        unit="entity" if card.has_dedupe_key else card.grain.unit,
        summary="Association between covariates and a binary outcome.",
        params={"outcome": outcome.path,
                "covariates": ", ".join(l.path for l in covariates)} if not blockers else {},
        blockers=blockers,
        warnings=warnings,
        unlock=_UNLOCK_DEDUPE if not card.has_dedupe_key else None,
        command=None if blockers else "epsilon snippet logistic --outcome {0}".format(outcome.path),
    )


def _eval_survival(card: Card) -> Match:
    event = _pick(card.binary_leaves())
    # A duration must be declared as one. A numeric field whose unit happens to
    # be "years" -- an age, most often -- is not a time to event, and treating
    # it as one is precisely the error this catalogue exists to prevent.
    duration = _pick(card.duration_leaves())
    temporal = card.temporal_leaves()
    blockers = []
    if duration is None and len(temporal) < 2:
        blockers.append(
            "Survival analysis needs a time from an origin to an event. This "
            "archetype grants {0}, and a single timestamp is not a duration."
            .format("no duration and no pair of dates to difference"
                    if not temporal else
                    "only one date ({0})".format(temporal[0].path)))
    if event is None:
        blockers.append(_describe_missing(card, "binary event indicator"))
    dedupe = _no_dedupe_blocker(card, "A survival curve")
    if dedupe:
        blockers.append(dedupe)
    return Match(
        key="survival",
        title="Survival analysis",
        status=BLOCKED if blockers else FEASIBLE,
        unit="entity",
        summary="Time from an origin to an event, with censoring.",
        params=({"duration": duration.path, "event": event.path}
                if duration and event and not blockers else {}),
        blockers=blockers,
        warnings=[],
        unlock=("Ask the data owner for a discharge, death or follow-up date "
                "alongside the existing timestamp -- two dates make a duration."),
        command=None,
    )


def _eval_trend(card: Card) -> Match:
    temporal = _pick(card.temporal_leaves())
    blockers = []
    if temporal is None:
        blockers.append(
            "This archetype grants no date or timestamp field, so it describes "
            "a cross-section. No trend over time is computable.")
    warnings = _leaf_warnings(card, [temporal.path] if temporal else [])
    if temporal is not None and not temporal.is_detailed and not temporal.releasable_as:
        blockers.append(
            "{0} is {1} and the card names no releasable buckets, so no "
            "time axis can be released.".format(temporal.path, temporal.access_level))
    if temporal is not None and temporal.comparable_across_entities is False:
        blockers.append(
            "{0} is not comparable between entities -- the card records that "
            "values are shifted per entity. Pooling them onto one calendar "
            "axis produces a trend that describes the shifting, not the data."
            .format(temporal.path))
    return Match(
        key="trend",
        title="Trend over time",
        status=BLOCKED if blockers else FEASIBLE,
        unit=card.grain.unit,
        summary="A quantity aggregated into time buckets and compared across them.",
        params={"time": temporal.path,
                "buckets": ", ".join(temporal.releasable_as) or "raw"} if not blockers else {},
        blockers=blockers,
        warnings=warnings + _grain_warning(card),
        command=None if blockers else "epsilon snippet trend --time {0}".format(temporal.path),
    )


CATALOGUE: List[AnalysisSpec] = [
    AnalysisSpec("describe", "Cohort description",
                 "What is in this dataset?", _eval_describe),
    AnalysisSpec("prevalence", "Prevalence",
                 "What share of entities have X?", _eval_prevalence),
    AnalysisSpec("composition", "Composition by stratum",
                 "What share of records are X, by Y?", _eval_composition),
    AnalysisSpec("cross_tab", "Cross-tabulation with chi-square",
                 "Is X associated with Y?", _eval_cross_tab),
    AnalysisSpec("group_compare", "Two-group comparison",
                 "Does X differ between two groups?", _eval_group_compare),
    AnalysisSpec("logistic", "Logistic regression",
                 "What predicts X, adjusting for Y?", _eval_logistic),
    AnalysisSpec("survival", "Survival analysis",
                 "How long until X happens?", _eval_survival),
    AnalysisSpec("trend", "Trend over time",
                 "Is X changing over time?", _eval_trend),
]

SPECS_BY_KEY = dict((spec.key, spec) for spec in CATALOGUE)


def evaluate(card: Card, keys: Optional[List[str]] = None) -> List[Match]:
    """Evaluate the catalogue against a card, feasible entries first."""
    specs = CATALOGUE if keys is None else [SPECS_BY_KEY[k] for k in keys if k in SPECS_BY_KEY]
    matches = [spec.evaluate(card) for spec in specs]
    order = dict((spec.key, i) for i, spec in enumerate(CATALOGUE))
    matches.sort(key=lambda m: (0 if m.feasible else 1, order.get(m.key, 99)))
    return matches


def feasible(card: Card) -> List[Match]:
    return [m for m in evaluate(card) if m.feasible]


def blocked(card: Card) -> List[Match]:
    return [m for m in evaluate(card) if not m.feasible]
