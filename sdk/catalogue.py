"""
The analysis catalogue: what can be asked of a dataset, decided in code.

Each entry declares requirements that are checked against a Dataset Profile by
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

from sdk.profile import Profile, Leaf

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
    evaluate: Callable[[Profile], Match]


# -- shared helpers --------------------------------------------------------

def _leaf_warnings(profile: Profile, paths: List[str]) -> List[str]:
    """Surface the caveats of every leaf an analysis would touch.

    This is how dataset-specific traps -- a de-identification age cap, shifted
    dates, a code system split across revisions -- reach the researcher at the
    moment they choose an analysis, rather than in a document they read once.
    """
    out = []
    for path in paths:
        leaf = profile.leaf(path)
        if not leaf:
            continue
        for caveat in leaf.caveats:
            out.append("{0}: {1}".format(path, caveat))
        if not leaf.is_detailed:
            allowed = ", ".join(leaf.releasable_as) or "aggregates only"
            out.append(
                "{0}: released as {1} -- raw values will not clear output "
                "review.".format(path, allowed))
    return out


def _grain_warning(profile: Profile) -> List[str]:
    """Rows may repeat the same entity, and nothing here can rule that out."""
    if profile.has_dedupe_key:
        return []
    return ["Results are per {0}, not per entity. Identifiers are stripped at "
            "projection, so if one entity contributes many rows this is "
            "weighted by row count -- state the denominator in your methods."
            .format(profile.grain.label)]


def _no_dedupe_blocker(profile: Profile, quantity: str) -> Optional[str]:
    """The single most common reason an analysis is not computable."""
    if profile.has_dedupe_key:
        return None
    return ("{0} is a per-entity quantity, and this archetype has no key that "
            "groups rows back to an entity -- identifiers are stripped at "
            "projection. Computing it anyway yields a figure weighted by row "
            "count.".format(quantity))


_UNLOCK_DEDUPE = ("Ask the data owner for a pseudonymised entity key -- a "
                  "stable salted hash carries no re-identification risk and "
                  "makes per-entity denominators computable.")


# What each named parameter has to be, so an override can be checked rather
# than trusted. Keys absent here are derived, not chosen.
PARAM_ROLES = {
    "outcome": "discrete",
    "by": "discrete",
    "rows": "discrete",
    "cols": "discrete",
    "value": "numeric",
    "group": "binary",
    "event": "binary",
    "time": "temporal",
    "duration": "duration",
}

_ROLE_TESTS = {
    "discrete": lambda leaf: leaf.is_discrete,
    "numeric": lambda leaf: leaf.is_numeric,
    "binary": lambda leaf: leaf.is_discrete and leaf.cardinality == 2,
    "temporal": lambda leaf: leaf.is_temporal,
    "duration": lambda leaf: leaf.is_duration,
}

_ROLE_NAMES = {
    "discrete": "a categorical or coded field",
    "numeric": "a numeric field",
    "binary": "a two-level categorical field",
    "temporal": "a date or timestamp field",
    "duration": "a duration field",
}


def _command(key: str, **params) -> str:
    """The exact command that reproduces a match, in the CLI's own syntax."""
    parts = ["epsilon snippet", key]
    for name in sorted(params):
        parts.append("--set {0}={1}".format(name, params[name]))
    return " ".join(parts)


class OverrideError(Exception):
    """An explicitly chosen field cannot fill the role it was given."""


def override(profile: Profile, match: Match, choices: Dict[str, str]) -> Match:
    """Re-parameterise a match with fields the researcher chose.

    Overrides are validated, not trusted: a chosen field still has to be the
    right kind of thing, and choosing a 1,472-level code column as a stratum
    still produces an unreleasable table. Nothing here can turn a blocked
    analysis into a permitted one.
    """
    if not match.feasible:
        raise OverrideError(
            "'{0}' is not available for this dataset, so its fields cannot be "
            "chosen.".format(match.key))

    params = dict(match.params)
    for name, path in choices.items():
        if name not in params:
            raise OverrideError(
                "'{0}' takes no parameter '{1}'. It takes: {2}.".format(
                    match.key, name, ", ".join(sorted(params)) or "none"))
        leaf = profile.leaf(path)
        if leaf is None:
            raise OverrideError(
                "'{0}' is not a field in this dataset. Available: {1}.".format(
                    path, ", ".join(sorted(profile.leaves))))
        role = PARAM_ROLES.get(name)
        if role and not _ROLE_TESTS[role](leaf):
            raise OverrideError(
                "{0} must be {1}; {2} is {3}.".format(
                    name, _ROLE_NAMES[role], path, leaf.type))
        params[name] = path

    warnings = list(match.warnings) + _leaf_warnings(profile, sorted(set(params.values())))
    blockers = []

    # A stratum with too many levels is unreleasable however it was chosen.
    for name in ("rows", "cols", "by", "outcome"):
        path = params.get(name)
        leaf = profile.leaf(path) if path else None
        if leaf and leaf.cardinality and leaf.cardinality > MAX_STRATA:
            blockers.append(
                "{0} has {1:,} distinct values. A table over that many levels "
                "cannot clear a suppression threshold of {2}.".format(
                    path, leaf.cardinality, profile.min_cell))

    if match.key in ("cross_tab", "composition") and profile.grain.rows:
        cells = 1
        for name in ("rows", "cols", "by", "outcome"):
            leaf = profile.leaf(params[name]) if params.get(name) else None
            if leaf and leaf.cardinality:
                cells *= leaf.cardinality
        if cells > 1:
            expected = profile.grain.rows / float(cells)
            if expected < 5:
                blockers.append(
                    "Those fields give {0:,} cells over {1:,} rows -- about "
                    "{2:.1f} expected per cell, below the 5 a chi-square test "
                    "needs.".format(cells, profile.grain.rows, expected))

    seen, deduped = set(), []
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            deduped.append(warning)

    return Match(
        key=match.key, title=match.title,
        status=BLOCKED if blockers else FEASIBLE,
        unit=match.unit, summary=match.summary, params=params,
        blockers=blockers, warnings=deduped, unlock=match.unlock,
        command=_command(match.key, **dict(
            (k, v) for k, v in params.items() if k in PARAM_ROLES)),
    )


def _pick(leaves: List[Leaf], exclude: Optional[List[str]] = None) -> Optional[Leaf]:
    exclude = exclude or []
    for leaf in leaves:
        if leaf.path not in exclude:
            return leaf
    return None


def _describe_missing(profile: Profile, want: str) -> str:
    """Explain a missing requirement -- and do not blame the archetype for it.

    When no profile is published the field types are unknown, so nothing matches
    a typed requirement. Reporting that as "this archetype grants no
    categorical field" sends the researcher to argue with their data owner
    about the wrong thing.
    """
    return "This archetype grants no {0}. Fields available: {1}.".format(
        want, ", ".join(sorted(profile.leaves)) or "none")


# -- entries ---------------------------------------------------------------

def _eval_describe(profile: Profile) -> Match:
    paths = sorted(profile.leaves)
    return Match(
        key="describe",
        title="Cohort description",
        status=FEASIBLE if paths else BLOCKED,
        unit=profile.grain.label,
        summary="Counts, ranges and distributions for every granted field, "
                "reported per {0}.".format(profile.grain.label),
        params={"fields": ", ".join(paths)},
        blockers=[] if paths else ["This archetype grants no fields."],
        warnings=_leaf_warnings(profile, paths) + _grain_warning(profile),
        command="epsilon snippet describe",
    )


def _eval_prevalence(profile: Profile) -> Match:
    outcome = _pick(profile.discrete_leaves(max_cardinality=MAX_STRATA))
    blockers, unlock = [], None
    if outcome is None:
        blockers.append(_describe_missing(profile, "categorical or coded field to use as an outcome"))
    dedupe = _no_dedupe_blocker(profile, "Prevalence")
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
        warnings=_leaf_warnings(profile, [outcome.path] if outcome else []),
        unlock=unlock,
        command=None if blockers else "epsilon snippet prevalence",
    )


def _eval_composition(profile: Profile) -> Match:
    """The record-level question that survives when prevalence does not."""
    outcome = _pick(profile.discrete_leaves(max_cardinality=MAX_STRATA))
    stratum = _pick(profile.discrete_leaves(max_cardinality=MAX_STRATA),
                    exclude=[outcome.path] if outcome else [])
    blockers = []
    if outcome is None or stratum is None:
        blockers.append(_describe_missing(profile, "two categorical or coded fields"))
    used = [l.path for l in (outcome, stratum) if l]
    warnings = _leaf_warnings(profile, used)
    if not profile.has_dedupe_key:
        warnings.insert(0, (
            "This answers a narrower question than prevalence: it describes "
            "{0}s, not entities. State that denominator in your methods."
        ).format(profile.grain.label))
    return Match(
        key="composition",
        title="Composition by stratum",
        status=BLOCKED if blockers else FEASIBLE,
        unit=profile.grain.label,
        summary="Share of {0}s with a characteristic, broken down by a "
                "second field.".format(profile.grain.label),
        params={"outcome": outcome.path, "by": stratum.path} if not blockers else {},
        blockers=blockers,
        warnings=warnings + _grain_warning(profile),
        command=None if blockers else _command("composition", outcome=outcome.path, by=stratum.path),
    )


def _eval_cross_tab(profile: Profile) -> Match:
    candidates = profile.discrete_leaves(max_cardinality=MAX_STRATA)
    a = _pick(candidates)
    b = _pick(candidates, exclude=[a.path] if a else [])
    blockers = []
    if a is None or b is None:
        blockers.append(_describe_missing(
            profile, "two categorical fields with at most {0} levels".format(MAX_STRATA)))
    cells = None
    if a and b and a.cardinality and b.cardinality:
        cells = a.cardinality * b.cardinality
    warnings = _leaf_warnings(profile, [l.path for l in (a, b) if l]) + _grain_warning(profile)
    if cells and profile.grain.rows:
        expected = profile.grain.rows / float(cells)
        if expected < 5:
            blockers.append(
                "The table would have {0:,} cells over {1:,} rows -- about "
                "{2:.1f} expected per cell, below the 5 a chi-square test "
                "needs and below the suppression threshold of {3}.".format(
                    cells, profile.grain.rows, expected, profile.min_cell))
        elif expected < profile.min_cell * 2:
            warnings.append(
                "About {0:.0f} expected per cell. Sparse cells will be "
                "suppressed at n < {1}.".format(expected, profile.min_cell))
    return Match(
        key="cross_tab",
        title="Cross-tabulation with chi-square",
        status=BLOCKED if blockers else FEASIBLE,
        unit=profile.grain.label,
        summary="Association between two categorical fields.",
        params={"rows": a.path, "cols": b.path} if not blockers else {},
        blockers=blockers,
        warnings=warnings,
        command=None if blockers else _command("cross_tab", rows=a.path, cols=b.path),
    )


def _eval_group_compare(profile: Profile) -> Match:
    value = _pick(profile.numeric_leaves(detailed_only=True))
    group = _pick(profile.binary_leaves())
    blockers = []
    if value is None:
        blockers.append(_describe_missing(profile, "numeric field at DETAILED access"))
    if group is None:
        blockers.append(_describe_missing(profile, "two-level categorical field to compare across"))
    warnings = _leaf_warnings(profile, [l.path for l in (value, group) if l])
    if not profile.has_dedupe_key:
        blockers.append(
            "A two-sample test assumes one observation per entity. With no key "
            "to group rows, that cannot be established -- an entity "
            "contributing many rows would be counted many times.")
    return Match(
        key="group_compare",
        title="Two-group comparison",
        status=BLOCKED if blockers else FEASIBLE,
        unit="entity" if profile.has_dedupe_key else profile.grain.label,
        summary="Whether a numeric field differs between two groups.",
        params={"value": value.path, "group": group.path} if not blockers else {},
        blockers=blockers,
        warnings=warnings,
        unlock=_UNLOCK_DEDUPE if not profile.has_dedupe_key else None,
        command=None if blockers else _command("group_compare", value=value.path, group=group.path),
    )


def _eval_logistic(profile: Profile) -> Match:
    outcome = _pick(profile.binary_leaves())
    covariates = [l for l in profile.all_leaves()
                  if l.is_detailed and l is not outcome
                  and (l.is_numeric or (l.is_discrete and (l.cardinality or 99) <= MAX_STRATA))]
    if outcome:
        covariates = [l for l in covariates if l.path != outcome.path]
    blockers = []
    if outcome is None:
        blockers.append(_describe_missing(profile, "binary outcome field"))
    if not covariates:
        blockers.append(_describe_missing(profile, "covariate at DETAILED access"))
    if not profile.has_dedupe_key:
        blockers.append(
            "A logistic model assumes independent observations. With no key to "
            "group rows, independence cannot be established, and repeated rows "
            "for one entity would make the standard errors far too small.")
    warnings = _leaf_warnings(profile, [l.path for l in ([outcome] if outcome else []) + covariates])
    if profile.grain.rows and covariates:
        capacity = profile.grain.rows / float(MIN_EVENTS_PER_VARIABLE)
        if len(covariates) > capacity:
            warnings.append(
                "At {0} events per variable you have room for about {1:.0f} "
                "covariates.".format(MIN_EVENTS_PER_VARIABLE, capacity))
    warnings.append("Check events-per-variable on your own cohort: the profile "
                    "reports row counts, not outcome counts.")
    return Match(
        key="logistic",
        title="Logistic regression",
        status=BLOCKED if blockers else FEASIBLE,
        unit="entity" if profile.has_dedupe_key else profile.grain.label,
        summary="Association between covariates and a binary outcome.",
        params={"outcome": outcome.path,
                "covariates": ", ".join(l.path for l in covariates)} if not blockers else {},
        blockers=blockers,
        warnings=warnings,
        unlock=_UNLOCK_DEDUPE if not profile.has_dedupe_key else None,
        command=None if blockers else _command("logistic", outcome=outcome.path),
    )


def _eval_survival(profile: Profile) -> Match:
    """Always refused, and the reason is structural rather than incidental.

    A time to event needs an origin and an event. An archetype expresses
    neither: it grants columns, not the knowledge of which date starts a clock
    and which stops it. A single timestamp is not a duration, and a numeric
    field measured in years is an age, not a follow-up. Guessing either would
    produce exactly the confidently wrong answer this catalogue exists to
    prevent, so this stays blocked until an archetype can carry a declared
    duration.
    """
    temporal = profile.temporal_leaves()
    blockers = [
        "Survival analysis needs a time from an origin to an event. This "
        "archetype grants {0}, and nothing declares which date starts a clock "
        "and which stops it.".format(
            "no dates" if not temporal else
            "{0} date field(s)".format(len(temporal)))]
    dedupe = _no_dedupe_blocker(profile, "A survival curve")
    if dedupe:
        blockers.append(dedupe)
    return Match(
        key="survival",
        title="Survival analysis",
        status=BLOCKED,
        unit="entity",
        summary="Time from an origin to an event, with censoring.",
        params={},
        blockers=blockers,
        warnings=[],
        unlock=("Ask the data owner for a follow-up or discharge date "
                "alongside an origin date, and for a key that groups rows to "
                "an entity."),
        command=None,
    )


def _eval_trend(profile: Profile) -> Match:
    temporal = _pick(profile.temporal_leaves())
    blockers = []
    if temporal is None:
        blockers.append(
            "This archetype grants no date or timestamp field, so it describes "
            "a cross-section. No trend over time is computable.")
    warnings = _leaf_warnings(profile, [temporal.path] if temporal else [])
    if temporal is not None and not temporal.is_detailed and not temporal.releasable_as:
        blockers.append(
            "{0} is {1} and the profile names no releasable buckets, so no "
            "time axis can be released.".format(temporal.path, temporal.access_level))
    if temporal is not None:
        # Whether dates are shifted per entity cannot be measured from the
        # data -- shifted dates look like ordinary dates. Warn rather than
        # block, because guessing either way would be wrong.
        warnings.append(
            "{0}: de-identified extracts frequently shift dates by a "
            "per-entity offset, which looks identical to real dates. Confirm "
            "with the data owner before reading a calendar trend."
            .format(temporal.path))
    return Match(
        key="trend",
        title="Trend over time",
        status=BLOCKED if blockers else FEASIBLE,
        unit=profile.grain.label,
        summary="A quantity aggregated into time buckets and compared across them.",
        params={"time": temporal.path,
                "buckets": ", ".join(temporal.releasable_as) or "raw"} if not blockers else {},
        blockers=blockers,
        warnings=warnings + _grain_warning(profile),
        command=None if blockers else _command("trend", time=temporal.path),
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


def evaluate(profile: Profile, keys: Optional[List[str]] = None) -> List[Match]:
    """Evaluate the catalogue against a profile, feasible entries first."""
    specs = CATALOGUE if keys is None else [SPECS_BY_KEY[k] for k in keys if k in SPECS_BY_KEY]
    matches = [spec.evaluate(profile) for spec in specs]
    order = dict((spec.key, i) for i, spec in enumerate(CATALOGUE))
    matches.sort(key=lambda m: (0 if m.feasible else 1, order.get(m.key, 99)))
    return matches


def feasible(profile: Profile) -> List[Match]:
    return [m for m in evaluate(profile) if m.feasible]


def blocked(profile: Profile) -> List[Match]:
    return [m for m in evaluate(profile) if not m.feasible]
