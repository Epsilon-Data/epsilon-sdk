"""Editable local notebook templates; opening a starter persists nothing."""
import ast
from textwrap import dedent

from sdk.workbench import analysis
from sdk.workbench.errors import PublicError
from sdk.workbench.security import safe_path
from sdk.workbench.store import identifier


def bindings(profile, method, fields=None):
    if method == "describe":
        analysis.match_for(profile, method)
        leaves = [leaf for leaf in profile.all_leaves() if leaf.is_numeric or leaf.is_discrete]
        if fields and (set(fields) != {"field"} or fields["field"] not in {leaf.path for leaf in leaves}):
            raise PublicError("Choose a numeric or categorical field for this starter.")
        leaf = next((leaf for leaf in leaves if leaf.path == (fields or {}).get("field")), None)
        leaf = leaf or next((leaf for leaf in leaves if leaf.is_numeric), None) or next(iter(leaves), None)
        if not leaf:
            raise PublicError("This starter needs a numeric or categorical field.")
        return {"field": leaf.path}
    return {key: value for key, value in analysis.match_for(profile, method, fields).params.items() if key in analysis.catalogue.PARAM_ROLES}


def cards(profile):
    result = []
    for method in ("describe", "composition", "cross_tab", "trend"):
        try:
            chosen = bindings(profile, method)
        except PublicError:
            continue
        title = {"describe": "Explore a variable", "composition": "Compare groups", "cross_tab": "Compare two variables", "trend": "Explore dates"}[method]
        result.append({"analysis": method, "title": title, "fields": chosen, "source": "catalogue",
                       "question": {"describe": "Inspect a distribution and adjust the grouping.", "composition": "Compare record counts between groups.", "cross_tab": "Count combinations of two categories.", "trend": "Practice grouping synthetic dates into periods."}[method]})
    return result


def notebook(project_dir, profile, method, fields=None, *, chart="bar"):
    chosen = bindings(profile, method, fields)
    if chart not in ("bar", "pie", "line"):
        raise PublicError("Choose a bar, pie or line chart for this template.")
    ordered = method == "trend" or (method == "describe" and profile.leaf(chosen["field"]).is_numeric)
    if chart == "line" and not ordered:
        raise PublicError("A line chart needs numeric bands or date periods. Choose a bar chart for categories.")
    if any(not all(part.isidentifier() and not part.startswith("__") for part in path.split(".")) for path in chosen.values()):
        raise PublicError("These fields cannot be used safely in a notebook template.")
    model = safe_path(project_dir, "generated/models.py", must_exist=False)
    if model.exists():
        loader = "from generated.models import create_dataset\n\ndataset = create_dataset()\ndata = pd.DataFrame(dataset.records)"
    else:
        loader = "# This project has no generated wrapper yet.\ndata = pd.read_csv('generated/data.csv')"
    setup = "import pandas as pd\nimport matplotlib.pyplot as plt\nfrom IPython.display import display\n\n" + loader + "\n"
    if method == "describe":
        field = chosen["field"]
        leaf = profile.leaf(field)
        source = f"field = {field!r}  # Change this to explore another field.\n"
        if leaf.is_numeric:
            source += "values = pd.to_numeric(data[field], errors='coerce')\n# Eight bands follow this variable's scale; adjust bins for your method.\ncounts = pd.cut(values, bins=8).value_counts(sort=False)\n"
        else:
            source += "counts = data[field].fillna('Missing').value_counts()\n"
        title = "Explore " + field
    elif method in ("composition", "cross_tab"):
        left, right = ("by", "outcome") if method == "composition" else ("rows", "cols")
        source = f"group = {chosen[left]!r}\ncompare = {chosen[right]!r}\n\ncounts = data.groupby([group, compare], dropna=False).size()\n"
        title = chosen[left] + " by " + chosen[right]
    else:
        leaf = profile.leaf(chosen["time"])
        bucket = next((name for name in ("year", "quarter", "month", "day") if name in leaf.releasable_as), "year")
        frequency = {"year": "Y", "quarter": "Q", "month": "M", "day": "D"}[bucket]
        source = f"date_field = {chosen['time']!r}\n# Synthetic dates may be shifted; these are practice counts.\nperiods = pd.to_datetime(data[date_field], errors='coerce', utc=True).dt.tz_localize(None).dt.to_period({frequency!r})\ncounts = periods.value_counts().sort_index()\n"
        if chart == "line":
            source += ("if not counts.empty:\n"
                       "    if counts.index[-1].ordinal - counts.index[0].ordinal > 1000:\n"
                       "        raise ValueError('Choose a coarser date interval for this chart.')\n"
                       f"    counts = counts.reindex(pd.period_range(counts.index[0], counts.index[-1], freq={frequency!r}), fill_value=0)\n")
        title = "Explore " + chosen["time"]
    display = dedent(f"""\
        # Keep small groups and their labels out of displayed count tables.
        min_cell = {max(10, profile.min_cell)}
        shown = counts[counts >= min_cell].copy()
        if len(counts) - len(shown) == 1 and not shown.empty:
            shown = shown.drop(shown.idxmin())  # Complementary suppression.
        display(shown.rename('Records').to_frame())
        if not shown.empty:
            shown.plot.bar(figsize=(8, 4), color='#1481F1')
            plt.ylabel('Synthetic records')
            plt.tight_layout()
            plt.show()
        else:
            print('No groups meet the minimum size. Try a coarser grouping.')
        """)
    if chart == "pie":
        display = display.replace("shown.plot.bar(figsize=(8, 4), color='#1481F1')", "shown.plot.pie(figsize=(6, 6), autopct='%1.1f%%' if len(shown) == len(counts) else None)\n    plt.axis('equal')")
        display = display.replace("plt.ylabel('Synthetic records')", "plt.ylabel('')")
    elif chart == "line":
        display = display.replace("shown.plot.bar(figsize=(8, 4), color='#1481F1')", "# Withheld or empty intervals break the line; only shown labels appear.\n    plt.figure(figsize=(8, 4))\n    visible = counts.index.isin(shown.index)\n    plt.plot(range(len(counts)), counts.where(visible), marker='o', color='#1481F1')\n    positions = [i for i, keep in enumerate(visible) if keep]\n    plt.xticks(positions, [str(counts.index[i]) for i in positions], rotation=45, ha='right')")
    cells = [{"kind": "markdown", "source": f"### {title}\n\nEdit the field names below, then **Run all**. These synthetic counts help you develop code; they are not research findings or approved TRE outputs."},
             {"kind": "code", "source": setup}, {"kind": "code", "source": source + "\n" + display}]
    for cell in cells:
        cell.update(id="cell-" + identifier(), output=None)
        if cell["kind"] == "code":
            ast.parse(cell["source"])
    return {"id": "draft-" + identifier(), "revision": 0, "temporary": True, "title": title[:100], "fields": chosen, "cells": cells}
