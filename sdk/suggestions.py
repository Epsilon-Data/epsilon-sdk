"""
Concrete analyses worth running on a particular dataset.

The catalogue says which *kinds* of analysis a dataset supports. That is the
right answer to "is this computable" and the wrong answer to "what should I
look at" -- a researcher opening a diabetes cohort wants "compare BMI between
diabetic and non-diabetic records", not "cross_tab is available".

So a model proposes specific questions grounded in the measured fields, and
every proposal is checked against the catalogue before it can become a card.
The model chooses what is interesting; the predicates decide what is possible.
A suggestion naming fields that do not exist, or resting on an analysis the
matcher blocks, never reaches the researcher.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sdk import catalogue as catalogue_mod
from sdk.profile import Profile

# Enough to fill a card grid without turning the screen into a menu.
WANTED = 6

SCHEMA = {
    "type": "object",
    "required": ["suggestions"],
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "question", "analysis", "fields"],
                "properties": {
                    "title": {"type": "string"},
                    "question": {"type": "string"},
                    "why": {"type": "string"},
                    "analysis": {
                        "type": "string",
                        "enum": sorted(catalogue_mod.SPECS_BY_KEY),
                    },
                    "fields": {
                        "type": "object",
                        "description": "Parameter name to field path, e.g. "
                                       "{\"rows\": \"patient.gender\"}",
                    },
                },
            },
        }
    },
}

SYSTEM = (
    "You propose concrete analyses a researcher could run on a dataset you "
    "have been measured a description of.\n\n"
    "Every suggestion must name real field paths from the list given, and an "
    "analysis from the catalogue. Do not propose anything the verdicts mark "
    "blocked -- those are decided by code and will be discarded.\n\n"
    "Write the title as the finding a researcher would want, not the method: "
    "\"Diabetes rate by age band\", not \"cross-tabulation\". Keep the "
    "question one sentence, phrased as the researcher would ask it. Keep "
    "'why' to one clause about what it would show.\n\n"
    "Prefer variety over completeness: different fields, different shapes. "
    "Say nothing about the data you were not told."
)


@dataclass
class Suggestion:
    title: str
    question: str
    analysis: str
    fields: Dict[str, str] = field(default_factory=dict)
    why: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        return {
            "title": self.title, "question": self.question,
            "analysis": self.analysis, "fields": self.fields,
            "why": self.why, "warnings": self.warnings,
        }


def _context(profile: Profile) -> str:
    lines = ["Dataset: {0}".format(profile.title),
             "One row per {0}; {1} rows.".format(
                 profile.grain.label, format(profile.grain.rows or 0, ","))]
    if not profile.has_dedupe_key:
        lines.append("No key groups rows back to an entity.")
    lines.append("")
    lines.append("Fields, as measured:")
    for leaf in profile.all_leaves():
        bits = [leaf.path, leaf.type]
        if leaf.value_range:
            bits.append("{0}–{1}".format(*leaf.value_range))
        elif leaf.categories:
            bits.append("{" + ", ".join(str(c) for c in leaf.categories[:6]) + "}")
        elif leaf.cardinality:
            bits.append("{0} distinct".format(leaf.cardinality))
        if not leaf.is_detailed:
            bits.append("aggregate only")
        lines.append("  " + "  ".join(bits))

    lines.append("")
    lines.append("Catalogue verdicts:")
    for match in catalogue_mod.evaluate(profile):
        lines.append("  {0}: {1}".format(match.key, match.status))
    return "\n".join(lines)


def validate(profile: Profile, raw: Dict[str, Any]) -> Optional[Suggestion]:
    """Keep a proposal only if the catalogue agrees it can be run."""
    key = raw.get("analysis")
    spec = catalogue_mod.SPECS_BY_KEY.get(key)
    if spec is None:
        return None

    match = spec.evaluate(profile)
    if not match.feasible:
        return None

    chosen = {}
    for name, path in (raw.get("fields") or {}).items():
        if isinstance(path, str) and profile.leaf(path) is not None:
            chosen[name] = path
    if chosen:
        try:
            match = catalogue_mod.override(profile, match, chosen)
        except catalogue_mod.OverrideError:
            # The model picked fields this analysis cannot use. The idea may
            # still be sound, so fall back to the matcher's own choice.
            match = spec.evaluate(profile)
            chosen = dict(match.params)
        if not match.feasible:
            return None

    title = (raw.get("title") or "").strip()
    question = (raw.get("question") or "").strip()
    if not title or not question:
        return None

    return Suggestion(
        title=title, question=question, analysis=match.key,
        fields=chosen or dict(match.params), why=(raw.get("why") or "").strip(),
        warnings=list(match.warnings),
    )


def propose(profile: Profile, provider=None,
            wanted: int = WANTED) -> List[Suggestion]:
    """Suggest analyses for this dataset. Falls back to the catalogue alone."""
    if provider is None:
        return fallback(profile, wanted)

    from sdk.llm import structured
    prompt = "{0}\n\nPropose {1} analyses worth running.".format(
        _context(profile), wanted)
    try:
        answer = structured(provider, SYSTEM, prompt, SCHEMA,
                            tool_name="suggest_analyses",
                            description="Propose analyses for this dataset.")
    except Exception:
        return fallback(profile, wanted)

    out: List[Suggestion] = []
    seen = set()
    for raw in (answer.get("suggestions") or []):
        if not isinstance(raw, dict):
            continue
        suggestion = validate(profile, raw)
        if suggestion is None or suggestion.title.lower() in seen:
            continue
        seen.add(suggestion.title.lower())
        out.append(suggestion)
        if len(out) >= wanted:
            break
    return out or fallback(profile, wanted)


def fallback(profile: Profile, wanted: int = WANTED) -> List[Suggestion]:
    """What the catalogue alone can offer, with no model configured."""
    out = []
    for match in catalogue_mod.evaluate(profile):
        if not match.feasible:
            continue
        out.append(Suggestion(
            title=match.title, question=match.summary, analysis=match.key,
            fields=dict(match.params), why="", warnings=list(match.warnings)))
        if len(out) >= wanted:
            break
    return out
