"""
Render a Dataset Profile, and what can be computed from it, as one briefing.

Pure formatting over sdk.profile and sdk.catalogue -- no network, no model, no
API key. `epsilon explain` works on a freshly initialised project with nothing
configured, which is deliberate: onboarding must not depend on the copilot
being set up, and the verdicts shown here are the same ones the agent gets.
"""
from __future__ import annotations

from typing import List, Optional

from sdk.profile import Leaf, Profile
from sdk.catalogue import Match, evaluate

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


def _field_table(profile: Profile) -> List[str]:
    rows = []
    for leaf in profile.all_leaves():
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


def _warnings(profile: Profile) -> List[str]:
    """Every reason a researcher might get a wrong-but-runnable answer."""
    out = []

    if not profile.has_dedupe_key:
        out.append(("NO ENTITY KEY",
                    "Identifiers are stripped at projection, so rows cannot be "
                    "grouped back to a person or a case. Per-entity quantities "
                    "-- prevalence, a mean per entity, counts per entity -- are "
                    "NOT computable from this archetype, however the analysis "
                    "is written."))

    for leaf in profile.aggregate_only_leaves():
        allowed = ", ".join(leaf.releasable_as) or "aggregates only"
        out.append(("AGGREGATE ONLY",
                    "{0} is released as {1}. Raw values will not clear output "
                    "review.".format(leaf.path, allowed)))

    for leaf in profile.all_leaves():
        for caveat in leaf.caveats:
            out.append(("MEASURED: " + leaf.path, caveat))

    for caveat in profile.caveats:
        out.append(("NOTE", caveat))

    return out


def render(profile: Profile) -> str:
    """Render the full briefing as plain text."""
    lines: List[str] = []
    a = lines.append

    a("")
    a("  " + profile.title)
    provenance = []
    if profile.archetype_id:
        provenance.append("archetype " + profile.archetype_id)
    if profile.dataset_version is not None:
        provenance.append("dataset version {0}".format(profile.dataset_version))
    if profile.schema_hash:
        provenance.append("schema " + profile.schema_hash[:12])
    if provenance:
        a("  " + " | ".join(provenance))
    a("")

    a("  GRAIN")
    if profile.grain.rows is not None:
        a("     One row per {0}. {1:,} rows.".format(
            profile.grain.label, profile.grain.rows))
    if not profile.has_dedupe_key:
        a("     No key groups rows back to an entity, so per-entity figures")
        a("     are not computable from this archetype.")
    a("")

    a("  FIELDS")
    lines.extend(_field_table(profile))
    a("")

    warnings = _warnings(profile)
    for title, body in warnings:
        a("  !  " + title)
        lines.extend(_wrap(body))
        a("")

    a("  Local data is SYNTHETIC. Numbers you see here are not results.")
    a("")
    return "\n".join(lines)


def render_summary(profile: Profile) -> str:
    """One-line summary, for use as context in a prompt or a log line."""
    bits = [profile.title, "{0} fields".format(len(profile.leaves))]
    if profile.grain.rows is not None:
        bits.append("{0:,} rows".format(profile.grain.rows))
    if not profile.has_dedupe_key:
        bits.append("no entity key")
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


def render_catalogue(profile: Profile) -> str:
    """The full deterministic listing: what this dataset supports, and what not."""
    matches = evaluate(profile)
    feasible = [m for m in matches if m.feasible]
    blocked = [m for m in matches if not m.feasible]

    out = ["", "  " + profile.title, ""]
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


def render_full(profile: Profile) -> str:
    """The dataset briefing followed by the catalogue verdicts."""
    return render(profile) + "\n" + render_catalogue(profile)
