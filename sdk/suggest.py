"""
Answer "what can I do with this dataset?" and "can I ask X?".

The division of labour is the point. The catalogue (sdk.catalogue) decides
feasibility from card facts in ordinary Python. A model, when one is
configured, only maps a natural-language question onto a catalogue entry and
phrases the result. It cannot overturn a verdict, and with no model configured
the deterministic listing is still produced -- which is why `epsilon suggest`
works on a machine that has never seen an API key.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sdk.card import Card
from sdk.catalogue import CATALOGUE, Match, SPECS_BY_KEY, evaluate
from sdk.explain import render_summary

# The model picks from a fixed set of keys and writes prose. It returns no
# verdict, no field names and no numbers -- everything checkable comes from
# the matcher.
QUESTION_SCHEMA = {
    "type": "object",
    "required": ["primary", "restated", "explanation"],
    "properties": {
        "primary": {
            "type": "string",
            "enum": [spec.key for spec in CATALOGUE],
        },
        "alternatives": {
            "type": "array",
            "items": {"type": "string", "enum": [spec.key for spec in CATALOGUE]},
        },
        "restated": {
            "type": "string",
        },
        "explanation": {
            "type": "string",
        },
    },
}

SYSTEM = (
    "You map a researcher's question onto one entry in a fixed catalogue of "
    "analyses available in a trusted research environment.\n\n"
    "You do NOT decide whether an analysis is possible. A deterministic "
    "matcher has already done that and its verdict is authoritative; you are "
    "given it as context so your explanation is consistent with it.\n\n"
    "Pick the catalogue entry that most directly answers the question, even "
    "when that entry is blocked -- naming the blocked entry and explaining why "
    "it is blocked is more useful than redirecting to something feasible but "
    "unrelated. List genuinely related entries as alternatives.\n\n"
    "Restate the question as it would be phrased against this dataset. Keep "
    "the explanation to two or three sentences, concrete, and free of hedging."
)


def _catalogue_context(card: Card, matches: List[Match]) -> str:
    lines = ["Dataset: " + render_summary(card), ""]
    if card.grain.known:
        lines.append("Grain: " + (card.grain.statement or card.grain.unit))
        lines.append("Entity key available: " + ("yes" if card.has_dedupe_key else "no"))
    lines.append("Fields: " + ", ".join(sorted(card.leaves)))
    lines.append("")
    lines.append("Catalogue verdicts (authoritative):")
    for match in matches:
        lines.append("- {0} [{1}]: {2}".format(match.key, match.status, match.summary))
        for blocker in match.blockers:
            lines.append("    blocked because: " + blocker)
    return "\n".join(lines)


def interpret(card: Card, question: str, provider=None) -> Dict[str, object]:
    """Map a question onto the catalogue. Returns {} when no model is available."""
    if provider is None:
        return {}
    matches = evaluate(card)
    prompt = "{0}\n\nResearcher's question: {1}".format(
        _catalogue_context(card, matches), question)
    from sdk.llm import structured
    return structured(provider, SYSTEM, prompt, QUESTION_SCHEMA,
                      tool_name="map_question",
                      description="Map the question onto a catalogue entry.")


# Every caveat is shown when a researcher asks for one analysis; a full
# catalogue listing shows a few and says how many were held back, so the
# important ones are not lost in a wall of text.
MAX_NOTES = 4


def _render_match(match: Match, indent: str = "  ",
                  max_notes: Optional[int] = None) -> List[str]:
    mark = "[OK]" if match.feasible else "[NO]"
    lines = ["{0}{1} {2}".format(indent, mark, match.title)]
    body = indent + "     "
    lines.extend(_bullet(match.summary, body, ""))
    # Parameters are the auto-chosen fields a snippet would use. They are only
    # meaningful for something you can actually run.
    if match.params and match.feasible:
        for key in sorted(match.params):
            lines.extend(_bullet(match.params[key], body, key + ": "))
    lines.append("{0}unit of analysis: {1}".format(body, match.unit))
    for blocker in match.blockers:
        lines.extend(_bullet(blocker, body, "why not: "))

    warnings = match.warnings
    held_back = 0
    if max_notes is not None and len(warnings) > max_notes:
        held_back = len(warnings) - max_notes
        warnings = warnings[:max_notes]
    for warning in warnings:
        lines.extend(_bullet(warning, body, "note: "))
    if held_back:
        lines.append("{0}... {1} more note{2} (see 'epsilon explain')".format(
            body, held_back, "" if held_back == 1 else "s"))

    if match.unlock:
        lines.extend(_bullet(match.unlock, body, "unlock: "))
    if match.command:
        lines.append(body + "-> " + match.command)
    return lines


def _bullet(text: str, indent: str, prefix: str, width: int = 76) -> List[str]:
    words = (prefix + text).split()
    lines, current = [], indent
    for word in words:
        candidate = current + word if current == indent else current + " " + word
        if len(candidate) > width and current != indent:
            lines.append(current)
            current = indent + "  " + word
        else:
            current = candidate
    if current.strip():
        lines.append(current)
    return lines


def render_catalogue(card: Card) -> str:
    """The full deterministic listing: what this dataset supports, and what not."""
    matches = evaluate(card)
    feasible = [m for m in matches if m.feasible]
    blocked = [m for m in matches if not m.feasible]

    out = ["", "  " + card.title, ""]
    out.append("  AVAILABLE ({0})".format(len(feasible)))
    out.append("")
    for match in feasible:
        out.extend(_render_match(match, max_notes=MAX_NOTES))
        out.append("")
    out.append("  NOT AVAILABLE ({0})".format(len(blocked)))
    out.append("")
    for match in blocked:
        out.extend(_render_match(match, max_notes=MAX_NOTES))
        out.append("")
    return "\n".join(out)


def render_answer(card: Card, question: str,
                  interpretation: Optional[Dict[str, object]] = None) -> str:
    """Answer one question, leading with the entry that actually addresses it."""
    matches = dict((m.key, m) for m in evaluate(card))
    interpretation = interpretation or {}

    primary_key = interpretation.get("primary")
    if primary_key not in matches:
        primary_key = _guess(card, question, matches)

    out = ["", '  Question: "{0}"'.format(question.strip()), ""]

    restated = interpretation.get("restated")
    if restated:
        out.append("  Against this dataset that reads as:")
        out.extend(_bullet(str(restated), "     ", ""))
        out.append("")

    primary = matches[primary_key]
    out.extend(_render_match(primary))
    out.append("")

    explanation = interpretation.get("explanation")
    if explanation:
        out.extend(_bullet(str(explanation), "     ", ""))
        out.append("")

    alternatives = [k for k in (interpretation.get("alternatives") or [])
                    if k in matches and k != primary_key]
    if not alternatives:
        alternatives = [m.key for m in evaluate(card)
                        if m.feasible and m.key != primary_key][:2]
    if alternatives:
        out.append("  RELATED")
        out.append("")
        for key in alternatives[:3]:
            out.extend(_render_match(matches[key], max_notes=2))
            out.append("")
    return "\n".join(out)


# Keyword fallback so `epsilon suggest "<question>"` still routes sensibly with
# no model configured. Deliberately crude: it only chooses which entry to show
# first, and every verdict shown is the matcher's.
_KEYWORDS = [
    ("survival", ("survival", "time to", "time-to", "kaplan", "hazard",
                  "readmission", "mortality over", "censor")),
    ("trend", ("trend", "over time", "by year", "seasonal", "monthly", "yearly")),
    ("prevalence", ("prevalence", "what share of patients", "proportion of patients",
                    "how many patients have", "rate of")),
    ("logistic", ("predict", "adjust", "adjusted", "odds", "regression",
                  "risk factor", "associated with", "controlling for")),
    ("group_compare", ("compare", "difference between", "differ", "higher in",
                       "lower in", "t-test", "mean of")),
    ("cross_tab", ("association", "chi-square", "chi square", "cross-tab",
                   "contingency", "related to")),
    ("composition", ("share", "proportion", "breakdown", "distribution of",
                     "by sex", "by gender", "by group")),
    ("describe", ("describe", "summary", "what is in", "overview", "table 1",
                  "characteristics")),
]


def _guess(card: Card, question: str, matches: Dict[str, Match]) -> str:
    lowered = question.lower()
    for key, triggers in _KEYWORDS:
        if key in matches and any(t in lowered for t in triggers):
            return key
    return "describe"
