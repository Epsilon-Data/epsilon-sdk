"""Validated plans and reproducible, bounded synthetic preview operations.

No generated models or researcher-authored Python are imported by this runner.
The portable source attached to an artifact uses the very same compute function.
"""
import ast
import csv
import hashlib
import inspect
import io
from collections import OrderedDict
from threading import RLock

from sdk import catalogue
from sdk.workbench.errors import PublicError
from sdk.profile import profile_project, MIN_CELL
from sdk.workbench.security import safe_path

SUPPORTED = {"describe", "composition", "cross_tab", "trend"}
TITLES = {"describe": "Dataset description", "composition": "Record composition by group",
          "cross_tab": "Cross-tabulation of records", "trend": "Record counts over time"}
SUMMARIES = {
    "describe": "Record counts by field: numeric bands, coarse date periods and categorical groups, with small groups withheld.",
    "composition": "Record counts for permitted group and outcome combinations. Hidden groups and percentages are excluded.",
    "cross_tab": "Record counts across two permitted categorical fields, with small groups and complementary cells withheld.",
    "trend": "Record counts over the coarsest permitted date period. Shifted synthetic dates do not establish real-world trends.",
}
MAX_BYTES = 256 * 1024 * 1024
ENGINE_VERSION = "1"
_digests = OrderedDict()
_digest_lock = RLock()


def input_fingerprint(project_dir):
    paths = [safe_path(project_dir, "generated/" + name) for name in ("archetype.json", "data.csv")]
    result = []
    for path in paths:
        stat = path.stat()
        if stat.st_size > MAX_BYTES:
            raise PublicError("This file exceeds the local preview size limit (256 MB).")
        result.append((str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(result)


def remember_digest(fingerprint, digest):
    # Only filesystem identities and hashes are retained, never dataset bytes.
    with _digest_lock:
        _digests[fingerprint] = digest
        _digests.move_to_end(fingerprint)
        while len(_digests) > 128:
            _digests.popitem(last=False)


def input_digest(project_dir):
    fingerprint = input_fingerprint(project_dir)
    with _digest_lock:
        cached = _digests.get(fingerprint)
    return cached or load_inputs(project_dir)[0]


def _compute(rows, spec):
    """Count synthetic records; return only the displayed part of each table."""
    from collections import Counter
    from datetime import datetime
    import math

    threshold = max(10, int(spec["min_cell"]))
    analysis, fields = spec["analysis"], spec["fields"]
    names = ((fields.get("by"), fields.get("outcome")) if analysis == "composition"
             else (fields.get("rows"), fields.get("cols")))
    counters = {}
    descriptors = spec.get("descriptors", [])
    if analysis == "describe":
        counters = {field["path"]: Counter() for field in descriptors}
    else:
        counters["result"] = Counter()

    def period(value, bucket):
        if not value:
            return "Missing"
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return "Invalid date"
        if bucket == "year":
            return str(value.year)
        if bucket == "quarter":
            return "%04d Q%d" % (value.year, (value.month - 1) // 3 + 1)
        if bucket == "day":
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m")

    for index, row in enumerate(rows):
        if index >= 1000000:
            raise ValueError("This local preview is limited to one million records.")
        if analysis == "describe":
            for descriptor in descriptors:
                value = row.get(descriptor["path"]) or "Missing"
                if descriptor["type"] in ("integer", "number") and value != "Missing":
                    try:
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError()
                        lower = math.floor(number / 10) * 10
                        value = "%s to < %s" % (lower, lower + 10)
                    except (ValueError, OverflowError):
                        value = "Invalid number"
                elif descriptor["type"] in ("date", "timestamp"):
                    value = period(value if value != "Missing" else "", descriptor.get("bucket", "year"))
                # Long strings are not useful grouping labels and may carry
                # free text; never reproduce them in a preview artifact.
                value = str(value) if len(str(value)) <= 100 else "Long values (grouped)"
                counters[descriptor["path"]][value] += 1
        elif analysis in ("composition", "cross_tab"):
            names = (fields["by"], fields["outcome"]) if analysis == "composition" else (fields["rows"], fields["cols"])
            values = tuple(str(row.get(name) or "Missing") for name in names)
            if any(len(value) > 100 for value in values):
                raise ValueError("Long free-text labels cannot be used in a preview table.")
            counters["result"][values] += 1
        elif analysis == "trend":
            counters["result"][period(row.get(fields["time"]), fields.get("bucket", "year"))] += 1
        else:
            raise ValueError("This analysis is not supported by the preview engine.")
        if any(len(counter) > 10000 for counter in counters.values()):
            raise ValueError("Too many groups for a bounded local preview. Choose coarser fields.")

    tables = []
    for name, counts in counters.items():
        shown = [(key, count) for key, count in counts.most_common(30) if count >= threshold]
        hidden = len(counts) - len(shown)
        # With a known record total, a single hidden group can be recovered.
        # Withhold a second group too. Do not return hidden labels or counts.
        if hidden == 1 and shown:
            shown.pop()
            hidden += 1
        if analysis in ("composition", "cross_tab"):
            columns = list(names) + ["records"]
            data = [dict(zip(columns, list(key) + [count])) for key, count in shown]
            labels = [" / ".join(key) for key, _ in shown]
        else:
            columns = ["group", "records"]
            if analysis == "trend":
                shown.sort(key=lambda item: item[0])
            data = [{"group": key, "records": count} for key, count in shown]
            labels = [str(key) for key, _ in shown]
        tables.append({"name": name, "columns": columns, "rows": data,
                       "withheld_groups": hidden,
                       "chart": {"labels": labels, "values": [count for _, count in shown]}})
    return {"synthetic": True, "unit": "record", "min_cell": threshold, "tables": tables,
            "policy": "local-preview-v1",
            "notes": ["Synthetic development output; not findings about real people.",
                      "No result total or percentages are released. Hidden groups are excluded, with complementary suppression when needed.",
                      "This local policy is not TRE output approval and does not assess inference across repeated queries."]}


def load_inputs(project_dir):
    fingerprint = input_fingerprint(project_dir)
    paths = [safe_path(project_dir, "generated/archetype.json"), safe_path(project_dir, "generated/data.csv")]
    blobs = []
    for path in paths:
        with path.open("rb") as stream:
            blob = stream.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise PublicError("This file exceeds the local preview size limit (256 MB).")
        blobs.append(blob)
    if fingerprint != input_fingerprint(project_dir):
        raise PublicError("The input files changed while reading them. Retry after the download or edit completes.")
    digest = hashlib.sha256(blobs[0])
    digest.update(b"\0")
    digest.update(blobs[1])
    signature = digest.hexdigest()
    remember_digest(fingerprint, signature)
    return signature, blobs[1]


def match_for(profile, analysis, fields=None):
    if analysis not in catalogue.SPECS_BY_KEY:
        raise PublicError("Unknown analysis. Choose an operation from the catalogue.")
    match = catalogue.SPECS_BY_KEY[analysis].evaluate(profile)
    if not match.feasible:
        raise PublicError(" ".join(match.blockers))
    if fields:
        try:
            choices = {}
            for key, value in fields.items():
                if key not in catalogue.PARAM_ROLES:
                    if key not in match.params or value != match.params[key]:
                        raise catalogue.OverrideError("Derived parameters cannot be overridden.")
                else:
                    choices[key] = value
            match = catalogue.override(profile, match, choices)
        except (catalogue.OverrideError, TypeError):
            raise PublicError("The selected fields do not meet this analysis's requirements.")
        if not match.feasible:
            raise PublicError("The selected fields make this analysis infeasible. Choose coarser fields.")
    if analysis not in SUPPORTED:
        raise PublicError("This method requires an additional reviewed execution implementation.")
    return match


def make_plan(project_dir, analysis, fields=None, *, profile=None, signature=None):
    # Check path confinement before the profiler reads project files.
    signature = signature or input_digest(project_dir)
    safe_path(project_dir, "project.yml", must_exist=False)
    profile = profile or profile_project(str(project_dir))
    match = match_for(profile, analysis, fields)
    descriptors = []
    for leaf in profile.all_leaves():
        if not all(part.isidentifier() and not part.startswith("__") for part in leaf.path.split(".")):
            raise PublicError("The archetype contains a field path that cannot be used safely in generated code.")
        if leaf.is_numeric or leaf.is_discrete or leaf.is_temporal:
            bucket = next((name for name in ("year", "quarter", "month", "day") if name in leaf.releasable_as), "year")
            descriptors.append({"path": leaf.path, "type": leaf.type, "bucket": bucket})
    bindings = {key: value for key, value in match.params.items() if key in catalogue.PARAM_ROLES}
    compute_fields = dict(bindings)
    if analysis == "trend":
        temporal = profile.leaf(bindings["time"])
        compute_fields["bucket"] = next((name for name in ("year", "quarter", "month", "day") if name in temporal.releasable_as), "year")
    spec = {"analysis": analysis, "fields": compute_fields, "min_cell": max(MIN_CELL, profile.min_cell),
            "descriptors": descriptors[:100]}
    code = render_code(spec)
    return {"analysis": analysis, "fields": bindings, "title": TITLES[analysis],
            "summary": SUMMARIES[analysis], "warnings": match.warnings,
            "unit": match.unit, "input_digest": signature, "spec": spec, "code": code,
            "engine_version": ENGINE_VERSION, "dataset_id": profile.dataset_id,
            "archetype_id": profile.archetype_id, "schema_hash": profile.schema_hash,
            "dataset_version": profile.dataset_version}


def render_code(spec):
    source = ("# Epsilon synthetic preview. Run from the project directory.\n"
              "# This output is for method development, not TRE release approval.\n"
              "import csv\nimport json\n\n" + inspect.getsource(_compute) +
              "\nSPEC = " + repr(spec) + "\n\n"
              "def main(data_path='generated/data.csv'):\n"
              "    with open(data_path, newline='', encoding='utf-8-sig') as stream:\n"
              "        return _compute(csv.DictReader(stream), SPEC)\n\n"
              "if __name__ == '__main__':\n"
              "    print(json.dumps(main(), indent=2))\n")
    ast.parse(source)
    return source


def run_plan(project_dir, plan, profile=None):
    signature, blob = load_inputs(project_dir)
    fresh = make_plan(project_dir, plan["analysis"], plan["fields"], profile=profile, signature=signature)
    if (signature != plan["input_digest"] or fresh["input_digest"] != signature or
            fresh["spec"] != plan["spec"] or fresh["code"] != plan["code"]):
        raise PublicError("The dataset, archetype or analysis changed. Create and review a new plan.")
    reader = csv.DictReader(io.StringIO(blob.decode("utf-8-sig"), newline=""))
    result = _compute(reader, fresh["spec"])
    return {"title": plan["title"], "analysis": plan["analysis"], "plan_id": plan["id"],
            "code": fresh["code"], "code_digest": hashlib.sha256(fresh["code"].encode()).hexdigest(),
            "input_digest": signature, "engine_version": ENGINE_VERSION,
            "dataset_id": fresh["dataset_id"], "archetype_id": fresh["archetype_id"],
            "schema_hash": fresh["schema_hash"], "dataset_version": fresh["dataset_version"],
            "result": result}
