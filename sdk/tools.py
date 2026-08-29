"""
The tools the copilot agent drives.

Everything the agent knows about a project it learns by calling one of these,
for the same reason a coding agent reads a file instead of recalling it: a
model that guesses a feasibility verdict, a column's cardinality, or the
contents of main.py will eventually guess wrong, and in a TRE a wrong guess
becomes an attested result.

Two limits are enforced here rather than asked for in a prompt:

* No tool ever returns a record. `profile_field` returns aggregates over the
  local synthetic projection, with rare levels withheld.
* No tool reaches outside the project directory, and none writes to
  generated/, which the SDK owns.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from sdk import catalogue as catalogue_mod
from sdk import checks as checks_mod
from sdk import explain as explain_mod
from sdk import snippets as snippets_mod
from sdk.profile import Profile
from sdk.llm.base import ToolSpec

# Tool output goes straight into the model's context. A runaway result would
# push the conversation out of the window, so every tool truncates.
MAX_RESULT_CHARS = 8000
RUN_TIMEOUT_SECONDS = 120

# Directories the agent may never write into.
PROTECTED_DIRS = ("generated",)


class ToolError(Exception):
    """A tool refused, with a reason the model should read and act on."""


@dataclass
class Tool:
    spec: ToolSpec
    run: Callable[..., str]
    # Shown to the user as the agent works, like a build log line.
    summarise: Optional[Callable[[Dict[str, Any], str], str]] = None


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    """Cap a tool result, and say loudly that what remains is incomplete.

    A quiet truncation is worse than a failure. A model handed the first 8,000
    characters of a 41,000-character result will summarise it as though it were
    whole, filling the gaps from whatever it read earlier -- which is how
    fabricated figures end up presented as the output of a run.
    """
    if len(text) <= limit:
        return text
    return (
        "[INCOMPLETE RESULT] Only the first {0} of {1} characters are shown. "
        "The rest was NOT computed away -- it exists but you cannot see it. Do "
        "not summarise, total, or report any field that does not appear below, "
        "and do not fill the gap from earlier context. Tell the researcher the "
        "output was too large and narrow the request.\n\n{2}\n\n"
        "[END OF VISIBLE PORTION -- {3} characters not shown]"
    ).format(limit, len(text), text[:limit], len(text) - limit)


# How many bars are worth drawing before a chart stops being readable.
MAX_BARS = 12


def chartable(result: Any) -> Optional[Dict[str, Any]]:
    """Find a series worth drawing in an analysis result, or None.

    Reads the shapes the generated templates return. Suppressed cells are
    carried through as such rather than dropped, so a chart shows the same
    holes the table does.
    """
    if not isinstance(result, dict):
        return None

    def bars(pairs):
        shown = [(str(k), v) for k, v in pairs if v is not None][:MAX_BARS]
        held = len([1 for _k, v in pairs if v is None])
        return shown, held

    # trend: a series over periods
    if isinstance(result.get("series"), list) and result["series"]:
        pairs = [(r.get("period"), r.get("n")) for r in result["series"]]
        shown, held = bars(pairs)
        if shown:
            return {"title": "Series", "groups": [{"label": "", "pairs": shown}],
                    "held": held}

    # composition / cross_tab: a table whose last numeric column is the count
    if isinstance(result.get("table"), list) and result["table"]:
        rows = result["table"]
        keys = [k for k in rows[0] if k != "n"]
        if keys:
            group_key = keys[0]
            label_key = keys[1] if len(keys) > 1 else keys[0]
            grouped: Dict[str, List] = {}
            for r in rows:
                grouped.setdefault(str(r.get(group_key)), []).append(
                    (r.get(label_key), r.get("n")))
            groups, held = [], 0
            for label, pairs in list(grouped.items())[:6]:
                shown, h = bars(pairs)
                held += h
                if shown:
                    groups.append({"label": "{0} = {1}".format(group_key, label),
                                   "pairs": shown})
            if groups:
                return {"title": "Counts by " + group_key, "groups": groups,
                        "held": held}

    # describe: the first field with released levels
    fields = result.get("fields")
    if isinstance(fields, dict):
        for name in sorted(fields):
            entry = fields[name]
            if isinstance(entry, dict) and entry.get("top"):
                pairs = [(lvl.get("value"), lvl.get("n")) for lvl in entry["top"]]
                shown, held = bars(pairs)
                if shown:
                    return {
                        "title": "Distribution of " + name,
                        "groups": [{"label": "", "pairs": shown}],
                        "held": held + int(entry.get("levels_not_shown") or 0),
                    }
    return None


class Toolbox(object):
    """The tools bound to one project directory."""

    def __init__(self, project_dir: str, profile: Profile):
        self.project_dir = os.path.abspath(project_dir)
        self.profile = profile
        # Chartable series pulled out of whatever the last runs returned. The
        # model never authors these numbers -- they come straight from the
        # released result, so a chart cannot disagree with the table above it.
        self.charts: List[Dict[str, Any]] = []

    # -- path safety -----------------------------------------------------

    def _resolve(self, relative: str, for_write: bool = False) -> str:
        if os.path.isabs(relative):
            raise ToolError("paths must be relative to the project directory")
        full = os.path.abspath(os.path.join(self.project_dir, relative))
        if full != self.project_dir and not full.startswith(self.project_dir + os.sep):
            raise ToolError(
                "'{0}' is outside the project directory. The agent works only "
                "inside this project.".format(relative))
        if for_write:
            head = os.path.relpath(full, self.project_dir).split(os.sep)[0]
            if head in PROTECTED_DIRS:
                raise ToolError(
                    "{0}/ is generated by the SDK and must not be edited. Write "
                    "analyses under analyses/ instead.".format(head))
        return full

    # -- tools -----------------------------------------------------------

    def read_dataset(self) -> str:
        """What the dataset holds, measured from the local data."""
        return explain_mod.render(self.profile)

    def list_analyses(self) -> str:
        matches = catalogue_mod.evaluate(self.profile)
        lines = []
        for match in matches:
            lines.append("{0} [{1}] {2}".format(
                match.key, match.status, match.title))
            lines.append("    unit: {0}".format(match.unit))
            if match.params:
                lines.append("    fields: " + json.dumps(match.params))
            for blocker in match.blockers:
                lines.append("    BLOCKED: " + blocker)
            for warning in match.warnings:
                lines.append("    warning: " + warning)
            if match.unlock:
                lines.append("    unlock: " + match.unlock)
        return _truncate("\n".join(lines))

    def _spec_or_error(self, analysis):
        spec = catalogue_mod.SPECS_BY_KEY.get(analysis)
        if spec is None:
            raise ToolError("unknown analysis '{0}'. Available: {1}".format(
                analysis, ", ".join(sorted(catalogue_mod.SPECS_BY_KEY))))
        return spec

    def _clean_fields(self, match, fields):
        """Normalise the `fields` argument, which models get wrong in
        predictable ways: a list of every column, a nested {"fields": [...]},
        or a bare string. Say what this analysis actually takes."""
        if fields in (None, {}, ""):
            return None
        takes = ", ".join(sorted(match.params)) or "no parameters"
        if not isinstance(fields, dict):
            raise ToolError(
                "'fields' must be an object mapping a parameter to one field "
                "path, e.g. {{\"rows\": \"patient.gender\"}}. "
                "{0} takes: {1}. Omit 'fields' to let the matcher choose."
                .format(match.key, takes))
        cleaned = {}
        for name, value in fields.items():
            if not isinstance(value, str):
                raise ToolError(
                    "'fields.{0}' must be a single field path as a string, not "
                    "{1}. {2} takes: {3}. Omit 'fields' to let the matcher "
                    "choose.".format(name, type(value).__name__, match.key, takes))
            cleaned[name] = value
        return cleaned

    def check_analysis(self, analysis: str,
                       fields: Optional[Dict[str, str]] = None) -> str:
        """Whether one analysis is available, with the fields it would use."""
        match = self._spec_or_error(analysis).evaluate(self.profile)
        chosen = self._clean_fields(match, fields)
        if chosen:
            try:
                match = catalogue_mod.override(self.profile, match, chosen)
            except catalogue_mod.OverrideError as exc:
                raise ToolError(str(exc))
        payload = {
            "analysis": match.key,
            "status": match.status,
            "unit_of_analysis": match.unit,
            "fields": match.params,
            "blockers": match.blockers,
            "warnings": match.warnings,
            "unlock": match.unlock,
        }
        return json.dumps(payload, indent=2)

    def generate_analysis(self, analysis: str,
                          fields: Optional[Dict[str, str]] = None,
                          filename: Optional[str] = None,
                          chart: bool = False) -> str:
        match = self._spec_or_error(analysis).evaluate(self.profile)
        chosen = self._clean_fields(match, fields)
        if chosen:
            try:
                match = catalogue_mod.override(self.profile, match, chosen)
            except catalogue_mod.OverrideError as exc:
                raise ToolError(str(exc))
        if not match.feasible:
            raise ToolError(
                "'{0}' is not available for this dataset and no code will be "
                "generated for it. Reason: {1} Tell the researcher this, and "
                "offer what is available.".format(
                    analysis, " ".join(match.blockers)))
        try:
            path = snippets_mod.write(self.profile, match,
                                      project_dir=self.project_dir,
                                      filename=filename, chart=chart)
        except snippets_mod.SnippetError as exc:
            raise ToolError(str(exc))
        relative = os.path.relpath(path, self.project_dir)
        with open(path, "r", encoding="utf-8") as fh:
            code = fh.read()
        return "Wrote {0}\n\n{1}".format(relative, _truncate(code))

    def list_files(self) -> str:
        out = []
        for root, dirs, files in os.walk(self.project_dir):
            dirs[:] = [d for d in dirs if d not in checks_mod.SKIP_DIRS]
            for name in sorted(files):
                path = os.path.relpath(os.path.join(root, name), self.project_dir)
                try:
                    size = os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
                out.append("{0}  ({1:,} bytes)".format(path, size))
        return _truncate("\n".join(sorted(out)) or "(empty project)")

    def read_file(self, path: str) -> str:
        full = self._resolve(path)
        if not os.path.exists(full):
            candidate = os.path.join(snippets_mod.ANALYSES_DIR,
                                     os.path.basename(path))
            alternative = self._resolve(candidate)
            if os.path.exists(alternative):
                path, full = candidate, alternative
            else:
                raise ToolError(
                    "{0} does not exist. Call list_files to see what the "
                    "project contains.".format(path))
        if os.path.getsize(full) > MAX_RESULT_CHARS * 4:
            raise ToolError(
                "{0} is too large to read into the conversation. Use "
                "profile_field for data files.".format(path))
        try:
            with open(full, "r", encoding="utf-8") as fh:
                return _truncate(fh.read())
        except UnicodeDecodeError:
            raise ToolError("{0} is not text".format(path))

    def write_file(self, path: str, content: str) -> str:
        full = self._resolve(path, for_write=True)
        directory = os.path.dirname(full)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        existed = os.path.exists(full)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        findings = []
        if path.endswith(".py"):
            findings = checks_mod.check_source(path, content)
        note = ""
        if findings:
            note = "\n\nSubmission checks on this file:\n" + "\n".join(
                f.format() for f in findings)
            blocking = [f for f in findings if f.blocking]
            if blocking:
                note += ("\n\nThis file would block a build. Fix it before "
                         "telling the researcher it is ready.")
        return "{0} {1} ({2} bytes){3}".format(
            "Updated" if existed else "Created", path, len(content), note)

    def profile_field(self, field: str) -> str:
        """Aggregate statistics for one field of the local synthetic CSV.

        Never returns rows, and levels below the suppression threshold are
        withheld -- so this cannot become a way to read rare values out one at
        a time. What it summarises is the synthetic projection sitting on this
        machine, never a record from the real dataset.
        """
        leaf = self.profile.leaf(field)
        if leaf is None:
            raise ToolError("'{0}' is not a field. Available: {1}".format(
                field, ", ".join(sorted(self.profile.leaves))))

        csv_path = os.path.join(self.project_dir, "generated", "data.csv")
        if not os.path.exists(csv_path):
            raise ToolError("generated/data.csv does not exist; run epsilon init")

        import csv as csv_mod
        from collections import Counter
        counts = Counter()
        numeric = []
        blank = total = 0
        with open(csv_path, "r", encoding="utf-8") as fh:
            reader = csv_mod.DictReader(fh)
            if field not in (reader.fieldnames or []):
                raise ToolError(
                    "'{0}' is not a column in generated/data.csv (columns: "
                    "{1})".format(field, ", ".join(reader.fieldnames or [])))
            for row in reader:
                total += 1
                value = (row.get(field) or "").strip()
                if not value:
                    blank += 1
                    continue
                counts[value] += 1
                try:
                    numeric.append(float(value))
                except ValueError:
                    pass

        report = {
            "field": field,
            "rows": total,
            "blank": blank,
            "distinct": len(counts),
        }
        if numeric and len(numeric) == total - blank:
            numeric.sort()
            report["min"] = numeric[0]
            report["max"] = numeric[-1]
            report["mean"] = round(sum(numeric) / float(len(numeric)), 3)
            report["median"] = numeric[len(numeric) // 2]
        # Only levels above the suppression threshold, so this cannot become a
        # way to read rare values out of the data one at a time.
        threshold = self.profile.min_cell
        common = [(v, n) for v, n in counts.most_common(25) if n >= threshold]
        report["levels_above_threshold"] = [
            {"value": v, "n": n} for v, n in common]
        report["levels_suppressed"] = len(counts) - len(common)
        return json.dumps(report, indent=2)

    def run_analysis(self, module: str) -> str:
        """Execute one analysis module locally against the synthetic data."""
        relative = module if module.endswith(".py") else module.replace(".", os.sep) + ".py"
        full = self._resolve(relative)
        if not os.path.exists(full):
            # "describe.py" almost always means analyses/describe.py.
            candidate = os.path.join(snippets_mod.ANALYSES_DIR,
                                     os.path.basename(relative))
            alternative = self._resolve(candidate)
            if os.path.exists(alternative):
                relative, full = candidate, alternative
            else:
                raise ToolError(
                    "neither {0} nor {1} exists. Call list_files to see what "
                    "the project contains.".format(relative, candidate))
        dotted = os.path.splitext(os.path.relpath(full, self.project_dir))[0]
        dotted = dotted.replace(os.sep, ".")
        code = (
            "import json, sys\n"
            "sys.path.insert(0, '.')\n"
            "mod = __import__('{0}', fromlist=['main'])\n"
            "result = mod.main() if hasattr(mod, 'main') else None\n"
            "print(json.dumps(result, indent=2, default=str)"
            " if result is not None else '(no main() return value)')\n"
        ).format(dotted)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code], cwd=self.project_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=RUN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise ToolError(
                "{0} did not finish within {1} seconds".format(
                    relative, RUN_TIMEOUT_SECONDS))
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        if proc.returncode != 0:
            return _truncate("FAILED (exit {0})\n\n{1}\n{2}".format(
                proc.returncode, err, out))

        # The generated templates print JSON; if the result carries a series
        # worth drawing, hand it to the caller so the chat can render it.
        for line in (out[out.find("{"):] if "{" in out else ""), out:
            try:
                series = chartable(json.loads(line))
            except (ValueError, TypeError):
                continue
            if series:
                series["source"] = relative
                self.charts.append(series)
                # Tell the model the chart is already in front of the
                # researcher, or it points them at an .svg file instead.
                out += ("\n[A chart of this result is rendered to the "
                        "researcher automatically. Do not mention chart "
                        "files or where anything was saved.]")
                break

        return _truncate(out + (("\n[stderr]\n" + err) if err.strip() else ""))

    def run_checks(self) -> str:
        findings = checks_mod.check_project(self.project_dir)
        entry = "main.py"
        project_yml = os.path.join(self.project_dir, "project.yml")
        if os.path.exists(project_yml):
            try:
                import yaml
                with open(project_yml, "r", encoding="utf-8") as fh:
                    entry = (yaml.safe_load(fh) or {}).get("entry_point", "main.py")
            except Exception:
                pass
        findings.extend(checks_mod.check_packaging(
            self.project_dir, entry, {"generated", snippets_mod.ANALYSES_DIR}))
        if not findings:
            return "All submission checks passed."
        return _truncate(checks_mod.summarise(findings) + "\n\n" + "\n".join(
            f.format() for f in findings))


# -- schemas ---------------------------------------------------------------

_FIELDS_SCHEMA = {
    "type": "object",
    "description": "Field choices, e.g. {\"rows\": \"patient.gender\"}. "
                   "Omit to let the matcher choose.",
}


def build_tools(box: Toolbox) -> List[Tool]:
    """The toolbox as model-callable tools, with their display summaries."""
    analyses = sorted(catalogue_mod.SPECS_BY_KEY)
    fields = sorted(box.profile.leaves)

    def spec(name, description, properties=None, required=None):
        return ToolSpec(name=name, description=description, schema={
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        })

    return [
        Tool(spec("read_dataset",
                  "Read the dataset profile: the grain of a row, every granted "
                  "field with its type and access level, and the owner's "
                  "caveats. Call this first."),
             lambda: box.read_dataset(),
             lambda args, out: "read_dataset"),

        Tool(spec("list_analyses",
                  "List every analysis in the catalogue with an authoritative "
                  "feasibility verdict for this dataset, the reasons for any "
                  "refusal, and what would unlock it."),
             lambda: box.list_analyses(),
             lambda args, out: "list_analyses"),

        Tool(spec("check_analysis",
                  "Check whether one analysis is available, optionally with "
                  "specific fields. Use this before promising a researcher "
                  "anything; the verdict is authoritative and you cannot "
                  "overrule it.",
                  {"analysis": {"type": "string", "enum": analyses},
                   "fields": _FIELDS_SCHEMA},
                  ["analysis"]),
             lambda analysis, fields=None: box.check_analysis(analysis, fields),
             lambda args, out: "check_analysis({0})".format(args.get("analysis"))),

        Tool(spec("generate_analysis",
                  "Generate starter code for a feasible analysis into "
                  "analyses/. The template already applies the suppression "
                  "threshold and states the unit of analysis.",
                  {"analysis": {"type": "string", "enum": analyses},
                   "fields": _FIELDS_SCHEMA,
                   "filename": {"type": "string",
                                "description": "Bare filename, e.g. "
                                               "'table1.py'. Not a path."},
                   "chart": {"type": "boolean",
                             "description": "Also generate a chart() that "
                                            "draws the released result as SVG. "
                                            "Use this instead of writing "
                                            "plotting code by hand."}},
                  ["analysis"]),
             lambda analysis, fields=None, filename=None, chart=False:
                 box.generate_analysis(analysis, fields, filename, chart),
             lambda args, out: "generate_analysis({0})".format(args.get("analysis"))),

        Tool(spec("list_files", "List the files in the project."),
             lambda: box.list_files(),
             lambda args, out: "list_files"),

        Tool(spec("read_file", "Read a text file from the project.",
                  {"path": {"type": "string"}}, ["path"]),
             lambda path: box.read_file(path),
             lambda args, out: "read_file({0})".format(args.get("path"))),

        Tool(spec("write_file",
                  "Write a file in the project. Analysis code belongs under "
                  "analyses/. Output must be aggregated and suppressed; never "
                  "write code that prints or saves individual records.",
                  {"path": {"type": "string"},
                   "content": {"type": "string"}},
                  ["path", "content"]),
             lambda path, content: box.write_file(path, content),
             lambda args, out: "write_file({0})".format(args.get("path"))),

        Tool(spec("profile_field",
                  "Aggregate statistics for one field of the local synthetic "
                  "data: counts, distinct values, and range. Returns no rows.",
                  {"field": {"type": "string", "enum": fields}}, ["field"]),
             lambda field: box.profile_field(field),
             lambda args, out: "profile_field({0})".format(args.get("field"))),

        Tool(spec("run_analysis",
                  "Run an analysis module locally against the synthetic data "
                  "and return what main() produced, or the traceback.",
                  {"module": {"type": "string",
                              "description": "e.g. analyses/cross_tab.py"}},
                  ["module"]),
             lambda module: box.run_analysis(module),
             lambda args, out: "run_analysis({0})".format(args.get("module"))),

        Tool(spec("run_checks",
                  "Run the submission checks the coordinator will run: no raw "
                  "records released, no network, no subprocesses, "
                  "dependencies pinned, no credentials, nothing imported that "
                  "would not be packaged."),
             lambda: box.run_checks(),
             lambda args, out: "run_checks"),
    ]
