"""
Render a Dataset Card, and what can be computed from it, as one briefing.

Pure formatting over sdk.card and sdk.catalogue -- no network, no model, no
API key. `epsilon explain` works on a freshly initialised project with nothing
configured, which is deliberate: onboarding must not depend on the copilot
being set up, and the verdicts shown here are the same ones the agent gets.
"""
from __future__ import annotations

from typing import List, Optional

from sdk.card import Card, HIGH_LEVEL, Leaf
from sdk.catalogue import Match, evaluate

# Below this many rows per entity the grain is worth stating but not warning
# about; above it, aggregate statistics are badly distorted by unequal weights.
AMPLIFICATION_WARN_RATIO = 1.5

# Widest the VALUES column may grow before category lists are elided.
DOMAIN_WIDTH = 34


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "--"
    return "{0:.0f}%".format(value * 100)


def _fmt_domain(leaf: Leaf) -> str:
    """A short description of the values a leaf takes."""
    if leaf.value_range and len(leaf.value_range) == 2:
        return "{0} {1}-{2}".format(leaf.type, leaf.value_range[0], leaf.value_range[1])
    if leaf.categories:
        prefix = "" if leaf.type == "categorical" else leaf.type + " "
        shown, budget = [], DOMAIN_WIDTH - len(prefix) - 2
        for category in leaf.categories:
            text = str(category)
            if sum(len(s) + 2 for s in shown) + len(text) > budget:
                shown.append("...")
                break
            shown.append(text)
        return "{0}{{{1}}}".format(prefix, ", ".join(shown))
    if leaf.cardinality is not None:
        return "{0}({1})".format(leaf.type, leaf.cardinality)
    return leaf.type


def _field_table(card: Card) -> List[str]:
    rows = []
    for leaf in card.all_leaves():
        rows.append((leaf.path, _fmt_domain(leaf), leaf.access_level, _fmt_pct(leaf.coverage)))
    if not rows:
        return ["  (this archetype grants no fields)"]

    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    w2 = max(len(r[2]) for r in rows)
    header = "  {0}  {1}  {2}  {3}".format(
        "FIELD".ljust(w0), "VALUES".ljust(w1), "ACCESS".ljust(w2), "COVERAGE")
    out = [header, "  " + "-" * (w0 + w1 + w2 + 14)]
    for path, domain, access, coverage in rows:
        out.append("  {0}  {1}  {2}  {3}".format(
            path.ljust(w0), domain.ljust(w1), access.ljust(w2), coverage.rjust(8)))
    return out


def _wrap(text: str, indent: str = "     ", width: int = 74) -> List[str]:
    words = text.split()
    lines, current = [], indent
    for word in words:
        candidate = current + word if current == indent else current + " " + word
        if len(candidate) > width and current != indent:
            lines.append(current)
            current = indent + word
        else:
            current = candidate
    if current.strip():
        lines.append(current)
    return lines


def _warnings(card: Card) -> List[str]:
    """Every reason the researcher might get a wrong-but-runnable answer."""
    out = []

    if not card.grain.known:
        out.append(("GRAIN UNKNOWN",
                    "No card is published for this dataset, so what one row "
                    "represents is unknown. Any statistic that assumes one row "
                    "per entity may be silently mis-weighted."))
    elif not card.has_dedupe_key:
        entity = _likely_entity(card)
        subject = "an entity" if not entity else "{0} {1}".format(_article(entity), entity)
        out.append(("NO DEDUPE KEY",
                    "Rows cannot be grouped back to {0} -- identifiers are "
                    "stripped at projection. Per-{1} quantities (prevalence, "
                    "mean per {1}, counts per {1}) are NOT computable from this "
                    "archetype, however the analysis is written.".format(
                        subject, entity or "entity")))

    ratio = card.grain.rows_per_entity
    if ratio and ratio >= AMPLIFICATION_WARN_RATIO:
        counts = ", ".join("{0:,} {1}".format(v, k)
                           for k, v in sorted(card.grain.entity_counts.items()))
        out.append(("GRAIN AMPLIFICATION",
                    "{0:,} rows describe {1}: about {2:,.0f} rows per entity, "
                    "and the count varies between entities. Row-level averages "
                    "are weighted by row count, not by entity.".format(
                        card.grain.rows or 0, counts, ratio)))

    for leaf in card.mixed_code_leaves():
        cs = leaf.code_system
        split = ""
        if cs.split:
            split = " (" + ", ".join(
                "{0} {1:.0f}%".format(cs.systems.get(k, k), v * 100)
                for k, v in sorted(cs.split.items())) + ")"
        discriminator = ""
        if cs.discriminator:
            discriminator = " Use {0} to tell them apart.".format(cs.discriminator)
        out.append(("TWO CODING SYSTEMS" if len(cs.systems) == 2 else "MIXED CODING SYSTEMS",
                    "{0} mixes {1}{2}. The same concept carries a different code "
                    "in each system, so counting raw values splits it.{3}".format(
                        leaf.path, cs.describe(), split, discriminator)))

    aggregate_only = card.aggregate_only_leaves()
    if aggregate_only:
        for leaf in aggregate_only:
            allowed = ", ".join(leaf.releasable_as) if leaf.releasable_as else "aggregates only"
            out.append(("AGGREGATE ONLY",
                        "{0} is {1} -- releasable as {2}. Raw values will not "
                        "clear output review.".format(leaf.path, HIGH_LEVEL, allowed)))

    for leaf in card.all_leaves():
        for caveat in leaf.caveats:
            out.append(("CAVEAT: " + leaf.path, caveat))

    for caveat in card.caveats:
        out.append(("CAVEAT", caveat))

    return out


def _likely_entity(card: Card) -> Optional[str]:
    """Name the entity a researcher most likely wants to count.

    That is the most aggregated one -- the entity with the fewest instances,
    which sits furthest from the row and so distorts most when ignored.
    """
    candidates = dict((k, v) for k, v in card.grain.entity_counts.items()
                      if k not in (card.grain.unit, card.grain.unit + "s"))
    if not candidates:
        return None
    return min(candidates, key=lambda k: candidates[k]).rstrip("s")


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def render(card: Card) -> str:
    """Render the full briefing as plain text."""
    lines: List[str] = []
    a = lines.append

    a("")
    a("  " + card.title)
    provenance = []
    if card.archetype_id:
        provenance.append("archetype " + card.archetype_id)
    if card.dataset_version is not None:
        provenance.append("dataset version {0}".format(card.dataset_version))
    if card.schema_hash:
        provenance.append("schema " + card.schema_hash[:12])
    if card.derived:
        provenance.append("DERIVED -- no card published")
    if provenance:
        a("  " + " | ".join(provenance))
    a("")

    a("  GRAIN")
    if card.grain.known:
        a("     " + (card.grain.statement or "One row per {0}.".format(card.grain.unit)))
        counts = []
        if card.grain.rows:
            counts.append("{0:,} rows".format(card.grain.rows))
        for name, n in sorted(card.grain.entity_counts.items()):
            counts.append("{0:,} {1}".format(n, name))
        if counts:
            a("     " + " | ".join(counts))
        if card.has_dedupe_key:
            a("     Group by {0} for per-entity statistics.".format(card.grain.dedupe_key))
    else:
        a("     Unknown -- no card published for this dataset.")
    a("")

    a("  FIELDS")
    lines.extend(_field_table(card))
    a("")

    warnings = _warnings(card)
    for title, body in warnings:
        a("  !  " + title)
        lines.extend(_wrap(body))
        a("")

    if card.excluded:
        a("  NOT IN THIS ARCHETYPE")
        for item in card.excluded:
            lines.extend(_wrap(item, indent="     "))
        a("")

    a("  Local data is SYNTHETIC. Numbers you see here are not results.")
    a("")
    return "\n".join(lines)


def render_summary(card: Card) -> str:
    """One-line summary, for use as context in a prompt or a log line."""
    bits = [card.title]
    if card.grain.known and card.grain.statement:
        bits.append(card.grain.statement)
    bits.append("{0} fields".format(len(card.leaves)))
    if not card.has_dedupe_key and card.grain.known:
        bits.append("no dedupe key")
    return " | ".join(bits)


# Every caveat is shown when a researcher asks about one analysis; the full
# listing shows a few and says how many were held back, so the important ones
# are not lost in a wall of text.
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


def render_full(card: Card) -> str:
    """The dataset briefing followed by the catalogue verdicts."""
    return render(card) + "\n" + render_catalogue(card)
