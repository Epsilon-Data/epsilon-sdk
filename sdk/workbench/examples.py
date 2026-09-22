"""Curated, schema-validated examples. Browsing never executes notebook Python.

The bounded reader counts permitted fields only. Notebook grouping helpers are
shared with this reader; parity tests check the pandas code against its tables.
Only displayed aggregates enter the small, process-local preview cache.
"""
import ast
import copy
import csv
import hashlib
import inspect
import json
import math
from collections import Counter, OrderedDict
from datetime import datetime
from threading import RLock

from sdk.workbench import analysis, starters
from sdk.workbench.errors import Conflict, NotFound, PublicError
from sdk.workbench.security import safe_metadata, safe_path

VERSION = "1"
MAX_GROUPS = 10000


def group_label(value):
    value = str(value) if value is not None else ""
    if len(value) > 60 or any(ord(c) < 32 for c in value):
        return "Long text (grouped)"
    return value or "Missing"


def band_key(value, width):
    try:
        number = float(value)
        if math.isfinite(number) and abs(number / width) < 1e12:
            return math.floor(number / width)
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def year_key(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).year
    except (TypeError, ValueError, OverflowError):
        return None


def label(path):
    name = path.rsplit(".", 1)[-1].replace("_", " ")
    return name.upper() if name.lower() in ("bmi", "icd", "hdl", "ldl") else name.capitalize()


def band_width(leaf):
    try:
        low, high = map(float, leaf.value_range)
        target = (high - low) / 8
        if not math.isfinite(target) or target <= 0:
            return 1
        scale = 10 ** math.floor(math.log10(target))
        width = next(n * scale for n in (1, 2, 5, 10) if n * scale >= target)
        return width if width >= 1e-9 else 1e-9
    except (TypeError, ValueError, OverflowError):
        return 1


def definitions(profile):
    """Offer only examples whose methods and fields the catalogue permits."""
    allowed = {f["path"] for f in safe_metadata(profile)["fields"]}
    leaves = [leaf for leaf in profile.all_leaves() if leaf.path in allowed]
    numeric = [leaf for leaf in leaves if leaf.is_numeric]
    discrete = [leaf for leaf in leaves if leaf.is_discrete]
    result = []

    def distribution(leaf):
        starters.bindings(profile, "describe", {"field": leaf.path})
        return {"kind": "bands" if leaf.is_numeric else "category", "field": leaf.path,
                **({"width": band_width(leaf)} if leaf.is_numeric else {})}

    def add(key, title, question, learn, series, panels):
        result.append({"id": key, "title": title, "question": question, "learn": learn,
                       "series": series, "panels": panels, "level": "Getting started",
                       "fields": list(dict.fromkeys(path for item in series for name, path in item.items()
                                                    if name in ("field", "rows", "cols")))})

    try:
        if numeric:
            chosen = numeric[:2]
            title = "Explore measurements" if len(chosen) == 2 else "Explore " + label(chosen[0].path).lower()
            panels = [{"series": i, "chart": "bar", "title": label(leaf.path) + " distribution"} for i, leaf in enumerate(chosen)]
            if len(panels) == 1:
                panels.append({"series": 0, "chart": "line", "title": "The same bands as a line"})
            add("measurements", title, "How are the measurements distributed across records?",
                ["Read a distribution using numeric bands.", "Adjust the band width and compare the charts."],
                [distribution(leaf) for leaf in chosen], panels)
    except PublicError:
        pass
    try:
        chosen = starters.bindings(profile, "cross_tab")
        if set(chosen.values()) <= allowed:
            left, right = chosen["rows"], chosen["cols"]
            add("compare-groups", "Compare " + label(left).lower() + " and " + label(right).lower(),
                "Which combinations of these categories appear in the records?",
                ["Build a cross-tabulation of two categories.", "Read the same counts as bars and a heatmap."],
                [{"kind": "pairs", "rows": left, "cols": right}],
                [{"series": 0, "chart": "bar", "title": "Category combinations"},
                 {"series": 0, "chart": "heatmap", "title": "Compare the combinations"}])
    except PublicError:
        pass
    try:
        chosen = starters.bindings(profile, "trend")
        leaf = profile.leaf(chosen["time"])
        if leaf.path in allowed and "year" in leaf.releasable_as:
            add("dates", "Explore records over time", "How do record counts vary between synthetic years?",
                ["Group permitted dates into years.", "Compare a bar chart with a line chart; gaps stay visible."],
                [{"kind": "years", "field": leaf.path}],
                [{"series": 0, "chart": "bar", "title": "Records by year"},
                 {"series": 0, "chart": "line", "title": "The same counts over time"}])
    except PublicError:
        pass
    if len(result) < 3 and discrete:
        try:
            leaf = discrete[0]
            add("categories", "Explore " + label(leaf.path).lower(),
                "How are records divided between these categories?",
                ["Compare counts between categories.", "See how bars and a pie chart present the same groups."],
                [distribution(leaf)],
                [{"series": 0, "chart": "bar", "title": "Compare category counts"},
                 {"series": 0, "chart": "pie", "title": "Composition of displayed groups"}])
        except PublicError:
            pass
    return result


def _cells(root, profile, example):
    model = safe_path(root, "generated/models.py", must_exist=False)
    loader = ("from generated.models import create_dataset\n\ndataset = create_dataset()\ndata = pd.DataFrame(dataset.records)"
              if model.exists() else "data = pd.read_csv('generated/data.csv', dtype=str, keep_default_na=False)")
    kinds = {spec["kind"] for spec in example["series"]}
    imports = ("import math\n" if "bands" in kinds else "") + ("from datetime import datetime\n" if "years" in kinds else "")
    sources = [("markdown", "# " + example["title"] + "\n\n" + example["question"] +
                "\n\nRun all cells from top to bottom. Edit the field names or grouping below, then rerun. "
                "These are synthetic record counts for method development, not findings about real people. "
                "Small groups are omitted; this is not TRE output approval."),
               ("code", imports + "import pandas as pd\nimport matplotlib.pyplot as plt\nfrom IPython.display import display\n\n" + loader + "\n"
                "data.columns = data.columns.str.lstrip('\\ufeff')\n")]
    helpers = "\n".join(inspect.getsource(fn) for fn, uses in ((group_label, {"category", "pairs"}),
                                                            (band_key, {"bands"}), (year_key, {"years"})) if kinds & uses)
    sources.append(("code", "# Grouping rules used by this example.\n" + helpers))
    sources.append(("code", f"MIN_CELL = {max(10, profile.min_cell)}\n\ndef visible_counts(counts):\n"
                    "    # Display at most 20 groups, withholding small groups and their labels.\n"
                    "    shown = counts[counts >= MIN_CELL].iloc[:20].copy()\n"
                    "    if len(counts) - len(shown) == 1 and not shown.empty:\n"
                    "        shown = shown.drop(shown.idxmin())  # Complementary suppression.\n"
                    "    return shown\n"))
    for index, spec in enumerate(example["series"]):
        name = f"counts_{index + 1}"
        kind = spec["kind"]
        if kind == "bands":
            source = (f"field = {spec['field']!r}\nband_width = {spec['width']!r}  # Edit to change the grouping.\n"
                      "bands = data[field].map(lambda value: band_key(value, band_width)).dropna()\n"
                      f"{name} = bands.astype(int).value_counts().sort_index()\n"
                      f"if not {name}.empty:\n"
                      f"    if {name}.index.max() - {name}.index.min() >= 10000:\n"
                      "        raise ValueError('Choose wider bands for this field.')\n"
                      f"    {name} = {name}.reindex(range({name}.index.min(), {name}.index.max() + 1), fill_value=0)\n"
                      f"{name}.index = [f'{{i * band_width:g}} to < {{(i + 1) * band_width:g}}' for i in {name}.index]\n")
        elif kind == "category":
            source = f"field = {spec['field']!r}\n{name} = data[field].map(group_label).value_counts().sort_index()\n"
        elif kind == "pairs":
            source = (f"row_field = {spec['rows']!r}\ncolumn_field = {spec['cols']!r}\n"
                      "groups = data[[row_field, column_field]].apply(lambda column: column.map(group_label))\n"
                      f"{name} = groups.groupby([row_field, column_field], sort=True).size()\n")
        else:
            source = (f"date_field = {spec['field']!r}\n"
                      "years = data[date_field].map(year_key).dropna().astype(int)\n"
                      f"{name} = years.value_counts().sort_index()\n"
                      f"if not {name}.empty:\n"
                      f"    {name} = {name}.reindex(range({name}.index.min(), {name}.index.max() + 1), fill_value=0)\n")
        source += (f"\nshown_{index + 1} = visible_counts({name})\n"
                   f"display(shown_{index + 1}.rename('Records').to_frame())\n"
                   f"print('Groups withheld:', len({name}) - len(shown_{index + 1}))\n")
        sources.append(("code", source))
    for panel in example["panels"]:
        number, chart = panel["series"] + 1, panel["chart"]
        name, shown = f"counts_{number}", f"shown_{number}"
        plot = f"{shown}.plot.barh(ax=ax, color='#1481F1')\nax.invert_yaxis()\nax.set_xlabel('Synthetic records')"
        if chart == "pie":
            plot = (f"{shown}.plot.pie(ax=ax, autopct=None, colors=['#1481F1', '#9FCBF9', '#014FE9', '#C5D3E0', '#3B3B3B'])\n"
                    "ax.set_ylabel('')  # Displayed groups only; no percentages or hidden slices.")
        elif chart == "line":
            plot = (f"visible = {name}.index.isin({shown}.index)\n"
                    f"ax.plot(range(len({name})), {name}.where(visible), marker='o', color='#1481F1')\n"
                    "positions = [i for i, keep in enumerate(visible) if keep]\n"
                    f"ax.set_xticks(positions, [str({name}.index[i]) for i in positions], rotation=45, ha='right')")
        elif chart == "heatmap":
            plot = (f"matrix = {shown}.unstack()  # Hidden combinations stay blank, never zero.\n"
                    "image = ax.imshow(matrix.to_numpy(dtype=float), cmap='Blues', aspect='auto')\n"
                    "ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=45, ha='right')\n"
                    "ax.set_yticks(range(len(matrix.index)), matrix.index)\n"
                    "for row in range(len(matrix.index)):\n"
                    "    for col in range(len(matrix.columns)):\n"
                    "        value = matrix.iloc[row, col]\n"
                    "        if pd.notna(value):\n"
                    "            ax.text(col, row, str(int(value)), ha='center', va='center',\n"
                    "                    color='white' if value > matrix.max().max() / 2 else '#202020')\n"
                    "fig.colorbar(image, ax=ax, label='Synthetic records')")
        source = (f"# {panel['title']}\nif {shown}.empty:\n"
                  "    print('No groups meet the minimum size. Try coarser grouping.')\nelse:\n"
                  "    fig, ax = plt.subplots(figsize=(8, 4))\n" +
                  "\n".join("    " + line for line in plot.splitlines()) +
                  f"\n    ax.set_title({panel['title']!r})\n" +
                  ("    ax.set_ylabel('Synthetic records')\n" if chart == "line" else "") +
                  "    plt.tight_layout()\n    plt.show()\n")
        sources.append(("code", source))
    sources.append(("markdown", "## Make it your own\n\n- Change a field or grouping and rerun.\n"
                    "- Select **Use with AI** on a code cell to review what you share, then ask for help adapting it.\n"
                    "- Export the notebook to keep the source. Outputs stay local.\n\n"
                    "Invalid numeric values and dates are excluded. Long category labels are grouped. "
                    "Comparisons count records, not unique people. Dates may be shifted. "
                    "Suppression here does not assess inference across repeated queries."))
    cells = [{"id": "example-cell-" + str(i + 1), "kind": kind, "source": source, "output": None}
             for i, (kind, source) in enumerate(sources)]
    for cell in cells:
        if cell["kind"] == "code":
            ast.parse(cell["source"])
    return cells


def _tables(root, example, min_cell):
    counters = [Counter() for _ in example["series"]]
    with safe_path(root, "generated/data.csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not set(example["fields"]) <= set(reader.fieldnames or []):
            raise PublicError("The projection fields changed. Initialize the dataset again before previewing.")
        for index, row in enumerate(reader):
            if index >= 1000000:
                raise PublicError("Example previews support up to one million records. Copy the code to work in the notebook.")
            for spec, counts in zip(example["series"], counters):
                kind = spec["kind"]
                if kind == "bands":
                    key = band_key(row.get(spec["field"]), spec["width"])
                elif kind == "years":
                    key = year_key(row.get(spec["field"]))
                elif kind == "pairs":
                    key = (group_label(row.get(spec["rows"])), group_label(row.get(spec["cols"])))
                else:
                    key = group_label(row.get(spec["field"]))
                if key is not None:
                    counts[key] += 1
                if len(counts) > MAX_GROUPS:
                    raise PublicError("There are too many groups for an example preview. Copy the code and choose coarser grouping.")
    tables = []
    for spec, counts in zip(example["series"], counters):
        if spec["kind"] in ("years", "bands") and counts:
            if max(counts) - min(counts) >= MAX_GROUPS:
                raise PublicError("Choose wider bands for this field in your own copy.")
            counts.update({key: 0 for key in range(min(counts), max(counts) + 1)})
        ordered = sorted(counts)
        shown = [key for key in ordered if counts[key] >= min_cell][:20]
        if len(counts) - len(shown) == 1 and shown:
            shown.remove(min(shown, key=counts.get))
        def display_key(key):
            if spec["kind"] == "bands":
                width = spec["width"]
                return f"{key * width:g} to < {(key + 1) * width:g}"
            return " / ".join(key) if isinstance(key, tuple) else str(key)
        rows = [{"group": display_key(key), "records": counts[key],
                 **({"row": key[0], "column": key[1]} if isinstance(key, tuple) else {})} for key in shown]
        tables.append({"name": label(spec.get("field", spec.get("rows", ""))),
                       "columns": ["group", "records"], "rows": rows,
                       "withheld_groups": len(counts) - len(shown),
                       "chart": {"labels": [row["group"] for row in rows], "values": [row["records"] for row in rows],
                                 "positions": [ordered.index(key) for key in shown]}})
    return tables


class Examples:
    def __init__(self, bench):
        self.bench = bench
        self.cache = OrderedDict()
        self.lock = RLock()

    def catalogue(self, pid):
        return definitions(self.bench.profile(pid))

    def detail(self, pid, eid, preview=True):
        root = self.bench.project(pid)["path"]
        profile = self.bench.profile(pid)
        example = next((item for item in definitions(profile) if item["id"] == eid), None)
        if example is None:
            raise NotFound("This example is not available for the dataset's current fields.")
        fingerprint = analysis.input_fingerprint(root)
        cells = _cells(root, profile, example)
        provenance = {"dataset": profile.title, "dataset_id": profile.dataset_id,
                      "dataset_version": profile.dataset_version, "schema_hash": profile.schema_hash,
                      "synthetic": True, "template_version": VERSION, "min_cell": max(10, profile.min_cell)}
        version = hashlib.sha256(json.dumps([provenance, fingerprint, cells], sort_keys=True).encode()).hexdigest()
        result = dict(example, cells=cells, version=version, provenance=provenance)
        if not preview:
            return result
        with self.lock:
            cached = self.cache.get(version)
        if cached is not None:
            return dict(result, preview=copy.deepcopy(cached))
        try:
            tables = _tables(root, example, max(10, profile.min_cell))
            if fingerprint != analysis.input_fingerprint(root):
                raise Conflict("The synthetic data changed while the preview was prepared. Reload the example.")
            output = {"status": "ready", "tables": tables}
        except PublicError as exc:
            if isinstance(exc, Conflict):
                raise
            output = {"status": "unavailable", "message": str(exc)}
        except (OSError, UnicodeError, csv.Error):
            output = {"status": "unavailable", "message": "The synthetic file could not be read. Check the dataset in Data."}
        if output["status"] == "ready":
            with self.lock:
                self.cache[version] = output
                while len(self.cache) > 8:
                    self.cache.popitem(last=False)
        return dict(result, preview=copy.deepcopy(output))

    def clone(self, pid, eid, version, request_id):
        example = self.detail(pid, eid, preview=False)
        if example["version"] != version:
            raise Conflict("The dataset or example changed. Reload the example before making a copy.")
        book = self.bench.store.copy_example(pid, example, request_id)
        self.bench.audit(pid, "example.copied", {"example_id": eid, "notebook_id": book["id"]})
        return book
